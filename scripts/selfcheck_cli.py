import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.db import async_session
from app.selfcheck import run_selfcheck, format_selfcheck_report


async def _main() -> None:
    async with async_session() as session:
        items = await run_selfcheck(session)
        print(format_selfcheck_report(items))


if __name__ == "__main__":
    asyncio.run(_main())

