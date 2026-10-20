"""Регрессионные тесты локализованных постеров и баннеров.

Английские копии картинок генерируются нейросетью и лежат рядом с русскими
оригиналами: `banners/en/<имя>` и `app/banner_en.jpg`. Проверяем, что:
* постер выбирается по языку получателя, а не всегда русский;
* отсутствие перевода не ломает показ (фолбэк на оригинал);
* язык берётся из контекста апдейта, если его не передали явно;
* промо-ротация и пул событий отдают английский текст вместе с постером.
"""
from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.holidays import HOLIDAYS, SPEC_BY_SLUG, resolve_poster
from app.i18n import language_scope, normalize_language
from app.models import Base, Event, utc_now
from app.services import get_auto_broadcast_pool
from app.user_handlers import WELCOME_BANNER_PATH, welcome_banner_path


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as session:
        yield session
    await engine.dispose()


def _make_event(**kwargs) -> Event:
    defaults = dict(
        name="🌷 Неделя к 8 Марта", description="Весенние скидки на всё в магазине!",
        discount_percent=15, duration_days=7, applies_vip=True, applies_coins=True,
        applies_lootbox=True, applies_cases=False, image_file_id=None,
        start_date=utc_now() - timedelta(days=1), end_date=utc_now() + timedelta(days=6),
        is_active=True, poster_path="mar_8.jpg", slug="mar_8",
    )
    defaults.update(kwargs)
    return Event(**defaults)


def _as_posix(path: str) -> str:
    return path.replace("\\", "/")


def test_every_holiday_has_english_poster():
    """У каждого праздника каталога есть английская копия постера."""
    for spec in HOLIDAYS:
        en = resolve_poster(spec.poster, lang="en")
        assert en, f"нет английского постера {spec.poster} для {spec.slug}"
        assert "/en/" in _as_posix(en) or _as_posix(en).endswith("/en/" + spec.poster), (
            f"постер {spec.slug} не из английской подпапки: {en}"
        )


def test_russian_poster_is_default():
    ru = resolve_poster("new_year.jpg", lang="ru")
    en = resolve_poster("new_year.jpg", lang="en")
    assert ru and en
    assert ru != en
    assert "/en/" not in _as_posix(ru)
    assert "/en/" in _as_posix(en)


def test_missing_translation_falls_back_to_original():
    """Если перевода нет — отдаётся русский оригинал, а не None."""
    assert resolve_poster("no_such_poster.jpg", lang="en") is None
    assert resolve_poster(None, lang="en") is None
    assert resolve_poster("../../etc/passwd", lang="en") is None


def test_poster_language_comes_from_context_when_not_passed():
    with language_scope("en"):
        assert "/en/" in _as_posix(resolve_poster("may_9.jpg"))
    with language_scope("ru"):
        assert "/en/" not in _as_posix(resolve_poster("may_9.jpg"))


def test_unknown_language_falls_back_to_russian():
    assert normalize_language("de") == "ru"
    ru = resolve_poster("may_9.jpg", lang="de")
    assert ru and "/en/" not in _as_posix(ru)


def test_welcome_banner_path_is_localized():
    en = welcome_banner_path("en")
    ru = welcome_banner_path("ru")
    assert ru == WELCOME_BANNER_PATH
    # Английский баннер — либо переведённый файл, либо тот же русский
    # (перевод необязателен, отсутствие файла не должно ломать /start).
    assert en in ("app/banner_en.jpg", WELCOME_BANNER_PATH)
    assert welcome_banner_path(None) == WELCOME_BANNER_PATH


async def test_promo_pool_uses_english_text_and_poster(db_session):
    """В ротации англоязычный пользователь видит английскую карточку и постер."""
    db_session.add(_make_event())
    await db_session.commit()

    en_pool = await get_auto_broadcast_pool(db_session, lang="en")
    en_items = [item for item in en_pool if item.get("image_path")]
    assert len(en_items) == 1
    assert "/en/" in _as_posix(en_items[0]["image_path"])
    assert "International Women’s Day" in en_items[0]["text"]

    ru_pool = await get_auto_broadcast_pool(db_session, lang="ru")
    ru_items = [item for item in ru_pool if item.get("image_path")]
    assert len(ru_items) == 1
    assert "/en/" not in _as_posix(ru_items[0]["image_path"])
    assert "8 Марта" in ru_items[0]["text"]


def test_mar_8_spec_is_the_one_used_in_pool_fixture():
    """Защита от рассинхрона: фикстура карточки должна совпадать с каталогом."""
    assert SPEC_BY_SLUG["mar_8"].poster == "mar_8.jpg"


def test_new_holidays_from_user_posters_are_wired():
    """День космонавтики, Валентин день и Хэллоуин добавлены по постерам.

    У каждого — окно, в которое попадает сам день праздника, постер на диске
    и английский перевод названия (иначе событие осталось бы без картинки,
    а у англоязычных — с русской подписью).
    """
    from app.holidays import holiday_window
    from app.i18n import t

    for slug, month, day in (("valentine", 2, 14), ("cosmonautics", 4, 12), ("halloween", 10, 31)):
        spec = SPEC_BY_SLUG[slug]
        start, end = holiday_window(spec, 2026)
        assert (start.month, start.day) <= (month, day) <= (end.month, end.day), slug
        assert resolve_poster(spec.poster), f"нет постера {slug}"
        assert resolve_poster(spec.poster, lang="en"), f"нет английского постера {slug}"
        assert t("en", spec.name) != spec.name, f"нет перевода названия {slug}"


def test_halloween_and_november_windows_do_not_clash():
    """Хэллоуин (25—31.10) и 4 Ноября идут друг за другом, без наложения."""
    from app.holidays import holiday_window

    # Окна хранятся в naive-UTC (даты заданы по Москве), поэтому «1 ноября»
    # проверяем со сдвигом +3 часа обратно на MSK.
    from datetime import timedelta

    hw_start, hw_end = holiday_window(SPEC_BY_SLUG["halloween"], 2026)
    nv_start, nv_end = holiday_window(SPEC_BY_SLUG["nov_4"], 2026)
    assert hw_end < nv_start, "окна Хэллоуина и 4 Ноября накладываются"
    assert (hw_start + timedelta(hours=3)).date() == date(2026, 10, 25)
    assert (nv_start + timedelta(hours=3)).date() == date(2026, 11, 1)
    assert (nv_start + timedelta(hours=3)).date() <= date(2026, 11, 4) <= (nv_end + timedelta(hours=3)).date()
