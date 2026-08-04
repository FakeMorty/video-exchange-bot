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
STARTING_BALANCE = _get_float("STARTING_BALANCE", 150.0)

# Просмотр видео
WATCH_COST = _get_float("WATCH_COST", 10.0)

# Награда за одобренную загрузку (базовая)
UPLOAD_REWARD = _get_float("UPLOAD_REWARD", 10.0)
PHOTO_UPLOAD_REWARD = _get_float("PHOTO_UPLOAD_REWARD", 10.0)
CONTENT_VIEWS_MILESTONE_THRESHOLD = _get_int("CONTENT_VIEWS_MILESTONE_THRESHOLD", 10)
VIDEO_VIEWS_MILESTONE_REWARD = _get_float("VIDEO_VIEWS_MILESTONE_REWARD", 10.0)
PHOTO_VIEWS_MILESTONE_REWARD = _get_float("PHOTO_VIEWS_MILESTONE_REWARD", 10.0)
CONTENT_QUALITY_MIN_AVG_RATING = _get_float("CONTENT_QUALITY_MIN_AVG_RATING", 4.0)
CONTENT_QUALITY_MIN_RATINGS = _get_int("CONTENT_QUALITY_MIN_RATINGS", 5)
CONTENT_QUALITY_BONUS = _get_float("CONTENT_QUALITY_BONUS", 10.0)

# Рефералы
REFERRAL_REWARD_INVITER = _get_float("REFERRAL_REWARD_INVITER", 20.0)
REFERRAL_REWARD_NEW_USER = _get_float("REFERRAL_REWARD_NEW_USER", 10.0)
REFERRAL_MILESTONES = {
    1: {"type": "coins", "amount": 20.0, "desc": "20 монет"},
    3: {"type": "coins", "amount": 30.0, "desc": "30 монет"},
    5: {"type": "coins", "amount": 50.0, "desc": "50 монет"},
    10: {"type": "coins", "amount": 100.0, "desc": "100 монет"},
}

# Курс Stars → монеты
STARS_TO_COINS_RATE = _get_float("STARS_TO_COINS_RATE", 10.0)

# Viewer-friendly пакеты Stars
# ── Воронка оплаты: старт-пак первого платежа (низкий порог входа) ──
# Показывается только тем, у кого ещё не было оплаченных платежей.
# Цена фиксированная, скидки событий/перков на него НЕ действуют.
STARTER_PACK_STARS = _get_int("STARTER_PACK_STARS", 9)
STARTER_PACK_COINS = _get_int("STARTER_PACK_COINS", 500)
# Через сколько просмотров за день показать «залипшему» юзеру оффер первого платежа
UPSELL_AFTER_VIEWS = _get_int("UPSELL_AFTER_VIEWS", 8)
# ── Удержание: онбординг-цепочка и бонус за возвращение ──
ONBOARDING_DRIP_ENABLED = _get_bool("ONBOARDING_DRIP_ENABLED", True)
COMEBACK_BONUS_AMOUNT = _get_float("COMEBACK_BONUS_AMOUNT", 100.0)
COMEBACK_INACTIVE_MIN_HOURS = _get_int("COMEBACK_INACTIVE_MIN_HOURS", 48)
COMEBACK_INACTIVE_MAX_HOURS = _get_int("COMEBACK_INACTIVE_MAX_HOURS", 96)
COMEBACK_COOLDOWN_DAYS = _get_int("COMEBACK_COOLDOWN_DAYS", 7)
# ── Контент: дневной лимит загрузок видео на автора (0 = без лимита) ──
DAILY_VIDEO_UPLOAD_LIMIT = _get_int("DAILY_VIDEO_UPLOAD_LIMIT", 100)

STARS_PACKAGES = {
    "starterpack": {"stars": STARTER_PACK_STARS, "coins": STARTER_PACK_COINS, "title": f"Старт-пак: {STARTER_PACK_COINS} монет"},
    "pack_50":  {"stars": 50,  "coins": 500,  "title": "500 монет"},
    "pack_100": {"stars": 100, "coins": 1000, "title": "1 000 монет"},
    "pack_200": {"stars": 200, "coins": 2200, "title": "2 200 монет"},
}

# Пакеты за реальные деньги (Примерно 1 Star = 2 RUB)
MONEY_PACKAGES = {
    "money_99":  {"amount": 9900,  "coins": 700,   "title": "700 монет"},
    "money_199": {"amount": 19900, "coins": 1600,   "title": "1 600 монет"},
    "money_499": {"amount": 49900, "coins": 4400,  "title": "4 400 монет"},
}

# Интервал показа офферов
OFFER_BROADCAST_INTERVAL_HOURS = _get_float("OFFER_BROADCAST_INTERVAL_HOURS", 2.5)
OFFER_UNSUBSCRIBE_GRACE_MINUTES = _get_int("OFFER_UNSUBSCRIBE_GRACE_MINUTES", 15)

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
NICKNAME_MIN_LENGTH = 4
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

# Секслото
# Расписание фиксируем в коде: каждый день в 20:00 по МСК.
# Длительность розыгрыша = LOTTERY_NUMBERS_PER_TICKET * LOTTERY_SECONDS_PER_BALL.
ENABLE_LOTTERY = _get_bool("ENABLE_LOTTERY", True)
LOTTERY_TICKET_PRICE = _get_float("LOTTERY_TICKET_PRICE", 30.0)
LOTTERY_NUMBERS_POOL = _get_int("LOTTERY_NUMBERS_POOL", 36)
LOTTERY_NUMBERS_PER_TICKET = _get_int("LOTTERY_NUMBERS_PER_TICKET", 6)
LOTTERY_MATCH2_REWARD = _get_float("LOTTERY_MATCH2_REWARD", 10.0)
LOTTERY_MATCH3_REWARD = _get_float("LOTTERY_MATCH3_REWARD", 20.0)
LOTTERY_WEEKLY_LEADERBOARD_REWARDS = {
    1: _get_float("LOTTERY_WEEKLY_LEADERBOARD_REWARD_1", 100.0),
    2: _get_float("LOTTERY_WEEKLY_LEADERBOARD_REWARD_2", 50.0),
    3: _get_float("LOTTERY_WEEKLY_LEADERBOARD_REWARD_3", 20.0),
}
LOTTERY_DRAW_HOUR_MSK = _get_int("LOTTERY_DRAW_HOUR_MSK", 20)
LOTTERY_SECONDS_PER_BALL = _get_int("LOTTERY_SECONDS_PER_BALL", 15)
LOTTERY_DRAW_SECRET = _get_str("LOTTERY_DRAW_SECRET", "")

# ============================
# КОСМИЧЕСКАЯ АРКАДА (риск-игра с множителем, a-la Galaga)
# ============================
ENABLE_ARCADE = _get_bool("ENABLE_ARCADE", True)
ARCADE_MIN_BET = _get_float("ARCADE_MIN_BET", 10.0)
ARCADE_MAX_BET = _get_float("ARCADE_MAX_BET", 250.0)
# Максимальный множитель ставки; при достижении выигрыш забирается автоматически.
ARCADE_MAX_MULTIPLIER = _get_float("ARCADE_MAX_MULTIPLIER", 50.0)
# Дневной кап ЧИСТОЙ прибыли игрока в аркаде (защита экономики: «чтобы не сильно богатели»).
ARCADE_DAILY_PROFIT_CAP = _get_float("ARCADE_DAILY_PROFIT_CAP", 500.0)
# Через сколько минут «зависший» забег считается протухшим и ставка возвращается.
ARCADE_RUN_TTL_MINUTES = _get_int("ARCADE_RUN_TTL_MINUTES", 30)
# --- Математика волн (жёстко в коде, см. app/arcade.py) ---
# Шанс уничтожить волну: 0.72 для первой, -4.5 п.п. за волну, пол 0.30.
# Шаг множителя: x1.35 за первую волну, +0.05 за каждую следующую, потолок x1.80.
# Итог: ранние волны около-безубыточны (весело), поздние — с растущим преимуществом бота.

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
AI_ASSISTANT_API_KEY = _get_str("AI_ASSISTANT_API_KEY", "")
AI_ASSISTANT_BASE_URL = _get_str("AI_ASSISTANT_BASE_URL", "https://api.openmodel.ai")
AI_ASSISTANT_MODEL = _get_str("AI_ASSISTANT_MODEL", "deepseek-v4-flash")
AI_ASSISTANT_MAX_TOKENS = _get_int("AI_ASSISTANT_MAX_TOKENS", 2048)
AI_ASSISTANT_COOLDOWN_SEC = _get_int("AI_ASSISTANT_COOLDOWN_SEC", 5)
AI_ASSISTANT_HISTORY_LIMIT = _get_int("AI_ASSISTANT_HISTORY_LIMIT", 10)  # пар сообщений
AI_ASSISTANT_DAILY_LIMIT = _get_int("AI_ASSISTANT_DAILY_LIMIT", 50)
AI_ASSISTANT_PRICE = _get_int("AI_ASSISTANT_PRICE", 5)

# Стикерпак Кати, Софы и Сани
KATYA_STICKER_PACK = _get_str("KATYA_STICKER_PACK", "katya_by_Wseksbot")
SOFA_STICKER_PACK = _get_str("SOFA_STICKER_PACK", "sofa_by_Wseksbot")
SANYA_STICKER_PACK = _get_str("SANYA_STICKER_PACK", "sanya_by_Wseksbot")

# Лимиты чатов с Катей
KATYA_MAX_CHATS = _get_int("KATYA_MAX_CHATS", 5)
KATYA_MAX_CHATS_VIP = _get_int("KATYA_MAX_CHATS_VIP", 10)

# ============================
# ЕЖЕНЕДЕЛЬНАЯ ХАЛЯВА (СЕКРЕТНОЕ СЛОВО)
# ============================
# День недели (0 - Понедельник, 1 - Вторник ... 6 - Воскресенье)
WEEKLY_PROMO_DAY = _get_int("WEEKLY_PROMO_DAY", 4) # Пятница
WEEKLY_PROMO_HOUR = _get_int("WEEKLY_PROMO_HOUR", 18)
WEEKLY_PROMO_AMOUNT = _get_float("WEEKLY_PROMO_AMOUNT", 100.0)
WEEKLY_PROMO_USES = _get_int("WEEKLY_PROMO_USES", 999999)
