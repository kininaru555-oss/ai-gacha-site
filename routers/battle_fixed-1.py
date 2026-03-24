"""
routers/battle_fixed.py — バトル（認証導入・排他強化・token_version対応版）

改善ポイント:
- payload.user_id を完全廃止し、認証ユーザーのみを使用
- battle_queue の UNIQUE 制約を前提に INSERT / IntegrityError で待機重複を処理
- revive_items の消費を UPDATE ... RETURNING で原子的に実施
- 対戦に使う owned_cards を FOR UPDATE でロック
- battle_logs 一覧は本人のみ取得可能
- opponent_name は users を JOIN して返却
- ランキングは win_rate を返却
- 例外処理を HTTPException / psycopg.Error / その他で分離
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from database import get_db
from helpers import (
    battle_score,
    level_up_card_if_needed,
    steal_random_ball_if_any,
    update_user_level,
)
from security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["battle"])

DRAW_DIFF_THRESHOLD = 4.0
WIN_EXP = 15
LOSE_EXP = 5
DRAW_EXP = 5
LOSE_STREAK_BONUS = 20


class BattleEntryPayload(BaseModel):
    work_id: int = Field(..., ge=1)


def _ensure_user_exists(conn, user_id: str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT user_id, is_active
            FROM users
            WHERE user_id = %s
            """,
            (user_id,),
        )
        user = cur.fetchone()

    if not user:
        raise HTTPException(status_code=404, detail="ユーザーが存在しません")
    if not bool(user.get("is_active", True)):
        raise HTTPException(status_code=403, detail="このユーザーアカウントは無効です")
    return user


def _ensure_user_owns_work(conn, user_id: str, work_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT work_id, owner_id
            FROM ownership
            WHERE work_id = %s
            """,
            (work_id,),
        )
        row = cur.fetchone()

    if not row or row["owner_id"] != user_id:
        raise HTTPException(status_code=400, detail="所有している作品のみバトル参加できます")


def _get_owned_card_for_update(conn, user_id: str, work_id: int) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM owned_cards
            WHERE user_id = %s
              AND work_id = %s
            ORDER BY id ASC
            LIMIT 1
            FOR UPDATE
            """,
            (user_id, work_id),
        )
        card = cur.fetchone()

    if not card:
        raise HTTPException(status_code=404, detail="所有カードがありません")
    return card


def _get_waiting_opponent_for_update(conn, user_id: str) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM battle_queue
            WHERE user_id <> %s
            ORDER BY id ASC
            LIMIT 1
            FOR UPDATE
            """,
            (user_id,),
        )
        return cur.fetchone()


def _enqueue_current_user(conn, user_id: str, work_id: int) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO battle_queue(user_id, work_id)
                VALUES(%s, %s)
                """,
                (user_id, work_id),
            )
        return True
    except psycopg.IntegrityError:
        return False


def _consume_revive_if_needed(conn, user_id: str, result: str) -> tuple[str, bool]:
    """
    敗北時に revive_items を原子的に 1 消費し、draw に変更する。
    """
    if result != "lose":
        return result, False

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET revive_items = revive_items - 1
            WHERE user_id = %s
              AND revive_items > 0
            RETURNING revive_items
            """,
            (user_id,),
        )
        row = cur.fetchone()

    if not row:
        return result, False
    return "draw", True


def _reward_for_result(result: str) -> int:
    if result == "win":
        return WIN_EXP
    if result == "draw":
        return DRAW_EXP
    return LOSE_EXP


def _apply_card_result(conn, card_id: int, result: str, exp_gain: int) -> bool:
    """
    カード側の戦績・EXP を最終結果に基づいて反映する。
    3連敗ボーナスが発動したら True を返す。
    """
    bonus_triggered = False

    with conn.cursor() as cur:
        if result == "win":
            cur.execute(
                """
                UPDATE owned_cards
                SET exp = exp + %s,
                    total_exp = COALESCE(total_exp, 0) + %s,
                    battle_count = COALESCE(battle_count, 0) + 1,
                    win_count = COALESCE(win_count, 0) + 1,
                    lose_streak_count = 0
                WHERE id = %s
                """,
                (exp_gain, exp_gain, card_id),
            )
        elif result == "draw":
            cur.execute(
                """
                UPDATE owned_cards
                SET exp = exp + %s,
                    total_exp = COALESCE(total_exp, 0) + %s,
                    battle_count = COALESCE(battle_count, 0) + 1
                WHERE id = %s
                """,
                (exp_gain, exp_gain, card_id),
            )
        else:
            cur.execute(
                """
                UPDATE owned_cards
                SET exp = exp + %s,
                    total_exp = COALESCE(total_exp, 0) + %s,
                    battle_count = COALESCE(battle_count, 0) + 1,
                    lose_streak_count = COALESCE(lose_streak_count, 0) + 1
                WHERE id = %s
                RETURNING lose_streak_count
                """,
                (exp_gain, exp_gain, card_id),
            )
            row = cur.fetchone()
            streak = int(row["lose_streak_count"]) if row and row.get("lose_streak_count") is not None else 0

            if streak >= 3:
                cur.execute(
                    """
                    UPDATE owned_cards
                    SET lose_streak_count = 0,
                        exp = exp + %s,
                        total_exp = COALESCE(total_exp, 0) + %s
                    WHERE id = %s
                    """,
                    (LOSE_STREAK_BONUS, LOSE_STREAK_BONUS, card_id),
                )
                bonus_triggered = True

    return bonus_triggered


def _apply_user_exp(conn, user_id: str, exp_gain: int, bonus: int = 0) -> None:
    total = exp_gain + bonus
    if total <= 0:
        return

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET exp = exp + %s
            WHERE user_id = %s
            """,
            (total, user_id),
        )


def _build_base_results(score_me: float, score_opp: float) -> tuple[str, str, str]:
    if abs(score_me - score_opp) < DRAW_DIFF_THRESHOLD:
        return (
            "draw",
            "draw",
            f"接戦で引き分け。A={score_me:.1f} / B={score_opp:.1f}",
        )

    if score_me > score_opp:
        return (
            "win",
            "lose",
            f"総合力で勝利。A={score_me:.1f} / B={score_opp:.1f}",
        )

    return (
        "lose",
        "win",
        f"相手が上回り敗北。A={score_me:.1f} / B={score_opp:.1f}",
    )


def _insert_battle_log(
    conn,
    *,
    user_id: str,
    opponent_user_id: str,
    result: str,
    log_text: str,
    reward_exp: int,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO battle_logs(user_id, opponent_user_id, result, log_text, reward_exp)
            VALUES(%s, %s, %s, %s, %s)
            """,
            (user_id, opponent_user_id, result, log_text, reward_exp),
        )


@router.post("/battle/entry")
def battle_entry(
    payload: BattleEntryPayload,
    current_user=Depends(get_current_user),
):
    user_id = current_user["user_id"]

    with get_db() as conn:
        try:
            _ensure_user_exists(conn, user_id)
            _ensure_user_owns_work(conn, user_id, payload.work_id)
            my_card = _get_owned_card_for_update(conn, user_id, payload.work_id)

            waiting = _get_waiting_opponent_for_update(conn, user_id)

            if not waiting:
                inserted = _enqueue_current_user(conn, user_id, payload.work_id)
                conn.commit()
                if inserted:
                    return {"message": "対戦待機に入りました。次の参加者とバトルします。"}
                return {"message": "すでに対戦待機中です。次の参加者とバトルします。"}

            opp_user_id = waiting["user_id"]
            opp_work_id = waiting["work_id"]

            _ensure_user_exists(conn, opp_user_id)
            _ensure_user_owns_work(conn, opp_user_id, opp_work_id)
            opp_card = _get_owned_card_for_update(conn, opp_user_id, opp_work_id)

            score_me = float(battle_score(my_card))
            score_opp = float(battle_score(opp_card))
            base_me, base_opp, base_log_text = _build_base_results(score_me, score_opp)

            result_me, me_revived = _consume_revive_if_needed(conn, user_id, base_me)
            result_opp, opp_revived = _consume_revive_if_needed(conn, opp_user_id, base_opp)

            if me_revived:
                result_opp = "draw"
            if opp_revived:
                result_me = "draw"

            exp_me = _reward_for_result(result_me)
            exp_opp = _reward_for_result(result_opp)

            extra_for_me: list[str] = []
            extra_for_opp: list[str] = []

            if me_revived:
                extra_for_me.append("復活アイテム発動(自分)")
                extra_for_opp.append("復活アイテム発動(相手)")
            if opp_revived:
                extra_for_me.append("復活アイテム発動(相手)")
                extra_for_opp.append("復活アイテム発動(自分)")

            me_bonus = _apply_card_result(conn, my_card["id"], result_me, exp_me)
            opp_bonus = _apply_card_result(conn, opp_card["id"], result_opp, exp_opp)

            _apply_user_exp(conn, user_id, exp_me, LOSE_STREAK_BONUS if me_bonus else 0)
            _apply_user_exp(conn, opp_user_id, exp_opp, LOSE_STREAK_BONUS if opp_bonus else 0)

            if me_bonus:
                extra_for_me.append("3敗ボーナスでEXP+20(自分)")
                extra_for_opp.append("3敗ボーナスでEXP+20(相手)")
            if opp_bonus:
                extra_for_me.append("3敗ボーナスでEXP+20(相手)")
                extra_for_opp.append("3敗ボーナスでEXP+20(自分)")

            stolen_for_me = None
            stolen_for_opp = None

            if result_me == "win":
                stolen_for_me = steal_random_ball_if_any(conn, opp_user_id, user_id)
                stolen_for_opp = stolen_for_me
            elif result_me == "lose":
                stolen_for_opp = steal_random_ball_if_any(conn, user_id, opp_user_id)
                stolen_for_me = stolen_for_opp

            if stolen_for_me:
                if result_me == "win":
                    extra_for_me.append(f"レジェンドボール奪取: {stolen_for_me}")
                    extra_for_opp.append(f"レジェンドボール喪失: {stolen_for_opp}")
                else:
                    extra_for_me.append(f"レジェンドボール喪失: {stolen_for_me}")
                    extra_for_opp.append(f"レジェンドボール奪取: {stolen_for_opp}")

            level_up_card_if_needed(conn, my_card["id"])
            level_up_card_if_needed(conn, opp_card["id"])
            update_user_level(conn, user_id)
            update_user_level(conn, opp_user_id)

            full_log_me = base_log_text + (" / " + " / ".join(extra_for_me) if extra_for_me else "")
            full_log_opp = base_log_text + (" / " + " / ".join(extra_for_opp) if extra_for_opp else "")

            _insert_battle_log(
                conn,
                user_id=user_id,
                opponent_user_id=opp_user_id,
                result=result_me,
                log_text=full_log_me,
                reward_exp=exp_me + (LOSE_STREAK_BONUS if me_bonus else 0),
            )
            _insert_battle_log(
                conn,
                user_id=opp_user_id,
                opponent_user_id=user_id,
                result=result_opp,
                log_text=full_log_opp,
                reward_exp=exp_opp + (LOSE_STREAK_BONUS if opp_bonus else 0),
            )

            with conn.cursor() as cur:
                cur.execute("DELETE FROM battle_queue WHERE id = %s", (waiting["id"],))

            conn.commit()
            return {
                "message": "バトルが完了しました",
                "result": result_me,
                "opponent_result": result_opp,
                "log": full_log_me,
                "reward_exp": exp_me + (LOSE_STREAK_BONUS if me_bonus else 0),
                "score_me": score_me,
                "score_opp": score_opp,
                "base_result": base_me,
                "final_result": result_me,
                "opponent_user_id": opp_user_id,
                "opponent_work_id": opp_work_id,
                "revive_triggered": me_revived,
                "opponent_revive_triggered": opp_revived,
                "streak_bonus_triggered": me_bonus,
                "opponent_streak_bonus_triggered": opp_bonus,
                "stolen_legend_ball": stolen_for_me,
            }

        except HTTPException:
            conn.rollback()
            raise
        except psycopg.Error:
            conn.rollback()
            logger.exception("battle_entry database error user_id=%s work_id=%s", user_id, payload.work_id)
            raise HTTPException(status_code=500, detail="バトル処理中にデータベースエラーが発生しました")
        except Exception:
            conn.rollback()
            logger.exception("battle_entry unexpected error user_id=%s work_id=%s", user_id, payload.work_id)
            raise HTTPException(status_code=500, detail="バトル処理中に予期しないエラーが発生しました")


@router.get("/battle/logs/me")
def get_my_battle_logs(
    limit: int = Query(default=50, ge=1, le=100),
    current_user=Depends(get_current_user),
):
    user_id = current_user["user_id"]

    with get_db() as conn:
        _ensure_user_exists(conn, user_id)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    bl.id,
                    bl.opponent_user_id,
                    COALESCE(u.creator_name, u.user_id, bl.opponent_user_id) AS opponent_name,
                    bl.result,
                    bl.log_text,
                    bl.reward_exp,
                    bl.created_at
                FROM battle_logs bl
                LEFT JOIN users u
                  ON u.user_id = bl.opponent_user_id
                WHERE bl.user_id = %s
                ORDER BY bl.id DESC
                LIMIT %s
                """,
                (user_id, limit),
            )
            rows = cur.fetchall()

    items = [
        {
            "id": r["id"],
            "opponent_id": r["opponent_user_id"],
            "opponent_name": r["opponent_name"],
            "result": r["result"],
            "log": r["log_text"],
            "reward_exp": r["reward_exp"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else "",
        }
        for r in rows
    ]

    return {"logs": items}


@router.get("/battle/ranking")
def battle_ranking(limit: int = Query(default=50, ge=1, le=100)):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    oc.id AS card_id,
                    oc.user_id,
                    oc.work_id,
                    oc.rarity,
                    oc.level,
                    oc.exp,
                    COALESCE(oc.total_exp, 0) AS total_exp,
                    COALESCE(oc.win_count, 0) AS win_count,
                    COALESCE(oc.battle_count, 0) AS battle_count,
                    CASE
                        WHEN COALESCE(oc.battle_count, 0) = 0 THEN 0
                        ELSE ROUND((COALESCE(oc.win_count, 0)::numeric / oc.battle_count::numeric) * 100, 2)
                    END AS win_rate,
                    oc.hp,
                    oc.atk,
                    oc.def,
                    oc.spd,
                    oc.luk,
                    oc.is_legend,
                    w.title,
                    w.creator_name,
                    w.image_url,
                    w.video_url
                FROM owned_cards oc
                JOIN works w
                  ON w.id = oc.work_id
                JOIN ownership o
                  ON o.work_id = oc.work_id
                 AND o.owner_id = oc.user_id
                ORDER BY
                    CASE
                        WHEN COALESCE(oc.battle_count, 0) = 0 THEN 0
                        ELSE (COALESCE(oc.win_count, 0)::numeric / oc.battle_count::numeric)
                    END DESC,
                    COALESCE(oc.win_count, 0) DESC,
                    oc.level DESC,
                    COALESCE(oc.total_exp, 0) DESC,
                    COALESCE(oc.battle_count, 0) DESC,
                    oc.id ASC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

    items = []
    rank = 1
    for row in rows:
        items.append(
            {
                "rank": rank,
                "card_id": row["card_id"],
                "user_id": row["user_id"],
                "work_id": row["work_id"],
                "title": row["title"],
                "creator_name": row["creator_name"],
                "image_url": row["image_url"],
                "video_url": row["video_url"],
                "rarity": row["rarity"],
                "level": row["level"],
                "exp": row["exp"],
                "total_exp": row["total_exp"],
                "win_count": row["win_count"],
                "battle_count": row["battle_count"],
                "win_rate": float(row["win_rate"]),
                "hp": row["hp"],
                "atk": row["atk"],
                "def": row["def"],
                "spd": row["spd"],
                "luk": row["luk"],
                "is_legend": bool(row["is_legend"]),
            }
        )
        rank += 1

    return {"items": items}
