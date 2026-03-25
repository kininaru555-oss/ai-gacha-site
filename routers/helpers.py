"""
helpers_gacha_integrated.py — 共通ゲームロジック・DBヘルパー・シリアライザー
ガチャ完全統合版

方針:
- users.password は完全廃止
- battle_score() は旧仕様固定（変更禁止）
- level_up_card_if_needed() は旧仕様固定（変更禁止）
- serialize_* は旧キー互換を基本維持
- distribute_points() は新仕様維持
- weighted_draw() は PostgreSQL 側で重み付き 1 件抽選
- defense に統一
- ガチャ本体(process_gacha)を helpers 側へ統合
"""

from __future__ import annotations

import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException

JST = timezone(timedelta(hours=9))

CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
CLOUDINARY_DEFAULT_BLUR = os.getenv("CLOUDINARY_DEFAULT_BLUR", "800").strip()

FREE_GACHA_DRAW_COST = 1
PAID_GACHA_POINT_COST = 30
PAID_GACHA_CREATOR_ROYALTY = 15


# ─────────────────────────────────────────────
# 日付ユーティリティ
# ─────────────────────────────────────────────
def now_jst() -> datetime:
    return datetime.now(JST)


def today_str() -> str:
    return now_jst().date().isoformat()


# ─────────────────────────────────────────────
# 基本取得
# ─────────────────────────────────────────────
def ensure_user(conn, user_id: str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM users
            WHERE user_id = %s
            """,
            (user_id,),
        )
        user = cur.fetchone()

    if not user:
        raise HTTPException(status_code=404, detail="ユーザーが存在しません")
    if not bool(user.get("is_active", True)):
        raise HTTPException(status_code=403, detail="このユーザーアカウントは無効です")
    return user


def ensure_work(conn, work_id: int) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM works
            WHERE id = %s
              AND is_active = TRUE
              AND is_deleted = FALSE
            """,
            (work_id,),
        )
        work = cur.fetchone()

    if not work:
        raise HTTPException(status_code=404, detail="作品が存在しません")
    return work


def ensure_system_user(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users(
                user_id,
                password_hash,
                token_version,
                points,
                exp,
                level,
                free_draw_count,
                revive_items,
                royalty_balance,
                daily_duplicate_exp,
                last_exp_reset,
                daily_exp_purchase_count,
                last_exp_purchase_date,
                is_admin,
                is_official,
                is_active
            )
            VALUES(
                'system',
                '',
                0,
                0,
                0,
                1,
                0,
                0,
                0,
                0,
                '',
                0,
                '',
                FALSE,
                TRUE,
                TRUE
            )
            ON CONFLICT (user_id) DO NOTHING
            """
        )


# ─────────────────────────────────────────────
# ユーザーシリアライズ
# ─────────────────────────────────────────────
def serialize_user(conn, user_id: str) -> dict[str, Any]:
    reset_daily_duplicate_exp_if_needed(conn, user_id)
    user = ensure_user(conn, user_id)

    return {
        "user_id": str(user["user_id"]),
        "points": int(user.get("points") or 0),
        "exp": int(user.get("exp") or 0),
        "level": int(user.get("level") or 1),
        "free_draw_count": int(user.get("free_draw_count") or 0),
        "revive_item_count": int(user.get("revive_items") or 0),
        "royalty_balance": int(user.get("royalty_balance") or 0),
        "ball_count": get_user_legend_ball_count(conn, user_id),
        "daily_duplicate_exp": int(user.get("daily_duplicate_exp") or 0),
    }


# ─────────────────────────────────────────────
# 閲覧権
# ─────────────────────────────────────────────
def grant_view_access(
    conn,
    user_id: str,
    work_id: int,
    access_type: str = "view",
    granted_by: str = "system",
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO view_accesses(user_id, work_id, access_type, granted_by)
            VALUES(%s, %s, %s, %s)
            ON CONFLICT (user_id, work_id, access_type) DO NOTHING
            """,
            (user_id, work_id, access_type, granted_by),
        )


def has_view_access(conn, user_id: str, work_id: int, access_type: str = "view") -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM view_accesses
            WHERE user_id = %s
              AND work_id = %s
              AND access_type = %s
            LIMIT 1
            """,
            (user_id, work_id, access_type),
        )
        return cur.fetchone() is not None


# ─────────────────────────────────────────────
# Cloudinary / メディア制御
# ─────────────────────────────────────────────
def _extract_cloudinary_parts(url: str) -> tuple[str, str]:
    if not url or "res.cloudinary.com" not in url or "/upload/" not in url:
        return "", ""

    left, right = url.split("/upload/", 1)

    resource_type = "image"
    if "/video/" in left:
        resource_type = "video"

    parts = right.split("/", 1)
    if len(parts) != 2:
        return "", ""

    public_id = parts[1]
    return resource_type, public_id


def build_locked_cloudinary_url(url: str, media_type: str = "image", blur_strength: Optional[str] = None) -> str:
    if not url:
        return ""

    blur_strength = (blur_strength or CLOUDINARY_DEFAULT_BLUR or "800").strip()
    resource_type, public_id = _extract_cloudinary_parts(url)
    if not resource_type or not public_id or not CLOUDINARY_CLOUD_NAME:
        return url

    actual_type = "video" if media_type == "video" or resource_type == "video" else "image"
    transformation = f"e_blur:{blur_strength},q_auto,f_auto"

    return (
        f"https://res.cloudinary.com/{CLOUDINARY_CLOUD_NAME}/"
        f"{actual_type}/upload/{transformation}/{public_id}"
    )


def resolve_media_access(
    conn,
    work_row: dict[str, Any],
    viewer_user_id: Optional[str] = None,
) -> dict[str, Any]:
    work_id = int(work_row["id"])
    media_type = str(work_row.get("media_type") or work_row.get("type") or "image")
    image_url = str(work_row.get("image_url") or "")
    video_url = str(work_row.get("video_url") or "")
    thumbnail_url = str(work_row.get("thumbnail_url") or image_url or "")

    can_view_full = False
    if viewer_user_id:
        owner = get_ownership(conn, work_id)
        if owner and owner["owner_id"] == viewer_user_id:
            can_view_full = True
        elif has_view_access(conn, viewer_user_id, work_id, "view"):
            can_view_full = True

    if can_view_full:
        return {
            "can_view_full": True,
            "media_type": media_type,
            "image_url": image_url,
            "video_url": video_url,
            "thumbnail_url": thumbnail_url,
            "preview_url": thumbnail_url or image_url or video_url,
            "needs_front_blur": False,
        }

    if media_type == "video":
        locked_preview = build_locked_cloudinary_url(thumbnail_url or image_url, "image")
        return {
            "can_view_full": False,
            "media_type": media_type,
            "image_url": locked_preview,
            "video_url": "",
            "thumbnail_url": locked_preview,
            "preview_url": locked_preview,
            "needs_front_blur": True,
        }

    locked_image = build_locked_cloudinary_url(image_url, "image")
    return {
        "can_view_full": False,
        "media_type": media_type,
        "image_url": locked_image,
        "video_url": "",
        "thumbnail_url": locked_image,
        "preview_url": locked_image,
        "needs_front_blur": True,
    }


# ─────────────────────────────────────────────
# EXP / レベル
# ─────────────────────────────────────────────
def reset_daily_duplicate_exp_if_needed(conn, user_id: str) -> None:
    user = ensure_user(conn, user_id)
    today = today_str()
    last_reset = str(user.get("last_exp_reset") or "")

    if last_reset == today:
        return

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET daily_duplicate_exp = 0,
                last_exp_reset = %s
            WHERE user_id = %s
            """,
            (today, user_id),
        )


def update_user_level(conn, user_id: str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT user_id, exp, level
            FROM users
            WHERE user_id = %s
            FOR UPDATE
            """,
            (user_id,),
        )
        user = cur.fetchone()

        if not user:
            raise HTTPException(status_code=404, detail="ユーザーが存在しません")

        exp = int(user.get("exp") or 0)
        current_level = int(user.get("level") or 1)
        new_level = max(1, exp // 100 + 1)

        if new_level != current_level:
            cur.execute(
                """
                UPDATE users
                SET level = %s
                WHERE user_id = %s
                """,
                (new_level, user_id),
            )
            user["level"] = new_level

        return user


def gain_duplicate_exp(conn, user_id: str, work_row: dict[str, Any]) -> dict[str, int]:
    """
    旧仕様互換:
    - work_row の exp_reward を使う
    - 30% を付与
    - 日次上限 100
    """
    reset_daily_duplicate_exp_if_needed(conn, user_id)
    user = ensure_user(conn, user_id)

    exp_reward = int(work_row.get("exp_reward") or 0)
    add = max(1, int(exp_reward * 0.3)) if exp_reward > 0 else 0
    current_daily = int(user.get("daily_duplicate_exp") or 0)
    available = max(0, 100 - current_daily)
    actual_add = min(add, available)

    if actual_add <= 0:
        return {"added": 0, "daily_duplicate_exp": current_daily}

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET exp = exp + %s,
                daily_duplicate_exp = COALESCE(daily_duplicate_exp, 0) + %s
            WHERE user_id = %s
            RETURNING daily_duplicate_exp
            """,
            (actual_add, actual_add, user_id),
        )
        row = cur.fetchone()

    update_user_level(conn, user_id)
    return {
        "added": actual_add,
        "daily_duplicate_exp": int(row["daily_duplicate_exp"] if row else current_daily),
    }


# ─────────────────────────────────────────────
# 所有権 / 所有カード
# ─────────────────────────────────────────────
def get_ownership(conn, work_id: int) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM ownership
            WHERE work_id = %s
            """,
            (work_id,),
        )
        return cur.fetchone()


def transfer_ownership(conn, work_id: int, from_user_id: str, to_user_id: str) -> None:
    ensure_user(conn, to_user_id)

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ownership
            SET owner_id = %s,
                acquired_at = NOW()
            WHERE work_id = %s
              AND owner_id = %s
            RETURNING work_id
            """,
            (to_user_id, work_id, from_user_id),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=409, detail="所有権移転に失敗しました。所有者が変わっている可能性があります")


def get_owned_card(conn, user_id: str, work_id: int, for_update: bool = False) -> Optional[dict[str, Any]]:
    sql = """
        SELECT *
        FROM owned_cards
        WHERE user_id = %s
          AND work_id = %s
        ORDER BY id ASC
        LIMIT 1
    """
    if for_update:
        sql += "\nFOR UPDATE"

    with conn.cursor() as cur:
        cur.execute(sql, (user_id, work_id))
        return cur.fetchone()


def create_owned_card_if_missing(conn, user_id: str, work_id: int) -> dict[str, Any]:
    card = get_owned_card(conn, user_id, work_id)
    if card:
        return card

    work = ensure_work(conn, work_id)
    ensure_user(conn, user_id)

    hp = int(work.get("hp") or 10)
    atk = int(work.get("atk") or 10)
    defense = int(work.get("defense") or 10)
    spd = int(work.get("spd") or 10)
    luk = int(work.get("luk") or 10)
    rarity = str(work.get("rarity") or "N")

    item_type = str(work.get("item_type") or "work")
    is_legend = item_type == "legend_ball" or bool(work.get("is_ball"))

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO owned_cards(
                user_id,
                work_id,
                rarity,
                level,
                exp,
                hp,
                atk,
                defense,
                spd,
                luk,
                lose_streak_count,
                is_legend,
                legend_at,
                total_exp,
                win_count,
                battle_count,
                current_rarity
            )
            VALUES(%s, %s, %s, 1, 0, %s, %s, %s, %s, %s, 0, %s, %s, 0, 0, 0, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                user_id,
                work_id,
                rarity,
                hp,
                atk,
                defense,
                spd,
                luk,
                is_legend,
                today_str() if is_legend else "",
                rarity,
            ),
        )

    card = get_owned_card(conn, user_id, work_id)
    if not card:
        raise HTTPException(status_code=500, detail="所有カードの作成に失敗しました")
    return card


# ─────────────────────────────────────────────
# ガチャ
# ─────────────────────────────────────────────
def _weight_case_sql() -> str:
    return """
        CASE
            WHEN %s >= 50 THEN
                CASE UPPER(COALESCE(rarity, 'N'))
                    WHEN 'SSR' THEN 8
                    WHEN 'SR' THEN 18
                    WHEN 'R' THEN 30
                    ELSE 44
                END
            WHEN %s >= 20 THEN
                CASE UPPER(COALESCE(rarity, 'N'))
                    WHEN 'SSR' THEN 5
                    WHEN 'SR' THEN 15
                    WHEN 'R' THEN 30
                    ELSE 50
                END
            ELSE
                CASE UPPER(COALESCE(rarity, 'N'))
                    WHEN 'SSR' THEN 2
                    WHEN 'SR' THEN 8
                    WHEN 'R' THEN 25
                    ELSE 65
                END
        END
    """


def weighted_draw(
    conn,
    *,
    user_level: int = 1,
    only_public: bool = True,
    only_gacha_enabled: bool = True,
    rng: Optional[random.Random] = None,
) -> dict[str, Any]:
    """
    PostgreSQL 側で重み付き 1 件抽選する。
    Python 側で全件 fetchall / pool.extend はしない。
    rng は互換性のため残すが、この SQL 抽選版では使用しない。
    """
    conditions = ["is_active = TRUE", "is_deleted = FALSE"]
    if only_public:
        conditions.append("is_public = TRUE")
    if only_gacha_enabled:
        conditions.append("gacha_enabled = TRUE")

    where_clause = " AND ".join(conditions)
    weight_sql = _weight_case_sql()

    sql = f"""
        WITH candidates AS (
            SELECT
                *,
                ({weight_sql})::double precision AS draw_weight
            FROM works
            WHERE {where_clause}
        ),
        totals AS (
            SELECT COALESCE(SUM(draw_weight), 0)::double precision AS total_weight
            FROM candidates
        ),
        picked AS (
            SELECT
                c.*,
                SUM(c.draw_weight) OVER (ORDER BY c.id ASC) AS cumulative_weight,
                t.total_weight,
                random() * t.total_weight AS cutoff
            FROM candidates c
            CROSS JOIN totals t
        )
        SELECT *
        FROM picked
        WHERE total_weight > 0
          AND cumulative_weight >= cutoff
        ORDER BY cumulative_weight ASC
        LIMIT 1
    """

    params = (user_level, user_level)

    with conn.cursor() as cur:
        cur.execute(sql, params)
        chosen = cur.fetchone()

    if not chosen:
        fallback_sql = f"""
        SELECT *
        FROM works
        WHERE {where_clause}
        ORDER BY id ASC
        LIMIT 1
        """
        with conn.cursor() as cur:
            cur.execute(fallback_sql)
            chosen = cur.fetchone()

    if not chosen:
        raise HTTPException(status_code=404, detail="抽選可能な作品がありません")
    return chosen


def consume_free_gacha(conn, user_id: str) -> None:
    user = ensure_user(conn, user_id)
    free_draw_count = int(user.get("free_draw_count") or 0)

    if free_draw_count < FREE_GACHA_DRAW_COST:
        raise HTTPException(status_code=400, detail="無料ガチャ回数がありません")

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET free_draw_count = free_draw_count - %s
            WHERE user_id = %s
            """,
            (FREE_GACHA_DRAW_COST, user_id),
        )


def consume_paid_gacha_points(conn, user_id: str, cost: int = PAID_GACHA_POINT_COST) -> None:
    user = ensure_user(conn, user_id)
    points = int(user.get("points") or 0)

    if points < cost:
        raise HTTPException(status_code=400, detail=f"ポイント不足です（{cost}pt必要）")

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET points = points - %s
            WHERE user_id = %s
            """,
            (cost, user_id),
        )


def apply_paid_gacha_creator_royalty(
    conn,
    creator_user_id: str,
    work_id: int,
    amount: int = PAID_GACHA_CREATOR_ROYALTY,
) -> dict[str, int]:
    ensure_user(conn, creator_user_id)

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET royalty_balance = COALESCE(royalty_balance, 0) + %s
            WHERE user_id = %s
            """,
            (amount, creator_user_id),
        )
        cur.execute(
            """
            INSERT INTO royalty_logs(
                user_id,
                work_id,
                source_type,
                amount
            )
            VALUES(%s, %s, %s, %s)
            """,
            (creator_user_id, work_id, "paid_gacha", amount),
        )

    return {
        "creator_royalty": amount,
    }


def _record_gacha_log(
    conn,
    *,
    user_id: str,
    draw_type: str,
    work_id: int,
    creator_user_id: str,
    cost_points: int,
    creator_royalty: int,
    is_duplicate: bool,
    is_win: bool,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO gacha_logs(
                user_id,
                gacha_type,
                work_id,
                creator_user_id,
                cost_points,
                system_points,
                creator_royalty,
                is_duplicate,
                is_win
            )
            VALUES(%s, %s, %s, %s, %s, 0, %s, %s, %s)
            """,
            (
                user_id,
                draw_type,
                work_id,
                creator_user_id,
                cost_points,
                creator_royalty,
                is_duplicate,
                is_win,
            ),
        )


def process_gacha(conn, user_id: str, draw_type: str = "free") -> dict[str, Any]:
    """
    ガチャ本体を helpers 側へ完全統合。
    - free: free_draw_count 消費
    - paid: 30pt 消費 + creator royalty +15
    - 未所有作品: ownership 作成 + owned_cards 作成 + 初回EXP
    - 既存所有作品: 閲覧権付与 + 重複EXP
    """
    if draw_type not in {"free", "paid"}:
        raise HTTPException(status_code=400, detail="draw_type が不正です")

    ensure_system_user(conn)
    reset_daily_duplicate_exp_if_needed(conn, user_id)

    user = ensure_user(conn, user_id)
    user_level = int(user.get("level") or 1)

    if draw_type == "free":
        consume_free_gacha(conn, user_id)
        cost_points = 0
    else:
        consume_paid_gacha_points(conn, user_id, PAID_GACHA_POINT_COST)
        cost_points = PAID_GACHA_POINT_COST

    work = weighted_draw(conn, user_level=user_level)
    work_id = int(work["id"])

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE works
            SET draw_count = COALESCE(draw_count, 0) + 1
            WHERE id = %s
            """,
            (work_id,),
        )

    owner = get_ownership(conn, work_id)
    is_new_owner = owner is None
    owner_user_id = user_id if is_new_owner else str(owner["owner_id"])
    exp_gained = 0

    if is_new_owner:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ownership(work_id, owner_id)
                VALUES(%s, %s)
                """,
                (work_id, user_id),
            )

        create_owned_card_if_missing(conn, user_id, work_id)

        exp_gained = int(work.get("exp_reward") or 5)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET exp = COALESCE(exp, 0) + %s
                WHERE user_id = %s
                """,
                (exp_gained, user_id),
            )
        update_user_level(conn, user_id)
    else:
        grant_view_access(conn, user_id, work_id, "view", "gacha")
        dup = gain_duplicate_exp(conn, user_id, work)
        exp_gained = int(dup.get("added") or 0)

    creator_royalty = 0
    if draw_type == "paid":
        royalty_info = apply_paid_gacha_creator_royalty(
            conn,
            str(work.get("creator_id") or ""),
            work_id,
            PAID_GACHA_CREATOR_ROYALTY,
        )
        creator_royalty = int(royalty_info.get("creator_royalty") or 0)

    refreshed_work = ensure_work(conn, work_id)

    _record_gacha_log(
        conn,
        user_id=user_id,
        draw_type=draw_type,
        work_id=work_id,
        creator_user_id=str(refreshed_work.get("creator_id") or ""),
        cost_points=cost_points,
        creator_royalty=creator_royalty,
        is_duplicate=not is_new_owner,
        is_win=is_new_owner,
    )

    return {
        "ok": True,
        "message": "ガチャ完了" if draw_type == "free" else "ポイントガチャ完了",
        "result": serialize_work(conn, refreshed_work, viewer_user_id=user_id),
        "info": {
            "draw_type": draw_type,
            "is_new_owner": is_new_owner,
            "owner_user_id": owner_user_id,
            "exp_gained": exp_gained,
            "creator_royalty": creator_royalty,
        },
    }


# ─────────────────────────────────────────────
# ポイント分配
# ─────────────────────────────────────────────
def distribute_points(
    conn,
    *,
    buyer_user_id: str,
    seller_user_id: str,
    creator_user_id: str,
    work_id: int,
    total_points: int,
    tx_type: str,
    platform_rate: float = 0.30,
    creator_rate: float = 0.10,
) -> dict[str, int]:
    """
    注意:
    - この関数は呼び出し側トランザクション内で使う前提
    - buyer / seller / creator を個別更新するだけで commit はしない
    - platform_fee は計算のみ。system への加算は行わない。
    """
    if total_points < 0:
        raise HTTPException(status_code=400, detail="ポイントが不正です")

    buyer = ensure_user(conn, buyer_user_id)
    ensure_user(conn, seller_user_id)
    ensure_user(conn, creator_user_id)

    buyer_points = int(buyer.get("points") or 0)
    if buyer_points < total_points:
        raise HTTPException(status_code=400, detail="ポイントが不足しています")

    platform_fee = int(total_points * platform_rate)
    creator_share = int(total_points * creator_rate)
    seller_share = total_points - platform_fee - creator_share

    if seller_share < 0:
        raise HTTPException(status_code=400, detail="分配計算が不正です")

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET points = points - %s
            WHERE user_id = %s
            """,
            (total_points, buyer_user_id),
        )
        cur.execute(
            """
            UPDATE users
            SET points = points + %s
            WHERE user_id = %s
            """,
            (seller_share, seller_user_id),
        )
        cur.execute(
            """
            UPDATE users
            SET royalty_balance = COALESCE(royalty_balance, 0) + %s
            WHERE user_id = %s
            """,
            (creator_share, creator_user_id),
        )
        cur.execute(
            """
            INSERT INTO transactions(
                work_id,
                buyer_user_id,
                seller_user_id,
                creator_user_id,
                total_points,
                platform_fee,
                seller_share,
                creator_share,
                tx_type
            )
            VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                work_id,
                buyer_user_id,
                seller_user_id,
                creator_user_id,
                total_points,
                platform_fee,
                seller_share,
                creator_share,
                tx_type,
            ),
        )
        cur.execute(
            """
            INSERT INTO royalty_logs(
                user_id,
                work_id,
                source_type,
                amount
            )
            VALUES(%s, %s, %s, %s)
            """,
            (creator_user_id, work_id, tx_type, creator_share),
        )

    return {
        "platform_fee": platform_fee,
        "creator_share": creator_share,
        "seller_share": seller_share,
    }


# ─────────────────────────────────────────────
# バトル
# ─────────────────────────────────────────────


def level_up_card_if_needed(conn, card_id: int) -> dict[str, Any]:
    """
    旧仕様固定。
    ⚠️ 成長バランスのため変更禁止。
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM owned_cards
            WHERE id = %s
            FOR UPDATE
            """,
            (card_id,),
        )
        card = cur.fetchone()

        if not card:
            raise HTTPException(status_code=404, detail="カードが存在しません")

        level = int(card.get("level") or 1)
        exp = int(card.get("exp") or 0)

        while exp >= max(30, level * 20):
            need = max(30, level * 20)
            exp -= need
            level += 1

            cur.execute(
                """
                UPDATE owned_cards
                SET level = %s,
                    exp = %s,
                    hp = hp + 2,
                    atk = atk + 2,
                    defense = defense + 2,
                    spd = spd + 1,
                    luk = luk + 1
                WHERE id = %s
                """,
                (level, exp, card_id),
            )

        cur.execute(
            """
            SELECT *
            FROM owned_cards
            WHERE id = %s
            """,
            (card_id,),
        )
        return cur.fetchone()


# ─────────────────────────────────────────────
# レジェンドボール（items / user_items 正本）
# ─────────────────────────────────────────────
def get_user_legend_ball_count(conn, user_id: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(SUM(ui.quantity), 0) AS ball_count
            FROM user_items ui
            JOIN items i ON i.id = ui.item_id
            WHERE ui.user_id = %s
              AND ui.quantity > 0
              AND COALESCE(i.item_type, '') = 'legend_ball'
              AND COALESCE(i.is_active, 1) = 1
            """,
            (user_id,),
        )
        row = cur.fetchone()
    return int(row["ball_count"] or 0)


def steal_random_ball_if_any(conn, winner_user_id: str, loser_user_id: str) -> Optional[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                ui.id AS user_item_id,
                ui.item_id,
                ui.quantity,
                i.name
            FROM user_items ui
            JOIN items i ON i.id = ui.item_id
            WHERE ui.user_id = %s
              AND ui.quantity > 0
              AND COALESCE(i.item_type, '') = 'legend_ball'
              AND COALESCE(i.is_active, 1) = 1
            ORDER BY RANDOM()
            LIMIT 1
            FOR UPDATE
            """,
            (loser_user_id,),
        )
        stolen_row = cur.fetchone()

        if not stolen_row:
            return None

        loser_user_item_id = int(stolen_row["user_item_id"])
        item_id = int(stolen_row["item_id"])
        item_name = str(stolen_row["name"] or "")

        cur.execute(
            """
            UPDATE user_items
            SET quantity = quantity - 1
            WHERE id = %s
            """,
            (loser_user_item_id,),
        )

        cur.execute(
            """
            DELETE FROM user_items
            WHERE id = %s
              AND quantity <= 0
            """,
            (loser_user_item_id,),
        )

        cur.execute(
            """
            SELECT id, quantity
            FROM user_items
            WHERE user_id = %s
              AND item_id = %s
            ORDER BY id ASC
            LIMIT 1
            FOR UPDATE
            """,
            (winner_user_id, item_id),
        )
        winner_row = cur.fetchone()

        if winner_row:
            winner_user_item_id = int(winner_row["id"])
            cur.execute(
                """
                UPDATE user_items
                SET quantity = quantity + 1
                WHERE id = %s
                """,
                (winner_user_item_id,),
            )
        else:
            cur.execute(
                """
                INSERT INTO user_items(
                    user_id,
                    item_id,
                    quantity,
                    level,
                    exp,
                    total_exp,
                    is_locked,
                    is_equipped,
                    slot_no
                )
                VALUES(%s, %s, 1, 1, 0, 0, 0, 0, 0)
                RETURNING id
                """,
                (winner_user_id, item_id),
            )
            inserted = cur.fetchone()
            if not inserted:
                raise HTTPException(status_code=500, detail="奪取アイテム付与に失敗しました")
            winner_user_item_id = int(inserted["id"])

        cur.execute(
            """
            INSERT INTO item_logs(
                user_id,
                item_id,
                user_item_id,
                action_type,
                amount,
                memo
            )
            VALUES(%s, %s, %s, %s, %s, %s)
            """,
            (
                loser_user_id,
                item_id,
                loser_user_item_id,
                "battle_lost",
                1,
                f"battleで{winner_user_id}に奪取された",
            ),
        )

        cur.execute(
            """
            INSERT INTO item_logs(
                user_id,
                item_id,
                user_item_id,
                action_type,
                amount,
                memo
            )
            VALUES(%s, %s, %s, %s, %s, %s)
            """,
            (
                winner_user_id,
                item_id,
                winner_user_item_id,
                "battle_stolen",
                1,
                f"battleで{loser_user_id}から奪取した",
            ),
        )

        return item_name


# ─────────────────────────────────────────────
# シリアライズ
# ─────────────────────────────────────────────
def _serialize_work_base(
    conn,
    work_row: dict[str, Any],
    viewer_user_id: Optional[str] = None,
) -> dict[str, Any]:
    media = resolve_media_access(conn, work_row, viewer_user_id=viewer_user_id)
    item_type = str(work_row.get("item_type") or "work")
    media_type = str(work_row.get("media_type") or work_row.get("type") or "image")

    return {
        "id": int(work_row["id"]),
        "title": str(work_row.get("title") or ""),
        "creator_user_id": str(work_row.get("creator_id") or ""),
        "creator_name": str(work_row.get("creator_name") or ""),
        "description": str(work_row.get("description") or ""),
        "genre": str(work_row.get("genre") or ""),
        "type": str(work_row.get("type") or media_type),
        "media_type": media_type,
        "item_type": item_type,
        "image_url": media["image_url"],
        "video_url": media["video_url"],
        "thumbnail_url": media["thumbnail_url"],
        "preview_url": media["preview_url"],
        "can_view_full": bool(media["can_view_full"]),
        "needs_front_blur": bool(media["needs_front_blur"]),
        "rarity": str(work_row.get("rarity") or "N"),
        "hp": int(work_row.get("hp") or 10),
        "atk": int(work_row.get("atk") or 10),
        "defense": int(work_row.get("defense") or 10),
        "spd": int(work_row.get("spd") or 10),
        "luk": int(work_row.get("luk") or 10),
        "exp_reward": int(work_row.get("exp_reward") or 5),
        "draw_count": int(work_row.get("draw_count") or 0),
        "likes": int(work_row.get("like_count") or 0),
        "is_active": bool(work_row.get("is_active", True)),
        "is_public": bool(work_row.get("is_public", True)),
        "gacha_enabled": bool(work_row.get("gacha_enabled", True)),
        "is_deleted": bool(work_row.get("is_deleted", False)),
        "is_ball": bool(work_row.get("is_ball", False)),
        "is_legend_ball": item_type == "legend_ball" or bool(work_row.get("is_ball")),
        "ball_code": str(work_row.get("ball_code") or ""),
        "legend_code": str(work_row.get("legend_code") or ""),
        "content_hash": str(work_row.get("content_hash") or ""),
        "link_url": str(work_row.get("link_url") or ""),
        "x_url": str(work_row.get("x_url") or ""),
        "booth_url": str(work_row.get("booth_url") or ""),
        "chichipui_url": str(work_row.get("chichipui_url") or ""),
        "dlsite_url": str(work_row.get("dlsite_url") or ""),
        "fanbox_url": str(work_row.get("fanbox_url") or ""),
        "skeb_url": str(work_row.get("skeb_url") or ""),
        "pixiv_url": str(work_row.get("pixiv_url") or ""),
        "published_at": work_row.get("published_at").isoformat() if work_row.get("published_at") else "",
        "created_at": work_row.get("created_at").isoformat() if work_row.get("created_at") else "",
    }


def serialize_work(
    conn,
    work_row: dict[str, Any],
    viewer_user_id: Optional[str] = None,
) -> dict[str, Any]:
    return _serialize_work_base(conn, work_row, viewer_user_id=viewer_user_id)


def serialize_owned_card(
    conn,
    card_row: dict[str, Any],
    viewer_user_id: Optional[str] = None,
    work_row: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if work_row is None:
        work_row = ensure_work(conn, int(card_row["work_id"]))

    base = _serialize_work_base(conn, work_row, viewer_user_id=viewer_user_id)
    base.update(
        {
            "card_id": int(card_row["id"]),
            "work_id": int(card_row["work_id"]),
            "user_id": str(card_row.get("user_id") or ""),
            "owner_user_id": str(card_row.get("user_id") or ""),
            "level": int(card_row.get("level") or 1),
            "exp": int(card_row.get("exp") or 0),
            "total_exp": int(card_row.get("total_exp") or 0),
            "win_count": int(card_row.get("win_count") or 0),
            "battle_count": int(card_row.get("battle_count") or 0),
            "lose_streak_count": int(card_row.get("lose_streak_count") or 0),
            "current_rarity": str(card_row.get("current_rarity") or ""),
            "card_rarity": str(card_row.get("rarity") or base["rarity"]),
            "hp": int(card_row.get("hp") or base["hp"]),
            "atk": int(card_row.get("atk") or base["atk"]),
            "defense": int(card_row.get("defense") or base["defense"]),
            "spd": int(card_row.get("spd") or base["spd"]),
            "luk": int(card_row.get("luk") or base["luk"]),
            "is_legend": bool(card_row.get("is_legend", False)),
            "legend_at": str(card_row.get("legend_at") or ""),
            "owned_created_at": card_row.get("created_at").isoformat() if card_row.get("created_at") else "",
        }
    )
    return base
