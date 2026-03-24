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
    if not STRIPE_WEBHOOK
