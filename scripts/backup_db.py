from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Create SQLite backup file.")
    parser.add_argument("--db", default="bot.db", help="Path to source sqlite DB")
    parser.add_argument("--out-dir", default="backups", help="Directory for backups")
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    if not db_path.exists():
        raise SystemExit(f"Database file not found: {db_path}")

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = out_dir / f"{db_path.stem}_{stamp}{db_path.suffix}"
    shutil.copy2(db_path, backup_path)
    print(f"Backup created: {backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
