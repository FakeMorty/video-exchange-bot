from __future__ import annotations
from app.models import utc_now

import os
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import (
    BOT_TOKEN,
    DATABASE_URL,
    WEBHOOK_BASE,
    WEBHOOK_PATH,
    ENABLE_LOTTERY,
    ENABLE_LOOTBOXES,
)


@dataclass
class CheckItem:
    name: str
    ok: bool
    details: str = ""


async def run_selfcheck(session: AsyncSession) -> list[CheckItem]:
    checks: list[CheckItem] = []

    # Config sanity
    checks.append(CheckItem("config:BOT_TOKEN", bool(BOT_TOKEN), "missing" if not BOT_TOKEN else "ok"))
    checks.append(CheckItem("config:DATABASE_URL", bool(DATABASE_URL), "missing" if not DATABASE_URL else "ok"))
    checks.append(CheckItem("config:WEBHOOK_BASE", bool(WEBHOOK_BASE), "missing" if not WEBHOOK_BASE else WEBHOOK_BASE))
    checks.append(CheckItem("config:WEBHOOK_PATH", bool(WEBHOOK_PATH), "missing" if not WEBHOOK_PATH else WEBHOOK_PATH))

    # DB connectivity + basic tables presence
    try:
        await session.execute(text("SELECT 1"))
        checks.append(CheckItem("db:connect", True, "ok"))
    except Exception as e:
        checks.append(CheckItem("db:connect", False, str(e)))
        return checks

    # Migrations sanity: check a few critical tables exist
    # (SQLite + Postgres compatible check)
    table_names = [
        "users", "videos", "balance_logs", "user_action_logs",
        "trusted_uploaders", "lootbox_opens",
        "lottery_rounds", "lottery_tickets", "lottery_bets",
        "video_views", "katya_chats", "katya_messages",
    ]
    for t in table_names:
        try:
            await session.execute(text(f'SELECT 1 FROM "{t}" LIMIT 1'))
            checks.append(CheckItem(f"db:table:{t}", True, "ok"))
        except Exception as e:
            checks.append(CheckItem(f"db:table:{t}", False, f"missing or unreadable: {e}"))

    # Schema sanity: verify critical columns exist (catches drift between DB and ORM/migrations)
    critical_columns = [
        ("video_views", "watched_at"),
        ("video_views", "created_at"),
    ]
    for table_name, column_name in critical_columns:
        try:
            # Works in both SQLite and Postgres: if column missing -> raises
            await session.execute(text(f'SELECT "{column_name}" FROM "{table_name}" LIMIT 1'))
            checks.append(CheckItem(f"db:column:{table_name}.{column_name}", True, "ok"))
        except Exception as e:
            checks.append(CheckItem(f"db:column:{table_name}.{column_name}", False, str(e)))

    # Feature toggles info
    checks.append(CheckItem("feature:lottery", True, "enabled" if ENABLE_LOTTERY else "disabled"))
    checks.append(CheckItem("feature:lootboxes", True, "enabled" if ENABLE_LOOTBOXES else "disabled"))

    # Reportlab availability (PDF exports)
    try:
        import reportlab  # noqa: F401
        checks.append(CheckItem("deps:reportlab", True, "ok"))
    except Exception as e:
        checks.append(CheckItem("deps:reportlab", False, str(e)))

    # Windows font presence for Cyrillic PDF (best-effort)
    try:
        win_arial = r"C:\Windows\Fonts\arial.ttf"
        if os.name == "nt":
            checks.append(CheckItem("pdf_font:arial", os.path.exists(win_arial), win_arial))
    except Exception as e:
        checks.append(CheckItem("pdf_font:arial", False, str(e)))

    checks.append(CheckItem("time:utc", True, utc_now().strftime("%Y-%m-%d %H:%M:%S")))
    return checks


def format_selfcheck_report(items: list[CheckItem]) -> str:
    ok_count = sum(1 for x in items if x.ok)
    total = len(items)
    lines = [f"🧪 Selfcheck: {ok_count}/{total} OK", ""]
    for it in items:
        status = "✅" if it.ok else "❌"
        details = f" — {it.details}" if it.details else ""
        lines.append(f"{status} {it.name}{details}")
    return "\n".join(lines)

