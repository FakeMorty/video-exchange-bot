import asyncio
import logging
import sys
import os
from sqlalchemy import select, text, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models import Base
from app.db import _fix_url, ensure_model_columns, _is_supabase_pooler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _inspect_source_columns(sync_conn, table_name):
    """Возвращает имена колонок таблицы в source-БД или None, если таблицы нет.

    inspect() нельзя вызывать напрямую на AsyncConnection
    (SQLAlchemy 2.0: "Inspection on an AsyncConnection is currently not
    supported"), поэтому эта функция выполняется через conn.run_sync().
    """
    inspector = inspect(sync_conn)
    if not inspector.has_table(table_name):
        return None
    return {c["name"] for c in inspector.get_columns(table_name)}


def _inspect_dest_columns(sync_conn, table_name):
    """Колонки таблицы в dest-БД (None, если таблицы нет) — через run_sync."""
    inspector = inspect(sync_conn)
    if not inspector.has_table(table_name):
        return None
    return {c["name"] for c in inspector.get_columns(table_name)}


async def _load_parent_ids(dest_conn, parent_table, parent_col, cache):
    """Множество существующих в dest значений родительского ключа (с кэшем)."""
    key = (parent_table, parent_col)
    if key not in cache:
        res = await dest_conn.execute(
            text(f'SELECT "{parent_col}" FROM "{parent_table}"')
        )
        cache[key] = {row[0] for row in res.fetchall()}
    return cache[key]


async def merge_table(table, source_conn, dest_conn):
    table_name = table.name
    logger.info(f"Merging table: {table_name}")

    # --- Get the list of columns that actually exist in the SOURCE table ---
    # The SQLAlchemy model may have columns (e.g. lootbox_pity_counter) that
    # haven't been added to the source database yet.  We must only SELECT
    # columns that are present in the source, otherwise the query will fail.
    source_columns = await source_conn.run_sync(_inspect_source_columns, table_name)

    if source_columns is None:
        logger.warning(f"Table {table_name} does not exist in source – skipping.")
        return 0

    # Колонки должны существовать и в DEST (перед merge выполняется create_all
    # + ensure_model_columns, так что расхождений быть не должно — но если
    # какую-то колонку добавить не удалось, лучше слить данные без неё,
    # чем уронить всю таблицу с UndefinedColumnError).
    dest_columns = await dest_conn.run_sync(_inspect_dest_columns, table_name)
    if dest_columns is None:
        logger.warning(f"Table {table_name} does not exist in dest – skipping.")
        return 0

    model_columns = [
        c for c in table.columns
        if c.name in source_columns and c.name in dest_columns
    ]

    skipped_cols = (source_columns & {c.name for c in table.columns}) - dest_columns
    if skipped_cols:
        logger.warning(
            f"Table {table_name}: columns present in source but missing in dest "
            f"({', '.join(sorted(skipped_cols))}) – values for them will NOT be merged."
        )

    if not model_columns:
        logger.warning(f"Table {table_name} has no matching columns in source/dest – skipping.")
        return 0

    # Build a SELECT that only includes columns present in the source.
    # ORDER BY PK — детерминированный порядок батчей (важно для self-FK, когда
    # строка ссылается на уже вставленную более раннюю запись).
    stmt = select(*model_columns)
    pk_cols = [c for c in model_columns if c.primary_key]
    if pk_cols:
        stmt = stmt.order_by(pk_cols[0])
    result = await source_conn.execute(stmt)
    rows = result.fetchall()
    if not rows:
        logger.info(f"Table {table_name} is empty in source.")
        return 0

    logger.info(f"Found {len(rows)} rows in source table {table_name}.")

    # Map column names from the select result (which are plain column names)
    col_names = [c.name for c in model_columns]
    data = [dict(zip(col_names, row)) for row in rows]

    # --- Отсекаем «сирот»: строки, ссылающиеся на отсутствующих родителей ---
    # В старой базе остались записи на удалённых вручную юзеров/видео (FK там
    # когда-то обходили) — одна такая строка роняет ВЕСЬ батч на 500 строк с
    # ForeignKeyViolationError. Родительские таблицы к этому моменту уже слиты
    # в dest (таблицы обходятся в топологическом порядке sorted_tables).
    parent_id_cache: dict = {}
    for col in model_columns:
        if not col.foreign_keys:
            continue
        fk = next(iter(col.foreign_keys))
        parent_t, parent_c = fk.column.table.name, fk.column.name
        allowed = await _load_parent_ids(dest_conn, parent_t, parent_c, parent_id_cache)
        if parent_t == table.name:
            # Self-FK (users.referred_by_user_id): разрешаем также id из самой
            # выборки — такие строки вставляются раньше в пределах батча
            # (ORDER BY pk делает это предсказуемым).
            allowed = allowed | {r.get("id") for r in data if r.get("id") is not None}
        before = len(data)
        data = [
            r for r in data
            if r.get(col.name) is None or r.get(col.name) in allowed
        ]
        dropped = before - len(data)
        if dropped:
            logger.warning(
                f"Table {table_name}: skipped {dropped} orphan rows "
                f"(missing parent {parent_t}.{parent_c} for FK column {col.name})"
            )

    if not data:
        logger.info(f"Table {table_name}: nothing to merge after orphan filtering.")
        return 0

    # We want to use ON CONFLICT DO NOTHING for PostgreSQL
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # Split into batches to avoid huge queries.
    # COMMIT ПОСЛЕ КАЖДОГО БАТЧА: одна битая строка не должна откатывать
    # успешно вставленные предыдущие батчи той же таблицы.
    batch_size = 500
    salvaged_skips = 0
    for i in range(0, len(data), batch_size):
        batch = data[i:i + batch_size]
        stmt = pg_insert(table).values(batch)
        stmt = stmt.on_conflict_do_nothing()
        try:
            await dest_conn.execute(stmt)
        except IntegrityError:
            # Сирота/нарушение констрейнта где-то внутри батча — откатываем
            # батч и сливаем его построчно, пропуская только битые строки.
            await dest_conn.rollback()
            for row in batch:
                try:
                    await dest_conn.execute(
                        pg_insert(table).values([row]).on_conflict_do_nothing()
                    )
                except IntegrityError:
                    await dest_conn.rollback()
                    salvaged_skips += 1
        await dest_conn.commit()

    if salvaged_skips:
        logger.warning(
            f"Table {table_name}: {salvaged_skips} rows skipped during "
            f"row-by-row salvage (FK/constraint violations)"
        )

    # Update sequence for tables with serial/identity columns
    try:
        if "id" in col_names:
            seq_name = f"{table_name}_id_seq"
            res = await dest_conn.execute(text(f"SELECT to_regclass('{seq_name}')"))
            if res.scalar():
                await dest_conn.execute(text(
                    f"SELECT setval('{seq_name}', (SELECT MAX(id) FROM {table_name}))"
                ))
                logger.info(f"Updated sequence {seq_name}")
            await dest_conn.commit()
    except Exception as e:
        logger.warning(f"Failed to update sequence for {table_name}: {e}")

    merged = len(data) - salvaged_skips
    logger.info(f"Successfully merged {merged} rows into {table_name}.")
    return merged


async def main():
    if len(sys.argv) < 3:
        print("Usage: python merge_databases.py <SOURCE_URL> <DEST_URL>")
        return

    source_url = _fix_url(sys.argv[1])
    dest_url = _fix_url(sys.argv[2])

    logger.info("Connecting to databases...")

    # For Neon/Supabase we need SSL
    connect_args = {"ssl": "require"}

    def _engine_for(url: str):
        args = dict(connect_args)
        if _is_supabase_pooler(url):
            # Supavisor в transaction mode не поддерживает prepared
            # statements — отключаем их кэш в asyncpg, иначе будет
            # DuplicatePreparedStatementError (та же логика, что в app/db.py,
            # безвредна и для session pooler).
            args["statement_cache_size"] = 0
        return create_async_engine(url, connect_args=args)

    source_engine = _engine_for(source_url)
    dest_engine = _engine_for(dest_url)

    # Целевая БД может отставать от моделей (create_all не ALTER'ит существующие
    # таблицы, а цепочка alembic неполная — см. users.lootbox_pity_counter).
    # Сначала создаём недостающие таблицы и догоняем недостающие колонки в dest,
    # иначе INSERT'ы упадут с UndefinedColumnError.
    async with dest_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        added = await ensure_model_columns(dest_engine)
        if added:
            logger.info(f"Dest schema: added missing columns: {', '.join(added)}")
    except Exception as e:
        logger.warning(f"Could not ensure dest columns (continuing anyway): {e}")

    failed = []   # list of (table_name, error)
    total_rows = 0

    try:
        async with source_engine.connect() as source_conn:
            async with dest_engine.connect() as dest_conn:
                # Get tables in dependency order
                tables = Base.metadata.sorted_tables

                for table in tables:
                    try:
                        total_rows += await merge_table(table, source_conn, dest_conn)
                    except Exception as e:
                        logger.error(f"Failed to merge table {table.name}: {e}")
                        failed.append((table.name, str(e)))
                        await dest_conn.rollback()
    finally:
        await source_engine.dispose()
        await dest_engine.dispose()

    if failed:
        # Не падаем с ненулевым кодом выхода: скрипт вызывается на каждом
        # деплое через `&&`, и блокировать старт бота из-за одноразовой
        # миграции нельзя. Но failures больше не должны оставаться незаметными.
        logger.error("=" * 70)
        logger.error(f"MERGE FINISHED WITH {len(failed)} FAILED TABLE(S) — DATA WAS NOT FULLY COPIED:")
        for name, err in failed:
            logger.error(f"  - {name}: {err[:300]}")
        logger.error("=" * 70)
    else:
        logger.info(f"Merge completed successfully. Total rows copied: {total_rows}.")


if __name__ == "__main__":
    asyncio.run(main())
