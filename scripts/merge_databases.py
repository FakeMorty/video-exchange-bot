import asyncio
import logging
import sys
import os
from decimal import Decimal
from datetime import datetime
from sqlalchemy import select, insert, text, inspect
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models import Base
from app.db import _fix_url

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def merge_table(table, source_conn, dest_conn):
    table_name = table.name
    logger.info(f"Merging table: {table_name}")

    # --- Get the list of columns that actually exist in the SOURCE table ---
    # The SQLAlchemy model may have columns (e.g. lootbox_pity_counter) that
    # haven't been added to the source database yet.  We must only SELECT
    # columns that are present in the source, otherwise the query will fail.
    source_inspector = inspect(source_conn)
    source_columns = {c["name"] for c in source_inspector.get_columns(table_name)}
    model_columns = [c for c in table.columns if c.name in source_columns]

    if not model_columns:
        logger.warning(f"Table {table_name} has no matching columns in source – skipping.")
        return

    # Build a SELECT that only includes columns present in the source
    stmt = select(*model_columns)
    result = await source_conn.execute(stmt)
    rows = result.fetchall()
    if not rows:
        logger.info(f"Table {table_name} is empty in source.")
        return

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
    except Exception as e:
        logger.warning(f"Failed to update sequence for {table_name}: {e}")

    logger.info(f"Successfully merged {table_name}.")

async def main():
    if len(sys.argv) < 3:
        print("Usage: python merge_databases.py <SOURCE_URL> <DEST_URL>")
        return

    source_url = _fix_url(sys.argv[1])
    dest_url = _fix_url(sys.argv[2])

    logger.info("Connecting to databases...")
    
    # For Neon/Supabase we need SSL
    connect_args = {"ssl": "require"}
    
    source_engine = create_async_engine(source_url, connect_args=connect_args)
    dest_engine = create_async_engine(dest_url, connect_args=connect_args)

    async with source_engine.connect() as source_conn:
        async with dest_engine.connect() as dest_conn:
            # Get tables in dependency order
            tables = Base.metadata.sorted_tables
            
            for table in tables:
                try:
                    await merge_table(table, source_conn, dest_conn)
                except Exception as e:
                    logger.error(f"Failed to merge table {table.name}: {e}")
                    await dest_conn.rollback()

    await source_engine.dispose()
    await dest_engine.dispose()
    logger.info("Merge completed.")

if __name__ == "__main__":
    asyncio.run(main())
