"""
Простой скрипт для исправления БД
Запуск: python fix_db.py
"""
import asyncio
from app.db import engine
from sqlalchemy import text

async def fix_database():
    print("🔧 Исправление структуры БД...")
    
    async with engine.begin() as conn:
        # 1. Создаём events если нет
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
                start_date TIMESTAMP NOT NULL,
                end_date TIMESTAMP NOT NULL,
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_by INTEGER REFERENCES users(id),
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        print("✅ Таблица events OK")
        
        # 2. Обновляем offers
        await conn.execute(text("""
            ALTER TABLE offers 
            ADD COLUMN IF NOT EXISTS duration_days INTEGER NOT NULL DEFAULT 30
        """))
        await conn.execute(text("""
            ALTER TABLE offers 
            ADD COLUMN IF NOT EXISTS placement_cost NUMERIC(10,2) NOT NULL DEFAULT 0
        """))
        print("✅ Колонки offers обновлены")
        
        # 3. Удаляем старые колонки аренды
        for col in ['is_rentable', 'rent_cost_per_day', 'max_simultaneous_rentals']:
            try:
                await conn.execute(text(f"ALTER TABLE offers DROP COLUMN IF EXISTS {col}"))
            except:
                pass
        print("✅ Старые колонки удалены")
        
        # 4. Удаляем offer_rentals
        try:
            await conn.execute(text("DROP TABLE IF EXISTS offer_rentals CASCADE"))
            print("✅ Таблица offer_rentals удалена")
        except:
            pass
        
        print("\n🎉 База данных исправлена!")

if __name__ == "__main__":
    asyncio.run(fix_database())
