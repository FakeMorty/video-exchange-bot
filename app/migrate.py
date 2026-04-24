import asyncio
import sys
sys.path.insert(0, '..')
import re

from sqlalchemy import text
from app.db import engine
from app.logger import setup_logging, get_logger, log_info

setup_logging()
logger = get_logger(__name__)


def _normalize_sql_for_sqlite(sql: str) -> str:
    normalized = sql
    normalized = re.sub(
        r"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS",
        "ADD COLUMN",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"\bSERIAL\b", "INTEGER", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bNOW\(\)", "CURRENT_TIMESTAMP", normalized, flags=re.IGNORECASE)
    return normalized


def _extract_add_column(sql: str) -> tuple[str, str] | None:
    match = re.search(
        r"ALTER\s+TABLE\s+([a-zA-Z_][\w]*)\s+ADD\s+COLUMN\s+([a-zA-Z_][\w]*)",
        sql,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(1), match.group(2)


def _extract_index_column(sql: str) -> tuple[str, str] | None:
    match = re.search(
        r"ON\s+([a-zA-Z_][\w]*)\s*\(\s*([a-zA-Z_][\w]*)\s*\)",
        sql,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(1), match.group(2)


async def _sqlite_column_exists(conn, table_name: str, column_name: str) -> bool:
    result = await conn.execute(text(f"PRAGMA table_info({table_name});"))
    columns = {row[1] for row in result.fetchall()}
    return column_name in columns

MIGRATIONS = [
    # --- offers ---
    """
    ALTER TABLE offers
    ADD COLUMN IF NOT EXISTS creator_user_id INTEGER NULL;
    """,
    """
    ALTER TABLE offers
    ADD COLUMN IF NOT EXISTS offer_kind VARCHAR(30) DEFAULT 'system';
    """,
    """
    ALTER TABLE offers
    ADD COLUMN IF NOT EXISTS promotion_tier VARCHAR(30) DEFAULT 'basic';
    """,
    """
    ALTER TABLE offers
    ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'approved';
    """,
    """
    ALTER TABLE offers
    ADD COLUMN IF NOT EXISTS payment_method VARCHAR(20) NULL;
    """,
    """
    ALTER TABLE offers
    ADD COLUMN IF NOT EXISTS promo_price_coins NUMERIC(12,2) DEFAULT 0;
    """,
    """
    ALTER TABLE offers
    ADD COLUMN IF NOT EXISTS promo_price_rub INTEGER DEFAULT 0;
    """,
    """
    ALTER TABLE offers
    ADD COLUMN IF NOT EXISTS promo_price_stars INTEGER DEFAULT 0;
    """,
    """
    ALTER TABLE offers
    ADD COLUMN IF NOT EXISTS priority_level INTEGER DEFAULT 10;
    """,
    """
    ALTER TABLE offers
    ADD COLUMN IF NOT EXISTS is_featured BOOLEAN DEFAULT FALSE;
    """,
    """
    ALTER TABLE offers
    ADD COLUMN IF NOT EXISTS moderation_comment TEXT NULL;
    """,
    """
    ALTER TABLE offers
    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP NULL;
    """,
    """
    ALTER TABLE offers
    ADD COLUMN IF NOT EXISTS is_rentable BOOLEAN DEFAULT FALSE;
    """,
    """
    ALTER TABLE offers
    ADD COLUMN IF NOT EXISTS rent_cost_per_day NUMERIC(10,2) DEFAULT 0;
    """,
    """
    ALTER TABLE offers
    ADD COLUMN IF NOT EXISTS max_simultaneous_rentals INTEGER DEFAULT 1;
    """,
    """
    ALTER TABLE offers
    ADD COLUMN IF NOT EXISTS penalty_unsubscribe NUMERIC(10,2) DEFAULT 40;
    """,
        # --- user_ad_states ---
    """
    CREATE TABLE IF NOT EXISTS user_ad_states (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
        last_offer_shown_at TIMESTAMP NULL,
        last_low_balance_hint_at TIMESTAMP NULL,
        forced_offer_id INTEGER NULL,
        forced_offer_shown_at TIMESTAMP NULL,
        updated_at TIMESTAMP DEFAULT NOW()
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_user_ad_states_user_id
    ON user_ad_states (user_id);
    """,
    # --- users ---
    """
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS display_name VARCHAR(32) NULL;
    """,
    """
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS nickname_set BOOLEAN DEFAULT FALSE;
    """,
    # --- game_sessions ---
    """
    CREATE TABLE IF NOT EXISTS game_sessions (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        window_start TIMESTAMP NOT NULL,
        games_played INTEGER DEFAULT 0,
        paid_at TIMESTAMP NULL
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_game_sessions_user_id
    ON game_sessions (user_id);
    """,
    # --- balance_logs ---
    """
    CREATE TABLE IF NOT EXISTS balance_logs (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        amount NUMERIC(10,2) NOT NULL,
        balance_before NUMERIC(10,2) NOT NULL,
        balance_after NUMERIC(10,2) NOT NULL,
        source VARCHAR(100) NOT NULL,
        source_id INTEGER NULL,
        admin_id INTEGER NULL,
        details TEXT NULL,
        created_at TIMESTAMP DEFAULT NOW()
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_balance_logs_user_id
    ON balance_logs (user_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_balance_logs_created_at
    ON balance_logs (created_at);
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_balance_logs_source
    ON balance_logs (source);
    """,
    # --- lootbox_opens ---
    """
    CREATE TABLE IF NOT EXISTS lootbox_opens (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        payment_payload VARCHAR(255) NULL,
        pay_currency VARCHAR(10) NOT NULL,
        price_coins NUMERIC(10,2) DEFAULT 0,
        price_stars INTEGER DEFAULT 0,
        reward_coins NUMERIC(10,2) DEFAULT 0,
        rarity VARCHAR(20) DEFAULT 'common',
        created_at TIMESTAMP DEFAULT NOW(),
        CONSTRAINT uq_lootbox_payment_payload UNIQUE (payment_payload)
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_lootbox_opens_user_id
    ON lootbox_opens (user_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_lootbox_opens_created_at
    ON lootbox_opens (created_at);
    """,
    # --- trusted_uploaders ---
    """
    CREATE TABLE IF NOT EXISTS trusted_uploaders (
        id SERIAL PRIMARY KEY,
        admin_user_id INTEGER NOT NULL REFERENCES users(id),
        trusted_user_id INTEGER NOT NULL REFERENCES users(id),
        created_at TIMESTAMP DEFAULT NOW(),
        CONSTRAINT uq_admin_trusted_user UNIQUE (admin_user_id, trusted_user_id)
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_trusted_uploaders_admin_user_id
    ON trusted_uploaders (admin_user_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_trusted_uploaders_trusted_user_id
    ON trusted_uploaders (trusted_user_id);
    """,
    # --- offer_rentals ---
    """
    CREATE TABLE IF NOT EXISTS offer_rentals (
        id SERIAL PRIMARY KEY,
        offer_id INTEGER NOT NULL REFERENCES offers(id),
        renter_user_id INTEGER NOT NULL REFERENCES users(id),
        renter_channel_title VARCHAR(255) NOT NULL,
        renter_channel_url TEXT NOT NULL,
        rent_days INTEGER NOT NULL,
        cost_paid NUMERIC(10,2) NOT NULL,
        status VARCHAR(20) DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT NOW(),
        expires_at TIMESTAMP NULL
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_offer_rentals_offer_id
    ON offer_rentals (offer_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_offer_rentals_renter_user_id
    ON offer_rentals (renter_user_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_offer_rentals_status
    ON offer_rentals (status);
    """,
    # --- индексы ---
    """
    CREATE INDEX IF NOT EXISTS ix_offers_creator_user_id
    ON offers (creator_user_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_offers_status
    ON offers (status);
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_game_history_user_id
    ON game_history (user_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_game_history_created_at
    ON game_history (created_at);
    """,
"""
ALTER TABLE users ADD COLUMN IF NOT EXISTS bonus_streak INTEGER DEFAULT 0;
""",
"""
ALTER TABLE users ADD COLUMN IF NOT EXISTS promo_created_this_month INTEGER DEFAULT 0;
""",
"""
CREATE TABLE IF NOT EXISTS promocodes (
    id SERIAL PRIMARY KEY,
    creator_user_id INTEGER NOT NULL REFERENCES users(id),
    code VARCHAR(50) UNIQUE NOT NULL,
    coin_amount NUMERIC(10,2) NOT NULL,
    max_uses INTEGER NOT NULL,
    used_count INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    is_public BOOLEAN DEFAULT FALSE,
    created_via_stars BOOLEAN DEFAULT TRUE,
    stars_paid INTEGER DEFAULT 0,
    expires_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
""",
"""
CREATE INDEX IF NOT EXISTS ix_promocodes_code ON promocodes (code);
""",
"""
CREATE INDEX IF NOT EXISTS ix_promocodes_creator ON promocodes (creator_user_id);
""",
"""
CREATE TABLE IF NOT EXISTS promocode_activations (
    id SERIAL PRIMARY KEY,
    promocode_id INTEGER NOT NULL REFERENCES promocodes(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW()
);
""",
"""
CREATE INDEX IF NOT EXISTS ix_promocode_activations_promo ON promocode_activations (promocode_id);
""",
"""
CREATE INDEX IF NOT EXISTS ix_promocode_activations_user ON promocode_activations (user_id);
""",
"""
ALTER TABLE offer_participations
ADD COLUMN IF NOT EXISTS unsubscribed_penalized_at TIMESTAMP NULL;
""",
"""
CREATE TABLE IF NOT EXISTS feedback_messages (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    kind VARCHAR(20) NOT NULL DEFAULT 'suggestion',
    text TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'new',
    created_at TIMESTAMP DEFAULT NOW()
);
""",
"""
CREATE INDEX IF NOT EXISTS ix_feedback_messages_user_id ON feedback_messages (user_id);
""",
"""
CREATE INDEX IF NOT EXISTS ix_feedback_messages_created_at ON feedback_messages (created_at);
""",
"""
CREATE TABLE IF NOT EXISTS lottery_rounds (
    id SERIAL PRIMARY KEY,
    week_key VARCHAR(20) UNIQUE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    ticket_price NUMERIC(10,2) NOT NULL DEFAULT 3,
    numbers_pool INTEGER NOT NULL DEFAULT 36,
    numbers_per_ticket INTEGER NOT NULL DEFAULT 6,
    drawn_numbers TEXT NULL,
    prize_pool NUMERIC(12,2) NOT NULL DEFAULT 0,
    starts_at TIMESTAMP NOT NULL,
    draw_starts_at TIMESTAMP NOT NULL,
    draw_ends_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
""",
"""
CREATE INDEX IF NOT EXISTS ix_lottery_rounds_week_key ON lottery_rounds (week_key);
""",
"""
CREATE TABLE IF NOT EXISTS lottery_tickets (
    id SERIAL PRIMARY KEY,
    round_id INTEGER NOT NULL REFERENCES lottery_rounds(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    numbers VARCHAR(100) NOT NULL,
    matched_count INTEGER NOT NULL DEFAULT 0,
    reward_paid BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);
""",
"""
CREATE INDEX IF NOT EXISTS ix_lottery_tickets_round_id ON lottery_tickets (round_id);
""",
"""
CREATE INDEX IF NOT EXISTS ix_lottery_tickets_user_id ON lottery_tickets (user_id);
""",
]


async def main():
    applied_count = 0
    skipped_count = 0

    async with engine.begin() as conn:
        is_sqlite = conn.dialect.name == "sqlite"

        for sql in MIGRATIONS:
            try:
                sql_to_run = sql.strip()
                if is_sqlite:
                    sql_to_run = _normalize_sql_for_sqlite(sql_to_run)

                    add_column = _extract_add_column(sql_to_run)
                    if add_column:
                        table_name, column_name = add_column
                        if await _sqlite_column_exists(conn, table_name, column_name):
                            skipped_count += 1
                            log_info(
                                logger,
                                f"Migration skipped: column already exists ({table_name}.{column_name})",
                            )
                            continue

                    if "CREATE INDEX" in sql_to_run.upper():
                        index_target = _extract_index_column(sql_to_run)
                        if index_target:
                            table_name, column_name = index_target
                            if not await _sqlite_column_exists(conn, table_name, column_name):
                                skipped_count += 1
                                log_info(
                                    logger,
                                    f"Migration skipped: index column missing ({table_name}.{column_name})",
                                )
                                continue
                await conn.execute(text(sql_to_run))
                applied_count += 1
            except Exception as e:
                skipped_count += 1
                log_info(logger, f"Migration skipped: {e}")
    await engine.dispose()
    log_info(
        logger,
        f"Migrations finished: applied={applied_count}, skipped={skipped_count}",
    )


if __name__ == "__main__":
    asyncio.run(main())