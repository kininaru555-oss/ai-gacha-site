"""
database.py — DB接続・テーブル初期化
"""
import os
import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL が設定されていません")

# Render / Heroku / Supabase などでは sslmode=prefer または require が一般的
if "sslmode=" not in DATABASE_URL:
    sep = "&" if "?" in DATABASE_URL else "?"
    DATABASE_URL = f"{DATABASE_URL}{sep}sslmode=prefer"


def get_db():
    """新しい接続を返す（本番では接続プール推奨）"""
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db():
    """テーブル作成 + 必要に応じてカラム追加（簡易マイグレーション）"""
    with get_db() as conn:
        with conn.cursor() as cur:
            # -----------------------
            # users
            # -----------------------
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id              TEXT PRIMARY KEY,
                password             TEXT    DEFAULT '',
                points               INTEGER DEFAULT 0,
                exp                  INTEGER DEFAULT 0,
                level                INTEGER DEFAULT 1,
                free_draw_count      INTEGER DEFAULT 1,
                revive_items         INTEGER DEFAULT 0,
                royalty_balance      INTEGER DEFAULT 0,
                daily_duplicate_exp  INTEGER DEFAULT 0,
                last_exp_reset       TIMESTAMP DEFAULT NULL
            )
            """)

            # -----------------------
            # works
            # -----------------------
            cur.execute("""
            CREATE TABLE IF NOT EXISTS works (
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
                rarity         TEXT    DEFAULT 'N' CHECK (rarity IN ('N','R','SR','SSR','UR','LR')),
                hp             INTEGER DEFAULT 10,
                atk            INTEGER DEFAULT 10,
                def            INTEGER DEFAULT 10,
                spd            INTEGER DEFAULT 10,
                luk            INTEGER DEFAULT 10,
                exp_reward     INTEGER DEFAULT 5,
                draw_count     INTEGER DEFAULT 0,
                like_count     INTEGER DEFAULT 0,
                is_active      BOOLEAN DEFAULT TRUE,
                is_ball        BOOLEAN DEFAULT FALSE,
                ball_code      TEXT    DEFAULT '',
                content_hash   TEXT    DEFAULT ''
            )
            """)

            # -----------------------
            # 所有関係（1作品＝複数人が所有可能にする場合）
            # -----------------------
            cur.execute("""
            CREATE TABLE IF NOT EXISTS owned_cards (
                id                BIGSERIAL PRIMARY KEY,
                user_id           TEXT    NOT NULL,
                work_id           BIGINT  NOT NULL,
                rarity            TEXT    DEFAULT 'N',
                level             INTEGER DEFAULT 1,
                total_exp         BIGINT  DEFAULT 0,      -- 累計経験値
                current_exp       INTEGER DEFAULT 0,      -- 現在のレベル内経験値（必要に応じて）
                hp                INTEGER DEFAULT 10,
                atk               INTEGER DEFAULT 10,
                def               INTEGER DEFAULT 10,
                spd               INTEGER DEFAULT 10,
                luk               INTEGER DEFAULT 10,
                win_count         INTEGER DEFAULT 0,
                battle_count      INTEGER DEFAULT 0,
                lose_streak_count INTEGER DEFAULT 0,
                is_legend         BOOLEAN DEFAULT FALSE,
                legend_at         TIMESTAMP DEFAULT NULL,
                acquired_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, work_id)  -- 同じ作品を1人1枚まで（必要に応じて削除）
            )
            """)

            # 旧カラム名exp → total_exp に移行したい場合のマイグレーション例
            # （本番では alembic などのツール推奨）
            try:
                cur.execute("ALTER TABLE owned_cards RENAME COLUMN exp TO current_exp")
            except psycopg.errors.UndefinedColumn:
                pass  # すでに変更済みなら無視

            cur.execute("""
            ALTER TABLE owned_cards
                ADD COLUMN IF NOT EXISTS total_exp     BIGINT  DEFAULT 0,
                ADD COLUMN IF NOT EXISTS win_count     INTEGER DEFAULT 0,
                ADD COLUMN IF NOT EXISTS battle_count  INTEGER DEFAULT 0,
                ADD COLUMN IF NOT EXISTS acquired_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            """)

            # ── 以降のテーブルも同様に記述（長くなるので省略） ──
            # ownership, offers, market, battle_queue, battle_logs, ...
            # 必要に応じて続けてください

            # インデックス（よく使う検索パターンに合わせる）
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_works_content_hash ON works(content_hash)")
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_works_ball_code   ON works(ball_code)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_owned_cards_user_id_work_id ON owned_cards(user_id, work_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_owned_cards_user_id      ON owned_cards(user_id)")
            # 必要に応じて追加

            conn.commit()
            print("Database initialization completed.")
