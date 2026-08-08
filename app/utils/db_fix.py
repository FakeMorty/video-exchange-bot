"""
Robust DB fix utility.
"""
from sqlalchemy import text
from app.db import engine

from app.logger import get_logger, log_info

logger = get_logger(__name__)

async def fix_database():
    log_info(logger, "Starting DB structure fix...")
    
    is_sqlite = engine.url.drivername == "sqlite+aiosqlite"
    
    async with engine.connect() as conn:
        # 1. Events Table
        if is_sqlite:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    discount_percent INTEGER NOT NULL,
                    duration_days INTEGER NOT NULL,
                    applies_vip BOOLEAN NOT NULL DEFAULT 0,
                    applies_coins BOOLEAN NOT NULL DEFAULT 0,
                    applies_lootbox BOOLEAN NOT NULL DEFAULT 0,
                    applies_cases BOOLEAN NOT NULL DEFAULT 0,
                    image_file_id TEXT,
                    start_date TIMESTAMP NOT NULL,
                    end_date TIMESTAMP NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    created_by INTEGER,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """))
        else:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS events (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    description TEXT,
                    discount_percent INTEGER NOT NULL,
                    duration_days INTEGER NOT NULL,
                    applies_vip BOOLEAN NOT NULL DEFAULT false,
                    applies_coins BOOLEAN NOT NULL DEFAULT false,
                    applies_lootbox BOOLEAN NOT NULL DEFAULT false,
                    applies_cases BOOLEAN NOT NULL DEFAULT false,
                    image_file_id TEXT,
                    start_date TIMESTAMP NOT NULL,
                    end_date TIMESTAMP NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT true,
                    created_by INTEGER,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """))
        await conn.commit()
        
        # Ensure image_file_id exists
        try:
            await conn.execute(text("ALTER TABLE events ADD COLUMN image_file_id TEXT"))
            await conn.commit()
        except Exception:
            await conn.rollback()
            
        # 2. Offers Table
        for col, col_type in [("duration_days", "INTEGER NOT NULL DEFAULT 30"), ("placement_cost", "NUMERIC(10,2) NOT NULL DEFAULT 0")]:
            try:
                await conn.execute(text(f"ALTER TABLE offers ADD COLUMN {col} {col_type}"))
                await conn.commit()
            except Exception:
                await conn.rollback()
        

        # 2b. UserPerks style_id column
        try:
            await conn.execute(text("ALTER TABLE user_perks ADD COLUMN style_id INTEGER"))
            await conn.commit()
            log_info(logger, "Added user_perks.style_id")
        except Exception:
            await conn.rollback()

        # 3. Active Sales Table
        if is_sqlite:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS active_sales (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    discount_percent INTEGER NOT NULL,
                    applies_to VARCHAR(50) NOT NULL,
                    end_date TIMESTAMP NOT NULL,
                    announcement TEXT
                )
            """))
        else:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS active_sales (
                    id SERIAL PRIMARY KEY,
                    discount_percent INTEGER NOT NULL,
                    applies_to VARCHAR(50) NOT NULL,
                    end_date TIMESTAMP NOT NULL,
                    announcement TEXT
                )
            """))
        await conn.commit()

        # 4. Settings Table
        if is_sqlite:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS bot_settings (
                    key VARCHAR(50) PRIMARY KEY,
                    value TEXT
                )
            """))
        else:
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS bot_settings (
                    key VARCHAR(50) PRIMARY KEY,
                    value TEXT
                )
            """))
        await conn.commit()

        # 5. Ensure last_freebie_week and last_freebie_year exist in users table
        for col in ["last_freebie_week", "last_freebie_year"]:
            try:
                await conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0"))
                await conn.commit()
                log_info(logger, f"Added users.{col}")
            except Exception:
                await conn.rollback()
                
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN timezone VARCHAR(50)"))
            await conn.commit()
            log_info(logger, "Added users.timezone")
        except Exception:
            await conn.rollback()

        # Ensure character exists in katya_chats table
        try:
            await conn.execute(text("ALTER TABLE katya_chats ADD COLUMN character VARCHAR(20) NOT NULL DEFAULT 'katya'"))
            await conn.commit()
            log_info(logger, "Added katya_chats.character")
        except Exception:
            await conn.rollback()

        # Ensure katya_messages table exists
        if is_sqlite:
            try:
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS katya_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER NOT NULL REFERENCES katya_chats(id) ON DELETE CASCADE,
                        role VARCHAR(20) NOT NULL,
                        content TEXT NOT NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                await conn.commit()
                log_info(logger, "Created katya_messages table")
            except Exception:
                await conn.rollback()
        else:
            try:
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS katya_messages (
                        id SERIAL PRIMARY KEY,
                        chat_id INTEGER NOT NULL REFERENCES katya_chats(id) ON DELETE CASCADE,
                        role VARCHAR(20) NOT NULL,
                        content TEXT NOT NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW()
                    )
                """))
                await conn.commit()
                log_info(logger, "Created katya_messages table")
            except Exception:
                await conn.rollback()

        # Ensure lottery_bets table exists
        if is_sqlite:
            try:
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS lottery_bets (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL REFERENCES users(id),
                        round_id INTEGER NOT NULL REFERENCES lottery_rounds(id),
                        bet_type VARCHAR(50),
                        amount NUMERIC(10,2) DEFAULT 10.0,
                        is_settled BOOLEAN DEFAULT 0,
                        is_won BOOLEAN DEFAULT 0
                    )
                """))
                await conn.commit()
                log_info(logger, "Created lottery_bets table")
            except Exception:
                await conn.rollback()
        else:
            try:
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS lottery_bets (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id),
                        round_id INTEGER NOT NULL REFERENCES lottery_rounds(id),
                        bet_type VARCHAR(50),
                        amount NUMERIC(10,2) DEFAULT 10.0,
                        is_settled BOOLEAN DEFAULT false,
                        is_won BOOLEAN DEFAULT false
                    )
                """))
                await conn.commit()
                log_info(logger, "Created lottery_bets table")
            except Exception:
                await conn.rollback()

        # Ensure arcade_runs table exists (🚀 Космическая аркада)
        if is_sqlite:
            try:
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS arcade_runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL REFERENCES users(id),
                        bet NUMERIC(10,2) NOT NULL DEFAULT 0,
                        wave INTEGER NOT NULL DEFAULT 0,
                        multiplier NUMERIC(8,2) NOT NULL DEFAULT 1,
                        crash_wave INTEGER NOT NULL DEFAULT 0,
                        status VARCHAR(20) NOT NULL DEFAULT 'active',
                        payout NUMERIC(10,2) NOT NULL DEFAULT 0,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        finished_at TIMESTAMP
                    )
                """))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_arcade_runs_user_id ON arcade_runs (user_id)"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_arcade_runs_status ON arcade_runs (status)"))
                await conn.commit()
                log_info(logger, "Created arcade_runs table")
            except Exception:
                await conn.rollback()
        else:
            try:
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS arcade_runs (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id),
                        bet NUMERIC(10,2) NOT NULL DEFAULT 0,
                        wave INTEGER NOT NULL DEFAULT 0,
                        multiplier NUMERIC(8,2) NOT NULL DEFAULT 1,
                        crash_wave INTEGER NOT NULL DEFAULT 0,
                        status VARCHAR(20) NOT NULL DEFAULT 'active',
                        payout NUMERIC(10,2) NOT NULL DEFAULT 0,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        finished_at TIMESTAMP
                    )
                """))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_arcade_runs_user_id ON arcade_runs (user_id)"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_arcade_runs_status ON arcade_runs (status)"))
                await conn.commit()
                log_info(logger, "Created arcade_runs table")
            except Exception:
                await conn.rollback()

        # Колонка crash_wave на случай таблицы, созданной старой схемой
        try:
            await conn.execute(text("ALTER TABLE arcade_runs ADD COLUMN crash_wave INTEGER NOT NULL DEFAULT 0"))
            await conn.commit()
        except Exception:
            await conn.rollback()

        # Ensure title column exists in promo_messages
        try:
            await conn.execute(text("ALTER TABLE promo_messages ADD COLUMN title VARCHAR(100)"))
            await conn.commit()
            log_info(logger, "Added promo_messages.title")
        except Exception:
            await conn.rollback()

    log_info(logger, "DB fix complete!")
