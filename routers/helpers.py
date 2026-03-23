"""
helpers.py — DBヘルパー・シリアライザー・ゲームロジック
"""
import random
from datetime import datetime, date

from fastapi import HTTPException


# ─────────────────────────────────────────────
# 日付ユーティリティ
# ─────────────────────────────────────────────
def today_str() -> str:
    return date.today().isoformat()


# ─────────────────────────────────────────────
# ユーザー / 作品 取得
# ─────────────────────────────────────────────
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


# ─────────────────────────────────────────────
# 閲覧権管理
# ─────────────────────────────────────────────
def grant_view_access(conn, user_id: str, work_id: int, granted_by: str = "system"):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO view_accesses(user_id, work_id, access_type, granted_by)
            VALUES(%s, %s, 'view', %s)
            ON CONFLICT (user_id, work_id, access_type) DO NOTHING
        """, (user_id, work_id, granted_by))


def has_view_access(conn, user_id: str, work_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT 1
            FROM view_accesses
            WHERE user_id=%s AND work_id=%s AND access_type='view'
            LIMIT 1
        """, (user_id, work_id))
        return cur.fetchone() is not None


# ─────────────────────────────────────────────
# EXP / レベル
# ─────────────────────────────────────────────
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


# ─────────────────────────────────────────────
# 所有権
# ─────────────────────────────────────────────
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


# ─────────────────────────────────────────────
# 所有カード
# ─────────────────────────────────────────────
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
    """
    所有カードは常に N スタート。
    作品側の rarity は排出率や演出用であり、育成カードの初期レア度には使わない。
    """
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
                lose_streak_count, is_legend, legend_at,
                total_exp, win_count, battle_count
            ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            user_id,
            work_row["id"],
            "N",
            1,
            0,
            hp,
            atk,
            ddef,
            spd,
            luk,
            0,
            0,
            "",
            0,
            0,
            0,
        ))

    return get_owned_card(conn, user_id, work_row["id"])


# ─────────────────────────────────────────────
# 重複EXP付与
# ─────────────────────────────────────────────
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


# ─────────────────────────────────────────────
# ガチャ抽選
# ─────────────────────────────────────────────
def weighted_draw(conn, user_id: str):
    user = ensure_user(conn, user_id)
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM works WHERE is_active=1")
        works = cur.fetchall()

    if not works:
        raise HTTPException(status_code=400, detail="排出対象がありません")

    level = user["level"]
    rarity_weights = {
        "N":      max(55 - level, 20),
        "R":      25 + min(level, 10),
        "SR":     min(10 + level, 24),
        "SSR":    min(3 + level // 3, 10),
        "LEGEND": 1,
    }

    pool = []
    for w in works:
        weight = rarity_weights.get((w["rarity"] or "N").upper(), 10)

        if w["is_ball"]:
            weight += 1

        # 運営作品は20%増し
        if w["creator_id"] == "admin":
            weight = max(1, int(round(weight * 1.2)))

        pool.extend([w] * max(1, weight))

    return random.choice(pool)


# ─────────────────────────────────────────────
# ポイント分配
# ─────────────────────────────────────────────
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
        "creator_share": creator_share
    }


# ─────────────────────────────────────────────
# バトル
# ─────────────────────────────────────────────
def battle_score(card) -> float:
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


# ─────────────────────────────────────────────
# トラゴンボウル
# ─────────────────────────────────────────────
def count_ball_codes(conn, user_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT w.ball_code
            FROM ownership o
            JOIN works w ON w.id = o.work_id
            WHERE o.owner_id = %s AND w.is_ball = 1
        """, (user_id,))
        rows = cur.fetchall()
    return len({r["ball_code"] for r in rows if r["ball_code"]})


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


# ─────────────────────────────────────────────
# シリアライザー
# ─────────────────────────────────────────────
def serialize_work(work: dict, can_view_full: bool = False) -> dict:
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
        "fanbox_url": work.get("fanbox_url", ""),
        "skeb_url": work.get("skeb_url", ""),
        "pixiv_url": work.get("pixiv_url", ""),
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
        "can_view_full": can_view_full,
    }


def serialize_owned_card(conn, owned: dict) -> dict:
    work = ensure_work(conn, owned["work_id"])
    owner = get_ownership(conn, owned["work_id"])

    card_power = (
        (owned.get("hp") or 0) +
        (owned.get("atk") or 0) +
        (owned.get("def") or 0) +
        (owned.get("spd") or 0) +
        (owned.get("luk") or 0)
    )

    return {
        "id": owned["id"],
        "work_id": owned["work_id"],
        "title": work["title"],
        "creator_user_id": work["creator_id"],
        "creator_name": work["creator_name"],
        "type": work["type"],
        "image_url": work["image_url"],
        "video_url": work["video_url"],
        "thumbnail_url": work["thumbnail_url"],
        "link_url": work["link_url"],
        "x_url": work["x_url"],
        "booth_url": work["booth_url"],
        "chichipui_url": work["chichipui_url"],
        "dlsite_url": work["dlsite_url"],
        "fanbox_url": work.get("fanbox_url", ""),
        "skeb_url": work.get("skeb_url", ""),
        "pixiv_url": work.get("pixiv_url", ""),
        "rarity": owned["rarity"],
        "hp": owned["hp"],
        "atk": owned["atk"],
        "def": owned["def"],
        "spd": owned["spd"],
        "luk": owned["luk"],
        "level": owned["level"],
        "exp": owned["exp"],
        "total_exp": owned.get("total_exp", 0),
        "win_count": owned.get("win_count", 0),
        "battle_count": owned.get("battle_count", 0),
        "lose_streak_count": owned["lose_streak_count"],
        "is_legend": bool(owned["is_legend"]),
        "legend_at": owned.get("legend_at", ""),
        "is_ball": bool(work["is_ball"]),
        "ball_code": work["ball_code"],
        "owner_user_id": owner["owner_id"] if owner else None,
        "draw_count": work["draw_count"],
        "like_count": work["like_count"],
        "card_power": card_power,
    }
