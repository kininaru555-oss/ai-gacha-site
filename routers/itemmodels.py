from typing import Literal, Optional
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# 管理者用
# ─────────────────────────────────────────────

class AdminCreateItemRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    item_type: Literal["legend_ball", "consumable", "material", "ticket"]
    effect_type: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=1000)
    rarity: Literal["N", "R", "SR", "SSR", "LEGEND"] = "N"
    base_value: int = Field(default=0, ge=0)
    growth_value: int = Field(default=0, ge=0)
    max_level: int = Field(default=1, ge=1, le=100)
    icon_image_url: str = Field(default="", max_length=1000)
    is_tradeable: int = Field(default=1, ge=0, le=1)


class AdminUpdateItemRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    effect_type: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = Field(default=None, max_length=1000)
    rarity: Optional[Literal["N", "R", "SR", "SSR", "LEGEND"]] = None
    base_value: Optional[int] = Field(default=None, ge=0)
    growth_value: Optional[int] = Field(default=None, ge=0)
    max_level: Optional[int] = Field(default=None, ge=1, le=100)
    icon_image_url: Optional[str] = Field(default=None, max_length=1000)
    is_tradeable: Optional[int] = Field(default=None, ge=0, le=1)
    is_active: Optional[int] = Field(default=None, ge=0, le=1)


class GiveItemRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=100)
    item_id: int = Field(..., gt=0)
    quantity: int = Field(default=1, ge=1, le=9999)


# ─────────────────────────────────────────────
# 一般ユーザー用
# ─────────────────────────────────────────────

class EquipItemRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=100)
    owned_card_id: int = Field(..., gt=0)
    user_item_id: int = Field(..., gt=0)
    slot_no: int = Field(..., ge=1, le=2)


class UnequipItemRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=100)
    owned_card_id: int = Field(..., gt=0)
    slot_no: int = Field(..., ge=1, le=2)


class ConsumeItemRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=100)
    user_item_id: int = Field(..., gt=0)
    target_owned_card_id: Optional[int] = Field(default=None, gt=0)


class LockItemRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=100)
    user_item_id: int = Field(..., gt=0)
    is_locked: int = Field(..., ge=0, le=1)


# ─────────────────────────────────────────────
# 将来拡張用
# ─────────────────────────────────────────────

class BuyItemRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=100)
    item_id: int = Field(..., gt=0)
    quantity: int = Field(default=1, ge=1, le=999)


class UpgradeItemRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=100)
    user_item_id: int = Field(..., gt=0)


class TransferItemRequest(BaseModel):
    from_user_id: str = Field(..., min_length=1, max_length=100)
    to_user_id: str = Field(..., min_length=1, max_length=100)
    user_item_id: int = Field(..., gt=0)
