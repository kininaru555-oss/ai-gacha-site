"""
routers/works.py — 作品・いいね・AI自動ステータス・管理API
"""
from fastapi import APIRouter, HTTPException

from database import get_db
from helpers import (
    ensure_user,
    ensure_work,
    serialize_work,
    serialize_owned_card,
)
from models import LikeRequest, AdminCreateWorkRequest, AutoStatRequest
from ai_stats import generate_auto_stats

router = APIRouter(tags=["works"])


@router.get("/works")
def get_works():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM works
                WHERE is_active = 1
                ORDER BY id DESC
            """)
            rows = cur.fetchall()

        return {"works": [serialize_work(x) for x in rows]}


@router.post("/works/{work_id}/like")
def like_work(work_id: int, payload: LikeRequest):
    with get_db() as conn:
        ensure_user(conn, payload.user_id)
        ensure_work(conn, work_id)

        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO like_logs(user_id, work_id)
                    VALUES(%s, %s)
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
def get_user_works(user_id: str):
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


@router.post("/ai/generate-stats")
def ai_generate_stats(payload: AutoStatRequest):
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


@router.post("/admin/works/create")
def admin_create_work(payload: AdminCreateWorkRequest):
    with get_db() as conn:
        ensure_user(conn, payload.creator_user_id)

        if not payload.content_hash.strip():
            raise HTTPException(status_code=400, detail="content_hash は必須です")

        with conn.cursor() as cur:
            cur.execute("""
                SELECT id
                FROM works
                WHERE content_hash = %s
                LIMIT 1
            """, (payload.content_hash.strip(),))
            if cur.fetchone():
                raise HTTPException(status_code=400, detail="同一コンテンツの投稿は禁止です")

        if payload.is_ball and payload.ball_code.strip():
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id
                    FROM works
                    WHERE ball_code = %s
                    LIMIT 1
                """, (payload.ball_code.strip(),))
                if cur.fetchone():
                    raise HTTPException(status_code=400, detail="同じball_codeは使えません")

        if payload.type == "image" and not payload.image_url.strip():
            raise HTTPException(status_code=400, detail="imageタイプには image_url が必要です")

        if payload.type == "video" and not payload.video_url.strip():
            raise HTTPException(status_code=400, detail="videoタイプには video_url が必要です")

        hp, atk, defense, spd, luk = (
            payload.hp, payload.atk, payload.defense, payload.spd, payload.luk
        )

        if payload.type == "image" and any(v is None for v in [hp, atk, defense, spd, luk]):
            try:
                auto = generate_auto_stats(
                    image_url=payload.image_url,
                    title=payload.title,
                    description=payload.description,
                    genre=payload.genre,
                )
                hp = hp if hp is not None else auto["hp"]
                atk = atk if atk is not None else auto["atk"]
                defense = defense if defense is not None else auto["defense"]
                spd = spd if spd is not None else auto["spd"]
                luk = luk if luk is not None else auto["luk"]
            except Exception:
                pass

        hp = int(hp or 10)
        atk = int(atk or 10)
        defense = int(defense or 10)
        spd = int(spd or 10)
        luk = int(luk or 10)

        # 一般投稿は常に N 固定
        rarity_value = "N"

        # 運営投稿だけ任意レア度を許可
        if payload.creator_user_id == "admin":
            rarity_value = (payload.rarity or "N").upper().strip()

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO works(
                    title, creator_id, creator_name, description, genre, type,
                    image_url, video_url, thumbnail_url,
                    link_url, x_url, booth_url, chichipui_url, dlsite_url,
                    fanbox_url, skeb_url, pixiv_url,
                    rarity, hp, atk, def, spd, luk, exp_reward,
                    is_active, is_ball, ball_code, content_hash
                ) VALUES(
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                )
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
                payload.fanbox_url,
                payload.skeb_url,
                payload.pixiv_url,
                rarity_value,
                hp,
                atk,
                defense,
                spd,
                luk,
                int(payload.exp_reward),
                1,
                int(payload.is_ball),
                payload.ball_code,
                payload.content_hash.strip(),
            ))
            work_id = cur.fetchone()["id"]

            # 投稿お礼の無料ガチャ
            cur.execute("""
                UPDATE users
                SET free_draw_count = free_draw_count + 1
                WHERE user_id = %s
            """, (payload.creator_user_id,))

        work = ensure_work(conn, work_id)
        user = ensure_user(conn, payload.creator_user_id)

        return {
            "message": "作品を登録しました。投稿のお礼として無料ガチャ1回を付与しました。",
            "work": serialize_work(work),
            "creator_free_draw_count": user["free_draw_count"],
        }


@router.post("/admin/points/add/{user_id}")
def admin_add_points(user_id: str, points: int):
    with get_db() as conn:
        ensure_user(conn, user_id)

        if points <= 0:
            raise HTTPException(status_code=400, detail="ポイントは1以上にしてください")

        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET points = points + %s
                WHERE user_id = %s
            """, (points, user_id))

        user = ensure_user(conn, user_id)
        return {
            "message": f"{user_id} に {points}pt 追加しました",
            "points": user["points"],
        }


@router.post("/admin/free-draw/add/{user_id}")
def admin_add_free_draw(user_id: str, count: int = 1):
    with get_db() as conn:
        ensure_user(conn, user_id)

        if count <= 0:
            raise HTTPException(status_code=400, detail="回数は1以上にしてください")

        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET free_draw_count = free_draw_count + %s
                WHERE user_id = %s
            """, (count, user_id))

        user = ensure_user(conn, user_id)
        return {
            "message": f"{user_id} に無料ガチャ {count} 回追加しました",
            "free_draw_count": user["free_draw_count"],
        }
