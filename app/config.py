import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")
PROVIDER_TOKEN = os.getenv("PROVIDER_TOKEN", "")

ADMINS_RAW = os.getenv("ADMINS", "")
ADMINS = []
for x in ADMINS_RAW.split(","):
    x = x.strip()
    if x.isdigit():
        ADMINS.append(int(x))

STARTING_BALANCE = float(os.getenv("STARTING_BALANCE", "2"))
WATCH_COST = float(os.getenv("WATCH_COST", "1"))
UPLOAD_REWARD = float(os.getenv("UPLOAD_REWARD", "0.5"))

REFERRAL_REWARD_INVITER = float(os.getenv("REFERRAL_REWARD_INVITER", "2"))
REFERRAL_REWARD_NEW_USER = float(os.getenv("REFERRAL_REWARD_NEW_USER", "1"))

STARS_TO_COINS_RATE = float(os.getenv("STARS_TO_COINS_RATE", "2.0"))

STARS_PACKAGES = {
    "pack_1":  {"stars": 1,   "coins": 2,    "title": "2 \u043c\u043e\u043d\u0435\u0442\u044b"},
    "pack_5":  {"stars": 5,   "coins": 10,   "title": "10 \u043c\u043e\u043d\u0435\u0442"},
    "pack_10": {"stars": 10,  "coins": 20,   "title": "20 \u043c\u043e\u043d\u0435\u0442"},
    "pack_25": {"stars": 25,  "coins": 50,   "title": "50 \u043c\u043e\u043d\u0435\u0442"},
    "pack_50": {"stars": 50,  "coins": 100,  "title": "100 \u043c\u043e\u043d\u0435\u0442"},
}

# ===== MONEY PACKS =====
MONEY_PACKAGES = {
    "money_99": {"amount": 9900, "coins": 250, "title": "250 \u043c\u043e\u043d\u0435\u0442"},
    "money_199": {"amount": 19900, "coins": 600, "title": "600 \u043c\u043e\u043d\u0435\u0442"},
    "money_499": {"amount": 49900, "coins": 1800, "title": "1800 \u043c\u043e\u043d\u0435\u0442"},
}
# amount в копейках/центах для Telegram invoice

OFFER_BROADCAST_INTERVAL_HOURS = float(os.getenv("OFFER_BROADCAST_INTERVAL_HOURS", "2.5"))

# === LEVELS ===
LEVEL_XP_BASE = 100
LEVEL_XP_MULTIPLIER = 1.5
XP_PER_WATCH = 5
XP_PER_UPLOAD = 20
XP_PER_RATING = 2
XP_PER_COMMENT = 3
XP_PER_REACTION = 1
XP_PER_GAME = 3

# === VIP ===
VIP_PRICE_STARS = 50
VIP_DURATION_DAYS = 30
VIP_BONUS_MULTIPLIER = 3.0
VIP_FREE_PHOTOS = True
VIP_WATCH_DISCOUNT = 0.5

# === GAMES ===
LOOTBOX_COST = 5
LOOTBOX_REWARDS = [
    (0.30, 1),
    (0.25, 3),
    (0.20, 5),
    (0.12, 10),
    (0.08, 20),
    (0.04, 50),
    (0.01, 100),
]

DICE_MIN_BET = 1
DICE_MAX_BET = 50

# === QUESTS ===
DAILY_QUESTS = [
    {"type": "watch", "target": 3, "reward": 2, "desc": "\u041f\u043e\u0441\u043c\u043e\u0442\u0440\u0438 3 \u0432\u0438\u0434\u0435\u043e"},
    {"type": "upload", "target": 1, "reward": 3, "desc": "\u0417\u0430\u0433\u0440\u0443\u0437\u0438 1 \u043a\u043e\u043d\u0442\u0435\u043d\u0442"},
    {"type": "rate", "target": 3, "reward": 1, "desc": "\u041e\u0446\u0435\u043d\u0438 3 \u0432\u0438\u0434\u0435\u043e"},
    {"type": "comment", "target": 2, "reward": 2, "desc": "\u041e\u0441\u0442\u0430\u0432\u044c 2 \u043a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u044f"},
    {"type": "react", "target": 5, "reward": 1, "desc": "\u041f\u043e\u0441\u0442\u0430\u0432\u044c 5 \u0440\u0435\u0430\u043a\u0446\u0438\u0439"},
]

PREMIUM_DAILY_QUESTS = [
    {"type": "watch", "target": 10, "reward": 8, "desc": "VIP: \u041f\u043e\u0441\u043c\u043e\u0442\u0440\u0438 10 \u0432\u0438\u0434\u0435\u043e"},
    {"type": "comment", "target": 5, "reward": 5, "desc": "VIP: \u041e\u0441\u0442\u0430\u0432\u044c 5 \u043a\u043e\u043c\u043c\u0435\u043d\u0442\u043e\u0432"},
]

REACTION_TYPES = ["\U0001f525", "\u2764\ufe0f", "\U0001f602", "\U0001f44d", "\U0001f4af"]

# === ANTI-SPAM COMMENTS ===
COMMENTS_PER_10_MIN = int(os.getenv("COMMENTS_PER_10_MIN", "5"))
COMMENT_MIN_INTERVAL_SEC = int(os.getenv("COMMENT_MIN_INTERVAL_SEC", "15"))

# === TG LOGGING ===
LOG_CHAT_ID = os.getenv("LOG_CHAT_ID", "")

# === WEEKLY REWARDS ===
WEEKLY_TOP1_REWARD = float(os.getenv("WEEKLY_TOP1_REWARD", "25"))
WEEKLY_TOP2_REWARD = float(os.getenv("WEEKLY_TOP2_REWARD", "15"))
WEEKLY_TOP3_REWARD = float(os.getenv("WEEKLY_TOP3_REWARD", "10"))

# === MONETIZATION ===
PIN_OFFER_COST = float(os.getenv("PIN_OFFER_COST", "100"))
BUMP_VIDEO_COST = float(os.getenv("BUMP_VIDEO_COST", "25"))
