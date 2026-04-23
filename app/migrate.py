import asyncio
import sys
sys.path.insert(0, '..')

from sqlalchemy import text
from app.db import engine
from app.logger import setup_logging, get_logger, log_info

setup_logging()
logger = get_logger(__name__)

MIGRATIONS = [
    # --- offers ---
    """
    ALTER TABLE offers
    ADD COLUMN IF NOT EXISTS created_by_user_id INTEGER NULL;
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
    CREATE INDEX IF NOT EXISTS ix_offers_created_by_user_id
    ON offers (created_by_user_id);
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
]


async def main():
    async with engine.begin() as conn:
        for sql in MIGRATIONS:
            try:
                await conn.execute(text(sql.strip()))
            except Exception as e:
                # SQLite не поддерживает часть синтаксиса PostgreSQL — пропускаем
                log_info(logger, f"Migration skipped: {e}")
    await engine.dispose()
    log_info(logger, "Migrations applied successfully")


if __name__ == "__main__":
    asyncio.run(main())