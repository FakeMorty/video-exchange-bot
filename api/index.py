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

ИЛИ напрямую из Vercel (без локального доступа к api.telegram.org):
    GET /api/setup-webhook?key=<WEBHOOK_SECRET>
    (требует WEBHOOK_SECRET и WEBHOOK_BASE в env Vercel)

ВАЖНО: webhook и polling взаимоисключающи. Если бот в этот же момент
запущен на Render/Docker через polling, Telegram будет отдавать апдейты
только одному из них, а polling-копия получит TelegramConflictError.
Оставляйте один боевой инстанс.

Vercel rewrite-роутинг (фикс v3.29.2):
Vercel rewrites вида {\"source\": \"/(.*)\", \"destination\": \"/api/index\"}
заставляют Python-runtime видеть в ASGI scope.path всегда \"/api/index\",
а оригинальный путь теряется → все хендлеры 404. Поэтому vercel.json
передаёт оригинальный путь как `?__vercel_path=/$1` (с мержем query),
а этот модуль восстанавливает его через _resolve_path(scope) с
фолбэком на заголовки Vercel (x-vercel-original-path и др.) и
совместимостью со старыми прямыми вызовами.
"""

from __future__ import annotations

import json
import os
import urllib.parse

_bot = None
_dp = None
_playlist_schema_ready = False
_bot_commands_ready = False


async def _ensure_playlist_schema() -> None:
    """Create only the new playlist tables on the first Vercel webhook.

    Vercel's ASGI entrypoint does not run ``app.main.on_startup`` or the
    Render migration script. The tables are also covered by Alembic for the
    always-on deployment; this small idempotent check lets the serverless
    webhook activate the feature without requiring an out-of-band shell.
    """
    global _playlist_schema_ready
    if _playlist_schema_ready:
        return

    from sqlalchemy import inspect
    from app.db import engine
    from app.models import UserPlaylist, UserPlaylistItem

    def create_tables(sync_conn):
        UserPlaylist.metadata.create_all(
            sync_conn,
            tables=[UserPlaylist.__table__, UserPlaylistItem.__table__],
            checkfirst=True,
        )

    try:
        async with engine.begin() as conn:
            await conn.run_sync(create_tables)
    except Exception:
        # Two serverless instances may cold-start concurrently: one can create
        # a table after the other's checkfirst inspection. Treat that narrow
        # race as success only when both tables now exist; otherwise propagate.
        async with engine.connect() as conn:
            tables_exist = await conn.run_sync(
                lambda sync_conn: (
                    inspect(sync_conn).has_table("user_playlists")
                    and inspect(sync_conn).has_table("user_playlist_items")
                )
            )
        if not tables_exist:
            raise
    _playlist_schema_ready = True


async def _ensure_bot_commands(bot) -> None:
    """Set the native Telegram command menu once per serverless instance.

    Vercel does not run ``app.main.on_startup``, so the command menu is
    applied lazily on the first webhook call of a warm instance. Failures
    are non-fatal: the flag stays unset and the next call retries.
    """
    global _bot_commands_ready
    if _bot_commands_ready:
        return
    try:
        from app.main import apply_bot_commands

        await apply_bot_commands(bot)
        _bot_commands_ready = True
    except Exception as exc:
        print(f"vercel set_my_commands error: {exc!r}", flush=True)


def _get_bot_and_dispatcher():
    """Ленивая (и переиспользуемая между тёплыми вызовами) сборка bot/dp."""
    global _bot, _dp
    if _bot is None or _dp is None:
        # Импорт здесь, а не на уровне модуля: импорт app.main тяжёлый,
        # а health-check'и должны отвечать даже без настроенных секретов.
        from app.main import create_bot_and_dispatcher

        _bot, _dp = create_bot_and_dispatcher()
    return _bot, _dp


def _resolve_path(scope) -> str:
    """Восстанавливает оригинальный путь запроса при Vercel rewrite.

    Vercel при rewrite `/(.*) -> /api/index?__vercel_path=/$1` передаёт
    оригинальный путь в query-параметре `__vercel_path` (Vercel мержит
    query оригинального запроса и destination). На случай смены формата
    также проверяем заголовки, которые Vercel может прокидывать
    (x-matched-path, x-forwarded-uri и т.д.), и делаем фолбэк на
    scope[\"path\"] с нормализацией \"/api/index\" -> \"/\" для
    совместимости с прямыми вызовами без rewrite.
    """
    # 1) Приоритет: query-параметр __vercel_path (основной механизм v3.29.2)
    qs_bytes = scope.get("query_string", b"")
    try:
        qs_str = qs_bytes.decode("latin-1") if isinstance(qs_bytes, (bytes, bytearray)) else str(qs_bytes)
    except Exception:
        qs_str = ""
    if qs_str:
        try:
            parsed = urllib.parse.parse_qs(qs_str, keep_blank_values=True)
            for key in ("__vercel_path", "__path", "__route", "__vpath", "_vercel_path"):
                if key in parsed and parsed[key]:
                    val = parsed[key][0]
                    if not val:
                        continue
                    # parse_qs уже декодирует %2F etc.; гарантируем ведущий слэш
                    if not val.startswith("/"):
                        val = "/" + val
                    # нормализуем // -> /
                    if val.startswith("//"):
                        val = "/" + val.lstrip("/")
                    return val
        except Exception:
            pass

    # 2) Фолбэк: заголовки, которые Vercel может выставлять при rewrite
    try:
        headers = {}
        for hk, hv in scope.get("headers", []):
            try:
                headers[hk.decode("latin-1").lower()] = hv.decode("latin-1")
            except Exception:
                continue
        for hk in (
            "x-vercel-original-path",
            "x-vercel-invoke-path",
            "x-vercel-matched-path",
            "x-matched-path",
            "x-forwarded-uri",
            "x-rewrite-url",
            "x-middleware-rewrite",
            "x-invoke-path",
        ):
            if hk in headers and headers[hk]:
                raw = headers[hk].split("?")[0].strip()
                if raw and raw not in ("/api/index", "/api/index.py"):
                    if not raw.startswith("/"):
                        raw = "/" + raw
                    return raw
    except Exception:
        pass

    # 3) Прямой путь из scope (локальный прогон без rewrite, старый vercel.json)
    path = scope.get("path", "/") or "/"
    # Если Vercel прислал destination без preservation старого формата — считаем это health
    if path in ("/api/index", "/api/index.py"):
        return "/"
    return path


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
    # Восстанавливаем оригинальный путь с учётом Vercel rewrite (v3.29.2)
    path = _resolve_path(scope)
    webhook_path = os.getenv("WEBHOOK_PATH", "/webhook").strip() or "/webhook"

    # Health-check: должен отвечать 200 даже без секретов, иначе в дашборде
    # Vercel нельзя отличить «функция жива» от «не заданы env vars».
    if method == "GET" and path in ("/", "/health", "/healthz", "/api/health", "/api/index"):
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
        # Парсим query надёжно через urllib (Vercel мержит ?__vercel_path и ?key)
        query = scope.get("query_string", b"").decode("latin-1") if scope.get("query_string") else ""
        parsed_qs = urllib.parse.parse_qs(query, keep_blank_values=True)
        # parse_qs возвращает list значений; берём первое
        key_val = parsed_qs.get("key", [""])[0] if parsed_qs.get("key") else ""
        # фолбэк для старых прямых парсингов без parse_qs
        if not key_val and query:
            try:
                params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
                key_val = params.get("key", "")
            except Exception:
                key_val = ""
        if not expected or not _hmac.compare_digest(key_val, expected):
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

    if method == "POST" and path in (webhook_path, "/webhook", "/api/webhook", "/api/index"):
        # /api/index как POST допускаем для совместимости, если rewrite без preservation
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
            await _ensure_playlist_schema()
            await _ensure_bot_commands(bot)
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
            "path": path,
            "hint": "On Vercel this bot serves only health-checks and the "
            "Telegram webhook. Mini App pages and background workers "
            "require the long-lived host (see render.yaml / Dockerfile).",
        },
    )


# Vercel также понимает имена `application` / `handler` — даём алиасы,
# чтобы рантайм нашёл entrypoint независимо от режима детекта.
application = app
handler = app
