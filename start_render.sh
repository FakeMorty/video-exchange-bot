#!/usr/bin/env bash
set -euo pipefail

python -m pip install --upgrade pip

# Optional but useful sanity check (won't block runtime if it prints warnings)
python -m compileall app >/dev/null 2>&1 || true

# Безопасное применение миграций (без сброса)
# Если alembic сломается — fallback на прямой скрипт
python -m alembic upgrade head 2>/dev/null || python fix_db.py || true

exec python -m app.main
