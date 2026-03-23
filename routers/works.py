"""
routers/works.py — 作品・いいね・AI自動ステータス・管理API（完全修正版）
"""
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

from database import get_db
from helpers import (
    ensure_user,
    ensure_work,
    serialize_work,
    serialize_owned_card,
    has_view_access,
)
from models import LikeRequest, AdminCreateWorkRequest, AutoStatRequest
from ai_stats import generate_auto_stats
from security import get_current_user, get_current_admin_user  # ← 新規作成推奨

router = APIRouter(tags=["works"])


# ====================== 認証付きエンドポイント ======================

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
            cur.execute("""
                SELECT * FROM works
                WHERE is_active = 1
                ORDER BY id DESC
                LIMIT 50
            """)
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
            cur.execute("""
                SELECT * FROM works
                WHERE is_active = 1
                ORDER BY id DESC
                LIMIT 100
            """)
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

        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO like_logs(user_id, work_id)
                    VALUES(%s, %s)
                    ON CONFLICT DO NOTHING
                """, (payload.user_id, work_id))
                cur.execute("""
                    UPDATE works
                    SET like_count = like_count + 1
                    WHERE id = %s
                """, (work_id,))
        except Exception:
            likes = ensure_work(conn, work_id)["like_count"]
            return {"message": "すでにいいね済みです", "likes": likes}

        likes = ensure_work(conn, work_id)["like_count"]
        return {"message": "いいねしました！", "likes": likes}


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
            cur.execute("""
                SELECT oc.*
                FROM owned_cards oc
                JOIN ownership o ON o.work_id = oc.work_id
                WHERE o.owner_id = %s
                  AND oc.user_id = %s
                ORDER BY oc.id DESC
            """, (user_id, user_id))
            rows = cur.fetchall()

        items = [serialize_owned_card(conn, row) for row in rows]
        return {"works": items}


# ====================== クリエイターランキング（N+1完全解消） ======================

@router.get("/creators/ranking")
def get_creator_ranking(limit: int = 10):
    limit = max(1, min(limit, 20))

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                WITH ranked_creators AS (
                    SELECT
                        creator_id,
                        creator_name,
                        COUNT(*) AS total_works,
                        SUM(like_count) AS total_likes,
                        SUM(draw_count) AS total_draws,
                        MAX(NULLIF(link_url, '')) AS link_url,
                        MAX(NULLIF(booth_url, '')) AS booth_url,
                        MAX(NULLIF(fanbox_url, '')) AS fanbox_url,
                        MAX(NULLIF(skeb_url, '')) AS skeb_url,
                        MAX(NULLIF(pixiv_url, '')) AS pixiv_url
                    FROM works
                    WHERE is_active = 1
                      AND creator_id <> 'admin'
                    GROUP BY creator_id, creator_name
                ),
                creator_top_card AS (
                    SELECT DISTINCT ON (w.creator_id)
                        w.creator_id,
                        oc.*,
                        w.title,
                        w.image_url,
                        w.video_url,
                        (COALESCE(oc.hp,0) + COALESCE(oc.atk,0) + COALESCE(oc.def,0) +
                         COALESCE(oc.spd,0) + COALESCE(oc.luk,0)) AS card_power
                    FROM owned_cards oc
                    JOIN works w ON w.id = oc.work_id
                    WHERE w.is_active = 1
                    ORDER BY w.creator_id, card_power DESC, oc.level DESC, oc.total_exp DESC
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
            """, (limit,))
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
                "score": 0,  # 必要ならここで再計算
                "top_card": top_card,
            })

        return {"items": results}


# ====================== AI自動ステータス（非同期化） ======================

async def background_generate_stats(
    image_url: str,
    title: str,
    description: str,
    genre: str,
    work_id: Optional[int] = None
):
    """バックグラウンドで自動ステータス生成"""
    try:
        stats = generate_auto_stats(image_url, title, description, genre)
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE owned_cards
                    SET hp=%s, atk=%s, def=%s, spd=%s, luk=%s
                    WHERE work_id = %s
                """, (stats["hp"], stats["atk"], stats["defense"],
                      stats["spd"], stats["luk"], work_id))
    except Exception:
        pass  # 失敗しても投稿自体は成功させる


@router.post("/ai/generate-stats")
async def ai_generate_stats(
    payload: AutoStatRequest,
    background_tasks: BackgroundTasks,
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
        return stats
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"自動ステータス生成失敗: {str(e)}")


# ====================== 管理API（admin限定） ======================

@router.post("/admin/works/create")
def admin_create_work(
    payload: AdminCreateWorkRequest,
    background_tasks: BackgroundTasks,
    current_user=Depends(get_current_admin_user)  # ← ここでadmin限定
):
    with get_db() as conn:
        ensure_user(conn, payload.creator_user_id)

        if not payload.content_hash.strip():
            raise HTTPException(status_code=400, detail="content_hash は必須です")

        # 重複チェック（より厳格に）
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id FROM works WHERE content_hash = %s LIMIT 1
            """, (payload.content_hash.strip(),))
            if cur.fetchone():
                raise HTTPException(status_code=409, detail="同一コンテンツの投稿は禁止です")

        # ball_code 重複チェック
        if payload.is_ball and payload.ball_code.strip():
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM works WHERE ball_code = %s LIMIT 1",
                           (payload.ball_code.strip(),))
                if cur.fetchone():
                    raise HTTPException(status_code=409, detail="同じball_codeは使えません")

        # URL必須チェック
        if payload.type == "image" and not payload.image_url:
            raise HTTPException(status_code=400, detail="imageタイプには image_url が必要です")
        if payload.type == "video" and not payload.video_url:
            raise HTTPException(status_code=400, detail="videoタイプには video_url が必要です")

        # 自動ステータス補完（画像のみ）
        hp = int(payload.hp or 10)
        atk = int(payload.atk or 10)
        defense = int(payload.defense or 10)
        spd = int(payload.spd or 10)
        luk = int(payload.luk or 10)

        if payload.type == "image" and any(v == 10 for v in [hp, atk, defense, spd, luk]):
            try:
                auto = generate_auto_stats(
                    image_url=payload.image_url,
                    title=payload.title,
                    description=payload.description,
                    genre=payload.genre,
                )
                hp = hp if payload.hp is not None else auto["hp"]
                atk = atk if payload.atk is not None else auto["atk"]
                defense = defense if payload.defense is not None else auto["defense"]
                spd = spd if payload.spd is not None else auto["spd"]
                luk = luk if payload.luk is not None else auto["luk"]
            except Exception:
                pass

        rarity_value = (payload.rarity or "N").upper().strip() if payload.creator_user_id == "admin" else "N"

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO works(
                    title, creator_id, creator_name, description, genre, type,
                    image_url, video_url, thumbnail_url,
                    link_url, x_url, booth_url, chichipui_url, dlsite_url,
                    fanbox_url, skeb_url, pixiv_url,
                    rarity, hp, atk, def, spd, luk, exp_reward,
                    is_active, is_ball, ball_code, content_hash
                ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                         %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
            """, (
                payload.title, payload.creator_user_id, payload.creator_name,
                payload.description, payload.genre, payload.type,
                payload.image_url, payload.video_url, payload.thumbnail_url,
                payload.link_url, payload.x_url, payload.booth_url,
                payload.chichipui_url, payload.dlsite_url,
                payload.fanbox_url, payload.skeb_url, payload.pixiv_url,
                rarity_value,
                hp, atk, defense, spd, luk,
                int(payload.exp_reward or 5),
                1, int(payload.is_ball or 0), payload.ball_code,
                payload.content_hash.strip()
            ))
            work_id = cur.fetchone()["id"]

            # 投稿者に無料ガチャ付与
            cur.execute("""
                UPDATE users SET free_draw_count = free_draw_count + 1
                WHERE user_id = %s
            """, (payload.creator_user_id,))

        # 非同期で詳細ステータス更新（画像の場合）
        if payload.type == "image":
            background_tasks.add_task(
                background_generate_stats,
                payload.image_url, payload.title,
                payload.description, payload.genre,
                work_id
            )

        work = ensure_work(conn, work_id)
        user = ensure_user(conn, payload.creator_user_id)

        return {
            "message": "作品を登録しました。投稿のお礼として無料ガチャ1回を付与しました。",
            "work": serialize_work(work, can_view_full=False),
            "creator_free_draw_count": user["free_draw_count"],
        }


# ====================== その他管理API（admin限定） ======================

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
            cur.execute("UPDATE users SET points = points + %s WHERE user_id = %s",
                       (points, user_id))

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
            cur.execute("""
                UPDATE users SET free_draw_count = free_draw_count + %s
                WHERE user_id = %s
            """, (count, user_id))

        user = ensure_user(conn, user_id)
        return {
            "message": f"{user_id} に無料ガチャ {count} 回追加しました",
            "free_draw_count": user["free_draw_count"]
    }
