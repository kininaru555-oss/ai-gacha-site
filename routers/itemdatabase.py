from database import get_db, _safe_execute


def init_item_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS items(
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    effect_type TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    rarity TEXT DEFAULT 'N',
                    base_value INTEGER DEFAULT 0,
                    growth_value INTEGER DEFAULT 0,
                    max_level INTEGER DEFAULT 1,
                    icon_image_url TEXT DEFAULT '',
                    is_tradeable INTEGER DEFAULT 1,
                    is_active INTEGER DEFAULT 1,
                    created_by TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_items(
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    item_id BIGINT NOT NULL,
                    quantity INTEGER DEFAULT 1,
                    level INTEGER DEFAULT 1,
                    exp INTEGER DEFAULT 0,
                    total_exp INTEGER DEFAULT 0,
                    is_locked INTEGER DEFAULT 0,
                    is_equipped INTEGER DEFAULT 0,
                    slot_no INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS item_logs(
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    item_id BIGINT NOT NULL,
                    user_item_id BIGINT,
                    action_type TEXT NOT NULL,
                    amount INTEGER DEFAULT 1,
                    memo TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS card_item_equips(
                    id BIGSERIAL PRIMARY KEY,
                    owned_card_id BIGINT NOT NULL,
                    user_item_id BIGINT NOT NULL,
                    slot_no INTEGER NOT NULL DEFAULT 1,
                    equipped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # ─────────────────────────────────────────────
            # 後方互換ALTER
            # ─────────────────────────────────────────────
            _safe_execute(cur, "ALTER TABLE items ADD COLUMN IF NOT EXISTS description TEXT DEFAULT ''")
            _safe_execute(cur, "ALTER TABLE items ADD COLUMN IF NOT EXISTS icon_image_url TEXT DEFAULT ''")
            _safe_execute(cur, "ALTER TABLE items ADD COLUMN IF NOT EXISTS created_by TEXT DEFAULT ''")

            _safe_execute(cur, "ALTER TABLE user_items ADD COLUMN IF NOT EXISTS total_exp INTEGER DEFAULT 0")
            _safe_execute(cur, "ALTER TABLE user_items ADD COLUMN IF NOT EXISTS is_locked INTEGER DEFAULT 0")

            _safe_execute(cur, "ALTER TABLE item_logs ADD COLUMN IF NOT EXISTS user_item_id BIGINT")
            _safe_execute(cur, "ALTER TABLE item_logs ADD COLUMN IF NOT EXISTS memo TEXT DEFAULT ''")

            # ─────────────────────────────────────────────
            # インデックス
            # ─────────────────────────────────────────────
            _safe_execute(cur, "CREATE INDEX IF NOT EXISTS idx_user_items_user_id ON user_items(user_id)")
            _safe_execute(cur, "CREATE INDEX IF NOT EXISTS idx_user_items_item_id ON user_items(item_id)")
            _safe_execute(cur, "CREATE INDEX IF NOT EXISTS idx_items_item_type ON items(item_type)")
            _safe_execute(cur, "CREATE INDEX IF NOT EXISTS idx_item_logs_user_id ON item_logs(user_id)")
            _safe_execute(cur, "CREATE INDEX IF NOT EXISTS idx_item_logs_item_id ON item_logs(item_id)")
            _safe_execute(cur, "CREATE INDEX IF NOT EXISTS idx_item_logs_user_item_id ON item_logs(user_item_id)")
            _safe_execute(cur, "CREATE INDEX IF NOT EXISTS idx_card_item_equips_owned_card_id ON card_item_equips(owned_card_id)")
            _safe_execute(cur, "CREATE INDEX IF NOT EXISTS idx_card_item_equips_user_item_id ON card_item_equips(user_item_id)")
            _safe_execute(cur, "CREATE UNIQUE INDEX IF NOT EXISTS idx_card_item_equips_user_item_unique ON card_item_equips(user_item_id)")
            _safe_execute(cur, "CREATE UNIQUE INDEX IF NOT EXISTS idx_card_item_equips_slot_unique ON card_item_equips(owned_card_id, slot_no)")

        conn.commit()
