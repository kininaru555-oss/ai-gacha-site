"""
models.py — Pydantic リクエストモデル
"""
from typing import Optional
from pydantic import BaseModel


# ─────────────────────────────────────────────
# 認証
# ─────────────────────────────────────────────
class LoginRequest(BaseModel):
    user_id: str
    password: str


# ─────────────────────────────────────────────
# マーケット / オファー
# ─────────────────────────────────────────────
class OfferRequest(BaseModel):
    from_user_id: str
    to_user_id: str
    work_id: int
    offer_points: int


class MarketListRequest(BaseModel):
    user_id: str
    work_id: int
    price_points: int


class MarketBuyRequest(BaseModel):
    buyer_user_id: str
    listing_id: int


# ─────────────────────────────────────────────
# バトル
# ─────────────────────────────────────────────
class BattleEntryRequest(BaseModel):
    user_id: str
    work_id: int


# ─────────────────────────────────────────────
# 汎用
# ─────────────────────────────────────────────
class UserOnlyRequest(BaseModel):
    user_id: str


# ─────────────────────────────────────────────
# 出金
# ─────────────────────────────────────────────
class WithdrawRequestIn(BaseModel):
    user_id: str
    amount: int  # 円単位


# ─────────────────────────────────────────────
# レジェンド
# ─────────────────────────────────────────────
class LegendRequest(BaseModel):
    user_id: str
    work_id: int


# ─────────────────────────────────────────────
# いいね
# ─────────────────────────────────────────────
class LikeRequest(BaseModel):
    user_id: str
    work_id: int


# ─────────────────────────────────────────────
# 管理者作品登録
# ─────────────────────────────────────────────
class AdminCreateWorkRequest(BaseModel):
    creator_user_id: str
    creator_name: str
    title: str

    description: str = ""
    genre: str = ""

    type: str = "image"
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

    rarity: str = "N"

    hp: Optional[int] = None
    atk: Optional[int] = None
    def_: Optional[int] = None   # ← 修正（def回避）
    spd: Optional[int] = None
    luk: Optional[int] = None

    exp_reward: int = 5

    content_hash: str

    is_ball: int = 0
    ball_code: str = ""


# ─────────────────────────────────────────────
# AIステータス生成
# ─────────────────────────────────────────────
class AutoStatRequest(BaseModel):
    image_url: str
    title: str = ""
    description: str = ""
    genre: str = ""


# ─────────────────────────────────────────────
# ポイント購入
# ─────────────────────────────────────────────
class PointPurchaseRequest(BaseModel):
    user_id: str
    type: str  # "300" or "1000"
