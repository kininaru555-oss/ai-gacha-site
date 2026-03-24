"""
routers/battle.py — バトル（改善版）

改善版ポイント:
- mutate系を明示的に commit / rollback
- 待機中の多重登録を防止
- マッチング時に FOR UPDATE で競合を抑制
- 復活アイテム判定を最終勝敗確定前に実施
- 3連敗ボーナス、勝利数、ログ、奪取を最終結果ベースで反映
- 「トラゴンボウル」表記を「レジェンドボール」へ統一

注意:
- 認証基盤が未導入のため、payload.user_id を使う互換APIのままです。
  本番では必ずトークン由来の user_id に置き換えてください。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from database import get_db
from helpers import (
    ensure_user,
    get_ownership,
    get_owned_card,
    battle_score,
    level_up_card_if_needed,
    update_user_level,
    steal_random_ball_if_any,
)
from models import BattleEntryRequest

router = APIRouter(tags=["battle"])

DRAW_DIFF_THRESHOLD = 4.0
WIN_EXP = 15
LOSE_EXP = 5
DRAW_EXP = 5
LOSE_STREAK_BONUS = 20


def _finalize_result_with_revive(conn, user_id: str, result: str) -> tuple[str, bool]:
    """
    最終勝敗を確定する。
    敗北時に revive_items を持っていれば1個消費して draw に変更する。
    """
    if result != "lose":
        return result, False

    user = ensure_user(conn, user_id)
    if (user.get("revive_items") or 0) <= 0:
        return result, False

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET revive_items = revive_items - 1
            WHERE user_id = %s AND revive_items > 0
            """,
            (user_id,),
        )
        if cur.rowcount == 0:
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
    カード側の戦績・EXPを最終結果に基づいて反映する。
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
        else:  # lose
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
            streak = row["lose_streak_count"] if row else 0
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
            "UPDATE users SET exp = exp + %s WHERE user_id = %s",
            (total, user_id),
        )


@router.post("/battle/entry")
def battle_entry(payload: BattleEntryRequest):
    with get_db() as conn:
        try:
            ensure_user(conn, payload.user_id)
            owner = get_ownership(conn, payload.work_id)

            if not owner or owner["owner_id"] != payload.user_id:
                raise HTTPException(status_code=400, detail="所有している作品のみバトル参加できます")

            my_card = get_owned_card(conn, payload.user_id, payload.work_id)
            if not my_card:
                raise HTTPException(status_code=404, detail="所有カードがありません")

            with conn.cursor() as cur:
                # 自分の既存待機を防止
                cur.execute(
                    "SELECT id FROM battle_queue WHERE user_id = %s FOR UPDATE",
                    (payload.user_id,),
                )
                my_wait = cur.fetchone()
                if my_wait:
                    conn.commit()
                    return {"message": "すでに対戦待機中です。次の参加者とバトルします。"}

                # 相手待機を競合しにくく取得
                cur.execute(
                    """
                    SELECT * FROM battle_queue
                    WHERE user_id != %s
                    ORDER BY id ASC
                    LIMIT 1
                    FOR UPDATE
                    """,
                    (payload.user_id,),
                )
                waiting = cur.fetchone()

                if not waiting:
                    cur.execute(
                        "INSERT INTO battle_queue(user_id, work_id) VALUES(%s, %s)",
                        (payload.user_id, payload.work_id),
                    )
                    conn.commit()
                    return {"message": "対戦待機に入りました。次の参加者とバトルします。"}

            opp_user_id = waiting["user_id"]
            opp_work_id = waiting["work_id"]
            opp_card = get_owned_card(conn, opp_user_id, opp_work_id)

            if not opp_card:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM battle_queue WHERE id = %s", (waiting["id"],))
                conn.commit()
                return {"message": "相手の待機データが無効でした。再度参加してください。"}

            score_me = battle_score(my_card)
            score_opp = battle_score(opp_card)

            if abs(score_me - score_opp) < DRAW_DIFF_THRESHOLD:
                base_me, base_opp = "draw", "draw"
                log_text = f"接戦で引き分け。A={score_me:.1f} / B={score_opp:.1f}"
            elif score_me > score_opp:
                base_me, base_opp = "win", "lose"
                log_text = f"総合力で勝利。A={score_me:.1f} / B={score_opp:.1f}"
            else:
                base_me, base_opp = "lose", "win"
                log_text = f"相手が上回り敗北。A={score_me:.1f} / B={score_opp:.1f}"

            # 復活アイテムは最終勝敗確定前に反映
            result_me, me_revived = _finalize_result_with_revive(conn, payload.user_id, base_me)
            result_opp, opp_revived = _finalize_result_with_revive(conn, opp_user_id, base_opp)

            # 片側だけ draw になるのは不自然なので相手側も draw に揃える
            if me_revived:
                result_opp = "draw"
            if opp_revived:
                result_me = "draw"

            exp_me = _reward_for_result(result_me)
            exp_opp = _reward_for_result(result_opp)

            extra = []
            if me_revived:
                extra.append("復活アイテム発動(自分)")
            if opp_revived:
                extra.append("復活アイテム発動(相手)")

            me_bonus = _apply_card_result(conn, my_card["id"], result_me, exp_me)
            opp_bonus = _apply_card_result(conn, opp_card["id"], result_opp, exp_opp)

            _apply_user_exp(conn, payload.user_id, exp_me, LOSE_STREAK_BONUS if me_bonus else 0)
            _apply_user_exp(conn, opp_user_id, exp_opp, LOSE_STREAK_BONUS if opp_bonus else 0)

            if me_bonus:
                extra.append("3敗ボーナスでEXP+20(自分)")
            if opp_bonus:
                extra.append("3敗ボーナスでEXP+20(相手)")

            ball_stolen = None
            if result_me == "win":
                ball_stolen = steal_random_ball_if_any(conn, opp_user_id, payload.user_id)
            elif result_me == "lose":
                ball_stolen = steal_random_ball_if_any(conn, payload.user_id, opp_user_id)

            if ball_stolen:
                extra.append(f"レジェンドボール奪取: {ball_stolen}")

            level_up_card_if_needed(conn, my_card["id"])
            level_up_card_if_needed(conn, opp_card["id"])
            update_user_level(conn, payload.user_id)
            update_user_level(conn, opp_user_id)

            full_log = log_text + (" / " + " / ".join(extra) if extra else "")

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO battle_logs(user_id, opponent_user_id, result, log_text, reward_exp)
                    VALUES(%s, %s, %s, %s, %s)
                    """,
                    (payload.user_id, opp_user_id, result_me, full_log, exp_me + (LOSE_STREAK_BONUS if me_bonus else 0)),
                )
                cur.execute(
                    """
                    INSERT INTO battle_logs(user_id, opponent_user_id, result, log_text, reward_exp)
                    VALUES(%s, %s, %s, %s, %s)
                    """,
                    (opp_user_id, payload.user_id, result_opp, full_log, exp_opp + (LOSE_STREAK_BONUS if opp_bonus else 0)),
                )
                cur.execute("DELETE FROM battle_queue WHERE id = %s", (waiting["id"],))

            conn.commit()
            return {
                "message": "バトルが完了しました",
                "result": result_me,
                "opponent_result": result_opp,
                "log": full_log,
                "reward_exp": exp_me + (LOSE_STREAK_BONUS if me_bonus else 0),
                "revive_triggered": me_revived,
                "streak_bonus_triggered": me_bonus,
                "stolen_legend_ball": ball_stolen,
            }
        except Exception:
            conn.rollback()
            raise


@router.get("/battle/logs/{user_id}")
def get_battle_logs(user_id: str):
    with get_db() as conn:
        ensure_user(conn, user_id)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM battle_logs
                WHERE user_id=%s
                ORDER BY id DESC
                LIMIT 50
                """,
                (user_id,),
            )
            rows = cur.fetchall()

        items = [
            {
                "id": r["id"],
                "opponent_id": r["opponent_user_id"],
                "opponent_name": r["opponent_user_id"],
                "result": r["result"],
                "log": r["log_text"],
                "reward_exp": r["reward_exp"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else "",
            }
            for r in rows
        ]

        return {"logs": items}


@router.get("/battle/ranking")
def battle_ranking(limit: int = 50):
    limit = max(1, min(limit, 100))

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
