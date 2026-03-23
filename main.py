from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3
import random
import io
from datetime import datetime, date
from typing import Optional

import requests
import numpy as np
from PIL import Image, ImageFilter

app = FastAPI(title="Bijo Gacha Quest API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB = "app.db"


# =========================================================
# DB
# =========================================================
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

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
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        work_id INTEGER PRIMARY KEY,
        owner_id TEXT NOT NULL,
        acquired_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS owned_cards(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        work_id INTEGER NOT NULL,
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
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        work_id INTEGER NOT NULL,
        from_user TEXT NOT NULL,
        to_user TEXT NOT NULL,
        points INTEGER NOT NULL,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS market(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        work_id INTEGER NOT NULL,
        seller TEXT NOT NULL,
        price INTEGER NOT NULL,
        status TEXT DEFAULT 'open',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS battle_queue(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        work_id INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS battle_logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        opponent_user_id TEXT DEFAULT '',
        result TEXT DEFAULT '',
        log_text TEXT DEFAULT '',
        reward_exp INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS transactions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        work_id INTEGER NOT NULL,
        buyer_user_id TEXT NOT NULL,
        seller_user_id TEXT NOT NULL,
        creator_user_id TEXT NOT NULL,
        total_points INTEGER NOT NULL,
        platform_fee INTEGER NOT NULL,
        seller_share INTEGER NOT NULL,
        creator_share INTEGER NOT NULL,
        tx_type TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS withdraw_requests(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        amount INTEGER NOT NULL,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS like_logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        work_id INTEGER NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, work_id)
    )
    """)

    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_works_content_hash_unique ON works(content_hash)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_works_ball_code_unique ON works(ball_code)")

    conn.commit()
    conn.close()


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
# Basic Helpers
# =========================================================
def row_to_dict(row):
    return dict(row) if row else None


def today_str():
    return date.today().isoformat()


def ensure_user(conn, user_id: str):
    cur = conn.cursor()
    user = cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="ユーザーが存在しません")
    return user


def ensure_work(conn, work_id: int):
    cur = conn.cursor()
    work = cur.execute("SELECT * FROM works WHERE id=? AND is_active=1", (work_id,)).fetchone()
    if not work:
        raise HTTPException(status_code=404, detail="作品が存在しません")
    return work


def reset_daily_duplicate_exp_if_needed(conn, user_id: str):
    cur = conn.cursor()
    user = ensure_user(conn, user_id)
    if user["last_exp_reset"] != today_str():
        cur.execute("""
            UPDATE users
            SET daily_duplicate_exp=0, last_exp_reset=?
            WHERE user_id=?
        """, (today_str(), user_id))
        conn.commit()


def update_user_level(conn, user_id: str):
    cur = conn.cursor()
    user = ensure_user(conn, user_id)
    level = max(1, 1 + (user["exp"] // 100))
    cur.execute("UPDATE users SET level=? WHERE user_id=?", (level, user_id))
    conn.commit()


def get_ownership(conn, work_id: int):
    cur = conn.cursor()
    return cur.execute("SELECT * FROM ownership WHERE work_id=?", (work_id,)).fetchone()


def transfer_ownership(conn, work_id: int, new_owner_id: str):
    cur = conn.cursor()
    exists = get_ownership(conn, work_id)
    if exists:
        cur.execute("""
            UPDATE ownership
            SET owner_id=?, acquired_at=?
            WHERE work_id=?
        """, (new_owner_id, datetime.utcnow().isoformat(), work_id))
    else:
        cur.execute("""
            INSERT INTO ownership(work_id, owner_id, acquired_at)
            VALUES(?,?,?)
        """, (work_id, new_owner_id, datetime.utcnow().isoformat()))
    conn.commit()


def get_owned_card(conn, user_id: str, work_id: int):
    cur = conn.cursor()
    return cur.execute("""
        SELECT * FROM owned_cards
        WHERE user_id=? AND work_id=?
        ORDER BY id DESC
        LIMIT 1
    """, (user_id, work_id)).fetchone()


def create_owned_card_if_missing(conn, user_id: str, work_row):
    cur = conn.cursor()
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

    cur.execute("""
        INSERT INTO owned_cards(
            user_id, work_id, rarity, level, exp, hp, atk, def, spd, luk,
            lose_streak_count, is_legend, legend_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        user_id, work_row["id"], work_row["rarity"], 1, 0,
        hp, atk, ddef, spd, luk,
        0, 1 if work_row["rarity"] == "LEGEND" else 0, ""
    ))
    conn.commit()
    return get_owned_card(conn, user_id, work_row["id"])


def gain_duplicate_exp(conn, user_id: str, work_row):
    reset_daily_duplicate_exp_if_needed(conn, user_id)
    cur = conn.cursor()
    user = ensure_user(conn, user_id)

    exp_gain = int(work_row["exp_reward"] * 0.3)
    exp_gain = max(3, min(exp_gain, 10))

    if user["daily_duplicate_exp"] >= 100:
        return 0

    if user["daily_duplicate_exp"] + exp_gain > 100:
        exp_gain = 100 - user["daily_duplicate_exp"]

    cur.execute("""
        UPDATE users
        SET exp = exp + ?, daily_duplicate_exp = daily_duplicate_exp + ?
        WHERE user_id=?
    """, (exp_gain, exp_gain, user_id))
    conn.commit()
    update_user_level(conn, user_id)
    return exp_gain


def weighted_draw(conn, user_id: str):
    cur = conn.cursor()
    user = ensure_user(conn, user_id)
    works = cur.execute("SELECT * FROM works WHERE is_active=1").fetchall()

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
    cur = conn.cursor()

    buyer = ensure_user(conn, buyer_user_id)
    if buyer["points"] < total_points:
        raise HTTPException(status_code=400, detail="ポイント不足です")

    work = ensure_work(conn, work_id)
    creator_id = work["creator_id"]

    fee = int(total_points * 0.30)
    remain = total_points - fee
    seller_share = remain // 2
    creator_share = remain - seller_share

    cur.execute("UPDATE users SET points = points - ? WHERE user_id=?", (total_points, buyer_user_id))
    cur.execute(
        "UPDATE users SET points = points + ?, royalty_balance = royalty_balance + ? WHERE user_id=?",
        (seller_share, seller_share, seller_user_id)
    )
    cur.execute(
        "UPDATE users SET points = points + ?, royalty_balance = royalty_balance + ? WHERE user_id=?",
        (creator_share, creator_share, creator_id)
    )

    cur.execute("""
        INSERT INTO transactions(
            work_id, buyer_user_id, seller_user_id, creator_user_id,
            total_points, platform_fee, seller_share, creator_share, tx_type
        ) VALUES(?,?,?,?,?,?,?,?,?)
    """, (
        work_id, buyer_user_id, seller_user_id, creator_id,
        total_points, fee, seller_share, creator_share, tx_type
    ))
    conn.commit()

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
    cur = conn.cursor()
    card = cur.execute("SELECT * FROM owned_cards WHERE id=?", (card_id,)).fetchone()
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

    cur.execute("""
        UPDATE owned_cards
        SET exp=?, level=?, hp=?, atk=?, def=?, spd=?, luk=?
        WHERE id=?
    """, (exp, level, hp, atk, ddef, spd, luk, card_id))
    conn.commit()


def count_ball_codes(conn, user_id: str):
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT w.ball_code
        FROM ownership o
        JOIN works w ON w.id = o.work_id
        WHERE o.owner_id = ? AND w.is_ball = 1
    """, (user_id,)).fetchall()
    return len(set([r["ball_code"] for r in rows if r["ball_code"]]))


def steal_random_ball_if_any(conn, loser_id: str, winner_id: str):
    cur = conn.cursor()
    balls = cur.execute("""
        SELECT o.work_id, w.ball_code, w.title
        FROM ownership o
        JOIN works w ON w.id = o.work_id
        WHERE o.owner_id = ? AND w.is_ball = 1
    """, (loser_id,)).fetchall()

    if not balls:
        return None

    target = random.choice(balls)
    cur.execute("""
        UPDATE ownership
        SET owner_id=?, acquired_at=?
        WHERE work_id=?
    """, (winner_id, datetime.utcnow().isoformat(), target["work_id"]))
    conn.commit()
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
        "hp": {
            "天使": 6, "姫": 5, "神": 7, "聖": 5, "癒し": 4, "花": 3, "月": 2, "光": 3
        },
        "atk": {
            "炎": 7, "剣": 6, "戦": 6, "魔王": 6, "竜": 5, "雷": 5, "爆": 6, "紅": 4
        },
        "defense": {
            "盾": 7, "鎧": 7, "城": 5, "要塞": 8, "闇": 4, "黒": 3, "鋼": 6
        },
        "spd": {
            "風": 7, "雷": 6, "電脳": 7, "忍": 7, "瞬": 6, "流": 4, "羽": 3
        },
         "luk": {
            "奇跡": 8, "夢": 5, "虹": 6, "星": 5, "月": 3, "運命": 7, "秘宝": 6
        },
    }

    result = {
        "hp": 0,
        "atk": 0,
        "defense": 0,
        "spd": 0,
        "luk": 0,
    }

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
    conn = get_db()
    cur = conn.cursor()

    cur.execute("INSERT OR IGNORE INTO users(user_id,password,points,free_draw_count) VALUES('admin','admin123',9999,99)")
    cur.execute("INSERT OR IGNORE INTO users(user_id,password,points,free_draw_count) VALUES('creator1','1234',100,3)")
    cur.execute("INSERT OR IGNORE INTO users(user_id,password,points,free_draw_count) VALUES('creator2','1234',100,3)")

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
        INSERT OR IGNORE INTO works(
            title, creator_id, creator_name, description, genre, type,
            image_url, video_url, thumbnail_url, link_url, x_url, booth_url, chichipui_url, dlsite_url,
            rarity, hp, atk, def, spd, luk, exp_reward, is_ball, ball_code, content_hash
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, w)

    for i in range(1, 8):
        cur.execute("""
        INSERT OR IGNORE INTO works(
            title, creator_id, creator_name, description, genre, type,
            image_url, video_url, thumbnail_url, link_url, x_url, booth_url, chichipui_url, dlsite_url,
            rarity, hp, atk, def, spd, luk, exp_reward, is_ball, ball_code, content_hash
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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

    conn.commit()
    conn.close()


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
    conn = get_db()
    cur = conn.cursor()

    user = cur.execute("SELECT * FROM users WHERE user_id=?", (payload.user_id,)).fetchone()
    if user:
        if user["password"] != payload.password:
            conn.close()
            raise HTTPException(status_code=401, detail="パスワードが違います")
    else:
        cur.execute("""
            INSERT INTO users(user_id, password, points, exp, level, free_draw_count)
            VALUES(?,?,?,?,?,?)
        """, (payload.user_id, payload.password, 0, 0, 1, 1))
        conn.commit()

    reset_daily_duplicate_exp_if_needed(conn, payload.user_id)
    user = ensure_user(conn, payload.user_id)
    ball_count = count_ball_codes(conn, payload.user_id)

    result = {
        "user_id": user["user_id"],
        "points": user["points"],
        "exp": user["exp"],
        "level": user["level"],
        "free_draw_count": user["free_draw_count"],
        "revive_item_count": user["revive_items"],
        "royalty_balance": user["royalty_balance"],
        "ball_count": ball_count,
    }
    conn.close()
    return result


@app.get("/users/{user_id}")
def get_user(user_id: str):
    conn = get_db()
    reset_daily_duplicate_exp_if_needed(conn, user_id)
    user = ensure_user(conn, user_id)

    result = {
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
    conn.close()
    return result


def process_gacha(conn, user_id: str, draw_type: str):
    cur = conn.cursor()
    work = weighted_draw(conn, user_id)

    cur.execute("UPDATE works SET draw_count = draw_count + 1 WHERE id=?", (work["id"],))
    owner = get_ownership(conn, work["id"])

    is_new_owner = owner is None
    if is_new_owner:
        transfer_ownership(conn, work["id"], user_id)
        create_owned_card_if_missing(conn, user_id, work)
        exp_gained = work["exp_reward"]

        cur.execute("UPDATE users SET exp = exp + ? WHERE user_id=?", (exp_gained, user_id))
        update_user_level(conn, user_id)
        owner_user_id = user_id
    else:
        exp_gained = gain_duplicate_exp(conn, user_id, work)
        owner_user_id = owner["owner_id"]

    if draw_type == "paid":
        cur.execute("""
            UPDATE users
            SET points = points + 10, royalty_balance = royalty_balance + 10
            WHERE user_id=?
        """, (work["creator_id"],))

    conn.commit()
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
    conn = get_db()
    cur = conn.cursor()
    user = ensure_user(conn, user_id)

    if user["free_draw_count"] <= 0:
        conn.close()
        raise HTTPException(status_code=400, detail="無料ガチャ回数がありません")

    cur.execute("UPDATE users SET free_draw_count = free_draw_count - 1 WHERE user_id=?", (user_id,))
    conn.commit()

    result = process_gacha(conn, user_id, "free")
    conn.close()
    return result


@app.post("/gacha/paid/{user_id}")
def gacha_paid(user_id: str):
    conn = get_db()
    cur = conn.cursor()
    user = ensure_user(conn, user_id)

    if user["points"] < 30:
        conn.close()
        raise HTTPException(status_code=400, detail="ポイント不足です")

    cur.execute("UPDATE users SET points = points - 30 WHERE user_id=?", (user_id,))
    conn.commit()

    result = process_gacha(conn, user_id, "paid")
    result["message"] = "ポイントガチャ完了"
    conn.close()
    return result


@app.post("/works/{work_id}/like")
def like_work(work_id: int, payload: LikeRequest):
    conn = get_db()
    cur = conn.cursor()
    ensure_user(conn, payload.user_id)
    ensure_work(conn, work_id)

    try:
        cur.execute(
            "INSERT INTO like_logs(user_id, work_id) VALUES(?,?)",
            (payload.user_id, work_id)
        )
        cur.execute("UPDATE works SET like_count = like_count + 1 WHERE id=?", (work_id,))
        conn.commit()
    except sqlite3.IntegrityError:
        likes = ensure_work(conn, work_id)["like_count"]
        conn.close()
        return {"message": "すでにいいね済みです", "likes": likes}

    likes = ensure_work(conn, work_id)["like_count"]
    conn.close()
    return {"message": "いいねしました", "likes": likes}


@app.get("/users/{user_id}/works")
def get_user_works(user_id: str):
    conn = get_db()
    ensure_user(conn, user_id)
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT oc.*
        FROM owned_cards oc
        JOIN ownership o ON o.work_id = oc.work_id
        WHERE o.owner_id = ? AND oc.user_id = ?
        ORDER BY oc.id DESC
    """, (user_id, user_id)).fetchall()

    items = [serialize_owned_card(conn, row) for row in rows]
    conn.close()
    return {"works": items}


@app.post("/battle/entry")
def battle_entry(payload: BattleEntryRequest):
    conn = get_db()
    cur = conn.cursor()

    ensure_user(conn, payload.user_id)
    owner = get_ownership(conn, payload.work_id)
    if not owner or owner["owner_id"] != payload.user_id:
        conn.close()
        raise HTTPException(status_code=400, detail="所有している作品のみバトル参加できます")

    my_card = get_owned_card(conn, payload.user_id, payload.work_id)
    if not my_card:
        conn.close()
        raise HTTPException(status_code=404, detail="所有カードがありません")

    waiting = cur.execute("""
        SELECT * FROM battle_queue
        WHERE user_id != ?
        ORDER BY id ASC
        LIMIT 1
    """, (payload.user_id,)).fetchone()

    if not waiting:
        cur.execute(
            "INSERT INTO battle_queue(user_id, work_id) VALUES(?,?)",
            (payload.user_id, payload.work_id)
        )
        conn.commit()
        conn.close()
        return {"message": "対戦待機に入りました。次の参加者とバトルします。"}

    opp_user_id = waiting["user_id"]
    opp_work_id = waiting["work_id"]
    opp_card = get_owned_card(conn, opp_user_id, opp_work_id)

    if not opp_card:
        cur.execute("DELETE FROM battle_queue WHERE id=?", (waiting["id"],))
        conn.commit()
        conn.close()
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

    cur.execute("UPDATE owned_cards SET exp = exp + ? WHERE id=?", (exp_me, my_card["id"]))
    cur.execute("UPDATE owned_cards SET exp = exp + ? WHERE id=?", (exp_opp, opp_card["id"]))
    cur.execute("UPDATE users SET exp = exp + ? WHERE user_id=?", (exp_me, payload.user_id))
    cur.execute("UPDATE users SET exp = exp + ? WHERE user_id=?", (exp_opp, opp_user_id))

    if result_me == "lose":
        cur.execute("""
            UPDATE owned_cards
            SET lose_streak_count = lose_streak_count + 1
            WHERE id=?
        """, (my_card["id"],))
        updated = cur.execute(
            "SELECT lose_streak_count FROM owned_cards WHERE id=?",
            (my_card["id"],)
        ).fetchone()
        if updated["lose_streak_count"] >= 3:
            cur.execute("""
                UPDATE owned_cards
                SET lose_streak_count = 0, exp = exp + 20
                WHERE id=?
            """, (my_card["id"],))
            cur.execute("UPDATE users SET exp = exp + 20 WHERE user_id=?", (payload.user_id,))
            extra.append("3敗ボーナスでEXP+20")
    elif result_me == "win":
        cur.execute("UPDATE owned_cards SET lose_streak_count = 0 WHERE id=?", (my_card["id"],))

    if result_opp == "lose":
        cur.execute("""
            UPDATE owned_cards
            SET lose_streak_count = lose_streak_count + 1
            WHERE id=?
        """, (opp_card["id"],))
        updated = cur.execute(
            "SELECT lose_streak_count FROM owned_cards WHERE id=?",
            (opp_card["id"],)
        ).fetchone()
        if updated["lose_streak_count"] >= 3:
            cur.execute("""
                UPDATE owned_cards
                SET lose_streak_count = 0, exp = exp + 20
                WHERE id=?
            """, (opp_card["id"],))
            cur.execute("UPDATE users SET exp = exp + 20 WHERE user_id=?", (opp_user_id,))
    elif result_opp == "win":
        cur.execute("UPDATE owned_cards SET lose_streak_count = 0 WHERE id=?", (opp_card["id"],))

    my_user = ensure_user(conn, payload.user_id)
    opp_user = ensure_user(conn, opp_user_id)

    if result_me == "lose" and my_user["revive_items"] > 0:
        cur.execute("UPDATE users SET revive_items = revive_items - 1 WHERE user_id=?", (payload.user_id,))
        result_me = "draw"
        extra.append("復活アイテム発動")
    elif result_opp == "lose" and opp_user["revive_items"] > 0:
        cur.execute("UPDATE users SET revive_items = revive_items - 1 WHERE user_id=?", (opp_user_id,))
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

    cur.execute("""
        INSERT INTO battle_logs(user_id, opponent_user_id, result, log_text, reward_exp)
        VALUES(?,?,?,?,?)
    """, (payload.user_id, opp_user_id, result_me, full_log, exp_me))

    cur.execute("""
        INSERT INTO battle_logs(user_id, opponent_user_id, result, log_text, reward_exp)
        VALUES(?,?,?,?,?)
    """, (opp_user_id, payload.user_id, result_opp, full_log, exp_opp))

    cur.execute("DELETE FROM battle_queue WHERE id=?", (waiting["id"],))
    conn.commit()
    conn.close()

    return {
        "message": "バトルが完了しました",
        "result": result_me,
        "log": full_log,
        "reward_exp": exp_me
    }


@app.get("/battle/logs/{user_id}")
def get_battle_logs(user_id: str):
    conn = get_db()
    ensure_user(conn, user_id)
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT * FROM battle_logs
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 50
    """, (user_id,)).fetchall()

    items = [{
        "id": r["id"],
        "opponent_id": r["opponent_user_id"],
        "opponent_name": r["opponent_user_id"],
        "result": r["result"],
        "log": r["log_text"],
        "reward_exp": r["reward_exp"],
        "created_at": r["created_at"]
    } for r in rows]

    conn.close()
    return {"logs": items}


@app.post("/rewards/ad-xp")
def reward_ad_xp(payload: UserOnlyRequest):
    conn = get_db()
    cur = conn.cursor()
    ensure_user(conn, payload.user_id)

    cur.execute("UPDATE users SET exp = exp + 20 WHERE user_id=?", (payload.user_id,))
    conn.commit()
    update_user_level(conn, payload.user_id)

    user = ensure_user(conn, payload.user_id)
    conn.close()

    return {
        "message": "広告報酬でEXP 20 を付与しました",
        "exp": user["exp"],
        "level": user["level"]
    }


@app.post("/items/revive/buy")
def buy_revive(payload: UserOnlyRequest):
    conn = get_db()
    cur = conn.cursor()
    user = ensure_user(conn, payload.user_id)

    if user["points"] < 100:
        conn.close()
        raise HTTPException(status_code=400, detail="ポイント不足です")

    cur.execute("""
        UPDATE users
        SET points = points - 100,
            revive_items = revive_items + 1
        WHERE user_id=?
    """, (payload.user_id,))
    conn.commit()

    user = ensure_user(conn, payload.user_id)
    conn.close()

    return {
        "message": "復活アイテムを購入しました",
        "revive_item_count": user["revive_items"],
        "points": user["points"]
    }
