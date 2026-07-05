from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, User, KatyaChat


class DummyState:
    def __init__(self, data=None):
        self.data = data or {}
        self.state = None

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def set_state(self, value):
        self.state = value


class DummyMessage:
    def __init__(self, text, user_id):
        self.text = text
        self.from_user = SimpleNamespace(id=user_id)
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


@pytest.mark.asyncio
async def test_custom_named_chat_keeps_selected_character(monkeypatch):
    import app.ai_assistant as ai_assistant

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(ai_assistant, "async_session", Session)

    async with Session() as session:
        user = User(telegram_id=8001, balance=Decimal("100.00"), nickname_set=True)
        session.add(user)
        await session.commit()

    state = DummyState({"waiting_chat_name": True, "selected_char": "sofa"})
    message = DummyMessage("Мой кастомный чат", 8001)

    await ai_assistant.katya_menu_message(message, state)

    async with Session() as session:
        created_chat = (await session.execute(select(KatyaChat))).scalar_one()
        assert created_chat.character == "sofa"
        assert created_chat.title == "Мой кастомный чат"

    assert state.data["selected_char"] == "sofa"
    assert any("Чат «Мой кастомный чат»" in text for text, _ in message.answers)

    await engine.dispose()
