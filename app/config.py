import os
from dotenv import load_dotenv

load_dotenv(override=False)

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMINS: list[int] = [int(x.strip()) for x in os.getenv("ADMINS", "").split(",") if x.strip()]
WEBHOOK_BASE: str = os.getenv("WEBHOOK_BASE", "")
WEBHOOK_PATH: str = os.getenv("WEBHOOK_PATH", "/webhook")
WEBHOOK_URL: str = f"{WEBHOOK_BASE}{WEBHOOK_PATH}"

DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///bot.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://") and "+asyncpg" not in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

STARTING_BALANCE = 2.0
WATCH_COST = 1.0
UPLOAD_REWARD = 0.5

REFERRAL_REWARD_INVITER = 2.0
REFERRAL_REWARD_NEW_USER = 1.0

STARS_PACKAGES = {
    "stars_50": {"title": "50 монет", "stars": 50, "coins": 50},
    "stars_120": {"title": "120 монет", "stars": 100, "coins": 120},
    "stars_350": {"title": "350 монет", "stars": 250, "coins": 350},
}
