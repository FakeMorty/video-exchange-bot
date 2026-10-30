from datetime import datetime as RealDatetime, timezone
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_holiday_sync_repeats_next_day_and_retries_failure(monkeypatch):
    from api import index
    from app import db, services

    class Clock:
        today = RealDatetime(2026, 10, 29, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz):
            return cls.today

    class SessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *args):
            pass

    sync = AsyncMock(side_effect=[RuntimeError('temporary'), 0, 0])
    monkeypatch.setattr(index, 'datetime', Clock)
    monkeypatch.setattr(index, '_holiday_events_synced_date', None)
    monkeypatch.setattr(db, 'async_session', SessionContext)
    monkeypatch.setattr(services, 'ensure_holiday_events', sync)
    await index._ensure_holiday_events()
    await index._ensure_holiday_events()
    await index._ensure_holiday_events()
    assert sync.await_count == 2
    Clock.today = RealDatetime(2026, 10, 30, tzinfo=timezone.utc)
    await index._ensure_holiday_events()
    assert sync.await_count == 3


@pytest.mark.asyncio
async def test_event_schema_upgrade_existing_table_and_retry(monkeypatch):
    from sqlalchemy import inspect, text
    from sqlalchemy.ext.asyncio import create_async_engine
    from api import index
    from app import db

    engine = create_async_engine('sqlite+aiosqlite:///:memory:')
    async with engine.begin() as conn:
        await conn.execute(text('CREATE TABLE events (id INTEGER PRIMARY KEY, name TEXT)'))
        await conn.execute(text("INSERT INTO events (id, name) VALUES (1, 'existing')"))
    monkeypatch.setattr(db, 'engine', engine)
    monkeypatch.setattr(index, '_event_schema_ready', False)
    await index._ensure_event_schema()
    monkeypatch.setattr(index, '_event_schema_ready', False)
    await index._ensure_event_schema()
    async with engine.connect() as conn:
        columns = await conn.run_sync(lambda c: {x['name'] for x in inspect(c).get_columns('events')})
        assert {'slug', 'poster_path'} <= columns
        assert (await conn.execute(text('SELECT name FROM events WHERE id = 1'))).scalar_one() == 'existing'
    await engine.dispose()
