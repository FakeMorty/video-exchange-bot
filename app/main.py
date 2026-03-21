import asyncio
import logging
import os
import traceback

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import BOT_TOKEN, WEBHOOK_URL, WEBHOOK_PATH, WEBHOOK_BASE
from app.db import init_db, reset_db
from app.user_handlers import router as user_router
from app.admin_handlers import router as admin_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
dp.include_router(admin_router)
dp.include_router(user_router)

webhook_keeper_task = None


async def ensure_webhook():
    try:
        info = await bot.get_webhook_info()
        if info.url != WEBHOOK_URL:
            logger.warning(f"[WEBHOOK_KEEPER] Webhook lost! was='{info.url}' expected='{WEBHOOK_URL}'")
            await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=False)
            logger.info(f"[WEBHOOK_KEEPER] Webhook restored: {WEBHOOK_URL}")
        return True
    except Exception as e:
        logger.error(f"[WEBHOOK_KEEPER] Error: {e}")
        return False


async def webhook_keeper():
    while True:
        await asyncio.sleep(30)
        await ensure_webhook()


async def handle_webhook(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        update = Update.model_validate(data, context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception as e:
        logger.error(f"[WEBHOOK] ERROR: {e}")
        logger.error(traceback.format_exc())

    return web.Response(text="ok")


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def handle_debug_webhook(request: web.Request) -> web.Response:
    try:
        info = await bot.get_webhook_info()
        return web.json_response({
            "url": info.url,
            "pending_update_count": info.pending_update_count,
            "last_error_date": str(info.last_error_date) if info.last_error_date else None,
            "last_error_message": info.last_error_message,
            "webhook_base": WEBHOOK_BASE,
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_set_webhook(request: web.Request) -> web.Response:
    try:
        await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
        info = await bot.get_webhook_info()
        return web.json_response({"result": "webhook set", "url": info.url})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_reset_db(request: web.Request) -> web.Response:
    secret = request.query.get("secret", "")
    expected = BOT_TOKEN[:10]

    if secret != expected:
        return web.json_response({"error": "forbidden"}, status=403)

    try:
        await reset_db()
        return web.json_response({"result": "db reset complete"})
    except Exception as e:
        logger.error(f"[RESET_DB] ERROR: {e}")
        logger.error(traceback.format_exc())
        return web.json_response({"error": str(e)}, status=500)


async def on_startup(app: web.Application):
    global webhook_keeper_task

    logger.info("=" * 50)
    logger.info("BOT STARTING")
    logger.info(f"WEBHOOK_URL: {WEBHOOK_URL}")
    logger.info("=" * 50)

    await init_db()
    logger.info("Database OK")

    if not WEBHOOK_BASE:
        logger.error("WEBHOOK_BASE is empty!")
        return

    await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=False)
    info = await bot.get_webhook_info()
    logger.info(f"Webhook confirmed: url={info.url}")

    webhook_keeper_task = asyncio.create_task(webhook_keeper())
    logger.info("Webhook keeper started")


async def on_shutdown(app: web.Application):
    global webhook_keeper_task
    logger.info("Shutting down... (NOT deleting webhook)")

    if webhook_keeper_task:
        webhook_keeper_task.cancel()

    try:
        await bot.session.close()
    except Exception as e:
        logger.error(f"Shutdown error: {e}")


def create_app() -> web.Application:
    app = web.Application()

    app.router.add_post(WEBHOOK_PATH, handle_webhook)
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/debug-webhook", handle_debug_webhook)
    app.router.add_get("/set-webhook", handle_set_webhook)
    app.router.add_get("/reset-db", handle_reset_db)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    return app


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=port)
