import logging
import asyncio
import traceback
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiohttp import web

from app.config import BOT_TOKEN, OFFER_BROADCAST_INTERVAL_HOURS, LOG_CHAT_ID
from app.db import engine, Base, async_session
from app.user_handlers import router as user_router
from app.admin_handlers import router as admin_router
from app.services import (
    get_active_offers, get_users_without_offer,
    reward_weekly_top_users,
)
from app.keyboards import offer_view_keyboard

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def tg_log(bot: Bot, text: str):
    if not LOG_CHAT_ID:
        return
    try:
        await bot.send_message(int(LOG_CHAT_ID), text, parse_mode="HTML")
    except Exception as e:
        logger.warning(f"[TG_LOG_FAIL] {e}")


async def offer_broadcaster(bot: Bot):
    interval = OFFER_BROADCAST_INTERVAL_HOURS * 3600
    while True:
        await asyncio.sleep(interval)
        try:
            async with async_session() as session:
                offers = await get_active_offers(session)
                for offer in offers:
                    users = await get_users_without_offer(session, offer.id)
                    for user in users:
                        try:
                            text = (
                                f"\U0001f381 <b>{offer.title}</b>\n\n"
                                f"{offer.description}\n\n"
                                f"\U0001f4b0 \u041d\u0430\u0433\u0440\u0430\u0434\u0430: <b>40</b> \u043c\u043e\u043d\u0435\u0442"
                            )
                            await bot.send_message(
                                user.telegram_id,
                                text,
                                parse_mode="HTML",
                                reply_markup=offer_view_keyboard(offer.id, offer.channel_url),
                            )
                        except Exception:
                            pass
                        await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"[OFFER_BROADCAST] {e}")
            logger.error(traceback.format_exc())
            await tg_log(bot, f"\u26a0\ufe0f <b>OFFER BROADCAST ERROR</b>\n<code>{e}</code>")


async def weekly_rewards_worker(bot: Bot):
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
                                f"\U0001f3c6 \u0412\u044b \u043f\u043e\u043f\u0430\u043b\u0438 \u0432 weekly top-{idx}!\n"
                                f"\U0001f4b0 \u041d\u0430\u0433\u0440\u0430\u0434\u0430: <b>{reward}</b>",
                                parse_mode="HTML",
                            )
                        except Exception:
                            pass

                    await tg_log(bot, "\n".join(lines))

                await asyncio.sleep(3700)
        except Exception as e:
            logger.error(f"[WEEKLY_REWARDS] {e}")
            logger.error(traceback.format_exc())
            await tg_log(bot, f"\u26a0\ufe0f <b>WEEKLY REWARD ERROR</b>\n<code>{e}</code>")


async def on_startup(app):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("DB ready")


async def handle_health(request):
    return web.Response(text="OK")


async def handle_reset(request):
    secret = request.query.get("secret", "")
    if secret != "8747618457":
        return web.Response(text="Forbidden", status=403)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    return web.Response(text="DB reset OK")


async def main():
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Webhook deleted, switching to polling")
    await tg_log(bot, "\U0001f7e2 <b>Bot started</b>")

    dp = Dispatcher()
    dp.include_router(user_router)
    dp.include_router(admin_router)

    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/reset-db", handle_reset)
    app.on_startup.append(on_startup)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 10000)
    await site.start()
    logger.info("Web server started on :10000")

    asyncio.create_task(offer_broadcaster(bot))
    logger.info(f"Offer broadcaster started (every {OFFER_BROADCAST_INTERVAL_HOURS}h)")

    asyncio.create_task(weekly_rewards_worker(bot))
    logger.info("Weekly rewards worker started")

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
