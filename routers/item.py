"""
routers/items.py — アイテム管理API

対象:
- 管理者: アイテム作成 / 更新 / 付与
- 一般: 所持一覧 / 装備 / 解除 / 消費 / ロック
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from database import get_db
from helpers import ensure_user, get_owned_card, level_up_card_if_needed
from itemmodels import (
    AdminCreateItemRequest,
    AdminUpdateItemRequest,
    GiveItemRequest,
    EquipItemRequest,
    UnequipItemRequest,
    ConsumeItemRequest,
    LockItemRequest,
)

router = APIRouter(tags=["items"])


# ─────────────────────────────────────────────
# 内部ヘルパー
# ─────────────────────────────────────────────
def ensure_admin_user(conn, user_id: str):
    user = ensure_user(conn, user_id)
    if int(user.get("is_admin") or 0) != 1:
        raise HTTPException(status_code=403, detail="管理者権限が必要です")
    return user


def ensure_item_master(conn, item_id: int):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM items WHERE id = %s AND is_active = 1", (item_id,))
        item = cur.fetchone()
    if not item:
        raise HTTPException(status_code=404, detail="アイテムが存在しません")
    return item


def ensure_user_item(conn, user_item_id: int):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM user_items WHERE id = %s", (user_item_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="所持アイテムが存在しません")
    return row


def ensure_owned_card_by_id(conn, owned_card_id: int):
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM owned_cards WHERE id = %s", (owned_card_id,))
        card = cur.fetchone()
    if not card:
        raise HTTPException(status_code=404, detail="対象カードが存在しません")
    return card


def log_item_action(
    conn,
    user_id: str,
    item_id: int,
    action_type: str,
    amount: int = 1,
    user_item_id: int | None = None,
    memo: str = "",
):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO item_logs(user_id, item_id, user_item_id, action_type, amount, memo)
            VALUES(%s, %s, %s, %s, %s, %s)
            """,
            (user_id, item_id, user_item_id, action_type, amount, memo),
        )


def get_item_effect_value(user_item: dict, item_master: dict) -> int:
    """
    基本効果値算出:
    base_value + (level - 1) * growth_value
    """
    level = int(user_item.get("level") or 1)
    base_value = int(item_master.get("base_value") or 0)
    growth_value = int(item_master.get("growth_value") or 0)
    return base_value + max(0, level - 1) * growth_value


def decrement_or_delete_user_item(conn, user_item: dict):
    quantity = int(user_item.get("quantity") or 0)
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="所持数が不正です")

    with conn.cursor() as cur:
        if quantity == 1:
            # 装備中なら消費不可
            cur.execute(
                "SELECT id FROM card_item_equips WHERE user_item_id = %s LIMIT 1",
                (user_item["id"],),
            )
            if cur.fetchone():
                raise HTTPException(status_code=400, detail="装備中アイテムは消費できません")

            cur.execute("DELETE FROM user_items WHERE id = %s", (user_item["id"],))
        else:
            cur.execute(
                "UPDATE user_items SET quantity = quantity - 1 WHERE id = %s",
                (user_item["id"],),
            )


def user_owns_card(conn, user_id: str, owned_card_id: int) -> bool:
    card = ensure_owned_card_by_id(conn, owned_card_id)
    return card["user_id"] == user_id


def get_equipped_item_types(conn, owned_card_id: int) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT i.item_type, i.name
            FROM card_item_equips e
            JOIN user_items ui ON ui.id = e.user_item_id
            JOIN items i ON i.id = ui.item_id
            WHERE e.owned_card_id = %s
            """,
            (owned_card_id,),
        )
        rows = cur.fetchall()
    return {f"{r['item_type']}::{r['name']}" for r in rows}


# ─────────────────────────────────────────────
# 管理者API
# ─────────────────────────────────────────────
@router.post("/admin/items")
def create_item(payload: AdminCreateItemRequest, admin_user_id: str):
    with get_db() as conn:
        try:
            ensure_admin_user(conn, admin_user_id)

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO items(
                        name, item_type, effect_type, description, rarity,
                        base_value, growth_value, max_level, icon_image_url,
                        is_tradeable, is_active, created_by
                    ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s)
                    RETURNING id
                    """,
                    (
                        payload.name,
                        payload.item_type,
                        payload.effect_type,
                        payload.description,
                        payload.rarity,
                        payload.base_value,
                        payload.growth_value,
                        payload.max_level,
                        payload.icon_image_url,
                        payload.is_tradeable,
                        admin_user_id,
                    ),
                )
                row = cur.fetchone()

            conn.commit()
            return {"message": "アイテムを作成しました", "item_id": row["id"]}
        except Exception:
            conn.rollback()
            raise


@router.patch("/admin/items/{item_id}")
def update_item(item_id: int, payload: AdminUpdateItemRequest, admin_user_id: str):
    with get_db() as conn:
        try:
            ensure_admin_user(conn, admin_user_id)
            ensure_item_master(conn, item_id)

            updates = []
            values = []

            fields = {
                "name": payload.name,
                "effect_type": payload.effect_type,
                "description": payload.description,
                "rarity": payload.rarity,
                "base_value": payload.base_value,
                "growth_value": payload.growth_value,
                "max_level": payload.max_level,
                "icon_image_url": payload.icon_image_url,
                "is_tradeable": payload.is_tradeable,
                "is_active": payload.is_active,
            }

            for key, value in fields.items():
                if value is not None:
                    updates.append(f"{key} = %s")
                    values.append(value)

            if not updates:
                raise HTTPException(status_code=400, detail="更新項目がありません")

            values.append(item_id)

            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE items SET {', '.join(updates)} WHERE id = %s",
                    tuple(values),
                )

            conn.commit()
            return {"message": "アイテムを更新しました"}
        except Exception:
            conn.rollback()
            raise


@router.post("/admin/items/grant")
def grant_item(payload: GiveItemRequest, admin_user_id: str):
    with get_db() as conn:
        try:
            ensure_admin_user(conn, admin_user_id)
            ensure_user(conn, payload.user_id)
            item = ensure_item_master(conn, payload.item_id)

            with conn.cursor() as cur:
                # すでに同種アイテム所持がある場合は quantity 加算
                cur.execute(
                    """
                    SELECT * FROM user_items
                    WHERE user_id = %s AND item_id = %s AND level = 1 AND exp = 0
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (payload.user_id, payload.item_id),
                )
                existing = cur.fetchone()

                if existing:
                    cur.execute(
                        "UPDATE user_items SET quantity = quantity + %s WHERE id = %s",
                        (payload.quantity, existing["id"]),
                    )
                    user_item_id = existing["id"]
                else:
                    cur.execute(
                        """
                        INSERT INTO user_items(user_id, item_id, quantity, level, exp, total_exp, is_locked)
                        VALUES(%s,%s,%s,1,0,0,0)
                        RETURNING id
                        """,
                        (payload.user_id, payload.item_id, payload.quantity),
                    )
                    user_item_id = cur.fetchone()["id"]

            log_item_action(
                conn,
                payload.user_id,
                payload.item_id,
                "grant",
                amount=payload.quantity,
                user_item_id=user_item_id,
                memo=f"granted_by={admin_user_id}",
            )

            conn.commit()
            return {"message": "アイテムを付与しました"}
        except Exception:
            conn.rollback()
            raise


# ─────────────────────────────────────────────
# 一般ユーザーAPI
# ─────────────────────────────────────────────
@router.get("/items/{user_id}")
def list_user_items(user_id: str):
    with get_db() as conn:
        ensure_user(conn, user_id)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    ui.id AS user_item_id,
                    ui.user_id,
                    ui.item_id,
                    ui.quantity,
                    ui.level,
                    ui.exp,
                    ui.total_exp,
                    ui.is_locked,
                    i.name,
                    i.item_type,
                    i.effect_type,
                    i.description,
                    i.rarity,
                    i.base_value,
                    i.growth_value,
                    i.max_level,
                    i.icon_image_url,
                    i.is_tradeable,
                    EXISTS(
                        SELECT 1 FROM card_item_equips e
                        WHERE e.user_item_id = ui.id
                    ) AS is_equipped
                FROM user_items ui
                JOIN items i ON i.id = ui.item_id
                WHERE ui.user_id = %s
                ORDER BY i.item_type ASC, i.rarity DESC, ui.id DESC
                """,
                (user_id,),
            )
            rows = cur.fetchall()

        return {"items": [dict(x) for x in rows]}


@router.get("/items/detail/{user_item_id}")
def get_user_item_detail(user_item_id: int, user_id: str):
    with get_db() as conn:
        ensure_user(conn, user_id)
        user_item = ensure_user_item(conn, user_item_id)
        if user_item["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="他人のアイテムは参照できません")

        item = ensure_item_master(conn, user_item["item_id"])

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT e.id, e.owned_card_id, e.slot_no, e.equipped_at, oc.work_id, oc.user_id AS card_owner_id
                FROM card_item_equips e
                JOIN owned_cards oc ON oc.id = e.owned_card_id
                WHERE e.user_item_id = %s
                """,
                (user_item_id,),
            )
            equips = cur.fetchall()

        return {
            "user_item": dict(user_item),
            "item_master": dict(item),
            "effect_value": get_item_effect_value(user_item, item),
            "equips": [dict(x) for x in equips],
        }


@router.post("/items/equip")
def equip_item(payload: EquipItemRequest):
    with get_db() as conn:
        try:
            ensure_user(conn, payload.user_id)

            card = ensure_owned_card_by_id(conn, payload.owned_card_id)
            if card["user_id"] != payload.user_id:
                raise HTTPException(status_code=403, detail="他人のカードには装備できません")

            user_item = ensure_user_item(conn, payload.user_item_id)
            if user_item["user_id"] != payload.user_id:
                raise HTTPException(status_code=403, detail="他人のアイテムは装備できません")

            if int(user_item.get("quantity") or 0) < 1:
                raise HTTPException(status_code=400, detail="所持数が不足しています")

            item = ensure_item_master(conn, user_item["item_id"])
            if item["item_type"] != "legend_ball":
                raise HTTPException(status_code=400, detail="装備できるのはレジェンドボールのみです")

            # すでにどこかへ装備済みか
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM card_item_equips WHERE user_item_id = %s LIMIT 1",
                    (payload.user_item_id,),
                )
                already = cur.fetchone()
                if already:
                    raise HTTPException(status_code=409, detail="このアイテムはすでに装備中です")

            # 同一カードの同スロット確認
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM card_item_equips
                    WHERE owned_card_id = %s AND slot_no = %s
                    LIMIT 1
                    """,
                    (payload.owned_card_id, payload.slot_no),
                )
                if cur.fetchone():
                    raise HTTPException(status_code=409, detail="そのスロットにはすでに装備があります")

            # 同種重複装備防止（name 単位）
            equipped_types = get_equipped_item_types(conn, payload.owned_card_id)
            this_key = f"{item['item_type']}::{item['name']}"
            if this_key in equipped_types:
                raise HTTPException(status_code=409, detail="同じアイテムは同一カードに重複装備できません")

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO card_item_equips(owned_card_id, user_item_id, slot_no)
                    VALUES(%s,%s,%s)
                    """,
                    (payload.owned_card_id, payload.user_item_id, payload.slot_no),
                )

            log_item_action(
                conn,
                payload.user_id,
                item["id"],
                "equip",
                amount=1,
                user_item_id=payload.user_item_id,
                memo=f"owned_card_id={payload.owned_card_id},slot_no={payload.slot_no}",
            )

            conn.commit()
            return {"message": "装備しました"}
        except Exception:
            conn.rollback()
            raise


@router.post("/items/unequip")
def unequip_item(payload: UnequipItemRequest):
    with get_db() as conn:
        try:
            ensure_user(conn, payload.user_id)

            card = ensure_owned_card_by_id(conn, payload.owned_card_id)
            if card["user_id"] != payload.user_id:
                raise HTTPException(status_code=403, detail="他人のカードは操作できません")

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT e.*, ui.item_id
                    FROM card_item_equips e
                    JOIN user_items ui ON ui.id = e.user_item_id
                    WHERE e.owned_card_id = %s AND e.slot_no = %s
                    LIMIT 1
                    """,
                    (payload.owned_card_id, payload.slot_no),
                )
                equip = cur.fetchone()

            if not equip:
                raise HTTPException(status_code=404, detail="そのスロットに装備はありません")

            user_item = ensure_user_item(conn, equip["user_item_id"])
            if user_item["user_id"] != payload.user_id:
                raise HTTPException(status_code=403, detail="他人の装備は解除できません")

            with conn.cursor() as cur:
                cur.execute("DELETE FROM card_item_equips WHERE id = %s", (equip["id"],))

            log_item_action(
                conn,
                payload.user_id,
                equip["item_id"],
                "unequip",
                amount=1,
                user_item_id=equip["user_item_id"],
                memo=f"owned_card_id={payload.owned_card_id},slot_no={payload.slot_no}",
            )

            conn.commit()
            return {"message": "装備を解除しました"}
        except Exception:
            conn.rollback()
            raise


@router.post("/items/consume")
def consume_item(payload: ConsumeItemRequest):
    with get_db() as conn:
        try:
            ensure_user(conn, payload.user_id)

            user_item = ensure_user_item(conn, payload.user_item_id)
            if user_item["user_id"] != payload.user_id:
                raise HTTPException(status_code=403, detail="他人のアイテムは使用できません")

            if int(user_item.get("is_locked") or 0) == 1:
                raise HTTPException(status_code=400, detail="ロック中アイテムは使用できません")

            item = ensure_item_master(conn, user_item["item_id"])

            if item["item_type"] not in ("consumable", "material", "ticket"):
                raise HTTPException(status_code=400, detail="このアイテムは消費できません")

            effect_type = item.get("effect_type") or ""
            effect_value = get_item_effect_value(user_item, item)

            # EXP付与
            if effect_type == "exp_gain":
                if not payload.target_owned_card_id:
                    raise HTTPException(status_code=400, detail="対象カードが必要です")

                card = ensure_owned_card_by_id(conn, payload.target_owned_card_id)
                if card["user_id"] != payload.user_id:
                    raise HTTPException(status_code=403, detail="他人のカードには使用できません")

                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE owned_cards
                        SET exp = exp + %s,
                            total_exp = COALESCE(total_exp, 0) + %s
                        WHERE id = %s
                        """,
                        (effect_value, effect_value, payload.target_owned_card_id),
                    )

                level_up_card_if_needed(conn, payload.target_owned_card_id)

            # 進化素材
            elif effect_type == "evolve":
                if not payload.target_owned_card_id:
                    raise HTTPException(status_code=400, detail="進化対象カードが必要です")

                card = ensure_owned_card_by_id(conn, payload.target_owned_card_id)
                if card["user_id"] != payload.user_id:
                    raise HTTPException(status_code=403, detail="他人のカードには使用できません")

                if int(card.get("level") or 0) < 100:
                    raise HTTPException(status_code=400, detail="レベル100のカードにのみ使用できます")

                # ここでは素材消費のみ。進化処理は別API/別ロジックへ委譲してもよい
                pass

            # 復活アイテム
            elif effect_type == "revive":
                # 即時消費ではなく、ユーザー復活アイテム所持数へ加算する運用
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE users
                        SET revive_items = COALESCE(revive_items, 0) + 1
                        WHERE user_id = %s
                        """,
                        (payload.user_id,),
                    )

            # 再抽選券など
            elif effect_type == "reroll":
                # 現時点では消費のみ。使用先画面ロジックで意味付けする
                pass

            else:
                raise HTTPException(status_code=400, detail="未対応の効果タイプです")

            decrement_or_delete_user_item(conn, user_item)

            log_item_action(
                conn,
                payload.user_id,
                item["id"],
                "consume",
                amount=1,
                user_item_id=payload.user_item_id,
                memo=f"effect_type={effect_type},target_owned_card_id={payload.target_owned_card_id}",
            )

            conn.commit()
            return {"message": "アイテムを使用しました"}
        except Exception:
            conn.rollback()
            raise



@router.post("/items/lock")
def lock_item(payload: LockItemRequest):
    with get_db() as conn:
        try:
            ensure_user(conn, payload.user_id)
            user_item = ensure_user_item(conn, payload.user_item_id)

            if user_item["user_id"] != payload.user_id:
                raise HTTPException(status_code=403, detail="他人のアイテムは操作できません")

            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE user_items SET is_locked = %s WHERE id = %s",
                    (payload.is_locked, payload.user_item_id),
                )

            conn.commit()
            return {"message": "ロック状態を更新しました", "is_locked": payload.is_locked}
        except Exception:
            conn.rollback()
            raise


# ─────────────────────────────────────────────
# 補助API
# ─────────────────────────────────────────────
@router.get("/items/legend-balls/{user_id}")
def list_legend_balls(user_id: str):
    with get_db() as conn:
        ensure_user(conn, user_id)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    ui.id AS user_item_id,
                    ui.user_id,
                    ui.quantity,
                    ui.level,
                    ui.exp,
                    ui.total_exp,
                    ui.is_locked,
                    i.id AS item_id,
                    i.name,
                    i.effect_type,
                    i.description,
                    i.rarity,
                    i.base_value,
                    i.growth_value,
                    i.max_level,
                    i.icon_image_url,
                    EXISTS(
                        SELECT 1 FROM card_item_equips e
                        WHERE e.user_item_id = ui.id
                    ) AS is_equipped
                FROM user_items ui
                JOIN items i ON i.id = ui.item_id
                WHERE ui.user_id = %s
                  AND i.item_type = 'legend_ball'
                  AND i.is_active = 1
                ORDER BY ui.level DESC, ui.id DESC
                """,
                (user_id,),
            )
            rows = cur.fetchall()

        return {"items": [dict(x) for x in rows]}
