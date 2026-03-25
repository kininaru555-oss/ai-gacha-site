"""
routers/battle.py — バトル（HPターン制・revive修正・競合防止版）

仕様準拠:
- revive: users.revive_items を参照・消費（無限復活防止）
- battle_queue: FOR UPDATE SKIP LOCKED 使用
- REVIVE_BONUS_EXP = 30
- 変更は最小限、仕様整合を最優先
"""

from __future__ import annotations

import logging
import random
from typing import Any, Optional

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from database import get_db
from helpers import (
    level_up_card_if_needed,
    steal_random_ball_if_any,
    update_user_level,
)
from security import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["battle"])

MAX_TURNS = 5
WIN_EXP = 15
LOSE_EXP = 5
DRAW_EXP = 5
REVIVE_BONUS_EXP = 30
LOSE_STREAK_BONUS = 20
DRAW_HP_RATIO_DELTA = 0.05


class BattleEntryPayload(BaseModel):
    work_id: int = Field(..., ge=1)


# ====================== 内部関数（変更なし） ======================
# _ensure_user_exists, _ensure_user_owns_work, _get_owned_card_for_update,
# _get_waiting_opponent_for_update, _reward_for_result, _calc_turn_damage,
# _decide_turn_order, _run_turn_battle, _apply_card_result, _apply_user_exp,
# _insert_battle_log は前回と同じです（省略せず全部含めています）

def _ensure_user_exists(conn, user_id: str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SELECT user_id, is_active FROM users WHERE user_id = %s", (user_id,))
        user = cur.fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="ユーザーが存在しません")
    if not bool(user.get("is_active", True)):
        raise HTTPException(status_code=403, detail="このユーザーアカウントは無効です")
    return user


def _ensure_user_owns_work(conn, user_id: str, work_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT work_id, owner_id FROM ownership WHERE work_id = %s", (work_id,))
        row = cur.fetchone()
    if not row or row["owner_id"] != user_id:
        raise HTTPException(status_code=400, detail="所有している作品のみバトル参加できます")


def _get_owned_card_for_update(conn, user_id: str, work_id: int) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM owned_cards WHERE user_id = %s AND work_id = %s ORDER BY id ASC LIMIT 1 FOR UPDATE",
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
            SELECT * FROM battle_queue
            WHERE user_id <> %s
            ORDER BY id ASC LIMIT 1 FOR UPDATE SKIP LOCKED
            """,
            (user_id,),
        )
        return cur.fetchone()


def _enqueue_current_user(conn, user_id: str, work_id: int) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO battle_queue(user_id, work_id) VALUES(%s, %s)", (user_id, work_id))
        return True
    except psycopg.IntegrityError:
        return False


def _reward_for_result(result: str) -> int:
    if result == "win": return WIN_EXP
    if result == "draw": return DRAW_EXP
    return LOSE_EXP


def _calc_turn_damage(attacker: dict, defender: dict) -> tuple[int, bool]:
    atk = int(attacker.get("atk") or 0)
    defense = int(defender.get("defense") or 0)
    luk = int(attacker.get("luk") or 0)
    random_bonus = random.randint(-3, 3)
    damage = max(1, int(atk - defense * 0.5 + random_bonus))
    crit_rate = min(50.0, 5.0 + luk * 0.2)
    is_critical = random.random() < (crit_rate / 100.0)
    if is_critical:
        damage = max(1, int(damage * 1.5))
    return damage, is_critical


def _decide_turn_order(card_a: dict, card_b: dict) -> tuple[dict, dict, str]:
    if card_a.get("spd", 0) != card_b.get("spd", 0):
        return (card_a, card_b, "A") if card_a.get("spd", 0) > card_b.get("spd", 0) else (card_b, card_a, "B")
    if card_a.get("luk", 0) != card_b.get("luk", 0):
        return (card_a, card_b, "A") if card_a.get("luk", 0) > card_b.get("luk", 0) else (card_b, card_a, "B")
    return (card_a, card_b, "A") if random.random() < 0.5 else (card_b, card_a, "B")


def _run_turn_battle(card_me: dict, card_opp: dict, my_user_id: str, opp_user_id: str, conn) -> dict[str, Any]:
    state = {
        "A": {"card_id": card_me["id"], "max_hp": int(card_me.get("hp") or 1), "current_hp": int(card_me.get("hp") or 1), "revive_used": False},
        "B": {"card_id": card_opp["id"], "max_hp": int(card_opp.get("hp") or 1), "current_hp": int(card_opp.get("hp") or 1), "revive_used": False},
        "turn_logs": [],
    }
    first, second, first_key = _decide_turn_order(card_me, card_opp)
    second_key = "B" if first_key == "A" else "A"
    side_to_user = {"A": my_user_id, "B": opp_user_id}

    def maybe_revive(side_key: str) -> bool:
        side = state[side_key]
        if side["current_hp"] > 0 or side["revive_used"]:
            return False
        user_id = side_to_user[side_key]
        with conn.cursor() as cur:
            cur.execute("SELECT revive_items FROM users WHERE user_id = %s FOR UPDATE", (user_id,))
            row = cur.fetchone()
            if not row or int(row.get("revive_items") or 0) < 1:
                return False
            cur.execute("UPDATE users SET revive_items = revive_items - 1 WHERE user_id = %s", (user_id,))
        side["current_hp"] = max(1, int(side["max_hp"] * 0.3))
        side["revive_used"] = True
        state["turn_logs"].append(f"{side_key}がrevive発動！ HP30%回復（残り revive_items -1）")
        return True

    for turn in range(1, MAX_TURNS + 1):
        state["turn_logs"].append(f"Turn {turn} 開始")
        dmg1, crit1 = _calc_turn_damage(first, second)
        state[second_key]["current_hp"] -= dmg1
        msg1 = f"{first_key}の攻撃: {dmg1}ダメージ"
        if crit1: msg1 += "（クリティカル）"
        msg1 += f" / {second_key} HP={max(0, state[second_key]['current_hp'])}"
        state["turn_logs"].append(msg1)

        if state[second_key]["current_hp"] <= 0:
            if not maybe_revive(second_key): break

        dmg2, crit2 = _calc_turn_damage(second, first)
        state[first_key]["current_hp"] -= dmg2
        msg2 = f"{second_key}の攻撃: {dmg2}ダメージ"
        if crit2: msg2 += "（クリティカル）"
        msg2 += f" / {first_key} HP={max(0, state[first_key]['current_hp'])}"
        state["turn_logs"].append(msg2)

        if state[first_key]["current_hp"] <= 0:
            if not maybe_revive(first_key): break

    hp_a = state["A"]["current_hp"]
    hp_b = state["B"]["current_hp"]

    if hp_a <= 0 and hp_b <= 0:
        result_a = result_b = "draw"
    elif hp_a <= 0:
        result_a, result_b = "lose", "win"
    elif hp_b <= 0:
        result_a, result_b = "win", "lose"
    else:
        ratio_a = hp_a / max(1, state["A"]["max_hp"])
        ratio_b = hp_b / max(1, state["B"]["max_hp"])
        if abs(ratio_a - ratio_b) < DRAW_HP_RATIO_DELTA:
            result_a = result_b = "draw"
        else:
            result_a, result_b = ("win", "lose") if ratio_a > ratio_b else ("lose", "win")

    state.update({
        "result_a": result_a, "result_b": result_b,
        "final_hp_a": max(0, hp_a), "final_hp_b": max(0, hp_b),
        "revive_a": state["A"]["revive_used"], "revive_b": state["B"]["revive_used"],
    })
    return state


def _apply_card_result(conn, card_id: int, result: str, exp_gain: int, revive_bonus: int = 0) -> bool:
    total_gain = exp_gain + revive_bonus
    bonus_triggered = False
    with conn.cursor() as cur:
        if result == "win":
            cur.execute("""UPDATE owned_cards SET exp = exp + %s, total_exp = COALESCE(total_exp, 0) + %s,
                           battle_count = COALESCE(battle_count, 0) + 1, win_count = COALESCE(win_count, 0) + 1,
                           lose_streak_count = 0 WHERE id = %s""", (total_gain, total_gain, card_id))
        elif result == "draw":
            cur.execute("""UPDATE owned_cards SET exp = exp + %s, total_exp = COALESCE(total_exp, 0) + %s,
                           battle_count = COALESCE(battle_count, 0) + 1 WHERE id = %s""", (total_gain, total_gain, card_id))
        else:
            cur.execute("""UPDATE owned_cards SET exp = exp + %s, total_exp = COALESCE(total_exp, 0) + %s,
                           battle_count = COALESCE(battle_count, 0) + 1, lose_streak_count = COALESCE(lose_streak_count, 0) + 1
                           WHERE id = %s RETURNING lose_streak_count""", (total_gain, total_gain, card_id))
            row = cur.fetchone()
            streak = int(row["lose_streak_count"]) if row else 0
            if streak >= 3:
                cur.execute("""UPDATE owned_cards SET lose_streak_count = 0, exp = exp + %s, total_exp = COALESCE(total_exp, 0) + %s
                               WHERE id = %s""", (LOSE_STREAK_BONUS, LOSE_STREAK_BONUS, card_id))
                bonus_triggered = True
    return bonus_triggered


def _apply_user_exp(conn, user_id: str, exp_gain: int, revive_bonus: int = 0, lose_bonus: int = 0) -> None:
    total = exp_gain + revive_bonus + lose_bonus
    if total <= 0: return
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET exp = exp + %s WHERE user_id = %s", (total, user_id))


def _insert_battle_log(conn, user_id: str, opponent_user_id: str, result: str, log_text: str, reward_exp: int, work_id: int, opponent_work_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO battle_logs(user_id, opponent_user_id, result, log_text, reward_exp, work_id, opponent_work_id)
               VALUES(%s, %s, %s, %s, %s, %s, %s)""",
            (user_id, opponent_user_id, result, log_text, reward_exp, work_id, opponent_work_id),
        )


@router.post("/battle/entry")
def battle_entry(payload: BattleEntryPayload, current_user=Depends(get_current_user)):
    user_id = current_user["user_id"]

    with get_db() as conn:
        try:
            _ensure_user_exists(conn, user_id)
            _ensure_user_owns_work(conn, user_id, payload.work_id)
            my_card = _get_owned_card_for_update(conn, user_id, payload.work_id)

            waiting = _get_waiting_opponent_for_update(conn, user_id)

            if not waiting:
                inserted = _enqueue_current_user(conn, user_id, payload.work_id)
                if inserted:
                    conn.commit()
                    return {"message": "対戦待機に入りました。次の参加者とバトルします。"}
                else:
                    conn.rollback()                                   # ← 安全のため明示 rollback
                    return {"message": "すでに対戦待機中です。次の参加者とバトルします。"}

            opp_user_id = waiting["user_id"]
            opp_work_id = waiting["work_id"]

            _ensure_user_exists(conn, opp_user_id)
            _ensure_user_owns_work(conn, opp_user_id, opp_work_id)
            opp_card = _get_owned_card_for_update(conn, opp_user_id, opp_work_id)

            battle = _run_turn_battle(my_card, opp_card, user_id, opp_user_id, conn)

            final_me = battle["result_a"]
            final_opp = battle["result_b"]

            exp_me = _reward_for_result(final_me)
            exp_opp = _reward_for_result(final_opp)

            revive_bonus_me = REVIVE_BONUS_EXP if battle["revive_a"] else 0
            revive_bonus_opp = REVIVE_BONUS_EXP if battle["revive_b"] else 0

            extra_me: list[str] = []
            extra_opp: list[str] = []

            if battle["revive_a"]:
                extra_me.append("revive発動（自分）")
                extra_opp.append("revive発動（相手）")
            if battle["revive_b"]:
                extra_me.append("revive発動（相手）")
                extra_opp.append("revive発動（自分）")

            me_bonus = _apply_card_result(conn, my_card["id"], final_me, exp_me, revive_bonus_me)
            opp_bonus = _apply_card_result(conn, opp_card["id"], final_opp, exp_opp, revive_bonus_opp)

            _apply_user_exp(conn, user_id, exp_me, revive_bonus_me, LOSE_STREAK_BONUS if me_bonus else 0)
            _apply_user_exp(conn, opp_user_id, exp_opp, revive_bonus_opp, LOSE_STREAK_BONUS if opp_bonus else 0)

            if me_bonus:
                extra_me.append("3連敗ボーナスEXP+20")
            if opp_bonus:
                extra_opp.append("3連敗ボーナスEXP+20")

            # ====================== 修正ポイント1: ボール奪取ログの対称性確保 ======================
            stolen_info = None
            if final_me == "win":
                stolen_info = steal_random_ball_if_any(conn, winner_user_id=user_id, loser_user_id=opp_user_id)
                if stolen_info:
                    extra_me.append(f"レジェンドボール奪取: {stolen_info}")
                    extra_opp.append(f"レジェンドボール喪失: {stolen_info}")
            elif final_me == "lose":
                stolen_info = steal_random_ball_if_any(conn, winner_user_id=opp_user_id, loser_user_id=user_id)
                if stolen_info:
                    extra_me.append(f"レジェンドボール喪失: {stolen_info}")
                    extra_opp.append(f"レジェンドボール奪取: {stolen_info}")
            # ======================================================================================

            level_up_card_if_needed(conn, my_card["id"])
            level_up_card_if_needed(conn, opp_card["id"])
            update_user_level(conn, user_id)
            update_user_level(conn, opp_user_id)

            my_log = " / ".join(battle["turn_logs"] + extra_me)
            opp_log = " / ".join(battle["turn_logs"] + extra_opp)

            _insert_battle_log(conn, user_id, opp_user_id, final_me, my_log,
                               exp_me + revive_bonus_me + (LOSE_STREAK_BONUS if me_bonus else 0),
                               payload.work_id, opp_work_id)
            _insert_battle_log(conn, opp_user_id, user_id, final_opp, opp_log,
                               exp_opp + revive_bonus_opp + (LOSE_STREAK_BONUS if opp_bonus else 0),
                               opp_work_id, payload.work_id)

            with conn.cursor() as cur:
                cur.execute("DELETE FROM battle_queue WHERE id = %s", (waiting["id"],))

            conn.commit()

            return {
                "message": "バトル完了",
                "your_result": final_me,
                "opponent_result": final_opp,
                "your_final_hp": battle["final_hp_a"],
                "opponent_final_hp": battle["final_hp_b"],
                "your_revive_used": battle["revive_a"],
                "opponent_revive_used": battle["revive_b"],
                "your_reward_exp": exp_me + revive_bonus_me + (LOSE_STREAK_BONUS if me_bonus else 0),
                "log": battle["turn_logs"],
                "stolen_ball_for_you": stolen_info if final_me == "win" else None,
            }

        except HTTPException:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            logger.exception("battle_entry error user_id=%s work_id=%s", user_id, payload.work_id)
            raise HTTPException(status_code=500, detail="バトル処理中にエラーが発生しました")


@router.get("/battle/logs/me")
def get_my_battle_logs(current_user=Depends(get_current_user), limit: int = Query(50, ge=1, le=100)):
    user_id = current_user["user_id"]
    with get_db() as conn:
        try:
            _ensure_user_exists(conn, user_id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, opponent_user_id, result, log_text, reward_exp,
                           work_id, opponent_work_id, created_at
                    FROM battle_logs WHERE user_id = %s ORDER BY id DESC LIMIT %s
                    """,
                    (user_id, limit),
                )
                rows = cur.fetchall() or []
            return {"count": len(rows), "logs": [dict(row) for row in rows]}
        except HTTPException:
            raise
        except Exception:
            logger.exception("get_my_battle_logs error user_id=%s", user_id)
            raise HTTPException(status_code=500, detail="バトル履歴の取得中にエラーが発生しました")


@router.get("/battle/ranking")
def battle_ranking(limit: int = Query(50, ge=1, le=100)):
    with get_db() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT oc.id AS owned_card_id, oc.user_id, oc.work_id,
                           COALESCE(oc.win_count, 0) AS win_count,
                           COALESCE(oc.battle_count, 0) AS battle_count,
                           COALESCE(oc.total_exp, 0) AS total_exp
                    FROM owned_cards oc
                    JOIN users u ON u.user_id = oc.user_id
                    WHERE COALESCE(u.is_active, TRUE) = TRUE
                    ORDER BY COALESCE(oc.win_count, 0) DESC,
                             (COALESCE(oc.win_count, 0)::float / GREATEST(COALESCE(oc.battle_count, 0), 1)) DESC,
                             COALESCE(oc.total_exp, 0) DESC,
                             oc.id ASC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall() or []

            ranking = []
            for idx, row in enumerate(rows, start=1):
                ranking.append({
                    "rank": idx,
                    "owned_card_id": row["owned_card_id"],
                    "user_id": row["user_id"],
                    "work_id": row["work_id"],
                    "win_count": row["win_count"],
                    "battle_count": row["battle_count"],
                    "win_rate": round((row["win_count"] / max(row["battle_count"], 1)) * 100, 2),
                    "total_exp": row["total_exp"],
                })
            return {"count": len(ranking), "ranking": ranking}
        except Exception:
            logger.exception("battle_ranking error")
            raise HTTPException(status_code=500, detail="ランキング取得中にエラーが発生しました")
