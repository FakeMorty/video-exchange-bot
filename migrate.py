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

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

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


def ensure_columns_step() -> None:
    """Создаёт отсутствующие таблицы и догоняет недостающие колонки моделей.

    Две страховки от дрейфа схемы на СУЩЕСТВУЮЩЕЙ БД:
    1) create_all создаёт таблицы, которых ещё нет (напр. blocked_users не
       существовала в свежей БД, и кнопка «Заблокировать автора» падала с
       UndefinedTable, пока таблицу не создал merge-скрипт);
    2) ensure_model_columns додаёт колонки (кейс users.lootbox_pity_counter,
       не покрытый ни одной alembic-миграцией).
    Оба шага идемпотентны — безопасны на каждом старте.
    """
    from app.db import engine, ensure_model_columns, init_db

    print("==> Ensuring missing tables & model columns exist (schema/model drift check)...")
    try:
        async def _run() -> list[str]:
            try:
                await init_db()  # create_all: создаст только ОТСУТСТВУЮЩИЕ таблицы
                return await ensure_model_columns()
            finally:
                await engine.dispose()

        added = asyncio.run(_run())
        if added:
            print(f"==> Added missing columns: {', '.join(added)}")
        else:
            print("==> Schema is in sync with models.")
    except Exception as e:
        # Не блокируем старт: бот поднимется, а ошибка останется в логах.
        print(f"==> Column ensure failed: {e!r}. Continuing.")


def repair_bonus_spam_step() -> None:
    """Одноразовая починка инфляции от бага спама ежедневного бонуса (2026-08-04).

    Баг: middleware начислял daily_return_bonus на КАЖДЫЙ апдейт, потому что
    пометка «уже начисляли сегодня» не сохранялась. Легитимно — первое
    начисление за сутки (UTC) на пользователя; всё сверх — вычитаем с баланса
    (не уходя в минус) с отдельной записью в balance_logs.
    Маркер bonus_spam_repaired_v1 в bot_settings делает шаг одноразовым.
    """
    print("==> Checking daily-bonus spam repair (one-off)...")

    async def _run() -> int:
        from decimal import Decimal
        from app.db import async_session, engine
        from app.models import BalanceLog, BotSetting, User
        from sqlalchemy import select

        try:
            repaired = 0
            async with async_session() as session:
                flag = (await session.execute(
                    select(BotSetting).where(BotSetting.key == "bonus_spam_repaired_v1")
                )).scalar_one_or_none()
                if flag:
                    return -1

                rows = (await session.execute(
                    select(BalanceLog)
                    .where(BalanceLog.source == "daily_return_bonus")
                    .order_by(BalanceLog.user_id, BalanceLog.created_at, BalanceLog.id)
                )).scalars().all()

                seen_days: set = set()
                spam_by_user: dict = {}
                for r in rows:
                    day_key = (r.user_id, r.created_at.date() if r.created_at else None)
                    amount = r.amount or Decimal("0")
                    if day_key not in seen_days:
                        seen_days.add(day_key)
                        continue  # первое начисление за сутки — легитимное
                    spam_by_user[r.user_id] = spam_by_user.get(r.user_id, Decimal("0")) + amount

                for uid, spam_sum in spam_by_user.items():
                    if spam_sum <= 0:
                        continue
                    user = await session.get(User, uid)
                    if not user:
                        continue
                    current = user.balance or Decimal("0")
                    if current <= 0:
                        continue
                    sub = min(spam_sum, current)
                    user.balance = current - sub
                    session.add(BalanceLog(
                        user_id=uid,
                        amount=-sub,
                        balance_before=current,
                        balance_after=current - sub,
                        source="bonus_spam_repair",
                        details=f"removed_spam={spam_sum}",
                    ))
                    repaired += 1

                session.add(BotSetting(key="bonus_spam_repaired_v1", value="1"))
                await session.commit()
            return repaired
        finally:
            await engine.dispose()

    try:
        n = asyncio.run(_run())
        if n > 0:
            print(f"==> Bonus spam repair: removed extra daily bonuses for {n} user(s).")
        elif n == 0:
            print("==> Bonus spam repair: no spam grants found.")
    except Exception as e:
        # Не роняем старт из-за починки — бот должен подняться в любом случае.
        print(f"==> Bonus spam repair skipped due to error: {e!r}")


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
        ensure_columns_step()
        repair_bonus_spam_step()
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

    # Финальная страховка для существующей БД: догон недостающих колонок
    ensure_columns_step()
    repair_bonus_spam_step()


if __name__ == "__main__":
    main()
