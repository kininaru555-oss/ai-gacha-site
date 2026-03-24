"""
security.py — 認証、権限管理、パスワードセキュリティ（password完全廃止 / token_version対応版）

方針:
- users.password は一切使わず、password_hash のみを使用
- パスワードハッシュ化に Argon2 (または Bcrypt) を使用
- JWT によるステートレス認証
- token_version により強制ログアウト/全トークン失効を可能にする
- is_official / is_admin フラグに基づいた権限チェック
- get_current_user / get_current_admin_user / get_current_official_user による依存注入
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from database import get_db

logger = logging.getLogger(__name__)

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "").strip()
if not SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY が設定されていません")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))

pwd_context = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


class TokenData(BaseModel):
    user_id: str
    token_type: str
    token_version: int = 0


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        logger.warning("password hash verify failed", exc_info=True)
        return False


def verify_password_and_update_hash(plain_password: str, hashed_password: str) -> tuple[bool, Optional[str]]:
    if not hashed_password:
        return False, None
    try:
        verified, new_hash = pwd_context.verify_and_update(plain_password, hashed_password)
        return bool(verified), new_hash
    except Exception:
        logger.warning("password hash verify/update failed", exc_info=True)
        return False, None


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(
    *,
    user_id: str,
    token_version: int,
    expires_delta: Optional[timedelta] = None,
    extra_claims: Optional[dict[str, Any]] = None,
) -> str:
    if not user_id:
        raise ValueError("user_id は必須です")
    if token_version < 0:
        raise ValueError("token_version は 0 以上である必要があります")

    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))

    payload: dict[str, Any] = {
        "sub": user_id,
        "token_type": "access",
        "token_version": token_version,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _build_credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="認証資格情報が無効です",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _decode_token(token: str) -> TokenData:
    credentials_exception = _build_credentials_exception()
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        user_id = payload.get("sub")
        token_type = payload.get("token_type")
        token_version = payload.get("token_version", 0)

        if not user_id or token_type != "access":
            raise credentials_exception

        if not isinstance(token_version, int):
            raise credentials_exception

        return TokenData(
            user_id=user_id,
            token_type=token_type,
            token_version=token_version,
        )
    except JWTError:
        raise credentials_exception


async def get_current_user(token: str = Depends(oauth2_scheme)):
    token_data = _decode_token(token)
    credentials_exception = _build_credentials_exception()

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    user_id,
                    password_hash,
                    token_version,
                    is_admin,
                    is_official,
                    is_active
                FROM users
                WHERE user_id = %s
                """,
                (token_data.user_id,),
            )
            user = cur.fetchone()

    if user is None:
        raise credentials_exception

    if not bool(user.get("is_active", True)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="このユーザーアカウントは無効です",
        )

    db_token_version = int(user.get("token_version", 0) or 0)
    if token_data.token_version != db_token_version:
        raise credentials_exception

    return user


async def get_current_admin_user(current_user=Depends(get_current_user)):
    if not current_user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="この操作には管理者権限が必要です",
        )
    return current_user


async def get_current_official_user(current_user=Depends(get_current_user)):
    if not current_user.get("is_official"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="この操作には公式クリエイター権限が必要です",
        )
    return current_user


def authenticate_user(user_id: str, plain_password: str):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    user_id,
                    password_hash,
                    token_version,
                    is_admin,
                    is_official,
                    is_active
                FROM users
                WHERE user_id = %s
                """,
                (user_id,),
            )
            user = cur.fetchone()

            if not user:
                return None

            if not bool(user.get("is_active", True)):
                return None

            hashed_password = user.get("password_hash", "")
            verified, new_hash = verify_password_and_update_hash(plain_password, hashed_password)
            if not verified:
                return None

            if new_hash:
                cur.execute(
                    """
                    UPDATE users
                    SET password_hash = %s
                    WHERE user_id = %s
                    """,
                    (new_hash, user_id),
                )
                conn.commit()
                user["password_hash"] = new_hash

            return user


def revoke_user_tokens(user_id: str) -> None:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET token_version = token_version + 1
                WHERE user_id = %s
                """,
                (user_id,),
            )
        conn.commit()
