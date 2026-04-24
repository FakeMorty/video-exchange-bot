#!/usr/bin/env bash
set -euo pipefail

python -m pip install --upgrade pip

# Optional but useful sanity check (won't block runtime if it prints warnings)
python -m compileall app >/dev/null 2>&1 || true

# Always run migrations before starting
python -m app.migrate

exec python -m app.main

