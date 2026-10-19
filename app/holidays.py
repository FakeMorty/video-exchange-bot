"""Каталог праздничных событий и их автоматическое расписание.

Бот сам создаёт праздничные события по этому каталогу: каждое событие
создаётся заранее (за 30 дней до старта, см. `ensure_holiday_events` в
`app/services.py`), в свою дату старта автоматически «просыпается» и длится
около недели. Всё это время в боте автоматически:

* действуют скидки события (магазин VIP/монет, бейджи «АКЦИЯ»);
* постер события заменяет приветственный баннер (`send_welcome_banner`);
* карточка события появляется в пуле авто-ротации рекламы и в рекламе
  между видео (`_show_ad_or_event`);
* к тексту приветствия добавляется праздничный блок;
* в день старта уходит разовая рассылка (polling-режим, см. worker).

Постеры ищутся в папке `постеры/` (приоритет), затем в `banners/`.
Имена файлов заданы в каталоге (поле `poster`): чтобы обновить картинку,
достаточно положить файл с тем же именем в `постеры/` — код трогать не нужно.

Даты заданы по Москве (MSK, UTC+3): событие начинается в 00:00 MSK дня
`start_md` и заканчивается в 23:59 MSK дня `end_md`. В БД хранится naive-UTC
(как везде в боте, см. `app.models.utc_now`).

Названия и описания событий — русские строки; английский перевод добавляется
в `app/i18n_en.py` по ключу-исходнику и подхватывается через `t()` в местах
отображения (рассылки, реклама, приветствие).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.i18n import t

# Москва: даты праздников заданы в локальном времени, а не UTC.
MSK = timezone(timedelta(hours=3))

# Где лежат постеры: пользовательская папка «постеры» приоритетнее
# репозиторного banners/ (можно переопределить картинку без смены кода).
POSTER_DIRS = ("постеры", "banners")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class HolidaySpec:
    """Один праздник из каталога: окно дат, скидка и постер."""

    slug: str                 # стабильный ключ (дедупликация, переводы)
    name: str                 # название события (RU; EN — через i18n_en)
    description: str          # описание для карточек/рассылок (RU)
    start_md: tuple[int, int]  # (месяц, день) начала окна по MSK
    end_md: tuple[int, int]    # (месяц, день) конца окна по MSK
    discount_percent: int      # скидка на время события
    poster: str                # имя файла постера в «постеры/» или banners/
    applies_vip: bool = True
    applies_coins: bool = True
    applies_lootbox: bool = True


# Окна подобраны так, чтобы события не пересекались и длились ~неделю,
# а праздник попадал в конец окна (скидки действуют до и в сам день).
HOLIDAYS: list[HolidaySpec] = [
    HolidaySpec(
        slug="christmas",
        name="🎅 Рождественская распродажа",
        description="Рождественская распродажа: праздничные скидки в магазине — успей до конца недели!",
        start_md=(12, 22), end_md=(12, 29),
        discount_percent=15, poster="christmas.jpg",
    ),
    HolidaySpec(
        slug="new_year",
        name="🎄 Новогодняя неделя",
        description="Новогодняя неделя в боте! Запасайся монетами, забирай VIP по праздничной цене и открывай лутбоксы — скидки всю неделю.",
        start_md=(12, 30), end_md=(1, 6),
        discount_percent=20, poster="new_year.jpg",
    ),
    HolidaySpec(
        slug="feb_23",
        name="⭐ Неделя к 23 Февраля",
        description="Праздничная неделя ко Дню защитника Отечества: скидки на всё в магазине — порадуй себя и друзей!",
        start_md=(2, 17), end_md=(2, 24),
        discount_percent=15, poster="feb_23.jpg",
    ),
    HolidaySpec(
        slug="mar_8",
        name="🌷 Неделя к 8 Марта",
        description="Праздничная неделя к Международному женскому дню: весенние скидки на всё в магазине!",
        start_md=(3, 2), end_md=(3, 9),
        discount_percent=15, poster="mar_8.jpg",
    ),
    HolidaySpec(
        slug="apr_1",
        name="😂 Неделя смеха",
        description="Первоапрельская неделя: несерьёзные цены — серьёзные скидки на всё в магазине!",
        start_md=(3, 29), end_md=(4, 5),
        discount_percent=10, poster="apr_1.jpg",
    ),
    HolidaySpec(
        slug="may_1",
        name="🌸 Майские скидки",
        description="Неделя к Празднику Весны и Труда: запасайся монетами и VIP на праздниках по сниженным ценам!",
        start_md=(4, 25), end_md=(5, 2),
        discount_percent=15, poster="may_1.jpg",
    ),
    HolidaySpec(
        slug="may_9",
        name="🎖 Неделя к 9 Мая",
        description="Праздничная неделя ко Дню Победы: скидки в магазине — с праздником!",
        start_md=(5, 3), end_md=(5, 10),
        discount_percent=15, poster="may_9.jpg",
    ),
    HolidaySpec(
        slug="jun_1",
        name="☀️ Летняя неделя скидок",
        description="Неделя к 1 июня: летние скидки на всё — начни лето с обновками в боте!",
        start_md=(5, 26), end_md=(6, 2),
        discount_percent=10, poster="jun_1.jpg",
    ),
    HolidaySpec(
        slug="sep_1",
        name="📚 Неделя к 1 Сентября",
        description="Неделя ко Дню знаний: скидки на всё — начни сезон с обновками!",
        start_md=(8, 26), end_md=(9, 2),
        discount_percent=10, poster="sep_1.jpg",
    ),
    HolidaySpec(
        slug="nov_4",
        name="🎆 Неделя к 4 Ноября",
        description="Праздничная неделя ко Дню народного единства: осенние скидки в магазине!",
        start_md=(10, 29), end_md=(11, 5),
        discount_percent=15, poster="nov_4.jpg",
    ),
]

SPEC_BY_SLUG: dict[str, HolidaySpec] = {spec.slug: spec for spec in HOLIDAYS}

# Шаблон праздничного блока, который добавляется к приветствию на время события.
WELCOME_BLOCK_TEMPLATE = (
    '🎉 <b>Сейчас идёт событие «{name}»</b>\n'
    '🔥 Скидка <b>{discount}%</b> действует до {end} — успей в 🛍 Магазин!'
)


def _msk_to_utc_naive(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """00:00 (или 23:59) MSK указанной даты -> naive-UTC (формат хранения в БД)."""
    dt = datetime(year, month, day, hour, minute, tzinfo=MSK)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def holiday_window(spec: HolidaySpec, anchor_year: int) -> tuple[datetime, datetime]:
    """Окно события (naive-UTC start/end) для года, в котором оно начинается.

    `anchor_year` — год дня старта. Если окно переходит через Новый год
    (конец раньше начала по календарю, например 30.12 -> 06.01), год конца
    сдвигается на +1.
    """
    start = _msk_to_utc_naive(anchor_year, spec.start_md[0], spec.start_md[1])
    end_year = anchor_year
    if spec.end_md < spec.start_md:
        end_year += 1
    end = _msk_to_utc_naive(end_year, spec.end_md[0], spec.end_md[1], hour=23, minute=59)
    return start, end


def holiday_windows_around(
    now: datetime,
    lookahead_days: int = 30,
) -> list[tuple[HolidaySpec, datetime, datetime]]:
    """Экземпляры праздников, актуальные сейчас: идущие и стартующие в пределах
    `lookahead_days`. Учитывает переход года (якорь — год дня старта)."""
    horizon = now + timedelta(days=lookahead_days)
    out: list[tuple[HolidaySpec, datetime, datetime]] = []
    seen: set[tuple[str, str]] = set()
    for spec in HOLIDAYS:
        for anchor_year in (now.year - 1, now.year, now.year + 1):
            start, end = holiday_window(spec, anchor_year)
            if end < now or start > horizon:
                continue
            key = (spec.slug, start.isoformat())
            if key in seen:
                continue
            seen.add(key)
            out.append((spec, start, end))
    out.sort(key=lambda item: item[1])
    return out


def resolve_poster(filename: str | None) -> str | None:
    """Путь к постеру на диске или None.

    Порядок поиска: `постеры/<имя>` (приоритет) -> `banners/<имя>`; каждая
    папка проверяется относительно cwd и корня репозитория (на Vercel/в
    Docker рабочая директория может отличаться).
    """
    if not filename:
        return None
    name = Path(str(filename)).name  # защита от выхода за пределы папки
    for folder in POSTER_DIRS:
        for base in (Path(folder), _PROJECT_ROOT / folder):
            candidate = base / name
            if candidate.is_file():
                return str(candidate)
    return None


def resolve_event_poster(event) -> str | None:
    """Постер события (Event.poster_path из каталога) или None, если файла нет."""
    return resolve_poster(getattr(event, "poster_path", None))


def build_event_welcome_block(event) -> str:
    """Праздничный блок для приветствия: название, скидка и дата окончания."""
    name = t(getattr(event, "name", "") or "")
    end_text = event.end_date.strftime("%d.%m")
    return t(
        WELCOME_BLOCK_TEMPLATE,
        name=name,
        discount=event.discount_percent,
        end=end_text,
    )


def parse_start_date(text: str, now: datetime) -> datetime | None:
    """Парсинг даты старта события в админском мастере.

    Принимает «сейчас» / «now» / пусто -> None (старт немедленно),
    а также «ДД.ММ», «ДД.ММ.ГГГГ», «ГГГГ-ММ-ДД» -> naive-UTC для 00:00 MSK
    указанной даты. Дата без года берётся в ближайшем будущем. На мусор
    бросает ValueError — хендлер переспрашивает.
    """
    raw = (text or "").strip().lower()
    if raw in ("", "сейчас", "now", "сегодня", "today", "0"):
        return None
    parsed: datetime | None = None
    has_year = False
    for fmt in ("%d.%m.%Y", "%d.%m", "%Y-%m-%d", "%d/%m/%Y", "%d/%m"):
        try:
            parsed = datetime.strptime(raw, fmt)
            has_year = "%Y" in fmt
            break
        except ValueError:
            continue
    if parsed is None:
        raise ValueError(raw)
    if not has_year:
        # Год не указан — ближайшая будущая дата (сегодня тоже подходит).
        parsed = parsed.replace(year=now.year)
        if parsed.date() < now.date():
            parsed = parsed.replace(year=now.year + 1)
    return _msk_to_utc_naive(parsed.year, parsed.month, parsed.day)


def event_poster_exists(spec_or_filename) -> bool:
    """Есть ли постер на диске (для диагностики/админ-панели)."""
    filename = getattr(spec_or_filename, "poster", spec_or_filename)
    return resolve_poster(filename) is not None


# Небольшая самодиагностика: python -m app.holidays покажет ближайшее расписание.
if __name__ == "__main__":  # pragma: no cover
    now = datetime.utcnow()
    print(f"Ближайшие события (от {now:%d.%m.%Y}):")
    for spec, start, end in holiday_windows_around(now, lookahead_days=365):
        poster = "есть" if event_poster_exists(spec) else "НЕТ ФАЙЛА"
        print(
            f"  {start:%d.%m.%Y} — {end:%d.%m.%Y} | {spec.name} "
            f"| скидка {spec.discount_percent}% | постер {spec.poster} ({poster})"
        )
