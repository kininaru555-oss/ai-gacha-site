from __future__ import annotations

from typing import Optional

from fastapi import Header, HTTPException
from pydantic import BaseModel


class CurrentUser(BaseModel):
    user_id: str


def decode_bearer_token(token: str) -> Optional[CurrentUser]:
    """
    本番では JWT 検証に置き換える。
    ここではサンプルとして:
      Bearer demo:<user_id>
    形式を許可する。
    """
    if not token:
      return None

    if token.startswith("demo:"):
        user_id = token.split(":", 1)[1].strip()
        if user_id:
            return CurrentUser(user_id=user_id)

    return None


async def get_current_user(authorization: str = Header(default="")) -> CurrentUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="認証が必要です。")

    token = authorization.split(" ", 1)[1].strip()
    user = decode_bearer_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="認証トークンが無効です。")

    return user
