from __future__ import annotations

import sqlite3
import threading
import time
from collections import deque, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/creators", tags=["creators"])

DB_PATH = "app.db"

# -----------------------------
# 調整しやすい設定値
# -----------------------------
RANKING_LIMIT = 10
CACHE_TTL_SECONDS = 120
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 60

# スコア重み
WEIGHT_DRAWS = 0.20
WEIGHT_LIKES = 1.00
WEIGHT_AVG_LEVEL = 3.00
WEIGHT_TOP_CARD_POWER = 0.08
WEIGHT_LEGEND = 15.0
WEIGHT_TOTAL_WORKS = 0.50

# -----------------------------
# キャッシュ
# -----------------------------
_ranking_cache_lock = threading.Lock()
_ranking_cache_data: Optional[dict[str, Any]] = None
_ranking_cache_expires_at: float = 0.0
_ranking_cache_generated_at: Optional[str] = None

# -----------------------------
# シンプルなインメモリ Rate Limit
# 本番は Redis 推奨
# -----------------------------
_rate_limit_lock = threading.Lock()
_rate_limit_store: dict[str, deque[float]] = defaultdict(deque)


@dataclass
class TopCard:
    id: int
    title: str
    rarity: str
    type: str
    image_url: str
    video_url: str
    thumbnail_url: str
    level: int
    card_power: int
    is_legend: bool


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_int(value: Any, fallback: int = 0) -> int:
    try:
        if value is None:
            return fallback
        return int(value)
    except (TypeError, ValueError):
        return fallback


def safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        if value is None:
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback


def extract_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = request.client
    return client.host if client else "unknown"


def enforce_rate_limit(ip: str) -> None:
    now = time.time()
    with _rate_limit_lock:
        q = _rate_limit_store[ip]

        while q and q[0] <= now - RATE_LIMIT_WINDOW_SECONDS:
            q.popleft()

        if len(q) >= RATE_LIMIT_MAX_REQUESTS:
            raise HTTPException(
                status_code=429,
                detail="アクセスが多すぎます。少し時間をおいて再試行してください。"
            )

        q.append(now)


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table' AND name = ?
        """,
        (table_name,)
    ).fetchone()
    return row is not None


def get_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    if not table_exists(conn, table_name):
        return set()

    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def choose_existing(columns: set[str], *candidates: str) -> Optional[str]:
    for c in candidates:
        if c in columns:
            return c
    return None


def build_card_power_expr(work_cols: set[str]) -> str:
    hp_col = choose_existing(work_cols, "hp")
    atk_col = choose_existing(work_cols, "atk")
    def_col = choose_existing(work_cols, "defense", "def")
    spd_col = choose_existing(work_cols, "spd")
    luk_col = choose_existing(work_cols, "luk")
    level_col = choose_existing(work_cols, "level")

    parts = []
    for col in [hp_col, atk_col, def_col, spd_col, luk_col]:
        if col:
            parts.append(f"COALESCE(w.{col}, 0)")
    if level_col:
        parts.append(f"(COALESCE(w.{level_col}, 0) * 3)")

    if not parts:
        return "0"

    return " + ".join(parts)


def build_legend_expr(work_cols: set[str]) -> str:
    if "is_legend" in work_cols:
        return "CASE WHEN COALESCE(w.is_legend, 0) = 1 THEN 1 ELSE 0 END"
    if "legend_rank" in work_cols:
        return "CASE WHEN COALESCE(w.legend_rank, 0) > 0 THEN 1 ELSE 0 END"
    return "0"


def build_official_filter(work_cols: set[str]) -> str:
    if "is_official" in work_cols:
        return "AND COALESCE(w.is_official, 0) = 0"
    return ""


def build_visibility_filter(work_cols: set[str]) -> str:
    clauses = []
    if "is_deleted" in work_cols:
        clauses.append("COALESCE(w.is_deleted, 0) = 0")
    if "is_hidden" in work_cols:
        clauses.append("COALESCE(w.is_hidden, 0) = 0")
    if "is_public" in work_cols:
        clauses.append("COALESCE(w.is_public, 1) = 1")

    if not clauses:
        return ""
    return "AND " + " AND ".join(clauses)


def build_creator_id_expr(work_cols: set[str]) -> str:
    creator_user_col = choose_existing(work_cols, "creator_user_id", "user_id")
    creator_name_col = choose_existing(work_cols, "creator_name", "author_name")

    if creator_user_col and creator_name_col:
        return f"""
            CASE
                WHEN TRIM(COALESCE(w.{creator_user_col}, '')) <> '' THEN w.{creator_user_col}
                ELSE w.{creator_name_col}
            END
        """
    if creator_user_col:
        return f"w.{creator_user_col}"
    if creator_name_col:
        return f"w.{creator_name_col}"

    raise RuntimeError("works テーブルに creator_user_id / creator_name 系の列が見つかりません。")


def build_creator_name_expr(work_cols: set[str]) -> str:
    creator_name_col = choose_existing(work_cols, "creator_name", "author_name")
    creator_user_col = choose_existing(work_cols, "creator_user_id", "user_id")

    if creator_name_col and creator_user_col:
        return f"""
            CASE
                WHEN TRIM(COALESCE(w.{creator_name_col}, '')) <> '' THEN w.{creator_name_col}
                ELSE w.{creator_user_col}
            END
        """
    if creator_name_col:
        return f"w.{creator_name_col}"
    if creator_user_col:
        return f"w.{creator_user_col}"

    raise RuntimeError("works テーブルに creator_user_id / creator_name 系の列が見つかりません。")


def build_draws_subquery(conn: sqlite3.Connection, work_cols: set[str]) -> str:
    # draw_count 列があればそれを使う
    if "draw_count" in work_cols:
        return """
            SELECT
                w.id AS work_id,
                COALESCE(w.draw_count, 0) AS total_draws
            FROM works w
        """

    # gacha_history などがあるなら集計
    if table_exists(conn, "gacha_history"):
        gh_cols = get_table_columns(conn, "gacha_history")
        if "work_id" in gh_cols:
            return """
                SELECT
                    gh.work_id AS work_id,
                    COUNT(*) AS total_draws
                FROM gacha_history gh
                GROUP BY gh.work_id
            """

    if table_exists(conn, "draw_logs"):
        dl_cols = get_table_columns(conn, "draw_logs")
        if "work_id" in dl_cols:
            return """
                SELECT
                    dl.work_id AS work_id,
                    COUNT(*) AS total_draws
                FROM draw_logs dl
                GROUP BY dl.work_id
            """

    return """
        SELECT
            w.id AS work_id,
            0 AS total_draws
        FROM works w
    """


def build_likes_subquery(conn: sqlite3.Connection) -> str:
    if table_exists(conn, "likes"):
        like_cols = get_table_columns(conn, "likes")
        if "work_id" in like_cols:
            return """
                SELECT
                    l.work_id AS work_id,
                    COUNT(*) AS total_likes
                FROM likes l
                GROUP BY l.work_id
            """

    if table_exists(conn, "work_likes"):
        like_cols = get_table_columns(conn, "work_likes")
        if "work_id" in like_cols:
            return """
                SELECT
                    wl.work_id AS work_id,
                    COUNT(*) AS total_likes
                FROM work_likes wl
                GROUP BY wl.work_id
            """

    return """
        SELECT
            w.id AS work_id,
            0 AS total_likes
        FROM works w
    """


def fetch_creator_ranking_from_db(limit: int = RANKING_LIMIT) -> dict[str, Any]:
    conn = get_db_connection()
    try:
        if not table_exists(conn, "works"):
            raise RuntimeError("works テーブルが存在しません。")

        work_cols = get_table_columns(conn, "works")

        if "id" not in work_cols:
            raise RuntimeError("works.id 列が必要です。")

        creator_id_expr = build_creator_id_expr(work_cols)
        creator_name_expr = build_creator_name_expr(work_cols)
        card_power_expr = build_card_power_expr(work_cols)
        legend_expr = build_legend_expr(work_cols)
        official_filter = build_official_filter(work_cols)
        visibility_filter = build_visibility_filter(work_cols)
        draws_subquery = build_draws_subquery(conn, work_cols)
        likes_subquery = build_likes_subquery(conn)

        title_col = choose_existing(work_cols, "title")
        rarity_col = choose_existing(work_cols, "rarity")
        type_col = choose_existing(work_cols, "type")
        image_url_col = choose_existing(work_cols, "image_url")
        video_url_col = choose_existing(work_cols, "video_url")
        thumbnail_url_col = choose_existing(work_cols, "thumbnail_url")
        level_col = choose_existing(work_cols, "level")

        link_url_col = choose_existing(work_cols, "link_url")
        booth_url_col = choose_existing(work_cols, "booth_url")
        fanbox_url_col = choose_existing(work_cols, "fanbox_url")
        skeb_url_col = choose_existing(work_cols, "skeb_url")
        pixiv_url_col = choose_existing(work_cols, "pixiv_url")

        query = f"""
        WITH work_draws AS (
            {draws_subquery}
        ),
        work_likes AS (
            {likes_subquery}
        ),
        work_base AS (
            SELECT
                w.id,
                {creator_id_expr} AS creator_id,
                {creator_name_expr} AS creator_name,
                {f"COALESCE(w.{title_col}, '')" if title_col else "''"} AS title,
                {f"COALESCE(w.{rarity_col}, '')" if rarity_col else "''"} AS rarity,
                {f"COALESCE(w.{type_col}, 'image')" if type_col else "'image'"} AS type,
                {f"COALESCE(w.{image_url_col}, '')" if image_url_col else "''"} AS image_url,
                {f"COALESCE(w.{video_url_col}, '')" if video_url_col else "''"} AS video_url,
                {f"COALESCE(w.{thumbnail_url_col}, '')" if thumbnail_url_col else "''"} AS thumbnail_url,
                {f"COALESCE(w.{level_col}, 0)" if level_col else "0"} AS level,
                ({card_power_expr}) AS card_power,
                ({legend_expr}) AS is_legend,
                COALESCE(wd.total_draws, 0) AS total_draws,
                COALESCE(wl.total_likes, 0) AS total_likes,
                {f"COALESCE(w.{link_url_col}, '')" if link_url_col else "''"} AS link_url,
                {f"COALESCE(w.{booth_url_col}, '')" if booth_url_col else "''"} AS booth_url,
                {f"COALESCE(w.{fanbox_url_col}, '')" if fanbox_url_col else "''"} AS fanbox_url,
                {f"COALESCE(w.{skeb_url_col}, '')" if skeb_url_col else "''"} AS skeb_url,
                {f"COALESCE(w.{pixiv_url_col}, '')" if pixiv_url_col else "''"} AS pixiv_url
            FROM works w
            LEFT JOIN work_draws wd ON wd.work_id = w.id
            LEFT JOIN work_likes wl ON wl.work_id = w.id
            WHERE 1=1
              {official_filter}
              {visibility_filter}
              AND TRIM(COALESCE({creator_id_expr}, '')) <> ''
        ),
        creator_agg AS (
            SELECT
                creator_id,
                MAX(creator_name) AS creator_name,
                COUNT(*) AS total_works,
                SUM(total_draws) AS total_draws,
                SUM(total_likes) AS total_likes,
                AVG(level) AS avg_level,
                SUM(is_legend) AS legend_count,
                MAX(CASE WHEN TRIM(link_url) <> '' THEN link_url ELSE '' END) AS link_url,
                MAX(CASE WHEN TRIM(booth_url) <> '' THEN booth_url ELSE '' END) AS booth_url,
                MAX(CASE WHEN TRIM(fanbox_url) <> '' THEN fanbox_url ELSE '' END) AS fanbox_url,
                MAX(CASE WHEN TRIM(skeb_url) <> '' THEN skeb_url ELSE '' END) AS skeb_url,
                MAX(CASE WHEN TRIM(pixiv_url) <> '' THEN pixiv_url ELSE '' END) AS pixiv_url
            FROM work_base
            GROUP BY creator_id
            HAVING COUNT(*) > 0
        ),
        top_cards AS (
            SELECT
                wb.*,
                ROW_NUMBER() OVER (
                    PARTITION BY wb.creator_id
                    ORDER BY
                        wb.card_power DESC,
                        wb.total_likes DESC,
                        wb.total_draws DESC,
                        wb.level DESC,
                        wb.id DESC
                ) AS rn
            FROM work_base wb
        )
        SELECT
            ca.creator_id,
            ca.creator_name,
            ca.total_works,
            ca.total_draws,
            ca.total_likes,
            ROUND(COALESCE(ca.avg_level, 0), 2) AS avg_level,
            ca.legend_count,
            ca.link_url,
            ca.booth_url,
            ca.fanbox_url,
            ca.skeb_url,
            ca.pixiv_url,

            tc.id AS top_card_id,
            tc.title AS top_card_title,
            tc.rarity AS top_card_rarity,
            tc.type AS top_card_type,
            tc.image_url AS top_card_image_url,
            tc.video_url AS top_card_video_url,
            tc.thumbnail_url AS top_card_thumbnail_url,
            tc.level AS top_card_level,
            tc.card_power AS top_card_power,
            tc.is_legend AS top_card_is_legend,

            ROUND(
                (COALESCE(ca.total_draws, 0) * {WEIGHT_DRAWS}) +
                (COALESCE(ca.total_likes, 0) * {WEIGHT_LIKES}) +
                (COALESCE(ca.avg_level, 0) * {WEIGHT_AVG_LEVEL}) +
                (COALESCE(tc.card_power, 0) * {WEIGHT_TOP_CARD_POWER}) +
                (COALESCE(ca.legend_count, 0) * {WEIGHT_LEGEND}) +
                (COALESCE(ca.total_works, 0) * {WEIGHT_TOTAL_WORKS}),
                2
            ) AS score
        FROM creator_agg ca
        LEFT JOIN top_cards tc
          ON tc.creator_id = ca.creator_id
         AND tc.rn = 1
        WHERE ca.total_works > 0
        ORDER BY
            score DESC,
            ca.total_likes DESC,
            ca.total_draws DESC,
            ca.total_works DESC,
            ca.creator_id ASC
        LIMIT ?
        """

        rows = conn.execute(query, (limit,)).fetchall()

        items: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            top_card = None
            top_card_id = row["top_card_id"]
            if top_card_id is not None:
                top_card = {
                    "id": safe_int(row["top_card_id"]),
                    "title": row["top_card_title"] or "",
                    "rarity": row["top_card_rarity"] or "",
                    "type": row["top_card_type"] or "image",
                    "image_url": row["top_card_image_url"] or "",
                    "video_url": row["top_card_video_url"] or "",
                    "thumbnail_url": row["top_card_thumbnail_url"] or "",
                    "level": safe_int(row["top_card_level"]),
                    "card_power": safe_int(row["top_card_power"]),
                    "is_legend": bool(safe_int(row["top_card_is_legend"])),
                }

            items.append({
                "rank": index,
                "creator_id": row["creator_id"] or "",
                "creator_name": row["creator_name"] or row["creator_id"] or "不明",
                "score": safe_float(row["score"]),
                "total_works": safe_int(row["total_works"]),
                "total_likes": safe_int(row["total_likes"]),
                "total_draws": safe_int(row["total_draws"]),
                "avg_level": round(safe_float(row["avg_level"]), 2),
                "legend_count": safe_int(row["legend_count"]),
                "link_url": row["link_url"] or "",
                "booth_url": row["booth_url"] or "",
                "fanbox_url": row["fanbox_url"] or "",
                "skeb_url": row["skeb_url"] or "",
                "pixiv_url": row["pixiv_url"] or "",
                "top_card": top_card,
            })

        generated_at = utc_now_iso()
        return {
            "items": items,
            "generated_at": generated_at,
        }

    finally:
        conn.close()


def get_cached_creator_ranking(limit: int = RANKING_LIMIT) -> dict[str, Any]:
    global _ranking_cache_data, _ranking_cache_expires_at, _ranking_cache_generated_at

    now = time.time()

    with _ranking_cache_lock:
        if _ranking_cache_data is not None and now < _ranking_cache_expires_at:
            return {
                **_ranking_cache_data,
                "cached": True,
                "cached_at": _ranking_cache_generated_at,
                "updated_at": _ranking_cache_generated_at,
                "cache_ttl_seconds": CACHE_TTL_SECONDS,
            }

    fresh = fetch_creator_ranking_from_db(limit=limit)

    with _ranking_cache_lock:
        _ranking_cache_data = fresh
        _ranking_cache_generated_at = fresh["generated_at"]
        _ranking_cache_expires_at = time.time() + CACHE_TTL_SECONDS

        return {
            **fresh,
            "cached": False,
            "cached_at": _ranking_cache_generated_at,
            "updated_at": _ranking_cache_generated_at,
            "cache_ttl_seconds": CACHE_TTL_SECONDS,
        }


@router.get("/ranking")
def get_creator_ranking(request: Request, limit: int = RANKING_LIMIT) -> dict[str, Any]:
    """
    公開ランキングAPI
    - 認証不要
    - IPごとの簡易Rate Limit
    - 短期キャッシュ
    - updated_at / generated_at / cached_at を返す
    """
    if limit <= 0:
        raise HTTPException(status_code=400, detail="limit は 1 以上にしてください。")
    if limit > 100:
        raise HTTPException(status_code=400, detail="limit は 100 以下にしてください。")

    client_ip = extract_client_ip(request)
    enforce_rate_limit(client_ip)

    try:
        data = get_cached_creator_ranking(limit=limit)
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"ランキング取得中にエラーが発生しました: {str(e)}"
        ) from e
