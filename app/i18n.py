"""Мультиязычность интерфейса бота (i18n).

Русский — канонический язык бота. Английский — первый дополнительный язык.
Язык пользователя хранится в `users.language` (по умолчанию `ru`) и выбирается
кнопкой «🌐 Язык» в главном меню.

Два способа перевода:

1. По исходному русскому тексту (ключ = сам русский текст) — для основного
   массива сообщений: `t("Привет!")` → вернёт «Hello!» для английского языка.
   Удобно: видно исходник прямо в коде, фолбэк — сам ключ (русский текст).
2. По семантическому ключу — для коротких подписей, общих для многих экранов:
   `t("menu.watch")` (см. `TRANSLATIONS` ниже).

Язык текущего апдейта берётся из `ContextVar` (`current_language()`), который
выставляет `BanCheckMiddleware` для каждого message/callback-апдейта. Поэтому
`lang` не нужно протаскивать через хендлеры, сервисы и сборщики клавиатур —
достаточно обернуть текст в `t(...)`. Вне апдейта (воркеры, рассылки) язык
задаётся явно: `set_current_language(...)` или контекст-менеджер
`language_scope(...)`.

Плейсхолдеры в шаблонах — именные, через `str.format`:
`t("Баланс: {balance} монет", balance=user.balance)`.

Как добавить новый язык:
1. Добавь код в `SUPPORTED_LANGUAGES` (флаг + название языка на этом языке).
2. Добавь словарь переводов (можно частичный — нет перевода = фолбэк на русский,
   а для неизвестного ключа вернётся сам ключ).
3. Главное меню и обработчики подхватят новый язык сами: меню собирается через
   `t("menu.<ключ>")`, а обработчики матчат `F.text` по `menu_button_variants()`
   из `app/keyboards.py`.
"""
from __future__ import annotations

import contextlib
from contextvars import ContextVar

# Массовые переводы «по исходному русскому тексту» вынесены в отдельный модуль,
# чтобы файл ядра оставался обозримым (тысячи пар «русский → английский»).
from app.i18n_en import EN_SOURCE

DEFAULT_LANGUAGE = "ru"

# Код языка -> (флаг, собственное название языка).
SUPPORTED_LANGUAGES: dict[str, tuple[str, str]] = {
    "ru": ("🇷🇺", "Русский"),
    "en": ("🇬🇧", "English"),
}

# Семантические переводы (короткие подписи меню, профиля, приветствия и т.п.).
TRANSLATIONS: dict[str, dict[str, str]] = {
    "ru": {
        # Кнопки главного меню
        "menu.watch": "🎬 Смотреть",
        "menu.upload": "📤 Загрузить",
        "menu.profile": "👤 Профиль",
        "menu.buy": "🛍 Магазин",
        "menu.offers": "📢 Офферы",
        "menu.referrals": "👥 Рефералы",
        "menu.games": "🎮 Игры",
        "menu.tops": "🏆 Топы",
        "menu.promo": "🎟 Промокоды",
        "menu.feedback": "💬 Жалобы и предложения",
        "menu.rules": "📜 Правила",
        "menu.faq": "ℹ️ FAQ / Помощь",
        "menu.admin": "🔧 Админка",
        "menu.lang": "🌐 Язык",
        # Выбор языка
        "lang.title": "🌐 <b>Выбери язык бота</b>",
        "lang.changed_alert": "✅ Язык: 🇷🇺 русский",
        # Главное меню
        "main_menu.title": "🏠 <b>Главное меню</b>\n\nВыбери нужный раздел:",
        "main_menu.button": "🏠 Главное меню",
        # Приветствие / старт
        "welcome.greeting": "👋 Привет, <b>{name}</b>{vip}!\n💰 Баланс: <b>{balance}</b> монет",
        "welcome.no_nickname_hint": (
            "🎬 Без ника можно посмотреть всего 3 фото или видео. "
            "Затем установи ник бесплатно в профиле; для загрузок он тоже понадобится."
        ),
        # Отмена FSM-сценариев
        "cancel.done": "✅ Режим сброшен. Нажми /start или выбери действие в меню.",
        "cancel.aborted": "❌ Действие отменено.",
        # Профиль
        "profile.title": "👤 <b>Профиль</b>",
        "profile.nick": "🏷 Ник:",
        "profile.telegram_id": "🆔 Telegram ID:",
        "profile.balance": "💰 Баланс: <b>{balance}</b> монет",
        "profile.level": "🏆 Уровень: <b>{level}</b>",
        "profile.xp": "⭐ XP: {current}/{needed} [{bar}]",
        "profile.referrals": "👥 Приглашено друзей: {count}",
        "profile.earned": "💎 Заработано с рефералов: {amount} монет",
        "profile.status": "📊 Статус: {status}",
        "profile.vip_until": "👑 VIP до: {date}",
        "profile.nick_cost": "Смена ника стоит {cost} монет",
        "profile.change_nick": "✏️ Сменить ник",
        "profile.blocked_authors": "🚫 Заблокированные авторы ({count})",
        # Служебные уведомления (middleware)
        "ban.blocked": "🚫 Доступ к боту для тебя заблокирован.",
        "bonus.daily": (
            "🔥 <b>Ежедневный бонус за возвращение!</b>\n\n"
            "Начислено: <b>+{reward}</b> монет\n"
            "Дней подряд: <b>{streak}</b>\n\n"
            "Бонус растёт с серией до дневного лимита — <b>{cap}</b> монет."
        ),
        "db.down": (
            "⚠️ Бот временно недоступен (ведутся технические работы). "
            "Попробуй, пожалуйста, позже."
        ),
    },
    "en": {
        # Main menu buttons
        "menu.watch": "🎬 Watch",
        "menu.upload": "📤 Upload",
        "menu.profile": "👤 Profile",
        "menu.buy": "🛍 Shop",
        "menu.offers": "📢 Offers",
        "menu.referrals": "👥 Referrals",
        "menu.games": "🎮 Games",
        "menu.tops": "🏆 Tops",
        "menu.promo": "🎟 Promo codes",
        "menu.feedback": "💬 Feedback",
        "menu.rules": "📜 Rules",
        "menu.faq": "ℹ️ FAQ / Help",
        "menu.admin": "🔧 Admin",
        "menu.lang": "🌐 Language",
        # Language picker
        "lang.title": "🌐 <b>Choose the bot language</b>",
        "lang.changed_alert": "✅ Language: 🇬🇧 English",
        # Main menu
        "main_menu.title": "🏠 <b>Main menu</b>\n\nPick a section:",
        "main_menu.button": "🏠 Main menu",
        # Welcome / start
        "welcome.greeting": "👋 Hi, <b>{name}</b>{vip}!\n💰 Balance: <b>{balance}</b> coins",
        "welcome.no_nickname_hint": (
            "🎬 Without a nickname you can watch just 3 photos or videos. "
            "Then set a nickname for free in your profile — you'll need it for uploads too."
        ),
        # FSM cancel
        "cancel.done": "✅ Cancelled. Tap /start or pick an action from the menu.",
        "cancel.aborted": "❌ Action cancelled.",
        # Profile
        "profile.title": "👤 <b>Profile</b>",
        "profile.nick": "🏷 Nickname:",
        "profile.telegram_id": "🆔 Telegram ID:",
        "profile.balance": "💰 Balance: <b>{balance}</b> coins",
        "profile.level": "🏆 Level: <b>{level}</b>",
        "profile.xp": "⭐ XP: {current}/{needed} [{bar}]",
        "profile.referrals": "👥 Friends invited: {count}",
        "profile.earned": "💎 Earned from referrals: {amount} coins",
        "profile.status": "📊 Status: {status}",
        "profile.vip_until": "👑 VIP until: {date}",
        "profile.nick_cost": "Nickname change costs {cost} coins",
        "profile.change_nick": "✏️ Change nickname",
        "profile.blocked_authors": "🚫 Blocked authors ({count})",
        # Service notifications (middleware)
        "ban.blocked": "🚫 Your access to the bot has been blocked.",
        "bonus.daily": (
            "🔥 <b>Daily comeback bonus!</b>\n\n"
            "Credited: <b>+{reward}</b> coins\n"
            "Day streak: <b>{streak}</b>\n\n"
            "The bonus grows with your streak up to the daily limit — <b>{cap}</b> coins."
        ),
        "db.down": (
            "⚠️ The bot is temporarily unavailable (maintenance in progress). "
            "Please try again later."
        ),
    },
}

# Английские переводы основного массива — по исходному русскому тексту.
TRANSLATIONS["en"] = {**TRANSLATIONS["en"], **EN_SOURCE}

# Язык текущего апдейта (выставляется BanCheckMiddleware для каждого
# message/callback; в воркерах/рассылках задаётся явно через set_current_language).
_current_lang: ContextVar[str] = ContextVar("bot_user_language", default=DEFAULT_LANGUAGE)


def set_current_language(lang: str | None) -> None:
    """Задать язык для текущего контекста (воркеры, рассылки, aiohttp-хендлеры)."""
    _current_lang.set(normalize_language(lang))


def current_language() -> str:
    """Язык текущего апдейта/контекста (по умолчанию русский)."""
    return _current_lang.get()


@contextlib.contextmanager
def language_scope(lang: str | None):
    """Временно переключить язык текущего контекста (например, на получателя рассылки)."""
    token = _current_lang.set(normalize_language(lang))
    try:
        yield
    finally:
        _current_lang.reset(token)


def normalize_language(code: str | None) -> str:
    """Приводит код языка к поддерживаемому виду.

    Понимает «EN», «en-US», «en_US» и т.п.; неизвестный или пустой код
    превращается в язык по умолчанию (русский).
    """
    if not code:
        return DEFAULT_LANGUAGE
    code = str(code).strip().lower().replace("_", "-")
    if code in SUPPORTED_LANGUAGES:
        return code
    base = code.split("-", 1)[0]
    if base in SUPPORTED_LANGUAGES:
        return base
    return DEFAULT_LANGUAGE


def get_user_language(user) -> str:
    """Язык интерфейса пользователя по его записи в БД (фолбэк — русский)."""
    return normalize_language(getattr(user, "language", None))


def language_label(code: str) -> str:
    """Подпись языка для кнопок: «🇷🇺 Русский», «🇬🇧 English»."""
    flag, name = SUPPORTED_LANGUAGES.get(normalize_language(code), ("", code))
    return f"{flag} {name}".strip()


def t(lang: str | None = None, key: str | None = None, **kwargs) -> str:
    """Перевод текста.

    Две формы вызова:
    * `t("Привет!")` / `t("menu.watch")` — язык берётся из контекста апдейта
      (см. `current_language()`);
    * `t("en", "Привет!")` — язык задан явно.

    Порядок фолбэков: запрошенный язык -> русский -> сам ключ (исходный текст).
    Именные плейсхолдеры `{name}` подставляются через `str.format`.
    """
    if key is None:
        # Форма t("ключ") — первый аргумент это ключ, язык из контекста.
        key, lang = lang, None
    if lang:
        lang = normalize_language(lang)
    else:
        lang = current_language()
    text = TRANSLATIONS.get(lang, {}).get(key)
    if text is None:
        text = TRANSLATIONS.get(DEFAULT_LANGUAGE, {}).get(key)
    if text is None:
        # фолбэк — исходный русский текст (сам ключ), его тоже надо отформатировать
        text = key
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text
