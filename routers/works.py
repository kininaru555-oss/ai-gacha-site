"""
routers/works.py — 作品・いいね・AI自動ステータス・管理API（完成版）

方針:
- 一般投稿作品の初期 rarity は必ず "N"
- admin / system の公式投稿のみ、許可された rarity を自由設定可
- auto_stats は能力値のみ生成し、rarity は決めない
- 同一 content_hash の重複投稿は禁止（レジェンドボール系は例外）
- 認証は security.py の get_current_user / get_current_admin_user 前提
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks

from database import get_db
from helpers import (
    ensure_user,
    ensure_work,
    serialize_work,
    serialize_owned_card,
    has_view_access,
)
from models import LikeRequest, AdminCreateWorkRequest, AutoStatRequest
from auto_stats import generate_auto_stats
from security import get_current_user, get_current_admin_user

router = APIRouter(tags=["works"])

ALLOWED_RARITIES = {"N", "R", "SR", "SSR", "LEGEND"}
OFFICIAL_CREATOR_IDS = {"admin", "system"}


def _stats_get(stats: Any, key: str):
    """generate_auto_stats の戻り値が dataclass / dict どちらでも吸えるようにする。"""
    if isinstance(stats, dict):
        return stats[key]
    return getattr(stats, key)


@router.get("/works/{user_id}")
def get_works(
    user_id: str,
    current_user=Depends(get_current_user)
):
    """ユーザーごとの作品一覧（閲覧権限付き）"""
    if current_user.user_id != user_id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="他ユーザーの作品一覧は閲覧できません")

    with get_db() as conn:
        ensure_user(conn, user_id)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM works
                WHERE is_active = 1
                ORDER BY id DESC
                LIMIT 50
                """
            )
            rows = cur.fetchall()

        items = []
        for row in rows:
            can_view_full = has_view_access(conn, user_id, row["id"])
            items.append(serialize_work(row, can_view_full=can_view_full))

        return {"works": items}


@router.get("/works")
def get_works_public():
    """公開一覧（閲覧権限なし）"""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM works
                WHERE is_active = 1
                ORDER BY id DESC
                LIMIT 100
                """
            )
            rows = cur.fetchall()

        return {"works": [serialize_work(x, can_view_full=False) for x in rows]}


@router.post("/works/{work_id}/like")
def like_work(
    work_id: int,
    payload: LikeRequest,
    current_user=Depends(get_current_user)
):
    """いいね（本人限定）"""
    if payload.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="他人のIDでいいねはできません")

    with get_db() as conn:
        ensure_user(conn, payload.user_id)
        ensure_work(conn, work_id)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO like_logs(user_id, work_id)
                VALUES(%s, %s)
                ON CONFLICT DO NOTHING
                RETURNING user_id
                """,
                (payload.user_id, work_id),
            )
            inserted = cur.fetchone()

            if inserted:
                cur.execute(
                    """
                    UPDATE works
                    SET like_count = COALESCE(like_count, 0) + 1
                    WHERE id = %s
                    """,
                    (work_id,),
                )
                message = "いいねしました！"
            else:
                message = "すでにいいね済みです"

            cur.execute("SELECT like_count FROM works WHERE id = %s", (work_id,))
            row = cur.fetchone()

        return {"message": message, "likes": int((row or {}).get("like_count", 0))}


@router.get("/users/{user_id}/works")
def get_user_works(
    user_id: str,
    current_user=Depends(get_current_user)
):
    """自分の所有カード一覧（本人限定）"""
    if current_user.user_id != user_id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="他ユーザーの所有カードは閲覧できません")

    with get_db() as conn:
        ensure_user(conn, user_id)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT oc.*
                FROM owned_cards oc
                JOIN ownership o ON o.work_id = oc.work_id
                WHERE o.owner_id = %s
                  AND oc.user_id = %s
                ORDER BY oc.id DESC
                """,
                (user_id, user_id),
            )
            rows = cur.fetchall()

        items = [serialize_owned_card(conn, row) for row in rows]
        return {"works": items}


@router.get("/creators/ranking")
def get_creator_ranking(limit: int = 10):
    """
    creators.py への一本化が理想だが、互換維持のため残す。
    """
    limit = max(1, min(limit, 20))

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH ranked_creators AS (
                    SELECT
                        creator_id,
                        creator_name,
                        COUNT(*) AS total_works,
                        COALESCE(SUM(like_count), 0) AS total_likes,
                        COALESCE(SUM(draw_count), 0) AS total_draws,
                        MAX(NULLIF(link_url, '')) AS link_url,
                        MAX(NULLIF(booth_url, '')) AS booth_url,
                        MAX(NULLIF(fanbox_url, '')) AS fanbox_url,
                        MAX(NULLIF(skeb_url, '')) AS skeb_url,
                        MAX(NULLIF(pixiv_url, '')) AS pixiv_url
                    FROM works
                    WHERE is_active = 1
                      AND creator_id NOT IN ('admin', 'system')
                    GROUP BY creator_id, creator_name
                ),
                creator_top_card AS (
                    SELECT DISTINCT ON (w.creator_id)
                        w.creator_id,
                        oc.rarity,
                        oc.level,
                        oc.is_legend,
                        w.title,
                        w.image_url,
                        w.video_url,
                        (COALESCE(oc.hp,0) + COALESCE(oc.atk,0) + COALESCE(oc.def,0) +
                         COALESCE(oc.spd,0) + COALESCE(oc.luk,0)) AS card_power
                    FROM owned_cards oc
                    JOIN works w ON w.id = oc.work_id
                    WHERE w.is_active = 1
                    ORDER BY w.creator_id, card_power DESC, oc.level DESC, COALESCE(oc.total_exp, 0) DESC
                ),
                creator_stats AS (
                    SELECT
                        w.creator_id,
                        AVG(oc.level) AS avg_level,
                        SUM(CASE WHEN oc.is_legend THEN 1 ELSE 0 END) AS legend_count
                    FROM owned_cards oc
                    JOIN works w ON w.id = oc.work_id
                    WHERE w.is_active = 1
                    GROUP BY w.creator_id
                )
                SELECT
                    rc.*,
                    ctc.title AS top_card_title,
                    ctc.image_url AS top_card_image_url,
                    ctc.video_url AS top_card_video_url,
                    ctc.level AS top_card_level,
                    ctc.rarity AS top_card_rarity,
                    ctc.is_legend AS top_card_is_legend,
                    ctc.card_power AS best_power,
                    COALESCE(cs.avg_level, 0) AS avg_level,
                    COALESCE(cs.legend_count, 0) AS legend_count
                FROM ranked_creators rc
                LEFT JOIN creator_top_card ctc ON rc.creator_id = ctc.creator_id
                LEFT JOIN creator_stats cs ON rc.creator_id = cs.creator_id
                ORDER BY (
                    (rc.total_likes * 3) +
                    (rc.total_draws * 2) +
                    (COALESCE(cs.avg_level, 0) * 10) +
                    (COALESCE(ctc.card_power, 0) * 0.5) +
                    (COALESCE(cs.legend_count, 0) * 50)
                ) DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

        results = []
        for i, row in enumerate(rows, start=1):
            top_card = None
            if row["top_card_title"]:
                top_card = {
                    "title": row["top_card_title"],
                    "image_url": row["top_card_image_url"],
                    "video_url": row["top_card_video_url"],
                    "level": row["top_card_level"],
                    "rarity": row["top_card_rarity"],
                    "is_legend": bool(row["top_card_is_legend"]),
                    "card_power": row["best_power"],
                }

            score = (
                (int(row["total_likes"] or 0) * 3)
                + (int(row["total_draws"] or 0) * 2)
                + (float(row["avg_level"] or 0) * 10)
                + (float(row["best_power"] or 0) * 0.5)
                + (int(row["legend_count"] or 0) * 50)
            )

            results.append({
                "rank": i,
                "creator_id": row["creator_id"],
                "creator_name": row["creator_name"],
                "link_url": row["link_url"],
                "booth_url": row["booth_url"],
                "fanbox_url": row["fanbox_url"],
                "skeb_url": row["skeb_url"],
                "pixiv_url": row["pixiv_url"],
                "total_likes": int(row["total_likes"] or 0),
                "total_draws": int(row["total_draws"] or 0),
                "total_works": int(row["total_works"] or 0),
                "avg_level": round(float(row["avg_level"] or 0), 1),
                "legend_count": int(row["legend_count"] or 0),
                "score": round(score, 1),
                "top_card": top_card,
            })

        return {"items": results}


@router.post("/ai/generate-stats")
async def ai_generate_stats(
    payload: AutoStatRequest,
    current_user=Depends(get_current_user)
):
    """同期版（フロント即時確認用）"""
    try:
        stats = generate_auto_stats(
            image_url=payload.image_url,
            title=payload.title,
            description=payload.description,
            genre=payload.genre,
        )
        return {
            "hp": _stats_get(stats, "hp"),
            "atk": _stats_get(stats, "atk"),
            "defense": _stats_get(stats, "defense"),
            "spd": _stats_get(stats, "spd"),
            "luk": _stats_get(stats, "luk"),
            "score_detail": _stats_get(stats, "score_detail"),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"自動ステータス生成失敗: {str(e)}")


@router.post("/admin/works/create")
def admin_create_work(
    payload: AdminCreateWorkRequest,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_admin_user)
):
    """
    重要仕様:
    - 一般投稿作品の初期 rarity は必ず N
    - admin / system の公式投稿のみ、許可された rarity を自由設定可
    - auto_stats は能力値のみ生成し、rarity は決めない
    """
    with get_db() as conn:
        ensure_user(conn, payload.creator_user_id)

        content_hash = (payload.content_hash or "").strip()
        if not content_hash:
            raise HTTPException(status_code=400, detail="content_hash は必須です")

        media_type = (getattr(payload, "media_type", None) or getattr(payload, "type", None) or "image").strip()
        item_type = (getattr(payload, "item_type", None) or "").strip()
        is_ball = int(getattr(payload, "is_ball", 0) or 0)
        ball_code = (getattr(payload, "ball_code", "") or "").strip()
        legend_code = (getattr(payload, "legend_code", "") or "").strip()

        if not item_type:
            item_type = "legend_ball" if is_ball else "work"
        if not legend_code and ball_code:
            legend_code = ball_code
        if not ball_code and legend_code:
            ball_code = legend_code

        final_rarity = "N"
        if payload.creator_user_id in OFFICIAL_CREATOR_IDS:
            req_rarity = (payload.rarity or "N").upper().strip()
            final_rarity = req_rarity if req_rarity in ALLOWED_RARITIES else "N"

        if item_type != "legend_ball":
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM works WHERE content_hash = %s LIMIT 1", (content_hash,))
                if cur.fetchone():
                    raise HTTPException(status_code=409, detail="同一コンテンツの投稿は禁止です")

        if item_type == "legend_ball" and legend_code:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id FROM works
                    WHERE (ball_code = %s OR legend_code = %s)
                    LIMIT 1
                    """,
                    (legend_code, legend_code),
                )
                if cur.fetchone():
                    raise HTTPException(status_code=409, detail="同じレジェンドコードは使えません")

        if media_type == "image" and not payload.image_url:
            raise HTTPException(status_code=400, detail="imageタイプには image_url が必要です")
        if media_type == "video" and not payload.video_url:
            raise HTTPException(status_code=400, detail="videoタイプには video_url が必要です")

        final_hp = payload.hp
        final_atk = payload.atk
        final_def = payload.def_ if getattr(payload, "def_", None) is not None else getattr(payload, "defense", None)
        final_spd = payload.spd
        final_luk = payload.luk

        needs_auto_stats = (
            media_type == "image" and
            payload.image_url and
            any(v is None for v in [final_hp, final_atk, final_def, final_spd, final_luk])
        )

        if needs_auto_stats:
            try:
                auto = generate_auto_stats(
                    image_url=payload.image_url,
                    title=payload.title or "",
                    description=payload.description or "",
                    genre=payload.genre or "",
                )
                final_hp = final_hp if final_hp is not None else _stats_get(auto, "hp")
                final_atk = final_atk if final_atk is not None else _stats_get(auto, "atk")
                final_def = final_def if final_def is not None else _stats_get(auto, "defense")
                final_spd = final_spd if final_spd is not None else _stats_get(auto, "spd")
                final_luk = final_luk if final_luk is not None else _stats_get(auto, "luk")
            except Exception:
                pass

        final_hp = int(final_hp or 10)
        final_atk = int(final_atk or 10)
        final_def = int(final_def or 10)
        final_spd = int(final_spd or 10)
        final_luk = int(final_luk or 10)
        exp_reward = int(payload.exp_reward or 5)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO works(
                    title, creator_id, creator_name, description, genre, type,
                    media_type, item_type,
                    image_url, video_url, thumbnail_url,
                    link_url, x_url, booth_url, chichipui_url, dlsite_url,
                    fanbox_url, skeb_url, pixiv_url,
                    rarity, hp, atk, def, spd, luk, exp_reward,
                    is_active, is_ball, ball_code, legend_code, content_hash
                ) VALUES(
                    %s,%s,%s,%s,%s,%s,
                    %s,%s,
                    %s,%s,%s,
                    %s,%s,%s,%s,%s,
                    %s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s
                )
                RETURNING id
                """,
                (
                    payload.title,
                    payload.creator_user_id,
                    payload.creator_name,
                    payload.description,
                    payload.genre,
                    media_type,
                    media_type,
                    item_type,
                    payload.image_url,
                    payload.video_url,
                    payload.thumbnail_url,
                    payload.link_url,
                    payload.x_url,
                    payload.booth_url,
                    payload.chichipui_url,
                    payload.dlsite_url,
                    payload.fanbox_url,
                    payload.skeb_url,
                    payload.pixiv_url,
                    final_rarity,
                    final_hp,
                    final_atk,
                    final_def,
                    final_spd,
                    final_luk,
                    exp_reward,
                    1,
                    is_ball,
                    ball_code,
                    legend_code,
                    content_hash,
                ),
            )
            work_id = cur.fetchone()["id"]

            cur.execute(
                """
                UPDATE users
                SET free_draw_count = free_draw_count + 1
                WHERE user_id = %s
                """,
                (payload.creator_user_id,),
            )

        conn.commit()

        work = ensure_work(conn, work_id)
        user = ensure_user(conn, payload.creator_user_id)

        return {
            "message": f"作品を登録しました（レアリティ: {final_rarity}）。投稿のお礼として無料ガチャ1回を付与しました。",
            "work": serialize_work(work, can_view_full=False),
            "creator_free_draw_count": user["free_draw_count"],
        }


@router.post("/admin/points/add/{user_id}")
def admin_add_points(
    user_id: str,
    points: int,
    current_user=Depends(get_current_admin_user)
):
    if points <= 0:
        raise HTTPException(status_code=400, detail="ポイントは1以上にしてください")

    with get_db() as conn:
        ensure_user(conn, user_id)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET points = points + %s WHERE user_id = %s",
                (points, user_id),
            )

        user = ensure_user(conn, user_id)
        return {"message": f"{user_id} に {points}pt 追加しました", "points": user["points"]}


@router.post("/admin/free-draw/add/{user_id}")
def admin_add_free_draw(
    user_id: str,
    count: int = 1,
    current_user=Depends(get_current_admin_user)
):
    if count <= 0:
        raise HTTPException(status_code=400, detail="回数は1以上にしてください")

    with get_db() as conn:
        ensure_user(conn, user_id)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET free_draw_count = free_draw_count + %s
                WHERE user_id = %s
                """,
                (count, user_id),
            )

        user = ensure_user(conn, user_id)
        return {
            "message": f"{user_id} に無料ガチャ {count} 回追加しました",
            "free_draw_count": user["free_draw_count"],
        }
