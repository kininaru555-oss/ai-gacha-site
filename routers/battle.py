"""
routers/battle.py — バトル関連エンドポイント（PostgreSQL + psycopg 対応版）
"""
from fastapi import APIRouter, HTTPException, status
from psycopg.rows import dict_row

from database import get_db  # psycopg.connect を返す関数（row_factory=dict_row 想定）
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
    バトル参加エントリー
    ・待機者がいなければキューに追加
    ・待機者がいれば即時バトル実行
    """
    with get_db() as conn:
        conn.autocommit = False
        try:
            # ユーザー存在確認
            ensure_user(conn, payload.user_id)

            # 所有確認
            owner = get_ownership(conn, payload.work_id)
            if not owner or owner["owner_id"] != payload.user_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="所有している作品のみバトル参加できます"
                )

            my_card = get_owned_card(conn, payload.user_id, payload.work_id)
            if not my_card:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="所有カードが見つかりません"
                )

            # 自分の参加カードを閲覧可能にする
            grant_view_access(conn, payload.user_id, payload.work_id, "battle")

            # 待機中の相手を探す（自分以外で最も古いもの）
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("""
                    SELECT id, user_id, work_id
                    FROM battle_queue
                    WHERE user_id != %s
                    ORDER BY id ASC
                    LIMIT 1
                """, (payload.user_id,))
                waiting = cur.fetchone()

            if not waiting:
                # 待機者なし → 自分がキューに入る
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO battle_queue (user_id, work_id)
                        VALUES (%s, %s)
                    """, (payload.user_id, payload.work_id))
                conn.commit()
                return {"message": "対戦待機に入りました。次の参加者とマッチングします。"}

            # 相手情報取得
            opp_user_id = waiting["user_id"]
            opp_work_id = waiting["work_id"]
            opp_card = get_owned_card(conn, opp_user_id, opp_work_id)

            if not opp_card:
                # 相手のカードが消えている場合はキュー削除
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM battle_queue WHERE id = %s", (waiting["id"],))
                conn.commit()
                return {"message": "相手の待機データが無効でした。再度エントリーしてください。"}

            # スコア計算
            score_me = battle_score(my_card)
            score_opp = battle_score(opp_card)

            # 勝敗判定
            if abs(score_me - score_opp) < 4:
                result_me = result_opp = "draw"
                exp_me = exp_opp = 5
                log_base = f"接戦で引き分け A={score_me:.1f} vs B={score_opp:.1f}"
            elif score_me > score_opp:
                result_me, result_opp = "win", "lose"
                exp_me, exp_opp = 15, 5
                log_base = f"勝利（総合力） A={score_me:.1f} > B={score_opp:.1f}"
            else:
                result_me, result_opp = "lose", "win"
                exp_me, exp_opp = 5, 15
                log_base = f"敗北 A={score_me:.1f} < B={score_opp:.1f}"

            extra_logs = []

            # 閲覧権限付与
            if result_me == "win":
                grant_view_access(conn, payload.user_id, payload.work_id, "battle")
                grant_view_access(conn, payload.user_id, opp_work_id, "battle")
            elif result_me == "lose":
                grant_view_access(conn, opp_user_id, opp_work_id, "battle")
                grant_view_access(conn, opp_user_id, payload.work_id, "battle")
            else:
                grant_view_access(conn, payload.user_id, payload.work_id, "battle")
                grant_view_access(conn, opp_user_id, opp_work_id, "battle")

            # 戦績・EXP更新（可能な限りまとめる）
            with conn.cursor() as cur:
                # 自分のカード
                cur.execute("""
                    UPDATE owned_cards
                    SET 
                        exp = exp + %s,
                        total_exp = COALESCE(total_exp, 0) + %s,
                        battle_count = COALESCE(battle_count, 0) + 1,
                        win_count = COALESCE(win_count, 0) + %s,
                        lose_streak_count = CASE 
                            WHEN %s = 'lose' THEN lose_streak_count + 1 
                            ELSE 0 
                        END
                    WHERE id = %s
                """, (exp_me, exp_me, 1 if result_me == "win" else 0,
                      result_me, my_card["id"]))

                # 相手のカード
                cur.execute("""
                    UPDATE owned_cards
                    SET 
                        exp = exp + %s,
                        total_exp = COALESCE(total_exp, 0) + %s,
                        battle_count = COALESCE(battle_count, 0) + 1,
                        win_count = COALESCE(win_count, 0) + %s,
                        lose_streak_count = CASE 
                            WHEN %s = 'lose' THEN lose_streak_count + 1 
                            ELSE 0 
                        END
                    WHERE id = %s
                """, (exp_opp, exp_opp, 1 if result_opp == "win" else 0,
                      result_opp, opp_card["id"]))

                # ユーザーEXP
                cur.execute("UPDATE users SET exp = exp + %s WHERE user_id = %s", (exp_me, payload.user_id))
                cur.execute("UPDATE users SET exp = exp + %s WHERE user_id = %s", (exp_opp, opp_user_id))

            # 3連敗ボーナス処理
            for uid, card_id, result in [
                (payload.user_id, my_card["id"], result_me),
                (opp_user_id, opp_card["id"], result_opp),
            ]:
                if result == "lose":
                    with conn.cursor(row_factory=dict_row) as cur:
                        cur.execute("""
                            SELECT lose_streak_count 
                            FROM owned_cards 
                            WHERE id = %s
                        """, (card_id,))
                        streak_row = cur.fetchone()

                    if streak_row and streak_row["lose_streak_count"] >= 3:
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
                            extra_logs.append("3連敗ボーナス +20EXP")

            # 復活アイテム処理
            my_user = ensure_user(conn, payload.user_id)
            opp_user = ensure_user(conn, opp_user_id)

            revived = False
            if result_me == "lose" and my_user.get("revive_items", 0) > 0:
                with conn.cursor() as cur:
                    cur.execute("UPDATE users SET revive_items = revive_items - 1 WHERE user_id = %s", (payload.user_id,))
                result_me = "draw"
                revived = True
                extra_logs.append("復活アイテム使用")

            elif result_opp == "lose" and opp_user.get("revive_items", 0) > 0:
                with conn.cursor() as cur:
                    cur.execute("UPDATE users SET revive_items = revive_items - 1 WHERE user_id = %s", (opp_user_id,))
                result_opp = "draw"
                revived = True

            # ボール奪取
            ball_stolen = None
            if result_me == "win":
                ball_stolen = steal_random_ball_if_any(conn, opp_user_id, payload.user_id)
            elif result_me == "lose":
                ball_stolen = steal_random_ball_if_any(conn, payload.user_id, opp_user_id)

            if ball_stolen:
                extra_logs.append(f"ボール奪取！ → {ball_stolen}")

            # レベルアップ反映
            level_up_card_if_needed(conn, my_card["id"])
            level_up_card_if_needed(conn, opp_card["id"])
            update_user_level(conn, payload.user_id)
            update_user_level(conn, opp_user_id)

            # 最終ログ生成
            full_log = log_base
            if extra_logs:
                full_log += " / " + " / ".join(extra_logs)

            # バトルログ保存 & キュー削除
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO battle_logs 
                        (user_id, opponent_user_id, result, log_text, reward_exp, created_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                """, (payload.user_id, opp_user_id, result_me, full_log, exp_me))

                cur.execute("""
                    INSERT INTO battle_logs 
                        (user_id, opponent_user_id, result, log_text, reward_exp, created_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                """, (opp_user_id, payload.user_id, result_opp, full_log, exp_opp))

                cur.execute("DELETE FROM battle_queue WHERE id = %s", (waiting["id"],))

            conn.commit()

            return {
                "message": "バトルが完了しました",
                "result": result_me,
                "log": full_log,
                "reward_exp": exp_me,
                "revived": revived,
            }

        except HTTPException as he:
            conn.rollback()
            raise he
        except Exception as e:
            conn.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"バトル処理中にエラーが発生しました: {str(e)}"
            ) from e


@router.get("/battle/logs/{user_id}")
def get_battle_logs(user_id: str):
    with get_db() as conn:
        ensure_user(conn, user_id)

        with conn.cursor(row_factory=dict_row) as cur:
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

        logs = []
        for r in rows:
            logs.append({
                "id": r["id"],
                "opponent_id": r["opponent_user_id"],
                "opponent_name": r["opponent_user_id"],  # 必要なら users テーブルから名前を取得
                "result": r["result"],
                "log": r["log_text"],
                "reward_exp": r["reward_exp"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            })

        return {"logs": logs}


@router.get("/battle/ranking")
def battle_ranking(limit: int = 50):
    limit = max(1, min(limit, 100))

    with get_db() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
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
                    oc.is_legend::boolean AS is_legend,
                    w.title,
                    w.creator_name,
                    w.image_url,
                    w.video_url
                FROM owned_cards oc
                INNER JOIN works w ON w.id = oc.work_id
                ORDER BY 
                    win_count DESC,
                    level DESC,
                    total_exp DESC,
                    battle_count DESC,
                    oc.id ASC
                LIMIT %s
            """, (limit,))
            rows = cur.fetchall()

        ranking = []
        for rank, row in enumerate(rows, start=1):
            ranking.append({
                "rank": rank,
                "card_id": row["card_id"],
                "user_id": row["user_id"],
                "work_id": row["work_id"],
                "title": row["title"],
                "creator_name": row["creator_name"] or "不明",
                "image_url": row["image_url"] or "",
                "video_url": row["video_url"] or "",
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
                "is_legend": row["is_legend"],
            })

        return {"items": ranking}
