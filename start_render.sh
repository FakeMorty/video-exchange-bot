#!/bin/bash
set -e

echo "==> Running safe migrations..."
python3 migrate.py

echo "==> Starting bot..."
exec python -m app.main
