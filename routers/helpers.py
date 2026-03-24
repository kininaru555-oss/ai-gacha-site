from pathlib import Path

content = r'''"""
helpers.py — DBヘルパー・シリアライザー・ゲームロジック（完成版）

方針:
- 二次流通会計は points / royalty_balance を分離
- 1作品 = 1育成個体 前提に寄せる
- レジェンドボール表記へ段階移行（旧 is_ball / ball_code は互換維持）
- 日次EXP処理は日本時間基準
"""
from __future__ import annotations

import random
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

from fastapi import HTTPException


JST = timezone(timedelta(hours=9))


# ─────────────────────────────────────────────
# 日付ユーティリティ
# ─────────────────────────────────────────────
def today_str() -> str:
    return datetime.now(JST).date().isoformat()


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


def ensure_system_user(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT user_id FROM users WHERE user_id=%s", ("system",))
        if not cur.fetchone():
            cur.execute(
                """
                INSERT INTO users(user_id, password, password_hash, points, exp, level, free_draw_count, revive_items, royalty_balance, daily_duplicate_exp, last_exp_reset)
                VALUES(%s,%s,%s,0,0,1,0,0,0,0,%s)
                """,
                ("system", "", "", today_str()),
            )


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
# Cloudinary ぼかしURL
# ─────────────────────────────────────────────
def _is_cloudinary_url(url: str) -> bool:
    if not url:
        return False
    try:
        host = urlparse(url).netloc.lower()
        return "res.cloudinary.com" in host
    except Exception:
        return False


def build_locked_cloudinary_url(url: str, media_type: str = "image") -> str:
    if not url or not _is_cloudinary_url(url):
        return url

    marker = "/upload/"
    if marker not in url:
        return url

    if media_type == "video":
        transform = "so_0,e_blur:800,w_480,q_auto:low,f_auto"
    else:
        transform = "e_blur:900,w_480,q_auto:low,f_auto"

    return url.replace(marker, f"/upload/{transform}/", 1)


def resolve_media_access(work: dict, can_view_full: bool) -> dict:
    media_type = work.get("media_type") or work.get("type", "image")
    image_url = work.get("image_url", "") or ""
    video_url = work.get("video_url", "") or ""

    if can_view_full:
        return {
            "image_url": image_url,
            "video_url": video_url,
            "needs_front_blur": False,
        }

    if media_type == "video":
        locked_video_url = build_locked_cloudinary_url(video_url, "video")
        needs_front_blur = locked_video_url == video_url and bool(video_url)
        return {
            "image_url": image_url,
            "video_url": locked_video_url,
            "needs_front_blur": needs_front_blur,
        }

    locked_image_url = build_locked_cloudinary_url(image_url, "image")
    needs_front_blur = locked_image_url == image_url and bool(image_url)
    return {
        "image_url": locked_image_url,
        "video_url": video_url,
        "needs_front_blur": needs_front_blur,
    }


# ─────────────────────────────────────────────
# EXP / レベル
# ─────────────────────────────────────────────
def reset_daily_duplicate_exp_if_needed(conn, user_id: str):
    user = ensure_user(conn, user_id)
    if (user.get("last_exp_reset") or "") != today_str():
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET daily_duplicate_exp=0, last_exp_reset=%s
                WHERE user_id=%s
            """, (today_str(), user_id))


def update_user_level(conn, user_id: str):
    user = ensure_user(conn, user_id)
    level = max(1, 1 + (int(user["exp"] or 0) // 100))
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
            """, (new_owner_id, datetime.now(timezone.utc), work_id))
        else:
            cur.execute("""
                INSERT INTO ownership(work_id, owner_id, acquired_at)
                VALUES(%s,%s,%s)
            """, (work_id, new_owner_id, datetime.now(timezone.utc)))


# ─────────────────────────────────────────────
# 所有カード
# ─────────────────────────────────────────────
def get_owned_card(conn, user_id: str, work_id: int):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT * FROM owned_cards
            WHERE user_id=%s AND work_id=%s
            LIMIT 1
        """, (user_id, work_id))
        return cur.fetchone()


def create_owned_card_if_missing(conn, user_id: str, work_row):
    existing = get_owned_card(conn, user_id, work_row["id"])
    if existing:
        return existing

    # 作品ベース値を個体初期値として採用（所有者依存の再ロールはしない）
    hp = int(work_row["hp"] or 10)
    atk = int(work_row["atk"] or 10)
    ddef = int(work_row["def"] or 10)
    spd = int(work_row["spd"] or 10)
    luk = int(work_row["luk"] or 10)

    rarity = (work_row.get("rarity") or "N").upper().strip()

    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO owned_cards(
                user_id, work_id, rarity, level, exp, hp, atk, def, spd, luk,
                lose_streak_count, is_legend, legend_at,
                total_exp, win_count, battle_count
            ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            user_id, work_row["id"], rarity, 1, 0,
            hp, atk, ddef, spd, luk,
            0, 1 if rarity == "LEGEND" else 0, "",
            0, 0, 0,
        ))

    return get_owned_card(conn, user_id, work_row["id"])


# ─────────────────────────────────────────────
# 重複EXP付与
# ─────────────────────────────────────────────
def gain_duplicate_exp(conn, user_id: str, work_row):
    reset_daily_duplicate_exp_if_needed(conn, user_id)
    user = ensure_user(conn, user_id)

    exp_gain = int((work_row.get("exp_reward") or 5) * 0.3)
    exp_gain = max(3, min(exp_gain, 10))

    daily = int(user.get("daily_duplicate_exp") or 0)
    if daily >= 100:
        return 0

    if daily + exp_gain > 100:
        exp_gain = 100 - daily

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
        cur.execute("""
            SELECT * FROM works
            WHERE is_active=1
              AND COALESCE(gacha_enabled, 1)=1
              AND COALESCE(is_deleted, 0)=0
        """)
        works = cur.fetchall()

    if not works:
        raise HTTPException(status_code=400, detail="排出対象がありません")

    level = int(user.get("level") or 1)
    rarity_weights = {
        "N":      max(55 - level, 20),
        "R":      25 + min(level, 10),
        "SR":     min(10 + level, 24),
        "SSR":    min(3 + level // 3, 10),
        "LEGEND": 1,
    }

    pool = []
    for w in works:
        weight = rarity_weights.get((w.get("rarity") or "N").upper(), 10)

        # レジェンドボールは少しだけ出やすくしてもよいが過剰にはしない
        item_type = (w.get("item_type") or "").strip()
        is_legend_ball = item_type == "legend_ball" or bool(w.get("is_ball"))
        if is_legend_ball:
            weight += 1

        if w.get("creator_id") in ("admin", "system"):
            weight = max(1, int(round(weight * 1.2)))

        pool.extend([w] * max(1, weight))

    return random.choice(pool)


# ─────────────────────────────────────────────
# ポイント分配（互換関数）
# ─────────────────────────────────────────────
def distribute_points(conn, work_id: int, buyer_user_id: str, seller_user_id: str, total_points: int, tx_type: str):
    """
    互換用。
    二次流通では以下で分離する:
    - buyer: points 減少
    - seller: points 増加
    - creator: royalty_balance 増加
    - system: points 増加
    """
    if total_points <= 0:
        raise HTTPException(status_code=400, detail="取引金額が不正です")

    buyer = ensure_user(conn, buyer_user_id)
    if int(buyer["points"] or 0) < total_points:
        raise HTTPException(status_code=400, detail="ポイント不足です")

    work = ensure_work(conn, work_id)
    creator_id = work["creator_id"]

    ensure_system_user(conn)

    fee = int(total_points * 0.30)
    remain = total_points - fee

    if creator_id == seller_user_id:
        seller_share = remain
        creator_share = 0
    else:
        seller_share = remain // 2
        creator_share = remain - seller_share

    with conn.cursor() as cur:
        cur.execute("UPDATE users SET points = points - %s WHERE user_id=%s", (total_points, buyer_user_id))
        cur.execute("UPDATE users SET points = points + %s WHERE user_id=%s", (fee, "system"))
        cur.execute("UPDATE users SET points = points + %s WHERE user_id=%s", (seller_share, seller_user_id))
        if creator_share > 0:
            cur.execute("UPDATE users SET royalty_balance = royalty_balance + %s WHERE user_id=%s", (creator_share, creator_id))
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
        (card["hp"] or 0) * 0.30 +
        (card["atk"] or 0) * 1.25 +
        (card["def"] or 0) * 0.95 +
        (card["spd"] or 0) * 0.75 +
        (card["luk"] or 0) * 0.55 +
        random.randint(0, 15)
    )


def level_up_card_if_needed(conn, card_id: int):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM owned_cards WHERE id=%s", (card_id,))
        card = cur.fetchone()
    if not card:
        return

    exp = int(card["exp"] or 0)
    level = int(card["level"] or 1)
    hp = int(card["hp"] or 0)
    atk = int(card["atk"] or 0)
    ddef = int(card["def"] or 0)
    spd = int(card["spd"] or 0)
    luk = int(card["luk"] or 0)

    need = max(30, level * 20)
    while exp >= need:
        exp -= need
        level += 1
        hp += 2
        atk += 2
        ddef += 2
        spd += 1
        luk += 1
        need = max(30, level * 20)

    with conn.cursor() as cur:
        cur.execute("""
            UPDATE owned_cards
            SET exp=%s, level=%s, hp=%s, atk=%s, def=%s, spd=%s, luk=%s
            WHERE id=%s
        """, (exp, level, hp, atk, ddef, spd, luk, card_id))


# ─────────────────────────────────────────────
# レジェンドボール
# ─────────────────────────────────────────────
def count_ball_codes(conn, user_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COALESCE(NULLIF(w.legend_code, ''), NULLIF(w.ball_code, '')) AS legend_code
            FROM ownership o
            JOIN works w ON w.id = o.work_id
            WHERE o.owner_id = %s
              AND (w.item_type = 'legend_ball' OR w.is_ball = 1)
        """, (user_id,))
        rows = cur.fetchall()
    return len({r["legend_code"] for r in rows if r["legend_code"]})


def steal_random_ball_if_any(conn, loser_id: str, winner_id: str):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT o.work_id,
                   COALESCE(NULLIF(w.legend_code, ''), NULLIF(w.ball_code, '')) AS legend_code,
                   w.title
            FROM ownership o
            JOIN works w ON w.id = o.work_id
            WHERE o.owner_id = %s
              AND (w.item_type = 'legend_ball' OR w.is_ball = 1)
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
        """, (winner_id, datetime.now(timezone.utc), target["work_id"]))
    return target["legend_code"] or target["title"]


# ─────────────────────────────────────────────
# シリアライザー
# ─────────────────────────────────────────────
def serialize_work(work: dict, can_view_full: bool = False) -> dict:
    media = resolve_media_access(work, can_view_full)
    item_type = (work.get("item_type") or ("legend_ball" if work.get("is_ball") else "work")).strip()
    legend_code = work.get("legend_code") or work.get("ball_code") or ""

    return {
        "id": work["id"],
        "title": work["title"],
        "creator_user_id": work["creator_id"],
        "creator_name": work["creator_name"],
        "description": work["description"],
        "genre": work["genre"],
        "type": work.get("type"),
        "media_type": work.get("media_type") or work.get("type"),
        "item_type": item_type,
        "image_url": media["image_url"],
        "video_url": media["video_url"],
        "thumbnail_url": work.get("thumbnail_url", ""),
        "link_url": work.get("link_url", ""),
        "x_url": work.get("x_url", ""),
        "booth_url": work.get("booth_url", ""),
        "chichipui_url": work.get("chichipui_url", ""),
        "dlsite_url": work.get("dlsite_url", ""),
        "fanbox_url": work.get("fanbox_url", ""),
        "skeb_url": work.get("skeb_url", ""),
        "pixiv_url": work.get("pixiv_url", ""),
        "rarity": work["rarity"],
        "hp": work["hp"],
        "atk": work["atk"],
        "def": work["def"],
        "spd": work["spd"],
        "luk": work["luk"],
        "exp_reward": work.get("exp_reward", 5),
        "draw_count": work.get("draw_count", 0),
        "likes": work.get("like_count", 0),
        "is_ball": bool(work.get("is_ball")),
        "ball_code": work.get("ball_code", ""),
        "is_legend_ball": item_type == "legend_ball",
        "legend_code": legend_code,
        "can_view_full": can_view_full,
        "needs_front_blur": media["needs_front_blur"],
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

    item_type = (work.get("item_type") or ("legend_ball" if work.get("is_ball") else "work")).strip()
    legend_code = work.get("legend_code") or work.get("ball_code") or ""

    return {
        "id": owned["id"],
        "work_id": owned["work_id"],
        "title": work["title"],
        "creator_user_id": work["creator_id"],
        "creator_name": work["creator_name"],
        "type": work.get("type"),
        "media_type": work.get("media_type") or work.get("type"),
        "item_type": item_type,
        "image_url": work.get("image_url", ""),
        "video_url": work.get("video_url", ""),
        "thumbnail_url": work.get("thumbnail_url", ""),
        "link_url": work.get("link_url", ""),
        "x_url": work.get("x_url", ""),
        "booth_url": work.get("booth_url", ""),
        "chichipui_url": work.get("chichipui_url", ""),
        "dlsite_url": work.get("dlsite_url", ""),
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
        "is_ball": bool(work.get("is_ball")),
        "ball_code": work.get("ball_code", ""),
        "is_legend_ball": item_type == "legend_ball",
        "legend_code": legend_code,
        "owner_user_id": owner["owner_id"] if owner else None,
        "draw_count": work.get("draw_count", 0),
        "like_count": work.get("like_count", 0),
        "card_power": card_power,
        "can_view_full": True,
        "needs_front_blur": False,
    }
'''
path = Path("/mnt/data/helpers_fixed.py")
path.write_text(content, encoding="utf-8")
print(path)
