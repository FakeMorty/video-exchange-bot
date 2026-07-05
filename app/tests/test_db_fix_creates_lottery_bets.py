import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_fix_database_creates_lottery_bets_table(monkeypatch):
    import app.utils.db_fix as db_fix

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(db_fix, "engine", engine)

    await db_fix.fix_database()

    async with engine.begin() as conn:
        tables = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    assert "lottery_bets" in tables
    assert "katya_messages" in tables

    await engine.dispose()
