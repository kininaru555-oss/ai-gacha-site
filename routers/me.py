from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth_utils import CurrentUser, get_current_user, get_admin_user  # ← 管理者用依存を仮定
from db import get_db_connection, get_columns, table_exists, choose_existing, safe_int

# ログ設定（詳細なログ・監視の第一歩）
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(tags=["me"])


# -----------------------------
# Pydantic models（追加分）
# -----------------------------
class WithdrawApproveReject(BaseModel):
    request_id: int


# -----------------------------
# Utility（ensure系を強化）
# -----------------------------
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_required_tables(conn):
    required = ["users", "works"]
    for t in required:
        if not table_exists(conn, t):
            raise HTTPException(status_code=500, detail="必要なテーブルがありません。")


def ensure_offers_table(conn):
    if not table_exists(conn, "offers"):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_id INTEGER NOT NULL,
                from_user_id TEXT NOT NULL,
                to_user_id TEXT NOT NULL,
                offer_points INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            )
        """)
        logger.info("Created offers table")


def ensure_battle_logs_table(conn):
    if not table_exists(conn, "battle_logs"):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS battle_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                work_id INTEGER NOT NULL,
                result TEXT NOT NULL,
                opponent_name TEXT,
                log TEXT,
                reward_exp INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        logger.info("Created battle_logs table")


def ensure_point_transactions_table(conn):
    if not table_exists(conn, "point_transactions"):
        conn.execute("""
            CREATE TABLE IF NOT EXISTS point_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                amount INTEGER NOT NULL,          -- 正:獲得 / 負:消費
                transaction_type TEXT NOT NULL,   -- 'ad_reward', 'withdraw_request', 'offer_accept' など
                reference_id INTEGER,             -- 関連するID（withdraw_id, offer_id など）
                description TEXT,
                created_at TEXT NOT NULL
            )
        """)
        logger.info("Created point_transactions table")


def ensure_withdraw_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS withdraw_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            amount INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            processed_at TEXT,
            processed_by TEXT
        )
    """)


# ポイント変動を記録するヘルパー（ほぼ全ての増減で呼ぶ）
def record_point_transaction(
    conn,
    user_id: str,
    amount: int,
    transaction_type: str,
    reference_id: int | None = None,
    description: str | None = None
):
    conn.execute(
        """
        INSERT INTO point_transactions 
        (user_id, amount, transaction_type, reference_id, description, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, amount, transaction_type, reference_id, description, utc_now_iso())
    )


# deduct_points / add_points を強化（トランザクション内前提）
def deduct_points(conn, user_id: str, amount: int, transaction_type: str, reference_id: int | None = None):
    conn.execute("BEGIN IMMEDIATE")
    current = conn.execute(
        "SELECT points FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    if not current or safe_int(current["points"]) < amount:
        conn.rollback()
        raise HTTPException(status_code=400, detail="ポイントが不足しています。")

    conn.execute(
        "UPDATE users SET points = points - ? WHERE user_id = ?",
        (amount, user_id)
    )
    record_point_transaction(conn, user_id, -amount, transaction_type, reference_id)


def add_points(conn, user_id: str, amount: int, transaction_type: str, reference_id: int | None = None):
    conn.execute(
        "UPDATE users SET points = points + ? WHERE user_id = ?",
        (amount, user_id)
    )
    record_point_transaction(conn, user_id, amount, transaction_type, reference_id)


# （他のutility関数は前回と同じ → 省略）


# -----------------------------
# レートリミット例（slowapi を想定）
# -----------------------------
# pip install slowapi
# from slowapi import Limiter, _rate_limit_exceeded_handler
# from slowapi.util import get_remote_address
# limiter = Limiter(key_func=get_remote_address)
# app.state.limiter = limiter
# app.add_exception_handler(429, _rate_limit_exceeded_handler)

# 例: 広告報酬に適用する場合
# @router.post("/rewards/ad-xp")
# @limiter.limit("1/hour")  # 1時間に1回
# def reward_ad_xp(...):


# -----------------------------
# GET /users/me/works （簡易ページネーション追加）
# -----------------------------
@router.get("/users/me/works")
def get_my_works(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(get_current_user)
):
    conn = get_db_connection()
    try:
        # ...（前回のクエリ部分はそのまま）...
        # ページネーション追加
        count_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM ... WHERE ...",  # 同じWHERE条件
            (current_user.user_id,)
        ).fetchone()
        total = safe_int(count_row["cnt"])

        # rows = ... LIMIT ? OFFSET ?
        # params に limit, offset を追加

        return {
            "works": [...],
            "total": total,
            "limit": limit,
            "offset": offset
        }
    finally:
        conn.close()


# -----------------------------
# 出金承認・拒否（管理者専用を仮定）
# -----------------------------
@router.post("/withdraw/{request_id}/approve")
def approve_withdraw(
    request_id: int,
    admin_user: CurrentUser = Depends(get_admin_user)  # 管理者認証を別途実装
):
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT user_id, amount, status FROM withdraw_requests WHERE id = ?",
            (request_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "申請が見つかりません。")
        if row["status"] != "pending":
            raise HTTPException(400, "すでに処理済みです。")

        conn.execute("BEGIN IMMEDIATE")
        deduct_points(
            conn,
            row["user_id"],
            row["amount"],
            "withdraw_approved",
            reference_id=request_id
        )

        conn.execute(
            """
            UPDATE withdraw_requests 
            SET status = 'approved', processed_at = ?, processed_by = ?
            WHERE id = ?
            """,
            (utc_now_iso(), admin_user.user_id, request_id)
        )
        conn.commit()

        logger.info(f"Withdraw {request_id} approved by {admin_user.user_id}")
        return {"ok": True, "message": "出金が承認されました。"}
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.post("/withdraw/{request_id}/reject")
def reject_withdraw(
    request_id: int,
    admin_user: CurrentUser = Depends(get_admin_user)
):
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT status FROM withdraw_requests WHERE id = ?",
            (request_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "申請が見つかりません。")
        if row["status"] != "pending":
            raise HTTPException(400, "すでに処理済みです。")

        conn.execute("BEGIN")
        conn.execute(
            """
            UPDATE withdraw_requests 
            SET status = 'rejected', processed_at = ?, processed_by = ?
            WHERE id = ?
            """,
            (utc_now_iso(), admin_user.user_id, request_id)
        )
        conn.commit()

        logger.info(f"Withdraw {request_id} rejected by {admin_user.user_id}")
        return {"ok": True, "message": "出金が拒否されました。"}
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()


# -----------------------------
# 既存エンドポイントの修正例（ポイント記録を追加）
# 例: /rewards/ad-xp
# -----------------------------
@router.post("/rewards/ad-xp")
def reward_ad_xp(current_user: CurrentUser = Depends(get_current_user)):
    conn = get_db_connection()
    try:
        # ...（前回のクールダウンチェックなど）...

        conn.execute("BEGIN")
        add_points(
            conn,
            current_user.user_id,
            20,
            "ad_reward"
        )
        # ad_reward_logs へのINSERTはそのまま
        conn.commit()
        return {"ok": True, "message": "広告報酬を受け取りました。", "reward_exp": 20}
    except:
        conn.rollback()
        raise
    finally:
        conn.close()


# 他のエンドポイント（battle/entry, legend/activate, offer/accept など）でも
# ポイント増減時に record_point_transaction() / deduct_points() / add_points() を呼ぶように修正
