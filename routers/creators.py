"""
creators_ranking.py
クリエイターランキングAPI（PostgreSQL版）
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque, defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Optional

from fastapi import APIRouter, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# ────────────────────────────────────────────────
# 設定
# ────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL or not DATABASE_URL.startswith("postgresql"):
    raise RuntimeError("環境変数 DATABASE_URL に有効な PostgreSQL接続文字列を設定してください")

RANKING_LIMIT_DEFAULT = 10
RANKING_LIMIT_MAX = 100

CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", 120))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", 60))
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", 60))

# スコア計算の重み（環境変数で上書き可能）
WEIGHT_DRAWS          = float(os.getenv("WEIGHT_DRAWS",          0.20))
WEIGHT_LIKES          = float(os.getenv("WEIGHT_LIKES",          1.00))
WEIGHT_AVG_LEVEL      = float(os.getenv("WEIGHT_AVG_LEVEL",      3.00))
WEIGHT_TOP_CARD_POWER = float(os.getenv("WEIGHT_TOP_CARD_POWER", 0.08))
WEIGHT_LEGEND         = float(os.getenv("WEIGHT_LEGEND",        15.0))
WEIGHT_TOTAL_WORKS    = float(os.getenv("WEIGHT_TOTAL_WORKS",    0.50))

# ────────────────────────────────────────────────
# グローバル変数・ロック
# ────────────────────────────────────────────────

router = APIRouter(prefix="/creators", tags=["creators"])

# 接続プール（アプリケーション全体で共有）
_pool: Optional[ConnectionPool] = None

# キャッシュ（limitごとに分ける）
_ranking_cache: dict[int, dict] = {}
_ranking_cache_expires: dict[int, float] = {}
_ranking_cache_lock = threading.Lock()

# Rate Limit（インメモリ・簡易版）
_rate_limit_store: dict[str, deque[float]] = defaultdict(lambda: deque())
_rate_limit_lock = threading.Lock()

# ────────────────────────────────────────────────
# データクラス
# ────────────────────────────────────────────────

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

# ────────────────────────────────────────────────
# ユーティリティ関数
# ────────────────────────────────────────────────

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value) if value is not None else fallback
    except (TypeError, ValueError):
        return fallback

def safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value) if value is not None else fallback
    except (TypeError, ValueError):
        return fallback

def extract_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def enforce_rate_limit(ip: str) -> None:
    now = time.time()
    with _rate_limit_lock:
        q = _rate_limit_store[ip]
        while q and q[0] <= now - RATE_LIMIT_WINDOW_SECONDS:
            q.popleft()
        if len(q) >= RATE_LIMIT_MAX_REQUESTS:
            raise HTTPException(
                status_code=429,
                detail="アクセスが多すぎます。1分ほどお待ちください。"
            )
        q.append(now)

# ────────────────────────────────────────────────
# DBヘルパー（PostgreSQL）
# ────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[psycopg.AsyncConnection, None]:
    if _pool is None:
        raise RuntimeError("Connection pool is not initialized")
    async with _pool.connection() as conn:
        yield conn

async def table_exists(conn: psycopg.AsyncConnection, table_name: str) -> bool:
    row = await conn.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_name = %s
        )
        """,
        (table_name,)
    )
    result = await row.fetchone()
    return bool(result[0]) if result else False

async def get_table_columns(conn: psycopg.AsyncConnection, table_name: str) -> set[str]:
    if not await table_exists(conn, table_name):
        return set()
    rows = await conn.execute(
        """
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = %s
        """,
        (table_name,)
    )
    return {row["column_name"] async for row in rows}

def choose_existing(columns: set[str], *candidates: str) -> Optional[str]:
    for c in candidates:
        if c in columns:
            return c
    return None

# ────────────────────────────────────────────────
# 動的SQL構築関数（変更なし部分が多い）
# ────────────────────────────────────────────────

def build_card_power_expr(work_cols: set[str]) -> str:
    parts = []
    for col in ["hp", "atk", "def", "defense", "spd", "luk"]:
        actual = choose_existing(work_cols, col)
        if actual:
            parts.append(f"COALESCE(w.{actual}, 0)")
    
    level_col = choose_existing(work_cols, "level")
    if level_col:
        parts.append(f"(COALESCE(w.{level_col}, 1) * 3)")  # 最低1倍

    return " + ".join(parts) if parts else "0"

def build_legend_expr(work_cols: set[str]) -> str:
    if "is_legend" in work_cols:
        return "CASE WHEN COALESCE(w.is_legend, FALSE) THEN 1 ELSE 0 END"
    if "legend_rank" in work_cols:
        return "CASE WHEN COALESCE(w.legend_rank, 0) > 0 THEN 1 ELSE 0 END"
    return "0"

def build_official_filter(work_cols: set[str]) -> str:
    if "is_official" in work_cols:
        return "AND COALESCE(w.is_official, FALSE) = FALSE"
    return ""

def build_visibility_filter(work_cols: set[str]) -> str:
    clauses = []
    if "is_deleted" in work_cols:
        clauses.append("COALESCE(w.is_deleted, FALSE) = FALSE")
    if "is_hidden" in work_cols:
        clauses.append("COALESCE(w.is_hidden, FALSE) = FALSE")
    if "is_public" in work_cols:
        clauses.append("COALESCE(w.is_public, TRUE) = TRUE")
    return " AND " + " AND ".join(clauses) if clauses else ""

def build_creator_id_expr(work_cols: set[str]) -> str:
    user_col = choose_existing(work_cols, "creator_id", "creator_user_id", "user_id")
    name_col = choose_existing(work_cols, "creator_name", "author_name")
    
    if user_col and name_col:
        return f"""
            CASE 
                WHEN TRIM(COALESCE(w.{user_col}, '')) <> '' 
                THEN w.{user_col}
                ELSE w.{name_col}
            END
        """
    if user_col:
        return f"w.{user_col}"
    if name_col:
        return f"w.{name_col}"
    raise RuntimeError("creator_id / creator_name 列が見つかりません")

def build_creator_name_expr(work_cols: set[str]) -> str:
    name_col = choose_existing(work_cols, "creator_name", "author_name")
    user_col = choose_existing(work_cols, "creator_id", "creator_user_id", "user_id")
    
    if name_col and user_col:
        return f"""
            CASE 
                WHEN TRIM(COALESCE(w.{name_col}, '')) <> '' 
                THEN w.{name_col}
                ELSE w.{user_col}
            END
        """
    if name_col:
        return f"w.{name_col}"
    if user_col:
        return f"w.{user_col}"
    raise RuntimeError("creator_name / creator_id 列が見つかりません")

async def build_draws_subquery(conn: psycopg.AsyncConnection, work_cols: set[str]) -> str:
    if "draw_count" in work_cols:
        return "SELECT w.id AS work_id, COALESCE(w.draw_count, 0) AS total_draws FROM works w"
    
    for tbl in ["gacha_history", "draw_logs", "gacha_logs"]:
        if await table_exists(conn, tbl):
            cols = await get_table_columns(conn, tbl)
            if "work_id" in cols:
                return f"""
                    SELECT work_id, COUNT(*) AS total_draws 
                    FROM {tbl} 
                    GROUP BY work_id
                """
    return "SELECT w.id AS work_id, 0 AS total_draws FROM works w"

async def build_likes_subquery(conn: psycopg.AsyncConnection) -> str:
    for tbl in ["likes", "work_likes", "like_logs"]:
        if await table_exists(conn, tbl):
            cols = await get_table_columns(conn, tbl)
            if "work_id" in cols:
                return f"""
                    SELECT work_id, COUNT(*) AS total_likes 
                    FROM {tbl} 
                    GROUP BY work_id
                """
    return "SELECT w.id AS work_id, 0 AS total_likes FROM works w"

# ────────────────────────────────────────────────
# メイン取得ロジック
# ────────────────────────────────────────────────

async def fetch_creator_ranking_from_db(limit: int = RANKING_LIMIT_DEFAULT) -> dict[str, Any]:
    async with get_db() as conn:
        async with conn.cursor() as cur:
            work_cols = await get_table_columns(conn, "works")
            if "id" not in work_cols:
                raise RuntimeError("worksテーブルにid列がありません")

            creator_id_expr   = build_creator_id_expr(work_cols)
            creator_name_expr = build_creator_name_expr(work_cols)
            card_power_expr   = build_card_power_expr(work_cols)
            legend_expr       = build_legend_expr(work_cols)
            official_filter   = build_official_filter(work_cols)
            visibility_filter = build_visibility_filter(work_cols)

            draws_subquery = await build_draws_subquery(conn, work_cols)
            likes_subquery = await build_likes_subquery(conn)

            title_col      = choose_existing(work_cols, "title")
            rarity_col     = choose_existing(work_cols, "rarity")
            type_col       = choose_existing(work_cols, "type")
            image_col      = choose_existing(work_cols, "image_url")
            video_col      = choose_existing(work_cols, "video_url")
            thumb_col      = choose_existing(work_cols, "thumbnail_url")
            level_col      = choose_existing(work_cols, "level")

            link_cols = {
                "link_url":   choose_existing(work_cols, "link_url"),
                "booth_url":  choose_existing(work_cols, "booth_url"),
                "fanbox_url": choose_existing(work_cols, "fanbox_url"),
                "skeb_url":   choose_existing(work_cols, "skeb_url"),
                "pixiv_url":  choose_existing(work_cols, "pixiv_url"),
            }

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
                    {creator_id_expr}   AS creator_id,
                    {creator_name_expr} AS creator_name,
                    {f"COALESCE(w.{title_col}, '')" if title_col else "''"} AS title,
                    {f"COALESCE(w.{rarity_col}, 'N')" if rarity_col else "'N'"} AS rarity,
                    {f"COALESCE(w.{type_col}, 'image')" if type_col else "'image'"} AS type,
                    {f"COALESCE(w.{image_col}, '')" if image_col else "''"} AS image_url,
                    {f"COALESCE(w.{video_col}, '')" if video_col else "''"} AS video_url,
                    {f"COALESCE(w.{thumb_col}, '')" if thumb_col else "''"} AS thumbnail_url,
                    {f"COALESCE(w.{level_col}, 1)" if level_col else "1"} AS level,
                    ({card_power_expr}) AS card_power,
                    ({legend_expr}) AS is_legend,
                    COALESCE(wd.total_draws, 0) AS total_draws,
                    COALESCE(wl.total_likes, 0) AS total_likes,
                    {f"COALESCE(w.{link_cols['link_url']}, '')"   if link_cols['link_url']   else "''"} AS link_url,
                    {f"COALESCE(w.{link_cols['booth_url']}, '')"  if link_cols['booth_url']  else "''"} AS booth_url,
                    {f"COALESCE(w.{link_cols['fanbox_url']}, '')" if link_cols['fanbox_url'] else "''"} AS fanbox_url,
                    {f"COALESCE(w.{link_cols['skeb_url']}, '')"   if link_cols['skeb_url']   else "''"} AS skeb_url,
                    {f"COALESCE(w.{link_cols['pixiv_url']}, '')"  if link_cols['pixiv_url']  else "''"} AS pixiv_url
                FROM works w
                LEFT JOIN work_draws wd ON wd.work_id = w.id
                LEFT JOIN work_likes wl ON wl.work_id = w.id
                WHERE TRIM(COALESCE({creator_id_expr}, '')) <> ''
                  {official_filter}
                  {visibility_filter}
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
                    MAX(link_url)   AS link_url,
                    MAX(booth_url)  AS booth_url,
                    MAX(fanbox_url) AS fanbox_url,
                    MAX(skeb_url)   AS skeb_url,
                    MAX(pixiv_url)  AS pixiv_url
                FROM work_base
                GROUP BY creator_id
                HAVING COUNT(*) > 0 
                   AND TRIM(COALESCE(creator_id, '')) <> ''
            ),
            top_cards AS (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY creator_id
                           ORDER BY card_power DESC, total_likes DESC, total_draws DESC, level DESC, id DESC
                       ) AS rn
                FROM work_base
            )
            SELECT
                ca.creator_id,
                ca.creator_name,
                ca.total_works,
                ca.total_draws,
                ca.total_likes,
                ROUND(ca.avg_level::numeric, 2) AS avg_level,
                ca.legend_count,
                ca.link_url,
                ca.booth_url,
                ca.fanbox_url,
                ca.skeb_url,
                ca.pixiv_url,
                tc.id           AS top_card_id,
                tc.title        AS top_card_title,
                tc.rarity       AS top_card_rarity,
                tc.type         AS top_card_type,
                tc.image_url    AS top_card_image_url,
                tc.video_url    AS top_card_video_url,
                tc.thumbnail_url AS top_card_thumbnail_url,
                tc.level        AS top_card_level,
                tc.card_power   AS top_card_power,
                tc.is_legend    AS top_card_is_legend,
                ROUND(
                    (ca.total_draws  * {WEIGHT_DRAWS}) +
                    (ca.total_likes  * {WEIGHT_LIKES}) +
                    (ca.avg_level    * {WEIGHT_AVG_LEVEL}) +
                    (tc.card_power   * {WEIGHT_TOP_CARD_POWER}) +
                    (ca.legend_count * {WEIGHT_LEGEND}) +
                    (ca.total_works  * {WEIGHT_TOTAL_WORKS}),
                    2
                ) AS score
            FROM creator_agg ca
            LEFT JOIN top_cards tc ON tc.creator_id = ca.creator_id AND tc.rn = 1
            ORDER BY score DESC, ca.total_likes DESC, ca.total_draws DESC, ca.total_works DESC, ca.creator_id
            LIMIT %s
            """

            await cur.execute(query, (limit,))
            rows = await cur.fetchall()

            items = []
            for rank, row in enumerate(rows, start=1):
                top_card = None
                if row["top_card_id"] is not None:
                    top_card = TopCard(
                        id            = safe_int(row["top_card_id"]),
                        title         = row["top_card_title"] or "",
                        rarity        = row["top_card_rarity"] or "N",
                        type          = row["top_card_type"] or "image",
                        image_url     = row["top_card_image_url"] or "",
                        video_url     = row["top_card_video_url"] or "",
                        thumbnail_url = row["top_card_thumbnail_url"] or "",
                        level         = safe_int(row["top_card_level"], 1),
                        card_power    = safe_int(row["top_card_power"]),
                        is_legend     = bool(safe_int(row["top_card_is_legend"])),
                    ).__dict__

                items.append({
                    "rank": rank,
                    "creator_id": row["creator_id"] or "",
                    "creator_name": row["creator_name"] or row["creator_id"] or "不明",
                    "score": safe_float(row["score"]),
                    "total_works": safe_int(row["total_works"]),
                    "total_likes": safe_int(row["total_likes"]),
                    "total_draws": safe_int(row["total_draws"]),
                    "avg_level": safe_float(row["avg_level"]),
                    "legend_count": safe_int(row["legend_count"]),
                    "link_url": row["link_url"] or "",
                    "booth_url": row["booth_url"] or "",
                    "fanbox_url": row["fanbox_url"] or "",
                    "skeb_url": row["skeb_url"] or "",
                    "pixiv_url": row["pixiv_url"] or "",
                    "top_card": top_card,
                })

            return {
                "items": items,
                "generated_at": utc_now_iso(),
            }

# ────────────────────────────────────────────────
# キャッシュラッパー
# ────────────────────────────────────────────────

async def get_cached_creator_ranking(limit: int) -> dict:
    now = time.time()

    with _ranking_cache_lock:
        if limit in _ranking_cache and now < _ranking_cache_expires.get(limit, 0):
            data = _ranking_cache[limit]
            return {
                **data,
                "cached": True,
                "cached_at": data["generated_at"],
                "cache_ttl_seconds": CACHE_TTL_SECONDS,
            }

    fresh = await fetch_creator_ranking_from_db(limit)

    with _ranking_cache_lock:
        _ranking_cache[limit] = fresh
        _ranking_cache_expires[limit] = now + CACHE_TTL_SECONDS

    return {
        **fresh,
        "cached": False,
        "cached_at": fresh["generated_at"],
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
    }

# ────────────────────────────────────────────────
# APIエンドポイント
# ────────────────────────────────────────────────

@router.get("/ranking")
async def get_creator_ranking(request: Request, limit: int = RANKING_LIMIT_DEFAULT):
    if limit < 1:
        raise HTTPException(400, "limit は 1 以上にしてください")
    if limit > RANKING_LIMIT_MAX:
        raise HTTPException(400, f"limit は {RANKING_LIMIT_MAX} 以下にしてください")

    ip = extract_client_ip(request)
    enforce_rate_limit(ip)

    try:
        data = await get_cached_creator_ranking(limit)
        return data
    except HTTPException:
        raise
    except Exception as e:
        # 本番では Sentry などへ送信推奨
        return JSONResponse(
            status_code=500,
            content={"detail": "ランキング取得中にエラーが発生しました"}
        )

# ────────────────────────────────────────────────
# アプリケーション起動時 / 終了時の処理
# ────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pool
    _pool = ConnectionPool(
        conninfo=DATABASE_URL,
        min_size=4,
        max_size=20,
        timeout=15,
        kwargs={"autocommit": True, "row_factory": dict_row},
        open=False
    )
    await _pool.open()
    yield
    await _pool.close()

# メインアプリでの使い方例：
# app = FastAPI(lifespan=lifespan)
# app.include_router(router)
