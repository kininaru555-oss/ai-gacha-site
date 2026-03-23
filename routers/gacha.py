"""
routers/gacha.py — ガチャ（SQLite + トランザクション対応版）
"""
from fastapi import APIRouter, Depends, HTTPException

from auth_utils import CurrentUser, get_current_user
from db import get_db_connection
from helpers import (
    ensure_user,
    ensure_work,
    weighted_draw,
    get_work_owner,
    serialize_work,
    update_user_level,
    record_point_transaction,   # ← point_transactions記録用
)
from models import SuccessResponse  # ← 必要に応じて

router = APIRouter(tags=["gacha"])


def apply_paid_gacha_creator_fee(conn, work_id: int, drawer_user_id: str):
    """
    有料ガチャ時：著作権者に royalty_balance +10
    ポイントには加算せず、履歴のみ記録
    """
    work = ensure_work(conn, work_id)
    creator_id = work.get("creator_user_id") or work.get("creator_id")

    if not creator_id:
        return None

    conn.execute(
        """
        UPDATE users
        SET royalty_balance = COALESCE(royalty_balance, 0) + 10
        WHERE user_id = ?
        """,
        (creator_id,)
    )

    # 履歴（ポイント変動ではないが、参考記録）
    record_point_transaction(
        conn,
        creator_id,
        10,
        "gacha_creator_fee",
        reference_id=work_id,
        description="有料ガチャ閲覧料"
    )

    return {
        "creator_user_id": creator_id,
        "creator_fee_yen": 10,
    }


def process_gacha(conn, current_user: CurrentUser, draw_type: str) -> dict:
    """
    共通ガチャ処理（free / paid）
    """
    work = weighted_draw(conn, current_user.user_id)
    if not work:
        raise HTTPException(status_code=500, detail="ガチャ排出に失敗しました")

    work_id = work["id"]

    # draw_count +1
    conn.execute(
        "UPDATE works SET draw_count = COALESCE(draw_count, 0) + 1 WHERE id = ?",
        (work_id,)
    )

    owner_id = get_work_owner(conn, work_id)
    is_new_owner = owner_id is None

    exp_gained = 0
    owner_user_id = current_user.user_id

    if is_new_owner:
        # 所有権移転
        if table_exists(conn, "work_owners"):
            conn.execute(
                "INSERT OR REPLACE INTO work_owners (work_id, owner_user_id) VALUES (?, ?)",
                (work_id, current_user.user_id)
            )
        else:
            # worksテーブルにowner列がある場合
            owner_col = next((c for c in get_columns(conn, "works") if c in ["owner_user_id", "current_owner_user_id"]), None)
            if owner_col:
                conn.execute(
                    f"UPDATE works SET {owner_col} = ? WHERE id = ?",
                    (current_user.user_id, work_id)
                )

        # 初回獲得EXP
        exp_gained = safe_int(work.get("exp_reward", 5))

        conn.execute(
            "UPDATE users SET exp = COALESCE(exp, 0) + ? WHERE user_id = ?",
            (exp_gained, current_user.user_id)
        )
        update_user_level(conn, current_user.user_id)

    else:
        # 重複獲得 → 日次重複EXP
        # ※ gain_duplicate_exp は旧設計のため、簡易版に置き換え可能
        exp_gained = min(10, max(3, int(safe_int(work.get("exp_reward", 5)) * 0.3)))
        # 日次上限などのチェックは省略（必要なら追加）

        conn.execute(
            "UPDATE users SET exp = COALESCE(exp, 0) + ? WHERE user_id = ?",
            (exp_gained, current_user.user_id)
        )
        update_user_level(conn, current_user.user_id)

        owner_user_id = owner_id

    gacha_fee_info = None
    if draw_type == "paid":
        gacha_fee_info = apply_paid_gacha_creator_fee(conn, work_id, current_user.user_id)

    # 最新のwork情報を取得
    work = ensure_work(conn, work_id)

    return {
        "ok": True,
        "message": "ガチャ完了" if draw_type == "free" else "有料ガチャ完了",
        "result": serialize_work(work),
        "info": {
            "draw_type": draw_type,
            "is_new_owner": is_new_owner,
            "owner_user_id": owner_user_id,
            "exp_gained": exp_gained,
            "creator_fee": gacha_fee_info,
        }
    }


@router.post("/gacha/free", response_model=SuccessResponse)
def gacha_free(current_user: CurrentUser = Depends(get_current_user)):
    conn = get_db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")

        user = ensure_user(conn, current_user.user_id)
        free_count = safe_int(user.get("free_draw_count", 0))

        if free_count <= 0:
            conn.rollback()
            raise HTTPException(status_code=400, detail="無料ガチャ回数がありません")

        conn.execute(
            "UPDATE users SET free_draw_count = free_draw_count - 1 WHERE user_id = ?",
            (current_user.user_id,)
        )

        result = process_gacha(conn, current_user, "free")

        conn.commit()
        return result

    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail="ガチャ処理に失敗しました") from e
    finally:
        conn.close()


@router.post("/gacha/paid", response_model=SuccessResponse)
def gacha_paid(current_user: CurrentUser = Depends(get_current_user)):
    conn = get_db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")

        user = ensure_user(conn, current_user.user_id)
        points = safe_int(user.get("points", 0))

        if points < 30:
            conn.rollback()
            raise HTTPException(status_code=400, detail="ポイントが不足しています（30pt必要）")

        conn.execute(
            "UPDATE users SET points = points - 30 WHERE user_id = ?",
            (current_user.user_id,)
        )

        # ポイント消費履歴
        record_point_transaction(
            conn,
            current_user.user_id,
            -30,
            "gacha_paid",
            description="有料ガチャ（30pt）"
        )

        result = process_gacha(conn, current_user, "paid")

        conn.commit()
        return result

    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()
