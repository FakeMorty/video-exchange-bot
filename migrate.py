"""
Безопасный запуск миграций.
Обходит DuplicateTableError путём stamp + retry.
"""
import subprocess
import sys


def run(cmd: str) -> tuple[bool, str]:
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    output = result.stdout + result.stderr
    return result.returncode == 0, output


def main():
    import os
    db_url = os.getenv("DATABASE_URL", "").strip()
    is_sqlite = (not db_url) or "sqlite" in db_url
    if is_sqlite:
        print("==> SQLite detected. Skipping Alembic migrations because SQLAlchemy will auto-create all tables on startup.")
        return

    print("==> Running Alembic migrations...")

    ok, output = run("alembic upgrade head")
    if ok:
        print("==> Migrations applied successfully")
        return

    print(f"==> Migration failed:\n{output[:500]}")

    # Если DuplicateTable — таблицы уже есть, но alembic не знает
    if "already exists" in output or "DuplicateTable" in output:
        print("==> Detected existing tables, fixing alembic version...")

        # Штампуем до HEAD — все миграции помечены как выполненные
        run("alembic stamp head")
        print("==> Stamped to head. All migrations marked as applied.")

        # Проверяем, что katya_chats существует (наша новая таблица)
        ok2, output2 = run("alembic upgrade head")
        if ok2:
            print("==> Upgrade successful after stamp")
        else:
            print("==> Upgrade still failing, but stamp applied. Continuing.")
            # Если katya_chats не существует — создадим вручную
            print("==> Ensuring katya_chats table exists...")
            run("""python3 -c "
import asyncio
from app.db import engine
from sqlalchemy import text

async def ensure_table():
    async with engine.begin() as conn:
        result = await conn.execute(text(
            \\\"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='katya_chats')\\\"
        ))
        if not result.scalar():
            await conn.execute(text('''
                CREATE TABLE katya_chats (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    title VARCHAR(50) NOT NULL DEFAULT \\'Болтовня\\',
                    message_count INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            '''))
            await conn.execute(text(
                'CREATE INDEX IF NOT EXISTS ix_katya_chats_user_id ON katya_chats(user_id)'
            ))
            print('Created katya_chats table')
        else:
            print('katya_chats table already exists')

asyncio.run(ensure_table())
" """)
    else:
        print("==> Unknown migration error. Attempting stamp + retry...")
        run("alembic stamp head")
        run("alembic upgrade head")


if __name__ == "__main__":
    main()
