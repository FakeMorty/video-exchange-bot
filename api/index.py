"""Vercel serverless entrypoint (ASGI) — webhook-режим бота.

Почему отдельный файл и почему webhook:
Vercel — serverless-платформа: там нет постоянно работающего процесса,
поэтому long-polling (`dp.start_polling` в `app/main.py`) и фоновые
воркеры (лотерея, retention, DonationAlerts-опрос и т.д.) на Vercel
работать не могут в принципе. Раньше в репозитории не было ни одного
entrypoint, который понимает Vercel, и деплой падал с ошибкой:

    PYTHON_ENTRYPOINT_NOT_FOUND:
    Found app/main.py but it does not export a top-level
    "app", "application", or "handler" variable.

Этот модуль экспортирует ASGI-приложение `app` и обрабатывает каждый
Telegram-апдейт отдельным вызовом функции через webhook:

    POST {WEBHOOK_PATH|/webhook}  ->  dp.feed_update(bot, update)

Что нужно для работы (Environment Variables в дашборде Vercel):
    BOT_TOKEN      — токен от @BotFather (обязательно)
    DATABASE_URL   — PostgreSQL async URL уже смигрированной БД (обязательно)
    ADMINS         — id администраторов через запятую
    WEBHOOK_PATH   — путь вебхука (по умолчанию /webhook)
    WEBHOOK_SECRET — необязательный секрет; если задан, он же должен быть
                     передан Telegram при setWebhook и сверяется с
                     заголовком X-Telegram-Bot-Api-Secret-Token.

После деплоя вебхук ставится один раз скриптом:
    WEBHOOK_BASE=https://<проект>.vercel.app BOT_TOKEN=... \\
        python scripts/set_vercel_webhook.py

ВАЖНО: webhook и polling взаимоисключающи. Если бот в этот же момент
запущен на Render/Docker через polling, Telegram будет отдавать апдейты
только одному из них, а polling-копия получит TelegramConflictError.
Оставляйте один боевой инстанс.
"""

from __future__ import annotations

import json
import os

_bot = None
_dp = None


def _get_bot_and_dispatcher():
    """Ленивая (и переиспользуемая между тёплыми вызовами) сборка bot/dp."""
    global _bot, _dp
    if _bot is None or _dp is None:
        # Импорт здесь, а не на уровне модуля: импорт app.main тяжёлый,
        # а health-check'и должны отвечать даже без настроенных секретов.
        from app.main import create_bot_and_dispatcher

        _bot, _dp = create_bot_and_dispatcher()
    return _bot, _dp


async def _send(send, status: int, body: bytes, content_type: str = "application/json") -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", content_type.encode()),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _json(send, status: int, payload: dict) -> None:
    await _send(send, status, json.dumps(payload, ensure_ascii=False).encode("utf-8"))


async def _read_body(receive) -> bytes:
    chunks: list[bytes] = []
    while True:
        message = await receive()
        if message["type"] == "http.request":
            chunks.append(message.get("body", b""))
            if not message.get("more_body"):
                break
        elif message["type"] == "http.disconnect":
            break
    return b"".join(chunks)


async def app(scope, receive, send):
    """ASGI-приложение, которое ждёт Vercel Python Runtime."""
    if scope["type"] == "lifespan":
        # Vercel не держит процесс между вызовами, lifespan нам не нужен:
        # просто подтверждаем старт/стоп, чтобы рантайм не падал.
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    if scope["type"] != "http":
        return

    method = scope.get("method", "GET")
    path = scope.get("path", "/")
    webhook_path = os.getenv("WEBHOOK_PATH", "/webhook").strip() or "/webhook"

    # Health-check: должен отвечать 200 даже без секретов, иначе в дашборде
    # Vercel нельзя отличить «функция жива» от «не заданы env vars».
    if method == "GET" and path in ("/", "/health", "/healthz", "/api/health"):
        configured = bool(os.getenv("BOT_TOKEN")) and bool(os.getenv("DATABASE_URL"))
        await _json(
            send,
            200,
            {
                "status": "ok",
                "service": "video-exchange-bot",
                "mode": "vercel-webhook",
                "configured": configured,
                "webhook_path": webhook_path,
                **(
                    {}
                    if configured
                    else {
                        "hint": "Set BOT_TOKEN and DATABASE_URL in Vercel "
                        "Project Settings -> Environment Variables, then redeploy."
                    }
                ),
            },
        )
        return

    if method == "GET" and path == "/api/setup-webhook":
        # Одноразовая установка вебхука прямо из функции Vercel (у песочниц и
        # локальных машин часто нет прямого доступа к api.telegram.org).
        # Защита: ?key= должен совпасть с WEBHOOK_SECRET из env vars.
        import hmac as _hmac

        expected = os.getenv("WEBHOOK_SECRET", "").strip()
        query = scope.get("query_string", b"").decode("latin-1")
        params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        if not expected or not _hmac.compare_digest(params.get("key", ""), expected):
            await _json(send, 403, {"ok": False, "error": "bad key"})
            return
        if not os.getenv("BOT_TOKEN"):
            await _json(send, 503, {"ok": False, "error": "BOT_TOKEN is not set"})
            return
        base = os.getenv("WEBHOOK_BASE", "").strip().rstrip("/")
        if not base.startswith("https://"):
            await _json(send, 503, {"ok": False, "error": "WEBHOOK_BASE must be https:// URL"})
            return
        try:
            bot, _dp_unused = _get_bot_and_dispatcher()
            await bot.set_webhook(
                url=f"{base}{webhook_path}",
                secret_token=expected,
                drop_pending_updates=False,
            )
            info = await bot.get_webhook_info()
            await _json(
                send,
                200,
                {
                    "ok": True,
                    "webhook_url": info.url,
                    "pending_update_count": info.pending_update_count,
                    "last_error_message": info.last_error_message,
                },
            )
        except Exception as exc:
            print(f"setup-webhook error: {exc!r}", flush=True)
            await _json(send, 502, {"ok": False, "error": "setWebhook failed, see Vercel logs"})
        return

    if method == "POST" and path in (webhook_path, "/webhook", "/api/webhook"):
        if not os.getenv("BOT_TOKEN"):
            await _json(send, 503, {"ok": False, "error": "BOT_TOKEN is not set"})
            return

        secret = os.getenv("WEBHOOK_SECRET", "").strip()
        if secret:
            headers = {
                k.decode("latin-1").lower(): v.decode("latin-1")
                for k, v in scope.get("headers", [])
            }
            if headers.get("x-telegram-bot-api-secret-token") != secret:
                await _json(send, 403, {"ok": False, "error": "bad secret token"})
                return

        raw = await _read_body(receive)
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            await _json(send, 400, {"ok": False, "error": "invalid json"})
            return

        try:
            from aiogram.types import Update

            bot, dp = _get_bot_and_dispatcher()
            update = Update.model_validate(data, context={"bot": bot})
            await dp.feed_update(bot, update)
        except Exception as exc:  # не роняем функцию: Telegram иначе ретраит штормом
            print(f"vercel webhook error: {exc!r}", flush=True)
            await _json(send, 200, {"ok": False, "error": "update processing failed"})
            return

        await _json(send, 200, {"ok": True})
        return

    await _json(
        send,
        404,
        {
            "ok": False,
            "error": "not found",
            "hint": "On Vercel this bot serves only health-checks and the "
            "Telegram webhook. Mini App pages and background workers "
            "require the long-lived host (see render.yaml / Dockerfile).",
        },
    )


# Vercel также понимает имена `application` / `handler` — даём алиасы,
# чтобы рантайм нашёл entrypoint независимо от режима детекта.
application = app
handler = app
