"""
Final Database and Code Stability Fix.
"""
import asyncio
import os
from sqlalchemy import text
from app.db import engine

async def fix_database():
    print("🔧 Starting Final DB Fix...")
    
    is_sqlite = engine.url.drivername == "sqlite+aiosqlite"
    
    # We use separate connections to avoid transaction aborts
    async with engine.connect() as conn:
        # 1. Fix Events Table
        print("Checking events table...")
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
        
        # Ensure image_file_id exists if table was created by older script
        try:
            await conn.execute(text("ALTER TABLE events ADD COLUMN image_file_id TEXT"))
            await conn.commit()
            print("✅ Added image_file_id to events")
        except:
            pass # Already exists
            
        # 2. Fix Offers Table
        print("Checking offers table...")
        for col, col_type in [("duration_days", "INTEGER NOT NULL DEFAULT 30"), ("placement_cost", "NUMERIC(10,2) NOT NULL DEFAULT 0")]:
            try:
                await conn.execute(text(f"ALTER TABLE offers ADD COLUMN {col} {col_type}"))
                await conn.commit()
            except:
                pass # Already exists
        print("✅ Offers columns checked")
        
        # 3. Fix Active Sales Table
        print("Checking active_sales table...")
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
        print("✅ ActiveSale table OK")

    print("🎉 DB fix complete!")

if __name__ == "__main__":
    asyncio.run(fix_database())
