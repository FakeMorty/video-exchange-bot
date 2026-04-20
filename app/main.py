import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from app.config import BOT_TOKEN, PORT
from app.db import engine, async_session
from app.user_handlers import router as user_router
from app.admin_handlers import router as admin_router
from app.logger import setup_logging, get_logger, log_info

setup_logging()
logger = get_logger(__name__)

async def on_startup(app):
    # Автомиграции отключены по просьбе пользователя
    log_info(logger, "Bot starting up... (Auto-migrations disabled)")

async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is empty")
    
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    
    dp = Dispatcher()
    dp.include_router(user_router)
    dp.include_router(admin_router)
    
    app = web.Application()
    app.on_startup.append(on_startup)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(PORT or 10000))
    await site.start()
    
    try:
        log_info(logger, "Polling started")
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
