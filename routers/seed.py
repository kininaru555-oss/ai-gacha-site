from pathlib import Path

content = r'''"""
seed.py — 初期データ投入（完成版）

方針:
- 開発・検証用の初期データのみ投入する
- 一般投稿作品の rarity は N 固定
- 公式作品(admin/system) のみ任意 rarity を使用
- レジェンドボール表記へ統一
- database_fixed.py の新カラム(media_type / item_type / legend_code 等)にも対応
- 既存DBとの互換のため、旧カラム(type / is_ball / ball_code) にも値を入れる
"""
from database import get_db


OFFICIAL_USERS = [
    ("system", "", 0, 0, 0),
    ("admin", "admin123", 9999, 99, 0),
]

CREATOR_USERS = [
    ("creator1", "1234", 100, 3, 0),
    ("creator2", "1234", 100, 3, 0),
    ("player1", "1234", 100, 1, 0),
]


def ensure_user_columns(cur):
    """古いDBでも seed が通りやすいように補助カラムを追加する。"""
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT DEFAULT ''")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_exp_purchase_count INTEGER DEFAULT 0")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_exp_purchase_date TEXT DEFAULT ''")


def ensure_work_columns(cur):
    """新仕様カラムを補助追加する。"""
    cur.execute("ALTER TABLE works ADD COLUMN IF NOT EXISTS media_type TEXT DEFAULT 'image'")
    cur.execute("ALTER TABLE works ADD COLUMN IF NOT EXISTS item_type TEXT DEFAULT 'work'")
    cur.execute("ALTER TABLE works ADD COLUMN IF NOT EXISTS legend_code TEXT DEFAULT ''")
    cur.execute("ALTER TABLE works ADD COLUMN IF NOT EXISTS is_public INTEGER DEFAULT 1")
    cur.execute("ALTER TABLE works ADD COLUMN IF NOT EXISTS gacha_enabled INTEGER DEFAULT 1")
    cur.execute("ALTER TABLE works ADD COLUMN IF NOT EXISTS is_deleted INTEGER DEFAULT 0")
    cur.execute("ALTER TABLE works ADD COLUMN IF NOT EXISTS draw_count INTEGER DEFAULT 0")
    cur.execute("ALTER TABLE works ADD COLUMN IF NOT EXISTS like_count INTEGER DEFAULT 0")
    cur.execute("ALTER TABLE works ADD COLUMN IF NOT EXISTS exp_reward INTEGER DEFAULT 5")


def _insert_users(cur):
    for uid, pw, pts, free, royalty in OFFICIAL_USERS + CREATOR_USERS:
        cur.execute(
            """
            INSERT INTO users(
                user_id,
                password,
                password_hash,
                points,
                free_draw_count,
                royalty_balance
            )
            VALUES(%s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (uid, pw, "", pts, free, royalty),
        )


def _insert_base_works(cur):
    """
    一般投稿作品は N 固定。
    公式作品(admin/system) だけ rarity を任意指定。
    """
    base_works = [
        {
            "title": "月下の魔導姫",
            "creator_id": "creator1",
            "creator_name": "投稿者1",
            "description": "夜の魔力をまとった静かな魔導姫。",
            "genre": "ファンタジー",
            "media_type": "image",
            "item_type": "work",
            "image_url": "https://res.cloudinary.com/demo/image/upload/sample.jpg",
            "video_url": "",
            "thumbnail_url": "",
            "link_url": "https://example.com/creator1",
            "x_url": "https://x.com/creator1",
            "booth_url": "https://booth.pm",
            "chichipui_url": "https://www.chichi-pui.com/",
            "dlsite_url": "",
            "fanbox_url": "",
            "skeb_url": "",
            "pixiv_url": "",
            "rarity": "N",
            "hp": 18,
            "atk": 12,
            "defense": 11,
            "spd": 10,
            "luk": 8,
            "exp_reward": 8,
            "is_active": 1,
            "is_ball": 0,
            "ball_code": "",
            "legend_code": "",
            "content_hash": "hash-1",
        },
        {
            "title": "深紅の踊り子",
            "creator_id": "creator1",
            "creator_name": "投稿者1",
            "description": "舞台を赤く染める華やかな踊り子。",
            "genre": "ダークファンタジー",
            "media_type": "image",
            "item_type": "work",
            "image_url": "https://res.cloudinary.com/demo/image/upload/sample.jpg",
            "video_url": "",
            "thumbnail_url": "",
            "link_url": "https://example.com/creator1",
            "x_url": "",
            "booth_url": "",
            "chichipui_url": "",
            "dlsite_url": "",
            "fanbox_url": "",
            "skeb_url": "",
            "pixiv_url": "",
            "rarity": "N",
            "hp": 20,
            "atk": 16,
            "defense": 12,
            "spd": 15,
            "luk": 10,
            "exp_reward": 10,
            "is_active": 1,
            "is_ball": 0,
            "ball_code": "",
            "legend_code": "",
            "content_hash": "hash-2",
        },
        {
            "title": "電脳天使ユリナ",
            "creator_id": "creator2",
            "creator_name": "投稿者2",
            "description": "都市の夜空を飛ぶ電脳系ヒロイン。",
            "genre": "SF",
            "media_type": "video",
            "item_type": "work",
            "image_url": "",
            "video_url": "https://www.w3schools.com/html/mov_bbb.mp4",
            "thumbnail_url": "",
            "link_url": "https://example.com/creator2",
            "x_url": "",
            "booth_url": "",
            "chichipui_url": "",
            "dlsite_url": "",
            "fanbox_url": "",
            "skeb_url": "",
            "pixiv_url": "",
            "rarity": "N",
            "hp": 22,
            "atk": 20,
            "defense": 16,
            "spd": 18,
            "luk": 12,
            "exp_reward": 15,
            "is_active": 1,
            "is_ball": 0,
            "ball_code": "",
            "legend_code": "",
            "content_hash": "hash-3",
        },
        {
            "title": "運営限定・白銀神姫",
            "creator_id": "admin",
            "creator_name": "運営",
            "description": "運営が広告・演出用に投入する限定カード。",
            "genre": "限定",
            "media_type": "image",
            "item_type": "work",
            "image_url": "https://res.cloudinary.com/demo/image/upload/sample.jpg",
            "video_url": "",
            "thumbnail_url": "",
            "link_url": "https://example.com/admin",
            "x_url": "",
            "booth_url": "",
            "chichipui_url": "",
            "dlsite_url": "",
            "fanbox_url": "",
            "skeb_url": "",
            "pixiv_url": "",
            "rarity": "SSR",
            "hp": 28,
            "atk": 26,
            "defense": 22,
            "spd": 18,
            "luk": 16,
            "exp_reward": 25,
            "is_active": 1,
            "is_ball": 0,
            "ball_code": "",
            "legend_code": "",
            "content_hash": "hash-4",
        },
    ]

    for w in base_works:
        cur.execute(
            """
            INSERT INTO works(
                title,
                creator_id,
                creator_name,
                description,
                genre,
                type,
                media_type,
                item_type,
                image_url,
                video_url,
                thumbnail_url,
                link_url,
                x_url,
                booth_url,
                chichipui_url,
                dlsite_url,
                fanbox_url,
                skeb_url,
                pixiv_url,
                rarity,
                hp,
                atk,
                def,
                spd,
                luk,
                exp_reward,
                is_active,
                is_ball,
                ball_code,
                legend_code,
                content_hash,
                is_public,
                gacha_enabled,
                is_deleted,
                draw_count,
                like_count
            )
            VALUES(
                %s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s
            )
            ON CONFLICT (content_hash) DO NOTHING
            """,
            (
                w["title"],
                w["creator_id"],
                w["creator_name"],
                w["description"],
                w["genre"],
                w["media_type"],  # 旧 type 互換
                w["media_type"],
                w["item_type"],
                w["image_url"],
                w["video_url"],
                w["thumbnail_url"],
                w["link_url"],
                w["x_url"],
                w["booth_url"],
                w["chichipui_url"],
                w["dlsite_url"],
                w["fanbox_url"],
                w["skeb_url"],
                w["pixiv_url"],
                w["rarity"],
                w["hp"],
                w["atk"],
                w["defense"],
                w["spd"],
                w["luk"],
                w["exp_reward"],
                w["is_active"],
                w["is_ball"],
                w["ball_code"],
                w["legend_code"],
                w["content_hash"],
                1,  # is_public
                1,  # gacha_enabled
                0,  # is_deleted
                0,  # draw_count
                0,  # like_count
            ),
        )


def _insert_legend_balls(cur):
    """
    レジェンドボール 1〜7
    旧互換のため is_ball / ball_code も埋める。
    """
    for i in range(1, 8):
        legend_code = f"LEGEND_BALL_{i}"
        cur.execute(
            """
            INSERT INTO works(
                title,
                creator_id,
                creator_name,
                description,
                genre,
                type,
                media_type,
                item_type,
                image_url,
                video_url,
                thumbnail_url,
                link_url,
                x_url,
                booth_url,
                chichipui_url,
                dlsite_url,
                fanbox_url,
                skeb_url,
                pixiv_url,
                rarity,
                hp,
                atk,
                def,
                spd,
                luk,
                exp_reward,
                is_active,
                is_ball,
                ball_code,
                legend_code,
                content_hash,
                is_public,
                gacha_enabled,
                is_deleted,
                draw_count,
                like_count
            )
            VALUES(
                %s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s
            )
            ON CONFLICT (content_hash) DO NOTHING
            """,
            (
                f"レジェンドボール {i}",
                "admin",
                "運営",
                "7つ集めるとレジェンド化に使用できます。",
                "アイテム",
                "image",          # 旧 type
                "image",
                "legend_ball",
                "https://res.cloudinary.com/demo/image/upload/sample.jpg",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "R",
                5,
                5,
                5,
                5,
                5,
                3,
                1,
                1,
                legend_code,      # 旧 ball_code
                legend_code,
                f"legend-ball-hash-{i}",
                1,
                1,
                0,
                0,
                0,
            ),
        )


def seed_data():
    with get_db() as conn:
        with conn.cursor() as cur:
            ensure_user_columns(cur)
            ensure_work_columns(cur)
            _insert_users(cur)
            _insert_base_works(cur)
            _insert_legend_balls(cur)

        conn.commit()


if __name__ == "__main__":
    seed_data()
    print("seed completed")
'''
path = Path("/mnt/data/seed_fixed.py")
path.write_text(content, encoding="utf-8")
print(path)
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
