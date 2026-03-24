"""
security.py — 認証、権限管理、パスワードセキュリティ（完全版）

方針:
- パスワードハッシュ化に Argon2 (または Bcrypt) を使用。
- JWT (JSON Web Token) によるステートレス認証。
- is_official / is_admin フラグに基づいた権限チェック。
- get_current_user / get_current_admin_user による依存注入。
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from database import get_db

# ────────────────────────────────────────────────
# 設定 (環境変数から取得推奨)
# ────────────────────────────────────────────────
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your-super-secret-key-for-dev")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7日間有効

# パスワードハッシュ設定 (Argon2推奨、環境によりBcrypt)
pwd_context = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")

# OAuth2 認証スキーム (トークンURLは /login などを想定)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# ────────────────────────────────────────────────
# モデル
# ────────────────────────────────────────────────

class TokenData(BaseModel):
    user_id: Optional[str] = None
    is_admin: bool = False
    is_official: bool = False

# ────────────────────────────────────────────────
# パスワード操作
# ────────────────────────────────────────────────

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """平文パスワードとハッシュを照合。旧仕様の平文(seed)も暫定的に許容する場合は調整可能だが、基本はハッシュのみ。"""
    if not hashed_password:
        return False
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """パスワードをハッシュ化する。"""
    return pwd_context.hash(password)

# ────────────────────────────────────────────────
# JWTトークン操作
# ────────────────────────────────────────────────

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """JWTアクセストークンを生成する。"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# ────────────────────────────────────────────────
# 依存注入用関数 (Depends)
# ────────────────────────────────────────────────

async def get_current_user(token: str = Depends(oauth2_scheme)):
    """
    現在のユーザーを取得する共通関数。
    認証に失敗した場合は 401 Unauthorized を返す。
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="認証資格情報が無効です",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        
        # 権限情報もペイロードから取得（DB参照を減らすため）
        is_admin = bool(payload.get("is_admin", False))
        is_official = bool(payload.get("is_official", False))
        
        token_data = TokenData(user_id=user_id, is_admin=is_admin, is_official=is_official)
    except JWTError:
        raise credentials_exception

    # DBから最新のユーザー情報を取得
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, is_admin, is_official, is_active FROM users WHERE user_id = %s",
                (token_data.user_id,)
            )
            user = cur.fetchone()

    if user is None:
        raise credentials_exception
    if not user.get("is_active", True):
        raise HTTPException(status_code=400, detail="このユーザーアカウントは無効です")
    
    return user

async def get_current_admin_user(current_user=Depends(get_current_user)):
    """管理者(is_admin=1)のみを許可するフィルタ。"""
    if not current_user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="この操作には管理者権限が必要です"
        )
    return current_user

async def get_current_official_user(current_user=Depends(get_current_user)):
    """
    公式ユーザー(is_official=1)のみを許可するフィルタ。
    作品投稿APIでSSRなどを指定できる権限の判定に使用。
    """
    if not current_user.get("is_official"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="この操作には公式クリエイター権限が必要です"
        )
    return current_user
