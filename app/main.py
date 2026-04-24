import asyncio
from datetime import datetime
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
)
from app.db import engine, init_db, async_session
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
logger = get_logger(__name__)


def _chat_id_from_offer_url(channel_url: str) -> str | None:
    if not channel_url:
        return None
    url = channel_url.strip()
    if "t.me/" in url:
        url = url.split("t.me/", 1)[1]
    if url.startswith("@"):
        return url
    url = url.strip("/").split("?")[0]
    if not url:
        return None
    return f"@{url}"


async def _is_subscribed(bot: Bot, telegram_user_id: int, channel_url: str) -> bool:
    chat_id = _chat_id_from_offer_url(channel_url)
    if not chat_id:
        return False
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=telegram_user_id)
        return member.status in {"member", "administrator", "creator"}
    except TelegramBadRequest:
        return False
    except Exception:
        return False


async def subscription_audit_worker(bot: Bot, stop_event: asyncio.Event):
    while not stop_event.is_set():
        checked_count = 0
        penalized_count = 0
        penalized_total = 0
        try:
            async with async_session() as session:
                parts = await get_offer_participations_for_subscription_audit(
                    session,
                    limit=max(1, OFFER_SUBSCRIPTION_CHECK_BATCH),
                )

                for part in parts:
                    checked_count += 1
                    offer = await get_offer_by_id(session, part.offer_id)
                    user = await get_user_by_id(session, part.user_id)
                    if not offer or not user:
                        continue

                    subscribed = await _is_subscribed(bot, user.telegram_id, offer.channel_url)
                    if subscribed:
                        continue

                    rewarded_total, extra_penalty, total_charge = await apply_offer_unsubscribe_penalty(
                        session, user, offer, part
                    )
                    if total_charge <= 0:
                        continue
                    penalized_count += 1
                    penalized_total += float(total_charge)
                    try:
                        await bot.send_message(
                            user.telegram_id,
                            (
                                "⚠️ Вы отписались от оффера после получения награды.\n\n"
                                f"Списано бонусов: {rewarded_total} монет\n"
                                f"Доп. штраф: {extra_penalty} монет\n"
                                f"Итого списано: {total_charge} монет"
                            ),
                        )
                    except Exception:
                        pass
            if checked_count:
                log_info(
                    logger,
                    (
                        "Subscription audit stats: "
                        f"checked={checked_count}, penalized={penalized_count}, "
                        f"total_charged={penalized_total:.2f}"
                    ),
                )
        except Exception as e:
            log_info(logger, f"Subscription audit warning: {e}")

        await asyncio.sleep(max(30, OFFER_SUBSCRIPTION_CHECK_INTERVAL_SECONDS))


async def lottery_worker(bot: Bot, stop_event: asyncio.Event):
    while not stop_event.is_set():
        try:
            async with async_session() as session:
                round_obj = await ensure_current_lottery_round(session)
                utc_now = datetime.utcnow()

                if round_obj.status == "open" and utc_now >= round_obj.draw_starts_at:
                    round_obj.status = "drawing"
                    await session.commit()
                    log_info(logger, f"Lottery round #{round_obj.id} moved to drawing")

                if round_obj.status == "drawing" and utc_now >= round_obj.draw_ends_at:
                    while round_obj.status == "drawing":
                        next_num = await draw_next_lottery_number(session, round_obj)
                        if next_num is None:
                            break
                    stats = await settle_lottery_round(session, round_obj)
                    log_info(
                        logger,
                        f"Lottery round #{round_obj.id} settled: {stats}",
                    )
        except Exception as e:
            log_info(logger, f"Lottery worker warning: {e}")

        await asyncio.sleep(30)


async def lottery_state_handler(request: web.Request) -> web.Response:
    async with async_session() as session:
        round_obj = await get_latest_lottery_round(session)
        return web.json_response(get_lottery_state_dict(round_obj))


async def lottery_draw_next_handler(request: web.Request) -> web.Response:
    secret = request.query.get("secret", "")
    if not LOTTERY_DRAW_SECRET or secret != LOTTERY_DRAW_SECRET:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    async with async_session() as session:
        round_obj = await get_latest_lottery_round(session)
        if not round_obj:
            return web.json_response({"ok": False, "error": "no_round"}, status=404)
        if round_obj.status not in {"drawing", "open"}:
            return web.json_response({"ok": False, "error": "round_not_drawing"}, status=400)
        if round_obj.status == "open":
            round_obj.status = "drawing"
            await session.commit()
        num = await draw_next_lottery_number(session, round_obj)
        if num is None:
            stats = await settle_lottery_round(session, round_obj)
            return web.json_response({"ok": True, "finished": True, "stats": stats})
        if round_obj.status == "completed":
            stats = await settle_lottery_round(session, round_obj)
            return web.json_response(
                {"ok": True, "number": num, "finished": True, "stats": stats, "state": get_lottery_state_dict(round_obj)}
            )
        return web.json_response({"ok": True, "number": num, "state": get_lottery_state_dict(round_obj)})


async def lottery_live_page_handler(request: web.Request) -> web.Response:
    html = """
<!doctype html>
<html>
<head><meta charset="utf-8"><title>Lottery Live</title></head>
<body style="font-family:Arial;max-width:900px;margin:20px auto;">
  <h2>Lottery Live Draw</h2>
  <p>Transparency page: state updates every 2 seconds.</p>
  <pre id="state">loading...</pre>
  <script>
    async function tick() {
      const res = await fetch('/lottery/state');
      const data = await res.json();
      document.getElementById('state').textContent = JSON.stringify(data, null, 2);
    }
    setInterval(tick, 2000);
    tick();
  </script>
</body>
</html>
"""
    return web.Response(text=html, content_type="text/html")


async def on_startup(app):
    from app.migrate import main as run_migrations
    await init_db()
    try:
        await run_migrations()
    except Exception as e:
        log_info(logger, f"Migrations warning: {e}")
    print("=" * 40)
    print("  BOT STARTED")
    print("=" * 40)
    log_info(logger, "Bot started, DB initialized")


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
    app.router.add_get("/lottery/state", lottery_state_handler)
    app.router.add_post("/lottery/draw-next", lottery_draw_next_handler)
    app.router.add_get("/lottery/live", lottery_live_page_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(PORT or 10000))
    await site.start()

    try:
        log_info(logger, "Polling started")
        stop_event = asyncio.Event()
        audit_task = None
        lottery_task = None
        if ENABLE_SUBSCRIPTION_AUDIT:
            audit_task = asyncio.create_task(subscription_audit_worker(bot, stop_event))
            log_info(logger, "Subscription audit worker enabled")
        else:
            log_info(logger, "Subscription audit worker disabled by config")
        if ENABLE_LOTTERY:
            lottery_task = asyncio.create_task(lottery_worker(bot, stop_event))
            log_info(logger, "Lottery worker enabled")
        await dp.start_polling(bot)
    finally:
        stop_event.set()
        if audit_task is not None:
            audit_task.cancel()
            try:
                await audit_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        if lottery_task is not None:
            lottery_task.cancel()
            try:
                await lottery_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        await runner.cleanup()
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())