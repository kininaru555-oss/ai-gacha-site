content = r'''"""
seed.py — 初期データ投入（完成版）

方針:
- 開発・検証用の初期データのみ投入する
- 一般投稿作品の rarity は N 固定
- 公式作品(admin/system) のみ任意 rarity を使用
- レジェンドボール表記へ統一
- database.py の新カラム(media_type / item_type / legend_code 等)に対応
- 既存DBとの互換のため、旧カラム(type / is_ball / ball_code) にも値を入れる
"""
from __future__ import annotations

from database import get_db


OFFICIAL_USERS = [
    ("system", "", 0, 0, 0, 0, 1),
    ("admin", "admin123", 9999, 99, 0, 1, 1),
]

CREATOR_USERS = [
    ("creator1", "1234", 100, 3, 0, 0, 0),
    ("creator2", "1234", 100, 3, 0, 0, 0),
    ("player1", "1234", 100, 1, 0, 0, 0),
]


def ensure_user_columns(cur):
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT DEFAULT ''")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS total_exp BIGINT DEFAULT 0")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_exp_purchase_count INTEGER DEFAULT 0")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_exp_purchase_date TEXT DEFAULT ''")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin INTEGER DEFAULT 0")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_official INTEGER DEFAULT 0")


def ensure_work_columns(cur):
    cur.execute("ALTER TABLE works ADD COLUMN IF NOT EXISTS media_type TEXT DEFAULT 'image'")
    cur.execute("ALTER TABLE works ADD COLUMN IF NOT EXISTS item_type TEXT DEFAULT 'work'")
    cur.execute("ALTER TABLE works ADD COLUMN IF NOT EXISTS legend_code TEXT DEFAULT NULL")
    cur.execute("ALTER TABLE works ADD COLUMN IF NOT EXISTS is_public INTEGER DEFAULT 1")
    cur.execute("ALTER TABLE works ADD COLUMN IF NOT EXISTS gacha_enabled INTEGER DEFAULT 1")
    cur.execute("ALTER TABLE works ADD COLUMN IF NOT EXISTS is_deleted INTEGER DEFAULT 0")
    cur.execute("ALTER TABLE works ADD COLUMN IF NOT EXISTS draw_count INTEGER DEFAULT 0")
    cur.execute("ALTER TABLE works ADD COLUMN IF NOT EXISTS like_count INTEGER DEFAULT 0")
    cur.execute("ALTER TABLE works ADD COLUMN IF NOT EXISTS exp_reward INTEGER DEFAULT 5")
    cur.execute("ALTER TABLE works ADD COLUMN IF NOT EXISTS fanbox_url TEXT DEFAULT ''")
    cur.execute("ALTER TABLE works ADD COLUMN IF NOT EXISTS skeb_url TEXT DEFAULT ''")
    cur.execute("ALTER TABLE works ADD COLUMN IF NOT EXISTS pixiv_url TEXT DEFAULT ''")
    cur.execute("UPDATE works SET ball_code = NULL WHERE ball_code = ''")
    cur.execute("UPDATE works SET legend_code = NULL WHERE legend_code = ''")


def ensure_owned_card_columns(cur):
    cur.execute("ALTER TABLE owned_cards ADD COLUMN IF NOT EXISTS total_exp BIGINT DEFAULT 0")
    cur.execute("ALTER TABLE owned_cards ADD COLUMN IF NOT EXISTS win_count INTEGER DEFAULT 0")
    cur.execute("ALTER TABLE owned_cards ADD COLUMN IF NOT EXISTS battle_count INTEGER DEFAULT 0")


def _insert_users(cur):
    for uid, pw, pts, free, royalty, is_admin, is_official in OFFICIAL_USERS + CREATOR_USERS:
        cur.execute(
            """
            INSERT INTO users(
                user_id,
                password,
                password_hash,
                points,
                free_draw_count,
                royalty_balance,
                is_admin,
                is_official
            )
            VALUES(%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO NOTHING
            """,
            (uid, pw, "", pts, free, royalty, is_admin, is_official),
        )


def _insert_base_works(cur):
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
            "ball_code": None,
            "legend_code": None,
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
            "ball_code": None,
            "legend_code": None,
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
            "ball_code": None,
            "legend_code": None,
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
            "ball_code": None,
            "legend_code": None,
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
                w["media_type"],
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
                1,
                1,
                0,
                0,
                0,
            ),
        )


def _insert_legend_balls(cur):
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
                "image",
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
                legend_code,
                legend_code,
                f"legend-ball-hash-{i}",
                1,
                1,
                0,
                0,
                0,
            ),
        )


def _grant_initial_ownership_and_cards(cur):
    titles = ["月下の魔導姫", "深紅の踊り子"]

    for title in titles:
        cur.execute("SELECT * FROM works WHERE title = %s LIMIT 1", (title,))
        work = cur.fetchone()
        if not work:
            continue

        cur.execute(
            """
            INSERT INTO ownership(work_id, owner_id)
            VALUES(%s, %s)
            ON CONFLICT (work_id) DO NOTHING
            """,
            (work["id"], "player1"),
        )

        base = {
            "月下の魔導姫": {"level": 5, "exp": 20, "total_exp": 140, "win": 3, "battle": 5},
            "深紅の踊り子": {"level": 8, "exp": 10, "total_exp": 280, "win": 7, "battle": 12},
        }[title]

        cur.execute(
            """
            INSERT INTO owned_cards(
                user_id, work_id, rarity, level, exp, total_exp,
                hp, atk, def, spd, luk,
                lose_streak_count, is_legend, legend_at,
                win_count, battle_count
            )
            VALUES(
                %s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,
                0,0,'',
                %s,%s
            )
            ON CONFLICT (work_id) DO NOTHING
            """,
            (
                "player1",
                work["id"],
                work["rarity"],
                base["level"],
                base["exp"],
                base["total_exp"],
                work["hp"],
                work["atk"],
                work["def"],
                work["spd"],
                work["luk"],
                base["win"],
                base["battle"],
            ),
        )


def _grant_initial_legend_balls(cur):
    cur.execute(
        """
        SELECT id
        FROM works
        WHERE item_type = 'legend_ball'
        ORDER BY id ASC
        """
    )
    rows = cur.fetchall()

    for row in rows:
        cur.execute(
            """
            INSERT INTO ownership(work_id, owner_id)
            VALUES(%s, %s)
            ON CONFLICT (work_id) DO NOTHING
            """,
            (row["id"], "player1"),
        )


def seed_data():
    with get_db() as conn:
        with conn.cursor() as cur:
            ensure_user_columns(cur)
            ensure_work_columns(cur)
            ensure_owned_card_columns(cur)
            _insert_users(cur)
            _insert_base_works(cur)
            _insert_legend_balls(cur)
            _grant_initial_ownership_and_cards(cur)
            _grant_initial_legend_balls(cur)

        conn.commit()


if __name__ == "__main__":
    seed_data()
    print("seed completed")
'''
path = "/mnt/data/seed_fixed.py"
with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print(path)
