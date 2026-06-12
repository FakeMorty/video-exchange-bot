"""
Скрипт для применения всех миграций на Render
"""
import asyncio
from alembic.config import Config
from alembic import command
from app.db import engine
from sqlalchemy import text

async def apply_migrations():
    print("=== Применение миграций ===")
    
    # 1. Пробуем обычный alembic upgrade
    try:
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        print("✅ Alembic upgrade head выполнен успешно")
    except Exception as e:
        print(f"⚠️ Alembic upgrade упал: {e}")
        print("Пробуем альтернативный метод...")
    
    # 2. Проверяем какие таблицы существуют
    async with engine.begin() as conn:
        result = await conn.execute(text("""
            SELECT tablename FROM pg_tables 
            WHERE schemaname = 'public'
            ORDER BY tablename
        """))
        tables = [row[0] for row in result.fetchall()]
        print(f"Существующие таблицы: {tables}")
        
        # 3. Если таблицы events нет — создаём вручную
        if 'events' not in tables:
            print("Создаём таблицу events...")
            await conn.execute(text("""
                CREATE TABLE events (
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
            await conn.execute(text("CREATE INDEX ix_events_start_date ON events(start_date)"))
            await conn.execute(text("CREATE INDEX ix_events_end_date ON events(end_date)"))
            print("✅ Таблица events создана")
        
        # 4. Обновляем таблицу offers
        print("Проверяем таблицу offers...")
        result = await conn.execute(text("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'offers'
        """))
        columns = [row[0] for row in result.fetchall()]
        print(f"Колонки offers: {columns}")
        
        # Добавляем duration_days если нет
        if 'duration_days' not in columns:
            await conn.execute(text("ALTER TABLE offers ADD COLUMN duration_days INTEGER NOT NULL DEFAULT 30"))
            print("✅ Добавлена колонка duration_days")
        
        # Добавляем placement_cost если нет
        if 'placement_cost' not in columns:
            await conn.execute(text("ALTER TABLE offers ADD COLUMN placement_cost NUMERIC(10,2) NOT NULL DEFAULT 0"))
            print("✅ Добавлена колонка placement_cost")
        
        # Удаляем старые колонки аренды
        for col in ['is_rentable', 'rent_cost_per_day', 'max_simultaneous_rentals']:
            if col in columns:
                await conn.execute(text(f"ALTER TABLE offers DROP COLUMN {col}"))
                print(f"✅ Удалена колонка {col}")
        
        # 5. Удаляем таблицу offer_rentals если есть
        if 'offer_rentals' in tables:
            await conn.execute(text("DROP TABLE offer_rentals CASCADE"))
            print("✅ Таблица offer_rentals удалена")
        
        print("\n=== Миграции завершены ===")

if __name__ == "__main__":
    asyncio.run(apply_migrations())
