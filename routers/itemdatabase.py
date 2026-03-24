from database import get_db, _safe_execute

def init_item_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS items(
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    effect_type TEXT DEFAULT '',
                    rarity TEXT DEFAULT 'N',
                    base_value INTEGER DEFAULT 0,
                    growth_value INTEGER DEFAULT 0,
                    max_level INTEGER DEFAULT 1,
                    is_tradeable INTEGER DEFAULT 1,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_items(
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    item_id BIGINT NOT NULL,
                    quantity INTEGER DEFAULT 1,
                    level INTEGER DEFAULT 1,
                    exp INTEGER DEFAULT 0,
                    is_equipped INTEGER DEFAULT 0,
                    slot_no INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS item_logs(
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    item_id BIGINT NOT NULL,
                    action_type TEXT NOT NULL,
                    amount INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            _safe_execute(cur, "CREATE INDEX IF NOT EXISTS idx_user_items_user_id ON user_items(user_id)")
            _safe_execute(cur, "CREATE INDEX IF NOT EXISTS idx_user_items_item_id ON user_items(item_id)")
            _safe_execute(cur, "CREATE INDEX IF NOT EXISTS idx_items_item_type ON items(item_type)")

        conn.commit()
