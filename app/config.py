import os
from dotenv import load_dotenv

load_dotenv()


def _get_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except Exception:
        return default


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except Exception:
        return default


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# ============================
# ОСНОВНЫЕ ПЕРЕМЕННЫЕ
# ============================
BOT_TOKEN = _get_str("BOT_TOKEN")
DATABASE_URL = _get_str("DATABASE_URL")
BOT_USERNAME = _get_str("BOT_USERNAME")
PROVIDER_TOKEN = _get_str("PROVIDER_TOKEN")
WEBHOOK_BASE = _get_str("WEBHOOK_BASE")
WEBHOOK_PATH = _get_str("WEBHOOK_PATH")
LOG_CHAT_ID = _get_str("LOG_CHAT_ID")

ADMINS_RAW = _get_str("ADMINS")
ADMINS: list[int] = []
for _x in ADMINS_RAW.split(","):
    _x = _x.strip()
    if _x.isdigit():
        ADMINS.append(int(_x))

PORT = _get_int("PORT", 10000)

# ============================
# ЭКОНОМИКА (ПЕРЕРАБОТАНА)
# ============================

# Стартовый баланс (умеренный, чтобы сразу попробовать функционал)
STARTING_BALANCE = _get_float("STARTING_BALANCE", 3.0)

# Просмотр видео: зритель ПЛАТИТ
WATCH_COST = _get_float("WATCH_COST", 1.5)

# Награда автору за загрузку (скромная, чтобы не фармили)
UPLOAD_REWARD = _get_float("UPLOAD_REWARD", 0.3)
PHOTO_UPLOAD_REWARD = _get_float("PHOTO_UPLOAD_REWARD", 0.1)

# Рефералы: награда пригласившему только после 5 просмотров рефералом
REFERRAL_REWARD_INVITER = _get_float("REFERRAL_REWARD_INVITER", 1.0)
REFERRAL_REWARD_NEW_USER = _get_float("REFERRAL_REWARD_NEW_USER", 0.5)

# Курс Stars -> монеты (базовый)
STARS_TO_COINS_RATE = _get_float("STARS_TO_COINS_RATE", 2.0)

# Пакеты покупки монет за Stars (основа)
STARS_PACKAGES = {
    "pack_1": {"stars": 1, "coins": 2, "title": "2 монеты"},
    "pack_5": {"stars": 5, "coins": 10, "title": "10 монет"},
    "pack_10": {"stars": 10, "coins": 20, "title": "20 монет"},
    "pack_25": {"stars": 25, "coins": 50, "title": "50 монет"},
    "pack_50": {"stars": 50, "coins": 100, "title": "100 монет"},
}

# Пакеты за реальные деньги (если используются)
MONEY_PACKAGES = {
    "money_99": {"amount": 9900, "coins": 250, "title": "250 монет"},
    "money_199": {"amount": 19900, "coins": 600, "title": "600 монет"},
    "money_499": {"amount": 49900, "coins": 1800, "title": "1800 монет"},
}

# Интервал показа офферов
OFFER_BROADCAST_INTERVAL_HOURS = _get_float("OFFER_BROADCAST_INTERVAL_HOURS", 2.5)

# ============================
# ЛИМИТЫ
# ============================
DAILY_PHOTO_LIMIT = _get_int("DAILY_PHOTO_LIMIT", 10)

# Бесплатные игры
FREE_GAMES_PER_SESSION = 5
GAME_SESSION_HOURS = 6
GAME_SESSION_COST = 10.0             # монет за продление сессии

# ============================
# ЕЖЕДНЕВНЫЙ БОНУС (ПРОГРЕССИВНЫЙ)
# ============================
DAILY_BONUS_STREAK_BASE = 2.0
DAILY_BONUS_STREAK_INCREASE = 1.0
MAX_BONUS_STREAK = 30

# ============================
# XP И УРОВНИ
# ============================
LEVEL_XP_BASE = _get_int("LEVEL_XP_BASE", 100)
LEVEL_XP_MULTIPLIER = _get_float("LEVEL_XP_MULTIPLIER", 1.5)

XP_PER_WATCH = _get_int("XP_PER_WATCH", 5)
XP_PER_UPLOAD = _get_int("XP_PER_UPLOAD", 20)
XP_PER_RATING = _get_int("XP_PER_RATING", 2)
XP_PER_COMMENT = _get_int("XP_PER_COMMENT", 3)
XP_PER_REACTION = _get_int("XP_PER_REACTION", 1)
XP_PER_GAME = _get_int("XP_PER_GAME", 3)

# ============================
# VIP
# ============================
VIP_PRICE_STARS = _get_int("VIP_PRICE_STARS", 50)
VIP_DURATION_DAYS = _get_int("VIP_DURATION_DAYS", 30)
VIP_BONUS_MULTIPLIER = _get_float("VIP_BONUS_MULTIPLIER", 3.0)
VIP_FREE_PHOTOS = True
VIP_WATCH_DISCOUNT = _get_float("VIP_WATCH_DISCOUNT", 0.4)   # скидка 60%
VIP_FREE_PROMO_PER_MONTH = 1                                  # бесплатных промокодов для VIP

# ============================
# ИГРЫ
# ============================
DICE_MIN_BET = _get_int("DICE_MIN_BET", 1)
DICE_MAX_BET = _get_int("DICE_MAX_BET", 50)

# ============================
# КВЕСТЫ (НА РУССКОМ)
# ============================
DAILY_QUESTS = [
    {"type": "watch", "target": 3, "reward": 2, "desc": "Посмотреть 3 видео"},
    {"type": "upload", "target": 1, "reward": 3, "desc": "Загрузить 1 видео или фото"},
    {"type": "rate", "target": 3, "reward": 1, "desc": "Оценить 3 видео"},
    {"type": "comment", "target": 2, "reward": 2, "desc": "Написать 2 комментария"},
    {"type": "react", "target": 5, "reward": 1, "desc": "Поставить 5 реакций"},
]
PREMIUM_DAILY_QUESTS = [
    {"type": "watch", "target": 10, "reward": 8, "desc": "VIP: Посмотреть 10 видео"},
    {"type": "comment", "target": 5, "reward": 5, "desc": "VIP: Написать 5 комментариев"},
]

REACTION_TYPES = ["👍", "❤", "🔥", "😁", "😢"]

# ============================
# КОММЕНТАРИИ (АНТИСПАМ)
# ============================
COMMENTS_PER_10_MIN = _get_int("COMMENTS_PER_10_MIN", 5)
COMMENT_MIN_INTERVAL_SEC = _get_int("COMMENT_MIN_INTERVAL_SEC", 15)

# ============================
# НАГРАДЫ ЗА ТОПЫ
# ============================
WEEKLY_TOP1_REWARD = _get_float("WEEKLY_TOP1_REWARD", 50.0)
WEEKLY_TOP2_REWARD = _get_float("WEEKLY_TOP2_REWARD", 25.0)
WEEKLY_TOP3_REWARD = _get_float("WEEKLY_TOP3_REWARD", 15.0)

# ============================
# ПРОДВИЖЕНИЕ
# ============================
PIN_OFFER_COST = _get_float("PIN_OFFER_COST", 100.0)
BUMP_VIDEO_COST = _get_float("BUMP_VIDEO_COST", 25.0)

# ============================
# НИКНЕЙМ
# ============================
NICKNAME_FIRST_FREE = True
NICKNAME_CHANGE_COST = _get_float("NICKNAME_CHANGE_COST", 50.0)
NICKNAME_MIN_LENGTH = 3
NICKNAME_MAX_LENGTH = 20

# ============================
# АРЕНДА (ОФФЕРЫ)
# ============================
OFFER_DEFAULT_RENT_COST_PER_DAY = _get_float("OFFER_DEFAULT_RENT_COST_PER_DAY", 5.0)
OFFER_MIN_RENT_DAYS = 1
OFFER_MAX_RENT_DAYS = 30

# ============================
# ПРОМОКОДЫ (ЗА STARS)
# ============================
# Стоимость создания: Stars = (сумма_монет * кол-во_использований) * RATE
# с учётом оптовой скидки при большом количестве использований
PROMOCODE_CREATION_STAR_RATE = 0.5             # Stars за 1 монету * 1 использование
PROMOCODE_BULK_DISCOUNT_THRESHOLD = 10         # от скольки использований действует скидка
PROMOCODE_BULK_DISCOUNT_RATE = 0.8             # множитель стоимости при опте (20% скидка)

# Процент от потраченных активировавшими монет, который получает создатель (0 = отключено)
PROMOCODE_CREATOR_BONUS_PERCENT = 5.0

# Ограничения при создании
PROMOCODE_MAX_AMOUNT = 1000                    # макс. монет в одном промокоде
PROMOCODE_MAX_USES = 100                       # макс. использований
PROMOCODE_MAX_HOURS = 168                      # макс. срок действия (7 дней)

# ============================
# ДИНАМИЧЕСКИЙ КУРС ПОКУПКИ МОНЕТ
# ============================
DYNAMIC_STAR_DISCOUNT_ENABLED = True
# Часы действия бонуса (UTC), например "17-20"
DYNAMIC_STAR_DISCOUNT_HOURS = "17-20"
# Множитель получаемых монет в эти часы (1.5 = +50%)
DYNAMIC_STAR_DISCOUNT_MULTIPLIER = 1.5
# Бонус монет за первую покупку дня (любой пакет)
FIRST_PURCHASE_DAILY_BONUS = 5.0

# ============================
# УМНЫЕ ПОКАЗЫ ОФФЕРОВ
# ============================
SMART_AD_MIN_INTERVAL_MINUTES = 15
SMART_AD_LOW_BALANCE_THRESHOLD = 3.0
SMART_AD_LOW_BALANCE_HINT_INTERVAL_MINUTES = 30
SMART_AD_VIDEO_CHANCE = 0.35
SMART_AD_FORCED_WATCH_SECONDS = 5

# Периодический аудит подписок по офферам
OFFER_SUBSCRIPTION_CHECK_INTERVAL_SECONDS = _get_int(
    "OFFER_SUBSCRIPTION_CHECK_INTERVAL_SECONDS",
    300,
)
OFFER_SUBSCRIPTION_CHECK_BATCH = _get_int(
    "OFFER_SUBSCRIPTION_CHECK_BATCH",
    200,
)
OFFER_DAILY_REWARD_CAP = _get_float("OFFER_DAILY_REWARD_CAP", 40.0)

# Флаги финальной эксплуатации
ENABLE_SUBSCRIPTION_AUDIT = _get_bool("ENABLE_SUBSCRIPTION_AUDIT", True)
ENABLE_PROMOCODES = _get_bool("ENABLE_PROMOCODES", True)
ENABLE_ADMIN_BROADCAST = _get_bool("ENABLE_ADMIN_BROADCAST", True)

# Антиспам / рейтлимиты
OFFER_ACTION_COOLDOWN_SECONDS = _get_int("OFFER_ACTION_COOLDOWN_SECONDS", 3)
PROMO_ACTIVATE_COOLDOWN_SECONDS = _get_int("PROMO_ACTIVATE_COOLDOWN_SECONDS", 10)
GUESS_JACKPOT_CHANCE = _get_float("GUESS_JACKPOT_CHANCE", 0.01)
GUESS_JACKPOT_MULTIPLIER = _get_int("GUESS_JACKPOT_MULTIPLIER", 20)

# Лотерея-лото
ENABLE_LOTTERY = _get_bool("ENABLE_LOTTERY", True)
LOTTERY_TICKET_PRICE = _get_float("LOTTERY_TICKET_PRICE", 3.0)
LOTTERY_NUMBERS_POOL = _get_int("LOTTERY_NUMBERS_POOL", 36)
LOTTERY_NUMBERS_PER_TICKET = _get_int("LOTTERY_NUMBERS_PER_TICKET", 6)
LOTTERY_DRAW_START_HOUR_UTC = _get_int("LOTTERY_DRAW_START_HOUR_UTC", 18)
LOTTERY_DRAW_END_HOUR_UTC = _get_int("LOTTERY_DRAW_END_HOUR_UTC", 20)
LOTTERY_DRAW_SECRET = _get_str("LOTTERY_DRAW_SECRET", "change-me-secret")