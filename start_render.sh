#!/bin/bash
set -e

# Страховка: если на Render в Build Command не стоит установка зависимостей
# (ModuleNotFoundError: sqlalchemy — реальный инцидент 2026-08-04, когда
# `bash start_render.sh` случайно попал в Build Command вместо
# `pip install -r requirements.txt`), ставим их сами перед запуском.
if ! python3 -c "import sqlalchemy, aiogram" >/dev/null 2>&1; then
    echo "==> Dependencies missing — running pip install -r requirements.txt ..."
    python3 -m pip install -r requirements.txt
fi

echo "==> Running safe migrations..."
python3 migrate.py

echo "==> Starting bot..."
exec python -m app.main
