from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, User


class DummyMessage:
    def __init__(self):
        self.answers = []
        self.from_user = SimpleNamespace(id=999999)  # simulate bot/non-user sender

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


@pytest.mark.asyncio
async def test_lottery_menu_uses_explicit_telegram_user_id_for_timezone(monkeypatch):
    import app.user_handlers as user_handlers

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(user_handlers, "async_session", Session)

    async with Session() as session:
        user = User(
            telegram_id=9601,
            balance=Decimal("0.00"),
            nickname_set=True,
            display_name="TimezoneUser",
            timezone="Europe/Moscow",
        )
        session.add(user)
        await session.commit()

    message = DummyMessage()
    await user_handlers._send_lottery_menu(message, 9601)

    assert message.answers
    text = message.answers[0][0]
    assert "по твоему времени" in text or "МСК" in text

    await engine.dispose()
