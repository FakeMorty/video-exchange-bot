import asyncio
import logging
from datetime import datetime

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import (
    BOT_TOKEN,
    OFFER_BROADCAST_INTERVAL_HOURS,
    LOG_CHAT_ID,
    PORT,
)
from app.db import engine, Base, async_session
from app.user_handlers import router as user_router
from app.admin_handlers import router as admin_router
from app.services import (
    get_active_offers,
    get_users_without_offer,
    reward_weekly_top_users,
)
from app.keyboards import offer_view_keyboard
from app.logger import setup_logging, get_logger, log_info, log_warning, log_exception

setup_logging()
logger = get_logger(__name__)


async def tg_log(bot: Bot, text: str):
    if not LOG_CHAT_ID:
        return

    chat_ids = [s.strip() for s in str(LOG_CHAT_ID).split(",") if s.strip()]
    for cid in chat_ids:
        try:
            await bot.send_message(int(cid), text, parse_mode="HTML")
        except Exception as e:
            log_warning(logger, "Не удалось отправить лог в Telegram", chat_id=cid, error=str(e))


async def offer_broadcaster(bot: Bot):
    interval = max(60, int(OFFER_BROADCAST_INTERVAL_HOURS * 3600))
    log_info(logger, "Фоновая рассылка офферов запущена", interval_seconds=interval)

    while True:
        await asyncio.sleep(interval)

        try:
            async with async_session() as session:
                offers = await get_active_offers(session)
                sent_count = 0

                for offer in offers:
                    users = await get_users_without_offer(session, offer.id)

                    for user in users:
                        try:
                            text = (
                                f"\U0001f381 <b>{offer.title}</b>\n\n"
                                f"{offer.description}\n\n"
                                f"\U0001f4b0 \u0412\u0441\u0435\u0433\u043e \u043c\u043e\u0436\u043d\u043e \u043f\u043e\u043b\u0443\u0447\u0438\u0442\u044c: <b>40</b> \u043c\u043e\u043d\u0435\u0442"
                            )
                            await bot.send_message(
                                user.telegram_id,
                                text,
                                parse_mode="HTML",
                                reply_markup=offer_view_keyboard(offer.id, offer.channel_url),
                            )
                            sent_count += 1
                        except Exception:
                            pass

                        await asyncio.sleep(0.1)

                log_info(
                    logger,
                    "Рассылка офферов завершена",
                    offers_count=len(offers),
                    sent_count=sent_count,
                )

        except asyncio.CancelledError:
            log_info(logger, "Фоновая рассылка офферов остановлена")
            raise
        except Exception:
            log_exception(logger, "Ошибка в фоновом процессе рассылки офферов")
            try:
                await tg_log(bot, "\u26a0\ufe0f <b>OFFER BROADCAST ERROR</b>")
            except Exception:
                pass


async def weekly_rewards_worker(bot: Bot):
    log_info(logger, "Фоновый процесс weekly rewards запущен")

    while True:
        await asyncio.sleep(3600)

        try:
            dt = datetime.utcnow()
            if dt.weekday() == 0 and dt.hour == 0:
                async with async_session() as session:
                    rewarded = await reward_weekly_top_users(session)

                    if rewarded:
                        lines = ["\U0001f3c6 <b>Weekly rewards paid</b>\n"]

                        for idx, (user, reward) in enumerate(rewarded, start=1):
                            lines.append(f"{idx}. <code>{user.telegram_id}</code> +{reward}")

                            try:
                                await bot.send_message(
                                    user.telegram_id,
                                    f"\U0001f3c6 \u0412\u044b \u0432\u043e\u0448\u043b\u0438 \u0432 weekly top-{idx}!\n"
                                    f"\U0001f4b0 \u041d\u0430\u0433\u0440\u0430\u0434\u0430: <b>{reward}</b>",
                                    parse_mode="HTML",
                                )
                            except Exception:
                                pass

                        await tg_log(bot, "\n".join(lines))
                        log_info(
                            logger,
                            "Weekly rewards выданы",
                            rewarded_count=len(rewarded),
                        )

                await asyncio.sleep(3700)

        except asyncio.CancelledError:
            log_info(logger, "Фоновый процесс weekly rewards остановлен")
            raise
        except Exception:
            log_exception(logger, "Ошибка в weekly rewards worker")
            try:
                await tg_log(bot, "\u26a0\ufe0f <b>WEEKLY REWARD ERROR</b>")
            except Exception:
                pass


async def on_startup(app):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    log_info(logger, "База данных подготовлена")


async def handle_health(request):
    return web.Response(text="OK")


async def handle_health_head(request):
    return web.Response(
        status=200,
        content_type="text/plain",
        headers={"Content-Length": "2"},
    )


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is empty")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    await bot.delete_webhook(drop_pending_updates=True)
    log_info(logger, "Webhook удалён, бот переведён в polling")

    try:
        await tg_log(bot, "\U0001f7e2 <b>Bot started</b>")
    except Exception:
        pass

    dp = Dispatcher()
    dp.include_router(user_router)
    dp.include_router(admin_router)

    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    app.router.add_head("/", handle_health_head)
    app.router.add_head("/health", handle_health_head)
    app.on_startup.append(on_startup)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(PORT or 10000)
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    log_info(logger, "HTTP сервер запущен", port=port)

    offer_task = asyncio.create_task(offer_broadcaster(bot))
    weekly_task = asyncio.create_task(weekly_rewards_worker(bot))

    try:
        log_info(logger, "Polling запущен")
        await dp.start_polling(bot)
    finally:
        log_info(logger, "Остановка приложения")

        for task in (offer_task, weekly_task):
            task.cancel()

        await asyncio.gather(offer_task, weekly_task, return_exceptions=True)

        await runner.cleanup()
        await bot.session.close()
        await engine.dispose()

        log_info(logger, "Завершение работы выполнено")
        

if __name__ == "__main__":
    asyncio.run(main())