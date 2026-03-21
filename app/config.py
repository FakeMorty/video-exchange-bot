import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")

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

OFFER_BROADCAST_INTERVAL_HOURS = float(os.getenv("OFFER_BROADCAST_INTERVAL_HOURS", "2.5"))
