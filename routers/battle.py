"""
routers/battle.py — バトル
"""
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


@router.post("/battle/entry")
def battle_entry(payload: BattleEntryRequest):
    with get_db() as conn:
        ensure_user(conn, payload.user_id)
        owner = get_ownership(conn, payload.work_id)

        if not owner or owner["owner_id"] != payload.user_id:
            raise HTTPException(status_code=400, detail="所有している作品のみバトル参加できます")

        my_card = get_owned_card(conn, payload.user_id, payload.work_id)
        if not my_card:
            raise HTTPException(status_code=404, detail="所有カードがありません")

        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM battle_queue
                WHERE user_id != %s
                ORDER BY id ASC
                LIMIT 1
            """, (payload.user_id,))
            waiting = cur.fetchone()

        if not waiting:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO battle_queue(user_id, work_id)
                    VALUES(%s, %s)
                """, (payload.user_id, payload.work_id))
            return {"message": "対戦待機に入りました。次の参加者とバトルします。"}

        opp_user_id = waiting["user_id"]
        opp_work_id = waiting["work_id"]
        opp_card = get_owned_card(conn, opp_user_id, opp_work_id)

        if not opp_card:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM battle_queue WHERE id=%s", (waiting["id"],))
            return {"message": "相手の待機データが無効でした。再度参加してください。"}

        score_me = battle_score(my_card)
        score_opp = battle_score(opp_card)

        if abs(score_me - score_opp) < 4:
            result_me, result_opp = "draw", "draw"
            exp_me, exp_opp = 5, 5
            log_text = f"接戦で引き分け。A={score_me:.1f} / B={score_opp:.1f}"
        elif score_me > score_opp:
            result_me, result_opp = "win", "lose"
            exp_me, exp_opp = 15, 5
            log_text = f"総合力で勝利。A={score_me:.1f} / B={score_opp:.1f}"
        else:
            result_me, result_opp = "lose", "win"
            exp_me, exp_opp = 5, 15
            log_text = f"相手が上回り敗北。A={score_me:.1f} / B={score_opp:.1f}"

        extra = []

        # 基本EXP加算 + 累計EXP + バトル回数
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE owned_cards
                SET exp = exp + %s,
                    total_exp = COALESCE(total_exp, 0) + %s,
                    battle_count = COALESCE(battle_count, 0) + 1
                WHERE id=%s
            """, (exp_me, exp_me, my_card["id"]))

            cur.execute("""
                UPDATE owned_cards
                SET exp = exp + %s,
                    total_exp = COALESCE(total_exp, 0) + %s,
                    battle_count = COALESCE(battle_count, 0) + 1
                WHERE id=%s
            """, (exp_opp, exp_opp, opp_card["id"]))

            cur.execute("""
                UPDATE users
                SET exp = exp + %s
                WHERE user_id=%s
            """, (exp_me, payload.user_id))

            cur.execute("""
                UPDATE users
                SET exp = exp + %s
                WHERE user_id=%s
            """, (exp_opp, opp_user_id))

            if result_me == "win":
                cur.execute("""
                    UPDATE owned_cards
                    SET win_count = COALESCE(win_count, 0) + 1
                    WHERE id=%s
                """, (my_card["id"],))
            elif result_opp == "win":
                cur.execute("""
                    UPDATE owned_cards
                    SET win_count = COALESCE(win_count, 0) + 1
                    WHERE id=%s
                """, (opp_card["id"],))

        # 連敗カウント・3敗ボーナス
        for uid, card, result in [
            (payload.user_id, my_card, result_me),
            (opp_user_id, opp_card, result_opp),
        ]:
            if result == "lose":
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE owned_cards
                        SET lose_streak_count = lose_streak_count + 1
                        WHERE id=%s
                    """, (card["id"],))
                    cur.execute("""
                        SELECT lose_streak_count
                        FROM owned_cards
                        WHERE id=%s
                    """, (card["id"],))
                    updated = cur.fetchone()

                if updated["lose_streak_count"] >= 3:
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE owned_cards
                            SET lose_streak_count = 0,
                                exp = exp + 20,
                                total_exp = COALESCE(total_exp, 0) + 20
                            WHERE id=%s
                        """, (card["id"],))
                        cur.execute("""
                            UPDATE users
                            SET exp = exp + 20
                            WHERE user_id=%s
                        """, (uid,))
                    if uid == payload.user_id:
                        extra.append("3敗ボーナスでEXP+20")

            elif result == "win":
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE owned_cards
                        SET lose_streak_count = 0
                        WHERE id=%s
                    """, (card["id"],))

        # 復活アイテム判定
        my_user = ensure_user(conn, payload.user_id)
        opp_user = ensure_user(conn, opp_user_id)

        if result_me == "lose" and my_user["revive_items"] > 0:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE users
                    SET revive_items = revive_items - 1
                    WHERE user_id=%s
                """, (payload.user_id,))
            result_me = "draw"
            extra.append("復活アイテム発動")

        elif result_opp == "lose" and opp_user["revive_items"] > 0:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE users
                    SET revive_items = revive_items - 1
                    WHERE user_id=%s
                """, (opp_user_id,))
            result_opp = "draw"

        # ボウル奪取
        ball_stolen = None
        if result_me == "win":
            ball_stolen = steal_random_ball_if_any(conn, opp_user_id, payload.user_id)
        elif result_me == "lose":
            ball_stolen = steal_random_ball_if_any(conn, payload.user_id, opp_user_id)

        if ball_stolen:
            extra.append(f"トラゴンボウル奪取: {ball_stolen}")

        # レベル反映
        level_up_card_if_needed(conn, my_card["id"])
        level_up_card_if_needed(conn, opp_card["id"])
        update_user_level(conn, payload.user_id)
        update_user_level(conn, opp_user_id)

        full_log = log_text + (" / " + " / ".join(extra) if extra else "")

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO battle_logs(
                    user_id, opponent_user_id, result, log_text, reward_exp
                ) VALUES(%s, %s, %s, %s, %s)
            """, (payload.user_id, opp_user_id, result_me, full_log, exp_me))

            cur.execute("""
                INSERT INTO battle_logs(
                    user_id, opponent_user_id, result, log_text, reward_exp
                ) VALUES(%s, %s, %s, %s, %s)
            """, (opp_user_id, payload.user_id, result_opp, full_log, exp_opp))

            cur.execute("""
                DELETE FROM battle_queue
                WHERE id=%s
            """, (waiting["id"],))

        return {
            "message": "バトルが完了しました",
            "result": result_me,
            "log": full_log,
            "reward_exp": exp_me,
        }


@router.get("/battle/logs/{user_id}")
def get_battle_logs(user_id: str):
    with get_db() as conn:
        ensure_user(conn, user_id)

        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM battle_logs
                WHERE user_id=%s
                ORDER BY id DESC
                LIMIT 50
            """, (user_id,))
            rows = cur.fetchall()

        items = [{
            "id": r["id"],
            "opponent_id": r["opponent_user_id"],
            "opponent_name": r["opponent_user_id"],
            "result": r["result"],
            "log": r["log_text"],
            "reward_exp": r["reward_exp"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else "",
        } for r in rows]

        return {"logs": items}


@router.get("/battle/ranking")
def battle_ranking(limit: int = 50):
    limit = max(1, min(limit, 100))

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
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
            """, (limit,))
            rows = cur.fetchall()

        items = []
        rank = 1
        for row in rows:
            items.append({
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
            })
            rank += 1

        return {"items": items}
