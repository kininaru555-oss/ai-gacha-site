"""
seed.py — 初期データ投入
"""
from database import get_db


def seed_data():
    with get_db() as conn:
        with conn.cursor() as cur:
            # ─────────────────────────────────────────────
            # 初期ユーザー
            # ─────────────────────────────────────────────
            for uid, pw, pts, free, royalty in [
                ("admin", "admin123", 9999, 99, 0),
                ("creator1", "1234", 100, 3, 0),
                ("creator2", "1234", 100, 3, 0),
                ("player1", "1234", 100, 1, 0),
            ]:
                cur.execute("""
                    INSERT INTO users(
                        user_id,
                        password,
                        points,
                        free_draw_count,
                        royalty_balance
                    )
                    VALUES(%s, %s, %s, %s, %s)
                    ON CONFLICT (user_id) DO NOTHING
                """, (uid, pw, pts, free, royalty))

            # ─────────────────────────────────────────────
            # 初期作品
            # 一般投稿作品は rarity=N を基本に統一
            # 運営作品のみ高レア演出用 rarity を使う
            # ─────────────────────────────────────────────
            base_works = [
                (
                    "月下の魔導姫",          # title
                    "creator1",             # creator_id
                    "投稿者1",              # creator_name
                    "夜の魔力をまとった静かな魔導姫。",  # description
                    "ファンタジー",          # genre
                    "image",                # type
                    "https://res.cloudinary.com/demo/image/upload/sample.jpg",  # image_url
                    "",                     # video_url
                    "",                     # thumbnail_url
                    "https://example.com/creator1",   # link_url
                    "https://x.com/creator1",         # x_url
                    "https://booth.pm",               # booth_url
                    "https://www.chichi-pui.com/",    # chichipui_url
                    "",                     # dlsite_url
                    "",                     # fanbox_url
                    "",                     # skeb_url
                    "",                     # pixiv_url
                    "N",                    # rarity
                    18, 12, 11, 10, 8,      # hp, atk, def, spd, luk
                    8,                      # exp_reward
                    1,                      # is_active
                    0,                      # is_ball
                    "",                     # ball_code
                    "hash-1",               # content_hash
                ),
                (
                    "深紅の踊り子",
                    "creator1",
                    "投稿者1",
                    "舞台を赤く染める華やかな踊り子。",
                    "ダークファンタジー",
                    "image",
                    "https://res.cloudinary.com/demo/image/upload/sample.jpg",
                    "",
                    "",
                    "https://example.com/creator1",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "N",
                    20, 16, 12, 15, 10,
                    10,
                    1,
                    0,
                    "",
                    "hash-2",
                ),
                (
                    "電脳天使ユリナ",
                    "creator2",
                    "投稿者2",
                    "都市の夜空を飛ぶ電脳系ヒロイン。",
                    "SF",
                    "video",
                    "",
                    "https://www.w3schools.com/html/mov_bbb.mp4",
                    "",
                    "https://example.com/creator2",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "N",
                    22, 20, 16, 18, 12,
                    15,
                    1,
                    0,
                    "",
                    "hash-3",
                ),
                (
                    "運営限定・白銀神姫",
                    "admin",
                    "運営",
                    "運営が広告・演出用に投入する限定カード。",
                    "限定",
                    "image",
                    "https://res.cloudinary.com/demo/image/upload/sample.jpg",
                    "",
                    "",
                    "https://example.com/admin",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "SSR",
                    28, 26, 22, 18, 16,
                    25,
                    1,
                    0,
                    "",
                    "hash-4",
                ),
            ]

            for w in base_works:
                cur.execute("""
                    INSERT INTO works(
                        title,
                        creator_id,
                        creator_name,
                        description,
                        genre,
                        type,
                        image_url,
                        video_url,
                        thumbnail_url,
                        link_url,
                        x_url,
                        booth_url,
                        chichipui_url,
                        dlsite_url,
                        fan
