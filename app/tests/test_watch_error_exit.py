"""Регрессионные тесты на «выход из ошибки» в просмотре видео/фото.

Проверяем два правила, ради которых правились обработчики:
1. Ошибки понятные — пользователь не видит сырой телеграм-исключение.
2. Из ошибки всегда есть выход — приходит клавиатура с кнопками продолжения,
   даже если одно видео/фото оказалось бракованным (следующее может быть живым).
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, User, Video, VideoView


class DummyMessage:
    def __init__(self, *, video_raises=False, photo_raises=False):
        self.video_answers = []
        self.photo_answers = []
        self.answers = []
        self._video_raises = video_raises
        self._photo_raises = photo_raises

    async def answer_video(self, *args, **kwargs):
        if self._video_raises:
            raise RuntimeError("Bad Request: failed to get HTTP URL")
        self.video_answers.append((args, kwargs))

    async def answer_photo(self, *args, **kwargs):
        if self._photo_raises:
            raise RuntimeError("Bad Request: failed to get HTTP URL")
        self.photo_answers.append((args, kwargs))

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


class DummyCallback:
    def __init__(self, user_id, *, video_raises=False, photo_raises=False):
        self.from_user = SimpleNamespace(id=user_id)
        self.message = DummyMessage(video_raises=video_raises, photo_raises=photo_raises)

    async def answer(self, *args, **kwargs):
        return None


def _markup_callbacks(message):
    """Собирает все callback_data из последнего ответа (если есть клавиатура)."""
    cbs = set()
    if not message.answers:
        return cbs
    _text, kwargs = message.answers[-1]
    markup = kwargs.get("reply_markup")
    if markup is None:
        return cbs
    for row in markup.inline_keyboard:
        for btn in row:
            cbs.add(btn.callback_data)
    return cbs


def _last_text(message):
    assert message.answers, "Ожидалось текстовое сообщение об ошибке"
    return message.answers[-1][0]


async def _make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, Session


# ---------------------------------------------------------------------------
# ВИДЕО
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_watch_video_no_content_shows_clear_message_with_exit(monkeypatch):
    """Нет доступных видео → понятный текст + кнопки продолжения (не тупик)."""
    import app.user_handlers as user_handlers

    engine, Session = await _make_session()
    monkeypatch.setattr(user_handlers, "async_session", Session)

    async with Session() as session:
        viewer = User(
            telegram_id=2001,
            balance=Decimal("1000.00"),
            nickname_set=True,
            display_name="Viewer",
        )
        session.add(viewer)
        await session.commit()

    callback = DummyCallback(2001)
    await user_handlers.watch_video_content(callback)

    text = _last_text(callback.message)
    assert "Нет доступных видео" not in text, "Не должно быть сырой старой фразы без контекста"
    assert "нет новых видео" in text.lower()
    # Главный признак исправления — есть выход:
    cbs = _markup_callbacks(callback.message)
    assert "watch_next" in cbs, "Должна быть кнопка «Смотреть дальше»"
    assert "watch_photo_content" in cbs, "Должна быть кнопка перехода к фото"

    await engine.dispose()


@pytest.mark.asyncio
async def test_watch_video_broken_video_does_not_leak_raw_error_and_gives_exit(monkeypatch):
    """Видео не отправляется → пользователь НЕ видит сырую ошибку, но может продолжить."""
    import app.user_handlers as user_handlers

    engine, Session = await _make_session()
    monkeypatch.setattr(user_handlers, "async_session", Session)

    async with Session() as session:
        uploader = User(telegram_id=2002, balance=Decimal("0.00"),
                        nickname_set=True, display_name="Uploader")
        viewer = User(telegram_id=2003, balance=Decimal("1000.00"),
                      nickname_set=True, display_name="Viewer")
        session.add_all([uploader, viewer])
        await session.flush()
        video = Video(
            uploader_user_id=uploader.id,
            content_type="video",
            telegram_file_id="file_broken",
            telegram_file_unique_id="uniq_broken",
            status="approved",
        )
        session.add(video)
        await session.commit()

    callback = DummyCallback(2003, video_raises=True)
    await user_handlers.watch_video_content(callback)

    text = _last_text(callback.message)
    # Сырая телеграм-ошибка НЕ должна попасть пользователю:
    assert "Bad Request" not in text
    assert "HTTP URL" not in text
    assert "не удалось показать" in text.lower()
    # ...зато есть выход:
    cbs = _markup_callbacks(callback.message)
    assert "watch_next" in cbs
    # И деньги за неотправленное видео вернули:
    async with Session() as session:
        from sqlalchemy import select
        views = (await session.execute(
            select(VideoView).where(VideoView.user_id == 2)
        )).scalars().all()
        assert views == [], "Просмотр неотправленного видео не должен сохраниться"

    await engine.dispose()


# ---------------------------------------------------------------------------
# ФОТО
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_watch_photo_no_content_shows_clear_message_with_exit(monkeypatch):
    """Нет доступных фото → понятный текст + кнопки продолжения."""
    import app.user_handlers as user_handlers

    engine, Session = await _make_session()
    monkeypatch.setattr(user_handlers, "async_session", Session)

    async with Session() as session:
        viewer = User(
            telegram_id=2004,
            balance=Decimal("1000.00"),
            nickname_set=True,
            display_name="Viewer",
        )
        session.add(viewer)
        await session.commit()

    callback = DummyCallback(2004)
    await user_handlers.watch_photo_content(callback)

    text = _last_text(callback.message)
    assert "нет новых фото" in text.lower()
    cbs = _markup_callbacks(callback.message)
    assert "watch_next_photo" in cbs, "Должна быть кнопка «Смотреть дальше»"
    assert "watch_video_content" in cbs, "Должна быть кнопка перехода к видео"

    await engine.dispose()


@pytest.mark.asyncio
async def test_watch_photo_broken_photo_does_not_leak_raw_error_and_gives_exit(monkeypatch):
    """Фото не отправляется → без сырой ошибки, с кнопкой продолжения."""
    import app.user_handlers as user_handlers

    engine, Session = await _make_session()
    monkeypatch.setattr(user_handlers, "async_session", Session)

    async with Session() as session:
        uploader = User(telegram_id=2005, balance=Decimal("0.00"),
                        nickname_set=True, display_name="Uploader")
        viewer = User(telegram_id=2006, balance=Decimal("1000.00"),
                      nickname_set=True, display_name="Viewer")
        session.add_all([uploader, viewer])
        await session.flush()
        photo = Video(
            uploader_user_id=uploader.id,
            content_type="photo",
            telegram_file_id="photo_broken",
            telegram_file_unique_id="uniq_photo_broken",
            status="approved",
        )
        session.add(photo)
        await session.commit()

    callback = DummyCallback(2006, photo_raises=True)
    await user_handlers.watch_photo_content(callback)

    text = _last_text(callback.message)
    assert "Bad Request" not in text
    assert "HTTP URL" not in text
    assert "не удалось показать" in text.lower()
    cbs = _markup_callbacks(callback.message)
    assert "watch_next_photo" in cbs

    await engine.dispose()


@pytest.mark.asyncio
async def test_watch_photo_daily_limit_shows_exit_to_video(monkeypatch):
    """Дневной лимит фото исчерпан → есть выход к видео (не тупик)."""
    import app.user_handlers as user_handlers

    engine, Session = await _make_session()
    monkeypatch.setattr(user_handlers, "async_session", Session)

    async with Session() as session:
        viewer = User(
            telegram_id=2007,
            balance=Decimal("1000.00"),
            nickname_set=True,
            display_name="Viewer",
            # не VIP → попадает под дневной лимит
        )
        session.add(viewer)
        await session.flush()

        # Создаём достаточно фото-просмотров, чтобы лимит был исчерпан.
        uploader = User(telegram_id=2008, balance=Decimal("0.00"),
                        nickname_set=True, display_name="Uploader")
        session.add(uploader)
        await session.flush()
        for i in range(user_handlers.DAILY_PHOTO_LIMIT + 1):
            photo = Video(
                uploader_user_id=uploader.id,
                content_type="photo",
                telegram_file_id=f"file_{i}",
                telegram_file_unique_id=f"uniq_{i}",
                status="approved",
            )
            session.add(photo)
            await session.flush()
            session.add(VideoView(user_id=viewer.id, video_id=photo.id))
        await session.commit()

    callback = DummyCallback(2007)
    await user_handlers.watch_photo_content(callback)

    text = _last_text(callback.message)
    assert "лимит" in text.lower()
    cbs = _markup_callbacks(callback.message)
    assert "watch_video_content" in cbs, "Из лимита фото должен быть выход к видео"

    await engine.dispose()
