import os
import json
from datetime import datetime

import stripe
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from database import get_db
from models import CreateCheckoutSessionRequest
from helpers import ensure_user

router = APIRouter(prefix="/payments", tags=["payments"])

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
FRONTEND_SUCCESS_URL = os.getenv("FRONTEND_SUCCESS_URL", "http://localhost:3000/payment/success")
FRONTEND_CANCEL_URL = os.getenv("FRONTEND_CANCEL_URL", "http://localhost:3000/payment/cancel")

PRODUCT_MAP = {
    "300": {"amount_jpy": 120, "points": 300, "name": "300ポイント"},
    "1000": {"amount_jpy": 370, "points": 1000, "name": "1000ポイント"},
    "3000": {"amount_jpy": 980, "points": 3000, "name": "3000ポイント"},
    "5000": {"amount_jpy": 1500, "points": 5000, "name": "5000ポイント"},
}


@router.post("/checkout-session")
def create_checkout_session(payload: CreateCheckoutSessionRequest):
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="STRIPE_SECRET_KEY が未設定です")

    product = PRODUCT_MAP.get(payload.product_type)
    if not product:
        raise HTTPException(status_code=400, detail="無効な商品タイプです")

    with get_db() as conn:
        ensure_user(conn, payload.user_id)

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "jpy",
                        "product_data": {
                            "name": product["name"],
                        },
                        "unit_amount": product["amount_jpy"],
                    },
                    "quantity": 1,
                }
            ],
            success_url=f"{FRONTEND_SUCCESS_URL}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=FRONTEND_CANCEL_URL,
            metadata={
                "user_id": payload.user_id,
                "product_type": payload.product_type,
                "points": str(product["points"]),
                "amount_jpy": str(product["amount_jpy"]),
            },
        )

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO point_purchase_logs(
                        user_id, stripe_session_id, product_type, points, amount_jpy, status
                    ) VALUES(%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (stripe_session_id) DO NOTHING
                """, (
                    payload.user_id,
                    session.id,
                    payload.product_type,
                    product["points"],
                    product["amount_jpy"],
                    "pending"
                ))

        return {"checkout_url": session.url}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Checkout Session 作成失敗: {str(e)}")


@router.post("/webhook")
async def stripe_webhook(request: Request):
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="STRIPE_WEBHOOK_SECRET が未設定です")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_id = event["id"]
    event_type = event["type"]

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM stripe_events WHERE event_id=%s", (event_id,))
            already = cur.fetchone()
            if already:
                return JSONResponse({"message": "already processed"})

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        metadata = session.get("metadata", {})

        user_id = metadata.get("user_id", "")
        product_type = metadata.get("product_type", "")
        points = int(metadata.get("points", "0"))
        amount_jpy = int(metadata.get("amount_jpy", "0"))
        payment_intent = session.get("payment_intent", "")

        if not user_id or points <= 0:
            raise HTTPException(status_code=400, detail="metadata 不正")

        with get_db() as conn:
            ensure_user(conn, user_id)

            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, status FROM point_purchase_logs
                    WHERE stripe_session_id=%s
                    LIMIT 1
                """, (session["id"],))
                log = cur.fetchone()

                if not log:
                    cur.execute("""
                        INSERT INTO point_purchase_logs(
                            user_id, stripe_session_id, stripe_payment_intent_id,
                            product_type, points, amount_jpy, status, completed_at
                        ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (
                        user_id,
                        session["id"],
                        payment_intent,
                        product_type,
                        points,
                        amount_jpy,
                        "completed",
                        datetime.utcnow(),
                    ))
                    cur.execute(
                        "UPDATE users SET points = points + %s WHERE user_id=%s",
                        (points, user_id)
                    )
                elif log["status"] != "completed":
                    cur.execute("""
                        UPDATE point_purchase_logs
                        SET stripe_payment_intent_id=%s,
                            status='completed',
                            completed_at=%s
                        WHERE stripe_session_id=%s
                    """, (
                        payment_intent,
                        datetime.utcnow(),
                        session["id"],
                    ))
                    cur.execute(
                        "UPDATE users SET points = points + %s WHERE user_id=%s",
                        (points, user_id)
                    )

                cur.execute("""
                    INSERT INTO stripe_events(event_id, event_type)
                    VALUES(%s,%s)
                    ON CONFLICT (event_id) DO NOTHING
                """, (event_id, event_type))

    return JSONResponse({"received": True})
