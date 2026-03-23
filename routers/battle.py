"""
routers/battle.py — バトル関連エンドポイント
PostgreSQL + psycopg3 対応版
"""
from fastapi import APIRouter, HTTPException

from database import get_db  # psycopg.connect を返す想定（dict_row 使用）
from helpers import (
    ensure_user,
    get_ownership,
    get_owned_card,
    battle_score,
    level_up_card_if_needed,
    update_user_level,
    steal_random_ball_if_any,
    grant_view_access,
)
from models import BattleEntryRequest

router = APIRouter(tags=["battle"])


@router.post("/battle/entry")
def battle_entry(payload: BattleEntryRequest):
    """
    バトルエントリー & マッチング処理
    - キューに誰もいなければ待機
    - 誰かいたら即バトル実行
    """
    with get_db() as conn:
        # トランザクション開始（明示的にコミット/ロールバックを管理したい場合は autocommit=False）
        conn.autocommit = False

        try:
            ensure_user(conn, payload.user_id)
            owner = get_ownership(conn, payload.work_id)

            if not owner or owner["owner_id"] != payload.user_id:
                raise HTTPException(400, "所有している作品のみバトル参加できます")

            my_card = get_owned_card(conn, payload.user_id, payload.work_id)
            if not my_card:
                raise HTTPException(404, "所有カードが見つかりません")

            # 自分の参加カードは閲覧解放
            grant_view_access(conn, payload.user_id, payload.work_id, "battle")

            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, user_id, work_id
                    FROM battle_queue
                    WHERE user_id != %s
                    ORDER BY id ASC
                    LIMIT 1
                """, (payload.user_id,))
                waiting = cur.fetchone()

            if not waiting:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO battle_queue (user_id, work_id)
                        VALUES (%s, %s)
                        RETURNING id
                    """, (payload.user_id, payload.work_id))
                conn.commit()
                return {"message": "対戦待機に入りました。次の参加者とマッチングします。"}

            opp_user_id = waiting["user_id"]
            opp_work_id = waiting["work_id"]
            opp_card = get_owned_card(conn, opp_user_id, opp_work_id)

            if not opp_card:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM battle_queue WHERE id = %s", (waiting["id"],))
                conn.commit()
                return {"message": "相手の待機データが無効でした。再度エントリーしてください。"}

            # スコア計算
            score_me  = battle_score(my_card)
            score_opp = battle_score(opp_card)

            if abs(score_me - score_opp) < 4:
                result_me, result_opp = "draw", "draw"
                exp_me, exp_opp = 5, 5
                log_text = f"接戦引き分け A={score_me:.1f} vs B={score_opp:.1f}"
            elif score_me > score_opp:
                result_me, result_opp = "win", "lose"
                exp_me, exp_opp = 15, 5
                log_text = f"勝利（総合力） A={score_me:.1f} > B={score_opp:.1f}"
            else:
                result_me, result_opp = "lose", "win"
                exp_me, exp_opp = 5, 15
                log_text = f"敗北 A={score_me:.1f} < B={score_opp:.1f}"

            extra = []

            # 閲覧権限付与（勝者側が両方見れる、引き分けは各自のみ）
            if result_me == "win":
                grant_view_access(conn, payload.user_id, payload.work_id, "battle")
                grant_view_access(conn, payload.user_id, opp_work_id, "battle")
            elif result_me == "lose":
                grant_view_access(conn, opp_user_id, opp_work_id, "battle")
                grant_view_access(conn, opp_user_id, payload.work_id, "battle")
            else:
                grant_view_access(conn, payload.user_id, payload.work_id, "battle")
                grant_view_access(conn, opp_user_id, opp_work_id, "battle")

            # EXP & 戦績更新
            with conn.cursor() as cur:
                # 自分
                cur.execute("""
                    UPDATE owned_cards
                    SET 
                        exp = exp + %s,
                        total_exp = COALESCE(total_exp, 0) + %s,
                        battle_count = COALESCE(battle_count, 0) + 1,
                        win_count = COALESCE(win_count, 0) + %s
                    WHERE id = %s
                """, (exp_me, exp_me, 1 if result_me == "win" else 0, my_card["id"]))

                # 相手
                cur.execute("""
                    UPDATE owned_cards
                    SET 
                        exp = exp + %s,
                        total_exp = COALESCE(total_exp, 0) + %s,
                        battle_count = COALESCE(battle_count, 0) + 1,
                        win_count = COALESCE(win_count, 0) + %s
                    WHERE id = %s
                """, (exp_opp, exp_opp, 1 if result_opp == "win" else 0, opp_card["id"]))

                # ユーザーレベルEXP
                cur.execute("UPDATE users SET exp = exp + %s WHERE user_id = %s", (exp_me,  payload.user_id))
                cur.execute("UPDATE users SET exp = exp + %s WHERE user_id = %s", (exp_opp, opp_user_id))

            # 連敗処理 & 3連敗ボーナス
            for uid, card_id, res in [
                (payload.user_id, my_card["id"],  result_me),
                (opp_user_id,    opp_card["id"], result_opp),
            ]:
                if res == "lose":
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE owned_cards
                            SET lose_streak_count = lose_streak_count + 1
                            WHERE id = %s
                            RETURNING lose_streak_count
                        """, (card_id,))
                        streak = cur.fetchone()["lose_streak_count"]

                    if streak >= 3:
                        with conn.cursor() as cur:
                            cur.execute("""
                                UPDATE owned_cards
                                SET 
                                    lose_streak_count = 0,
                                    exp = exp + 20,
                                    total_exp = COALESCE(total_exp, 0) + 20
                                WHERE id = %s
                            """, (card_id,))
                            cur.execute("UPDATE users SET exp = exp + 20 WHERE user_id = %s", (uid,))
                        if uid == payload.user_id:
                            extra.append("3連敗ボーナス +20EXP")

                elif res == "win":
                    with conn.cursor() as cur:
                        cur.execute("UPDATE owned_cards SET lose_streak_count = 0 WHERE id = %s", (card_id,))

            # 復活アイテム（負けた側が使用可能）
            my_user  = ensure_user(conn, payload.user_id)
            opp_user = ensure_user(conn, opp_user_id)

            revived = False
            if result_me == "lose" and my_user.get("revive_items", 0) > 0:
                with conn.cursor() as cur:
                    cur.execute("UPDATE users SET revive_items = revive_items - 1 WHERE user_id = %s", (payload.user_id,))
                result_me = "draw"
                revived = True
                extra.append("復活アイテム使用")

            elif result_opp == "lose" and opp_user.get("revive_items", 0) > 0:
                with conn.cursor() as cur:
                    cur.execute("UPDATE users SET revive_items = revive_items - 1 WHERE user_id = %s", (opp_user_id,))
                result_opp = "draw"
                revived = True

            # ボール（トラゴンボウル？）奪取
            ball_stolen = None
            if result_me == "win":
                ball_stolen = steal_random_ball_if_any(conn, opp_user_id, payload.user_id)
            elif result_me == "lose":
                ball_stolen = steal_random_ball_if_any(conn, payload.user_id, opp_user_id)

            if ball_stolen:
                extra.append(f"ボール奪取！ → {ball_stolen}")

            # レベルアップ反映
            level_up_card_if_needed(conn, my_card["id"])
            level_up_card_if_needed(conn, opp_card["id"])
            update_user_level(conn, payload.user_id)
            update_user_level(conn, opp_user_id)

            # ログ生成 & 保存
            full_log = log_text
            if extra:
                full_log += " / " + " / ".join(extra)

            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO battle_logs (
                        user_id, opponent_user_id, result, log_text, reward_exp, created_at
                    ) VALUES (%s, %s, %s, %s, %s, NOW())
                """, (payload.user_id, opp_user_id, result_me, full_log, exp_me))

                cur.execute("""
                    INSERT INTO battle_logs (
                        user_id, opponent_user_id, result, log_text, reward_exp, created_at
                    ) VALUES (%s, %s, %s, %s, %s, NOW())
                """, (opp_user_id, payload.user_id, result_opp, full_log, exp_opp))

                # キュー削除
                cur.execute("DELETE FROM battle_queue WHERE id = %s", (waiting["id"],))

            conn.commit()

            return {
                "message": "バトル完了",
                "result": result_me,
                "log": full_log,
                "reward_exp": exp_me,
                "revived": revived,
            }

        except Exception as e:
            conn.rollback()
            raise HTTPException(500, f"バトル処理中にエラーが発生しました: {str(e)}") from e


@router.get("/battle/logs/{user_id}")
def get_battle_logs(user_id: str):
    with get_db() as conn:
        ensure_user(conn, user_id)

        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    id,
                    opponent_user_id,
                    result,
                    log_text,
                    reward_exp,
                    created_at
                FROM battle_logs
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 50
            """, (user_id,))
            rows = cur.fetchall()

        items = [
            {
                "id": r["id"],
                "opponent_id": r["opponent_user_id"],
                "opponent_name": r["opponent_user_id"],  # 必要なら JOIN で名前取得
                "result": r["result"],
                "log": r["log_text"],
                "reward_exp": r["reward_exp"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]

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
                    oc.hp, oc.atk, oc.def, oc.spd, oc.luk,
                    oc.is_legend::boolean AS is_legend,
                    w.title,
                    w.creator_name,
                    w.image_url,
                    w.video_url
                FROM owned_cards oc
                INNER JOIN works w ON w.id = oc.work_id
                -- ownership テーブルがあるなら必要に応じて JOIN（現在は所有チェック省略可）
                ORDER BY 
                    win_count DESC,
                    level DESC,
                    total_exp DESC,
                    battle_count DESC,
                    oc.id ASC
                LIMIT %s
            """, (limit,))
            rows = cur.fetchall()

        items = []
        for rank, r in enumerate(rows, 1):
            items.append({
                "rank": rank,
                "card_id": r["card_id"],
                "user_id": r["user_id"],
                "work_id": r["work_id"],
                "title": r["title"],
                "creator_name": r["creator_name"],
                "image_url": r["image_url"] or "",
                "video_url": r["video_url"] or "",
                "rarity": r["rarity"],
                "level": r["level"],
                "exp": r["exp"],
                "total_exp": r["total_exp"],
                "win_count": r["win_count"],
                "battle_count": r["battle_count"],
                "hp": r["hp"],
                "atk": r["atk"],
                "def": r["def"],
                "spd": r["spd"],
                "luk": r["luk"],
                "is_legend": r["is_legend"],
            })

        return {"items": items}
