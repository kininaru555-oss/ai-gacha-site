"""
seed.py — 初期データ投入（完全修正・本番安全版）
実行方法: python seed.py
何度実行しても大丈夫（ON CONFLICT DO NOTHING）
"""
from database import get_db
import hashlib

def hash_password(plain: str) -> str:
    """開発用簡易ハッシュ（本番は bcrypt / argon2 に置き換えてください）"""
    return hashlib.sha256(plain.encode()).hexdigest()[:60]

def seed_data():
    with get_db() as conn:
        with conn.cursor() as cur:

            # =============================================
            # 1. 初期ユーザー
            # =============================================
            users = [
                ("admin",     "admin123", 99999, 99, 0),   # 運営用
                ("creator1",  "1234",     500,   5,  0),
                ("creator2",  "1234",     300,   3,  0),
                ("player1",   "1234",     200,   3,  0),
                ("player2",   "1234",     150,   1,  0),
            ]

            for uid, pw, pts, free, royalty in users:
                hashed = hash_password(pw)
                cur.execute("""
                    INSERT INTO users(user_id, password, points, free_draw_count, royalty_balance)
                    VALUES(%s, %s, %s, %s, %s)
                    ON CONFLICT (user_id) DO NOTHING
                """, (uid, hashed, pts, free, royalty))

            # =============================================
            # 2. 初期作品（一般N + 運営SSR）
            # =============================================
            base_works = [
                # creator1
                ("月下の魔導姫", "creator1", "投稿者1", "夜の魔力をまとった静かな魔導姫。", "ファンタジー", "image",
                 "https://res.cloudinary.com/demo/image/upload/v1/ai-beauty/magical_princess.jpg", "", "",
                 "https://example.com/creator1", "https://x.com/creator1", "https://booth.pm/@creator1", "", "", "", "", "", "N",
                 18, 14, 12, 11, 9, 8, 1, 0, "", "hash-moon-princess"),

                ("深紅の踊り子", "creator1", "投稿者1", "舞台を赤く染める華やかな踊り子。", "ダークファンタジー", "image",
                 "https://res.cloudinary.com/demo/image/upload/v1/ai-beauty/crimson_dancer.jpg", "", "",
                 "https://example.com/creator1", "", "", "", "", "", "", "", "N",
                 21, 17, 13, 15, 10, 10, 1, 0, "", "hash-crimson-dancer"),

                # creator2
                ("電脳天使ユリナ", "creator2", "投稿者2", "都市の夜空を飛ぶ電脳系ヒロイン。", "SF", "video",
                 "", "https://www.w3schools.com/html/mov_bbb.mp4", "",
                 "https://example.com/creator2", "", "", "", "", "", "", "", "N",
                 23, 19, 15, 17, 11, 15, 1, 0, "", "hash-neo-angel"),

                # 運営限定SSR（演出用）
                ("白銀神姫・エレノア", "admin", "運営", "運営が特別演出・ガチャピックアップ用に投入する最上位カード。", "限定", "image",
                 "https://res.cloudinary.com/demo/image/upload/v1/ai-beauty/silver_goddess.jpg", "", "",
                 "https://example.com/admin", "", "", "", "", "", "", "", "SSR",
                 30, 28, 24, 22, 18, 30, 1, 0, "", "hash-silver-goddess"),
            ]

            for w in base_works:
                cur.execute("""
                    INSERT INTO works(
                        title, creator_id, creator_name, description, genre, type,
                        image_url, video_url, thumbnail_url,
                        link_url, x_url, booth_url, chichipui_url, dlsite_url,
                        fanbox_url, skeb_url, pixiv_url,
                        rarity, hp, atk, def, spd, luk, exp_reward,
                        is_active, is_ball, ball_code, content_hash
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (content_hash) DO NOTHING
                """, w)

            # =============================================
            # 3. 初期所有カード（mypage / market 即テスト用）
            # =============================================
            # player1 に作品を2枚所有させる
            cur.execute("""
                INSERT INTO owned_cards (work_id, user_id, level, exp, total_exp, win_count, battle_count)
                SELECT id, 'player1', 5, 120, 450, 3, 5
                FROM works WHERE title = '月下の魔導姫'
                ON CONFLICT DO NOTHING
            """)
            cur.execute("""
                INSERT INTO owned_cards (work_id, user_id, level, exp, total_exp, win_count, battle_count)
                SELECT id, 'player1', 8, 280, 920, 7, 12
                FROM works WHERE title = '深紅の踊り子'
                ON CONFLICT DO NOTHING
            """)

            # ownership テーブルにも反映
            cur.execute("""
                INSERT INTO ownership (work_id, owner_id)
                SELECT id, 'player1' FROM works 
                WHERE title IN ('月下の魔導姫', '深紅の踊り子')
                ON CONFLICT DO NOTHING
            """)

            # =============================================
            # 4. トラゴンボール（7種）
            # =============================================
            for i in range(1, 8):
                cur.execute("""
                    INSERT INTO balls (ball_code, owner_id)
                    VALUES(%s, 'player1')
                    ON CONFLICT DO NOTHING
                """, (f"BALL_{i}",))

            conn.commit()

    print("✅ seed_data() 完了！")
    print("   - ユーザー: admin / creator1 / player1 など")
    print("   - 作品4枚 + 所有カード2枚 + ボール7個 投入済み")
    print("   - mypage / market / result.html が即テスト可能になりました")


if __name__ == "__main__":
    seed_data()
