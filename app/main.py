import logging
import os
import traceback

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import BOT_TOKEN, WEBHOOK_URL, WEBHOOK_PATH, WEBHOOK_BASE
from app.db import init_db
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


async def handle_webhook(request: web.Request) -> web.Response:
    try:
        data = await request.json()

        # Log what we received
        update_id = data.get("update_id", "?")
        msg = data.get("message", {})
        cb = data.get("callback_query", {})

        if msg:
            user = msg.get("from", {})
            text = msg.get("text", "")
            video = "VIDEO" if msg.get("video") else ""
            content = text or video or "other"
            logger.info(
                f"[WEBHOOK] update={update_id} "
                f"user={user.get('id', '?')} (@{user.get('username', '?')}) "
                f"content={content}"
            )
        elif cb:
            user = cb.get("from", {})
            cb_data = cb.get("data", "")
            logger.info(
                f"[WEBHOOK] update={update_id} "
                f"user={user.get('id', '?')} (@{user.get('username', '?')}) "
                f"callback={cb_data}"
            )
        else:
            logger.info(f"[WEBHOOK] update={update_id} type=unknown")

        update = Update.model_validate(data, context={"bot": bot})
        await dp.feed_update(bot, update)
        logger.info(f"[WEBHOOK] update={update_id} processed OK")

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


async def on_startup(app: web.Application):
    logger.info("=" * 50)
    logger.info("BOT STARTING")
    logger.info(f"BOT_TOKEN present: {bool(BOT_TOKEN)}")
    logger.info(f"WEBHOOK_BASE: {WEBHOOK_BASE}")
    logger.info(f"WEBHOOK_URL: {WEBHOOK_URL}")
    logger.info("=" * 50)

    logger.info("Initializing database...")
    await init_db()
    logger.info("Database OK")

    if not WEBHOOK_URL or WEBHOOK_URL == "/webhook":
        logger.error("WEBHOOK_URL is empty! Check WEBHOOK_BASE env variable.")
        return

    logger.info(f"Setting webhook: {WEBHOOK_URL}")
    try:
        await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
        info = await bot.get_webhook_info()
        logger.info(f"Webhook confirmed: url={info.url}")
    except Exception as e:
        logger.error(f"Failed to set webhook: {e}")
        logger.error(traceback.format_exc())


async def on_shutdown(app: web.Application):
    logger.info("Shutting down...")
    try:
        await bot.delete_webhook()
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

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    return app


if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    logger.info(f"Starting server on port {port}")
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=port)
