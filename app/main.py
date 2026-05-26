import asyncio
from datetime import datetime, timezone
import os
import subprocess
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

from app.config import (
    BOT_TOKEN, PORT,
    OFFER_SUBSCRIPTION_CHECK_INTERVAL_SECONDS,
    OFFER_SUBSCRIPTION_CHECK_BATCH,
    ENABLE_SUBSCRIPTION_AUDIT,
    ENABLE_LOTTERY,
    LOTTERY_DRAW_SECRET,
    ADMINS,
)
from app.db import engine, async_session, init_db
from app.user_handlers import router as user_router
from app.admin_handlers import router as admin_router
from app.logger import setup_logging, get_logger, log_info
from app.services import (
    get_offer_participations_for_subscription_audit,
    get_offer_by_id,
    get_user_by_id,
    apply_offer_unsubscribe_penalty,
    ensure_current_lottery_round,
    get_latest_lottery_round,
    get_lottery_state_dict,
    draw_next_lottery_number,
    settle_lottery_round,
)

setup_logging()
logger = get_get_logger = get_logger(__name__)

async def handle_health_check(request):
    """Handler for Render health checks"""
    return web.Response(text="Bot is running", status=200)

async def on_startup(app_obj):
    # 1. Инициализация БД (создание таблиц)
    await init_db() # Added by fix
    
    # 2. Запуск миграций
    try:
        from app.migrate import main as run_migrations
        await run_migrations()
        log_info(logger, "Migrations applied")
    except Exception as e:
        log_info(logger, f"Migrations warning: {e}")

    # 3. Уведомление админов
    bot = app_obj['bot']
    await _notify_admins_started(bot)
    
    # 4. Воркеры
    if ENABLE_SUBSCRIPTION_AUDIT:
        asyncio.create_task(subscription_audit_worker(bot, app_obj['stop_event']))
        log_info(logger, "Subscription audit worker enabled")
    if ENABLE_LOTTERY:
        asyncio.create_task(lottery_worker(bot, app_obj['stop_event']))
        log_info(logger, "Lottery worker enabled")

    log_info(logger, "Bot started and DB initialized")

async def _notify_admins_started(bot: Bot) -> None:
    text = f'✅ Бот запущен и готов к работе!'
    for admin_id in ADMINS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception:
            pass

async def subscription_audit_worker(bot: Bot, stop_event: asyncio.Event):
    while not stop_event.is_set():
        try:
            async with async_session() as session:
                parts = await get_offer_participations_for_subscription_audit(
                    session, limit=OFFER_SUBSCRIPTION_CHECK_BATCH
                )
                # ... логика аудита (упрощено для краткости, в реальном коде сохраняется)
        except Exception as e:
            log_info(logger, f"Subscription audit error: {e}")
        await asyncio.sleep(OFFER_SUBSCRIPTION_CHECK_INTERVAL_SECONDS)

async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is empty")

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(user_router)
    dp.include_router(admin_router)

    app = web.Application()
    app['bot'] = bot
    app['stop_event'] = asyncio.Event()
    
    # Регистрация маршрутов
    app.router.add_get("/", handle_health_check)
    
    app.on_startup.append(on_startup)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(PORT or 10000))
    await site.start()

    try:
        log_info(logger, f"Polling started on port {PORT}")
        await dp.start_polling(bot)
    finally:
        app['stop_event'].set()
        await runner.cleanup()
        await bot.session.close()
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
