"""Регрессионные тесты автоматических праздничных событий.

Проверяют каталог app/holidays.py и автоматику в app/services.py:
- окна событий ~неделя, без пересечений, с учётом перехода года;
- ensure_holiday_events идемпотентна и уважает переключатель;
- get_active_events не возвращает события до старта окна;
- постеры находятся на диске (banners/ и приоритетная «постеры/»);
- карточка события и приветственный блок переводятся на английский;
- пул промо-ротации несёт постер события;
- парсер даты старта для админского мастера.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.holidays import (
    HOLIDAYS,
    SPEC_BY_SLUG,
    WELCOME_BLOCK_TEMPLATE,
    build_event_welcome_block,
    holiday_window,
    holiday_windows_around,
    parse_start_date,
    resolve_poster,
)
from app.i18n import TRANSLATIONS, language_scope
from app.models import Base, Event
from app.services import (
    build_event_promo_text,
    ensure_holiday_events,
    get_active_events,
    get_auto_broadcast_pool,
    holiday_events_enabled,
    set_holiday_events_enabled,
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


def _make_event(**kwargs) -> Event:
    defaults = dict(
        name="Тест", description="описание", discount_percent=15,
        duration_days=7, applies_vip=True, applies_coins=True,
        applies_lootbox=True, applies_cases=False, image_file_id=None,
        start_date=datetime(2026, 1, 1), end_date=datetime(2026, 1, 8),
        is_active=True,
    )
    defaults.update(kwargs)
    return Event(**defaults)


# ══════════════════════════════════════════════════════════════
#  Каталог праздников: окна дат
# ══════════════════════════════════════════════════════════════

def test_every_holiday_poster_file_exists():
    """У каждого праздника из каталога постер реально лежит на диске."""
    for spec in HOLIDAYS:
        assert resolve_poster(spec.poster), f"нет постера {spec.poster} для {spec.slug}"


def test_holiday_windows_are_about_a_week_and_ordered():
    for spec in HOLIDAYS:
        start, end = holiday_window(spec, 2026)
        length = end - start
        assert timedelta(days=5) <= length <= timedelta(days=10), spec.slug
        assert start < end
        assert spec.slug in SPEC_BY_SLUG


def test_new_year_window_spans_year_boundary():
    ny = SPEC_BY_SLUG["new_year"]
    start, end = holiday_window(ny, 2026)
    assert start.year == 2026 and start.month == 12
    assert end.year == 2027 and end.month == 1


def test_holiday_windows_do_not_overlap():
    """Ни одна пара окон в одном сезоне не пересекается."""
    windows = []
    for spec in HOLIDAYS:
        for anchor in (2026, 2027):
            start, end = holiday_window(spec, anchor)
            windows.append((spec.slug, start, end))
    for i in range(len(windows)):
        for j in range(i + 1, len(windows)):
            slug_a, a0, a1 = windows[i]
            slug_b, b0, b1 = windows[j]
            assert a1 < b0 or b1 < a0, f"пересечение {slug_a} ({a0}—{a1}) и {slug_b} ({b0}—{b1})"


def test_holiday_windows_around_returns_current_and_upcoming():
    # Середина октября 2026: в пределах 30 дней Хэллоуин (25—31.10) и 4 Ноября (1—8.11).
    now = datetime(2026, 10, 19, 12, 0)
    upcoming = holiday_windows_around(now)
    slugs = [spec.slug for spec, _s, _e in upcoming]
    assert slugs == ["halloween", "nov_4"]

    # 31 декабря: новогоднее окно (30.12—06.01) уже идёт, рождественское закончилось.
    now = datetime(2026, 12, 31, 12, 0)
    slugs = [spec.slug for spec, _s, _e in holiday_windows_around(now)]
    assert slugs == ["new_year"]

    # 2 января 2027: то же новогоднее окно с якорем 2026 года.
    now = datetime(2027, 1, 2, 12, 0)
    windows = holiday_windows_around(now)
    assert [spec.slug for spec, _s, _e in windows] == ["new_year"]
    assert windows[0][1].year == 2026  # старт окна — 30.12.2026

    # 24 декабря: идёт рождественское окно и через 6 дней стартует новогоднее.
    now = datetime(2026, 12, 24, 12, 0)
    slugs = [spec.slug for spec, _s, _e in holiday_windows_around(now)]
    assert slugs == ["christmas", "new_year"]


# ══════════════════════════════════════════════════════════════
#  ensure_holiday_events: создание, идемпотентность, переключатель
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_ensure_holiday_events_creates_once(db_session):
    now = datetime(2026, 10, 19, 12, 0)
    created = await ensure_holiday_events(db_session, now=now)
    assert created == 2  # в 30-дневном окне Хэллоуин и 4 Ноября

    spec = SPEC_BY_SLUG["nov_4"]
    start, end = holiday_window(spec, 2026)
    from sqlalchemy import select
    ev = (await db_session.execute(select(Event).where(Event.slug == "nov_4"))).scalars().first()
    assert ev is not None
    assert ev.name == spec.name
    assert ev.poster_path == spec.poster
    assert ev.discount_percent == spec.discount_percent
    assert ev.start_date == start
    assert ev.end_date == end
    assert ev.is_active is True

    # Повторный вызов — идемпотентен (по маркеру и по slug+start_date).
    assert await ensure_holiday_events(db_session, now=now) == 0


@pytest.mark.asyncio
async def test_ensure_holiday_events_respects_toggle(db_session):
    now = datetime(2026, 10, 19, 12, 0)
    await set_holiday_events_enabled(db_session, False)
    assert not await holiday_events_enabled(db_session)
    assert await ensure_holiday_events(db_session, now=now) == 0

    from sqlalchemy import select
    assert (await db_session.execute(select(Event))).scalars().all() == []

    # Включение сразу создаёт предстоящие события.
    await set_holiday_events_enabled(db_session, True)
    assert await holiday_events_enabled(db_session)
    assert await ensure_holiday_events(db_session, now=now) == 2


@pytest.mark.asyncio
async def test_toggle_off_deactivates_future_auto_events_only(db_session):
    from sqlalchemy import select
    now = datetime(2026, 10, 19, 12, 0)
    await ensure_holiday_events(db_session, now=now)
    manual = _make_event(name="Ручное", slug=None, start_date=now, end_date=now + timedelta(days=3))
    db_session.add(manual)
    await db_session.commit()

    await set_holiday_events_enabled(db_session, False)
    auto = (await db_session.execute(select(Event).where(Event.slug == "nov_4"))).scalars().first()
    assert auto.is_active is False
    assert manual.is_active is True  # ручное событие переключатель не трогает

    await set_holiday_events_enabled(db_session, True)
    auto = (await db_session.execute(select(Event).where(Event.slug == "nov_4"))).scalars().first()
    assert auto.is_active is True


@pytest.mark.asyncio
async def test_ensure_closes_expired_events(db_session):
    from sqlalchemy import select
    now = datetime(2026, 10, 19, 12, 0)
    expired = _make_event(name="Старое", start_date=now - timedelta(days=30), end_date=now - timedelta(days=20))
    db_session.add(expired)
    await db_session.commit()

    await ensure_holiday_events(db_session, now=now)
    refreshed = (await db_session.execute(select(Event).where(Event.id == expired.id))).scalars().first()
    assert refreshed.is_active is False


# ══════════════════════════════════════════════════════════════
#  get_active_events: окно старта/окончания
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_get_active_events_respects_start_and_end(db_session):
    from app.models import utc_now
    now = utc_now()
    future = _make_event(name="Будущее", start_date=now + timedelta(days=2), end_date=now + timedelta(days=9))
    running = _make_event(name="Идёт", discount_percent=25, start_date=now - timedelta(days=1), end_date=now + timedelta(days=6))
    finished = _make_event(name="Прошлое", start_date=now - timedelta(days=10), end_date=now - timedelta(days=3))
    db_session.add_all([future, running, finished])
    await db_session.commit()

    active = await get_active_events(db_session)
    names = [ev.name for ev in active]
    assert names == ["Идёт"]  # будущие и истёкшие не действуют


# ══════════════════════════════════════════════════════════════
#  Постеры: приоритет папок и защита от мусора
# ══════════════════════════════════════════════════════════════

def test_resolve_poster_finds_repo_banners_and_rejects_missing():
    assert resolve_poster("new_year.jpg") is not None  # banners/new_year.jpg
    assert resolve_poster("no_such_poster.jpg") is None
    assert resolve_poster(None) is None
    # Попытка выйти за пределы папки игнорируется (берётся только имя файла).
    assert resolve_poster("../../etc/passwd") is None


def test_resolve_event_poster_uses_event_field():
    from app.holidays import resolve_event_poster
    ev = _make_event(poster_path="mar_8.jpg")
    assert resolve_event_poster(ev) is not None
    ev2 = _make_event(poster_path=None)
    assert resolve_event_poster(ev2) is None


# ══════════════════════════════════════════════════════════════
#  Локализация карточки события и приветственного блока
# ══════════════════════════════════════════════════════════════

def test_event_card_and_welcome_block_are_translated():
    spec = SPEC_BY_SLUG["new_year"]
    ev = _make_event(
        name=spec.name, description=spec.description, slug=spec.slug,
        discount_percent=spec.discount_percent,
        start_date=datetime(2026, 12, 30, 21, 0), end_date=datetime(2027, 1, 6, 20, 59),
    )
    with language_scope("ru"):
        card = build_event_promo_text(ev)
        assert "Новогодняя неделя" in card
        assert "Скидка" in card
        welcome = build_event_welcome_block(ev)
        assert "Сейчас идёт событие" in welcome
        # Скидка берётся из каталога (и совпадает с числом на постере).
        assert f"{spec.discount_percent}%" in welcome
    with language_scope("en"):
        card = build_event_promo_text(ev)
        assert "New Year week" in card
        assert "Новогодняя" not in card
        welcome = build_event_welcome_block(ev)
        assert "event is on" in welcome


def test_catalog_is_fully_translated():
    """Каждое название/описание каталога и шаблон приветствия имеют EN-пару."""
    en = TRANSLATIONS["en"]
    missing = []
    for spec in HOLIDAYS:
        for source in (spec.name, spec.description):
            if en.get(source) in (None, source):
                missing.append(source)
    if en.get(WELCOME_BLOCK_TEMPLATE) in (None, WELCOME_BLOCK_TEMPLATE):
        missing.append(WELCOME_BLOCK_TEMPLATE)
    assert not missing, f"нет EN-перевода для: {missing}"


# ══════════════════════════════════════════════════════════════
#  Пул промо-ротации: карточка события с постером
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_auto_broadcast_pool_includes_event_with_poster(db_session):
    from app.models import utc_now
    now = utc_now()
    spec = SPEC_BY_SLUG["mar_8"]
    ev = _make_event(
        name=spec.name, description=spec.description, slug=spec.slug,
        poster_path=spec.poster, discount_percent=spec.discount_percent,
        start_date=now - timedelta(days=1), end_date=now + timedelta(days=6),
    )
    db_session.add(ev)
    await db_session.commit()

    pool = await get_auto_broadcast_pool(db_session)
    event_items = [item for item in pool if item.get("image_path")]
    assert len(event_items) == 1
    assert event_items[0]["image_path"].endswith("mar_8.jpg")
    assert "Неделя к 8 Марта" in event_items[0]["text"]
    assert event_items[0]["image_file_id"] is None


# ══════════════════════════════════════════════════════════════
#  Парсер даты старта (мастер создания события)
# ══════════════════════════════════════════════════════════════

def test_parse_start_date_variants():
    now = datetime(2026, 10, 19, 12, 0)
    assert parse_start_date("сейчас", now) is None
    assert parse_start_date("now", now) is None
    assert parse_start_date("", now) is None

    # ДД.ММ без года — ближайшая будущая дата; 00:00 MSK = 21:00 UTC накануне.
    got = parse_start_date("25.12", now)
    assert got == datetime(2026, 12, 24, 21, 0)

    # Прошедшая в этом году дата без года уезжает на следующий год.
    got = parse_start_date("01.05", now)
    assert got == datetime(2027, 4, 30, 21, 0)

    # Полная дата.
    got = parse_start_date("01.05.2028", now)
    assert got == datetime(2028, 4, 30, 21, 0)
    got = parse_start_date("2028-05-01", now)
    assert got == datetime(2028, 4, 30, 21, 0)

    with pytest.raises(ValueError):
        parse_start_date("когда-нибудь", now)
    with pytest.raises(ValueError):
        parse_start_date("99.99", now)
