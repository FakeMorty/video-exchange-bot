import asyncio
import logging
import sys
import os
from sqlalchemy import select, text, inspect
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

    skipped = (source_columns & {c.name for c in table.columns}) - dest_columns
    if skipped:
        logger.warning(
            f"Table {table_name}: columns present in source but missing in dest "
            f"({', '.join(sorted(skipped))}) – values for them will NOT be merged."
        )

    if not model_columns:
        logger.warning(f"Table {table_name} has no matching columns in source/dest – skipping.")
        return 0

    # Build a SELECT that only includes columns present in the source
    stmt = select(*model_columns)
    result = await source_conn.execute(stmt)
    rows = result.fetchall()
    if not rows:
        logger.info(f"Table {table_name} is empty in source.")
        return 0

    logger.info(f"Found {len(rows)} rows in source table {table_name}.")

    # Map column names from the select result (which are plain column names)
    col_names = [c.name for c in model_columns]
    data = [dict(zip(col_names, row)) for row in rows]

    # We want to use ON CONFLICT DO NOTHING for PostgreSQL
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # Split into batches to avoid huge queries
    batch_size = 500
    for i in range(0, len(data), batch_size):
        batch = data[i:i + batch_size]
        # Insert only the columns that exist in source
        stmt = pg_insert(table).values(batch)
        stmt = stmt.on_conflict_do_nothing()
        await dest_conn.execute(stmt)

    await dest_conn.commit()

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

    logger.info(f"Successfully merged {len(rows)} rows into {table_name}.")
    return len(rows)


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
