# Video Exchange Bot Runbook

## Start

- Install dependencies: `venv\Scripts\python -m pip install -r requirements.txt`
- Run migrations: `venv\Scripts\python -m app.migrate`
- Start bot: `venv\Scripts\python -m app.main`

## Render deploy (recommended)

- Build command:
  - `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`
- Start command:
  - `bash start_render.sh`

## Health Checks

- In Telegram as admin: `/health`
- Local syntax check: `python -m compileall app`
- Migration check: `venv\Scripts\python -m app.migrate`

## Safety Flags (.env)

- `ENABLE_SUBSCRIPTION_AUDIT=true|false`
- `ENABLE_PROMOCODES=true|false`
- `ENABLE_ADMIN_BROADCAST=true|false`
- `OFFER_SUBSCRIPTION_CHECK_INTERVAL_SECONDS=300`
- `OFFER_SUBSCRIPTION_CHECK_BATCH=200`
- `OFFER_ACTION_COOLDOWN_SECONDS=3`
- `PROMO_ACTIVATE_COOLDOWN_SECONDS=10`

## Backup and Restore

- Create backup: `venv\Scripts\python scripts\backup_db.py --db bot.db --out-dir backups`
- Restore (stop bot first): copy chosen backup file over `bot.db`

## Incident Response

- Disable risky features quickly via flags (`ENABLE_*`), restart bot.
- Re-run migration module after update.
- Check recent bot logs for:
  - `Subscription audit stats`
  - `Subscription audit warning`
  - `Migration skipped` / `Migrations finished`
