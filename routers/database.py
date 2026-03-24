"""
database.py — DB接続・テーブル初期化（改善版）

改善点:
- users に経験値購入の日次管理カラムを追加
- works に media_type / item_type / legend_code を追加
- 旧 ball_code / is_ball を後方互換で残しつつ、部分 UNIQUE を導入
- content_hash は通常作品のみ一意に近づけるための準備を実施
- gacha_logs / royalty_logs を追加
- owned_cards の work_id 一意制約を追加（1作品=1育成個体前提）
- 基本的な外部キーを追加
- password を残しつつ password_hash を追加（移行準備）

注意:
- 既存環境との互換性を壊しにくいよう、完全な rename はせず ADD COLUMN 中心です。
- PostgreSQL 前提です。
"""
import os
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL が設定されていません")

if "sslmode=" not in DATABASE_URL:
    sep = "&" if "?" in DATABASE_URL else "?"
    DATABASE_URL = f"{DATABASE_URL}{sep}sslmode=prefer"


def get_db():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def _safe_execute(cur, sql: str, params=None):
    try:
        cur.execute(sql, params or ())
    except Exception:
        # 既存環境で追加済み/競合しても init が極力止まらないようにする
        pass


def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:

        CREATE TABLE IF NOT EXISTS stripe_events (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT UNIQUE NOT NULL,
    event_type TEXT NOT NULL,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
    
  cur.execute(
"""
CREATE TABLE IF NOT EXISTS point_purchase_logs (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    stripe_session_id TEXT NOT NULL UNIQUE,
    stripe_payment_intent_id TEXT DEFAULT '',
    product_type TEXT NOT NULL,
    points INTEGER NOT NULL,
    amount_jpy INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
)
"""
            # ─────────────────────────
            # users
            # ─────────────────────────
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users(
                    user_id                    TEXT PRIMARY KEY,
                    password                   TEXT    DEFAULT '',
                    password_hash              TEXT    DEFAULT '',
                    points                     INTEGER DEFAULT 0,
                    exp                        INTEGER DEFAULT 0,
                    level                      INTEGER DEFAULT 1,
                    free_draw_count            INTEGER DEFAULT 1,
                    revive_items               INTEGER DEFAULT 0,
                    royalty_balance            INTEGER DEFAULT 0,
                    daily_duplicate_exp        INTEGER DEFAULT 0,
                    last_exp_reset             TEXT    DEFAULT '',
                    daily_exp_purchase_count   INTEGER DEFAULT 0,
                    last_exp_purchase_date     TEXT    DEFAULT '',
                    is_admin                   INTEGER DEFAULT 0,
                    is_official                INTEGER DEFAULT 0,
                    is_active                  INTEGER DEFAULT 1,
                    created_at                 TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # ─────────────────────────
            # works
            # ─────────────────────────
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS works(
                    id             BIGSERIAL PRIMARY KEY,
                    title          TEXT    NOT NULL,
                    creator_id     TEXT    NOT NULL,
                    creator_name   TEXT    DEFAULT '',
                    description    TEXT    DEFAULT '',
                    genre          TEXT    DEFAULT '',
                    type           TEXT    DEFAULT 'image',
                    media_type     TEXT    DEFAULT 'image',
                    item_type      TEXT    DEFAULT 'work',
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
                    is_public      INTEGER DEFAULT 1,
                    gacha_enabled  INTEGER DEFAULT 1,
                    is_deleted     INTEGER DEFAULT 0,
                    is_ball        INTEGER DEFAULT 0,
                    ball_code      TEXT    DEFAULT NULL,
                    legend_code    TEXT    DEFAULT NULL,
                    content_hash   TEXT    DEFAULT NULL,
                    published_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # ─────────────────────────
            # ownership / owned_cards
            # ─────────────────────────
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS ownership(
                    work_id      BIGINT PRIMARY KEY,
                    owner_id     TEXT   NOT NULL,
                    acquired_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            cur.execute(
                """
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
                    legend_at         TEXT    DEFAULT '',
                    total_exp         BIGINT  DEFAULT 0,
                    win_count         INTEGER DEFAULT 0,
                    battle_count      INTEGER DEFAULT 0,
                    current_rarity    TEXT    DEFAULT '',
                    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # ─────────────────────────
            # market / offers / transactions
            # ─────────────────────────
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS offers(
                    id          BIGSERIAL PRIMARY KEY,
                    work_id     BIGINT NOT NULL,
                    from_user   TEXT   NOT NULL,
                    to_user     TEXT   NOT NULL,
                    points      INTEGER NOT NULL,
                    status      TEXT    DEFAULT 'pending',
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS market(
                    id          BIGSERIAL PRIMARY KEY,
                    work_id     BIGINT  NOT NULL,
                    seller      TEXT    NOT NULL,
                    price       INTEGER NOT NULL,
                    status      TEXT    DEFAULT 'open',
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS transactions(
                    id               BIGSERIAL PRIMARY KEY,
                    work_id          BIGINT NOT NULL,
                    buyer_user_id    TEXT   NOT NULL,
                    seller_user_id   TEXT   NOT NULL,
                    creator_user_id  TEXT   NOT NULL,
                    total_points     INTEGER NOT NULL,
                    platform_fee     INTEGER NOT NULL,
                    seller_share     INTEGER NOT NULL,
                    creator_share    INTEGER NOT NULL,
                    tx_type          TEXT    NOT NULL,
                    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # ─────────────────────────
            # battles
            # ─────────────────────────
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS battle_queue(
                    id          BIGSERIAL PRIMARY KEY,
                    user_id     TEXT   NOT NULL,
                    work_id     BIGINT NOT NULL,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS battle_logs(
                    id                BIGSERIAL PRIMARY KEY,
                    user_id           TEXT    NOT NULL,
                    opponent_user_id  TEXT    DEFAULT '',
                    result            TEXT    DEFAULT '',
                    log_text          TEXT    DEFAULT '',
                    reward_exp        INTEGER DEFAULT 0,
                    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # ─────────────────────────
            # likes / withdrawals / access / purchases
            # ─────────────────────────
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS withdraw_requests(
                    id          BIGSERIAL PRIMARY KEY,
                    user_id     TEXT    NOT NULL,
                    amount      INTEGER NOT NULL,
                    status      TEXT    DEFAULT 'pending',
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS like_logs(
                    id          BIGSERIAL PRIMARY KEY,
                    user_id     TEXT   NOT NULL,
                    work_id     BIGINT NOT NULL,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, work_id)
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS view_accesses(
                    id           BIGSERIAL PRIMARY KEY,
                    user_id      TEXT    NOT NULL,
                    work_id      BIGINT  NOT NULL,
                    access_type  TEXT    NOT NULL DEFAULT 'view',
                    granted_by   TEXT    NOT NULL DEFAULT 'system',
                    granted_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, work_id, access_type)
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS purchase_logs(
                    id                 BIGSERIAL PRIMARY KEY,
                    user_id            TEXT    NOT NULL,
                    price_type         TEXT    NOT NULL,
                    points_added       INTEGER NOT NULL,
                    stripe_session_id  TEXT    UNIQUE NOT NULL,
                    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # ─────────────────────────
            # ガチャ / ロイヤリティ履歴
            # ─────────────────────────
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS gacha_logs(
                    id                 BIGSERIAL PRIMARY KEY,
                    user_id            TEXT    NOT NULL,
                    gacha_type         TEXT    NOT NULL,
                    work_id            BIGINT,
                    creator_user_id    TEXT    DEFAULT '',
                    cost_points        INTEGER NOT NULL,
                    system_points      INTEGER NOT NULL DEFAULT 0,
                    creator_royalty    INTEGER NOT NULL DEFAULT 0,
                    is_duplicate       INTEGER NOT NULL DEFAULT 0,
                    is_win             INTEGER NOT NULL DEFAULT 0,
                    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS royalty_logs(
                    id                BIGSERIAL PRIMARY KEY,
                    user_id           TEXT    NOT NULL,
                    work_id           BIGINT,
                    source_type       TEXT    NOT NULL,
                    source_id         BIGINT,
                    amount            INTEGER NOT NULL,
                    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # ─────────────────────────
            # 後方互換用 ALTER
            # ─────────────────────────
            alter_statements = [
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT DEFAULT ''",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_exp_purchase_count INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_exp_purchase_date TEXT DEFAULT ''",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_official INTEGER DEFAULT 0",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active INTEGER DEFAULT 1",
                "ALTER TABLE works ADD COLUMN IF NOT EXISTS media_type TEXT DEFAULT 'image'",
                "ALTER TABLE works ADD COLUMN IF NOT EXISTS item_type TEXT DEFAULT 'work'",
                "ALTER TABLE works ADD COLUMN IF NOT EXISTS is_public INTEGER DEFAULT 1",
                "ALTER TABLE works ADD COLUMN IF NOT EXISTS gacha_enabled INTEGER DEFAULT 1",
                "ALTER TABLE works ADD COLUMN IF NOT EXISTS is_deleted INTEGER DEFAULT 0",
                "ALTER TABLE works ADD COLUMN IF NOT EXISTS legend_code TEXT DEFAULT NULL",
                "ALTER TABLE works ADD COLUMN IF NOT EXISTS published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                "ALTER TABLE owned_cards ADD COLUMN IF NOT EXISTS total_exp BIGINT DEFAULT 0",
                "ALTER TABLE owned_cards ADD COLUMN IF NOT EXISTS win_count INTEGER DEFAULT 0",
                "ALTER TABLE owned_cards ADD COLUMN IF NOT EXISTS battle_count INTEGER DEFAULT 0",
                "ALTER TABLE owned_cards ADD COLUMN IF NOT EXISTS current_rarity TEXT DEFAULT ''",
            ]
            for stmt in alter_statements:
                _safe_execute(cur, stmt)

            # media_type 初期値同期
            _safe_execute(cur, "UPDATE works SET media_type = COALESCE(NULLIF(media_type, ''), type, 'image')")
            # item_type 初期値同期
            _safe_execute(
                cur,
                """
                UPDATE works
                SET item_type = CASE
                    WHEN COALESCE(item_type, '') <> '' AND item_type <> 'work' THEN item_type
                    WHEN COALESCE(is_ball, 0) = 1 THEN 'legend_ball'
                    ELSE 'work'
                END
                """
            )
            # legend_code 同期
            _safe_execute(cur, "UPDATE works SET legend_code = ball_code WHERE legend_code IS NULL AND ball_code IS NOT NULL")
            # NULL/空文字整理
            _safe_execute(cur, "UPDATE works SET content_hash = NULL WHERE content_hash = ''")
            _safe_execute(cur, "UPDATE works SET ball_code = NULL WHERE ball_code = ''")
            _safe_execute(cur, "UPDATE works SET legend_code = NULL WHERE legend_code = ''")

            # ─────────────────────────
            # 外部キー（追加できるものだけ）
            # ─────────────────────────
            fk_statements = [
                "ALTER TABLE works ADD CONSTRAINT fk_works_creator FOREIGN KEY (creator_id) REFERENCES users(user_id) ON DELETE RESTRICT",
                "ALTER TABLE ownership ADD CONSTRAINT fk_ownership_work FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE",
                "ALTER TABLE ownership ADD CONSTRAINT fk_ownership_owner FOREIGN KEY (owner_id) REFERENCES users(user_id) ON DELETE CASCADE",
                "ALTER TABLE owned_cards ADD CONSTRAINT fk_owned_cards_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE",
                "ALTER TABLE owned_cards ADD CONSTRAINT fk_owned_cards_work FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE",
                "ALTER TABLE offers ADD CONSTRAINT fk_offers_work FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE",
                "ALTER TABLE market ADD CONSTRAINT fk_market_work FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE",
                "ALTER TABLE like_logs ADD CONSTRAINT fk_like_logs_work FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE",
                "ALTER TABLE view_accesses ADD CONSTRAINT fk_view_accesses_work FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE",
                "ALTER TABLE gacha_logs ADD CONSTRAINT fk_gacha_logs_work FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE SET NULL",
                "ALTER TABLE royalty_logs ADD CONSTRAINT fk_royalty_logs_work FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE SET NULL",
            ]
            for stmt in fk_statements:
                _safe_execute(cur, stmt)

            # ─────────────────────────
            # インデックス / 制約
            # ─────────────────────────
            # 古い一律 UNIQUE を外す（存在していれば）
            _safe_execute(cur, "DROP INDEX IF EXISTS idx_works_ball_code")
            _safe_execute(cur, "DROP INDEX IF EXISTS idx_works_content_hash")

            # 通常作品だけ content_hash 一意（NULL は除外）
            _safe_execute(
                cur,
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_works_content_hash_work_only
                ON works(content_hash)
                WHERE content_hash IS NOT NULL AND COALESCE(item_type, 'work') = 'work'
                """
            )
            # レジェンドボールだけ legend_code 一意
            _safe_execute(
                cur,
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_works_legend_code_only
                ON works(legend_code)
                WHERE legend_code IS NOT NULL AND COALESCE(item_type, 'work') = 'legend_ball'
                """
            )
            # 旧列互換: is_ball=1 側のみ ball_code 一意
            _safe_execute(
                cur,
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_works_ball_code_ball_only
                ON works(ball_code)
                WHERE ball_code IS NOT NULL AND COALESCE(is_ball, 0) = 1
                """
            )

            # 1作品=1育成個体前提
            _safe_execute(cur, "CREATE UNIQUE INDEX IF NOT EXISTS idx_owned_cards_work_id_unique ON owned_cards(work_id)")

            # その他インデックス
            index_statements = [
                "CREATE INDEX IF NOT EXISTS idx_works_creator_id ON works(creator_id)",
                "CREATE INDEX IF NOT EXISTS idx_works_item_type ON works(item_type)",
                "CREATE INDEX IF NOT EXISTS idx_works_media_type ON works(media_type)",
                "CREATE INDEX IF NOT EXISTS idx_ownership_owner_id ON ownership(owner_id)",
                "CREATE INDEX IF NOT EXISTS idx_owned_cards_user_id ON owned_cards(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_offers_to_user ON offers(to_user)",
                "CREATE INDEX IF NOT EXISTS idx_offers_from_user ON offers(from_user)",
                "CREATE INDEX IF NOT EXISTS idx_market_status ON market(status)",
                "CREATE INDEX IF NOT EXISTS idx_market_work_id ON market(work_id)",
                "CREATE INDEX IF NOT EXISTS idx_battle_queue_user_id ON battle_queue(user_id)",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_battle_queue_user_unique ON battle_queue(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_battle_logs_user_id ON battle_logs(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_transactions_work_id ON transactions(work_id)",
                "CREATE INDEX IF NOT EXISTS idx_transactions_buyer ON transactions(buyer_user_id)",
                "CREATE INDEX IF NOT EXISTS idx_transactions_seller ON transactions(seller_user_id)",
                "CREATE INDEX IF NOT EXISTS idx_withdraw_requests_user ON withdraw_requests(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_view_accesses_user_work ON view_accesses(user_id, work_id)",
                "CREATE INDEX IF NOT EXISTS idx_gacha_logs_user ON gacha_logs(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_royalty_logs_user ON royalty_logs(user_id)",
            ]
            for stmt in index_statements:
                _safe_execute(cur, stmt)

            # system ユーザー存在保証
            _safe_execute(
                cur,
                """
                INSERT INTO users(user_id, password, password_hash, points, exp, level, free_draw_count, revive_items, royalty_balance, daily_duplicate_exp, last_exp_reset, daily_exp_purchase_count, last_exp_purchase_date, is_admin, is_official, is_active)
                VALUES('system', '', '', 0, 0, 1, 0, 0, 0, 0, '', 0, '', 0, 1, 1)
                ON CONFLICT (user_id) DO NOTHING
                """
            )

        conn.commit()


if __name__ == "__main__":
    init_db()
    print("database init complete")
