"""
routers/auth.py

方針:
- POST /auth/login を提供
- POST /auth/logout-all を提供
- security.py を正本として使用
- users/me や gacha/free の Bearer 認証と整合する返却を行う
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status

from database import get_db
from helpers import serialize_user
from models import LoginRequest
from security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    authenticate_user,
    create_access_token,
    get_current_user,
    revoke_user_tokens,
)

router = APIRouter(tags=["auth"])


@router.get("/auth/health")
def auth_health():
    return {
        "ok": True,
        "message": "auth router ready",
    }


@router.post("/auth/login")
def auth_login(payload: LoginRequest):
    with get_db() as conn:
        user = authenticate_user(conn, payload.user_id, payload.password)

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="ユーザーIDまたはパスワードが正しくありません",
            )

        token = create_access_token(
            user_id=user["user_id"],
            token_version=int(user.get("token_version") or 0),
            expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
            extra_claims={
                "is_admin": bool(user.get("is_admin", False)),
                "is_official": bool(user.get("is_official", False)),
            },
        )

        profile = serialize_user(conn, user["user_id"])

    return {
        **profile,
        "access_token": token,
        "token": token,
        "token_type": "bearer",
    }


@router.post("/auth/logout-all")
def auth_logout_all(current_user=Depends(get_current_user)):
    with get_db() as conn:
        revoke_user_tokens(conn, current_user["user_id"])

    return {
        "ok": True,
        "message": "すべてのログイン状態を無効化しました",
    }
