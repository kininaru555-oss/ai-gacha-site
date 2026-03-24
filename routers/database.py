"""
database.py — PostgreSQL 接続・スキーマ初期化・軽量マイグレーション（password完全削除版 / token_version対応版）

改善方針:
- users.password は完全廃止し、password_hash のみを正式採用
- token_version を users に保持し、JWT強制失効に対応できるようにする
- 重要な CREATE TABLE は必ず失敗を表面化
- 互換用 ALTER / UPDATE / INDEX / FK は「存在確認 + ログ付き」で安全に適用
- schema_version テーブルで適用バージョンを記録
- 後方互換を維持しつつ media_type / item_type / legend_code へ移行
- インデックス・外部キー・最低限の CHECK 制約を追加
- system ユーザーを必ず保証
"""

from __future__ import annotations

import logging
import os
from typing import Any, Iterable, Optional

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL が設定されていません")

if "sslmode=" not in DATABASE_URL:
    sep = "&" if "?" in DATABASE_URL else "?"
    DATABASE_URL = f"{DATABASE_URL}{sep}sslmode=prefer"

SCHEMA_VERSION = 3


def get_db():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def _normalize_sql(sql: str) -> str:
    return " ".join(sql.split())


def _execute_required(cur, sql: str, params: Optional[Iterable[Any]] = None) -> None:
    try:
        cur.execute(sql, params or ())
    except Exception:
        logger.exception("必須SQLの実行に失敗しました: %s", _normalize_sql(sql))
        raise


def _execute_optional(cur, sql: str, params: Optional[Iterable[Any]] = None) -> bool:
    try:
        cur.execute(sql, params or ())
        return True
    except Exception:
        logger.warning("任意SQLの実行に失敗しました: %s", _normalize_sql(sql), exc_info=True)
        return False


def _table_exists(cur, table_name: str) -> bool:
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = %s
        ) AS exists
        """,
        (table_name,),
    )
    row = cur.fetchone()
    return bool(row["exists"])


def _column_exists(cur, table_name: str, column_name: str) -> bool:
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
              AND column_name = %s
        ) AS exists
        """,
        (table_name, column_name),
    )
    row = cur.fetchone()
    return bool(row["exists"])


def _constraint_exists(cur, constraint_name: str) -> bool:
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conname = %s
        ) AS exists
        """,
        (constraint_name,),
    )
    row = cur.fetchone()
    return bool(row["exists"])


def _index_exists(cur, index_name: str) -> bool:
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND indexname = %s
        ) AS exists
        """,
        (index_name,),
    )
    row = cur.fetchone()
    return bool(row["exists"])


def _create_index_if_missing(cur, index_name: str, sql: str) -> None:
    if _index_exists(cur, index_name):
        return
    _execute_optional(cur, sql)


def _add_constraint_if_missing(cur, constraint_name: str, sql: str) -> None:
    if _constraint_exists(cur, constraint_name):
        return
    _execute_optional(cur, sql)


def _set_schema_version(cur, version: int) -> None:
    _execute_required(
        cur,
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            key TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    )
    _execute_required(
        cur,
        """
        INSERT INTO schema_version(key, version, updated_at)
        VALUES('main', %s, NOW())
        ON CONFLICT (key)
        DO UPDATE SET
            version = EXCLUDED.version,
            updated_at = NOW()
        """,
        (version,),
    )


def _create_core_tables(cur) -> None:
    _execute_required(
        cur,
        """
        CREATE TABLE IF NOT EXISTS users(
            user_id                    TEXT PRIMARY KEY,
            password_hash              TEXT NOT NULL DEFAULT '',
            token_version              INTEGER NOT NULL DEFAULT 0,
            points                     INTEGER NOT NULL DEFAULT 0,
            exp                        INTEGER NOT NULL DEFAULT 0,
            level                      INTEGER NOT NULL DEFAULT 1,
            free_draw_count            INTEGER NOT NULL DEFAULT 1,
            revive_items               INTEGER NOT NULL DEFAULT 0,
            royalty_balance            INTEGER NOT NULL DEFAULT 0,
            daily_duplicate_exp        INTEGER NOT NULL DEFAULT 0,
            last_exp_reset             TEXT DEFAULT '',
            daily_exp_purchase_count   INTEGER NOT NULL DEFAULT 0,
            last_exp_purchase_date     TEXT DEFAULT '',
            is_admin                   BOOLEAN NOT NULL DEFAULT FALSE,
            is_official                BOOLEAN NOT NULL DEFAULT FALSE,
            is_active                  BOOLEAN NOT NULL DEFAULT TRUE,
            created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    )

    _execute_required(
        cur,
        """
        CREATE TABLE IF NOT EXISTS works(
            id             BIGSERIAL PRIMARY KEY,
            title          TEXT NOT NULL,
            creator_id     TEXT NOT NULL,
            creator_name   TEXT DEFAULT '',
            description    TEXT DEFAULT '',
            genre          TEXT DEFAULT '',
            type           TEXT DEFAULT 'image',
            media_type     TEXT DEFAULT 'image',
            item_type      TEXT DEFAULT 'work',
            image_url      TEXT DEFAULT '',
            video_url      TEXT DEFAULT '',
            thumbnail_url  TEXT DEFAULT '',
            link_url       TEXT DEFAULT '',
            x_url          TEXT DEFAULT '',
            booth_url      TEXT DEFAULT '',
            chichipui_url  TEXT DEFAULT '',
            dlsite_url     TEXT DEFAULT '',
            fanbox_url     TEXT DEFAULT '',
            skeb_url       TEXT DEFAULT '',
            pixiv_url      TEXT DEFAULT '',
            rarity         TEXT DEFAULT 'N',
            hp             INTEGER NOT NULL DEFAULT 10,
            atk            INTEGER NOT NULL DEFAULT 10,
            def            INTEGER NOT NULL DEFAULT 10,
            spd            INTEGER NOT NULL DEFAULT 10,
            luk            INTEGER NOT NULL DEFAULT 10,
            exp_reward     INTEGER NOT NULL DEFAULT 5,
            draw_count     INTEGER NOT NULL DEFAULT 0,
            like_count     INTEGER NOT NULL DEFAULT 0,
            is_active      BOOLEAN NOT NULL DEFAULT TRUE,
            is_public      BOOLEAN NOT NULL DEFAULT TRUE,
            gacha_enabled  BOOLEAN NOT NULL DEFAULT TRUE,
            is_deleted     BOOLEAN NOT NULL DEFAULT FALSE,
            is_ball        BOOLEAN NOT NULL DEFAULT FALSE,
            ball_code      TEXT DEFAULT NULL,
            legend_code    TEXT DEFAULT NULL,
            content_hash   TEXT DEFAULT NULL,
            published_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    )

    _execute_required(
        cur,
        """
        CREATE TABLE IF NOT EXISTS ownership(
            work_id      BIGINT PRIMARY KEY,
            owner_id     TEXT NOT NULL,
            acquired_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    )

    _execute_required(
        cur,
        """
        CREATE TABLE IF NOT EXISTS owned_cards(
            id                BIGSERIAL PRIMARY KEY,
            user_id           TEXT NOT NULL,
            work_id           BIGINT NOT NULL,
            rarity            TEXT DEFAULT 'N',
            level             INTEGER NOT NULL DEFAULT 1,
            exp               INTEGER NOT NULL DEFAULT 0,
            hp                INTEGER NOT NULL DEFAULT 10,
            atk               INTEGER NOT NULL DEFAULT 10,
            def               INTEGER NOT NULL DEFAULT 10,
            spd               INTEGER NOT NULL DEFAULT 10,
            luk               INTEGER NOT NULL DEFAULT 10,
            lose_streak_count INTEGER NOT NULL DEFAULT 0,
            is_legend         BOOLEAN NOT NULL DEFAULT FALSE,
            legend_at         TEXT DEFAULT '',
            total_exp         BIGINT NOT NULL DEFAULT 0,
            win_count         INTEGER NOT NULL DEFAULT 0,
            battle_count      INTEGER NOT NULL DEFAULT 0,
            current_rarity    TEXT DEFAULT '',
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    )

    _execute_required(
        cur,
        """
        CREATE TABLE IF NOT EXISTS offers(
            id          BIGSERIAL PRIMARY KEY,
            work_id     BIGINT NOT NULL,
            from_user   TEXT NOT NULL,
            to_user     TEXT NOT NULL,
            points      INTEGER NOT NULL,
            status      TEXT NOT NULL DEFAULT 'pending',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    )

    _execute_required(
        cur,
        """
        CREATE TABLE IF NOT EXISTS market(
            id          BIGSERIAL PRIMARY KEY,
            work_id     BIGINT NOT NULL,
            seller      TEXT NOT NULL,
            price       INTEGER NOT NULL,
            status      TEXT NOT NULL DEFAULT 'open',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    )

    _execute_required(
        cur,
        """
        CREATE TABLE IF NOT EXISTS transactions(
            id               BIGSERIAL PRIMARY KEY,
            work_id          BIGINT NOT NULL,
            buyer_user_id    TEXT NOT NULL,
            seller_user_id   TEXT NOT NULL,
            creator_user_id  TEXT NOT NULL,
            total_points     INTEGER NOT NULL,
            platform_fee     INTEGER NOT NULL,
            seller_share     INTEGER NOT NULL,
            creator_share    INTEGER NOT NULL,
            tx_type          TEXT NOT NULL,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    )

    _execute_required(
        cur,
        """
        CREATE TABLE IF NOT EXISTS battle_queue(
            id          BIGSERIAL PRIMARY KEY,
            user_id     TEXT NOT NULL,
            work_id     BIGINT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    )

    _execute_required(
        cur,
        """
        CREATE TABLE IF NOT EXISTS battle_logs(
            id                BIGSERIAL PRIMARY KEY,
            user_id           TEXT NOT NULL,
            opponent_user_id  TEXT DEFAULT '',
            result            TEXT DEFAULT '',
            log_text          TEXT DEFAULT '',
            reward_exp        INTEGER NOT NULL DEFAULT 0,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    )

    _execute_required(
        cur,
        """
        CREATE TABLE IF NOT EXISTS withdraw_requests(
            id          BIGSERIAL PRIMARY KEY,
            user_id     TEXT NOT NULL,
            amount      INTEGER NOT NULL,
            status      TEXT NOT NULL DEFAULT 'pending',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    )

    _execute_required(
        cur,
        """
        CREATE TABLE IF NOT EXISTS like_logs(
            id          BIGSERIAL PRIMARY KEY,
            user_id     TEXT NOT NULL,
            work_id     BIGINT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(user_id, work_id)
        )
        """,
    )

    _execute_required(
        cur,
        """
        CREATE TABLE IF NOT EXISTS view_accesses(
            id           BIGSERIAL PRIMARY KEY,
            user_id      TEXT NOT NULL,
            work_id      BIGINT NOT NULL,
            access_type  TEXT NOT NULL DEFAULT 'view',
            granted_by   TEXT NOT NULL DEFAULT 'system',
            granted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(user_id, work_id, access_type)
        )
        """,
    )

    _execute_required(
        cur,
        """
        CREATE TABLE IF NOT EXISTS purchase_logs(
            id                 BIGSERIAL PRIMARY KEY,
            user_id            TEXT NOT NULL,
            price_type         TEXT NOT NULL,
            points_added       INTEGER NOT NULL,
            stripe_session_id  TEXT UNIQUE NOT NULL,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    )

    _execute_required(
        cur,
        """
        CREATE TABLE IF NOT EXISTS gacha_logs(
            id                 BIGSERIAL PRIMARY KEY,
            user_id            TEXT NOT NULL,
            gacha_type         TEXT NOT NULL,
            work_id            BIGINT,
            creator_user_id    TEXT DEFAULT '',
            cost_points        INTEGER NOT NULL,
            system_points      INTEGER NOT NULL DEFAULT 0,
            creator_royalty    INTEGER NOT NULL DEFAULT 0,
            is_duplicate       BOOLEAN NOT NULL DEFAULT FALSE,
            is_win             BOOLEAN NOT NULL DEFAULT FALSE,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    )

    _execute_required(
        cur,
        """
        CREATE TABLE IF NOT EXISTS royalty_logs(
            id                BIGSERIAL PRIMARY KEY,
            user_id           TEXT NOT NULL,
            work_id           BIGINT,
            source_type       TEXT NOT NULL,
            source_id         BIGINT,
            amount            INTEGER NOT NULL,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    )

    _execute_required(
        cur,
        """
        CREATE TABLE IF NOT EXISTS stripe_events(
            id            BIGSERIAL PRIMARY KEY,
            event_id      TEXT UNIQUE NOT NULL,
            event_type    TEXT NOT NULL,
            processed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
    )

    _execute_required(
        cur,
        """
        CREATE TABLE IF NOT EXISTS point_purchase_logs(
            id                        BIGSERIAL PRIMARY KEY,
            user_id                   TEXT NOT NULL,
            stripe_session_id         TEXT NOT NULL UNIQUE,
            stripe_payment_intent_id  TEXT DEFAULT '',
            product_type              TEXT NOT NULL,
            points                    INTEGER NOT NULL,
            amount_jpy                INTEGER NOT NULL,
            status                    TEXT NOT NULL DEFAULT 'pending',
            created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at              TIMESTAMPTZ
        )
        """,
    )


def _apply_backward_compatible_alters(cur) -> None:
    alter_statements = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_exp_purchase_count INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_exp_purchase_date TEXT DEFAULT ''",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_official BOOLEAN DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS media_type TEXT DEFAULT 'image'",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS item_type TEXT DEFAULT 'work'",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS is_public BOOLEAN DEFAULT TRUE",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS gacha_enabled BOOLEAN DEFAULT TRUE",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN DEFAULT FALSE",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS is_ball BOOLEAN DEFAULT FALSE",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS legend_code TEXT DEFAULT NULL",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS content_hash TEXT DEFAULT NULL",
        "ALTER TABLE works ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ DEFAULT NOW()",
        "ALTER TABLE owned_cards ADD COLUMN IF NOT EXISTS total_exp BIGINT DEFAULT 0",
        "ALTER TABLE owned_cards ADD COLUMN IF NOT EXISTS win_count INTEGER DEFAULT 0",
        "ALTER TABLE owned_cards ADD COLUMN IF NOT EXISTS battle_count INTEGER DEFAULT 0",
        "ALTER TABLE owned_cards ADD COLUMN IF NOT EXISTS current_rarity TEXT DEFAULT ''",
        "ALTER TABLE point_purchase_logs ADD COLUMN IF NOT EXISTS stripe_payment_intent_id TEXT DEFAULT ''",
        "ALTER TABLE point_purchase_logs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ",
    ]
    for stmt in alter_statements:
        _execute_optional(cur, stmt)

    if _column_exists(cur, "users", "password"):
        logger.warning("legacy users.password column detected -> dropping")
        _execute_optional(cur, "ALTER TABLE users DROP COLUMN password")

    _execute_optional(
        cur,
        """
        ALTER TABLE users
        ALTER COLUMN password_hash SET NOT NULL
        """,
    )
    _execute_optional(
        cur,
        """
        ALTER TABLE users
        ALTER COLUMN token_version SET NOT NULL
        """,
    )


def _normalize_existing_data(cur) -> None:
    if _table_exists(cur, "works"):
        _execute_optional(
            cur,
            """
            UPDATE works
            SET media_type = COALESCE(NULLIF(media_type, ''), NULLIF(type, ''), 'image')
            WHERE COALESCE(NULLIF(media_type, ''), '') = ''
            """,
        )
        _execute_optional(
            cur,
            """
            UPDATE works
            SET item_type = CASE
                WHEN COALESCE(NULLIF(item_type, ''), '') <> '' AND item_type <> 'work' THEN item_type
                WHEN COALESCE(is_ball, FALSE) = TRUE THEN 'legend_ball'
                ELSE 'work'
            END
            """,
        )
        _execute_optional(
            cur,
            """
            UPDATE works
            SET legend_code = ball_code
            WHERE legend_code IS NULL
              AND ball_code IS NOT NULL
            """,
        )
        _execute_optional(cur, "UPDATE works SET content_hash = NULL WHERE content_hash = ''")
        _execute_optional(cur, "UPDATE works SET ball_code = NULL WHERE ball_code = ''")
        _execute_optional(cur, "UPDATE works SET legend_code = NULL WHERE legend_code = ''")

    if _table_exists(cur, "users"):
        _execute_optional(
            cur,
            """
            UPDATE users
            SET password_hash = ''
            WHERE password_hash IS NULL
            """,
        )
        _execute_optional(
            cur,
            """
            UPDATE users
            SET token_version = 0
            WHERE token_version IS NULL
            """,
        )


def _add_check_constraints(cur) -> None:
    _add_constraint_if_missing(
        cur,
        "chk_users_points_non_negative",
        """
        ALTER TABLE users
        ADD CONSTRAINT chk_users_points_non_negative
        CHECK (points >= 0)
        """,
    )
    _add_constraint_if_missing(
        cur,
        "chk_users_level_positive",
        """
        ALTER TABLE users
        ADD CONSTRAINT chk_users_level_positive
        CHECK (level >= 1)
        """,
    )
    _add_constraint_if_missing(
        cur,
        "chk_users_revive_items_non_negative",
        """
        ALTER TABLE users
        ADD CONSTRAINT chk_users_revive_items_non_negative
        CHECK (revive_items >= 0)
        """,
    )
    _add_constraint_if_missing(
        cur,
        "chk_users_token_version_non_negative",
        """
        ALTER TABLE users
        ADD CONSTRAINT chk_users_token_version_non_negative
        CHECK (token_version >= 0)
        """,
    )
    _add_constraint_if_missing(
        cur,
        "chk_owned_cards_level_positive",
        """
        ALTER TABLE owned_cards
        ADD CONSTRAINT chk_owned_cards_level_positive
        CHECK (level >= 1)
        """,
    )
    _add_constraint_if_missing(
        cur,
        "chk_market_price_non_negative",
        """
        ALTER TABLE market
        ADD CONSTRAINT chk_market_price_non_negative
        CHECK (price >= 0)
        """,
    )
    _add_constraint_if_missing(
        cur,
        "chk_offers_points_non_negative",
        """
        ALTER TABLE offers
        ADD CONSTRAINT chk_offers_points_non_negative
        CHECK (points >= 0)
        """,
    )
    _add_constraint_if_missing(
        cur,
        "chk_transactions_total_points_non_negative",
        """
        ALTER TABLE transactions
        ADD CONSTRAINT chk_transactions_total_points_non_negative
        CHECK (total_points >= 0)
        """,
    )


def _add_foreign_keys(cur) -> None:
    _add_constraint_if_missing(
        cur,
        "fk_works_creator",
        """
        ALTER TABLE works
        ADD CONSTRAINT fk_works_creator
        FOREIGN KEY (creator_id) REFERENCES users(user_id) ON DELETE RESTRICT
        """,
    )
    _add_constraint_if_missing(
        cur,
        "fk_ownership_work",
        """
        ALTER TABLE ownership
        ADD CONSTRAINT fk_ownership_work
        FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE
        """,
    )
    _add_constraint_if_missing(
        cur,
        "fk_ownership_owner",
        """
        ALTER TABLE ownership
        ADD CONSTRAINT fk_ownership_owner
        FOREIGN KEY (owner_id) REFERENCES users(user_id) ON DELETE CASCADE
        """,
    )
    _add_constraint_if_missing(
        cur,
        "fk_owned_cards_user",
        """
        ALTER TABLE owned_cards
        ADD CONSTRAINT fk_owned_cards_user
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        """,
    )
    _add_constraint_if_missing(
        cur,
        "fk_owned_cards_work",
        """
        ALTER TABLE owned_cards
        ADD CONSTRAINT fk_owned_cards_work
        FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE
        """,
    )
    _add_constraint_if_missing(
        cur,
        "fk_offers_work",
        """
        ALTER TABLE offers
        ADD CONSTRAINT fk_offers_work
        FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE
        """,
    )
    _add_constraint_if_missing(
        cur,
        "fk_market_work",
        """
        ALTER TABLE market
        ADD CONSTRAINT fk_market_work
        FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE
        """,
    )
    _add_constraint_if_missing(
        cur,
        "fk_like_logs_work",
        """
        ALTER TABLE like_logs
        ADD CONSTRAINT fk_like_logs_work
        FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE
        """,
    )
    _add_constraint_if_missing(
        cur,
        "fk_view_accesses_work",
        """
        ALTER TABLE view_accesses
        ADD CONSTRAINT fk_view_accesses_work
        FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE CASCADE
        """,
    )
    _add_constraint_if_missing(
        cur,
        "fk_gacha_logs_work",
        """
        ALTER TABLE gacha_logs
        ADD CONSTRAINT fk_gacha_logs_work
        FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE SET NULL
        """,
    )
    _add_constraint_if_missing(
        cur,
        "fk_royalty_logs_work",
        """
        ALTER TABLE royalty_logs
        ADD CONSTRAINT fk_royalty_logs_work
        FOREIGN KEY (work_id) REFERENCES works(id) ON DELETE SET NULL
        """,
    )
    _add_constraint_if_missing(
        cur,
        "fk_point_purchase_logs_user",
        """
        ALTER TABLE point_purchase_logs
        ADD CONSTRAINT fk_point_purchase_logs_user
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        """,
    )


def _create_indexes(cur) -> None:
    _execute_optional(cur, "DROP INDEX IF EXISTS idx_works_ball_code")
    _execute_optional(cur, "DROP INDEX IF EXISTS idx_works_content_hash")

    _create_index_if_missing(
        cur,
        "idx_works_content_hash_work_only",
        """
        CREATE UNIQUE INDEX idx_works_content_hash_work_only
        ON works(content_hash)
        WHERE content_hash IS NOT NULL
          AND COALESCE(item_type, 'work') = 'work'
        """,
    )
    _create_index_if_missing(
        cur,
        "idx_works_legend_code_only",
        """
        CREATE UNIQUE INDEX idx_works_legend_code_only
        ON works(legend_code)
        WHERE legend_code IS NOT NULL
          AND COALESCE(item_type, 'work') = 'legend_ball'
        """,
    )
    _create_index_if_missing(
        cur,
        "idx_works_ball_code_ball_only",
        """
        CREATE UNIQUE INDEX idx_works_ball_code_ball_only
        ON works(ball_code)
        WHERE ball_code IS NOT NULL
          AND COALESCE(is_ball, FALSE) = TRUE
        """,
    )
    _create_index_if_missing(
        cur,
        "idx_owned_cards_work_id_unique",
        "CREATE UNIQUE INDEX idx_owned_cards_work_id_unique ON owned_cards(work_id)",
    )

    index_statements = {
        "idx_users_token_version": "CREATE INDEX idx_users_token_version ON users(token_version)",
        "idx_works_creator_id": "CREATE INDEX idx_works_creator_id ON works(creator_id)",
        "idx_works_item_type": "CREATE INDEX idx_works_item_type ON works(item_type)",
        "idx_works_media_type": "CREATE INDEX idx_works_media_type ON works(media_type)",
        "idx_works_created_at": "CREATE INDEX idx_works_created_at ON works(created_at DESC)",
        "idx_ownership_owner_id": "CREATE INDEX idx_ownership_owner_id ON ownership(owner_id)",
        "idx_owned_cards_user_id": "CREATE INDEX idx_owned_cards_user_id ON owned_cards(user_id)",
        "idx_offers_to_user": "CREATE INDEX idx_offers_to_user ON offers(to_user)",
        "idx_offers_from_user": "CREATE INDEX idx_offers_from_user ON offers(from_user)",
        "idx_market_status": "CREATE INDEX idx_market_status ON market(status)",
        "idx_market_work_id": "CREATE INDEX idx_market_work_id ON market(work_id)",
        "idx_market_status_created_at": "CREATE INDEX idx_market_status_created_at ON market(status, created_at DESC)",
        "idx_battle_queue_user_id": "CREATE INDEX idx_battle_queue_user_id ON battle_queue(user_id)",
        "idx_battle_queue_user_unique": "CREATE UNIQUE INDEX idx_battle_queue_user_unique ON battle_queue(user_id)",
        "idx_battle_logs_user_id": "CREATE INDEX idx_battle_logs_user_id ON battle_logs(user_id)",
        "idx_battle_logs_user_created_at": "CREATE INDEX idx_battle_logs_user_created_at ON battle_logs(user_id, created_at DESC)",
        "idx_transactions_work_id": "CREATE INDEX idx_transactions_work_id ON transactions(work_id)",
        "idx_transactions_buyer": "CREATE INDEX idx_transactions_buyer ON transactions(buyer_user_id)",
        "idx_transactions_seller": "CREATE INDEX idx_transactions_seller ON transactions(seller_user_id)",
        "idx_transactions_created_at": "CREATE INDEX idx_transactions_created_at ON transactions(created_at DESC)",
        "idx_withdraw_requests_user": "CREATE INDEX idx_withdraw_requests_user ON withdraw_requests(user_id)",
        "idx_view_accesses_user_work": "CREATE INDEX idx_view_accesses_user_work ON view_accesses(user_id, work_id)",
        "idx_gacha_logs_user": "CREATE INDEX idx_gacha_logs_user ON gacha_logs(user_id)",
        "idx_gacha_logs_user_created_at": "CREATE INDEX idx_gacha_logs_user_created_at ON gacha_logs(user_id, created_at DESC)",
        "idx_royalty_logs_user": "CREATE INDEX idx_royalty_logs_user ON royalty_logs(user_id)",
        "idx_royalty_logs_user_created_at": "CREATE INDEX idx_royalty_logs_user_created_at ON royalty_logs(user_id, created_at DESC)",
        "idx_point_purchase_logs_user": "CREATE INDEX idx_point_purchase_logs_user ON point_purchase_logs(user_id)",
        "idx_point_purchase_logs_created_at": "CREATE INDEX idx_point_purchase_logs_created_at ON point_purchase_logs(created_at DESC)",
        "idx_stripe_events_processed_at": "CREATE INDEX idx_stripe_events_processed_at ON stripe_events(processed_at DESC)",
    }

    for index_name, stmt in index_statements.items():
        _create_index_if_missing(cur, index_name, stmt)


def _ensure_system_user(cur) -> None:
    _execute_required(
        cur,
        """
        INSERT INTO users(
            user_id,
            password_hash,
            token_version,
            points,
            exp,
            level,
            free_draw_count,
            revive_items,
            royalty_balance,
            daily_duplicate_exp,
            last_exp_reset,
            daily_exp_purchase_count,
            last_exp_purchase_date,
            is_admin,
            is_official,
            is_active
        )
        VALUES(
            'system',
            '',
            0,
            0,
            0,
            1,
            0,
            0,
            0,
            0,
            '',
            0,
            '',
            FALSE,
            TRUE,
            TRUE
        )
        ON CONFLICT (user_id) DO NOTHING
        """,
    )


def init_db() -> None:
    with get_db() as conn:
        with conn.cursor() as cur:
            _set_schema_version(cur, SCHEMA_VERSION)
            _create_core_tables(cur)
            _apply_backward_compatible_alters(cur)
            _normalize_existing_data(cur)
            _add_check_constraints(cur)
            _add_foreign_keys(cur)
            _create_indexes(cur)
            _ensure_system_user(cur)
        conn.commit()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    print("database init complete")
