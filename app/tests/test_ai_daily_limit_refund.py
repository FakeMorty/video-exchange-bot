import time
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, User


class DummyState:
    def __init__(self):
        self.data = {}

    async def get_data(self):
        return dict(self.data)


class DummyBot:
    async def send_chat_action(self, *args, **kwargs):
        return None


class DummyMessage:
    def __init__(self, user_id, text):
        self.from_user = SimpleNamespace(id=user_id)
        self.text = text
        self.bot = DummyBot()
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


@pytest.mark.asyncio
async def test_ai_api_failure_refunds_balance_and_releases_daily_limit(monkeypatch):
    import app.ai_assistant as ai

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(ai, "async_session", Session)
    monkeypatch.setattr(ai, "call_katya", lambda *args, **kwargs: __import__('asyncio').sleep(0, result=None))
    monkeypatch.setattr(ai, "_append_history", lambda *args, **kwargs: __import__('asyncio').sleep(0))
    monkeypatch.setattr(ai, "_get_history", lambda *args, **kwargs: __import__('asyncio').sleep(0, result=[]))

    user_id = 9201
    ai._user_daily_count[user_id] = ai.AI_ASSISTANT_DAILY_LIMIT - 1
    ai._user_daily_reset[user_id] = time.monotonic()
    ai._user_last_ts.pop(user_id, None)

    async with Session() as session:
        user = User(telegram_id=user_id, balance=Decimal("100.00"), nickname_set=True, display_name="Tester")
        session.add(user)
        await session.commit()

    message = DummyMessage(user_id, "Привет")
    state = DummyState()

    await ai.katya_chat_message(message, state)

    async with Session() as session:
        db_user = (await session.execute(select(User).where(User.telegram_id == user_id))).scalar_one()
        assert db_user.balance == Decimal("100.00")

    assert ai._user_daily_count[user_id] == ai.AI_ASSISTANT_DAILY_LIMIT - 1
    assert message.answers
    assert "связь барахлит" in message.answers[-1][0]

    await engine.dispose()
