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
# ЭКОНОМИКА (СБАЛАНСИРОВАННАЯ x10)
# ============================

# Стартовый баланс
STARTING_BALANCE = _get_float("STARTING_BALANCE", 100.0)

# Просмотр видео
WATCH_COST = _get_float("WATCH_COST", 10.0)

# Награда за загрузку
UPLOAD_REWARD = _get_float("UPLOAD_REWARD", 30.0)
PHOTO_UPLOAD_REWARD = _get_float("PHOTO_UPLOAD_REWARD", 15.0)

# Рефералы
REFERRAL_REWARD_INVITER = _get_float("REFERRAL_REWARD_INVITER", 50.0)
REFERRAL_REWARD_NEW_USER = _get_float("REFERRAL_REWARD_NEW_USER", 20.0)

# Курс Stars → монеты (Базовый: 1 Star = 500 монет)
STARS_TO_COINS_RATE = _get_float("STARS_TO_COINS_RATE", 10.0)

# Пакеты Stars (С прогрессивным бонусом)
STARS_PACKAGES = {
    "pack_1":   {"stars": 1,   "coins": 10,    "title": "10 монет"},
    "pack_5":   {"stars": 5,   "coins": 55,   "title": "55 монет"},
    "pack_10":  {"stars": 10,  "coins": 120,   "title": "120 монет"},
    "pack_25":  {"stars": 25,  "coins": 320,  "title": "320 монет"},
    "pack_50":  {"stars": 50,  "coins": 700,  "title": "700 монет"},
    "pack_100": {"stars": 100, "coins": 1600,  "title": "1 600 монет"},
}

# Пакеты за реальные деньги (Примерно 1 Star = 2 RUB)
MONEY_PACKAGES = {
    "money_99":  {"amount": 9900,  "coins": 700,   "title": "700 монет"},
    "money_199": {"amount": 19900, "coins": 1600,   "title": "1 600 монет"},
    "money_499": {"amount": 49900, "coins": 4400,  "title": "4 400 монет"},
}

# Интервал показа офферов
OFFER_BROADCAST_INTERVAL_HOURS = _get_float("OFFER_BROADCAST_INTERVAL_HOURS", 2.5)

# ============================
# ПРОГРЕССИВНЫЕ РЕФЕРАЛЫ (BATTLE PASS)
# ============================
REFERRAL_MILESTONES = {
    3: {"type": "coins", "amount": 20.0, "desc": "20 монет"},
    5: {"type": "lootbox", "amount": 1, "desc": "1 Лутбокс"},
    10: {"type": "coins", "amount": 60.0, "desc": "60 монет"},
    15: {"type": "lootbox", "amount": 3, "desc": "3 Лутбокса"},
    20: {"type": "vip", "amount": 7, "desc": "VIP на 7 дней"},
}

DAILY_PHOTO_LIMIT = _get_int("DAILY_PHOTO_LIMIT", 10)

# Бесплатные игры
FREE_GAMES_PER_SESSION = 5
GAME_SESSION_HOURS = 6
GAME_SESSION_COST = 100.0             # монет за продление сессии

# ============================
# ЕЖЕДНЕВНЫЙ БОНУС (ПРОГРЕССИВНЫЙ)
# ============================
DAILY_BONUS_STREAK_BASE = 20.0
DAILY_BONUS_STREAK_INCREASE = 10.0
MAX_BONUS_STREAK = 30

# ============================
# XP И УРОВНИ
# ============================
LEVEL_XP_BASE = _get_int("LEVEL_XP_BASE", 100)
LEVEL_XP_MULTIPLIER = _get_float("LEVEL_XP_MULTIPLIER", 1.5)

XP_PER_WATCH = _get_int("XP_PER_WATCH", 15)
XP_PER_UPLOAD = _get_int("XP_PER_UPLOAD", 20)
XP_PER_RATING = _get_int("XP_PER_RATING", 2)
XP_PER_COMMENT = _get_int("XP_PER_COMMENT", 3)
XP_PER_REACTION = _get_int("XP_PER_REACTION", 1)
XP_PER_GAME = _get_int("XP_PER_GAME", 3)

# ============================
# VIP
# ============================
VIP_PRICE_STARS = _get_int("VIP_PRICE_STARS", 100)
VIP_DURATION_DAYS = _get_int("VIP_DURATION_DAYS", 30)
VIP_BONUS_MULTIPLIER = _get_float("VIP_BONUS_MULTIPLIER", 2.0) # Снижено с 3.0 для баланса
VIP_FREE_PHOTOS = True
VIP_WATCH_DISCOUNT = _get_float("VIP_WATCH_DISCOUNT", 0.5)   # скидка 50%
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
    {"type": "watch", "target": 3, "reward": 10, "desc": "Посмотреть 3 видео"},
    {"type": "upload", "target": 1, "reward": 30, "desc": "Загрузить 1 видео или фото"},
    {"type": "rate", "target": 3, "reward": 6, "desc": "Оценить 3 видео"},
    {"type": "comment", "target": 2, "reward": 10, "desc": "Написать 2 комментария"},
    {"type": "react", "target": 5, "reward": 6, "desc": "Поставить 5 реакций"},
]
PREMIUM_DAILY_QUESTS = [
    {"type": "watch", "target": 10, "reward": 40, "desc": "VIP: Посмотреть 10 видео"},
    {"type": "comment", "target": 5, "reward": 30, "desc": "VIP: Написать 5 комментариев"},
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
WEEKLY_TOP1_REWARD = _get_float("WEEKLY_TOP1_REWARD", 200.0)
WEEKLY_TOP2_REWARD = _get_float("WEEKLY_TOP2_REWARD", 100.0)
WEEKLY_TOP3_REWARD = _get_float("WEEKLY_TOP3_REWARD", 60.0)

# ============================
# ПРОДВИЖЕНИЕ
# ============================
PIN_OFFER_COST = _get_float("PIN_OFFER_COST", 1000.0)
BUMP_VIDEO_COST = _get_float("BUMP_VIDEO_COST", 300.0)

# ============================
# НИКНЕЙМ
# ============================
NICKNAME_FIRST_FREE = True
NICKNAME_CHANGE_COST = _get_float("NICKNAME_CHANGE_COST", 200.0)
NICKNAME_MIN_LENGTH = 3
NICKNAME_MAX_LENGTH = 20

# ============================
# АРЕНДА (ОФФЕРЫ)
# ============================
OFFER_DEFAULT_RENT_COST_PER_DAY = _get_float("OFFER_DEFAULT_RENT_COST_PER_DAY", 10.0)
OFFER_MIN_RENT_DAYS = 1
OFFER_MAX_RENT_DAYS = 30

# ============================
# ПРОМОКОДЫ (ЗА STARS)
# ============================
PROMOCODE_CREATION_STAR_RATE = 0.5
PROMOCODE_BULK_DISCOUNT_THRESHOLD = 10
PROMOCODE_BULK_DISCOUNT_RATE = 0.8
PROMOCODE_CREATOR_BONUS_PERCENT = 5.0

PROMOCODE_MAX_AMOUNT = 100000
PROMOCODE_MAX_USES = 100
PROMOCODE_MAX_HOURS = 168

# ============================
# ДИНАМИЧЕСКИЙ КУРС ПОКУПКИ МОНЕТ
# ============================
DYNAMIC_STAR_DISCOUNT_ENABLED = True
DYNAMIC_STAR_DISCOUNT_HOURS = "17-20"
DYNAMIC_STAR_DISCOUNT_MULTIPLIER = 1.5
FIRST_PURCHASE_DAILY_BONUS = 10.0

# ============================
# УМНЫЕ ПОКАЗЫ ОФФЕРОВ
# ============================
SMART_AD_MIN_INTERVAL_MINUTES = 15
SMART_AD_LOW_BALANCE_THRESHOLD = 6.0
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
OFFER_DAILY_REWARD_CAP = _get_float("OFFER_DAILY_REWARD_CAP", 80.0)

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
LOTTERY_TICKET_PRICE = _get_float("LOTTERY_TICKET_PRICE", 30.0)
LOTTERY_NUMBERS_POOL = _get_int("LOTTERY_NUMBERS_POOL", 36)
LOTTERY_NUMBERS_PER_TICKET = _get_int("LOTTERY_NUMBERS_PER_TICKET", 6)
LOTTERY_DRAW_START_HOUR_UTC = _get_int("LOTTERY_DRAW_START_HOUR_UTC", 18)
LOTTERY_DRAW_END_HOUR_UTC = _get_int("LOTTERY_DRAW_END_HOUR_UTC", 20)
LOTTERY_DRAW_SECRET = _get_str("LOTTERY_DRAW_SECRET", "super-secret-key-12345")

# ============================
# ЛУТБОКСЫ
# ============================
ENABLE_LOOTBOXES = _get_bool("ENABLE_LOOTBOXES", True)
LOOTBOX_COIN_PRICE = _get_float("LOOTBOX_COIN_PRICE", 100.0)
LOOTBOX_STAR_PRICE = _get_int("LOOTBOX_STAR_PRICE", 15) # Снижено с 30 для привлекательности

# ============================
# АВТО-МОДЕРАЦИЯ
# ============================
ENABLE_AUTO_MODERATION = _get_bool("ENABLE_AUTO_MODERATION", True)

# Админы покупают всё бесплатно (для тестирования / эксплуатации)
ENABLE_ADMIN_FREE = _get_bool("ENABLE_ADMIN_FREE", False)

# ============================
# AI-АССИСТЕНТ (DeepSeek V4 Flash via OpenModel)
# ============================
ENABLE_AI_ASSISTANT = _get_bool("ENABLE_AI_ASSISTANT", True)
AI_ASSISTANT_API_KEY = _get_str("AI_ASSISTANT_API_KEY", "om-2iuAzLeMjkk4EuxYnw5iHKjk6pGz1oxnJxujXFf")
AI_ASSISTANT_BASE_URL = _get_str("AI_ASSISTANT_BASE_URL", "https://api.openmodel.ai")
AI_ASSISTANT_MODEL = _get_str("AI_ASSISTANT_MODEL", "deepseek-v4-flash")
AI_ASSISTANT_MAX_TOKENS = _get_int("AI_ASSISTANT_MAX_TOKENS", 2048)
AI_ASSISTANT_COOLDOWN_SEC = _get_int("AI_ASSISTANT_COOLDOWN_SEC", 5)
AI_ASSISTANT_HISTORY_LIMIT = _get_int("AI_ASSISTANT_HISTORY_LIMIT", 10)  # пар сообщений
AI_ASSISTANT_DAILY_LIMIT = _get_int("AI_ASSISTANT_DAILY_LIMIT", 50)
AI_ASSISTANT_PRICE = _get_int("AI_ASSISTANT_PRICE", 5)

# Стикерпак Кати
KATYA_STICKER_PACK = _get_str("KATYA_STICKER_PACK", "katya_by_Wseksbot")

# Лимиты чатов с Катей
KATYA_MAX_CHATS = _get_int("KATYA_MAX_CHATS", 5)
KATYA_MAX_CHATS_VIP = _get_int("KATYA_MAX_CHATS_VIP", 10)
