from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import BalanceLog, Base, User, Video
from app.services import approve_all_pending


async def _make_db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'approve-all.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, session_factory


def _pending_video(author_id: int, number: int) -> Video:
    return Video(
        uploader_user_id=author_id,
        telegram_file_id=f"file-{number}",
        telegram_file_unique_id=f"unique-{number}",
        status="pending",
    )


class _FakeMessage:
    def __init__(self):
        self.chat = SimpleNamespace(id=99001)
        self.edits = []

    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs))


class _FakeCallback:
    def __init__(self, telegram_id: int):
        self.from_user = SimpleNamespace(
            id=telegram_id,
            username="root_admin",
            first_name="Root",
            last_name="Admin",
        )
        self.message = _FakeMessage()
        self.answers = []

    async def answer(self, text=None, **kwargs):
        self.answers.append((text, kwargs))


class _FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text, kwargs))


@pytest.mark.asyncio
async def test_approve_all_processes_batches_and_rewards_each_video_once(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.UPLOAD_REWARD", 10.0)
    engine, session_factory = await _make_db(tmp_path)
    try:
        async with session_factory() as session:
            admin = User(telegram_id=99001, is_admin=True, balance=Decimal("0"))
            author = User(telegram_id=99002, balance=Decimal("0"))
            session.add_all([admin, author])
            await session.flush()
            session.add_all([_pending_video(author.id, number) for number in range(3)])
            await session.commit()
            admin_id, author_id = admin.id, author.id

        async with session_factory() as session:
            assert await approve_all_pending(session, admin_id, limit=2) == 2
        async with session_factory() as session:
            assert await approve_all_pending(session, admin_id, limit=2) == 1
            assert await approve_all_pending(session, admin_id, limit=2) == 0

            statuses = (await session.execute(select(Video.status))).scalars().all()
            assert statuses == ["approved", "approved", "approved"]
            author = await session.get(User, author_id)
            assert author.balance == Decimal("30.00")
            rewards = (await session.execute(
                select(BalanceLog).where(BalanceLog.source == "upload_approved")
            )).scalars().all()
            assert len(rewards) == 3
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_approve_all_confirm_runs_and_creates_missing_env_admin(tmp_path, monkeypatch):
    """Полный сценарий кнопки: logging импортирован, admin_id всегда существует."""
    monkeypatch.setattr("app.services.UPLOAD_REWARD", 10.0)
    engine, session_factory = await _make_db(tmp_path)
    try:
        async with session_factory() as session:
            author = User(telegram_id=99102, balance=Decimal("0"))
            session.add(author)
            await session.flush()
            session.add_all([_pending_video(author.id, number) for number in range(2)])
            await session.commit()
            author_id = author.id

        import app.admin_handlers as admin_handlers
        import app.db as db_module

        monkeypatch.setattr(admin_handlers, "async_session", session_factory)
        monkeypatch.setattr(db_module, "async_session", session_factory)
        monkeypatch.setattr(admin_handlers, "IS_SERVERLESS", True)
        monkeypatch.setattr(admin_handlers, "is_super_admin", lambda _tid: True)

        callback = _FakeCallback(telegram_id=99101)
        bot = _FakeBot()
        await admin_handlers.admin_approve_all_confirm(callback, bot)

        async with session_factory() as session:
            admin = (await session.execute(
                select(User).where(User.telegram_id == 99101)
            )).scalar_one_or_none()
            assert admin is not None
            statuses = (await session.execute(select(Video.status))).scalars().all()
            assert statuses == ["approved", "approved"]
            author = await session.get(User, author_id)
            assert author.balance == Decimal("20.00")

        assert any("успешно завершено" in text for _chat_id, text, _kwargs in bot.messages)
        assert not any("Произошла ошибка" in text for _chat_id, text, _kwargs in bot.messages)
    finally:
        await engine.dispose()
