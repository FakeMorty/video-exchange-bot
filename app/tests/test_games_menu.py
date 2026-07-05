from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, User


class DummyState:
    async def clear(self):
        return None


class DummyMessage:
    def __init__(self, user_id):
        self.from_user = SimpleNamespace(id=user_id)
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


@pytest.mark.asyncio
async def test_games_menu_is_not_blocked_by_legacy_game_session(monkeypatch):
    import app.user_handlers as user_handlers

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(user_handlers, "async_session", Session)
    monkeypatch.setattr(user_handlers, "require_nickname", lambda *args, **kwargs: __import__('asyncio').sleep(0, result=True))

    async with Session() as session:
        user = User(telegram_id=9001, balance=Decimal("0.00"), nickname_set=True, display_name="Player")
        session.add(user)
        await session.commit()

    message = DummyMessage(9001)
    state = DummyState()

    await user_handlers.btn_games(message, state)

    assert message.answers
    assert "Игровой центр" in message.answers[0][0]

    await engine.dispose()
