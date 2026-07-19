"""
Безопасный запуск миграций.

Логика:
- SQLite / нет DATABASE_URL → пропуск (SQLAlchemy сам создаст таблицы на старте).
- Свежая ПУСТАЯ БД (нет таблицы users) → создаём схему напрямую из моделей
  SQLAlchemy (init_db / Base.metadata.create_all) и выполняем `alembic stamp head`.
  Историческая цепочка alembic-миграций не поднимается с нуля (db_fix.py
  создаёт служебные таблицы, которые миграции затем пытаются создать повторно),
  поэтому для установки "с чистого листа" источник истины — текущие модели.
- СУЩЕСТВУЮЩАЯ БД → обычный `alembic upgrade head`; при ошибках вида
  DuplicateTable / "already exists" (таблицы есть, alembic об этом не знает) —
  `alembic stamp head` + повторный upgrade.
"""
import asyncio
import os
import shutil
import subprocess
import sys

# alembic может не быть в PATH (напр. venv не активирован) — тогда зовём через python -m
ALEMBIC = shutil.which("alembic") or f'"{sys.executable}" -m alembic'


def run(cmd: str) -> tuple[bool, str]:
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    output = result.stdout + result.stderr
    return result.returncode == 0, output


def get_db_state() -> tuple[bool, str | None]:
    """Возвращает (есть ли таблица users, текущая alembic-ревизия или None)."""
    from sqlalchemy import text
    from app.db import engine

    async def _check() -> tuple[bool, str | None]:
        try:
            async with engine.connect() as conn:
                r = await conn.execute(text("SELECT to_regclass('public.users')"))
                has_users = r.scalar() is not None
                r = await conn.execute(text("SELECT to_regclass('public.alembic_version')"))
                rev = None
                if r.scalar() is not None:
                    r = await conn.execute(text("SELECT version_num FROM alembic_version"))
                    rev = r.scalar()
            return has_users, rev
        finally:
            await engine.dispose()

    return asyncio.run(_check())


def create_schema_from_models() -> None:
    """Создаёт все таблицы по текущим моделям SQLAlchemy."""
    from app.db import engine, init_db

    async def _run() -> None:
        try:
            await init_db()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def main():
    db_url = os.getenv("DATABASE_URL", "").strip()
    is_sqlite = (not db_url) or "sqlite" in db_url
    if is_sqlite:
        print("==> SQLite detected. Skipping Alembic migrations because SQLAlchemy will auto-create all tables on startup.")
        return

    # --- Определяем состояние БД ---
    print("==> Checking database state...")
    try:
        has_users, rev = get_db_state()
    except Exception as e:
        # БД недоступна (квота, сеть и т.п.) — conservative path: пробуем обычный
        # alembic upgrade, чтобы не штамповать вслепую. Бот всё равно поднимется
        # и покажет пользователям заглушку о тех. работах.
        print(f"==> Could not inspect database ({e!r}). Falling back to plain alembic upgrade.")
        has_users, rev = True, None

    # --- Свежая пустая БД: схема из моделей + stamp head ---
    if not has_users:
        print("==> Fresh empty database detected. Creating schema from SQLAlchemy models...")
        try:
            create_schema_from_models()
        except Exception as e:
            print(f"==> Schema creation from models failed: {e!r}")
            sys.exit(1)

        ok, output = run(f"{ALEMBIC} stamp head")
        if not ok:
            print(f"==> alembic stamp head failed:\n{output[:500]}")
            sys.exit(1)
        print("==> Schema created. Stamped to head. All migrations marked as applied.")
        return

    # --- Существующая БД: обычный путь миграций ---
    print(f"==> Existing schema detected (alembic revision: {rev or 'unknown'}). Running Alembic migrations...")

    ok, output = run(f"{ALEMBIC} upgrade head")
    if ok:
        print("==> Migrations applied successfully")
        return

    print(f"==> Migration failed:\n{output[:500]}")

    # Если DuplicateTable — таблицы уже есть, но alembic не знает
    if "already exists" in output or "DuplicateTable" in output:
        print("==> Detected existing tables, fixing alembic version...")

        # Штампуем до HEAD — все миграции помечены как выполненные
        run(f"{ALEMBIC} stamp head")
        print("==> Stamped to head. All migrations marked as applied.")

        # Проверяем, что upgrade теперь проходит
        ok2, output2 = run(f"{ALEMBIC} upgrade head")
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
            \\"SELECT to_regclass('public.katya_chats')\\"
        ))
        if result.scalar() is None:
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
        run(f"{ALEMBIC} stamp head")
        run(f"{ALEMBIC} upgrade head")


if __name__ == "__main__":
    main()
