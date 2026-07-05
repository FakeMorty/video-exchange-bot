from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, User


class DummyVideo:
    def __init__(self):
        self.file_id = "file"
        self.file_unique_id = "uniq"
        self.duration = 10
        self.file_size = 123


class DummyMessage:
    def __init__(self, user_id):
        self.from_user = SimpleNamespace(id=user_id)
        self.video = DummyVideo()
        self.chat = SimpleNamespace(id=user_id)
        self.answers = []
        self.bot = SimpleNamespace()

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


@pytest.mark.asyncio
async def test_trusted_auto_approve_message_shows_fractional_reward(monkeypatch):
    import app.user_handlers as user_handlers

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(user_handlers, "async_session", Session)
    import app.services as services

    monkeypatch.setattr(user_handlers, "save_video", AsyncMock(return_value=(SimpleNamespace(id=1), False)))
    monkeypatch.setattr(user_handlers, "_update_quest_progress", AsyncMock())
    monkeypatch.setattr(user_handlers, "schedule_mod_notification", AsyncMock())
    monkeypatch.setattr(user_handlers, "_level_up_check", AsyncMock())
    monkeypatch.setattr(user_handlers, "get_xp_multiplier", AsyncMock(return_value=1.0))
    monkeypatch.setattr(services, "auto_approve_if_trusted", AsyncMock(return_value=(True, Decimal("0.50"))))

    async with Session() as session:
        user = User(telegram_id=9801, balance=Decimal("0.00"), nickname_set=True, agreed_to_rules=True, display_name="Trusted")
        session.add(user)
        await session.commit()

    message = DummyMessage(9801)
    await user_handlers.handle_video_upload(message)

    assert message.answers
    assert "+0.50 монет" in message.answers[-1][0]

    await engine.dispose()
