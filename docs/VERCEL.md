# Деплой на Vercel

## Что было сломано

Деплой падал на этапе сборки с ошибкой:

```
PYTHON_ENTRYPOINT_NOT_FOUND
Found app/main.py but it does not export a top-level "app", "application", or "handler" variable.
```

В репозитории не было entrypoint, который понимает Vercel: бот запускался
только как постоянно живой процесс (`python -m app.main`, long-polling).

Вторая ошибка после добавления entrypoint — `uv sync` на сборке падал на
`.python-version` с 3.11.11: такого интерпретатора у Vercel нет (поддерживаются
3.12+). Файл поднят до 3.13 — как в `Dockerfile`. На Render это не влияет:
там версия задана отдельно переменной `PYTHON_VERSION=3.11.11` в `render.yaml`.

## Что сделано

- `api/index.py` — ASGI-entrypoint для Vercel Python Runtime. Экспортирует
  `app` / `application` / `handler`, отвечает на health-check'и и принимает
  Telegram-апдейты вебхуком (`dp.feed_update`) — polling на serverless
  невозможен.
- `vercel.json` — функция `api/index.py` (maxDuration 60 c), rewrites для
  `/`, `/health`, `/healthz`, `/webhook` и регион `fra1` (Frankfurt), ближе к
  Supabase Central EU для сокращения задержек между функцией и базой.
- `app/main.py` — сборка Bot + Dispatcher вынесена в
  `create_bot_and_dispatcher()`, её переиспользуют и polling-режим
  (Render/Docker), и Vercel-вебхук. Поведение polling-режима не изменилось.
- `api/index.py` — при первом Telegram webhook идемпотентно создаёт только
  таблицы VIP-плейлистов, нужные serverless-версии бота. Базовые таблицы
  `users` и `videos` должны уже существовать; DB-пользователю нужны права
  проверять схему и создавать таблицы/индексы (или их нужно заранее создать
  через Alembic `upgrade head`).
- `scripts/set_vercel_webhook.py` — ставит/снимает Telegram-вебхук.

## Как задеплоить

1. Запушьте эту ветку / смержите в `master` (production branch проекта на Vercel).
2. В Vercel: **Project → Settings → Environment Variables** задайте минимум:
   - `BOT_TOKEN` — токен от @BotFather;
   - `DATABASE_URL` — PostgreSQL URL БД с уже созданной базовой схемой
     (`users`, `videos` и т. п.; та же, что на Render/Supabase). На первом
     Telegram webhook Vercel создаёт только таблицы VIP-плейлистов; для этого
     нужны права DDL, если миграция `vip_playlists_001` ещё не применена;
   - `ADMINS` — id администраторов через запятую;
   - при желании `WEBHOOK_PATH=/webhook` и `WEBHOOK_SECRET=<случайная строка>`.
3. Сделайте Redeploy.
4. Поставьте вебхук:

   ```bash
   BOT_TOKEN=... WEBHOOK_BASE=https://<проект>.vercel.app \
       python scripts/set_vercel_webhook.py
   ```

   Если задавали `WEBHOOK_SECRET` в Vercel, передайте его и скрипту.
5. Проверьте: `curl https://<проект>.vercel.app/health` → `{"status": "ok", ..., "configured": true}`.

## Ограничения Vercel (важно)

- **Webhook и polling взаимоисключающи.** Не держите одновременно
  Render/Docker-инстанс c polling и Vercel-вебхук — апдейты уйдут только
  одному, второй получит `TelegramConflictError`.
- **Фоновые воркеры на Vercel не работают**: лотерея, retention-рассылки,
  опрос DonationAlerts, аудит подписок, чистка видеокэша. Они живут в
  `app.main.main()` и требуют постоянного процесса.
- **Mini App страницы** (`/arcade`, `/cases`, `/lottery/live`, `/videofeed`)
  на Vercel не отдаются — это маршруты aiohttp-приложения из polling-режима.

Итог: Vercel годится как webhook-хост для диалогов бота при внешней
PostgreSQL. Полноценный боевой режим (Mini App + воркеры) — по-прежнему
Render (`render.yaml`) или Docker/VPS.
