"""
routers/gacha.py — ガチャ
"""
from fastapi import APIRouter, HTTPException

from database import get_db
from helpers import (
    ensure_user,
    ensure_work,
    weighted_draw,
    get_ownership,
    transfer_ownership,
    create_owned_card_if_missing,
    gain_duplicate_exp,
    update_user_level,
    serialize_work,
)

router = APIRouter(tags=["gacha"])


def apply_paid_gacha_creator_fee(conn, work_id: int):
    """
    有料ガチャ時のみ、著作権者へ閲覧料 10円 を royalty_balance に加算する。
    ポイントには加算しない。
    """
    work = ensure_work(conn, work_id)
    creator_id = work["creator_id"]

    with conn.cursor() as cur:
        cur.execute("""
            UPDATE users
            SET royalty_balance = royalty_balance + 10
            WHERE user_id = %s
        """, (creator_id,))

    return {
        "creator_user_id": creator_id,
        "creator_fee_yen": 10,
        "operator_keep_points": 20,
    }


def process_gacha(conn, user_id: str, draw_type: str) -> dict:
    """
    ガチャ本体は1種類のみ。
    draw_type は支払い方法の違いだけを表す。
    - free: 無料ガチャ回数を使う
    - paid: 30ptを使う
    """
    work = weighted_draw(conn, user_id)

    with conn.cursor() as cur:
        cur.execute("""
            UPDATE works
            SET draw_count = draw_count + 1
            WHERE id = %s
        """, (work["id"],))

    owner = get_ownership(conn, work["id"])
    is_new_owner = owner is None

    if is_new_owner:
        transfer_ownership(conn, work["id"], user_id)
        create_owned_card_if_missing(conn, user_id, work)

        exp_gained = work["exp_reward"]

        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET exp = exp + %s
                WHERE user_id = %s
            """, (exp_gained, user_id))

        update_user_level(conn, user_id)
        owner_user_id = user_id
    else:
        exp_gained = gain_duplicate_exp(conn, user_id, work)
        owner_user_id = owner["owner_id"]

    gacha_fee_info = None

    # 有料ガチャ時のみ、著作権者へ10円の閲覧料
    if draw_type == "paid":
        gacha_fee_info = apply_paid_gacha_creator_fee(conn, work["id"])

    work = ensure_work(conn, work["id"])

    return {
        "message": "ガチャ完了" if draw_type == "free" else "ポイントガチャ完了",
        "result": serialize_work(work),
        "info": {
            "draw_type": draw_type,
            "is_new_owner": is_new_owner,
            "owner_user_id": owner_user_id,
            "exp_gained": exp_gained,
            "creator_fee": gacha_fee_info,
        },
    }


@router.post("/gacha/free/{user_id}")
def gacha_free(user_id: str):
    with get_db() as conn:
        user = ensure_user(conn, user_id)

        if user["free_draw_count"] <= 0:
            raise HTTPException(status_code=400, detail="無料ガチャ回数がありません")

        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET free_draw_count = free_draw_count - 1
                WHERE user_id = %s
            """, (user_id,))

        return process_gacha(conn, user_id, "free")


@router.post("/gacha/paid/{user_id}")
def gacha_paid(user_id: str):
    with get_db() as conn:
        user = ensure_user(conn, user_id)

        if user["points"] < 30:
            raise HTTPException(status_code=400, detail="ポイント不足です（30pt必要）")

        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET points = points - 30
                WHERE user_id = %s
            """, (user_id,))

        return process_gacha(conn, user_id, "paid")
