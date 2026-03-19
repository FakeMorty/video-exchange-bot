import logging
import os

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import BOT_TOKEN, WEBHOOK_URL, WEBHOOK_PATH
from app.db import init_db
from app.user_handlers import router as user_router
from app.admin_handlers import router as admin_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
dp.include_router(admin_router)
dp.include_router(user_router)


async def handle_webhook(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        update = Update.model_validate(data, context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
    return web.Response(text="ok")


async def handle_health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def handle_debug_webhook(request: web.Request) -> web.Response:
    info = await bot.get_webhook_info()
    return web.json_response({
        "url": info.url,
        "pending_update_count": info.pending_update_count,
        "last_error_date": str(info.last_error_date) if info.last_error_date else None,
        "last_error_message": info.last_error_message,
    })


async def on_startup(app: web.Application):
    logger.info("Initializing database...")
    await init_db()

    logger.info(f"Setting webhook: {WEBHOOK_URL}")
    await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)

    info = await bot.get_webhook_info()
    logger.info(f"Webhook set to: {info.url}")


async def on_shutdown(app: web.Application):
    logger.info("Shutting down...")
    await bot.delete_webhook()
    await bot.session.close()


def create_app() -> web.Application:
    app = web.Application()

    app.router.add_post(WEBHOOK_PATH, handle_webhook)
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/debug-webhook", handle_debug_webhook)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    return app


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=port)
