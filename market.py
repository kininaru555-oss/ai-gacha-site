"""
routers/market.py — オファー・マーケット・出金・レジェンド・ボウル
"""
from datetime import datetime

from fastapi import APIRouter, HTTPException

from database import get_db
from helpers import (
    ensure_user,
    ensure_work,
    get_ownership,
    transfer_ownership,
    distribute_points,
    count_ball_codes,
    get_owned_card,
    update_user_level,
    grant_view_access,
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


# ─────────────────────────────────────────────
# 内部ヘルパー
# ─────────────────────────────────────────────
def transfer_owned_card_to_new_owner(conn, work_id: int, old_owner_id: str, new_owner_id: str):
    """
    育成済みカードそのものを新所有者へ移す。
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT * FROM owned_cards
            WHERE work_id = %s AND user_id = %s
            ORDER BY id DESC
            LIMIT 1
        """, (work_id, old_owner_id))
        card = cur.fetchone()

        if not card:
            raise HTTPException(status_code=404, detail="移転対象の所有カードが存在しません")

        cur.execute("""
            UPDATE owned_cards
            SET user_id = %s
            WHERE id = %s
        """, (new_owner_id, card["id"]))

    return True


# ─────────────────────────────────────────────
# オファー
# ─────────────────────────────────────────────
@router.post("/offers")
def send_offer(payload: OfferRequest):
    if payload.offer_points < 30:
        raise HTTPException(status_code=400, detail="オファーは30pt以上で送信してください")

    with get_db() as conn:
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
        if sender["points"] < payload.offer_points:
            raise HTTPException(status_code=400, detail="ポイント不足です")

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO offers(work_id, from_user, to_user, points, status)
                VALUES(%s, %s, %s, %s, %s)
            """, (payload.work_id, payload.from_user_id, payload.to_user_id, payload.offer_points, "pending"))

        # オファー送信時点で閲覧権解放
        grant_view_access(conn, payload.from_user_id, payload.work_id, "offer")

        return {"message": "オファーを送信しました！"}


@router.get("/offers/{user_id}")
def get_offers(user_id: str):
    with get_db() as conn:
        ensure_user(conn, user_id)

        with conn.cursor() as cur:
            cur.execute("""
                SELECT o.*, w.title AS work_title
                FROM offers o
                JOIN works w ON w.id = o.work_id
                WHERE o.to_user = %s
                ORDER BY o.id DESC
            """, (user_id,))
            incoming = cur.fetchall()

            cur.execute("""
                SELECT o.*, w.title AS work_title
                FROM offers o
                JOIN works w ON w.id = o.work_id
                WHERE o.from_user = %s
                ORDER BY o.id DESC
            """, (user_id,))
            outgoing = cur.fetchall()

        return {
            "incoming": [dict(x) for x in incoming],
            "outgoing": [dict(x) for x in outgoing],
        }


@router.post("/offers/{offer_id}/accept")
def accept_offer(offer_id: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM offers WHERE id = %s", (offer_id,))
            offer = cur.fetchone()

        if not offer:
            raise HTTPException(status_code=404, detail="オファーが存在しません")
        if offer["status"] != "pending":
            raise HTTPException(status_code=400, detail="このオファーは処理済みです")

        owner = get_ownership(conn, offer["work_id"])
        if not owner or owner["owner_id"] != offer["to_user"]:
            raise HTTPException(status_code=400, detail="現在の所有者が一致しません")

        shares = distribute_points(
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

        # 承認後も閲覧権を保証
        grant_view_access(conn, offer["from_user"], offer["work_id"], "offer")

        with conn.cursor() as cur:
            cur.execute("""
                UPDATE offers
                SET status = 'accepted'
                WHERE id = %s
            """, (offer_id,))

            cur.execute("""
                UPDATE offers
                SET status = 'cancelled'
                WHERE work_id = %s
                  AND status = 'pending'
                  AND id <> %s
            """, (offer["work_id"], offer_id))

        return {
            "message": "オファーを承認しました。育成済みカードを含め所有権を移転しました。",
            "shares": shares,
        }


@router.post("/offers/{offer_id}/reject")
def reject_offer(offer_id: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM offers WHERE id = %s", (offer_id,))
            offer = cur.fetchone()

        if not offer:
            raise HTTPException(status_code=404, detail="オファーが存在しません")
        if offer["status"] != "pending":
            raise HTTPException(status_code=400, detail="このオファーは処理済みです")

        with conn.cursor() as cur:
            cur.execute("""
                UPDATE offers
                SET status = 'rejected'
                WHERE id = %s
            """, (offer_id,))

        return {"message": "オファーを拒否しました"}


# ─────────────────────────────────────────────
# マーケット
# ─────────────────────────────────────────────
@router.post("/market/list")
def list_market(payload: MarketListRequest):
    if payload.price_points < 1:
        raise HTTPException(status_code=400, detail="出品価格は1pt以上にしてください")

    with get_db() as conn:
        ensure_user(conn, payload.user_id)
        ensure_work(conn, payload.work_id)

        owner = get_ownership(conn, payload.work_id)
        if not owner or owner["owner_id"] != payload.user_id:
            raise HTTPException(status_code=400, detail="所有者のみ出品できます")

        card = get_owned_card(conn, payload.user_id, payload.work_id)
        if not card:
            raise HTTPException(status_code=400, detail="出品対象の所有カードが存在しません")

        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM market
                WHERE work_id = %s AND status = 'open'
                LIMIT 1
            """, (payload.work_id,))
            if cur.fetchone():
                raise HTTPException(status_code=400, detail="すでに出品中です")

            cur.execute("""
                INSERT INTO market(work_id, seller, price, status)
                VALUES(%s, %s, %s, %s)
            """, (payload.work_id, payload.user_id, payload.price_points, "open"))

        return {"message": "マーケットに出品しました！"}


@router.get("/market/listings")
def get_market_listings():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
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
                LEFT JOIN owned_cards oc
                  ON oc.work_id = m.work_id
                 AND oc.user_id = m.seller
                WHERE m.status = 'open'
                ORDER BY m.id DESC
            """)
            rows = cur.fetchall()

        items = []
        for x in rows:
            row = dict(x)
            row["card_power"] = (
                (row.get("hp") or 0) +
                (row.get("atk") or 0) +
                (row.get("def") or 0) +
                (row.get("spd") or 0) +
                (row.get("luk") or 0)
            )
            items.append(row)

        return {"items": items}


@router.post("/market/buy")
def buy_market(payload: MarketBuyRequest):
    with get_db() as conn:
        ensure_user(conn, payload.buyer_user_id)

        with conn.cursor() as cur:
            cur.execute("""
                SELECT * FROM market
                WHERE id = %s
            """, (payload.listing_id,))
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

        shares = distribute_points(
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

        # 購入時に閲覧権解放
        grant_view_access(conn, payload.buyer_user_id, listing["work_id"], "market")

        with conn.cursor() as cur:
            cur.execute("""
                UPDATE market
                SET status = 'sold'
                WHERE id = %s
            """, (payload.listing_id,))

            cur.execute("""
                UPDATE offers
                SET status = 'cancelled'
                WHERE work_id = %s
                  AND status = 'pending'
            """, (listing["work_id"],))

        return {
            "message": "購入しました！育成済みカードを含め所有権を移転しました。",
            "shares": shares,
        }


# ─────────────────────────────────────────────
# 出金
# ─────────────────────────────────────────────
@router.post("/withdraw/request")
def withdraw_request(payload: WithdrawRequestIn):
    with get_db() as conn:
        user = ensure_user(conn, payload.user_id)

        if payload.amount < 1000:
            raise HTTPException(status_code=400, detail="出金は1,000円以上から申請できます")
        if user["royalty_balance"] < payload.amount:
            raise HTTPException(status_code=400, detail="出金可能残高が不足しています")

        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET royalty_balance = royalty_balance - %s
                WHERE user_id = %s
            """, (payload.amount, payload.user_id))

            cur.execute("""
                INSERT INTO withdraw_requests(user_id, amount, status)
                VALUES(%s, %s, %s)
            """, (payload.user_id, payload.amount, "pending"))

        return {"message": "出金申請を受け付けました。確認後、順次処理いたします。"}


# ─────────────────────────────────────────────
# レジェンド化
# ─────────────────────────────────────────────
@router.post("/legend/activate")
def legend_activate(payload: LegendRequest):
    with get_db() as conn:
        ensure_user(conn, payload.user_id)
        owner = get_ownership(conn, payload.work_id)

        if not owner or owner["owner_id"] != payload.user_id:
            raise HTTPException(status_code=400, detail="所有作品のみレジェンド化できます")
        if count_ball_codes(conn, payload.user_id) < 7:
            raise HTTPException(status_code=400, detail="トラゴンボウル7種が揃っていません")

        card = get_owned_card(conn, payload.user_id, payload.work_id)
        if not card:
            raise HTTPException(status_code=404, detail="所有カードがありません")
        if card["is_legend"]:
            raise HTTPException(status_code=400, detail="すでにレジェンド化済みです")

        with conn.cursor() as cur:
            cur.execute("""
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
            """, (datetime.utcnow().isoformat(), card["id"]))

            cur.execute("""
                UPDATE works
                SET rarity = 'LEGEND'
                WHERE id = %s
            """, (payload.work_id,))

            cur.execute("""
                SELECT o.work_id
                FROM ownership o
                JOIN works w ON w.id = o.work_id
                WHERE o.owner_id = %s
                  AND w.is_ball = 1
            """, (payload.user_id,))
            ball_rows = cur.fetchall()

            for row in ball_rows:
                cur.execute("""
                    DELETE FROM ownership
                    WHERE work_id = %s
                """, (row["work_id"],))

        return {"message": "レジェンド化しました！トラゴンボウル7個は消費されました。"}


@router.get("/balls/{user_id}")
def get_balls(user_id: str):
    with get_db() as conn:
        ensure_user(conn, user_id)

        with conn.cursor() as cur:
            cur.execute("""
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
            """, (user_id,))
            rows = cur.fetchall()

        return {"count": len(rows), "items": [dict(x) for x in rows]}


# ─────────────────────────────────────────────
# アイテム・報酬
# ─────────────────────────────────────────────
@router.post("/items/revive/buy")
def buy_revive(payload: UserOnlyRequest):
    with get_db() as conn:
        user = ensure_user(conn, payload.user_id)

        if user["points"] < 100:
            raise HTTPException(status_code=400, detail="ポイント不足です（100pt必要）")

        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET points = points - 100,
                    revive_items = revive_items + 1
                WHERE user_id = %s
            """, (payload.user_id,))

        user = ensure_user(conn, payload.user_id)
        return {
            "message": "復活アイテムを購入しました！",
            "revive_item_count": user["revive_items"],
            "points": user["points"],
        }


@router.post("/rewards/ad-xp")
def reward_ad_xp(payload: UserOnlyRequest):
    with get_db() as conn:
        ensure_user(conn, payload.user_id)

        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users
                SET exp = exp + 20
                WHERE user_id = %s
            """, (payload.user_id,))

        update_user_level(conn, payload.user_id)
        user = ensure_user(conn, payload.user_id)

        return {
            "message": "広告報酬でEXP +20 を獲得しました！",
            "exp": user["exp"],
            "level": user["level"],
                }
