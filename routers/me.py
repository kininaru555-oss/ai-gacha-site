from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth_utils import CurrentUser, get_current_user
from db import get_db_connection, get_columns, table_exists, choose_existing, safe_int

router = APIRouter(tags=["me"])


# -----------------------------
# Pydantic models
# -----------------------------
class BattleEntryRequest(BaseModel):
    work_id: int


class MarketListRequest(BaseModel):
    work_id: int
    price_points: int = Field(ge=1)


class LegendActivateRequest(BaseModel):
    work_id: int


class WithdrawRequestBody(BaseModel):
    amount: int = Field(ge=1000)


# -----------------------------
# Utility
# -----------------------------
def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_required_tables(conn):
    required = [
        "users",
        "works",
    ]
    for t in required:
        if not table_exists(conn, t):
            raise HTTPException(status_code=500, detail=f"{t} テーブルがありません。")


def get_user_row(conn, user_id: str):
    row = conn.execute(
        "SELECT * FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません。")
    return row


def get_user_points(conn, user_id: str) -> int:
    row = conn.execute(
        "SELECT points FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません。")
    return safe_int(row["points"])


def get_user_ball_count(conn, user_id: str) -> int:
    if table_exists(conn, "user_balls"):
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM user_balls WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        return safe_int(row["cnt"])

    row = conn.execute(
        "SELECT ball_count FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    return safe_int(row["ball_count"]) if row else 0


def get_work_owner(conn, work_id: int) -> str | None:
    if table_exists(conn, "work_owners"):
        row = conn.execute(
            """
            SELECT owner_user_id
            FROM work_owners
            WHERE work_id = ?
            """,
            (work_id,)
        ).fetchone()
        if row:
            return row["owner_user_id"]

    work_cols = get_columns(conn, "works")
    owner_col = choose_existing(work_cols, "owner_user_id", "current_owner_user_id")
    if owner_col:
        row = conn.execute(
            f"SELECT {owner_col} AS owner_user_id FROM works WHERE id = ?",
            (work_id,)
        ).fetchone()
        if row:
            return row["owner_user_id"]

    return None


def assert_work_owned_by_current_user(conn, work_id: int, user_id: str):
    owner_id = get_work_owner(conn, work_id)
    if not owner_id:
        raise HTTPException(status_code=400, detail="作品の所有者情報がありません。")
    if owner_id != user_id:
        raise HTTPException(status_code=403, detail="この作品を操作する権限がありません。")


def get_offer_row(conn, offer_id: int):
    if not table_exists(conn, "offers"):
        raise HTTPException(status_code=500, detail="offers テーブルがありません。")

    row = conn.execute(
        "SELECT * FROM offers WHERE id = ?",
        (offer_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="オファーが見つかりません。")
    return row


def ensure_ad_reward_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ad_reward_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            rewarded_exp INTEGER NOT NULL DEFAULT 20,
            created_at TEXT NOT NULL
        )
        """
    )


def ensure_withdraw_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS withdraw_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            amount INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
        """
    )


def ensure_market_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS market_listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_id INTEGER NOT NULL,
            seller_user_id TEXT NOT NULL,
            price_points INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        )
        """
    )


# -----------------------------
# GET /users/me
# -----------------------------
@router.get("/users/me")
def get_me(current_user: CurrentUser = Depends(get_current_user)):
    conn = get_db_connection()
    try:
        ensure_required_tables(conn)
        row = get_user_row(conn, current_user.user_id)

        return {
            "user_id": row["user_id"],
            "points": safe_int(row["points"]),
            "exp": safe_int(row["exp"]),
            "level": safe_int(row["level"], 1),
            "free_draw_count": safe_int(row["free_draw_count"]),
            "revive_item_count": safe_int(row["revive_item_count"]),
            "ball_count": get_user_ball_count(conn, current_user.user_id),
        }
    finally:
        conn.close()


# -----------------------------
# GET /balls/me
# -----------------------------
@router.get("/balls/me")
def get_my_balls(current_user: CurrentUser = Depends(get_current_user)):
    conn = get_db_connection()
    try:
        items = []

        if table_exists(conn, "user_balls"):
            rows = conn.execute(
                """
                SELECT ball_code
                FROM user_balls
                WHERE user_id = ?
                ORDER BY ball_code ASC
                """,
                (current_user.user_id,)
            ).fetchall()
            items = [{"ball_code": r["ball_code"]} for r in rows]
        else:
            row = conn.execute(
                "SELECT ball_count FROM users WHERE user_id = ?",
                (current_user.user_id,)
            ).fetchone()
            count = safe_int(row["ball_count"]) if row else 0
            items = [{"ball_code": f"BALL_{i}"} for i in range(1, min(count, 7) + 1)]

        return {"items": items}
    finally:
        conn.close()


# -----------------------------
# GET /offers/me
# -----------------------------
@router.get("/offers/me")
def get_my_offers(current_user: CurrentUser = Depends(get_current_user)):
    conn = get_db_connection()
    try:
        if not table_exists(conn, "offers"):
            return {"incoming": [], "outgoing": []}

        incoming_rows = conn.execute(
            """
            SELECT
                o.id,
                o.work_id,
                o.from_user_id AS from_user,
                o.to_user_id AS to_user,
                o.offer_points AS points,
                o.status,
                COALESCE(w.title, '') AS work_title
            FROM offers o
            LEFT JOIN works w ON w.id = o.work_id
            WHERE o.to_user_id = ?
            ORDER BY o.id DESC
            """,
            (current_user.user_id,)
        ).fetchall()

        outgoing_rows = conn.execute(
            """
            SELECT
                o.id,
                o.work_id,
                o.from_user_id AS from_user,
                o.to_user_id AS to_user,
                o.offer_points AS points,
                o.status,
                COALESCE(w.title, '') AS work_title
            FROM offers o
            LEFT JOIN works w ON w.id = o.work_id
            WHERE o.from_user_id = ?
            ORDER BY o.id DESC
            """,
            (current_user.user_id,)
        ).fetchall()

        return {
            "incoming": [dict(r) for r in incoming_rows],
            "outgoing": [dict(r) for r in outgoing_rows],
        }
    finally:
        conn.close()


# -----------------------------
# POST /offers/{offer_id}/accept
# -----------------------------
@router.post("/offers/{offer_id}/accept")
def accept_offer(offer_id: int, current_user: CurrentUser = Depends(get_current_user)):
    conn = get_db_connection()
    try:
        offer = get_offer_row(conn, offer_id)

        if offer["status"] != "pending":
            raise HTTPException(status_code=400, detail="このオファーは処理済みです。")

        if offer["to_user_id"] != current_user.user_id:
            raise HTTPException(status_code=403, detail="このオファーを承認する権限がありません。")

        work_id = safe_int(offer["work_id"])
        owner_id = get_work_owner(conn, work_id)
        if owner_id != current_user.user_id:
            raise HTTPException(status_code=403, detail="現在の所有者ではないため承認できません。")

        buyer_id = offer["from_user_id"]
        points = safe_int(offer["offer_points"])

        buyer_points = get_user_points(conn, buyer_id)
        if buyer_points < points:
            raise HTTPException(status_code=400, detail="オファー送信者のポイント残高が不足しています。")

        # トランザクション開始
        conn.execute("BEGIN")

        conn.execute(
            "UPDATE users SET points = points - ? WHERE user_id = ?",
            (points, buyer_id)
        )
        conn.execute(
            "UPDATE users SET points = points + ? WHERE user_id = ?",
            (points, current_user.user_id)
        )

        if table_exists(conn, "work_owners"):
            conn.execute(
                "UPDATE work_owners SET owner_user_id = ? WHERE work_id = ?",
                (buyer_id, work_id)
            )
        else:
            work_cols = get_columns(conn, "works")
            owner_col = choose_existing(work_cols, "owner_user_id", "current_owner_user_id")
            if owner_col:
                conn.execute(
                    f"UPDATE works SET {owner_col} = ? WHERE id = ?",
                    (buyer_id, work_id)
                )

        conn.execute(
            "UPDATE offers SET status = 'accepted' WHERE id = ?",
            (offer_id,)
        )
        conn.execute(
            """
            UPDATE offers
            SET status = 'cancelled'
            WHERE work_id = ?
              AND id <> ?
              AND status = 'pending'
            """,
            (work_id, offer_id)
        )

        conn.commit()

        return {"ok": True, "message": "オファーを承認しました。"}
    except:
        conn.rollback()
        raise
    finally:
        conn.close()


# -----------------------------
# POST /offers/{offer_id}/reject
# -----------------------------
@router.post("/offers/{offer_id}/reject")
def reject_offer(offer_id: int, current_user: CurrentUser = Depends(get_current_user)):
    conn = get_db_connection()
    try:
        offer = get_offer_row(conn, offer_id)

        if offer["to_user_id"] != current_user.user_id:
            raise HTTPException(status_code=403, detail="このオファーを拒否する権限がありません。")

        if offer["status"] != "pending":
            raise HTTPException(status_code=400, detail="このオファーは処理済みです。")

        conn.execute(
            "UPDATE offers SET status = 'rejected' WHERE id = ?",
            (offer_id,)
        )
        conn.commit()

        return {"ok": True, "message": "オファーを拒否しました。"}
    finally:
        conn.close()


# -----------------------------
# GET /users/me/works
# -----------------------------
@router.get("/users/me/works")
def get_my_works(current_user: CurrentUser = Depends(get_current_user)):
    conn = get_db_connection()
    try:
        work_cols = get_columns(conn, "works")
        owner_col = choose_existing(work_cols, "owner_user_id", "current_owner_user_id")
        if not owner_col and not table_exists(conn, "work_owners"):
            return {"works": []}

        power_expr_parts = []
        for col in ["hp", "atk", "defense", "def", "spd", "luk"]:
            if col in work_cols:
                power_expr_parts.append(f"COALESCE(w.{col}, 0)")
        if "level" in work_cols:
            power_expr_parts.append("(COALESCE(w.level, 0) * 3)")
        power_expr = " + ".join(power_expr_parts) if power_expr_parts else "0"

        if table_exists(conn, "work_owners"):
            rows = conn.execute(
                f"""
                SELECT
                    w.id AS work_id,
                    COALESCE(w.title, '') AS title,
                    COALESCE(w.creator_name, '') AS creator_name,
                    COALESCE(w.rarity, 'N') AS rarity,
                    COALESCE(w.image_url, '') AS image_url,
                    COALESCE(w.video_url, '') AS video_url,
                    COALESCE(w.thumbnail_url, '') AS thumbnail_url,
                    COALESCE(w.hp, 0) AS hp,
                    COALESCE(w.atk, 0) AS atk,
                    COALESCE(w.defense, COALESCE(w.def, 0)) AS def,
                    COALESCE(w.spd, 0) AS spd,
                    COALESCE(w.luk, 0) AS luk,
                    COALESCE(w.level, 1) AS level,
                    COALESCE(w.exp, 0) AS exp,
                    COALESCE(w.total_exp, 0) AS total_exp,
                    COALESCE(w.win_count, 0) AS win_count,
                    COALESCE(w.battle_count, 0) AS battle_count,
                    COALESCE(w.lose_streak_count, 0) AS lose_streak_count,
                    COALESCE(w.draw_count, 0) AS draw_count,
                    COALESCE(w.is_legend, 0) AS is_legend,
                    COALESCE(w.is_ball, 0) AS is_ball,
                    ({power_expr}) AS power
                FROM works w
                INNER JOIN work_owners wo ON wo.work_id = w.id
                WHERE wo.owner_user_id = ?
                ORDER BY w.id DESC
                """,
                (current_user.user_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                f"""
                SELECT
                    w.id AS work_id,
                    COALESCE(w.title, '') AS title,
                    COALESCE(w.creator_name, '') AS creator_name,
                    COALESCE(w.rarity, 'N') AS rarity,
                    COALESCE(w.image_url, '') AS image_url,
                    COALESCE(w.video_url, '') AS video_url,
                    COALESCE(w.thumbnail_url, '') AS thumbnail_url,
                    COALESCE(w.hp, 0) AS hp,
                    COALESCE(w.atk, 0) AS atk,
                    COALESCE(w.defense, COALESCE(w.def, 0)) AS def,
                    COALESCE(w.spd, 0) AS spd,
                    COALESCE(w.luk, 0) AS luk,
                    COALESCE(w.level, 1) AS level,
                    COALESCE(w.exp, 0) AS exp,
                    COALESCE(w.total_exp, 0) AS total_exp,
                    COALESCE(w.win_count, 0) AS win_count,
                    COALESCE(w.battle_count, 0) AS battle_count,
                    COALESCE(w.lose_streak_count, 0) AS lose_streak_count,
                    COALESCE(w.draw_count, 0) AS draw_count,
                    COALESCE(w.is_legend, 0) AS is_legend,
                    COALESCE(w.is_ball, 0) AS is_ball,
                    ({power_expr}) AS power
                FROM works w
                WHERE w.{owner_col} = ?
                ORDER BY w.id DESC
                """,
                (current_user.user_id,)
            ).fetchall()

        return {"works": [dict(r) for r in rows]}
    finally:
        conn.close()


# -----------------------------
# GET /battle/logs/me
# -----------------------------
@router.get("/battle/logs/me")
def get_my_battle_logs(current_user: CurrentUser = Depends(get_current_user)):
    conn = get_db_connection()
    try:
        if not table_exists(conn, "battle_logs"):
            return {"logs": []}

        rows = conn.execute(
            """
            SELECT
                id,
                result,
                opponent_name,
                log,
                reward_exp,
                created_at
            FROM battle_logs
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 100
            """,
            (current_user.user_id,)
        ).fetchall()

        return {"logs": [dict(r) for r in rows]}
    finally:
        conn.close()


# -----------------------------
# POST /battle/entry
# -----------------------------
@router.post("/battle/entry")
def battle_entry(
    body: BattleEntryRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    conn = get_db_connection()
    try:
        assert_work_owned_by_current_user(conn, body.work_id, current_user.user_id)

        if not table_exists(conn, "battle_logs"):
            conn.execute(
                """
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
                """
            )

        reward_exp = 10
        result = "win"
        opponent_name = "CPU"
        log_text = "バトルに勝利しました。"

        conn.execute("BEGIN")

        conn.execute(
            """
            INSERT INTO battle_logs (user_id, work_id, result, opponent_name, log, reward_exp, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (current_user.user_id, body.work_id, result, opponent_name, log_text, reward_exp, utc_now_iso())
        )

        if "exp" in get_columns(conn, "works"):
            conn.execute(
                "UPDATE works SET exp = COALESCE(exp, 0) + ? WHERE id = ?",
                (reward_exp, body.work_id)
            )
        if "total_exp" in get_columns(conn, "works"):
            conn.execute(
                "UPDATE works SET total_exp = COALESCE(total_exp, 0) + ? WHERE id = ?",
                (reward_exp, body.work_id)
            )
        if "battle_count" in get_columns(conn, "works"):
            conn.execute(
                "UPDATE works SET battle_count = COALESCE(battle_count, 0) + 1 WHERE id = ?",
                (body.work_id,)
            )
        if "win_count" in get_columns(conn, "works"):
            conn.execute(
                "UPDATE works SET win_count = COALESCE(win_count, 0) + 1 WHERE id = ?",
                (body.work_id,)
            )

        conn.execute(
            "UPDATE users SET exp = COALESCE(exp, 0) + ? WHERE user_id = ?",
            (reward_exp, current_user.user_id)
        )

        conn.commit()

        return {"ok": True, "message": "バトルに参加しました。"}
    except:
        conn.rollback()
        raise
    finally:
        conn.close()


# -----------------------------
# POST /market/list
# -----------------------------
@router.post("/market/list")
def market_list(
    body: MarketListRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    conn = get_db_connection()
    try:
        ensure_market_table(conn)
        assert_work_owned_by_current_user(conn, body.work_id, current_user.user_id)

        existing = conn.execute(
            """
            SELECT id
            FROM market_listings
            WHERE work_id = ?
              AND status = 'active'
            """,
            (body.work_id,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="この作品はすでに出品中です。")

        conn.execute(
            """
            INSERT INTO market_listings (work_id, seller_user_id, price_points, status, created_at)
            VALUES (?, ?, ?, 'active', ?)
            """,
            (body.work_id, current_user.user_id, body.price_points, utc_now_iso())
        )
        conn.commit()

        return {"ok": True, "message": "マーケットに出品しました。"}
    finally:
        conn.close()


# -----------------------------
# POST /legend/activate
# -----------------------------
@router.post("/legend/activate")
def legend_activate(
    body: LegendActivateRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    conn = get_db_connection()
    try:
        assert_work_owned_by_current_user(conn, body.work_id, current_user.user_id)

        work = conn.execute(
            "SELECT * FROM works WHERE id = ?",
            (body.work_id,)
        ).fetchone()
        if not work:
            raise HTTPException(status_code=404, detail="作品が見つかりません。")

        if safe_int(work["is_legend"]) == 1:
            raise HTTPException(status_code=400, detail="この作品はすでにレジェンド化済みです。")

        ball_count = get_user_ball_count(conn, current_user.user_id)
        if ball_count < 7:
            raise HTTPException(status_code=400, detail="トラゴンボウルが不足しています。")

        conn.execute("BEGIN")

        if table_exists(conn, "user_balls"):
            rows = conn.execute(
                """
                SELECT id
                FROM user_balls
                WHERE user_id = ?
                ORDER BY id ASC
                LIMIT 7
                """,
                (current_user.user_id,)
            ).fetchall()

            if len(rows) < 7:
                raise HTTPException(status_code=400, detail="トラゴンボウルが不足しています。")

            ids = [r["id"] for r in rows]
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                f"DELETE FROM user_balls WHERE id IN ({placeholders})",
                ids
            )
        else:
            conn.execute(
                """
                UPDATE users
                SET ball_count = CASE
                    WHEN COALESCE(ball_count, 0) >= 7 THEN ball_count - 7
                    ELSE ball_count
                END
                WHERE user_id = ?
                """,
                (current_user.user_id,)
            )

        conn.execute(
            "UPDATE works SET is_legend = 1 WHERE id = ?",
            (body.work_id,)
        )

        conn.commit()

        return {"ok": True, "message": "レジェンド化しました。"}
    except:
        conn.rollback()
        raise
    finally:
        conn.close()


# -----------------------------
# POST /items/revive/buy
# -----------------------------
@router.post("/items/revive/buy")
def buy_revive_item(current_user: CurrentUser = Depends(get_current_user)):
    conn = get_db_connection()
    try:
        cost = 100
        points = get_user_points(conn, current_user.user_id)
        if points < cost:
            raise HTTPException(status_code=400, detail="ポイントが不足しています。")

        conn.execute("BEGIN")
        conn.execute(
            "UPDATE users SET points = points - ?, revive_item_count = COALESCE(revive_item_count, 0) + 1 WHERE user_id = ?",
            (cost, current_user.user_id)
        )
        conn.commit()

        return {"ok": True, "message": "復活アイテムを購入しました。"}
    except:
        conn.rollback()
        raise
    finally:
        conn.close()


# -----------------------------
# POST /rewards/ad-xp
# -----------------------------
@router.post("/rewards/ad-xp")
def reward_ad_xp(current_user: CurrentUser = Depends(get_current_user)):
    conn = get_db_connection()
    try:
        ensure_ad_reward_table(conn)

        # 例: 1時間に1回まで
        cooldown_border = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        recent = conn.execute(
            """
            SELECT id
            FROM ad_reward_logs
            WHERE user_id = ?
              AND created_at >= ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (current_user.user_id, cooldown_border)
        ).fetchone()

        if recent:
            raise HTTPException(status_code=429, detail="広告報酬は一定時間ごとに受け取れます。少し時間をおいて再試行してください。")

        reward_exp = 20

        conn.execute("BEGIN")
        conn.execute(
            """
            INSERT INTO ad_reward_logs (user_id, rewarded_exp, created_at)
            VALUES (?, ?, ?)
            """,
            (current_user.user_id, reward_exp, utc_now_iso())
        )
        conn.execute(
            "UPDATE users SET exp = COALESCE(exp, 0) + ? WHERE user_id = ?",
            (reward_exp, current_user.user_id)
        )
        conn.commit()

        return {"ok": True, "message": "広告報酬を受け取りました。", "reward_exp": reward_exp}
    except:
        conn.rollback()
        raise
    finally:
        conn.close()


# -----------------------------
# POST /withdraw/request
# -----------------------------
@router.post("/withdraw/request")
def withdraw_request(
    body: WithdrawRequestBody,
    current_user: CurrentUser = Depends(get_current_user)
):
    conn = get_db_connection()
    try:
        ensure_withdraw_table(conn)

        user_points = get_user_points(conn, current_user.user_id)
        if user_points < body.amount:
            raise HTTPException(status_code=400, detail="ポイント残高が不足しています。")

        # 例: pending は1件まで
        pending = conn.execute(
            """
            SELECT id
            FROM withdraw_requests
            WHERE user_id = ?
              AND status = 'pending'
            ORDER BY id DESC
            LIMIT 1
            """,
            (current_user.user_id,)
        ).fetchone()
        if pending:
            raise HTTPException(status_code=400, detail="未処理の出金申請がすでにあります。")

        # 例: 1日1回制限
        one_day_border = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        recent = conn.execute(
            """
            SELECT id
            FROM withdraw_requests
            WHERE user_id = ?
              AND created_at >= ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (current_user.user_id, one_day_border)
        ).fetchone()
        if recent:
            raise HTTPException(status_code=429, detail="出金申請は一定時間ごとに行えます。")

        conn.execute("BEGIN")

        # 仮押さえとしてポイントを即時減算
        conn.execute(
            "UPDATE users SET points = points - ? WHERE user_id = ?",
            (body.amount, current_user.user_id)
        )
        conn.execute(
            """
            INSERT INTO withdraw_requests (user_id, amount, status, created_at)
            VALUES (?, ?, 'pending', ?)
            """,
            (current_user.user_id, body.amount, utc_now_iso())
        )

        conn.commit()

        return {"ok": True, "message": "出金申請を受け付けました。"}
    except:
        conn.rollback()
        raise
    finally:
        conn.close()
