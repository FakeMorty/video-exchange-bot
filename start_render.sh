#!/bin/bash
set -e

# Запуск миграций
alembic upgrade head

# Запуск бота
python -m app.main
