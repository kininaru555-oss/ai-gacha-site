"""
routers/market.py — オファー・マーケット・出金・レジェンド・レジェンドボール

改善版ポイント:
- 二次流通の会計を points / royalty_balance で分離
- mutate 系エンドポイントを明示的に commit / rollback
- owned_cards の移転を厳格化
- market/listings の重複に強い JOIN へ変更
- レジェンド化は owned_cards の個体に閉じ、works.rarity は変更しない
- 「トラゴンボウル」表記を「レジェンドボール」へ統一
- /withdraw/request に 1000円以上の最低出金制限を実装
- /items/exp/buy を追加し、1日5回までポイントでEXP購入可能

注意:
- 認証基盤が未導入のため、payload の user_id を使う互換APIのままです。
  本番では必ずトークン由来の user_id に置き換えてください。
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_db
from helpers import (
    ensure_user,
    ensure_work,
    get_ownership,
    transfer_ownership,
    count_ball_codes,
    get_owned_card,
    update_user_level,
    grant_view_access,
    level_up_card_if_needed,
)
from models import (
    OfferRequest,
    MarketListRequest,
    MarketBuyRequest,
    WithdrawRequestIn,
    LegendRequest,
    UserOnlyRequest,
)

router = APIRouter(tags=["market"])


class ExpBuyRequest(BaseModel):
    user_id: str
    work_id: int


# ─────────────────────────────────────────────
# 内部ヘルパー
# ─────────────────────────────────────────────
def _today_jst_str() -> str:
    jst = timezone(timedelta(hours=9))
    return datetime.now(jst).date().isoformat()


def ensure_system_user(conn):
    """運営受取先 system ユーザーを存在保証する。"""
    with conn.cursor() as cur:
        cur.execute("SELECT user_id FROM users WHERE user_id = %s", ("system",))
        if not cur.fetchone():
            cur.execute(
                """
                INSERT INTO users(
                    user_id, password, points, exp, level, free_draw_count,
                    revive_items, royalty_balance, daily_duplicate_exp, last_exp_reset
                )
                VALUES(%s, %s, 0, 0, 1, 0, 0, 0, 0, '')
                """,
                ("system", ""),
            )


def ensure_exp_purchase_columns(conn):
    """EXP購入回数制限用カラムを存在保証する。PostgreSQL前提。"""
    with conn.cursor() as cur:
        cur.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_exp_purchase_count INTEGER DEFAULT 0"
        )
        cur.execute(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_exp_purchase_date TEXT DEFAULT ''"
        )


def settle_secondary_sale(
    conn,
    work_id: int,
    buyer_user_id: str,
    seller_user_id: str,
    total_points: int,
    tx_type: str,
) -> Dict[str, int]:
    """
    二次流通の会計処理。

    重要:
    - buyer は points を消費
    - seller は points を受け取る
    - creator は royalty_balance を受け取る
    - platform(system) は points を受け取る
    - 同一金額を points / royalty_balance の両方に二重計上しない
    """
    if total_points <= 0:
        raise HTTPException(status_code=400, detail="取引金額が不正です")

    buyer = ensure_user(conn, buyer_user_id)
    if int(buyer["points"] or 0) < total_points:
        raise HTTPException(status_code=400, detail="ポイント不足です")

    work = ensure_work(conn, work_id)
    creator_id = work["creator_id"]

    ensure_system_user(conn)

    # platform 30% / seller 35% / creator 35% を基本とし、作者本人売りは seller 70% + platform 30%
    platform_fee = int(total_points * 0.30)
    remain = total_points - platform_fee

    if creator_id == seller_user_id:
        seller_share = remain
        creator_share = 0
    else:
        seller_share = remain // 2
        creator_share = remain - seller_share

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE users SET points = points - %s WHERE user_id = %s",
            (total_points, buyer_user_id),
        )
        cur.execute(
            "UPDATE users SET points = points + %s WHERE user_id = %s",
            (platform_fee, "system"),
        )
        cur.execute(
            "UPDATE users SET points = points + %s WHERE user_id = %s",
            (seller_share, seller_user_id),
        )
        if creator_share > 0:
            cur.execute(
                "UPDATE users SET royalty_balance = royalty_balance + %s WHERE user_id = %s",
                (creator_share, creator_id),
            )

        cur.execute(
            """
            INSERT INTO transactions(
                work_id, buyer_user_id, seller_user_id, creator_user_id,
                total_points, platform_fee, seller_share, creator_share, tx_type
            ) VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                work_id,
                buyer_user_id,
                seller_user_id,
                creator_id,
                total_points,
                platform_fee,
                seller_share,
                creator_share,
                tx_type,
            ),
        )

    return {
        "platform_fee": platform_fee,
        "seller_share": seller_share,
        "creator_share": creator_share,
    }


def transfer_owned_card_to_new_owner(conn, work_id: int, old_owner_id: str, new_owner_id: str) -> bool:
    """
    育成済みカードそのものを新所有者へ移す。

    仕様:
    - 1作品 = 1育成個体 が望ましいため、重複がある場合は安全側でエラーにする
    - buyer 側に同じ work_id の owned_card が既にある場合もエラーにする
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM owned_cards
            WHERE work_id = %s AND user_id = %s
            ORDER BY id DESC
            """,
            (work_id, old_owner_id),
        )
        cards = cur.fetchall()

        if not cards:
            raise HTTPException(status_code=404, detail="移転対象の所有カードが存在しません")
        if len(cards) > 1:
            raise HTTPException(status_code=409, detail="所有カードが重複しており、安全に移転できません")

        card = cards[0]

        cur.execute(
            "SELECT id FROM owned_cards WHERE work_id = %s AND user_id = %s LIMIT 1",
            (work_id, new_owner_id),
        )
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="新所有者側に同じ所有カードが既に存在します")

        cur.execute(
            "UPDATE owned_cards SET user_id = %s WHERE id = %s",
            (new_owner_id, card["id"]),
        )

    return True


# ─────────────────────────────────────────────
# オファー
# ─────────────────────────────────────────────
@router.post("/offers")
def send_offer(payload: OfferRequest):
    if payload.offer_points < 30:
        raise HTTPException(status_code=400, detail="オファーは30pt以上で送信してください")

    with get_db() as conn:
        try:
            ensure_user(conn, payload.from_user_id)
            ensure_user(conn, payload.to_user_id)
            ensure_work(conn, payload.work_id)

            owner = get_ownership(conn, payload.work_id)
            if not owner:
                raise HTTPException(status_code=400, detail="未所有作品にはオファーできません")
            if owner["owner_id"] != payload.to_user_id:
                raise HTTPException(status_code=400, detail="宛先が現在の所有者ではありません")
            if payload.from_user_id == payload.to_user_id:
                raise HTTPException(status_code=400, detail="自分の作品にはオファーできません")

            sender = ensure_user(conn, payload.from_user_id)
            if int(sender["points"] or 0) < payload.offer_points:
                raise HTTPException(status_code=400, detail="ポイント不足です")

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO offers(work_id, from_user, to_user, points, status)
                    VALUES(%s, %s, %s, %s, %s)
                    """,
                    (payload.work_id, payload.from_user_id, payload.to_user_id, payload.offer_points, "pending"),
                )

            # オファー送信時点で閲覧権解放
            grant_view_access(conn, payload.from_user_id, payload.work_id, "offer")
            conn.commit()
            return {"message": "オファーを送信しました！"}
        except Exception:
            conn.rollback()
            raise


@router.get("/offers/{user_id}")
def get_offers(user_id: str):
    with get_db() as conn:
        ensure_user(conn, user_id)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT o.*, w.title AS work_title
                FROM offers o
                JOIN works w ON w.id = o.work_id
                WHERE o.to_user = %s
                ORDER BY o.id DESC
                """,
                (user_id,),
            )
            incoming = cur.fetchall()

            cur.execute(
                """
                SELECT o.*, w.title AS work_title
                FROM offers o
                JOIN works w ON w.id = o.work_id
                WHERE o.from_user = %s
                ORDER BY o.id DESC
                """,
                (user_id,),
            )
            outgoing = cur.fetchall()

        return {
            "incoming": [dict(x) for x in incoming],
            "outgoing": [dict(x) for x in outgoing],
        }


@router.post("/offers/{offer_id}/accept")
def accept_offer(offer_id: int):
    with get_db() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM offers WHERE id = %s FOR UPDATE", (offer_id,))
                offer = cur.fetchone()

            if not offer:
                raise HTTPException(status_code=404, detail="オファーが存在しません")
            if offer["status"] != "pending":
                raise HTTPException(status_code=400, detail="このオファーは処理済みです")

            owner = get_ownership(conn, offer["work_id"])
            if not owner or owner["owner_id"] != offer["to_user"]:
                raise HTTPException(status_code=400, detail="現在の所有者が一致しません")

            shares = settle_secondary_sale(
                conn,
                offer["work_id"],
                offer["from_user"],
                offer["to_user"],
                offer["points"],
                "offer",
            )

            transfer_ownership(conn, offer["work_id"], offer["from_user"])
            transfer_owned_card_to_new_owner(
                conn,
                offer["work_id"],
                offer["to_user"],
                offer["from_user"],
            )

            grant_view_access(conn, offer["from_user"], offer["work_id"], "offer")

            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE offers SET status = 'accepted' WHERE id = %s",
                    (offer_id,),
                )
                cur.execute(
                    """
                    UPDATE offers
                    SET status = 'cancelled'
                    WHERE work_id = %s
                      AND status = 'pending'
                      AND id <> %s
                    """,
                    (offer["work_id"], offer_id),
                )

            conn.commit()
            return {
                "message": "オファーを承認しました。育成済みカードを含め所有権を移転しました。",
                "shares": shares,
            }
        except Exception:
            conn.rollback()
            raise


@router.post("/offers/{offer_id}/reject")
def reject_offer(offer_id: int):
    with get_db() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM offers WHERE id = %s FOR UPDATE", (offer_id,))
                offer = cur.fetchone()

            if not offer:
                raise HTTPException(status_code=404, detail="オファーが存在しません")
            if offer["status"] != "pending":
                raise HTTPException(status_code=400, detail="このオファーは処理済みです")

            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE offers SET status = 'rejected' WHERE id = %s",
                    (offer_id,),
                )

            conn.commit()
            return {"message": "オファーを拒否しました"}
        except Exception:
            conn.rollback()
            raise


# ─────────────────────────────────────────────
# マーケット
# ─────────────────────────────────────────────
@router.post("/market/list")
def list_market(payload: MarketListRequest):
    if payload.price_points < 1:
        raise HTTPException(status_code=400, detail="出品価格は1pt以上にしてください")

    with get_db() as conn:
        try:
            ensure_user(conn, payload.user_id)
            ensure_work(conn, payload.work_id)

            owner = get_ownership(conn, payload.work_id)
            if not owner or owner["owner_id"] != payload.user_id:
                raise HTTPException(status_code=400, detail="所有者のみ出品できます")

            card = get_owned_card(conn, payload.user_id, payload.work_id)
            if not card:
                raise HTTPException(status_code=400, detail="出品対象の所有カードが存在しません")

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM market
                    WHERE work_id = %s AND status = 'open'
                    LIMIT 1
                    FOR UPDATE
                    """,
                    (payload.work_id,),
                )
                if cur.fetchone():
                    raise HTTPException(status_code=400, detail="すでに出品中です")

                cur.execute(
                    """
                    INSERT INTO market(work_id, seller, price, status)
                    VALUES(%s, %s, %s, %s)
                    """,
                    (payload.work_id, payload.user_id, payload.price_points, "open"),
                )

            conn.commit()
            return {"message": "マーケットに出品しました！"}
        except Exception:
            conn.rollback()
            raise


@router.get("/market/listings")
def get_market_listings():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    m.id AS listing_id,
                    m.work_id,
                    m.seller AS seller_user_id,
                    m.price AS price_points,
                    w.title,
                    w.creator_name,
                    w.image_url,
                    w.video_url,
                    w.link_url,
                    w.draw_count,
                    oc.id AS card_id,
                    oc.rarity,
                    oc.level,
                    oc.exp,
                    oc.hp,
                    oc.atk,
                    oc.def,
                    oc.spd,
                    oc.luk,
                    oc.lose_streak_count,
                    oc.is_legend,
                    COALESCE(oc.total_exp, 0) AS total_exp,
                    COALESCE(oc.win_count, 0) AS win_count,
                    COALESCE(oc.battle_count, 0) AS battle_count
                FROM market m
                JOIN works w ON w.id = m.work_id
                LEFT JOIN LATERAL (
                    SELECT *
                    FROM owned_cards oc1
                    WHERE oc1.work_id = m.work_id
                      AND oc1.user_id = m.seller
                    ORDER BY oc1.id DESC
                    LIMIT 1
                ) oc ON TRUE
                WHERE m.status = 'open'
                ORDER BY m.id DESC
                """
            )
            rows = cur.fetchall()

        items = []
        for x in rows:
            row = dict(x)
            row["card_power"] = (
                (row.get("hp") or 0)
                + (row.get("atk") or 0)
                + (row.get("def") or 0)
                + (row.get("spd") or 0)
                + (row.get("luk") or 0)
            )
            items.append(row)

        return {"items": items}


@router.post("/market/buy")
def buy_market(payload: MarketBuyRequest):
    with get_db() as conn:
        try:
            ensure_user(conn, payload.buyer_user_id)

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM market WHERE id = %s FOR UPDATE",
                    (payload.listing_id,),
                )
                listing = cur.fetchone()

            if not listing:
                raise HTTPException(status_code=404, detail="出品が存在しません")
            if listing["status"] != "open":
                raise HTTPException(status_code=400, detail="この出品は購入できません")
            if listing["seller"] == payload.buyer_user_id:
                raise HTTPException(status_code=400, detail="自分の出品は購入できません")

            owner = get_ownership(conn, listing["work_id"])
            if not owner or owner["owner_id"] != listing["seller"]:
                raise HTTPException(status_code=400, detail="現在の所有者が一致しません")

            shares = settle_secondary_sale(
                conn,
                listing["work_id"],
                payload.buyer_user_id,
                listing["seller"],
                listing["price"],
                "market",
            )

            transfer_ownership(conn, listing["work_id"], payload.buyer_user_id)
            transfer_owned_card_to_new_owner(
                conn,
                listing["work_id"],
                listing["seller"],
                payload.buyer_user_id,
            )

            grant_view_access(conn, payload.buyer_user_id, listing["work_id"], "market")

            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE market SET status = 'sold' WHERE id = %s",
                    (payload.listing_id,),
                )
                cur.execute(
                    """
                    UPDATE offers
                    SET status = 'cancelled'
                    WHERE work_id = %s
                      AND status = 'pending'
                    """,
                    (listing["work_id"],),
                )

            conn.commit()
            return {
                "message": "購入しました！育成済みカードを含め所有権を移転しました。",
                "shares": shares,
            }
        except Exception:
            conn.rollback()
            raise


# ─────────────────────────────────────────────
# 出金
# ─────────────────────────────────────────────
@router.post("/withdraw/request")
def withdraw_request(payload: WithdrawRequestIn):
    with get_db() as conn:
        try:
            user = ensure_user(conn, payload.user_id)

            if payload.amount < 1000:
                raise HTTPException(status_code=400, detail="出金は1,000円以上から申請できます")
            if int(user["royalty_balance"] or 0) < payload.amount:
                raise HTTPException(status_code=400, detail="出金可能残高が不足しています")

            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET royalty_balance = royalty_balance - %s WHERE user_id = %s",
                    (payload.amount, payload.user_id),
                )
                cur.execute(
                    """
                    INSERT INTO withdraw_requests(user_id, amount, status)
                    VALUES(%s, %s, %s)
                    """,
                    (payload.user_id, payload.amount, "pending"),
                )

            conn.commit()
            return {"message": "出金申請を受け付けました。確認後、順次処理いたします。"}
        except Exception:
            conn.rollback()
            raise


# ─────────────────────────────────────────────
# レジェンド化
# ─────────────────────────────────────────────
@router.post("/legend/activate")
def legend_activate(payload: LegendRequest):
    with get_db() as conn:
        try:
            ensure_user(conn, payload.user_id)
            owner = get_ownership(conn, payload.work_id)

            if not owner or owner["owner_id"] != payload.user_id:
                raise HTTPException(status_code=400, detail="所有作品のみレジェンド化できます")
            if count_ball_codes(conn, payload.user_id) < 7:
                raise HTTPException(status_code=400, detail="レジェンドボール7種が揃っていません")

            card = get_owned_card(conn, payload.user_id, payload.work_id)
            if not card:
                raise HTTPException(status_code=404, detail="所有カードがありません")
            if card["is_legend"]:
                raise HTTPException(status_code=400, detail="すでにレジェンド化済みです")

            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE owned_cards
                    SET is_legend = 1,
                        legend_at = %s,
                        rarity = 'LEGEND',
                        hp = hp + 15,
                        atk = atk + 15,
                        def = def + 15,
                        spd = spd + 10,
                        luk = luk + 10
                    WHERE id = %s
                    """,
                    (datetime.utcnow().isoformat(), card["id"]),
                )

                # レジェンドボールは7個だけ消費する。works マスターは変更しない。
                cur.execute(
                    """
                    SELECT o.work_id
                    FROM ownership o
                    JOIN works w ON w.id = o.work_id
                    WHERE o.owner_id = %s
                      AND w.is_ball = 1
                    ORDER BY w.ball_code ASC, o.work_id ASC
                    LIMIT 7
                    """,
                    (payload.user_id,),
                )
                ball_rows = cur.fetchall()

                if len(ball_rows) < 7:
                    raise HTTPException(status_code=400, detail="レジェンドボール7個の消費に失敗しました")

                for row in ball_rows:
                    cur.execute("DELETE FROM ownership WHERE work_id = %s", (row["work_id"],))
                    # 万一 special item に owned_cards がある環境でも掃除しておく
                    cur.execute(
                        "DELETE FROM owned_cards WHERE work_id = %s AND user_id = %s",
                        (row["work_id"], payload.user_id),
                    )

            conn.commit()
            return {"message": "レジェンド化しました！レジェンドボール7個は消費されました。"}
        except Exception:
            conn.rollback()
            raise


@router.get("/balls/{user_id}")
def get_balls(user_id: str):
    with get_db() as conn:
        ensure_user(conn, user_id)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    w.id AS work_id,
                    w.title,
                    w.ball_code,
                    w.image_url
                FROM ownership o
                JOIN works w ON w.id = o.work_id
                WHERE o.owner_id = %s
                  AND w.is_ball = 1
                ORDER BY w.ball_code ASC
                """,
                (user_id,),
            )
            rows = cur.fetchall()

        return {"count": len(rows), "items": [dict(x) for x in rows]}


@router.get("/legend-balls/{user_id}")
def get_legend_balls(user_id: str):
    """名称統一用エイリアス。内部互換のため balls API を残しつつ追加。"""
    return get_balls(user_id)


# ─────────────────────────────────────────────
# アイテム・報酬
# ─────────────────────────────────────────────
@router.post("/items/revive/buy")
def buy_revive(payload: UserOnlyRequest):
    with get_db() as conn:
        try:
            user = ensure_user(conn, payload.user_id)

            if int(user["points"] or 0) < 100:
                raise HTTPException(status_code=400, detail="ポイント不足です（100pt必要）")

            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE users
                    SET points = points - 100,
                        revive_items = revive_items + 1
                    WHERE user_id = %s
                    """,
                    (payload.user_id,),
                )

            user = ensure_user(conn, payload.user_id)
            conn.commit()
            return {
                "message": "復活アイテムを購入しました！",
                "revive_item_count": user["revive_items"],
                "points": user["points"],
            }
        except Exception:
            conn.rollback()
            raise


@router.post("/items/exp/buy")
def buy_exp(payload: ExpBuyRequest):
    """
    1日5回までポイントでEXPを直接購入する。

    現仕様:
    - 1回 50pt 消費
    - 対象カードへ EXP +20
    - 1日 5回まで
    """
    EXP_BUY_COST = 50
    EXP_GAIN = 20
    DAILY_LIMIT = 5

    with get_db() as conn:
        try:
            ensure_exp_purchase_columns(conn)
            user = ensure_user(conn, payload.user_id)
            owner = get_ownership(conn, payload.work_id)
            if not owner or owner["owner_id"] != payload.user_id:
                raise HTTPException(status_code=400, detail="自分が所有している作品にのみEXP購入できます")

            card = get_owned_card(conn, payload.user_id, payload.work_id)
            if not card:
                raise HTTPException(status_code=404, detail="対象の所有カードが存在しません")

            today = _today_jst_str()
            last_date = (user.get("last_exp_purchase_date") or "")
            current_count = int(user.get("daily_exp_purchase_count") or 0)
            if last_date != today:
                current_count = 0

            if current_count >= DAILY_LIMIT:
                raise HTTPException(status_code=400, detail="EXP購入は1日5回までです")
            if int(user["points"] or 0) < EXP_BUY_COST:
                raise HTTPException(status_code=400, detail=f"ポイント不足です（{EXP_BUY_COST}pt必要）")

            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET points = points - %s WHERE user_id = %s",
                    (EXP_BUY_COST, payload.user_id),
                )
                cur.execute(
                    """
                    UPDATE users
                    SET daily_exp_purchase_count = %s,
                        last_exp_purchase_date = %s
                    WHERE user_id = %s
                    """,
                    (current_count + 1, today, payload.user_id),
                )
                cur.execute(
                    "UPDATE owned_cards SET exp = exp + %s, total_exp = COALESCE(total_exp, 0) + %s WHERE id = %s",
                    (EXP_GAIN, EXP_GAIN, card["id"]),
                )

            level_up_card_if_needed(conn, card["id"])
            update_user_level(conn, payload.user_id)

            updated_user = ensure_user(conn, payload.user_id)
            updated_card = get_owned_card(conn, payload.user_id, payload.work_id)
            conn.commit()
            return {
                "message": f"EXPを購入しました！カードEXP +{EXP_GAIN}",
                "points": updated_user["points"],
                "daily_exp_purchase_count": int(updated_user.get("daily_exp_purchase_count") or 0),
                "card": dict(updated_card) if updated_card else None,
            }
        except Exception:
            conn.rollback()
            raise


@router.post("/rewards/ad-xp")
def reward_ad_xp(payload: UserOnlyRequest):
    with get_db() as conn:
        try:
            ensure_user(conn, payload.user_id)

            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET exp = exp + 20 WHERE user_id = %s",
                    (payload.user_id,),
                )

            update_user_level(conn, payload.user_id)
            user = ensure_user(conn, payload.user_id)
            conn.commit()

            return {
                "message": "広告報酬でEXP +20 を獲得しました！",
                "exp": user["exp"],
                "level": user["level"],
            }
        except Exception:
            conn.rollback()
            raise
