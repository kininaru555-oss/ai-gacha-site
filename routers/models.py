"""
models_fixed.py — Pydantic request models (improved)

方針:
- 将来の認証導入を見据えつつ、既存 payload 互換をできるだけ維持
- 数値バリデーションを追加
- 旧名称(type / is_ball / ball_code)を残しつつ、新名称(media_type / item_type / legend_code)を追加
- def_ / defense の両対応を吸収
- PointPurchaseRequest.type は Literal で制限
"""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel

class CreateCheckoutSessionRequest(BaseModel):
    product_type: Literal["300", "1000", "3000", "5000"]
    # user_id は JWT認証（get_current_user）から取得するため不要

from pydantic import BaseModel, Field, model_validator


# ─────────────────────────────────────────────
# 認証
# ─────────────────────────────────────────────
class LoginRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


# ─────────────────────────────────────────────
# マーケット / オファー
# ─────────────────────────────────────────────
class OfferRequest(BaseModel):
    to_user_id: str = Field(..., min_length=1, max_length=64)
    work_id: int = Field(..., gt=0)
    offer_points: int = Field(..., ge=30, le=10_000_000)
    # from_user_id は JWT認証（get_current_user）から取得するため不要


class MarketListRequest(BaseModel):
    work_id: int = Field(..., gt=0)
    price_points: int = Field(..., ge=1, le=10_000_000)
    # user_id は JWT認証（get_current_user）から取得するため不要


class MarketBuyRequest(BaseModel):
    listing_id: int = Field(..., gt=0)
    # buyer_user_id は JWT認証（get_current_user）から取得するため不要


# ─────────────────────────────────────────────
# バトル
# ─────────────────────────────────────────────
class BattleEntryRequest(BaseModel):
    work_id: int = Field(..., gt=0)
    # user_id は JWT認証（get_current_user）から取得するため不要


# ─────────────────────────────────────────────
# 汎用
# ─────────────────────────────────────────────
class UserOnlyRequest(BaseModel):
    pass  # user_id は JWT認証（get_current_user）から取得するため不要


# ─────────────────────────────────────────────
# 出金
# ─────────────────────────────────────────────
class WithdrawRequestIn(BaseModel):
    amount: int = Field(..., ge=1000, le=10_000_000, description="円単位")
    # user_id は JWT認証（get_current_user）から取得するため不要


# ─────────────────────────────────────────────
# レジェンド化
# ─────────────────────────────────────────────
class LegendRequest(BaseModel):
    work_id: int = Field(..., gt=0)
    # user_id は JWT認証（get_current_user）から取得するため不要


# ─────────────────────────────────────────────
# いいね
# ─────────────────────────────────────────────
class LikeRequest(BaseModel):
    work_id: int = Field(..., gt=0)
    # user_id は JWT認証（get_current_user）から取得するため不要


# ─────────────────────────────────────────────
# 管理者作品登録
# ─────────────────────────────────────────────
class AdminCreateWorkRequest(BaseModel):
    creator_user_id: str = Field(..., min_length=1, max_length=64)
    creator_name: str = Field(..., min_length=1, max_length=128)
    title: str = Field(..., min_length=1, max_length=255)

    description: str = Field(default="", max_length=5000)
    genre: str = Field(default="", max_length=255)

    # 旧互換: type
    type: Optional[str] = None
    # 新推奨: media_type / item_type
    media_type: str = Field(default="image")
    item_type: str = Field(default="work")

    image_url: str = Field(default="", max_length=2000)
    video_url: str = Field(default="", max_length=2000)
    thumbnail_url: str = Field(default="", max_length=2000)

    link_url: str = Field(default="", max_length=2000)
    x_url: str = Field(default="", max_length=2000)
    booth_url: str = Field(default="", max_length=2000)
    chichipui_url: str = Field(default="", max_length=2000)
    dlsite_url: str = Field(default="", max_length=2000)
    fanbox_url: str = Field(default="", max_length=2000)
    skeb_url: str = Field(default="", max_length=2000)
    pixiv_url: str = Field(default="", max_length=2000)

    rarity: str = Field(default="N", min_length=1, max_length=16)

    hp: Optional[int] = Field(default=None, ge=5, le=999)
    atk: Optional[int] = Field(default=None, ge=5, le=999)
    def_: Optional[int] = Field(default=None, ge=5, le=999)
    defense: Optional[int] = Field(default=None, ge=5, le=999)
    spd: Optional[int] = Field(default=None, ge=5, le=999)
    luk: Optional[int] = Field(default=None, ge=5, le=999)

    exp_reward: int = Field(default=5, ge=0, le=1000)

    content_hash: str = Field(..., min_length=1, max_length=255)

    # 旧互換
    is_ball: int = Field(default=0, ge=0, le=1)
    ball_code: str = Field(default="", max_length=64)
    # 新推奨
    legend_code: str = Field(default="", max_length=64)

    @model_validator(mode="after")
    def normalize_and_validate(self):
        # 旧 type 互換
        if self.type and not self.media_type:
            self.media_type = self.type
        if self.type and self.media_type == "image":
            self.media_type = self.type

        self.media_type = (self.media_type or "image").strip().lower()
        self.item_type = (self.item_type or "work").strip().lower()
        self.rarity = (self.rarity or "N").strip().upper()

        if self.media_type not in {"image", "video"}:
            raise ValueError("media_type は 'image' または 'video' を指定してください")

        if self.item_type not in {"work", "legend_ball", "material", "reward"}:
            raise ValueError("item_type が不正です")

        # 旧 def_ / defense 吸収
        if self.defense is None and self.def_ is not None:
            self.defense = self.def_
        if self.def_ is None and self.defense is not None:
            self.def_ = self.defense

        # 旧 is_ball / ball_code 互換を新仕様へ寄せる
        if self.is_ball == 1 and self.item_type == "work":
            self.item_type = "legend_ball"
        if self.legend_code and not self.ball_code:
            self.ball_code = self.legend_code
        if self.ball_code and not self.legend_code:
            self.legend_code = self.ball_code

        # メディア必須条件
        if self.media_type == "image" and not self.image_url:
            raise ValueError("image作品には image_url が必要です")
        if self.media_type == "video" and not self.video_url:
            raise ValueError("video作品には video_url が必要です")

        return self


# ─────────────────────────────────────────────
# AIステータス生成
# ─────────────────────────────────────────────
class AutoStatRequest(BaseModel):
    image_url: str = Field(..., min_length=1, max_length=2000)
    title: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=5000)
    genre: str = Field(default="", max_length=255)


# ─────────────────────────────────────────────
# ポイント購入
# ─────────────────────────────────────────────
class PointPurchaseRequest(BaseModel):
    type: Literal["300", "1000","3000","10000"]
    # user_id は JWT認証（get_current_user）から取得するため不要


# ─────────────────────────────────────────────
# 経験値購入（新仕様）
# ─────────────────────────────────────────────
class ExpBuyRequest(BaseModel):
    work_id: int = Field(..., gt=0)
    # 将来拡張用。現状は basic のみ想定。
    pack_type: Literal["basic"] = "basic"
    # user_id は JWT認証（get_current_user）から取得するため不要
