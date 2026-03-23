"""
models.py — Pydantic リクエスト/レスポンスモデル（完全修正・強化版）
Pydantic v2 対応 / バリデーション強化 / 命名統一
"""
from typing import Optional
from pydantic import BaseModel, Field, HttpUrl, SecretStr, field_validator


class LoginRequest(BaseModel):
    """ログインリクエスト"""
    user_id: str = Field(..., min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$",
                         description="ユーザーID（英数字・アンダースコア・ハイフン）")
    password: SecretStr = Field(..., min_length=6, max_length=128,
                                description="パスワード（平文で送信。本番ではHTTPS必須）")

    model_config = {"str_strip_whitespace": True}


# ─────────────────────────────────────────────
# マーケット / オファー
# ─────────────────────────────────────────────
class OfferRequest(BaseModel):
    """オファー送信リクエスト"""
    from_user_id: str = Field(..., min_length=3, max_length=32)
    to_user_id: str = Field(..., min_length=3, max_length=32)
    work_id: int = Field(..., ge=1)
    offer_points: int = Field(..., ge=30, le=999999,
                              description="オファー額（pt）。最低30pt")

    @field_validator("from_user_id", "to_user_id")
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        if v == "admin":
            raise ValueError("adminユーザーへの直接オファーは禁止されています")
        return v


class MarketListRequest(BaseModel):
    """マーケット出品リクエスト"""
    user_id: str = Field(..., min_length=3, max_length=32)
    work_id: int = Field(..., ge=1)
    price_points: int = Field(..., ge=1, le=9999999,
                              description="出品価格（pt）。最低1pt")


class MarketBuyRequest(BaseModel):
    """マーケット購入リクエスト"""
    buyer_user_id: str = Field(..., min_length=3, max_length=32)
    listing_id: int = Field(..., ge=1)


# ─────────────────────────────────────────────
# バトル
# ─────────────────────────────────────────────
class BattleEntryRequest(BaseModel):
    """バトル参加リクエスト"""
    user_id: str = Field(..., min_length=3, max_length=32)
    work_id: int = Field(..., ge=1)


# ─────────────────────────────────────────────
# 出金
# ─────────────────────────────────────────────
class WithdrawRequestIn(BaseModel):
    """出金申請リクエスト"""
    user_id: str = Field(..., min_length=3, max_length=32)
    amount: int = Field(..., ge=1000, le=10000000,
                        description="出金額（円単位）。最低1,000円")


# ─────────────────────────────────────────────
# レジェンド化
# ─────────────────────────────────────────────
class LegendRequest(BaseModel):
    """レジェンド化リクエスト"""
    user_id: str = Field(..., min_length=3, max_length=32)
    work_id: int = Field(..., ge=1)


# ─────────────────────────────────────────────
# いいね
# ─────────────────────────────────────────────
class LikeRequest(BaseModel):
    """いいねリクエスト"""
    user_id: str = Field(..., min_length=3, max_length=32)
    work_id: int = Field(..., ge=1)


# ─────────────────────────────────────────────
# 管理者作品登録（強化版）
# ─────────────────────────────────────────────
class AdminCreateWorkRequest(BaseModel):
    """管理者用作品登録リクエスト（投稿フォーム対応）"""
    creator_user_id: str = Field(..., min_length=3, max_length=32)
    creator_name: str = Field(..., min_length=1, max_length=50)
    title: str = Field(..., min_length=1, max_length=100)

    description: str = Field(default="", max_length=2000)
    genre: str = Field(default="", max_length=50)

    type: str = Field(default="image", pattern="^(image|video)$")
    image_url: Optional[HttpUrl] = Field(default=None)
    video_url: Optional[HttpUrl] = Field(default=None)
    thumbnail_url: Optional[HttpUrl] = Field(default=None)

    link_url: Optional[HttpUrl] = Field(default=None)
    x_url: Optional[HttpUrl] = Field(default=None)
    booth_url: Optional[HttpUrl] = Field(default=None)
    chichipui_url: Optional[HttpUrl] = Field(default=None)
    dlsite_url: Optional[HttpUrl] = Field(default=None)
    fanbox_url: Optional[HttpUrl] = Field(default=None)
    skeb_url: Optional[HttpUrl] = Field(default=None)
    pixiv_url: Optional[HttpUrl] = Field(default=None)

    rarity: str = Field(default="N", pattern="^(N|R|SR|SSR|LEGEND)$")

    hp: Optional[int] = Field(default=None, ge=1, le=999)
    atk: Optional[int] = Field(default=None, ge=1, le=999)
    defense: Optional[int] = Field(default=None, ge=1, le=999, alias="def")  # ← フロントのdefに対応
    spd: Optional[int] = Field(default=None, ge=1, le=999)
    luk: Optional[int] = Field(default=None, ge=1, le=999)

    exp_reward: int = Field(default=5, ge=1, le=100)

    content_hash: str = Field(..., min_length=8, max_length=128)

    is_ball: int = Field(default=0, ge=0, le=1)
    ball_code: str = Field(default="", max_length=32)

    model_config = {
        "populate_by_name": True,          # alias対応
        "str_strip_whitespace": True,
        "json_schema_extra": {
            "example": {
                "creator_user_id": "creator1",
                "title": "月下の魔導姫",
                "type": "image",
                "image_url": "https://...jpg",
                "rarity": "N",
                "content_hash": "sha256-of-content"
            }
        }
    }

    @field_validator("image_url", "video_url", mode="before")
    @classmethod
    def validate_media_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        return v


# ─────────────────────────────────────────────
# AIステータス生成
# ─────────────────────────────────────────────
class AutoStatRequest(BaseModel):
    """AI自動ステータス生成リクエスト"""
    image_url: HttpUrl = Field(..., description="Cloudinaryなどの画像URL")
    title: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=1000)
    genre: str = Field(default="", max_length=50)


# ─────────────────────────────────────────────
# ポイント購入（仮）
# ─────────────────────────────────────────────
class PointPurchaseRequest(BaseModel):
    """ポイント購入リクエスト（仮）"""
    user_id: str = Field(..., min_length=3, max_length=32)
    type: str = Field(..., pattern="^(300|1000|5000)$",
                      description="購入パック: 300pt / 1000pt / 5000pt")
