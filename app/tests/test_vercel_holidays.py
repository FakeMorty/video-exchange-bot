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
