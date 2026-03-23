"""
models.py — Pydantic リクエスト/レスポンスモデル
"""
from typing import Optional
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# 認証（ログインは別途扱うことが多いので残すが、me系では不要）
# ─────────────────────────────────────────────
class LoginRequest(BaseModel):
    user_id: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)


# ─────────────────────────────────────────────
# マーケット / オファー
# ─────────────────────────────────────────────
class OfferCreateRequest(BaseModel):
    """オファー作成リクエスト（送信側が指定）"""
    work_id: int = Field(..., gt=0)
    offer_points: int = Field(..., gt=0)


class MarketListRequest(BaseModel):
    """マーケット出品リクエスト"""
    work_id: int = Field(..., gt=0)
    price_points: int = Field(..., gt=0)


class MarketBuyRequest(BaseModel):
    """マーケット即時購入リクエスト（将来的に追加する場合）"""
    listing_id: int = Field(..., gt=0)


# ─────────────────────────────────────────────
# バトル
# ─────────────────────────────────────────────
class BattleEntryRequest(BaseModel):
    """バトル参加リクエスト"""
    work_id: int = Field(..., gt=0)


# ─────────────────────────────────────────────
# 出金
# ─────────────────────────────────────────────
class WithdrawRequest(BaseModel):
    """出金申請リクエスト（ユーザー側）"""
    amount: int = Field(..., ge=1000, description="出金申請額（ポイント単位）")


# ─────────────────────────────────────────────
# レジェンド化
# ─────────────────────────────────────────────
class LegendActivateRequest(BaseModel):
    """レジェンド化リクエスト"""
    work_id: int = Field(..., gt=0)


# ─────────────────────────────────────────────
# いいね（将来的に追加する場合）
# ─────────────────────────────────────────────
class LikeRequest(BaseModel):
    work_id: int = Field(..., gt=0)


# ─────────────────────────────────────────────
# 管理者作品登録
# ─────────────────────────────────────────────
class AdminCreateWorkRequest(BaseModel):
    creator_user_id: str = Field(..., min_length=3)
    creator_name: str = Field(..., min_length=1, max_length=100)
    title: str = Field(..., min_length=1, max_length=200)

    description: str = ""
    genre: str = Field(default="", max_length=50)

    type: str = Field(default="image", pattern="^(image|video|audio)$")
    image_url: str = ""
    video_url: str = ""
    thumbnail_url: str = ""

    link_url: str = ""
    x_url: str = ""
    booth_url: str = ""
    chichipui_url: str = ""
    dlsite_url: str = ""
    fanbox_url: str = ""
    skeb_url: str = ""
    pixiv_url: str = ""

    rarity: str = Field(default="N", pattern="^(N|R|SR|SSR|UR|LR)$")

    hp: Optional[int] = Field(None, ge=0)
    atk: Optional[int] = Field(None, ge=0)
    defense: Optional[int] = Field(None, ge=0)  # def_ → defense に変更
    spd: Optional[int] = Field(None, ge=0)
    luk: Optional[int] = Field(None, ge=0)

    exp_reward: int = Field(default=5, ge=0)

    content_hash: str = Field(..., min_length=32, max_length=128)

    is_ball: int = Field(default=0, ge=0, le=1)
    ball_code: str = ""


# ─────────────────────────────────────────────
# AIステータス自動生成リクエスト
# ─────────────────────────────────────────────
class AutoStatRequest(BaseModel):
    image_url: str = Field(..., min_length=10)
    title: str = ""
    description: str = ""
    genre: str = ""


# ─────────────────────────────────────────────
# ポイント購入（例：ショップ）
# ─────────────────────────────────────────────
class PointPurchaseRequest(BaseModel):
    purchase_type: str = Field(..., pattern="^(300|1000|5000)$", 
                               description="購入パック: '300', '1000', '5000' など")


# ─────────────────────────────────────────────
# 共通レスポンス（オプションで使う）
# ─────────────────────────────────────────────
class SuccessResponse(BaseModel):
    ok: bool = True
    message: str


class ErrorResponse(BaseModel):
    ok: bool = False
    detail: str
