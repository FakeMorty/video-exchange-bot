import os
from dotenv import load_dotenv

# load_dotenv loads .env file ONLY if it exists, does NOT override real env vars
load_dotenv(override=False)

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMINS: list[int] = [int(x.strip()) for x in os.getenv("ADMINS", "").split(",") if x.strip()]
WEBHOOK_BASE: str = os.getenv("WEBHOOK_BASE", "")
WEBHOOK_PATH: str = os.getenv("WEBHOOK_PATH", "/webhook")
WEBHOOK_URL: str = f"{WEBHOOK_BASE}{WEBHOOK_PATH}"
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///bot.db")

STARTING_BALANCE = 2.0
WATCH_COST = 1.0
UPLOAD_REWARD = 0.5
