import asyncio
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _run(cmd: list[str], title: str) -> None:
    print(f"[SMOKE] {title}: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0:
        if result.stderr.strip():
            print(result.stderr.strip())
        raise RuntimeError(f"{title} failed with exit code {result.returncode}")


async def _selfcheck() -> None:
    from app.db import async_session
    from app.selfcheck import run_selfcheck

    print("[SMOKE] selfcheck")
    async with async_session() as session:
        items = await run_selfcheck(session)
    failed = [x for x in items if not x.ok]
    if failed:
        details = "; ".join(f"{x.name}: {x.details}" for x in failed)
        raise RuntimeError(f"selfcheck failed: {details}")
    print(f"[SMOKE] selfcheck OK ({len(items)}/{len(items)})")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    load_dotenv(PROJECT_ROOT / ".env")
    if not os.getenv("DATABASE_URL"):
        raise RuntimeError("DATABASE_URL is required for smoke checks")

    _run([sys.executable, "-m", "compileall", "-q", "app", "alembic", "scripts"], "compileall")
    _run([sys.executable, "-m", "alembic", "current"], "alembic current")
    _run([sys.executable, "-m", "alembic", "upgrade", "head"], "alembic upgrade head")
    asyncio.run(_selfcheck())
    print("[SMOKE] ALL CHECKS PASSED")


if __name__ == "__main__":
    main()

