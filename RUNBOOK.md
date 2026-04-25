# Руководство по Video Exchange Bot

## Запуск

- Установить зависимости: `venv\Scripts\python -m pip install -r requirements.txt`
- Применить миграции: `venv\Scripts\python -m alembic upgrade head`
- Запустить бота: `venv\Scripts\python -m app.main`

### Быстрый сценарий Alembic (просто)

- Разово для существующей БД (уже в проде): `venv\Scripts\python -m alembic stamp head`
- Новая миграция после изменений в моделях:
  - `venv\Scripts\python -m alembic revision --autogenerate -m "описание изменений"`
  - проверить файл в `alembic\versions\...`
  - `venv\Scripts\python -m alembic upgrade head`
- Проверить текущую ревизию: `venv\Scripts\python -m alembic current`

> Для корректного autogenerate запускайте его на том же типе БД, что и в проде (Postgres), а не на локальном SQLite.

## Деплой на Render (рекомендуется)

- Команда сборки:
  - `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`
- Команда старта:
  - `bash start_render.sh`

## Проверки работоспособности

- В Telegram под админом: `/health`
- Локальная проверка синтаксиса: `python -m compileall app`
- Проверка миграций: `venv\Scripts\python -m alembic current`
- Полный smoke-check: `venv\Scripts\python scripts\release_smoke_check.py`

## Защитные флаги (.env)

- `ENABLE_SUBSCRIPTION_AUDIT=true|false`
- `ENABLE_PROMOCODES=true|false`
- `ENABLE_ADMIN_BROADCAST=true|false`
- `OFFER_SUBSCRIPTION_CHECK_INTERVAL_SECONDS=300`
- `OFFER_SUBSCRIPTION_CHECK_BATCH=200`
- `OFFER_ACTION_COOLDOWN_SECONDS=3`
- `PROMO_ACTIVATE_COOLDOWN_SECONDS=10`

## Резервное копирование и восстановление

- Создать бэкап: `venv\Scripts\python scripts\backup_db.py --db bot.db --out-dir backups`
- Восстановить (сначала остановить бота): заменить файл `bot.db` выбранной копией

## Действия при инциденте

- Быстро отключить рискованные функции через флаги (`ENABLE_*`) и перезапустить бота.
- После обновления снова применить миграции: `venv\Scripts\python -m alembic upgrade head`
- Проверить последние логи бота:
  - `Subscription audit stats`
  - `Subscription audit warning`
  - ошибки/предупреждения Alembic по миграциям
