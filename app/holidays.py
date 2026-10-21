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
Для английского интерфейса постер берётся из подпапки `en/` той же папки
(`banners/en/<имя>`), а если её нет — русский оригинал.

Даты заданы по Москве (MSK, UTC+3): событие начинается в 00:00 MSK дня
`start_md` и заканчивается в 23:59 MSK дня `end_md`. В БД хранится naive-UTC
(как везде в боте, см. `app.models.utc_now`).

Названия и описания событий — русские строки; английский перевод добавляется
в `app/i18n_en.py` по ключу-исходнику и подхватывается через `t()` в местах
отображения (рассылки, реклама, приветствие).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from app.i18n import DEFAULT_LANGUAGE, current_language, normalize_language, t

# Москва: даты праздников заданы в локальном времени, а не UTC.
MSK = timezone(timedelta(hours=3))

# Где лежат постеры: пользовательская папка «постеры» приоритетнее
# репозиторного banners/ (можно переопределить картинку без смены кода).
POSTER_DIRS = ("постеры", "banners")

# Подпапки с переводами постеров: `постеры/en/<имя>`, `banners/en/<имя>`.
# Английские копии генерируются нейросетью из русских оригиналов; если для
# языка файла нет, показывается русский постер (фолбэк в resolve_poster).
LOCALIZED_POSTER_DIRS = {"en": "en"}

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class HolidaySpec:
    """Один праздник из каталога: окно дат, скидка и постер."""

    slug: str                 # стабильный ключ (дедупликация, переводы)
    name: str                 # название события (RU; EN — через i18n_en)
    description: str          # описание для карточек/рассылок (RU)
    start_md: tuple[int, int] | None = None  # (месяц, день) начала окна по локальной зоне
    end_md: tuple[int, int] | None = None    # (месяц, день) конца окна по локальной зоне
    discount_percent: int = 0      # скидка на время события
    poster: str = ""                # имя файла постера в «постеры/» или banners/
    applies_vip: bool = True
    applies_coins: bool = True
    applies_lootbox: bool = True
    # Новые поля для региональных календарей:
    date_rule: Callable[[int], date] | None = None  # фиксированная дата праздника -> date
    window_days: int = 7           # длительность окна (дней, праздник в конце)
    tz: str = "Europe/Moscow"      # IANA зона для расчёта окна
    window_anchor: str = "end"  # "end" = праздник в конце окна, "start" = праздник в начале окна

    def __post_init__(self):
        # Для совместимости со старыми вызовами где start_md/end_md обязательны,
        # но новые floating-праздники их не имеют.
        pass


# Окна подобраны так, чтобы события не пересекались и длились ~неделю,
# а праздник попадал в конец окна (скидки действуют до и в сам день).
#
# ВАЖНО: `discount_percent` — ровно то число, что напечатано на основном
# постере праздника в папке «постеры/» (прочитано с картинок). Если менять
# скидку здесь, постер надо перерисовывать вместе с ней — иначе бот в
# сообщении обещает одно, а пользователь видит на картинке другое.
# Рассинхрон ловит тест test_catalog_discounts_match_posters.
HOLIDAYS: list[HolidaySpec] = [
    HolidaySpec(
        slug="christmas",
        name="🎅 Рождественская распродажа",
        description="Рождественская распродажа: праздничные скидки в магазине — успей до конца недели!",
        start_md=(12, 22), end_md=(12, 29),
        discount_percent=25, poster="christmas.jpg",
    ),
    HolidaySpec(
        slug="new_year",
        name="🎄 Новогодняя неделя",
        description="Новогодняя неделя в боте! Запасайся монетами, забирай VIP по праздничной цене и открывай лутбоксы — скидки всю неделю.",
        start_md=(12, 30), end_md=(1, 6),
        discount_percent=30, poster="new_year.jpg",
    ),
    HolidaySpec(
        slug="valentine",
        name="💝 Неделя ко Дню святого Валентина",
        description="Неделя ко Дню всех влюблённых: скидки на всё в магазине — порадуй себя и того, кто тебе дорог!",
        start_md=(2, 7), end_md=(2, 14),
        discount_percent=25, poster="valentine.jpg",
    ),
    HolidaySpec(
        slug="feb_23",
        name="⭐ Неделя к 23 Февраля",
        description="Праздничная неделя ко Дню защитника Отечества: скидки на всё в магазине — порадуй себя и друзей!",
        start_md=(2, 17), end_md=(2, 24),
        discount_percent=23, poster="feb_23.jpg",
    ),
    HolidaySpec(
        slug="mar_8",
        name="🌷 Неделя к 8 Марта",
        description="Праздничная неделя к Международному женскому дню: весенние скидки на всё в магазине!",
        start_md=(3, 2), end_md=(3, 9),
        discount_percent=25, poster="mar_8.jpg",
    ),
    HolidaySpec(
        slug="apr_1",
        name="😂 Неделя смеха",
        description="Первоапрельская неделя: несерьёзные цены — серьёзные скидки на всё в магазине!",
        start_md=(3, 29), end_md=(4, 5),
        discount_percent=15, poster="apr_1.jpg",
    ),
    HolidaySpec(
        slug="cosmonautics",
        name="🚀 Неделя ко Дню космонавтики",
        description="Неделя ко Дню космонавтики: скидки на всё — взлетаем вместе с ценами вниз!",
        start_md=(4, 6), end_md=(4, 13),
        discount_percent=12, poster="cosmonautics.jpg",
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
        discount_percent=45, poster="may_9.jpg",
    ),
    HolidaySpec(
        slug="jun_1",
        name="☀️ Летняя неделя скидок",
        description="Неделя к 1 июня: летние скидки на всё — начни лето с обновками в боте!",
        start_md=(5, 26), end_md=(6, 2),
        discount_percent=15, poster="jun_1.jpg",
    ),
    HolidaySpec(
        slug="sep_1",
        name="📚 Неделя к 1 Сентября",
        description="Неделя ко Дню знаний: скидки на всё — начни сезон с обновками!",
        start_md=(8, 26), end_md=(9, 2),
        discount_percent=20, poster="sep_1.jpg",
    ),
    HolidaySpec(
        slug="halloween",
        name="🎃 Неделя Хэллоуина",
        description="Жуткая неделя скидок: Хэллоуин в боте — монеты и VIP по сниженным ценам!",
        start_md=(10, 25), end_md=(10, 31),
        discount_percent=50, poster="halloween.jpg",
    ),
    HolidaySpec(
        # Окно сдвинуто на 1–8 ноября: раньше было 29.10–5.11 и пересекалось
        # с Хэллоуином (25–31 октября), из-за чего события накладывались.
        slug="nov_4",
        name="🎆 Неделя к 4 Ноября",
        description="Праздничная неделя ко Дню народного единства: осенние скидки в магазине!",
        start_md=(11, 1), end_md=(11, 8),
        discount_percent=20, poster="nov_4.jpg",
    ),
]

SPEC_BY_SLUG: dict[str, HolidaySpec] = {spec.slug: spec for spec in HOLIDAYS}

# Шаблон праздничного блока, который добавляется к приветствию на время события.
WELCOME_BLOCK_TEMPLATE = (
    '🎉 <b>Сейчас идёт событие «{name}»</b>\n'
    '🔥 Скидка <b>{discount}%</b> действует до {end} — успей в 🛍 Магазин!'
)


# ─────────────────────────────────────────────────────────────
# Региональная система: часовые пояса, плавающие даты, календари
# ─────────────────────────────────────────────────────────────

# Регион -> IANA зона (для расчёта локальных окон)
REGION_TZ: dict[str, str] = {
    "RU": "Europe/Moscow",
    "US": "America/New_York",
    "GB": "Europe/London",
    "AU": "Australia/Sydney",
    "CA": "America/Toronto",
    "NZ": "Pacific/Auckland",
    "ES": "Europe/Madrid",
    "BR": "America/Sao_Paulo",
    "PT": "Europe/Lisbon",
}

# Язык -> регион по умолчанию (первый заход, см. постановку)
DEFAULT_CALENDAR_BY_LANG: dict[str, str] = {
    "en": "US",
    "es": "ES",
    "pt": "BR",
    "ru": "RU",
}

# ── helpers для плавающих дат ─────────────────────────────────

def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """n-й weekday месяца (weekday 0=Mon .. 6=Sun). n>=1. Для last используйте n=-1."""
    if n > 0:
        # первый день месяца
        d = date(year, month, 1)
        # сдвиг до нужного weekday
        offset = (weekday - d.weekday()) % 7
        d = d + timedelta(days=offset)
        d = d + timedelta(days=7 * (n - 1))
        return d
    else:
        # последний
        import calendar
        last_day = calendar.monthrange(year, month)[1]
        d = date(year, month, last_day)
        offset = (d.weekday() - weekday) % 7
        return d - timedelta(days=offset)


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    return _nth_weekday_of_month(year, month, weekday, -1)


def easter_gregorian(year: int) -> date:
    """Григорианская Пасха (Anonymous Gregorian algorithm)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


# Конкретные правила для праздников (возвращают дату праздника)

def thanksgiving_us_date(year: int) -> date:
    # 4-й четверг ноября
    return _nth_weekday_of_month(year, 11, 3, 4)  # Thu=3


def thanksgiving_ca_date(year: int) -> date:
    # 2-й понедельник октября
    return _nth_weekday_of_month(year, 10, 0, 2)


def mothers_day_br_date(year: int) -> date:
    # 2-е воскресенье мая
    return _nth_weekday_of_month(year, 5, 6, 2)


def carnival_date(year: int) -> date:
    # Карнавал (вторник) = Пасха -47 дней
    return easter_gregorian(year) - timedelta(days=47)


def semana_santa_date(year: int) -> date:
    # Семана Санта — Пасха (воскресенье)
    return easter_gregorian(year)


# Матарики (NZ) — плавающий, июнь–июль, реальные даты 2024-2031
_MATARIKI_DATES: dict[int, date] = {
    2024: date(2024, 6, 28),
    2025: date(2025, 6, 20),
    2026: date(2026, 7, 10),
    2027: date(2027, 6, 25),
    2028: date(2028, 7, 14),
    2029: date(2029, 7, 6),
    2030: date(2030, 6, 21),
    2031: date(2031, 6, 27),
}


def matariki_date(year: int) -> date:
    if year in _MATARIKI_DATES:
        return _MATARIKI_DATES[year]
    # fallback: 3-я пятница июня
    return _nth_weekday_of_month(year, 6, 4, 3)


def black_friday_date(year: int) -> date:
    return thanksgiving_us_date(year) + timedelta(days=1)


# ── Региональные календари ───────────────────────────────────

def _make_calendar(region: str, specs: list[HolidaySpec]) -> list[HolidaySpec]:
    """Проставляет tz по региону, если не задан."""
    out = []
    tz = REGION_TZ.get(region, "UTC")
    for s in specs:
        if s.tz != "Europe/Moscow" or region == "RU":
            out.append(s)
        else:
            # для новых регионов выставляем их tz, если не переопределён
            out.append(HolidaySpec(
                slug=s.slug, name=s.name, description=s.description,
                start_md=s.start_md, end_md=s.end_md,
                discount_percent=s.discount_percent, poster=s.poster,
                applies_vip=s.applies_vip, applies_coins=s.applies_coins,
                applies_lootbox=s.applies_lootbox,
                date_rule=s.date_rule, window_days=s.window_days, tz=tz,
            ))
    return out


# US — 4 праздника (используем halloween как общий, но он уже есть)
_US_SPECS: list[HolidaySpec] = [
    HolidaySpec(
        slug="us_independence",
        name="🎆 Неделя ко Дню независимости США",
        description="Неделя ко Дню независимости США: праздничные скидки — celebrate freedom with discounts!",
        start_md=(6, 28), end_md=(7, 4),
        discount_percent=30, poster="us_independence.jpg",
        tz=REGION_TZ["US"],
    ),
    HolidaySpec(
        slug="halloween",
        name="🎃 Неделя Хэллоуина",
        description="Жуткая неделя скидок: Хэллоуин в боте — монеты и VIP по сниженным ценам!",
        start_md=(10, 25), end_md=(10, 31),
        discount_percent=50, poster="halloween.jpg",
        tz=REGION_TZ["US"],
    ),
    HolidaySpec(
        slug="us_thanksgiving",
        name="🦃 Неделя Дня благодарения",
        description="Неделя Дня благодарения: скидки и подарки — время благодарить и экономить!",
        discount_percent=25, poster="us_thanksgiving.jpg",
        tz=REGION_TZ["US"],
        date_rule=thanksgiving_us_date, window_days=7,
    ),
    HolidaySpec(
        slug="black_friday",
        name="🛒 Чёрная пятница",
        description="Чёрная пятница: самые горячие скидки года — успей урвать!",
        discount_percent=45, poster="black_friday.jpg",
        tz=REGION_TZ["US"],
        date_rule=black_friday_date, window_days=3, window_anchor="start",
    ),
]

_GB_SPECS: list[HolidaySpec] = [
    HolidaySpec(
        slug="guy_fawkes",
        name="🎆 Ночь Гая Фокса",
        description="Ночь Гая Фокса: скидки и огни — remember, remember the 5th of November!",
        start_md=(10, 30), end_md=(11, 5),
        discount_percent=20, poster="guy_fawkes.jpg",
        tz=REGION_TZ["GB"],
    ),
    HolidaySpec(
        slug="christmas_gb",
        name="🎄 Рождество и Boxing Day",
        description="Рождество и Boxing Day: праздничные скидки — Merry Christmas & Happy Boxing Day!",
        start_md=(12, 20), end_md=(12, 26),
        discount_percent=30, poster="christmas_gb.jpg",
        tz=REGION_TZ["GB"],
    ),
]

_AU_SPECS: list[HolidaySpec] = [
    HolidaySpec(
        slug="australia_day",
        name="🇦🇺 День Австралии",
        description="День Австралии: скидки ко дню страны — celebrate Australia Day!",
        start_md=(1, 20), end_md=(1, 26),
        discount_percent=20, poster="australia_day.jpg",
        tz=REGION_TZ["AU"],
    ),
    HolidaySpec(
        slug="anzac_day",
        name="🌺 День АНЗАК",
        description="День АНЗАК: скидки в память о героях — Lest we forget.",
        start_md=(4, 19), end_md=(4, 25),
        discount_percent=25, poster="anzac_day.jpg",
        tz=REGION_TZ["AU"],
    ),
]

_CA_SPECS: list[HolidaySpec] = [
    HolidaySpec(
        slug="canada_day",
        name="🍁 День Канады",
        description="День Канады: скидки к национальному празднику — Happy Canada Day!",
        start_md=(6, 25), end_md=(7, 1),
        discount_percent=25, poster="canada_day.jpg",
        tz=REGION_TZ["CA"],
    ),
    HolidaySpec(
        slug="thanksgiving_ca",
        name="🍂 День благодарения Канады",
        description="Канадский День благодарения: осенние скидки и уют!",
        discount_percent=20, poster="thanksgiving_ca.jpg",
        tz=REGION_TZ["CA"],
        date_rule=thanksgiving_ca_date, window_days=7,
    ),
]

_NZ_SPECS: list[HolidaySpec] = [
    HolidaySpec(
        slug="waitangi_day",
        name="🇳🇿 День Вайтанги",
        description="День Вайтанги: скидки ко дню основания Новой Зеландии!",
        start_md=(1, 31), end_md=(2, 6),
        discount_percent=20, poster="waitangi_day.jpg",
        tz=REGION_TZ["NZ"],
    ),
    HolidaySpec(
        slug="matariki",
        name="✨ Матарики",
        description="Матарики — маорийский Новый год: скидки и новые начинания!",
        discount_percent=25, poster="matariki.jpg",
        tz=REGION_TZ["NZ"],
        date_rule=matariki_date, window_days=7,
    ),
]

_ES_SPECS: list[HolidaySpec] = [
    HolidaySpec(
        slug="reyes",
        name="👑 День трёх королей (Reyes Magos)",
        description="Reyes Magos — Богоявление: подарки и скидки для всех!",
        start_md=(12, 31), end_md=(1, 6),
        discount_percent=20, poster="reyes.jpg",
        tz=REGION_TZ["ES"],
    ),
    HolidaySpec(
        slug="semana_santa",
        name="✝️ Семана Санта",
        description="Семана Санта — Страстная неделя: скидки к Пасхе!",
        discount_percent=20, poster="semana_santa.jpg",
        tz=REGION_TZ["ES"],
        date_rule=semana_santa_date, window_days=4,
    ),
    HolidaySpec(
        slug="sant_jordi",
        name="🌹 Сан-Жорди",
        description="Сан-Жорди — день книги и розы: скидки для влюблённых в истории!",
        start_md=(4, 21), end_md=(4, 23),
        discount_percent=15, poster="sant_jordi.jpg",
        tz=REGION_TZ["ES"],
    ),
    HolidaySpec(
        slug="hispanidad",
        name="🇪🇸 День испанской нации (Fiesta Nacional)",
        description="Fiesta Nacional de España: скидки ко дню испаноязычности!",
        start_md=(10, 6), end_md=(10, 12),
        discount_percent=25, poster="hispanidad.jpg",
        tz=REGION_TZ["ES"],
    ),
    HolidaySpec(
        slug="constitucion_es",
        name="📜 День Конституции Испании",
        description="День Конституции: скидки в честь основного закона!",
        start_md=(11, 30), end_md=(12, 6),
        discount_percent=20, poster="constitucion_es.jpg",
        tz=REGION_TZ["ES"],
    ),
]

_BR_SPECS: list[HolidaySpec] = [
    HolidaySpec(
        slug="carnival",
        name="🎭 Карнавал",
        description="Карнавал в Бразилии: скидки в ритме самбы!",
        discount_percent=25, poster="carnival.jpg",
        tz=REGION_TZ["BR"],
        date_rule=carnival_date, window_days=7,
    ),
    HolidaySpec(
        slug="mothers_day_br",
        name="💐 День матери (Бразилия)",
        description="День матери: скидки для самых любимых!",
        discount_percent=20, poster="mothers_day_br.jpg",
        tz=REGION_TZ["BR"],
        date_rule=mothers_day_br_date, window_days=7,
    ),
    HolidaySpec(
        slug="valentines_br",
        name="💘 День влюблённых (Бразилия)",
        description="Dia dos Namorados: скидки ко дню влюблённых!",
        start_md=(6, 6), end_md=(6, 12),
        discount_percent=20, poster="valentines_br.jpg",
        tz=REGION_TZ["BR"],
    ),
    HolidaySpec(
        slug="festa_junina",
        name="🌽 Феста Жунина",
        description="Festa Junina: июньские скидки — São João!",
        start_md=(6, 18), end_md=(6, 24),
        discount_percent=15, poster="festa_junina.jpg",
        tz=REGION_TZ["BR"],
    ),
    HolidaySpec(
        slug="independence_br",
        name="🇧🇷 День независимости Бразилии",
        description="День независимости Бразилии: скидки ко дню свободы!",
        start_md=(9, 1), end_md=(9, 7),
        discount_percent=25, poster="independence_br.jpg",
        tz=REGION_TZ["BR"],
    ),
    HolidaySpec(
        slug="christmas_br",
        name="🎅 Рождество (Бразилия)",
        description="Рождество в Бразилии: праздничные скидки!",
        start_md=(12, 22), end_md=(12, 29),
        discount_percent=25, poster="christmas_br.jpg",
        tz=REGION_TZ["BR"],
    ),
]

_PT_SPECS: list[HolidaySpec] = [
    HolidaySpec(
        slug="portugal_day",
        name="🇵🇹 День Португалии",
        description="Dia de Portugal: скидки ко дню страны!",
        start_md=(6, 4), end_md=(6, 10),
        discount_percent=20, poster="portugal_day.jpg",
        tz=REGION_TZ["PT"],
    ),
]

# Итоговый реестр календарей по регионам.
# Текущий HOLIDAYS остаётся календарём RU.
REGION_CALENDARS: dict[str, list[HolidaySpec]] = {
    "RU": HOLIDAYS,
    "US": _US_SPECS,
    "GB": _GB_SPECS,
    "AU": _AU_SPECS,
    "CA": _CA_SPECS,
    "NZ": _NZ_SPECS,
    "ES": _ES_SPECS,
    "BR": _BR_SPECS,
    "PT": _PT_SPECS,
}

# Для удобства — все известные регионы
ALL_REGIONS: set[str] = set(REGION_CALENDARS.keys())

# Для тестов: все спеки по слагу (включая региональные)
ALL_SPECS_BY_SLUG: dict[str, HolidaySpec] = {}
for cal in REGION_CALENDARS.values():
    for s in cal:
        # halloween существует в RU и US — это один и тот же slug, оставляем первый
        if s.slug not in ALL_SPECS_BY_SLUG:
            ALL_SPECS_BY_SLUG[s.slug] = s


def _msk_to_utc_naive(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """00:00 (или 23:59) MSK указанной даты -> naive-UTC (формат хранения в БД)."""
    dt = datetime(year, month, day, hour, minute, tzinfo=MSK)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _tz_to_utc_naive(year: int, month: int, day: int, hour: int = 0, minute: int = 0, tz_name: str = "UTC") -> datetime:
    """Локальная дата/время в зоне tz_name -> naive-UTC."""
    if ZoneInfo is not None:
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc
    else:
        tz = timezone.utc
        # fallback для известных зон: используем фиксированные смещения если zoneinfo недоступен
        if tz_name == "Europe/Moscow":
            tz = MSK
    dt = datetime(year, month, day, hour, minute, tzinfo=tz)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _holiday_date_for_spec(spec: HolidaySpec, year: int) -> date:
    if spec.date_rule is not None:
        return spec.date_rule(year)
    # фиксированная дата — конец окна = дата праздника
    if spec.end_md is not None:
        return date(year, spec.end_md[0], spec.end_md[1])
    # fallback: start
    if spec.start_md is not None:
        return date(year, spec.start_md[0], spec.start_md[1])
    raise ValueError(f"spec {spec.slug} has no date")


def holiday_window(spec: HolidaySpec, anchor_year: int) -> tuple[datetime, datetime]:
    """Окно события (naive-UTC start/end) для года, в котором оно начинается.

    `anchor_year` — год дня старта (для фиксированных окон) или год праздника
    (для плавающих). Если окно переходит через Новый год
    (конец раньше начала по календарю, например 30.12 -> 06.01), год конца
    сдвигается на +1.
    """
    tz_name = getattr(spec, "tz", "Europe/Moscow") or "Europe/Moscow"
    if spec.date_rule is not None:
        holiday_date = spec.date_rule(anchor_year)
        if getattr(spec, "window_anchor", "end") == "start":
            start_date = holiday_date
            end_date = holiday_date + timedelta(days=spec.window_days - 1)
        else:
            start_date = holiday_date - timedelta(days=spec.window_days - 1)
            end_date = holiday_date
        start = _tz_to_utc_naive(start_date.year, start_date.month, start_date.day, 0, 0, tz_name)
        end = _tz_to_utc_naive(end_date.year, end_date.month, end_date.day, 23, 59, tz_name)
        return start, end
    # фиксированное окно
    if spec.start_md is None or spec.end_md is None:
        raise ValueError(f"spec {spec.slug} missing start_md/end_md and no date_rule")
    start = _tz_to_utc_naive(anchor_year, spec.start_md[0], spec.start_md[1], 0, 0, tz_name)
    end_year = anchor_year
    if spec.end_md < spec.start_md:  # переход через год
        end_year += 1
    end = _tz_to_utc_naive(end_year, spec.end_md[0], spec.end_md[1], 23, 59, tz_name)
    return start, end


def holiday_windows_around(
    now: datetime,
    lookahead_days: int = 30,
    *,
    region: str | None = None,
    lang: str | None = None,
) -> list[tuple[HolidaySpec, datetime, datetime]]:
    """Экземпляры праздников, актуальные сейчас: идущие и стартующие в пределах
    `lookahead_days`. Учитывает переход года (якорь — год дня старта).

    Если указан region/lang — берётся календарь этого региона/языка;
    иначе — RU (старое поведение, для обратной совместимости с тестами).
    """
    # Определяем календарь
    calendar = HOLIDAYS
    if region is not None:
        r = region.upper() if isinstance(region, str) else ""
        if r in REGION_CALENDARS:
            calendar = REGION_CALENDARS[r]
        else:
            # неизвестный регион -> фолбэк через язык или RU
            if lang is not None:
                fallback = DEFAULT_CALENDAR_BY_LANG.get(normalize_language(lang))
                if fallback and fallback in REGION_CALENDARS:
                    calendar = REGION_CALENDARS[fallback]
    elif lang is not None:
        fallback = DEFAULT_CALENDAR_BY_LANG.get(normalize_language(lang))
        if fallback and fallback in REGION_CALENDARS:
            calendar = REGION_CALENDARS[fallback]

    horizon = now + timedelta(days=lookahead_days)
    out: list[tuple[HolidaySpec, datetime, datetime]] = []
    seen: set[tuple[str, str]] = set()
    for spec in calendar:
        for anchor_year in (now.year - 1, now.year, now.year + 1):
            try:
                start, end = holiday_window(spec, anchor_year)
            except Exception:
                continue
            if end < now or start > horizon:
                continue
            key = (spec.slug, start.isoformat())
            if key in seen:
                continue
            seen.add(key)
            out.append((spec, start, end))
    out.sort(key=lambda item: item[1])
    return out


def get_calendar_for_region(region_code: str | None) -> list[HolidaySpec]:
    """Календарь региона или RU по умолчанию."""
    if region_code:
        r = region_code.upper()
        if r in REGION_CALENDARS:
            return REGION_CALENDARS[r]
    return REGION_CALENDARS["RU"]


def get_calendar_for_user(user) -> list[HolidaySpec]:
    """Итоговый календарь пользователя: ровно один.

    Приоритет: user.region -> дефолт языка -> RU.
    """
    # user может быть объектом User или строкой кода
    if isinstance(user, str):
        return get_calendar_for_region(user)
    region = getattr(user, "region", None) if user is not None else None
    if region and region.upper() in REGION_CALENDARS:
        return REGION_CALENDARS[region.upper()]
    # фолбэк по языку
    lang = getattr(user, "language", None) if user is not None else None
    if lang:
        norm = normalize_language(lang)
        fallback = DEFAULT_CALENDAR_BY_LANG.get(norm)
        if fallback and fallback in REGION_CALENDARS:
            return REGION_CALENDARS[fallback]
    return REGION_CALENDARS["RU"]


def get_user_region(user) -> str:
    """Определяет регион пользователя с учётом фолбэков."""
    if user is None:
        return "RU"
    region = getattr(user, "region", None)
    if region and region.upper() in REGION_CALENDARS:
        return region.upper()
    lang = getattr(user, "language", None)
    if lang:
        norm = normalize_language(lang)
        fb = DEFAULT_CALENDAR_BY_LANG.get(norm)
        if fb:
            return fb
    return "RU"


def resolve_poster(filename: str | None, lang: str | None = None, region: str | None = None) -> str | None:
    """Путь к постеру на диске или None.

    Порядок поиска: `постеры/<имя>` (приоритет) -> `banners/<имя>`; каждая
    папка проверяется относительно cwd и корня репозитория (на Vercel/в
    Docker рабочая директория может отличаться).

    `lang` — язык получателя: для него сначала ищется локализованная копия
    (`постеры/en/<имя>`, затем `banners/en/<имя>`), а если перевода нет —
    берётся русский оригинал. Переведённые постеры необязательны: отсутствие
    файла в подпапке языка не ломает показ события. По умолчанию язык берётся
    из контекста текущего апдейта (см. `app.i18n.current_language`).

    Расширенный каскад с регионом (§3.5):
      постеры/<region>/<lang>/<имя> → постеры/<region>/<имя> →
      постеры/<lang>/<имя> → постеры/<имя> (и то же для banners/).
    `region` — код страны (US, GB, ...); старые вызовы без него работают как раньше.
    """
    if not filename:
        return None
    name = Path(str(filename)).name  # защита от выхода за пределы папки
    code = normalize_language(lang or current_language())
    subdir = LOCALIZED_POSTER_DIRS.get(code)

    # Нормализуем регион к папке (lowercase)
    region_part: str | None = None
    if region:
        r = str(region).strip()
        if r:
            # папка региона — lowercase, например US -> us
            region_part = r.lower()

    # Строим упорядоченный список (folder, subdir) для проверки
    order: list[tuple[str, str | None]] = []

    # Каскад с регионом:
    # 1) region/lang
    # 2) region
    # 3) lang
    # 4) base
    # Для каждого уровня — сначала постеры, потом banners.
    # region/lang — высший приоритет
    if region_part and subdir:
        for folder in POSTER_DIRS:
            order.append((folder, f"{region_part}/{subdir}"))
    elif region_part and code not in (DEFAULT_LANGUAGE, subdir) and code != "en":
        # у языка нет своей папки, но есть регион: проверяем region/en как фолбэк
        # (как и раньше: для языка без своей папки подставляем en)
        for folder in POSTER_DIRS:
            order.append((folder, f"{region_part}/en"))

    # region alone
    if region_part:
        for folder in POSTER_DIRS:
            order.append((folder, region_part))

    # lang alone (существующая логика)
    if subdir:
        order.extend((folder, subdir) for folder in POSTER_DIRS)
    if code not in (DEFAULT_LANGUAGE, subdir) and code != "en":
        order.extend((folder, "en") for folder in POSTER_DIRS)

    # оригиналы
    order.extend((folder, None) for folder in POSTER_DIRS)

    # дедупликация (могли добавить дважды region/en и en)
    seen_order: set[tuple[str, str | None]] = set()
    deduped: list[tuple[str, str | None]] = []
    for item in order:
        if item not in seen_order:
            seen_order.add(item)
            deduped.append(item)
    order = deduped

    for folder, sub in order:
        for base in (Path(folder), _PROJECT_ROOT / folder):
            candidate = base / sub / name if sub else base / name
            if candidate.is_file():
                return str(candidate)
    return None


def resolve_event_poster(event, lang: str | None = None, region: str | None = None) -> str | None:
    """Постер события (Event.poster_path из каталога) или None, если файла нет.

    `lang` — язык получателя: английские копии лежат в подпапках `en/`.
    `region` — код страны для расширенного каскада постеров.
    """
    return resolve_poster(getattr(event, "poster_path", None), lang=lang, region=region)


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
