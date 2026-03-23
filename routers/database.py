"""
database.py — DB接続・テーブル初期化
"""
import os
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL が設定されていません")

# Render/managed Postgres は SSL 必須のことが多いので prefer を既定に
if "sslmode=" not in DATABASE_URL:
    sep = "&" if "?" in DATABASE_URL else "?"
    DATABASE_URL = f"{DATABASE_URL}{sep}sslmode=prefer"


def get_db():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)

cur.execute("ALTER TABLE owned_cards ADD COLUMN IF NOT EXISTS total_exp BIGINT DEFAULT 0")
            cur.execute("ALTER TABLE owned_cards ADD COLUMN IF NOT EXISTS win_count INTEGER DEFAULT 0")
            cur.execute("ALTER TABLE owned_cards ADD COLUMN IF NOT EXISTS battle_count INTEGER DEFAULT 0")

def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users(
                user_id              TEXT PRIMARY KEY,
                password             TEXT    DEFAULT '',
                points               INTEGER DEFAULT 0,
                exp                  INTEGER DEFAULT 0,
                level                INTEGER DEFAULT 1,
                free_draw_count      INTEGER DEFAULT 1,
                revive_items         INTEGER DEFAULT 0,
                royalty_balance      INTEGER DEFAULT 0,
                daily_duplicate_exp  INTEGER DEFAULT 0,
                last_exp_reset       TEXT    DEFAULT ''
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS works(
                id             BIGSERIAL PRIMARY KEY,
                title          TEXT    NOT NULL,
                creator_id     TEXT    NOT NULL,
                creator_name   TEXT    DEFAULT '',
                description    TEXT    DEFAULT '',
                genre          TEXT    DEFAULT '',
                type           TEXT    DEFAULT 'image',
                image_url      TEXT    DEFAULT '',
                video_url      TEXT    DEFAULT '',
                thumbnail_url  TEXT    DEFAULT '',
                link_url       TEXT    DEFAULT '',
                x_url          TEXT    DEFAULT '',
                booth_url      TEXT    DEFAULT '',
                chichipui_url  TEXT    DEFAULT '',
                dlsite_url     TEXT    DEFAULT '',
                fanbox_url     TEXT    DEFAULT '',
                skeb_url       TEXT    DEFAULT '',
                pixiv_url      TEXT    DEFAULT '',
                rarity         TEXT    DEFAULT 'N',
                hp             INTEGER DEFAULT 10,
                atk            INTEGER DEFAULT 10,
                def            INTEGER DEFAULT 10,
                spd            INTEGER DEFAULT 10,
                luk            INTEGER DEFAULT 10,
                exp_reward     INTEGER DEFAULT 5,
                draw_count     INTEGER DEFAULT 0,
                like_count     INTEGER DEFAULT 0,
                is_active      INTEGER DEFAULT 1,
                is_ball        INTEGER DEFAULT 0,
                ball_code      TEXT    DEFAULT '',
                content_hash   TEXT    DEFAULT ''
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS ownership(
                work_id     BIGINT PRIMARY KEY,
                owner_id    TEXT   NOT NULL,
                acquired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS owned_cards(
                id                BIGSERIAL PRIMARY KEY,
                user_id           TEXT    NOT NULL,
                work_id           BIGINT  NOT NULL,
                rarity            TEXT    DEFAULT 'N',
                level             INTEGER DEFAULT 1,
                exp               INTEGER DEFAULT 0,
                hp                INTEGER DEFAULT 10,
                atk               INTEGER DEFAULT 10,
                def               INTEGER DEFAULT 10,
                spd               INTEGER DEFAULT 10,
                luk               INTEGER DEFAULT 10,
                lose_streak_count INTEGER DEFAULT 0,
                is_legend         INTEGER DEFAULT 0,
                legend_at         TEXT    DEFAULT ''
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS offers(
                id         BIGSERIAL PRIMARY KEY,
                work_id    BIGINT NOT NULL,
                from_user  TEXT   NOT NULL,
                to_user    TEXT   NOT NULL,
                points     INTEGER NOT NULL,
                status     TEXT    DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS market(
                id         BIGSERIAL PRIMARY KEY,
                work_id    BIGINT  NOT NULL,
                seller     TEXT    NOT NULL,
                price      INTEGER NOT NULL,
                status     TEXT    DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS battle_queue(
                id         BIGSERIAL PRIMARY KEY,
                user_id    TEXT   NOT NULL,
                work_id    BIGINT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS battle_logs(
                id               BIGSERIAL PRIMARY KEY,
                user_id          TEXT    NOT NULL,
                opponent_user_id TEXT    DEFAULT '',
                result           TEXT    DEFAULT '',
                log_text         TEXT    DEFAULT '',
                reward_exp       INTEGER DEFAULT 0,
                created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS transactions(
                id              BIGSERIAL PRIMARY KEY,
                work_id         BIGINT NOT NULL,
                buyer_user_id   TEXT   NOT NULL,
                seller_user_id  TEXT   NOT NULL,
                creator_user_id TEXT   NOT NULL,
                total_points    INTEGER NOT NULL,
                platform_fee    INTEGER NOT NULL,
                seller_share    INTEGER NOT NULL,
                creator_share   INTEGER NOT NULL,
                tx_type         TEXT    NOT NULL,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS withdraw_requests(
                id         BIGSERIAL PRIMARY KEY,
                user_id    TEXT    NOT NULL,
                amount     INTEGER NOT NULL,
                status     TEXT    DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS like_logs(
                id         BIGSERIAL PRIMARY KEY,
                user_id    TEXT   NOT NULL,
                work_id    BIGINT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, work_id)
            )
            """)

            # purchase_logs (Stripe冪等用)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS purchase_logs(
                id                BIGSERIAL PRIMARY KEY,
                user_id           TEXT    NOT NULL,
                price_type        TEXT    NOT NULL,
                points_added      INTEGER NOT NULL,
                stripe_session_id TEXT    UNIQUE NOT NULL,
                created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # インデックス
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_works_content_hash ON works(content_hash)")
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_works_ball_code   ON works(ball_code)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ownership_owner_id       ON ownership(owner_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_owned_cards_user_id      ON owned_cards(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_offers_to_user           ON offers(to_user)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_offers_from_user         ON offers(from_user)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_market_status            ON market(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_battle_queue_user_id     ON battle_queue(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_battle_logs_user_id      ON battle_logs(user_id)")
