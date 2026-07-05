from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest

from app.models import User
from app.services import log_balance_change
from app.utils.messaging import format_time_for_user


class DummySession:
    def __init__(self):
        self.items = []

    def add(self, item):
        self.items.append(item)


@pytest.mark.asyncio
async def test_log_balance_change_only_logs_without_mutating_balance():
    user = User(id=1, telegram_id=123, balance=Decimal("100.00"))
    session = DummySession()

    await log_balance_change(session, user, Decimal("25.00"), "test_source")

    assert user.balance == Decimal("100.00")
    assert len(session.items) == 1
    log = session.items[0]
    assert log.balance_before == Decimal("100.00")
    assert log.balance_after == Decimal("125.00")
    assert log.amount == Decimal("25.00")


def test_format_time_for_user_includes_local_and_msk_when_timezone_known():
    target = datetime.now(timezone.utc) + timedelta(hours=3)
    text = format_time_for_user(target, "Europe/Moscow")

    assert "через" in text
    assert "по твоему времени" in text
    assert "МСК" in text


def test_format_time_for_user_falls_back_to_msk_only():
    target = datetime.now(timezone.utc) + timedelta(minutes=45)
    text = format_time_for_user(target)

    assert "через" in text
    assert "МСК" in text
