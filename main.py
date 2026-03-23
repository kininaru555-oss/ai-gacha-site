import io
import os
import random
from datetime import datetime, date
from typing import Optional

import numpy as np
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, ImageFilter
from pydantic import BaseModel
import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers.creators import router as creators_router

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本番は絞る
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(creators_router)

app = FastAPI(title="Bijo Gacha Quest API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本番では Render のフロントURLに絞る
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL が設定されていません")

# Render/managed Postgres で SSL 必須のことが多いので prefer を既定に
if "sslmode=" not in DATABASE_URL:
    sep = "&" if "?" in DATABASE_URL else "?"
    DATABASE_URL = f"{DATABASE_URL}{sep}sslmode=prefer"


# =========================================================
# DB
# =========================================================
def get_db():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users(
                user_id TEXT PRIMARY KEY,
                password TEXT DEFAULT '',
                points INTEGER DEFAULT 0,
                exp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                free_draw_count INTEGER DEFAULT 1,
                revive_items INTEGER DEFAULT 0,
                royalty_balance INTEGER DEFAULT 0,
                daily_duplicate_exp INTEGER DEFAULT 0,
                last_exp_reset TEXT DEFAULT ''
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS works(
                id BIGSERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                creator_id TEXT NOT NULL,
                creator_name TEXT DEFAULT '',
                description TEXT DEFAULT '',
                genre TEXT DEFAULT '',
                type TEXT DEFAULT 'image',
                image_url TEXT DEFAULT '',
                video_url TEXT DEFAULT '',
                thumbnail_url TEXT DEFAULT '',
                link_url TEXT DEFAULT '',
                x_url TEXT DEFAULT '',
                booth_url TEXT DEFAULT '',
                chichipui_url TEXT DEFAULT '',
                dlsite_url TEXT DEFAULT '',
                rarity TEXT DEFAULT 'N',
                hp INTEGER DEFAULT 10,
                atk INTEGER DEFAULT 10,
                def INTEGER DEFAULT 10,
                spd INTEGER DEFAULT 10,
                luk INTEGER DEFAULT 10,
                exp_reward INTEGER DEFAULT 5,
                draw_count INTEGER DEFAULT 0,
                like_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                is_ball INTEGER DEFAULT 0,
                ball_code TEXT DEFAULT '',
                content_hash TEXT DEFAULT ''
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS ownership(
                work_id BIGINT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                acquired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS owned_cards(
                id BIGSERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                work_id BIGINT NOT NULL,
                rarity TEXT DEFAULT 'N',
                level INTEGER DEFAULT 1,
                exp INTEGER DEFAULT 0,
                hp INTEGER DEFAULT 10,
                atk INTEGER DEFAULT 10,
                def INTEGER DEFAULT 10,
                spd INTEGER DEFAULT 10,
                luk INTEGER DEFAULT 10,
                lose_streak_count INTEGER DEFAULT 0,
                is_legend INTEGER DEFAULT 0,
                legend_at TEXT DEFAULT ''
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS offers(
                id BIGSERIAL PRIMARY KEY,
                work_id BIGINT NOT NULL,
                from_user TEXT NOT NULL,
                to_user TEXT NOT NULL,
                points INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS market(
                id BIGSERIAL PRIMARY KEY,
                work_id BIGINT NOT NULL,
                seller TEXT NOT NULL,
                price INTEGER NOT NULL,
                status TEXT DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS battle_queue(
                id BIGSERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                work_id BIGINT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS battle_logs(
                id BIGSERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                opponent_user_id TEXT DEFAULT '',
                result TEXT DEFAULT '',
                log_text TEXT DEFAULT '',
                reward_exp INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS transactions(
                id BIGSERIAL PRIMARY KEY,
                work_id BIGINT NOT NULL,
                buyer_user_id TEXT NOT NULL,
                seller_user_id TEXT NOT NULL,
                creator_user_id TEXT NOT NULL,
                total_points INTEGER NOT NULL,
                platform_fee INTEGER NOT NULL,
                seller_share INTEGER NOT NULL,
                creator_share INTEGER NOT NULL,
                tx_type TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS withdraw_requests(
                id BIGSERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                amount INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS like_logs(
                id BIGSERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                work_id BIGINT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, work_id)
            )
            """)

            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_works_content_hash_unique ON works(content_hash)")
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_works_ball_code_unique ON works(ball_code)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ownership_owner_id ON ownership(owner_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_owned_cards_user_id ON owned_cards(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_offers_to_user ON offers(to_user)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_offers_from_user ON offers(from_user)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_market_status ON market(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_battle_queue_user_id ON battle_queue(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_battle_logs_user_id ON battle_logs(user_id)")


# =========================================================
# Models
# =========================================================
class LoginRequest(BaseModel):
    user_id: str
    password: str


class OfferRequest(BaseModel):
    from_user_id: str
    to_user_id: str
    work_id: int
    offer_points: int


class MarketListRequest(BaseModel):
    user_id: str
    work_id: int
    price_points: int


class MarketBuyRequest(BaseModel):
    buyer_user_id: str
    listing_id: int


class BattleEntryRequest(BaseModel):
    user_id: str
    work_id: int


class UserOnlyRequest(BaseModel):
    user_id: str


class WithdrawRequestIn(BaseModel):
    user_id: str
    amount: int


class LegendRequest(BaseModel):
    user_id: str
    work_id: int


class LikeRequest(BaseModel):
    user_id: str
    work_id: int


class AdminCreateWorkRequest(BaseModel):
    creator_user_id: str
    creator_name: str
    title: str
    description: str = ""
    genre: str = ""
    type: str = "image"
    image_url: str = ""
    video_url: str = ""
    thumbnail_url: str = ""
    link_url: str = ""
    x_url: str = ""
    booth_url: str = ""
    chichipui_url: str = ""
    dlsite_url: str = ""
    rarity: str = "N"
    hp: Optional[int] = None
    atk: Optional[int] = None
    defense: Optional[int] = None
    spd: Optional[int] = None
    luk: Optional[int] = None
    exp_reward: int = 5
    is_official: int = 0
    content_hash: str
    is_ball: int = 0
    ball_code: str = ""


class AutoStatRequest(BaseModel):
    image_url: str
    title: str = ""
    description: str = ""
    genre: str = ""


# =========================================================
# Helpers
# =========================================================
def today_str():
    return date.today().isoformat()


def ensure_user(conn, user_id: str):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
        user = cur.fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="ユーザーが存在しません")
    return user


def ensure_work(conn, work_id: int):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM works WHERE id=%s AND is_active=1", (work_id,))
        work = cur.fetchone()
    if not work:
        raise HTTPException(status_code=404, detail="作品が存在しません")
    return work


def reset_daily_duplicate_exp_if_needed(conn, user_id: str):
    user = ensure_user(conn, user_id)
    if user["last_exp_reset"] != today_str():
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET daily_duplicate_exp=0, last_exp_reset=%s
                WHERE user_id=%s
            """, (today_str(), user_id))


def update_user_level(conn, user_id: str):
    user = ensure_user(conn, user_id)
    level = max(1, 1 + (user["exp"] // 100))
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET level=%s WHERE user_id=%s", (level, user_id))


def get_ownership(conn, work_id: int):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM ownership WHERE work_id=%s", (work_id,))
        return cur.fetchone()


def transfer_ownership(conn, work_id: int, new_owner_id: str):
    exists = get_ownership(conn, work_id)
    with conn.cursor() as cur:
        if exists:
            cur.execute("""
                UPDATE ownership
                SET owner_id=%s, acquired_at=%s
                WHERE work_id=%s
            """, (new_owner_id, datetime.utcnow(), work_id))
        else:
            cur.execute("""
                INSERT INTO ownership(work_id, owner_id, acquired_at)
                VALUES(%s,%s,%s)
            """, (work_id, new_owner_id, datetime.utcnow()))


def get_owned_card(conn, user_id: str, work_id: int):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT * FROM owned_cards
            WHERE user_id=%s AND work_id=%s
            ORDER BY id DESC
            LIMIT 1
        """, (user_id, work_id))
        return cur.fetchone()


def create_owned_card_if_missing(conn, user_id: str, work_row):
    existing = get_owned_card(conn, user_id, work_row["id"])
    if existing:
        return existing

    user = ensure_user(conn, user_id)
    level_bonus = max(0, user["level"] - 1)

    hp = work_row["hp"] + random.randint(0, 6) + level_bonus
    atk = work_row["atk"] + random.randint(0, 6) + level_bonus
    ddef = work_row["def"] + random.randint(0, 6) + level_bonus
    spd = work_row["spd"] + random.randint(0, 4)
    luk = work_row["luk"] + random.randint(0, 4)

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO owned_cards(
                user_id, work_id, rarity, level, exp, hp, atk, def, spd, luk,
                lose_streak_count, is_legend, legend_at
            ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            user_id, work_row["id"], work_row["rarity"], 1, 0,
            hp, atk, ddef, spd, luk,
            0, 1 if work_row["rarity"] == "LEGEND" else 0, ""
        ))
    return get_owned_card(conn, user_id, work_row["id"])


def gain_duplicate_exp(conn, user_id: str, work_row):
    reset_daily_duplicate_exp_if_needed(conn, user_id)
    user = ensure_user(conn, user_id)

    exp_gain = int(work_row["exp_reward"] * 0.3)
    exp_gain = max(3, min(exp_gain, 10))

    if user["daily_duplicate_exp"] >= 100:
        return 0

    if user["daily_duplicate_exp"] + exp_gain > 100:
        exp_gain = 100 - user["daily_duplicate_exp"]

    with conn.cursor() as cur:
        cur.execute("""
            UPDATE users
            SET exp = exp + %s,
                daily_duplicate_exp = daily_duplicate_exp + %s
            WHERE user_id=%s
        """, (exp_gain, exp_gain, user_id))

    update_user_level(conn, user_id)
    return exp_gain


def weighted_draw(conn, user_id: str):
    user = ensure_user(conn, user_id)
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM works WHERE is_active=1")
        works = cur.fetchall()

    if not works:
        raise HTTPException(status_code=400, detail="排出対象がありません")

    level = user["level"]
    rarity_weights = {
        "N": max(55 - level, 20),
        "R": 25 + min(level, 10),
        "SR": min(10 + level, 24),
        "SSR": min(3 + level // 3, 10),
        "LEGEND": 1
    }

    pool = []
    for w in works:
        weight = rarity_weights.get((w["rarity"] or "N").upper(), 10)
        if w["is_ball"]:
            weight += 1
        pool.extend([w] * max(1, weight))

    return random.choice(pool)


def serialize_work(work):
    return {
        "id": work["id"],
        "title": work["title"],
        "creator_user_id": work["creator_id"],
        "creator_name": work["creator_name"],
        "description": work["description"],
        "genre": work["genre"],
        "type": work["type"],
        "image_url": work["image_url"],
        "video_url": work["video_url"],
        "thumbnail_url": work["thumbnail_url"],
        "link_url": work["link_url"],
        "x_url": work["x_url"],
        "booth_url": work["booth_url"],
        "chichipui_url": work["chichipui_url"],
        "dlsite_url": work["dlsite_url"],
        "rarity": work["rarity"],
        "hp": work["hp"],
        "atk": work["atk"],
        "def": work["def"],
        "spd": work["spd"],
        "luk": work["luk"],
        "exp_reward": work["exp_reward"],
        "draw_count": work["draw_count"],
        "likes": work["like_count"],
        "is_ball": bool(work["is_ball"]),
        "ball_code": work["ball_code"],
    }


def serialize_owned_card(conn, owned):
    work = ensure_work(conn, owned["work_id"])
    owner = get_ownership(conn, owned["work_id"])
    return {
        "id": owned["id"],
        "work_id": owned["work_id"],
        "title": work["title"],
        "creator_name": work["creator_name"],
        "type": work["type"],
        "image_url": work["image_url"],
        "video_url": work["video_url"],
        "link_url": work["link_url"],
        "rarity": owned["rarity"],
        "hp": owned["hp"],
        "atk": owned["atk"],
        "def": owned["def"],
        "spd": owned["spd"],
        "luk": owned["luk"],
        "level": owned["level"],
        "exp": owned["exp"],
        "lose_streak_count": owned["lose_streak_count"],
        "is_legend": bool(owned["is_legend"]),
        "owner_user_id": owner["owner_id"] if owner else None,
        "draw_count": work["draw_count"],
    }


def distribute_points(conn, work_id: int, buyer_user_id: str, seller_user_id: str, total_points: int, tx_type: str):
    buyer = ensure_user(conn, buyer_user_id)
    if buyer["points"] < total_points:
        raise HTTPException(status_code=400, detail="ポイント不足です")

    work = ensure_work(conn, work_id)
    creator_id = work["creator_id"]

    fee = int(total_points * 0.30)
    remain = total_points - fee
    seller_share = remain // 2
    creator_share = remain - seller_share

    with conn.cursor() as cur:
        cur.execute("UPDATE users SET points = points - %s WHERE user_id=%s", (total_points, buyer_user_id))
        cur.execute("""
            UPDATE users
            SET points = points + %s,
                royalty_balance = royalty_balance + %s
            WHERE user_id=%s
        """, (seller_share, seller_share, seller_user_id))
        cur.execute("""
            UPDATE users
            SET points = points + %s,
                royalty_balance = royalty_balance + %s
            WHERE user_id=%s
        """, (creator_share, creator_share, creator_id))
        cur.execute("""
            INSERT INTO transactions(
                work_id, buyer_user_id, seller_user_id, creator_user_id,
                total_points, platform_fee, seller_share, creator_share, tx_type
            ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            work_id, buyer_user_id, seller_user_id, creator_id,
            total_points, fee, seller_share, creator_share, tx_type
        ))

    return {
        "platform_fee": fee,
        "seller_share": seller_share,
        "creator_share": creator_share,
    }


def battle_score(card):
    return (
        card["hp"] * 0.30 +
        card["atk"] * 1.25 +
        card["def"] * 0.95 +
        card["spd"] * 0.75 +
        card["luk"] * 0.55 +
        random.randint(0, 15)
    )


def level_up_card_if_needed(conn, card_id: int):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM owned_cards WHERE id=%s", (card_id,))
        card = cur.fetchone()

    if not card:
        return

    exp = card["exp"]
    level = card["level"]
    hp = card["hp"]
    atk = card["atk"]
    ddef = card["def"]
    spd = card["spd"]
    luk = card["luk"]

    while exp >= 30:
        exp -= 30
        level += 1
        hp += 2
        atk += 2
        ddef += 2
        spd += 1
        luk += 1

    with conn.cursor() as cur:
        cur.execute("""
            UPDATE owned_cards
            SET exp=%s, level=%s, hp=%s, atk=%s, def=%s, spd=%s, luk=%s
            WHERE id=%s
        """, (exp, level, hp, atk, ddef, spd, luk, card_id))


def count_ball_codes(conn, user_id: str):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT w.ball_code
            FROM ownership o
            JOIN works w ON w.id = o.work_id
            WHERE o.owner_id = %s AND w.is_ball = 1
        """, (user_id,))
        rows = cur.fetchall()
    return len(set([r["ball_code"] for r in rows if r["ball_code"]]))


def steal_random_ball_if_any(conn, loser_id: str, winner_id: str):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT o.work_id, w.ball_code, w.title
            FROM ownership o
            JOIN works w ON w.id = o.work_id
            WHERE o.owner_id = %s AND w.is_ball = 1
        """, (loser_id,))
        balls = cur.fetchall()

    if not balls:
        return None

    target = random.choice(balls)
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE ownership
            SET owner_id=%s, acquired_at=%s
            WHERE work_id=%s
        """, (winner_id, datetime.utcnow(), target["work_id"]))
    return target["ball_code"] or target["title"]


# =========================================================
# Auto Stat AI Helpers
# =========================================================
def clamp_stat(value: float, min_value: int = 5, max_value: int = 99) -> int:
    return max(min_value, min(max_value, int(round(value))))


def fetch_image_from_url(image_url: str, timeout: int = 20) -> Image.Image:
    res = requests.get(image_url, timeout=timeout)
    res.raise_for_status()
    return Image.open(io.BytesIO(res.content)).convert("RGB")


def normalize(value: float, src_min: float, src_max: float, dst_min: float = 0.0, dst_max: float = 1.0) -> float:
    if src_max - src_min == 0:
        return dst_min
    ratio = (value - src_min) / (src_max - src_min)
    ratio = max(0.0, min(1.0, ratio))
    return dst_min + ratio * (dst_max - dst_min)


def compute_image_features(img: Image.Image):
    img_small = img.resize((256, 256))
    arr = np.asarray(img_small).astype(np.float32) / 255.0

    r = arr[:, :, 0]
    g = arr[:, :, 1]
    b = arr[:, :, 2]

    brightness = float(arr.mean())
    contrast = float(arr.std())

    rgb_mean = arr.mean(axis=2, keepdims=True)
    saturation_like = float(np.abs(arr - rgb_mean).mean())

    red_bias = float((r - (g + b) / 2.0).mean())
    blue_bias = float((b - (r + g) / 2.0).mean())
    dark_ratio = float((arr.mean(axis=2) < 0.25).mean())
    bright_ratio = float((arr.mean(axis=2) > 0.75).mean())

    gray = img_small.convert("L")
    gray_arr = np.asarray(gray).astype(np.float32) / 255.0

    edge_img = gray.filter(ImageFilter.FIND_EDGES)
    edge_arr = np.asarray(edge_img).astype(np.float32) / 255.0
    edge_strength = float(edge_arr.mean())

    sharpness = float(
        np.abs(np.diff(gray_arr, axis=0)).mean() +
        np.abs(np.diff(gray_arr, axis=1)).mean()
    )

    return {
        "brightness": brightness,
        "contrast": contrast,
        "saturation_like": saturation_like,
        "red_bias": red_bias,
        "blue_bias": blue_bias,
        "dark_ratio": dark_ratio,
        "bright_ratio": bright_ratio,
        "edge_strength": edge_strength,
        "sharpness": sharpness,
    }


def keyword_bonus(text: str):
    rules = {
        "hp": {"天使": 6, "姫": 5, "神": 7, "聖": 5, "癒し": 4, "花": 3, "月": 2, "光": 3},
        "atk": {"炎": 7, "剣": 6, "戦": 6, "魔王": 6, "竜": 5, "雷": 5, "爆": 6, "紅": 4},
        "defense": {"盾": 7, "鎧": 7, "城": 5, "要塞": 8, "闇": 4, "黒": 3, "鋼": 6},
        "spd": {"風": 7, "雷": 6, "電脳": 7, "忍": 7, "瞬": 6, "流": 4, "羽": 3},
        "luk": {"奇跡": 8, "夢": 5, "虹": 6, "星": 5, "月": 3, "運命": 7, "秘宝": 6},
    }

    result = {"hp": 0, "atk": 0, "defense": 0, "spd": 0, "luk": 0}
    joined = text or ""
    for stat_name, mapping in rules.items():
        for word, bonus in mapping.items():
            if word in joined:
                result[stat_name] += bonus
    return result


def generate_auto_stats(image_url: str, title: str = "", description: str = "", genre: str = ""):
    img = fetch_image_from_url(image_url)
    f = compute_image_features(img)

    hp = (
        20
        + normalize(f["brightness"], 0.2, 0.9, 0, 20)
        + normalize(f["bright_ratio"], 0.0, 0.7, 0, 10)
        + normalize(f["contrast"], 0.05, 0.35, 0, 8)
    )

    atk = (
        20
        + normalize(f["red_bias"], -0.2, 0.2, 0, 18)
        + normalize(f["contrast"], 0.05, 0.35, 0, 12)
        + normalize(f["saturation_like"], 0.02, 0.25, 0, 10)
    )

    defense = (
        20
        + normalize(f["dark_ratio"], 0.0, 0.8, 0, 18)
        + normalize(f["blue_bias"], -0.2, 0.2, 0, 12)
        + normalize(f["edge_strength"], 0.01, 0.18, 0, 8)
    )

    spd = (
        20
        + normalize(f["edge_strength"], 0.01, 0.18, 0, 18)
        + normalize(f["sharpness"], 0.005, 0.25, 0, 14)
        + normalize(f["contrast"], 0.05, 0.35, 0, 6)
    )

    luk = (
        20
        + normalize(f["saturation_like"], 0.02, 0.25, 0, 14)
        + normalize(f["bright_ratio"], 0.0, 0.7, 0, 8)
        + random.randint(0, 9)
    )

    bonus = keyword_bonus(f"{title} {description} {genre}")
    hp += bonus["hp"]
    atk += bonus["atk"]
    defense += bonus["defense"]
    spd += bonus["spd"]
    luk += bonus["luk"]

    return {
        "hp": clamp_stat(hp),
        "atk": clamp_stat(atk),
        "defense": clamp_stat(defense),
        "spd": clamp_stat(spd),
        "luk": clamp_stat(luk),
        "debug": f,
    }


# =========================================================
# Seed
# =========================================================
def seed_data():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users(user_id,password,points,free_draw_count)
                VALUES(%s,%s,%s,%s)
                ON CONFLICT (user_id) DO NOTHING
            """, ("admin", "admin123", 9999, 99))
            cur.execute("""
                INSERT INTO users(user_id,password,points,free_draw_count)
                VALUES(%s,%s,%s,%s)
                ON CONFLICT (user_id) DO NOTHING
            """, ("creator1", "1234", 100, 3))
            cur.execute("""
                INSERT INTO users(user_id,password,points,free_draw_count)
                VALUES(%s,%s,%s,%s)
                ON CONFLICT (user_id) DO NOTHING
            """, ("creator2", "1234", 100, 3))

            base_works = [
                (
                    "月下の魔導姫", "creator1", "投稿者1", "銀髪の二次元美少女イラスト", "ファンタジー",
                    "image", "https://res.cloudinary.com/demo/image/upload/sample.jpg", "", "",
                    "https://example.com/creator1", "https://x.com", "https://booth.pm",
                    "https://www.chichi-pui.com/", "", "N", 18, 12, 11, 10, 8, 8, 0, "", "hash-1"
                ),
                (
                    "深紅の踊り子", "creator1", "投稿者1", "華やかな二次元キャラ", "和風",
                    "image", "https://res.cloudinary.com/demo/image/upload/sample.jpg", "", "",
                    "https://example.com/creator1", "", "", "", "", "R", 20, 16, 12, 15, 10, 10, 0, "", "hash-2"
                ),
                (
                    "電脳天使ユリナ", "creator2", "投稿者2", "近未来系の二次元動画カード", "SF",
                    "video", "", "https://www.w3schools.com/html/mov_bbb.mp4", "",
                    "https://example.com/creator2", "", "", "", "", "SR", 22, 20, 16, 18, 12, 15, 0, "", "hash-3"
                ),
                (
                    "運営限定・白銀神姫", "admin", "運営", "運営カード。経験値ボーナス対象。", "限定",
                    "image", "https://res.cloudinary.com/demo/image/upload/sample.jpg", "", "",
                    "https://example.com/admin", "", "", "", "", "SSR", 28, 26, 22, 18, 16, 25, 0, "", "hash-4"
                ),
            ]

            for w in base_works:
                cur.execute("""
                    INSERT INTO works(
                        title, creator_id, creator_name, description, genre, type,
                        image_url, video_url, thumbnail_url, link_url, x_url, booth_url, chichipui_url, dlsite_url,
                        rarity, hp, atk, def, spd, luk, exp_reward, is_ball, ball_code, content_hash
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (content_hash) DO NOTHING
                """, w)

            for i in range(1, 8):
                cur.execute("""
                    INSERT INTO works(
                        title, creator_id, creator_name, description, genre, type,
                        image_url, video_url, thumbnail_url, link_url, x_url, booth_url, chichipui_url, dlsite_url,
                        rarity, hp, atk, def, spd, luk, exp_reward, is_ball, ball_code, content_hash
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (content_hash) DO NOTHING
                """, (
                    f"トラゴンボウル {i}",
                    "admin",
                    "運営",
                    "7つ集めるとレジェンド化できます。",
                    "アイテム",
                    "image",
                    "https://res.cloudinary.com/demo/image/upload/sample.jpg",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "R",
                    5, 5, 5, 5, 5,
                    3,
                    1,
                    f"BALL_{i}",
                    f"ball-hash-{i}"
                ))


init_db()
seed_data()

# =========================================================
# Routes Part 1
# =========================================================
@app.get("/")
def root():
    return {"message": "Bijo Gacha Quest API running"}


@app.post("/auth/login")
def auth_login(payload: LoginRequest):
    with get_db() as conn:
        user = None
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE user_id=%s", (payload.user_id,))
            user = cur.fetchone()

            if user:
                if user["password"] != payload.password:
                    raise HTTPException(status_code=401, detail="パスワードが違います")
            else:
                cur.execute("""
                    INSERT INTO users(user_id, password, points, exp, level, free_draw_count)
                    VALUES(%s,%s,%s,%s,%s,%s)
                """, (payload.user_id, payload.password, 0, 0, 1, 1))

        reset_daily_duplicate_exp_if_needed(conn, payload.user_id)
        user = ensure_user(conn, payload.user_id)
        ball_count = count_ball_codes(conn, payload.user_id)

        return {
            "user_id": user["user_id"],
            "points": user["points"],
            "exp": user["exp"],
            "level": user["level"],
            "free_draw_count": user["free_draw_count"],
            "revive_item_count": user["revive_items"],
            "royalty_balance": user["royalty_balance"],
            "ball_count": ball_count,
        }


@app.get("/users/{user_id}")
def get_user(user_id: str):
    with get_db() as conn:
        reset_daily_duplicate_exp_if_needed(conn, user_id)
        user = ensure_user(conn, user_id)

        return {
            "user_id": user["user_id"],
            "points": user["points"],
            "exp": user["exp"],
            "level": user["level"],
            "free_draw_count": user["free_draw_count"],
            "revive_item_count": user["revive_items"],
            "royalty_balance": user["royalty_balance"],
            "ball_count": count_ball_codes(conn, user_id),
            "daily_duplicate_exp": user["daily_duplicate_exp"],
        }


def process_gacha(conn, user_id: str, draw_type: str):
    work = weighted_draw(conn, user_id)

    with conn.cursor() as cur:
        cur.execute("UPDATE works SET draw_count = draw_count + 1 WHERE id=%s", (work["id"],))

    owner = get_ownership(conn, work["id"])

    is_new_owner = owner is None
    if is_new_owner:
        transfer_ownership(conn, work["id"], user_id)
        create_owned_card_if_missing(conn, user_id, work)
        exp_gained = work["exp_reward"]

        with conn.cursor() as cur:
            cur.execute("UPDATE users SET exp = exp + %s WHERE user_id=%s", (exp_gained, user_id))
        update_user_level(conn, user_id)
        owner_user_id = user_id
    else:
        exp_gained = gain_duplicate_exp(conn, user_id, work)
        owner_user_id = owner["owner_id"]

    if draw_type == "paid":
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET points = points + 10,
                    royalty_balance = royalty_balance + 10
                WHERE user_id=%s
            """, (work["creator_id"],))

    work = ensure_work(conn, work["id"])

    return {
        "message": "ガチャ完了",
        "result": serialize_work(work),
        "info": {
            "is_new_owner": is_new_owner,
            "owner_user_id": owner_user_id,
            "exp_gained": exp_gained,
        }
    }


@app.post("/gacha/free/{user_id}")
def gacha_free(user_id: str):
    with get_db() as conn:
        user = ensure_user(conn, user_id)

        if user["free_draw_count"] <= 0:
            raise HTTPException(status_code=400, detail="無料ガチャ回数がありません")

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET free_draw_count = free_draw_count - 1 WHERE user_id=%s",
                (user_id,)
            )

        return process_gacha(conn, user_id, "free")


@app.post("/gacha/paid/{user_id}")
def gacha_paid(user_id: str):
    with get_db() as conn:
        user = ensure_user(conn, user_id)

        if user["points"] < 30:
            raise HTTPException(status_code=400, detail="ポイント不足です")

        with conn.cursor() as cur:
            cur.execute("UPDATE users SET points = points - 30 WHERE user_id=%s", (user_id,))

        result = process_gacha(conn, user_id, "paid")
        result["message"] = "ポイントガチャ完了"
        return result


@app.post("/works/{work_id}/like")
def like_work(work_id: int, payload: LikeRequest):
    with get_db() as conn:
        ensure_user(conn, payload.user_id)
        ensure_work(conn, work_id)

        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO like_logs(user_id, work_id) VALUES(%s,%s)",
                    (payload.user_id, work_id)
                )
                cur.execute("UPDATE works SET like_count = like_count + 1 WHERE id=%s", (work_id,))
        except Exception:
            likes = ensure_work(conn, work_id)["like_count"]
            return {"message": "すでにいいね済みです", "likes": likes}

        likes = ensure_work(conn, work_id)["like_count"]
        return {"message": "いいねしました", "likes": likes}


@app.get("/users/{user_id}/works")
def get_user_works(user_id: str):
    with get_db() as conn:
        ensure_user(conn, user_id)

        with conn.cursor() as cur:
            cur.execute("""
                SELECT oc.*
                FROM owned_cards oc
                JOIN ownership o ON o.work_id = oc.work_id
                WHERE o.owner_id = %s AND oc.user_id = %s
                ORDER BY oc.id DESC
            """, (user_id, user_id))
            rows = cur.fetchall()

        items = [serialize_owned_card(conn, row) for row in rows]
        return {"works": items}


@app.post("/battle/entry")
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
                cur.execute(
                    "INSERT INTO battle_queue(user_id, work_id) VALUES(%s,%s)",
                    (payload.user_id, payload.work_id)
                )
            return {"message": "対戦待機に入りました。次の参加者とバトルします。"}

        opp_user_id = waiting["user_id"]
        opp_work_id = waiting["work_id"]
        opp_card = get_owned_card(conn, opp_user_id, opp_work_id)

        if not opp_card:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM battle_queue WHERE id=%s", (waiting["id"],))
            return {"message": "相手の待機データが壊れていました。再度参加してください。"}

        score_me = battle_score(my_card)
        score_opp = battle_score(opp_card)

        if abs(score_me - score_opp) < 4:
            result_me = "draw"
            result_opp = "draw"
            exp_me = 5
            exp_opp = 5
            log_text = f"接戦で引き分け。A={score_me:.1f} / B={score_opp:.1f}"
        elif score_me > score_opp:
            result_me = "win"
            result_opp = "lose"
            exp_me = 15
            exp_opp = 5
            log_text = f"総合力で勝利。A={score_me:.1f} / B={score_opp:.1f}"
        else:
            result_me = "lose"
            result_opp = "win"
            exp_me = 5
            exp_opp = 15
            log_text = f"相手が上回り敗北。A={score_me:.1f} / B={score_opp:.1f}"

        extra = []

        with conn.cursor() as cur:
            cur.execute("UPDATE owned_cards SET exp = exp + %s WHERE id=%s", (exp_me, my_card["id"]))
            cur.execute("UPDATE owned_cards SET exp = exp + %s WHERE id=%s", (exp_opp, opp_card["id"]))
            cur.execute("UPDATE users SET exp = exp + %s WHERE user_id=%s", (exp_me, payload.user_id))
            cur.execute("UPDATE users SET exp = exp + %s WHERE user_id=%s", (exp_opp, opp_user_id))

        if result_me == "lose":
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE owned_cards
                    SET lose_streak_count = lose_streak_count + 1
                    WHERE id=%s
                """, (my_card["id"],))
                cur.execute("SELECT lose_streak_count FROM owned_cards WHERE id=%s", (my_card["id"],))
                updated = cur.fetchone()

            if updated["lose_streak_count"] >= 3:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE owned_cards
                        SET lose_streak_count = 0, exp = exp + 20
                        WHERE id=%s
                    """, (my_card["id"],))
                    cur.execute("UPDATE users SET exp = exp + 20 WHERE user_id=%s", (payload.user_id,))
                extra.append("3敗ボーナスでEXP+20")
        elif result_me == "win":
            with conn.cursor() as cur:
                cur.execute("UPDATE owned_cards SET lose_streak_count = 0 WHERE id=%s", (my_card["id"],))

        if result_opp == "lose":
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE owned_cards
                    SET lose_streak_count = lose_streak_count + 1
                    WHERE id=%s
                """, (opp_card["id"],))
                cur.execute("SELECT lose_streak_count FROM owned_cards WHERE id=%s", (opp_card["id"],))
                updated = cur.fetchone()

            if updated["lose_streak_count"] >= 3:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE owned_cards
                        SET lose_streak_count = 0, exp = exp + 20
                        WHERE id=%s
                    """, (opp_card["id"],))
                    cur.execute("UPDATE users SET exp = exp + 20 WHERE user_id=%s", (opp_user_id,))
        elif result_opp == "win":
            with conn.cursor() as cur:
                cur.execute("UPDATE owned_cards SET lose_streak_count = 0 WHERE id=%s", (opp_card["id"],))

        my_user = ensure_user(conn, payload.user_id)
        opp_user = ensure_user(conn, opp_user_id)

        if result_me == "lose" and my_user["revive_items"] > 0:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET revive_items = revive_items - 1 WHERE user_id=%s", (payload.user_id,))
            result_me = "draw"
            extra.append("復活アイテム発動")
        elif result_opp == "lose" and opp_user["revive_items"] > 0:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET revive_items = revive_items - 1 WHERE user_id=%s", (opp_user_id,))
            result_opp = "draw"

        ball_stolen = None
        if result_me == "win":
            ball_stolen = steal_random_ball_if_any(conn, opp_user_id, payload.user_id)
        elif result_me == "lose":
            ball_stolen = steal_random_ball_if_any(conn, payload.user_id, opp_user_id)

        if ball_stolen:
            extra.append(f"トラゴンボウル奪取: {ball_stolen}")

        level_up_card_if_needed(conn, my_card["id"])
        level_up_card_if_needed(conn, opp_card["id"])
        update_user_level(conn, payload.user_id)
        update_user_level(conn, opp_user_id)

        full_log = log_text + (" / " + " / ".join(extra) if extra else "")

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO battle_logs(user_id, opponent_user_id, result, log_text, reward_exp)
                VALUES(%s,%s,%s,%s,%s)
            """, (payload.user_id, opp_user_id, result_me, full_log, exp_me))

            cur.execute("""
                INSERT INTO battle_logs(user_id, opponent_user_id, result, log_text, reward_exp)
                VALUES(%s,%s,%s,%s,%s)
            """, (opp_user_id, payload.user_id, result_opp, full_log, exp_opp))

            cur.execute("DELETE FROM battle_queue WHERE id=%s", (waiting["id"],))

        return {
            "message": "バトルが完了しました",
            "result": result_me,
            "log": full_log,
            "reward_exp": exp_me
        }


@app.get("/battle/logs/{user_id}")
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
            "created_at": r["created_at"].isoformat() if r["created_at"] else ""
        } for r in rows]

        return {"logs": items}


@app.post("/rewards/ad-xp")
def reward_ad_xp(payload: UserOnlyRequest):
    with get_db() as conn:
        ensure_user(conn, payload.user_id)

        with conn.cursor() as cur:
            cur.execute("UPDATE users SET exp = exp + 20 WHERE user_id=%s", (payload.user_id,))

        update_user_level(conn, payload.user_id)
        user = ensure_user(conn, payload.user_id)

        return {
            "message": "広告報酬でEXP 20 を付与しました",
            "exp": user["exp"],
            "level": user["level"]
        }


@app.post("/items/revive/buy")
def buy_revive(payload: UserOnlyRequest):
    with get_db() as conn:
        user = ensure_user(conn, payload.user_id)

        if user["points"] < 100:
            raise HTTPException(status_code=400, detail="ポイント不足です")

        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET points = points - 100,
                    revive_items = revive_items + 1
                WHERE user_id=%s
            """, (payload.user_id,))

        user = ensure_user(conn, payload.user_id)

        return {
            "message": "復活アイテムを購入しました",
            "revive_item_count": user["revive_items"],
            "points": user["points"]
    }

# =========================================================
# Routes Part 2
# =========================================================
@app.post("/offers")
def send_offer(payload: OfferRequest):
    with get_db() as conn:
        ensure_user(conn, payload.from_user_id)
        ensure_user(conn, payload.to_user_id)
        ensure_work(conn, payload.work_id)

        owner = get_ownership(conn, payload.work_id)
        if not owner:
            raise HTTPException(status_code=400, detail="未所有作品にはオファーできません")
        if owner["owner_id"] != payload.to_user_id:
            raise HTTPException(status_code=400, detail="宛先が現在の所有者ではありません")
        if payload.from_user_id == payload.to_user_id:
            raise HTTPException(status_code=400, detail="自分の作品にはオファーできません")

        sender = ensure_user(conn, payload.from_user_id)
        if sender["points"] < payload.offer_points:
            raise HTTPException(status_code=400, detail="ポイント不足です")

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO offers(work_id, from_user, to_user, points, status)
                VALUES(%s,%s,%s,%s,%s)
            """, (payload.work_id, payload.from_user_id, payload.to_user_id, payload.offer_points, "pending"))

        return {"message": "オファーを送信しました"}


@app.get("/offers/{user_id}")
def get_offers(user_id: str):
    with get_db() as conn:
        ensure_user(conn, user_id)

        with conn.cursor() as cur:
            cur.execute("""
                SELECT o.*, w.title AS work_title
                FROM offers o
                JOIN works w ON w.id = o.work_id
                WHERE o.to_user=%s
                ORDER BY o.id DESC
            """, (user_id,))
            incoming = cur.fetchall()

            cur.execute("""
                SELECT o.*, w.title AS work_title
                FROM offers o
                JOIN works w ON w.id = o.work_id
                WHERE o.from_user=%s
                ORDER BY o.id DESC
            """, (user_id,))
            outgoing = cur.fetchall()

        return {
            "incoming": [dict(x) for x in incoming],
            "outgoing": [dict(x) for x in outgoing]
        }


@app.post("/offers/{offer_id}/accept")
def accept_offer(offer_id: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM offers WHERE id=%s", (offer_id,))
            offer = cur.fetchone()

        if not offer:
            raise HTTPException(status_code=404, detail="オファーが存在しません")
        if offer["status"] != "pending":
            raise HTTPException(status_code=400, detail="このオファーは処理済みです")

        owner = get_ownership(conn, offer["work_id"])
        if not owner or owner["owner_id"] != offer["to_user"]:
            raise HTTPException(status_code=400, detail="現在の所有者が一致しません")

        shares = distribute_points(
            conn,
            offer["work_id"],
            offer["from_user"],
            offer["to_user"],
            offer["points"],
            "offer"
        )
        transfer_ownership(conn, offer["work_id"], offer["from_user"])

        work = ensure_work(conn, offer["work_id"])
        create_owned_card_if_missing(conn, offer["from_user"], work)

        with conn.cursor() as cur:
            cur.execute("UPDATE offers SET status='accepted' WHERE id=%s", (offer_id,))
            cur.execute("""
                UPDATE offers
                SET status='cancelled'
                WHERE work_id=%s AND status='pending' AND id<>%s
            """, (offer["work_id"], offer_id))

        return {
            "message": "オファーを承認しました。所有権を移転しました。",
            "shares": shares
        }


@app.post("/offers/{offer_id}/reject")
def reject_offer(offer_id: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM offers WHERE id=%s", (offer_id,))
            offer = cur.fetchone()

        if not offer:
            raise HTTPException(status_code=404, detail="オファーが存在しません")
        if offer["status"] != "pending":
            raise HTTPException(status_code=400, detail="このオファーは処理済みです")

        with conn.cursor() as cur:
            cur.execute("UPDATE offers SET status='rejected' WHERE id=%s", (offer_id,))

        return {"message": "オファーを拒否しました"}


@app.post("/market/list")
def list_market(payload: MarketListRequest):
    with get_db() as conn:
        ensure_user(conn, payload.user_id)
        ensure_work(conn, payload.work_id)

        owner = get_ownership(conn, payload.work_id)
        if not owner or owner["owner_id"] != payload.user_id:
            raise HTTPException(status_code=400, detail="所有者のみ出品できます")

        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM market
                WHERE work_id=%s AND status='open'
                LIMIT 1
            """, (payload.work_id,))
            open_listing = cur.fetchone()

        if open_listing:
            raise HTTPException(status_code=400, detail="すでに公開売却中です")

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO market(work_id, seller, price, status)
                VALUES(%s,%s,%s,%s)
            """, (payload.work_id, payload.user_id, payload.price_points, "open"))

        return {"message": "公開売却に出品しました"}


@app.get("/market/listings")
def get_market_listings():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    m.id AS listing_id,
                    m.work_id,
                    m.seller AS seller_user_id,
                    m.price AS price_points,
                    w.title,
                    w.creator_name,
                    w.image_url,
                    w.video_url,
                    w.link_url,
                    w.draw_count,
                    oc.rarity,
                    oc.hp,
                    oc.atk,
                    oc.def,
                    oc.level,
                    oc.is_legend
                FROM market m
                JOIN works w ON w.id = m.work_id
                LEFT JOIN owned_cards oc ON oc.work_id = m.work_id AND oc.user_id = m.seller
                WHERE m.status='open'
                ORDER BY m.id DESC
            """)
            rows = cur.fetchall()

        return {"items": [dict(x) for x in rows]}


@app.post("/market/buy")
def buy_market(payload: MarketBuyRequest):
    with get_db() as conn:
        ensure_user(conn, payload.buyer_user_id)

        with conn.cursor() as cur:
            cur.execute("SELECT * FROM market WHERE id=%s", (payload.listing_id,))
            listing = cur.fetchone()

        if not listing:
            raise HTTPException(status_code=404, detail="出品が存在しません")
        if listing["status"] != "open":
            raise HTTPException(status_code=400, detail="この出品は購入できません")
        if listing["seller"] == payload.buyer_user_id:
            raise HTTPException(status_code=400, detail="自分の出品は購入できません")

        owner = get_ownership(conn, listing["work_id"])
        if not owner or owner["owner_id"] != listing["seller"]:
            raise HTTPException(status_code=400, detail="現在の所有者が一致しません")

        shares = distribute_points(
            conn,
            listing["work_id"],
            payload.buyer_user_id,
            listing["seller"],
            listing["price"],
            "market"
        )
        transfer_ownership(conn, listing["work_id"], payload.buyer_user_id)

        work = ensure_work(conn, listing["work_id"])
        create_owned_card_if_missing(conn, payload.buyer_user_id, work)

        with conn.cursor() as cur:
            cur.execute("UPDATE market SET status='sold' WHERE id=%s", (payload.listing_id,))
            cur.execute("""
                UPDATE offers
                SET status='cancelled'
                WHERE work_id=%s AND status='pending'
            """, (listing["work_id"],))

        return {
            "message": "購入しました。所有権を移転しました。",
            "shares": shares
        }


@app.post("/withdraw/request")
def withdraw_request(payload: WithdrawRequestIn):
    with get_db() as conn:
        user = ensure_user(conn, payload.user_id)

        if payload.amount < 1000:
            raise HTTPException(status_code=400, detail="1000以上から出金申請できます")
        if user["royalty_balance"] < payload.amount:
            raise HTTPException(status_code=400, detail="出金可能残高が不足しています")

        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET royalty_balance = royalty_balance - %s
                WHERE user_id=%s
            """, (payload.amount, payload.user_id))

            cur.execute("""
                INSERT INTO withdraw_requests(user_id, amount, status)
                VALUES(%s,%s,%s)
            """, (payload.user_id, payload.amount, "pending"))

        return {"message": "出金申請を受け付けました"}


@app.post("/legend/activate")
def legend_activate(payload: LegendRequest):
    with get_db() as conn:
        ensure_user(conn, payload.user_id)
        owner = get_ownership(conn, payload.work_id)

        if not owner or owner["owner_id"] != payload.user_id:
            raise HTTPException(status_code=400, detail="所有作品のみレジェンド化できます")

        if count_ball_codes(conn, payload.user_id) < 7:
            raise HTTPException(status_code=400, detail="トラゴンボウル7種が揃っていません")

        card = get_owned_card(conn, payload.user_id, payload.work_id)
        if not card:
            raise HTTPException(status_code=404, detail="所有カードがありません")
        if card["is_legend"]:
            raise HTTPException(status_code=400, detail="すでにレジェンド化済みです")

        with conn.cursor() as cur:
            cur.execute("""
                UPDATE owned_cards
                SET is_legend=1,
                    legend_at=%s,
                    rarity='LEGEND',
                    hp = hp + 15,
                    atk = atk + 15,
                    def = def + 15,
                    spd = spd + 10,
                    luk = luk + 10
                WHERE id=%s
            """, (datetime.utcnow().isoformat(), card["id"]))

            cur.execute("UPDATE works SET rarity='LEGEND' WHERE id=%s", (payload.work_id,))

            cur.execute("""
                SELECT o.work_id
                FROM ownership o
                JOIN works w ON w.id = o.work_id
                WHERE o.owner_id=%s AND w.is_ball=1
            """, (payload.user_id,))
            ball_rows = cur.fetchall()

            for row in ball_rows:
                cur.execute("DELETE FROM ownership WHERE work_id=%s", (row["work_id"],))

        return {"message": "レジェンド化しました。トラゴンボウル7個は消費されました。"}


@app.get("/balls/{user_id}")
def get_balls(user_id: str):
    with get_db() as conn:
        ensure_user(conn, user_id)

        with conn.cursor() as cur:
            cur.execute("""
                SELECT w.id AS work_id, w.title, w.ball_code, w.image_url
                FROM ownership o
                JOIN works w ON w.id = o.work_id
                WHERE o.owner_id=%s AND w.is_ball=1
                ORDER BY w.ball_code ASC
            """, (user_id,))
            rows = cur.fetchall()

        return {"count": len(rows), "items": [dict(x) for x in rows]}


@app.get("/works")
def get_works():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM works WHERE is_active=1 ORDER BY id DESC")
            rows = cur.fetchall()

        return {"works": [serialize_work(x) for x in rows]}


@app.post("/ai/generate-stats")
def ai_generate_stats(payload: AutoStatRequest):
    try:
        stats = generate_auto_stats(
            image_url=payload.image_url,
            title=payload.title,
            description=payload.description,
            genre=payload.genre
        )
        return stats
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"自動ステータス生成失敗: {str(e)}")


@app.post("/admin/works/create")
def admin_create_work(payload: AdminCreateWorkRequest):
    with get_db() as conn:
        ensure_user(conn, payload.creator_user_id)

        if not payload.content_hash.strip():
            raise HTTPException(status_code=400, detail="content_hash は必須です")

        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM works WHERE content_hash=%s LIMIT 1",
                (payload.content_hash.strip(),)
            )
            dup = cur.fetchone()

        if dup:
            raise HTTPException(status_code=400, detail="同一コンテンツは禁止です")

        if payload.is_ball and payload.ball_code.strip():
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM works WHERE ball_code=%s LIMIT 1",
                    (payload.ball_code.strip(),)
                )
                dup_ball = cur.fetchone()
            if dup_ball:
                raise HTTPException(status_code=400, detail="同じball_codeは使えません")

        if payload.type == "image" and not payload.image_url.strip():
            raise HTTPException(status_code=400, detail="imageタイプには image_url が必要です")

        if payload.type == "video" and not payload.video_url.strip():
            raise HTTPException(status_code=400, detail="videoタイプには video_url が必要です")

        hp = payload.hp
        atk = payload.atk
        defense = payload.defense
        spd = payload.spd
        luk = payload.luk

        if payload.type == "image" and (
            hp is None or atk is None or defense is None or spd is None or luk is None
        ):
            try:
                auto_stats = generate_auto_stats(
                    image_url=payload.image_url,
                    title=payload.title,
                    description=payload.description,
                    genre=payload.genre,
                )
                hp = hp if hp is not None else auto_stats["hp"]
                atk = atk if atk is not None else auto_stats["atk"]
                defense = defense if defense is not None else auto_stats["defense"]
                spd = spd if spd is not None else auto_stats["spd"]
                luk = luk if luk is not None else auto_stats["luk"]
            except Exception:
                hp = hp if hp is not None else 10
                atk = atk if atk is not None else 10
                defense = defense if defense is not None else 10
                spd = spd if spd is not None else 10
                luk = luk if luk is not None else 10
        else:
            hp = hp if hp is not None else 10
            atk = atk if atk is not None else 10
            defense = defense if defense is not None else 10
            spd = spd if spd is not None else 10
            luk = luk if luk is not None else 10

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO works(
                    title, creator_id, creator_name, description, genre, type,
                    image_url, video_url, thumbnail_url, link_url, x_url, booth_url, chichipui_url, dlsite_url,
                    rarity, hp, atk, def, spd, luk, exp_reward,
                    is_active, is_ball, ball_code, content_hash
                ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
            """, (
                payload.title,
                payload.creator_user_id,
                payload.creator_name,
                payload.description,
                payload.genre,
                payload.type,
                payload.image_url,
                payload.video_url,
                payload.thumbnail_url,
                payload.link_url,
                payload.x_url,
                payload.booth_url,
                payload.chichipui_url,
                payload.dlsite_url,
                payload.rarity,
                int(hp),
                int(atk),
                int(defense),
                int(spd),
                int(luk),
                int(payload.exp_reward),
                1,
                int(payload.is_ball),
                payload.ball_code,
                payload.content_hash.strip(),
            ))
            inserted = cur.fetchone()
            work_id = inserted["id"]

            cur.execute("""
                UPDATE users
                SET free_draw_count = free_draw_count + 1
                WHERE user_id=%s
            """, (payload.creator_user_id,))

        work = ensure_work(conn, work_id)
        user = ensure_user(conn, payload.creator_user_id)

        return {
            "message": "作品を登録しました。投稿者に無料ガチャ1回を付与しました。",
            "work": serialize_work(work),
            "creator_free_draw_count": user["free_draw_count"]
        }


@app.post("/admin/points/add/{user_id}")
def admin_add_points(user_id: str, points: int):
    with get_db() as conn:
        ensure_user(conn, user_id)

        if points <= 0:
            raise HTTPException(status_code=400, detail="ポイントは1以上にしてください")

        with conn.cursor() as cur:
            cur.execute("UPDATE users SET points = points + %s WHERE user_id=%s", (points, user_id))

        user = ensure_user(conn, user_id)
        return {
            "message": f"{user_id} に {points}pt 追加しました",
            "points": user["points"]
        }


@app.post("/admin/free-draw/add/{user_id}")
def admin_add_free_draw(user_id: str, count: int = 1):
    with get_db() as conn:
        ensure_user(conn, user_id)

        if count <= 0:
            raise HTTPException(status_code=400, detail="回数は1以上にしてください")

        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET free_draw_count = free_draw_count + %s
                WHERE user_id=%s
            """, (count, user_id))

        user = ensure_user(conn, user_id)
        return {
            "message": f"{user_id} に無料ガチャ {count} 回追加しました",
            "free_draw_count": user["free_draw_count"]
            }
