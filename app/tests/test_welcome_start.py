"""Регрессионные тесты приветствия /start.

Проверяют, что при /start пользователь получает:
* штатный баннер `app/banner.jpg` (если админ не загрузил свой);
* приветствие с именем и балансом + презентационный текст проекта;
* перевод презентационного блока на английский;
* подсказку про ник, кастомный текст из админки и блок события — без
  превышения лимита Telegram на подпись к фото (хвост уходит отдельным
  сообщением, а не ломает отправку картинки).
"""
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.i18n import t
from app.models import Base, User, utc_now
from app.services import set_setting
from app.user_handlers import (
    WELCOME_BANNER_PATH,
    WELCOME_CAPTION_LIMIT,
    build_welcome_blocks,
    send_welcome_banner,
    split_welcome_blocks,
)


# Текст презентации проекта — цитата из ТЗ на экран /start.
PITCH_RU_PARTS = (
    "наиболее продвинутый и необычный проект в нише обмена видео",
    "отзывчивая и живая администрация",
    "Бот сделан от людей для людей",
    "администраторами (их всего 2)",
    "Расслабьтесь и добро пожаловать в Wseksbot! 😌📣",
)


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as session:
        yield session
    await engine.dispose()


def _make_user(**kwargs) -> User:
    defaults = dict(
        telegram_id=1001,
        username="viperr",
        first_name="Viperr",
        display_name="Viperr",
        nickname_set=True,
        balance=Decimal("687.50"),
        language="ru",
        agreed_to_rules=True,
        status="active",
        created_at=utc_now() - timedelta(days=2),
        vip_until=None,
    )
    defaults.update(kwargs)
    return User(**defaults)


def test_welcome_pitch_translated_to_both_languages():
    ru = t("ru", "welcome.pitch")
    en = t("en", "welcome.pitch")
    for part in PITCH_RU_PARTS:
        assert part in ru
    assert ru != en
    assert "Wseksbot" in en
    assert "Wseksbot" in ru


def test_welcome_greeting_has_name_and_balance():
    ru = t("ru", "welcome.greeting", name="Viperr", vip="", balance=Decimal("687.50"))
    assert "Viperr" in ru
    assert "687.50" in ru
    # Имя и баланс выделены жирным — экран читается как в ТЗ.
    assert "<b>Viperr</b>" in ru
    assert "<b>687.50</b>" in ru


async def test_build_welcome_blocks_contains_greeting_and_pitch(db_session):
    user = _make_user()
    db_session.add(user)
    await db_session.commit()

    blocks, poster = await build_welcome_blocks(db_session, user, "ru")
    assert poster is None
    assert "Viperr" in blocks[0]
    assert "687.50" in blocks[0]
    for part in PITCH_RU_PARTS:
        assert part in blocks[1]
    # Без ника — только приветствие + презентация.
    assert len(blocks) == 2


async def test_build_welcome_blocks_pitch_is_english_for_en_user(db_session):
    user = _make_user(language="en")
    db_session.add(user)
    await db_session.commit()

    blocks, _ = await build_welcome_blocks(db_session, user, "en")
    assert "video exchange niche" in blocks[1]
    assert "Wseksbot" in blocks[1]
    assert "проект в нише" not in blocks[1]


async def test_build_welcome_blocks_adds_nickname_hint_and_custom_text(db_session):
    user = _make_user(nickname_set=False, display_name=None)
    db_session.add(user)
    await set_setting(db_session, "welcome_text", "Специальное предложение дня!")
    await db_session.commit()

    blocks, _ = await build_welcome_blocks(db_session, user, "ru")
    assert any("ник" in b for b in blocks)
    assert "Специальное предложение дня!" in blocks


def test_split_welcome_blocks_keeps_caption_within_limit():
    blocks = ["Приветствие", "Презентация", "Х" * 1200]
    caption, rest = split_welcome_blocks(blocks)
    assert len(caption) <= WELCOME_CAPTION_LIMIT
    assert rest == ["Х" * 1200]
    assert "Приветствие" in caption and "Презентация" in caption


def test_split_welcome_blocks_no_overflow_for_short_text():
    blocks = ["Один", "Два"]
    caption, rest = split_welcome_blocks(blocks)
    assert caption == "Один\n\nДва"
    assert rest == []


async def test_send_welcome_banner_posts_default_banner_with_pitch(db_session):
    """Главный сценарий: /start отдаёт app/banner.jpg с текстом из ТЗ."""
    import os

    assert os.path.exists(WELCOME_BANNER_PATH), (
        "Штатный баннер приветствия пропал — /start уйдёт текстом без картинки"
    )

    user = _make_user(created_at=utc_now() - timedelta(hours=3))
    db_session.add(user)
    await db_session.commit()

    target = SimpleNamespace(
        answer_photo=AsyncMock(),
        answer=AsyncMock(),
    )

    await send_welcome_banner(target, db_session, user)

    assert target.answer_photo.await_count == 1
    kwargs = target.answer_photo.await_args.kwargs
    caption = kwargs["caption"]
    assert kwargs["parse_mode"] == "HTML"
    assert len(caption) <= WELCOME_CAPTION_LIMIT
    for part in PITCH_RU_PARTS:
        assert part in caption
    assert "Viperr" in caption
    # Меню прикладывается к самому приветствию (хвоста нет).
    assert kwargs["reply_markup"] is not None
    # Стартовый лутбокс предлагается отдельным сообщением.
    assert target.answer.await_count >= 1
    lootbox_text = target.answer.await_args_list[0].args[0]
    assert "лутбокс" in lootbox_text.lower()


async def test_send_welcome_banner_sends_overflow_as_separate_message(db_session):
    """Длинный текст из админки не ломает отправку картинки."""
    user = _make_user()
    db_session.add(user)
    await set_setting(db_session, "welcome_text", "Ы" * 1500)
    await db_session.commit()

    target = SimpleNamespace(
        answer_photo=AsyncMock(),
        answer=AsyncMock(),
    )

    await send_welcome_banner(target, db_session, user)

    assert target.answer_photo.await_count == 1
    photo_kwargs = target.answer_photo.await_args.kwargs
    assert len(photo_kwargs["caption"]) <= WELCOME_CAPTION_LIMIT
    # Кнопки меню уезжают в последнее сообщение, а не теряются.
    assert photo_kwargs["reply_markup"] is None
    answer_calls = target.answer.await_args_list
    assert any("Ы" * 100 in call.args[0] for call in answer_calls)
    assert any(call.kwargs.get("reply_markup") is not None for call in answer_calls)


async def test_admin_banner_from_settings_wins_over_default_file(db_session):
    user = _make_user()
    db_session.add(user)
    await set_setting(db_session, "welcome_banner_id", "AgACAgIAAxkBAAI")
    await db_session.commit()

    target = SimpleNamespace(answer_photo=AsyncMock(), answer=AsyncMock())
    await send_welcome_banner(target, db_session, user)

    assert target.answer_photo.await_args.kwargs["photo"] == "AgACAgIAAxkBAAI"
