from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, User, Video


class DummyMessage:
    def __init__(self):
        self.video_answers = []
        self.answers = []

    async def answer_video(self, *args, **kwargs):
        self.video_answers.append((args, kwargs))

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


class DummyCallback:
    def __init__(self, user_id):
        self.from_user = SimpleNamespace(id=user_id)
        self.message = DummyMessage()

    async def answer(self, *args, **kwargs):
        return None


@pytest.mark.asyncio
async def test_watch_video_triggers_referral_reward_check_after_successful_send(monkeypatch):
    import app.user_handlers as user_handlers

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(user_handlers, "async_session", Session)
    referral_mock = AsyncMock()
    monkeypatch.setattr(user_handlers, "process_referral_reward", referral_mock)

    async with Session() as session:
        inviter = User(telegram_id=9101, balance=Decimal("0.00"), nickname_set=True, display_name="Inviter")
        viewer = User(
            telegram_id=9102,
            balance=Decimal("100.00"),
            nickname_set=True,
            display_name="Viewer",
            referred_by_user_id=1,
        )
        uploader = User(telegram_id=9103, balance=Decimal("0.00"), nickname_set=True, display_name="Uploader")
        session.add_all([inviter, viewer, uploader])
        await session.flush()
        viewer.referred_by_user_id = inviter.id

        video = Video(
            uploader_user_id=uploader.id,
            content_type="video",
            telegram_file_id="file_1",
            telegram_file_unique_id="uniq_1",
            status="approved",
        )
        session.add(video)
        await session.commit()

    callback = DummyCallback(9102)
    await user_handlers.watch_video_content(callback)

    referral_mock.assert_awaited_once()
    assert callback.message.video_answers

    await engine.dispose()
