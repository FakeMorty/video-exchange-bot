from app.models import LotteryTicket, User, utc_now, LotteryRound
import os
import json
import hmac
import hashlib
import urllib.parse
from sqlalchemy import func
from app.models import Video
from sqlalchemy import select
from alembic import command
from alembic.config import Config
import asyncio
from datetime import datetime, timezone, timedelta
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
from app.db import engine, init_db, async_session
from app.user_handlers import router as user_router
from app.admin_handlers import router as admin_router
from app.user_offer_handlers import router as user_offer_router
from app.donation_shop import router as donation_router
from app.ai_assistant import router as ai_router
from app.arcade_handlers import router as arcade_router
from app.logger import setup_logging, get_logger, log_info, log_error
from app.services import (
    get_offer_participations_for_subscription_audit,
    get_offer_by_id,
    get_user_by_id,
    apply_offer_unsubscribe_penalty,
    classify_offer_url,
    normalize_telegram_url,
    notify_admins,
    ensure_current_lottery_round,
    get_latest_lottery_round,
    get_lottery_state_dict,
    draw_next_lottery_number,
    settle_lottery_round,
    _deserialize_numbers,
    to_decimal,
)

setup_logging()
logger = get_logger(__name__)


def _validate_telegram_webapp_init_data(init_data: str) -> int | None:
    """Проверяет Telegram WebApp initData и возвращает telegram user id."""
    if not init_data or not BOT_TOKEN:
        return None

    try:
        pairs = urllib.parse.parse_qsl(init_data, keep_blank_values=True)
        data = dict(pairs)
        received_hash = data.pop("hash", "")
        if not received_hash:
            return None

        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        auth_date = int(data.get("auth_date", "0") or 0)
        now_ts = int(datetime.now(timezone.utc).timestamp())
        if auth_date and abs(now_ts - auth_date) > 24 * 60 * 60:
            return None

        user_raw = data.get("user")
        if not user_raw:
            return None
        user_data = json.loads(user_raw)
        user_id = int(user_data.get("id", 0))
        return user_id or None
    except Exception:
        return None


def _get_webapp_user_id(request: web.Request, payload: dict | None = None) -> int | None:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if not init_data and payload:
        init_data = str(payload.get("init_data", "") or "")
    if not init_data:
        init_data = request.query.get("init_data", "")
    return _validate_telegram_webapp_init_data(init_data)


def _chat_id_from_offer_url(channel_url: str) -> str | None:
    meta = classify_offer_url(channel_url)
    normalized = normalize_telegram_url(channel_url)
    if not meta.get("auto_verify") or not normalized:
        return None
    path = urllib.parse.urlsplit(normalized).path.strip("/")
    username = path.split("/", 1)[0]
    if not username:
        return None
    return f"@{username}"


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

                    target_meta = classify_offer_url(offer.channel_url)
                    if not target_meta.get("auto_verify"):
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
                        msg = (
                            "⚠️ <b>Оффер завершён с возвратом награды</b>\n\n"
                            "После твоей отписки от канала ранее начисленная награда была отозвана."
                        )
                        if extra_penalty > 0:
                            msg += f"\n\n⚠️ Дополнительно списан штраф за отписку: <b>{extra_penalty}</b> монет."
                        
                        msg += (
                            f"\n\nСписано всего: <b>{total_charge}</b> монет\n"
                            f"Текущий баланс: <b>{max(user.balance, 0)}</b> монет"
                        )
                        await bot.send_message(
                            user.telegram_id,
                            msg,
                            parse_mode="HTML",
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
                if penalized_count > 0:
                    try:
                        await notify_admins(
                            bot,
                            f"⚠️ <b>Сработали штрафы по офферам</b>\n"
                            f"Проверено участий: <b>{checked_count}</b>\n"
                            f"Ошибочных/наказанных: <b>{penalized_count}</b>\n"
                            f"Списано суммарно: <b>{penalized_total:.2f}</b> монет",
                        )
                    except Exception:
                        pass
        except Exception as e:
            log_info(logger, f"Subscription audit warning: {e}")

        await asyncio.sleep(max(30, OFFER_SUBSCRIPTION_CHECK_INTERVAL_SECONDS))





async def notify_lottery_reminder(bot: Bot, session, round_id: int, draw_starts_at: datetime):
    from sqlalchemy import select
    from app.models import LotteryTicket, User
    from datetime import timedelta
    from app.utils.messaging import format_time_for_user
    
    tickets = (await session.execute(select(LotteryTicket).where(LotteryTicket.round_id == round_id))).scalars().all()
    user_ids = list(set(t.user_id for t in tickets))
    users = (await session.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
    
    for u in users:
        time_str = format_time_for_user(draw_starts_at, u.timezone)
        msg = (
            "⏰ <b>Секслото — скоро розыгрыш!</b>\n\n"
            f"Розыгрыш начнётся {time_str}.\n"
            "Не забудьте зайти в Live и посмотреть на свои бочонки! 🎰"
        )
        try:
            await bot.send_message(u.telegram_id, msg, parse_mode="HTML")
        except Exception:
            pass
        await asyncio.sleep(0.05)


async def notify_lottery_started(bot: Bot, session, round_id: int):
    from app.config import LOTTERY_SECONDS_PER_BALL

    tickets = (await session.execute(select(LotteryTicket).where(LotteryTicket.round_id == round_id))).scalars().all()
    user_ids = list(set(t.user_id for t in tickets))
    users = (await session.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()

    msg = (
        f"🎰 <b>СЕКСЛОТО #{round_id} НАЧИНАЕТСЯ!</b> 🎰\n\n"
        f"Лототрон запущен! Бочонки начинают перемешиваться! 🌀\n"
        f"Следи за сообщениями — мы будем вытаскивать бочонки в реальном времени примерно каждые {LOTTERY_SECONDS_PER_BALL} секунд! 🎪"
    )
    for u in users:
        try:
            await bot.send_message(u.telegram_id, msg, parse_mode="HTML")
        except Exception:
            pass
        await asyncio.sleep(0.05)


async def notify_lottery_results(bot: Bot, session, round_id: int):
    # Получаем раунд лотереи
    result = await session.execute(select(LotteryRound).where(LotteryRound.id == round_id))
    round_obj = result.scalar_one_or_none()
    if not round_obj:
        return
        
    drawn_nums = _deserialize_numbers(round_obj.drawn_numbers)
    drawn_nums_str = ", ".join(str(n) for n in drawn_nums)
    
    # Получаем все билеты раунда
    tickets = (await session.execute(
        select(LotteryTicket).where(LotteryTicket.round_id == round_id)
    )).scalars().all()
    
    if not tickets:
        return # Если билетов никто не купил, рассылать результаты некому
        
    # Считаем количество победителей в каждой категории
    n = round_obj.numbers_per_ticket
    pool = to_decimal(round_obj.prize_pool)
    
    winners_6_cnt = sum(1 for t in tickets if t.matched_count >= n)
    winners_5_cnt = sum(1 for t in tickets if t.matched_count == n - 1)
    winners_4_cnt = sum(1 for t in tickets if t.matched_count == n - 2)
    winners_3_cnt = sum(1 for t in tickets if t.matched_count == n - 3)
    winners_2_cnt = sum(1 for t in tickets if t.matched_count == n - 4)

    # Распределение призового фонда (должно совпадать с settle_lottery_round):
    # 3 совпадения — 60%, 4 совпадения — 25%, 5 совпадений — 10%, 6 — 5%.
    per_ticket_6 = to_decimal(0)
    if winners_6_cnt > 0:
        per_ticket_6 = round((pool * to_decimal(0.05)) / to_decimal(winners_6_cnt), 2)

    per_ticket_5 = to_decimal(0)
    if winners_5_cnt > 0:
        per_ticket_5 = round((pool * to_decimal(0.10)) / to_decimal(winners_5_cnt), 2)

    per_ticket_4 = to_decimal(0)
    if winners_4_cnt > 0:
        per_ticket_4 = round((pool * to_decimal(0.25)) / to_decimal(winners_4_cnt), 2)

    per_ticket_3 = to_decimal(0)
    if winners_3_cnt > 0:
        per_ticket_3 = round((pool * to_decimal(0.60)) / to_decimal(winners_3_cnt), 2)

    # Фиксированные выплаты за 2 совпадения (берём из конфига).
    per_ticket_2 = to_decimal(0)
    if winners_2_cnt > 0:
        from app.config import LOTTERY_MATCH2_REWARD
        per_ticket_2 = to_decimal(LOTTERY_MATCH2_REWARD)

    # Группируем билеты по пользователям
    user_tickets = {}
    for t in tickets:
        if t.user_id not in user_tickets:
            user_tickets[t.user_id] = []
        user_tickets[t.user_id].append(t)
        
    # Получаем пользователей
    user_ids = list(user_tickets.keys())
    users = {u.id: u for u in (await session.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()}
    
    for uid, tickets_list in user_tickets.items():
        u = users.get(uid)
        if not u:
            continue
            
        total_won = to_decimal(0)
        tickets_info = []
        
        for idx, t in enumerate(tickets_list, 1):
            matched = t.matched_count
            win_amount = to_decimal(0)
            shared_with = 0
            if matched >= n:
                win_amount = per_ticket_6
                shared_with = winners_6_cnt
            elif matched == n - 1:
                win_amount = per_ticket_5
                shared_with = winners_5_cnt
            elif matched == n - 2:
                win_amount = per_ticket_4
                shared_with = winners_4_cnt
            elif matched == n - 3:
                win_amount = per_ticket_3
                shared_with = winners_3_cnt
            elif matched == n - 4:
                win_amount = per_ticket_2
                shared_with = winners_2_cnt

            total_won += win_amount
            ticket_nums_str = ", ".join(str(n) for n in _deserialize_numbers(t.numbers))

            if win_amount > 0:
                share_note = (
                    f" (делится на {shared_with} победителей)"
                    if shared_with > 1
                    else ""
                )
                tickets_info.append(
                    f"🎫 Билет №{t.id} [{ticket_nums_str}]: "
                    f"совпало {matched} чисел — <b>выигрыш {win_amount} монет</b>{share_note} 🎉"
                )
            else:
                tickets_info.append(
                    f"🎫 Билет №{t.id} [{ticket_nums_str}]: "
                    f"совпало {matched} чисел (без выигрыша) 😔"
                )

        tickets_report = "\n".join(tickets_info)

        if total_won > 0:
            msg = (
                f"🎉 <b>РОЗЫГРЫШ ЛОТЕРЕИ #{round_id} ЗАВЕРШЕН!</b>\n\n"
                f"🔵 <b>Выигрышные номера:</b>\n"
                f"➡ <b>[ {drawn_nums_str} ]</b>\n\n"
                f"📝 <b>Результаты твоих билетов:</b>\n"
                f"{tickets_report}\n\n"
                f"🏆 <b>Итоговый выигрыш: {total_won} монет!</b>\n"
                f"Награда зачислена на твой баланс. Поздравляем!"
            )
        else:
            msg = (
                f"🎰 <b>РОЗЫГРЫШ ЛОТЕРЕИ #{round_id} ЗАВЕРШЕН!</b>\n\n"
                f"🔵 <b>Выигрышные номера:</b>\n"
                f"➡ <b>[ {drawn_nums_str} ]</b>\n\n"
                f"📝 <b>Результаты твоих билетов:</b>\n"
                f"{tickets_report}\n\n"
                f"😔 К сожалению, в этот раз выиграть не удалось. Повезет в следующий раз!"
            )
            
        try:
            await bot.send_message(u.telegram_id, msg, parse_mode="HTML")
        except Exception:
            pass
        await asyncio.sleep(0.05)


async def lottery_worker(bot: Bot, stop_event: asyncio.Event):
    from app.config import LOTTERY_SECONDS_PER_BALL

    REMINDER_HOURS_BEFORE = 1  # За сколько часов до розыгрыша напомнить
    while not stop_event.is_set():
        try:
            async with async_session() as session:
                round_obj = await ensure_current_lottery_round(session)
                now_utc = utc_now()

                # Напоминание за 1 час до розыгрыша
                if (
                    round_obj.status == "open"
                    and not round_obj.draw_reminder_sent
                    and now_utc >= round_obj.draw_starts_at - timedelta(hours=REMINDER_HOURS_BEFORE)
                ):
                    round_obj.draw_reminder_sent = True
                    await session.commit()
                    log_info(logger, f"Lottery round #{round_obj.id}: sending draw reminder")
                    await notify_lottery_reminder(bot, session, round_obj.id, round_obj.draw_starts_at)

                # Запуск розыгрыша Секслото в реальном времени
                if round_obj.status == "open" and now_utc >= round_obj.draw_starts_at:
                    round_obj.status = "drawing"
                    await session.commit()
                    log_info(logger, f"Lottery round #{round_obj.id} moved to drawing")

                    # Оповещаем о старте лототрона
                    await notify_lottery_started(bot, session, round_obj.id)

                    drawn_nums = []
                    # Тянем бочонки по одному: один цикл лототрона = 15 секунд.
                    # Промежуточные результаты НЕ рассылаем — Telegram может за такое
                    # забанить рассылку. Всё покажем в одном итоговом сообщении.
                    for _step in range(round_obj.numbers_per_ticket):
                        if stop_event.is_set():
                            break

                        await asyncio.sleep(LOTTERY_SECONDS_PER_BALL)

                        next_num = await draw_next_lottery_number(session, round_obj)
                        if next_num is None:
                            break
                        drawn_nums.append(next_num)

                    # Рассчитываем и распределяем выигрыши
                    stats = await settle_lottery_round(session, round_obj)
                    log_info(logger, f"Lottery round #{round_obj.id} settled: {stats}")

                    # Оповещаем участников о подробных результатах
                    # (включая все выпавшие бочонки)
                    await notify_lottery_results(bot, session, round_obj.id)
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
        finished = (num is None) or (round_obj.status == "completed")
        if finished:
            # Ensure completed status before settle to avoid double-settle edge cases
            if round_obj.status != "completed":
                round_obj.status = "completed"
                await session.commit()
            stats = await settle_lottery_round(session, round_obj)
            return web.json_response(
                {"ok": True, "finished": True, "stats": stats, "state": get_lottery_state_dict(round_obj)} if num is not None
                else {"ok": True, "finished": True, "stats": stats}
            )
        return web.json_response({"ok": True, "number": num, "state": get_lottery_state_dict(round_obj)})


async def lottery_live_page_handler(request: web.Request) -> web.Response:
    html = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>Lottery Live — Секслото Шоу 🎰</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root {
      --bg-color: var(--tg-theme-bg-color, #131722);
      --text-color: var(--tg-theme-text-color, #ffffff);
      --accent-color: var(--tg-theme-button-color, #2a85ff);
      --card-bg: var(--tg-theme-secondary-bg-color, #1b2030);
      --gold: #ffd700;
    }
    body {
      margin: 0;
      padding: 16px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--bg-color);
      color: var(--text-color);
      display: flex;
      flex-direction: column;
      align-items: center;
      box-sizing: border-box;
      user-select: none;
      -webkit-user-select: none;
    }
    .container {
      width: 100%;
      max-width: 480px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }
    .user-header {
      background-color: var(--card-bg);
      border-radius: 12px;
      padding: 10px 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 13px;
      border: 1px solid rgba(255, 255, 255, 0.05);
    }
    .card {
      background-color: var(--card-bg);
      border-radius: 20px;
      padding: 20px;
      text-align: center;
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
      border: 1px solid rgba(255, 255, 255, 0.05);
      position: relative;
      overflow: hidden;
    }
    .header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
    }
    .header h2 {
      margin: 0;
      font-size: 20px;
      font-weight: 800;
    }
    .status-badge {
      display: inline-block;
      padding: 5px 12px;
      border-radius: 20px;
      font-size: 12px;
      font-weight: bold;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    .status-open {
      background-color: #30d158;
      box-shadow: 0 0 15px rgba(48, 209, 88, 0.4);
    }
    .status-drawing {
      background-color: #ff9f0a;
      box-shadow: 0 0 15px rgba(255, 159, 10, 0.4);
      animation: pulse 1s infinite alternate;
    }
    .status-completed {
      background-color: #0a84ff;
      box-shadow: 0 0 15px rgba(10, 132, 255, 0.4);
    }
    @keyframes pulse {
      from { opacity: 1; }
      to { opacity: 0.6; }
    }

    /* Призовой фонд */
    .prize-box {
      background: linear-gradient(135deg, rgba(255,215,0,0.12), rgba(255,149,0,0.04));
      border: 1px dashed rgba(255,215,0,0.3);
      border-radius: 16px;
      padding: 16px;
      margin: 15px 0;
      text-align: center;
    }
    .prize-pool {
      font-size: 32px;
      font-weight: 900;
      color: var(--gold);
      text-shadow: 0 0 15px rgba(255, 215, 0, 0.45);
      margin-top: 5px;
    }
    
    /* Горизонтальная полоска с выпавшими числами */
    .strip-container {
      background-color: var(--card-bg);
      border-radius: 16px;
      padding: 16px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
      border: 1px solid rgba(255, 255, 255, 0.05);
    }
    .strip-title {
      font-size: 13px;
      font-weight: 700;
      color: var(--tg-theme-hint-color, #888);
      margin-bottom: 12px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      text-align: center;
    }
    .balls-strip {
      display: flex;
      justify-content: center;
      flex-wrap: wrap;
      gap: 10px;
      min-height: 48px;
      align-items: center;
    }
    .ball {
      width: 44px;
      height: 44px;
      border-radius: 50%;
      background: radial-gradient(circle at 35% 35%, #ffffff 0%, #ff9500 60%, #cc5200 100%);
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 18px;
      font-weight: 800;
      box-shadow: 0 6px 12px rgba(255,149,0,0.25), inset -3px -3px 8px rgba(0,0,0,0.4);
      animation: popIn 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards;
    }
    @keyframes popIn {
      from { transform: scale(0) rotate(-180deg); opacity: 0; }
      to { transform: scale(1) rotate(0deg); opacity: 1; }
    }
    .info-row {
      display: flex;
      justify-content: space-between;
      margin-bottom: 10px;
      font-size: 15px;
      border-bottom: 1px solid rgba(255,255,255,0.05);
      padding-bottom: 5px;
    }
    .info-row:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
    
    .interactive-tip {
      font-size: 11px;
      color: var(--tg-theme-hint-color, #888);
      margin-top: 8px;
      font-style: italic;
    }

    /* Рекламная карусель баннеров */
    .banner-carousel {
      display: flex;
      overflow-x: auto;
      scroll-snap-type: x mandatory;
      gap: 15px;
      padding: 10px 0;
      scrollbar-width: none;
      -ms-overflow-style: none;
    }
    .banner-carousel::-webkit-scrollbar {
      display: none;
    }
    .banner-slide {
      flex: 0 0 100%;
      scroll-snap-align: start;
      background: linear-gradient(135deg, rgba(42, 133, 255, 0.12), rgba(42, 133, 255, 0.04));
      border: 1px solid rgba(42, 133, 255, 0.2);
      border-radius: 16px;
      padding: 16px;
      box-sizing: border-box;
      text-align: center;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      min-height: 140px;
    }
    .banner-slide h3 {
      margin: 0 0 8px 0;
      font-size: 16px;
      color: var(--accent-color);
    }
    .banner-slide p {
      margin: 0 0 12px 0;
      font-size: 12px;
      color: var(--tg-theme-hint-color, #888);
    }
    .banner-btn {
      background-color: var(--accent-color);
      color: #fff;
      border: none;
      border-radius: 10px;
      padding: 8px 16px;
      font-size: 13px;
      font-weight: bold;
      cursor: pointer;
      transition: opacity 0.2s;
    }
    .banner-btn:active {
      opacity: 0.8;
    }

    /* Модальное окно Офферов и Звёзд */
    .modal {
      display: none;
      position: fixed;
      left: 0;
      top: 0;
      width: 100%;
      height: 100%;
      background: rgba(0,0,0,0.85);
      z-index: 1000;
      justify-content: center;
      align-items: center;
      padding: 16px;
      box-sizing: border-box;
    }
    .modal-content {
      background-color: var(--card-bg);
      border-radius: 20px;
      width: 100%;
      max-width: 400px;
      padding: 20px;
      border: 1px solid rgba(255, 255, 255, 0.08);
      position: relative;
    }
    .modal-close {
      position: absolute;
      right: 16px;
      top: 16px;
      font-size: 22px;
      cursor: pointer;
      color: var(--tg-theme-hint-color, #888);
    }
    .package-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px;
      border-bottom: 1px solid rgba(255,255,255,0.05);
    }
    .package-item:last-child { border-bottom: none; }
  </style>
</head>
<body>
  <div class="container">
    <!-- Шапка Пользователя -->
    <div class="user-header">
      <div style="font-weight: bold;">👤 <span id="user-name">Гость</span></div>
      <div style="font-weight: 800; color: var(--gold);">💰 <span id="user-balance">--</span> 🪙</div>
    </div>

    <div class="card">
      <div class="header">
        <h2>🏆 Секслото <span id="round-id">...</span></h2>
        <div id="status-badge" class="status-badge">Загрузка...</div>
      </div>
      
      <!-- Лототрон Секслото с реальной 2D физикой Canvas -->
      <canvas id="lototron-canvas" width="160" height="160" style="display: block; margin: 10px auto; border-radius: 50%; box-shadow: 0 0 25px rgba(42, 133, 255, 0.35); border: 4px solid var(--accent-color); background: radial-gradient(circle at 50% 50%, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.02));"></canvas>
      <div id="interactive-tip" class="interactive-tip">📱 Наклоняй телефон или таскай шары пальцем!</div>

      <!-- Таймер до розыгрыша -->
      <div id="timer-box" style="margin: 10px 0; font-size: 14px; font-weight: bold; background: rgba(255,255,255,0.05); padding: 10px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.05);">
        ⏱ До розыгрыша: <span id="countdown" style="color: var(--accent-color);">--:--:--</span>
      </div>

      <!-- Призовой фонд -->
      <div class="prize-box">
        <div style="font-size: 13px; color: var(--tg-theme-hint-color, #888); font-weight: bold; text-transform: uppercase;">Призовой фонд 💰</div>
        <div class="prize-pool" id="prize-pool">0.00 🪙</div>
      </div>

      <div class="info-row">
        <span style="color: var(--tg-theme-hint-color, #888);">Цена билета:</span>
        <strong><span id="ticket-price">-</span> 🪙</strong>
      </div>
      <div class="info-row">
        <span style="color: var(--tg-theme-hint-color, #888);">Куплено билетов:</span>
        <strong id="tickets-count">-</strong>
      </div>
      <div class="info-row">
        <span style="color: var(--tg-theme-hint-color, #888);">Старт розыгрыша:</span>
        <strong id="draw-time">-</strong>
      </div>
    </div>

    <!-- Свайпаемые рекламные баннеры (Акции и ставки) -->
    <div id="banners-container">
      <div class="strip-title" style="margin-bottom: 8px;">🔥 Акции и Ставки Секслото 🔥</div>
      <div class="banner-carousel">
        
        <!-- Слайд 1: Купить билеты -->
        <div class="banner-slide">
          <div>
            <h3>🎟 Купить билеты Секслото</h3>
            <p>Испытай свою удачу и выбери, сколько билетов хочешь взять в этот раунд!</p>
          </div>
          <button class="banner-btn" onclick="openTicketModal()">Купить билеты по <span id="banner-ticket-price">-</span> 🪙</button>
        </div>
        
        <!-- Слайд 2: Монеты за звезды -->
        <div class="banner-slide">
          <div>
            <h3>💎 Монеты за звёзды</h3>
            <p>Получи мгновенный буст баланса монет за Telegram Stars!</p>
          </div>
          <button class="banner-btn" onclick="openStarsModal()">Купить монеты</button>
        </div>

        <!-- Слайд 3: Бесплатные монеты / Офферы -->
        <div class="banner-slide">
          <div>
            <h3>📋 Бесплатные монеты</h3>
            <p>Выполняй задания и подписки в разделе Офферы!</p>
          </div>
          <button class="banner-btn" onclick="openOffersModal()">Открыть Офферы</button>
        </div>

        <!-- Слайд 4: Ставки на первый/последний бочонок -->
        <div class="banner-slide">
          <div>
            <h3>🎯 Ставки на бочонки</h3>
            <p>Угадай, чётный или нечётный выпадет первый/последний бочонок!</p>
          </div>
          <div style="display: flex; gap: 8px; justify-content: center; margin-bottom: 8px;">
            <button class="banner-btn" style="background: #34c759; padding: 6px 12px; font-size: 11px;" onclick="placeBetAction('first')">Ставка на 1-й</button>
            <button class="banner-btn" style="background: #bf5af2; padding: 6px 12px; font-size: 11px;" onclick="placeBetAction('last')">Ставка на последний</button>
          </div>
        </div>
      </div>
      <div style="text-align: center; font-size: 10px; color: var(--tg-theme-hint-color, #888); margin-top: -5px;">↔ Свайпай баннеры влево/вправо</div>
    </div>

    <!-- Полоска с выпавшими числами -->
    <div class="strip-container">
      <div class="strip-title">🔵 Выпавшие бочонки «Секслото» 🔵</div>
      <div class="balls-strip" id="balls-container">
        <div class="no-numbers" style="color: var(--tg-theme-hint-color); font-size: 14px; text-align:center; width:100%;">Розыгрыш еще не начался...</div>
      </div>
    </div>
  </div>

  <!-- Модальное окно покупки билетов -->
  <div id="ticket-modal" class="modal">
    <div class="modal-content">
      <span class="modal-close" onclick="closeTicketModal()">&times;</span>
      <h3 style="color: var(--accent-color); margin-top: 0; text-align: center;">🎟 Купить билеты</h3>
      <p style="font-size: 12px; text-align: center; color: var(--tg-theme-hint-color, #888);">
        Укажи количество билетов или нажми «Максимум».
      </p>
      <div style="display:flex; flex-direction:column; gap:10px;">
        <div style="display:flex; gap:8px; justify-content:center; flex-wrap:wrap;">
          <button class="banner-btn" style="padding: 6px 12px; font-size: 11px;" onclick="setTicketQty(1)">1</button>
          <button class="banner-btn" style="padding: 6px 12px; font-size: 11px;" onclick="setTicketQty(5)">5</button>
          <button class="banner-btn" style="padding: 6px 12px; font-size: 11px;" onclick="setTicketQty(10)">10</button>
          <button class="banner-btn" style="padding: 6px 12px; font-size: 11px; background:#34c759;" onclick="setMaxTicketQty()">Максимум</button>
        </div>
        <input id="ticket-qty-input" type="number" min="1" step="1" value="1"
               style="width:100%; box-sizing:border-box; padding:10px 12px; border-radius:12px; border:1px solid rgba(255,255,255,0.1); background:rgba(255,255,255,0.04); color:var(--text-color); font-size:15px;" />
        <div style="font-size:12px; color: var(--tg-theme-hint-color, #888); text-align:center;">
          Цена билета: <b><span id="ticket-modal-price">-</span> 🪙</b><br>
          Сейчас можно купить до: <b><span id="ticket-modal-max">-</span></b>
        </div>
        <button class="banner-btn" onclick="confirmBuyTickets()">Купить</button>
      </div>
    </div>
  </div>

  <!-- Модальное окно Звёзд -->
  <div id="stars-modal" class="modal">
    <div class="modal-content">
      <span class="modal-close" onclick="closeStarsModal()">&times;</span>
      <h3 style="color: var(--accent-color); margin-top: 0; text-align: center;">💎 Монеты за звёзды</h3>
      <p style="font-size: 12px; text-align: center; color: var(--tg-theme-hint-color, #888);">3 понятных пакета, чтобы быстро вернуться к просмотру:</p>
      <div style="display: flex; flex-direction: column; gap: 8px; max-height: 250px; overflow-y: auto;">
        <div class="package-item">
          <div><b>⚡ 500 монет</b><br><small style="color: var(--tg-theme-hint-color);">Быстрый старт · 50 ★</small></div>
          <button class="banner-btn" style="padding: 6px 12px; font-size: 11px;" onclick="buyCoins('pack_50')">Купить</button>
        </div>
        <div class="package-item">
          <div><b>🔥 1 000 монет</b><br><small style="color: var(--tg-theme-hint-color);">Популярный пакет · 100 ★</small></div>
          <button class="banner-btn" style="padding: 6px 12px; font-size: 11px;" onclick="buyCoins('pack_100')">Купить</button>
        </div>
        <div class="package-item">
          <div><b>💎 2 200 монет</b><br><small style="color: var(--tg-theme-hint-color);">Самый выгодный · 200 ★</small></div>
          <button class="banner-btn" style="padding: 6px 12px; font-size: 11px;" onclick="buyCoins('pack_200')">Купить</button>
        </div>
      </div>
    </div>
  </div>

  <!-- Модальное окно Офферов -->
  <div id="offers-modal" class="modal">
    <div class="modal-content">
      <span class="modal-close" onclick="closeOffersModal()">&times;</span>
      <h3 style="color: var(--accent-color); margin-top: 0; text-align: center;">📋 Бесплатные монеты</h3>
      <p style="font-size: 12px; text-align: center; color: var(--tg-theme-hint-color, #888);">Выполняй задания партнёров и получай монеты по условиям каждого оффера.</p>
      <div id="offers-list" style="display: flex; flex-direction: column; gap: 8px; max-height: 250px; overflow-y: auto;">
        <div style="text-align: center; font-size: 13px; padding: 20px; color: var(--tg-theme-hint-color);">Загрузка заданий...</div>
      </div>
    </div>
  </div>

  <script>
    window.Telegram.WebApp.ready();
    window.Telegram.WebApp.expand();

    // Telegram WebApp auth context
    const tgUser = window.Telegram.WebApp.initDataUnsafe.user;
    const initData = window.Telegram.WebApp.initData || '';
    const userId = tgUser ? tgUser.id : 0;
    const userName = tgUser ? (tgUser.first_name + (tgUser.last_name ? ' ' + tgUser.last_name : '')) : 'Гость';

    function authHeaders(extra = {}) {
        return Object.assign({'X-Telegram-Init-Data': initData}, extra);
    }

    document.getElementById('user-name').innerText = userName;

    let lastRoundId = null;
    let isSpinning = false;
    let drawStartsAt = null;
    let currentUserBalance = 0;
    let currentTicketPrice = 0;
    
    // Инициализация Canvas и 2D Физики
    const canvas = document.getElementById('lototron-canvas');
    const ctx = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    const cx = width / 2;
    const cy = height / 2;
    const drumRadius = width / 2 - 4;
    
    const balls = [];
    const ballColors = [
        '#ff453a', '#ff9f0a', '#ffd60a', '#30d158', '#64d2ff', 
        '#0a84ff', '#bf5af2', '#ff3b30', '#ffcc00', '#4cd964', 
        '#5ac8fa', '#007aff', '#5856d6', '#ff2d55', '#34c759'
    ];
    
    // Переменные гравитации
    let gx = 0;
    let gy = 0.22;
    
    // Создаем 15 физических бочонков
    for (let i = 1; i <= 15; i++) {
        let angle = Math.random() * Math.PI * 2;
        let r = Math.random() * (drumRadius - 16);
        balls.push({
            id: i,
            x: cx + Math.cos(angle) * r,
            y: cy + Math.sin(angle) * r,
            vx: (Math.random() - 0.5) * 5,
            vy: (Math.random() - 0.5) * 5,
            radius: 9,
            color: ballColors[(i - 1) % ballColors.length],
            isDragged: false
        });
    }
    
    // Обработка Drag-and-Drop
    let draggedBall = null;
    
    function getMousePos(evt) {
        const rect = canvas.getBoundingClientRect();
        const clientX = evt.touches ? evt.touches[0].clientX : evt.clientX;
        const clientY = evt.touches ? evt.touches[0].clientY : evt.clientY;
        return {
            x: ((clientX - rect.left) / rect.width) * width,
            y: ((clientY - rect.top) / rect.height) * height
        };
    }
    
    function handleStart(evt) {
        if (isSpinning) return;
        const pos = getMousePos(evt);
        for (let i = 0; i < balls.length; i++) {
            const b = balls[i];
            const dx = pos.x - b.x;
            const dy = pos.y - b.y;
            const dist = Math.sqrt(dx*dx + dy*dy);
            if (dist < b.radius + 6) {
                draggedBall = b;
                b.isDragged = true;
                b.vx = 0;
                b.vy = 0;
                canvas.style.cursor = 'grabbing';
                break;
            }
        }
    }
    
    function handleMove(evt) {
        if (!draggedBall || isSpinning) return;
        evt.preventDefault();
        const pos = getMousePos(evt);
        
        const dx = pos.x - cx;
        const dy = pos.y - cy;
        const dist = Math.sqrt(dx*dx + dy*dy);
        const rLimit = drumRadius - draggedBall.radius;
        
        if (dist > rLimit) {
            const nx = dx / dist;
            const ny = dy / dist;
            draggedBall.x = cx + nx * rLimit;
            draggedBall.y = cy + ny * rLimit;
        } else {
            draggedBall.x = pos.x;
            draggedBall.y = pos.y;
        }
    }
    
    function handleEnd() {
        if (draggedBall) {
            draggedBall.isDragged = false;
            draggedBall.vx = (Math.random() - 0.5) * 6;
            draggedBall.vy = (Math.random() - 0.5) * 6;
            draggedBall = null;
            canvas.style.cursor = 'grab';
        }
    }
    
    canvas.addEventListener('mousedown', handleStart);
    canvas.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseup', handleEnd);
    
    canvas.addEventListener('touchstart', handleStart, { passive: false });
    canvas.addEventListener('touchmove', handleMove, { passive: false });
    window.addEventListener('touchend', handleEnd);
    
    window.addEventListener('keydown', (evt) => {
        if (evt.keyCode === 32) {
            evt.preventDefault();
            shakeBalls();
        }
    });
    
    function shakeBalls() {
        if (isSpinning) return;
        for (let i = 0; i < balls.length; i++) {
            balls[i].vx += (Math.random() - 0.5) * 14;
            balls[i].vy += (Math.random() - 0.5) * 14;
        }
        if (window.Telegram.WebApp.HapticFeedback) {
            window.Telegram.WebApp.HapticFeedback.notificationOccurred('success');
        }
    }
    
    window.addEventListener('deviceorientation', (event) => {
        if (isSpinning) return;
        const tiltX = event.gamma;
        const tiltY = event.beta;
        if (tiltX !== null && tiltY !== null) {
            gx = (tiltX / 90) * 0.45;
            gy = (tiltY / 90) * 0.45;
            gx = Math.max(-0.5, Math.min(gx, 0.5));
            gy = Math.max(-0.5, Math.min(gy, 0.5));
        }
    });
    
    let lastX = null, lastY = null, lastZ = null;
    const shakeThreshold = 14;
    window.addEventListener('devicemotion', (event) => {
        if (isSpinning) return;
        const acc = event.accelerationIncludingGravity;
        if (!acc) return;
        if (lastX !== null) {
            const deltaX = Math.abs(acc.x - lastX);
            const deltaY = Math.abs(acc.y - lastY);
            const deltaZ = Math.abs(acc.z - lastZ);
            if (deltaX + deltaY + deltaZ > shakeThreshold * 3) {
                shakeBalls();
            }
        }
        lastX = acc.x;
        lastY = acc.y;
        lastZ = acc.z;
    });

    function animatePhysics() {
        requestAnimationFrame(animatePhysics);
        ctx.clearRect(0, 0, width, height);
        
        for (let i = 0; i < balls.length; i++) {
            const b = balls[i];
            
            if (b.isDragged) {
                ctx.beginPath();
                ctx.arc(b.x, b.y, b.radius + 2, 0, Math.PI * 2);
                ctx.fillStyle = b.color;
                ctx.fill();
                
                const shineGrad = ctx.createRadialGradient(
                    b.x - b.radius/3, b.y - b.radius/3, b.radius/10,
                    b.x, b.y, b.radius
                );
                shineGrad.addColorStop(0, 'rgba(255,255,255,0.65)');
                shineGrad.addColorStop(0.4, 'rgba(255,255,255,0)');
                shineGrad.addColorStop(1, 'rgba(0,0,0,0.4)');
                ctx.fillStyle = shineGrad;
                ctx.fill();
                ctx.closePath();
                continue;
            }
            
            if (isSpinning) {
                b.vx += - (b.y - cy) * 0.09 + (Math.random() - 0.5) * 1.8;
                b.vy += (b.x - cx) * 0.09 + (Math.random() - 0.5) * 1.8;
                b.vx *= 0.97;
                b.vy *= 0.97;
            } else {
                b.vx += gx;
                b.vy += gy;
                b.vx *= 0.98;
                b.vy *= 0.98;
            }
            
            b.x += b.vx;
            b.y += b.vy;
            
            const dx = b.x - cx;
            const dy = b.y - cy;
            const dist = Math.sqrt(dx*dx + dy*dy);
            const rLimit = drumRadius - b.radius;
            
            if (dist > rLimit) {
                const nx = dx / dist;
                const ny = dy / dist;
                const dot = b.vx * nx + b.vy * ny;
                b.vx = (b.vx - 2 * dot * nx) * 0.8;
                b.vy = (b.vy - 2 * dot * ny) * 0.8;
                b.x = cx + nx * rLimit;
                b.y = cy + ny * rLimit;
            }
            
            for (let j = i + 1; j < balls.length; j++) {
                const b2 = balls[j];
                if (b2.isDragged) continue;
                
                const b_dx = b2.x - b.x;
                const b_dy = b2.y - b.y;
                const b_dist = Math.sqrt(b_dx*b_dx + b_dy*b_dy);
                const minDist = b.radius + b2.radius;
                
                if (b_dist < minDist) {
                    const nx = b_dx / b_dist;
                    const ny = b_dy / b_dist;
                    const kx = b.vx - b2.vx;
                    const ky = b.vy - b2.vy;
                    const p = 2 * (nx * kx + ny * ky) / 2.0;
                    b.vx -= p * nx * 0.85;
                    b.vy -= p * ny * 0.85;
                    b2.vx += p * nx * 0.85;
                    b2.vy += p * ny * 0.85;
                    const overlap = minDist - b_dist;
                    b.x -= nx * overlap * 0.5;
                    b.y -= ny * overlap * 0.5;
                    b2.x += nx * overlap * 0.5;
                    b2.y += ny * overlap * 0.5;
                }
            }
            
            ctx.beginPath();
            ctx.arc(b.x, b.y, b.radius, 0, Math.PI * 2);
            ctx.fillStyle = b.color;
            ctx.fill();
            const shineGrad = ctx.createRadialGradient(
                b.x - b.radius/3, b.y - b.radius/3, b.radius/10,
                b.x, b.y, b.radius
            );
            shineGrad.addColorStop(0, 'rgba(255,255,255,0.65)');
            shineGrad.addColorStop(0.4, 'rgba(255,255,255,0)');
            shineGrad.addColorStop(1, 'rgba(0,0,0,0.4)');
            ctx.fillStyle = shineGrad;
            ctx.fill();
            ctx.closePath();
        }
    }
    
    animatePhysics();

    // Загрузка Баланса Пользователя
        async function sendTimezone() {
        try {
            const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
            if (tz) {
                await fetch('/api/user/timezone', {
                    method: 'POST',
                    headers: authHeaders({'Content-Type': 'application/json'}),
                    body: JSON.stringify({timezone: tz})
                });
            }
        } catch (e) {
            console.error(e);
        }
    }
    
    sendTimezone();
    async function loadUserBalance() {
        try {
            const res = await fetch('/api/user/balance', {
                headers: authHeaders()
            });
            if (res.ok) {
                const data = await res.json();
                currentUserBalance = Number(data.balance || 0);
                document.getElementById('user-balance').innerText = currentUserBalance.toFixed(2);
            }
        } catch (e) {
            console.error(e);
        }
    }

    function openTicketModal() {
        const maxCount = currentTicketPrice > 0 ? Math.max(0, Math.floor(currentUserBalance / currentTicketPrice)) : 0;
        document.getElementById('ticket-modal').style.display = 'flex';
        document.getElementById('ticket-qty-input').value = maxCount > 0 ? '1' : '0';
        document.getElementById('ticket-modal-price').innerText = currentTicketPrice.toFixed(2);
        document.getElementById('ticket-modal-max').innerText = String(maxCount);
    }

    function closeTicketModal() {
        document.getElementById('ticket-modal').style.display = 'none';
    }

    function setTicketQty(value) {
        document.getElementById('ticket-qty-input').value = String(value);
    }

    function setMaxTicketQty() {
        const maxCount = currentTicketPrice > 0 ? Math.max(0, Math.floor(currentUserBalance / currentTicketPrice)) : 0;
        document.getElementById('ticket-qty-input').value = String(maxCount);
    }

    async function confirmBuyTickets() {
        const qtyInput = document.getElementById('ticket-qty-input');
        const quantity = parseInt(qtyInput.value || '0', 10);
        if (!Number.isFinite(quantity) || quantity < 1) {
            window.Telegram.WebApp.showAlert('❌ Введи корректное количество билетов.');
            return;
        }
        try {
            const res = await fetch('/api/lottery/buy', {
                method: 'POST',
                headers: authHeaders({'Content-Type': 'application/json'}),
                body: JSON.stringify({quantity})
            });
            const data = await res.json();
            if (res.ok && data.ok) {
                closeTicketModal();
                window.Telegram.WebApp.HapticFeedback.notificationOccurred('success');
                currentUserBalance = Number(data.balance || 0);
                document.getElementById('user-balance').innerText = currentUserBalance.toFixed(2);
                window.Telegram.WebApp.showAlert('🎟 Куплено билетов: ' + data.quantity + '. Баланс обновлен!');
                tick();
            } else {
                window.Telegram.WebApp.showAlert('❌ Ошибка покупки: ' + (data.error || 'неизвестно'));
            }
        } catch (e) {
            window.Telegram.WebApp.showAlert('❌ Сбой сервера покупки билетов.');
        }
    }

    // Модальное окно Звёзд
    function openStarsModal() {
        document.getElementById('stars-modal').style.display = 'flex';
    }
    function closeStarsModal() {
        document.getElementById('stars-modal').style.display = 'none';
    }

    // Покупка пака монет за звёзды прямо в WebApp!
    async function buyCoins(packageId) {
        try {
            const res = await fetch('/api/lottery/buy-coins', {
                method: 'POST',
                headers: authHeaders({'Content-Type': 'application/json'}),
                body: JSON.stringify({package_id: packageId})
            });
            const data = await res.json();
            if (res.ok && data.ok) {
                closeStarsModal();
                // Открываем нативный инвойс оплаты Telegram Stars прямо в WebApp!
                window.Telegram.WebApp.openInvoice(data.invoice_link, function(status) {
                    if (status === 'paid') {
                        window.Telegram.WebApp.HapticFeedback.notificationOccurred('success');
                        window.Telegram.WebApp.showAlert('💎 Оплата успешно завершена! Пакет монет начислен!');
                        setTimeout(loadUserBalance, 1500);
                    }
                });
            } else {
                window.Telegram.WebApp.showAlert('❌ Ошибка создания инвойса: ' + (data.error || 'неизвестно'));
            }
        } catch (e) {
            window.Telegram.WebApp.showAlert('❌ Сбой соединения с платежным шлюзом.');
        }
    }

    // Модальное окно Офферов
    function openOffersModal() {
        document.getElementById('offers-modal').style.display = 'flex';
        loadOffers();
    }
    function closeOffersModal() {
        document.getElementById('offers-modal').style.display = 'none';
    }

    async function loadOffers() {
        const list = document.getElementById('offers-list');
        list.innerHTML = '<div style="text-align: center; color: var(--tg-theme-hint-color); padding: 15px;">Загрузка заданий...</div>';
        try {
            const res = await fetch('/api/lottery/offers');
            if (res.ok) {
                const data = await res.json();
                if (data.offers && data.offers.length > 0) {
                    list.innerHTML = '';
                    data.offers.forEach(o => {
                        const div = document.createElement('div');
                        div.className = 'package-item';
                        div.innerHTML = `
                            <div><b>${o.title}</b><br><small style="color: var(--tg-theme-hint-color);">Награда: +${o.reward} 🪙</small></div>
                            <button class="banner-btn" style="padding: 6px 12px; font-size: 11px;" onclick="window.Telegram.WebApp.openLink('${o.url}')">Выполнить</button>
                        `;
                        list.appendChild(div);
                    });
                } else {
                    list.innerHTML = '<div style="text-align: center; color: var(--tg-theme-hint-color); padding: 15px;">Доступных офферов пока нет.</div>';
                }
            }
        } catch (e) {
            list.innerHTML = '<div style="text-align: center; color: red; padding: 15px;">Ошибка загрузки.</div>';
        }
    }

    // Интерактивные ставки на бочонки прямо в WebApp!
    function placeBetAction(type) {
        window.Telegram.WebApp.showPopup({
            title: '🎯 Ставка на ' + (type === 'first' ? '1-й' : 'последний') + ' бочонок',
            message: 'Сделай прогноз на чётность ' + (type === 'first' ? 'первого' : 'последнего') + ' бочонка. Стоимость ставки: 10 монет (удвоение при выигрыше!)',
            buttons: [
                {id: 'even', type: 'default', text: 'ЧЁТНЫЙ 🟢'},
                {id: 'odd', type: 'default', text: 'НЕЧЁТНЫЙ 🔴'},
                {id: 'cancel', type: 'cancel', text: 'Отмена'}
            ]
        }, async function(buttonId) {
            if (buttonId === 'even' || buttonId === 'odd') {
                const betType = type + '_' + buttonId;
                try {
                    const res = await fetch('/api/lottery/place-bet', {
                        method: 'POST',
                        headers: authHeaders({'Content-Type': 'application/json'}),
                        body: JSON.stringify({bet_type: betType})
                    });
                    const data = await res.json();
                    if (res.ok && data.ok) {
                        window.Telegram.WebApp.HapticFeedback.notificationOccurred('success');
                        window.Telegram.WebApp.showAlert('🎯 Ставка успешно зарегистрирована в Секслото! Баланс монет обновлен!');
                        document.getElementById('user-balance').innerText = data.balance.toFixed(2);
                    } else {
                        window.Telegram.WebApp.showAlert('❌ Ставка отклонена: ' + (data.error || 'неизвестно'));
                    }
                } catch (e) {
                    window.Telegram.WebApp.showAlert('❌ Сбой сервера ставок.');
                }
            }
        });
    }

    function updateTimer() {
        if (!drawStartsAt) return;
        let drawDateStr = drawStartsAt;
        if (!drawDateStr.endsWith('Z')) drawDateStr += 'Z';
        const drawDate = new Date(drawDateStr);
        const now = new Date();
        const diff = drawDate - now;
        
        const timerBox = document.getElementById('timer-box');
        const countdown = document.getElementById('countdown');
        
        if (diff <= 0 || isSpinning) {
            timerBox.style.display = 'none';
        } else {
            timerBox.style.display = 'block';
            const hours = Math.floor(diff / 3600000);
            const minutes = Math.floor((diff % 3600000) / 60000);
            const seconds = Math.floor((diff % 60000) / 1000);
            countdown.innerText = 
                String(hours).padStart(2, '0') + ':' + 
                String(minutes).padStart(2, '0') + ':' + 
                String(seconds).padStart(2, '0');
        }
    }

    function updateUI(data) {
        document.getElementById('round-id').innerText = '#' + data.round_id;
        drawStartsAt = data.draw_starts_at;
        
        let statusText = '';
        let badgeClass = 'status-badge ';
        const tip = document.getElementById('interactive-tip');
        const banners = document.getElementById('banners-container');
        const timerBox = document.getElementById('timer-box');
        
        if (data.status === 'open') {
            statusText = 'Открыта';
            badgeClass += 'status-open';
            isSpinning = false;
            tip.style.display = 'block';
            banners.style.display = 'block';
            timerBox.style.display = 'block';
        } else if (data.status === 'drawing') {
            statusText = 'Идет розыгрыш!';
            badgeClass += 'status-drawing';
            isSpinning = true;
            tip.style.display = 'none'; 
            banners.style.display = 'none'; 
            timerBox.style.display = 'none'; 
        } else if (data.status === 'completed') {
            statusText = 'Завершена';
            badgeClass += 'status-completed';
            isSpinning = false;
            tip.style.display = 'block';
            banners.style.display = 'block';
            timerBox.style.display = 'none'; 
        }
        
        const badge = document.getElementById('status-badge');
        badge.innerText = statusText;
        badge.className = badgeClass;

        currentTicketPrice = Number(data.ticket_price || 0);
        document.getElementById('prize-pool').innerText = data.prize_pool + ' 🪙';
        document.getElementById('ticket-price').innerText = data.ticket_price + ' 🪙';
        document.getElementById('banner-ticket-price').innerText = data.ticket_price;
        document.getElementById('tickets-count').innerText = data.tickets_count;
        
        let drawDateStr = data.draw_starts_at;
        if (!drawDateStr.endsWith('Z')) drawDateStr += 'Z';
        const drawDate = new Date(drawDateStr);
        document.getElementById('draw-time').innerText = drawDate.toLocaleString();

        const container = document.getElementById('balls-container');
        
        if (lastRoundId !== data.round_id) {
            container.innerHTML = '';
            lastRoundId = data.round_id;
        }

        if (data.drawn_numbers && data.drawn_numbers.length > 0) {
            const currentBalls = container.querySelectorAll('.ball').length;
            if (data.drawn_numbers.length > currentBalls) {
                if (container.querySelector('.no-numbers')) {
                    container.innerHTML = '';
                }
                for (let i = currentBalls; i < data.drawn_numbers.length; i++) {
                    const ball = document.createElement('div');
                    ball.className = 'ball';
                    ball.innerText = data.drawn_numbers[i];
                    container.appendChild(ball);
                    if (window.Telegram.WebApp.HapticFeedback) {
                        window.Telegram.WebApp.HapticFeedback.impactOccurred('medium');
                    }
                }
            }
        } else {
            if (container.children.length === 0) {
                container.innerHTML = '<div class="no-numbers" style="color: var(--tg-theme-hint-color); font-size: 14px; text-align:center; width:100%;">Розыгрыш еще не начался...</div>';
            }
        }
        
        updateTimer();
    }

    async function tick() {
      try {
        const res = await fetch('/lottery/state');
        if(res.ok) {
            const data = await res.json();
            updateUI(data);
        }
      } catch (e) {
        console.error('Fetch error:', e);
      }
    }
    
    // Начальная загрузка баланса
    loadUserBalance();
    
    setInterval(tick, 1000);
    tick();
  </script>
</body>
</html>
"""
    return web.Response(text=html, content_type="text/html")


async def api_videofeed_feed(request: web.Request) -> web.Response:
    try:
        async with async_session() as session:
            videos = (await session.execute(
                select(Video).where(Video.status == "approved")
                .order_by(func.random()).limit(10)
            )).scalars().all()
            
            data = [{"id": v.id, "author": v.uploader_user_id} for v in videos]
            headers = {"Access-Control-Allow-Origin": "*"}
            return web.json_response({"videos": data}, headers=headers)
    except Exception:
        return web.json_response({"error": "Internal Server Error"}, status=500)

async def api_video_stream(request: web.Request) -> web.Response:
    video_id = request.match_info.get("id")
    if not video_id or not video_id.isdigit():
        return web.Response(status=400, text="Invalid ID")

    async with async_session() as session:
        video = await session.get(Video, int(video_id))
        if not video:
            return web.Response(status=404, text="Not found")
        if video.status != "approved" or video.content_type != "video":
            return web.Response(status=403, text="Forbidden")

    bot = request.app['bot']
    cache_dir = "video_cache"
    os.makedirs(cache_dir, exist_ok=True)
    file_path_local = os.path.join(cache_dir, f"{video.telegram_file_unique_id}.mp4")

    if not os.path.exists(file_path_local):
        try:
            tg_file = await bot.get_file(video.telegram_file_id)
            await bot.download_file(tg_file.file_path, file_path_local)
        except TelegramBadRequest as e:
            # File might be larger than 20MB
            return web.Response(status=400, text=f"TG API Error: {str(e)}. File might be >20MB.")
        except Exception as e:
            return web.Response(status=500, text=str(e))

    response = web.FileResponse(file_path_local)
    response.content_type = 'video/mp4'
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

async def videofeed_page_handler(request: web.Request) -> web.Response:
    html = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>VideoFeed</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    body, html { margin: 0; padding: 0; width: 100%; height: 100%; background: #000; overflow: hidden; font-family: -apple-system, sans-serif;}
    .feed {
      width: 100%; height: 100%; overflow-y: scroll; scroll-snap-type: y mandatory; scroll-behavior: smooth;
    }
    .video-container {
      width: 100%; height: 100%; scroll-snap-align: start; position: relative;
      display: flex; justify-content: center; align-items: center; background: #111;
    }
    video {
      width: 100%; height: 100%; object-fit: cover; cursor: pointer;
    }
    .overlay {
      position: absolute; bottom: 80px; right: 15px; display: flex; flex-direction: column; gap: 20px; z-index: 10;
    }
    .btn {
      width: 45px; height: 45px; background: rgba(255,255,255,0.2); border-radius: 50%;
      display: flex; justify-content: center; align-items: center; color: white; font-size: 20px;
      backdrop-filter: blur(5px); cursor: pointer;
    }
    .loading {
      position: absolute; color: rgba(255,255,255,0.5); font-size: 16px; z-index: 1; pointer-events: none;
    }
    .mute-btn {
      position: absolute; top: 20px; right: 20px; width: 40px; height: 40px; background: rgba(0,0,0,0.5); 
      color: white; border-radius: 50%; display: flex; justify-content: center; align-items: center; z-index: 10;
      cursor: pointer; backdrop-filter: blur(5px);
    }
  </style>
</head>
<body>
  <div class="feed" id="feed">
     <div style="color:white; text-align:center; padding-top: 50vh;">Загрузка ленты...</div>
  </div>
  <script>
     window.Telegram.WebApp.ready();
     window.Telegram.WebApp.expand();
     
     let isMuted = true;

     async function loadFeed() {
        try {
            document.getElementById('feed').innerHTML = '<div style="color:yellow; text-align:center; padding-top: 50vh;">Fetching API...</div>';
            
            let host = window.location.origin;
            if (host === "null" || host === "about:blank" || !host.startsWith("http")) {
                host = window.location.href.split('/').slice(0, 3).join('/');
            }
            const api_url = host + '/api/videofeed/feed';
            
            document.getElementById('feed').innerHTML = '<div style="color:yellow; text-align:center; padding-top: 50vh;">Fetching: ' + api_url + '</div>';
            
            const res = await fetch(api_url);
            
            document.getElementById('feed').innerHTML = '<div style="color:yellow; text-align:center; padding-top: 50vh;">Reading Response...</div>';
            const textRaw = await res.text();
            let data;
            try {
                data = JSON.parse(textRaw);
            } catch(e) {
                document.getElementById('feed').innerHTML = '<div style="color:red; padding: 20px;">Parse error: ' + e.message + '<br><br>' + textRaw + '</div>';
                return;
            }
            
            if(data.error) {
                document.getElementById('feed').innerHTML = '<div style="color:red; padding: 20px;">Server error: ' + data.error + '</div>';
                return;
            }
            const feed = document.getElementById('feed');
            feed.innerHTML = ''; // clear loading
            
            if(data.videos.length === 0) {
                feed.innerHTML = '<div style="color:white; text-align:center; padding-top: 50vh;">Нет доступных видео.<br>Загрузи видео в бота!</div>';
                return;
            }

            data.videos.forEach(v => {
                const container = document.createElement('div');
                container.className = 'video-container';
                container.innerHTML = `
                    <div class="loading">Загрузка видео...</div>
                    <video src="/api/video/${v.id}" loop playsinline preload="auto" muted crossOrigin="anonymous" style="background:transparent;"></video>
                    <div class="mute-btn" onclick="toggleMute(event)">🔇</div>
                    <div class="overlay">
                        <div class="btn" onclick="window.Telegram.WebApp.HapticFeedback.impactOccurred('medium'); alert('Функция лайков в разработке!')">❤️</div>
                        <div class="btn" onclick="window.Telegram.WebApp.HapticFeedback.impactOccurred('medium'); alert('Донаты автору в разработке!')">💸</div>
                    </div>
                `;
                
                const vid = container.querySelector('video');
                vid.addEventListener('click', () => {
                    if(vid.paused) vid.play();
                    else vid.pause();
                });
                
                vid.addEventListener('loadeddata', () => {
                    const l = container.querySelector('.loading');
                    if(l) l.remove();
                });

                feed.appendChild(container);
            });
            setupObserver();
        } catch(e) {
            document.getElementById('feed').innerHTML = '<div style="color:red; text-align:center; padding-top: 50vh;">Ошибка загрузки видео.</div>';
        }
     }
     
     window.toggleMute = function(e) {
         if(e) e.stopPropagation();
         isMuted = !isMuted;
         document.querySelectorAll('video').forEach(v => v.muted = isMuted);
         document.querySelectorAll('.mute-btn').forEach(btn => btn.innerText = isMuted ? '🔇' : '🔊');
     };

     function setupObserver() {
        const videos = document.querySelectorAll('video');
        const observer = new IntersectionObserver(entries => {
            entries.forEach(entry => {
                if(entry.isIntersecting) {
                    entry.target.muted = isMuted;
                    let playPromise = entry.target.play();
                    if (playPromise !== undefined) {
                        playPromise.catch(error => {
                            console.log('Autoplay prevented:', error);
                        });
                    }
                } else {
                    entry.target.pause();
                    entry.target.currentTime = 0;
                }
            });
        }, { threshold: 0.6 });
        videos.forEach(v => observer.observe(v));
     }
     loadFeed();
  </script>
</body>
</html>
"""
    return web.Response(text=html, content_type="text/html")

async def handle_health_check(request):
    """Handler for Render health checks"""
    return web.Response(text="Bot is running", status=200)

async def _notify_admins_started(bot: Bot) -> None:
    text = '✅ Бот запущен и готов к работе!'
    for admin_id in ADMINS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception:
            pass


async def _mod_notification_loop(bot):
    """Периодическая отправка агрегированных уведомлений о модерации."""
    await asyncio.sleep(60)  # подождать старта
    while True:
        try:
            await asyncio.sleep(120)  # каждые 2 минуты
            from app.db import async_session
            from app.services import should_flush_notifications, flush_mod_notifications
            async with async_session() as session:
                if await should_flush_notifications(session):
                    await flush_mod_notifications(bot, session)
        except Exception as e:
            log_error(logger, f"Mod notification loop error: {e}")
            await asyncio.sleep(300)


async def _cancel_task(task: asyncio.Task | None) -> None:
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


async def video_cache_cleanup_worker(stop_event: asyncio.Event):
    """Периодически очищает кэш видео, если он стал слишком большим."""
    cache_dir = "video_cache"
    MAX_CACHE_SIZE_MB = 2000  # 2 ГБ
    CLEANUP_INTERVAL = 3600  # Раз в час
    while not stop_event.is_set():
        try:
            if os.path.exists(cache_dir):
                total_size = 0
                files = []
                for f in os.listdir(cache_dir):
                    path = os.path.join(cache_dir, f)
                    if os.path.isfile(path):
                        size = os.path.getsize(path)
                        total_size += size
                        files.append((path, os.path.getmtime(path), size))
                
                if total_size > MAX_CACHE_SIZE_MB * 1024 * 1024:
                    # Сортируем по времени модификации (старые в начале)
                    files.sort(key=lambda x: x[1])
                    while total_size > MAX_CACHE_SIZE_MB * 1024 * 1024 and files:
                        path, _, size = files.pop(0)
                        os.remove(path)
                        total_size -= size
                    log_info(logger, f"Video cache cleaned. Current size: {total_size / (1024*1024):.2f} MB")
        except Exception as e:
            log_error(logger, f"Video cache cleanup error: {e}")
        await asyncio.sleep(CLEANUP_INTERVAL)


async def auto_broadcast_worker(bot):
    import asyncio
    import random
    from app.db import async_session
    from app.models import User
    from sqlalchemy import select
    
    # Готовые шаблоны сообщений рассылки для ротации (ровно 25 штук)
    templates = [
        '🎰 <b>Секслото — розыгрыш монет</b>\n\nНовый раунд уже открыт! Купи билет за монеты и следи за розыгрышем в прямом эфире. Размер призового фонда зависит от количества купленных билетов. 🎡\n\n👉 Зайди в меню <b>🎰 Секслото</b>',
        '💋 <b>Виртуальные подруги заждались тебя...</b>\n\nСаня, Катя и Софа скучают и хотят поболтать. Они подготовили новые пикантные темы для беседы и сочные стикеры! 😏🤸‍♀️\n\n👉 Нажми кнопку <b>💋 ИИ-Общение</b> в главном меню!',
        '🎟 <b>Создавай свои промокоды за Stars!</b>\n\nХочешь порадовать подписчиков своего канала или друзей? Создай свой уникальный промокод на любую сумму монет и подари его им! 🎁\n\n👉 Перейди в меню <b>🎟 Промокоды ➔ 🎟 Создать промокод</b>',
        '👑 <b>Получи статус VIP-пользователя!</b>\n\nVIP даёт множитель начисления монет ×2, скидку на просмотр видео, просмотр фото без дневного лимита и дополнительные бонусы в экономике. ⭐\n\n👉 Перейди в меню <b>👑 VIP</b>!',
        '🎬 <b>Новый контент уже в ленте!</b>\n\nНаши пользователи загрузили кучу свежего и интересного контента. Скорее заходи в ленту, смотри, оценивай и оставляй комментарии! 💬\n\n👉 Нажми кнопку <b>🎬 Смотреть</b> в меню!',
        '📤 <b>Зарабатывай на своем контенте!</b>\n\nЗагрузи видео или фото прямо сейчас! Пользователи будут смотреть и оценивать твой контент, а ты получишь награду по текущим настройкам бота. 🚀\n\n👉 Нажми кнопку <b>📤 Загрузить</b>!',
        '👥 <b>Позови друзей и забери бонусы!</b>\n\nСкопируй свою реферальную ссылку и отправь друзьям. За каждого приглашенного ты получишь бонус в монетах! Растем вместе! 🤝\n\n👉 Перейди в раздел <b>👥 Рефералы</b>!',
        '🐞 <b>Нашёл баг или есть идея?</b>\n\nМы постоянно улучшаем бота и ценим любое твое мнение. Напиши нам о любой ошибке или предложи крутую функцию в разделе поддержки!\n\n👉 Кнопка <b>💬 Жалобы и предложения</b>!',
        '🎁 <b>Забери еженедельную халяву!</b>\n\nРаз в неделю бот рассылает секретный промокод на бесплатные монеты. Активируй его и забери награду! 🎟\n\n👉 Раздел <b>🎟 Промокоды ➔ Активировать промокод</b>!',
        '📈 <b>Прокачай свой уровень в системе!</b>\n\nЗа каждую активность (просмотры, загрузки, комменты) ты получаешь XP. Повышение уровня открывает доступ к элитным никам и бонусам! 📊\n\n👉 Посмотри свой ранг в меню <b>📊 Уровень</b>!',
        '🏆 <b>Топы игроков</b>\n\nСравни результаты с другими пользователями: в разделе доступны рейтинги загрузчиков, зрителей, XP и текущего баланса. 🥇\n\n👉 Посмотри лидеров в меню <b>🏆 Топы</b>!',
        '💬 <b>Общайся и обсуждай контент!</b>\n\nПод каждым одобренным видео есть раздел комментариев. Делись своим мнением с другими пользователями и ставьте яркие реакции! 🔥\n\n👉 Зайди в меню <b>🎬 Смотреть</b>!',
        '🔥 <b>Поставь реакцию на любимые ролики!</b>\n\nПоделись эмоциями: поставь огонёк, сердечко или лайк под понравившимся контентом! Это помогает авторам расти. ❤️\n\n👉 Раздел <b>🎬 Смотреть</b>!',
        '💎 <b>Оформи профиль элитными символами!</b>\n\nУ нас доступно 168 премиум-стилей никнеймов на базе рун, алхимии и дзен-символов. Сделай свой профиль самым красивым и узнаваемым! ✨\n\n👉 Посмотри стили в меню <b>👤 Профиль</b>!',
        '🎡 <b>Следи за барабаном Секслото!</b>\n\nНе пропусти розыгрыш в прямом эфире! Следи за выпадением бочонков прямо через встроенный Mini App. 🔴\n\n👉 Раздел <b>🎰 Секслото ➔ 🔴 Открыть Live</b>!',
        '💳 <b>Пополнение баланса</b>\n\nНужно больше монет для промокодов или общения? Выбери пакет и оплатите его через Telegram Stars. ⚡\n\n👉 Нажми кнопку <b>💳 Купить монеты</b>!'
    ]
    
    await asyncio.sleep(60) # подождать старта бота
    while True:
        try:
            # Рандомный интервал от 20 минут до 6 часов
            interval_sec = random.randint(20 * 60, 6 * 3600)
            await asyncio.sleep(interval_sec)
            
            # Выбираем случайное сообщение
            msg_text = random.choice(templates)
            
            async with async_session() as session:
                users = (await session.execute(select(User.telegram_id).where(User.status == "active"))).scalars().all()
                
            sent = 0
            for tid in users:
                try:
                    await bot.send_message(tid, msg_text, parse_mode="HTML")
                    sent += 1
                    if sent % 30 == 0:
                        await asyncio.sleep(0.5)
                except Exception:
                    pass
        except Exception as e:
            await asyncio.sleep(60)



# =========================
# WEB APP API HANDLERS
# =========================
async def api_user_balance(request: web.Request) -> web.Response:
    try:
        telegram_user_id = _get_webapp_user_id(request)
        if not telegram_user_id:
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

        from app.services import get_user
        from app.db import async_session
        async with async_session() as session:
            user = await get_user(session, telegram_user_id)
            if not user:
                return web.json_response({"ok": False, "error": "User not found"})
            return web.json_response({"ok": True, "balance": float(user.balance)})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})

async def api_lottery_buy(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        telegram_user_id = _get_webapp_user_id(request, data)
        if not telegram_user_id:
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

        quantity = int(data.get("quantity", 1) or 1)

        from app.services import get_user, buy_lottery_tickets
        from app.db import async_session
        async with async_session() as session:
            user = await get_user(session, telegram_user_id)
            if not user:
                return web.json_response({"ok": False, "error": "User not found"})
            tickets, total_cost, error = await buy_lottery_tickets(session, user, quantity)
            if error or not tickets:
                return web.json_response({"ok": False, "error": error or "purchase_failed"})
            await session.refresh(user)
            return web.json_response({
                "ok": True,
                "balance": float(user.balance),
                "quantity": len(tickets),
                "total_cost": float(total_cost),
                "ticket_ids": [t.id for t in tickets[:20]],
            })
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})

async def api_lottery_buy_coins(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        telegram_user_id = _get_webapp_user_id(request, data)
        if not telegram_user_id:
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

        pack_key = data.get("package_id", "")
        from app.services import get_user, create_payment, get_current_prices
        from app.db import async_session
        from app.config import STARS_PACKAGES
        pack = STARS_PACKAGES.get(pack_key)
        if not pack:
            return web.json_response({"ok": False, "error": "Unknown package"})

        async with async_session() as session:
            user = await get_user(session, telegram_user_id)
            if not user:
                return web.json_response({"ok": False, "error": "User not found"})

            _, current_packs, _ = await get_current_prices(session, user.id)
            current_pack = current_packs.get(pack_key)
            if not current_pack:
                return web.json_response({"ok": False, "error": "Unknown package"})

            payment = await create_payment(
                session,
                user.id,
                pack_key,
                stars_amount_override=current_pack["stars"],
            )

            from aiogram.types import LabeledPrice
            bot = request.app['bot']
            link = await bot.create_invoice_link(
                title=f"Покупка {pack['title']}",
                description=f"{pack['coins']} монет за {current_pack['stars']} Stars",
                payload=payment.payload,
                currency="XTR",
                prices=[LabeledPrice(label=pack['title'], amount=current_pack['stars'])]
            )
            return web.json_response({"ok": True, "invoice_link": link})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})

async def api_lottery_offers(request: web.Request) -> web.Response:
    try:
        from app.services import get_active_offers
        from app.db import async_session
        async with async_session() as session:
            offers = await get_active_offers(session)
            res_offers = [{"id": o.id, "title": o.title, "reward": float(o.reward_preview), "url": o.channel_url} for o in offers[:5]]
            return web.json_response({"ok": True, "offers": res_offers})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})

async def api_lottery_place_bet(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        telegram_user_id = _get_webapp_user_id(request, data)
        if not telegram_user_id:
            return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

        bet_type = data.get("bet_type", "")
        allowed_bets = {"first_even", "first_odd", "last_even", "last_odd"}
        if bet_type not in allowed_bets:
            return web.json_response({"ok": False, "error": "Неверный тип ставки"})

        from app.services import get_user, ensure_current_lottery_round, change_balance_atomic, to_decimal

        # В Mini App ставка фиксированная: 10 монет.
        bet_amount = to_decimal(data.get("bet_amount", 10) or 10)
        from app.db import async_session
        from app.models import LotteryBet
        async with async_session() as session:
            user = await get_user(session, telegram_user_id)
            if not user:
                return web.json_response({"ok": False, "error": "User not found"})
            if user.balance < bet_amount:
                return web.json_response({"ok": False, "error": "Недостаточно монет"})

            round_obj = await ensure_current_lottery_round(session)
            if round_obj.status != "open":
                return web.json_response({"ok": False, "error": "Прием ставок закрыт"})

            await change_balance_atomic(session, user.id, -bet_amount, "lottery_bet", source_id=round_obj.id, details=f"type={bet_type}")
            bet = LotteryBet(
                user_id=user.id,
                round_id=round_obj.id,
                bet_type=bet_type,
                amount=bet_amount,
            )
            session.add(bet)
            await session.commit()
            await session.refresh(user)
            return web.json_response({"ok": True, "balance": float(user.balance)})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})

async def api_user_timezone(request: web.Request) -> web.Response:
    try:
        data = await request.json()
        telegram_user_id = _get_webapp_user_id(request, data)
        timezone = data.get("timezone", "")
        if not telegram_user_id or not timezone:
            return web.json_response({"ok": False}, status=401)

        from app.services import get_user
        from app.db import async_session
        async with async_session() as session:
            user = await get_user(session, telegram_user_id)
            if user:
                user.timezone = timezone
                await session.commit()
                return web.json_response({"ok": True})
        return web.json_response({"ok": False})
    except Exception:
        return web.json_response({"ok": False})

async def on_startup(app):
    bot = app['bot']

    from app.config import DATABASE_URL
    is_sqlite = (not DATABASE_URL) or "sqlite" in DATABASE_URL

    try:
        if is_sqlite:
            # Для SQLite поднимаем схему напрямую из ORM — это dev/test путь.
            await init_db()
            log_info(logger, "SQLite detected. ORM schema initialized.")
        else:
            # Для Postgres/production сначала прогоняем Alembic, чтобы не создавать
            # таблицы в обход миграций и не ломать историю версий.
            def run_migrations():
                alembic_cfg = Config("alembic.ini")
                command.upgrade(alembic_cfg, "head")

            await asyncio.to_thread(run_migrations)
            log_info(logger, "Alembic migrations synced")
    except Exception as e:
        log_error(logger, f"Migration sync error: {e}")

    if not is_sqlite:
        # Self-heal: если базовой схемы всё ещё нет (свежая БД, а alembic-цепочка
        # с нуля не поднимается), создаём таблицы из ORM-моделей и штампуем head.
        try:
            from sqlalchemy import text as _text
            async with engine.connect() as conn:
                r = await conn.execute(_text("SELECT to_regclass('public.users')"))
                has_users = r.scalar() is not None
            if not has_users:
                log_error(logger, "users table missing — creating schema from models (self-heal)")
                await init_db()

                def stamp_head():
                    alembic_cfg = Config("alembic.ini")
                    command.stamp(alembic_cfg, "head")

                await asyncio.to_thread(stamp_head)
                log_info(logger, "Schema created from models, alembic stamped to head (self-heal)")
        except Exception as e:
            log_error(logger, f"Schema self-heal error: {e}")

    # DB Maintenance
    from app.utils.db_fix import fix_database
    try:
        await fix_database()
        log_info(logger, "Database maintenance complete")
    except Exception as e:
        log_error(logger, f"Database maintenance error: {e}")
        
    await _notify_admins_started(bot)

    # Загрузка стикеров Кати
    try:
        from app.ai_assistant import load_sticker_set
        await load_sticker_set(bot)
    except Exception as e:
        log_error(logger, f"Katya sticker load error: {e}")

    log_info(logger, "Service initialized")



async def retention_worker(bot: Bot, stop_event: asyncio.Event):
    """
    Рассылка: отправляем бонус пользователям с низким балансом,
    которые смотрели видео 1-2 часа назад и еще не получали такой пуш.
    """
    from sqlalchemy import select
    from datetime import timedelta
    from app.models import User, VideoView, UserActionLog
    from app.services import change_balance_atomic, to_decimal
    
    while not stop_event.is_set():
        try:
            async with async_session() as session:
                from app.models import utc_now
                now = utc_now()
                one_hour_ago = now - timedelta(hours=1)
                two_hours_ago = now - timedelta(hours=2)
                
                # Ищем юзеров с балансом < 10 (мало для просмотра)
                low_balance_users = (await session.execute(
                    select(User).where(User.balance < to_decimal(10.0), User.status == "active")
                )).scalars().all()
                
                for u in low_balance_users:
                    # Проверяем, отправляли ли уже пуш
                    got_push = (await session.execute(
                        select(UserActionLog).where(
                            UserActionLog.user_id == u.id, 
                            UserActionLog.action == "retention_push"
                        )
                    )).scalars().first()
                    
                    if got_push:
                        continue
                        
                    # Проверяем последний просмотр видео
                    last_view = (await session.execute(
                        select(VideoView).where(VideoView.user_id == u.id)
                        .order_by(VideoView.watched_at.desc())
                        .limit(1)
                    )).scalars().first()
                    
                    if last_view and two_hours_ago <= last_view.watched_at <= one_hour_ago:
                        # Начисляем бонус
                        bonus = 30.0
                        await change_balance_atomic(session, u.id, to_decimal(bonus), "retention_bonus")
                        log = UserActionLog(user_id=u.id, action="retention_push", details=f"Sent {bonus} coins")
                        session.add(log)
                        await session.commit()
                        
                        try:
                            bot_info = await bot.get_me()
                            ref_link = f"https://t.me/{bot_info.username}?start={u.referral_code}"
                            await bot.send_message(
                                u.telegram_id,
                                "😭 <b>Мы заметили, что у тебя кончились монетки!</b>\n\n"
                                f"Не уходи просто так! Мы начислили тебе <b>+{bonus} бонусных монет</b>, чтобы ты мог посмотреть еще пару сливчиков. 🔥\n\n"
                                "👉 <b>Хочешь смотреть бесконечно?</b>\n"
                                f"Скинь эту ссылку друзьям:\n<code>{ref_link}</code>\n\n"
                                "За каждого, кто посмотрит 5 видео, мы начислим тебе огромный бонус! Ждем тебя в ленте 🎬",
                                parse_mode="HTML"
                            )
                        except Exception:
                            pass
        except Exception as e:
            logger.error(f"Retention worker error: {e}")
            
        # Проверяем каждые 15 минут
        for _ in range(15 * 60):
            if stop_event.is_set():
                break
            await asyncio.sleep(1)

async def weekly_promo_worker(bot: Bot, stop_event: asyncio.Event):
    import string, random
    from sqlalchemy import select
    from app.config import WEEKLY_PROMO_DAY, WEEKLY_PROMO_HOUR, WEEKLY_PROMO_AMOUNT, WEEKLY_PROMO_USES
    from app.models import Promocode, User
    from app.services import to_decimal
    
    last_run_week = None
    
    while not stop_event.is_set():
        try:
            now_utc = datetime.now(timezone.utc)

            async with async_session() as session:
                from app.services import get_setting

                db_day = await get_setting(session, "weekly_promo_day", "")
                db_hour = await get_setting(session, "weekly_promo_hour", "")
                db_amount = await get_setting(session, "weekly_promo_amount", "")

                p_day = int(db_day) if db_day.isdigit() else WEEKLY_PROMO_DAY
                p_hour = int(db_hour) if db_hour.isdigit() else WEEKLY_PROMO_HOUR
                p_amount = float(db_amount) if db_amount else WEEKLY_PROMO_AMOUNT
                p_uses = 999999

                # Настройка часа в админке подписана как UTC — соблюдаем это в рантайме.
                if now_utc.weekday() == p_day and now_utc.hour == p_hour:
                    current_week = now_utc.isocalendar()[1]
                    if last_run_week != current_week:
                        last_run_week = current_week
                        
                        code = "FREEBIE_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
                        
                        super_admin_id = ADMINS[0] if ADMINS else 1
                        admin_user = (await session.execute(select(User).where(User.telegram_id == super_admin_id))).scalars().first()
                        creator_id = admin_user.id if admin_user else 1
                        
                        promo = Promocode(
                            creator_user_id=creator_id,
                            code=code,
                            coin_amount=to_decimal(p_amount),
                            max_uses=p_uses,
                            used_count=0,
                            is_active=True,
                            expires_at=now_utc + timedelta(days=2)
                        )
                        session.add(promo)
                        await session.commit()
                        
                        users = (await session.execute(select(User.telegram_id).where(User.status == "active"))).scalars().all()
                        
                        msg = (
                            "🎁 <b>ЕЖЕНЕДЕЛЬНАЯ ХАЛЯВА!</b>\n\n"
                            f"Лови секретный промокод на <b>{p_amount}</b> монет!\n"
                            f"Активировать: <code>/start promo_{code}</code>\n\n"
                            "<i>Количество активаций не ограничено.</i>"
                        )
                        
                        sent = 0
                        for uid in users:
                            try:
                                await bot.send_message(uid, msg, parse_mode="HTML")
                                sent += 1
                                if sent % 30 == 0:
                                    await asyncio.sleep(0.5)
                            except Exception:
                                pass
        except Exception as e:
            logger.error(f"Weekly promo worker error: {e}")
            
        await asyncio.sleep(60)


# ============================
# 🎁 КЕЙСЫ (Mini App)
# ============================

CASES_PAGE_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"/>
<title>Кейсы</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root {
  --bg: #0f1015;
  --panel: #1a1c23;
  --accent: #ffb700;
  --blue: #4b69ff;
  --purple: #8847ff;
  --pink: #d32ce6;
  --red: #eb4b4b;
  --gold: #e4ae39;
  --text: #ffffff;
}
* { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'Segoe UI', Roboto, sans-serif;
  height: 100vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.header {
  padding: 15px;
  background: var(--panel);
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 2px solid rgba(255,255,255,0.05);
}
.balance { font-weight: bold; color: var(--accent); font-size: 18px; }

.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 20px;
  gap: 30px;
}

/* Spinner Styles */
.spinner-container {
  width: 100%;
  max-width: 600px;
  height: 140px;
  background: var(--panel);
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(255,255,255,0.1);
  box-shadow: inset 0 0 40px rgba(0,0,0,0.5);
}
.spinner-container::before {
  content: '';
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  width: 2px;
  background: var(--accent);
  z-index: 10;
  box-shadow: 0 0 15px var(--accent);
}
.spinner-track {
  display: flex;
  position: absolute;
  left: 0;
  top: 0;
  height: 100%;
  transition: transform 7s cubic-bezier(0.1, 0, 0.1, 1);
}
.item {
  width: 120px;
  height: 100%;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border-right: 1px solid rgba(255,255,255,0.05);
  position: relative;
  padding: 10px;
  text-align: center;
}
.item-bg {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 4px;
}
.item-icon { font-size: 40px; margin-bottom: 5px; filter: drop-shadow(0 0 10px rgba(255,255,255,0.2)); }
.item-label { font-size: 11px; font-weight: bold; text-transform: uppercase; opacity: 0.8; }
.item-value { font-size: 14px; font-weight: 900; }

.rarity-common { color: var(--blue); }
.rarity-rare { color: var(--purple); }
.rarity-epic { color: var(--pink); }
.rarity-jackpot { color: var(--red); }
.rarity-gold { color: var(--gold); }

.bg-common { background: var(--blue); }
.bg-rare { background: var(--purple); }
.bg-epic { background: var(--pink); }
.bg-jackpot { background: var(--red); }
.bg-gold { background: var(--gold); }

.controls {
  width: 100%;
  max-width: 400px;
  display: flex;
  flex-direction: column;
  gap: 15px;
}
.btn-open {
  background: linear-gradient(to bottom, #4CAF50, #2E7D32);
  color: white;
  border: none;
  padding: 18px;
  border-radius: 8px;
  font-size: 18px;
  font-weight: bold;
  cursor: pointer;
  box-shadow: 0 4px 0 #1B5E20;
  text-transform: uppercase;
}
.btn-open:active { transform: translateY(2px); box-shadow: 0 2px 0 #1B5E20; }
.btn-open:disabled { background: #555; box-shadow: 0 4px 0 #333; opacity: 0.6; }

.pity-info { font-size: 13px; color: #888; text-align: center; }

.case-selector {
  display: flex;
  gap: 10px;
  width: 100%;
  overflow-x: auto;
  padding-bottom: 10px;
}
.case-card {
  flex-shrink: 0;
  width: 120px;
  background: var(--panel);
  padding: 15px;
  border-radius: 12px;
  text-align: center;
  border: 2px solid transparent;
}
.case-card.active { border-color: var(--accent); background: rgba(255,183,0,0.05); }
.case-card-icon { font-size: 30px; margin-bottom: 10px; }
.case-card-name { font-size: 12px; font-weight: bold; margin-bottom: 5px; }
.case-card-price { font-size: 14px; color: var(--accent); font-weight: bold; }

#win-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.9);
  z-index: 100;
  display: none;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  animation: fadeIn 0.5s ease;
}
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

.win-title { font-size: 24px; color: var(--accent); margin-bottom: 20px; }
.win-item { font-size: 80px; margin-bottom: 20px; }
.win-name { font-size: 20px; font-weight: bold; margin-bottom: 30px; }

</style>
</head>
<body>

<div class="header">
  <div>КЕЙСЫ <span id="case-name-top">ОБЫЧНЫЙ</span></div>
  <div class="balance"><span id="balance-val">0.00</span> 🪙</div>
</div>

<div class="main">
  <div class="case-selector" id="case-selector">
    <!-- Кнопки выбора кейсов -->
  </div>

  <div class="spinner-container">
    <div class="spinner-track" id="spinner-track">
      <!-- Элементы будут тут -->
    </div>
  </div>

  <div class="controls">
    <button class="btn-open" id="btn-open">ОТКРЫТЬ ЗА <span id="open-price">100</span></button>
    <div class="pity-info" id="pity-info">До гаранта Редкого+: 10</div>
  </div>
</div>

<div id="win-overlay">
  <div class="win-title">ПРЕДМЕТ ПОЛУЧЕН!</div>
  <div class="win-item" id="win-icon">🎁</div>
  <div class="win-name" id="win-name">???</div>
  <button class="btn-open" onclick="closeWin()">ОТЛИЧНО</button>
</div>

<script>
const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

const track = document.getElementById('spinner-track');
const btnOpen = document.getElementById('btn-open');
const winOverlay = document.getElementById('win-overlay');

let balance = 0;
let currentCase = 'common';
let pity = 10;
let isSpinning = false;

const RARITIES = {
  common: { name: 'Армейское', color: 'blue' },
  rare: { name: 'Запрещенное', color: 'purple' },
  epic: { name: 'Засекреченное', color: 'pink' },
  jackpot: { name: 'Тайное', color: 'red' },
  gold: { name: 'Золотое', color: 'gold' }
};

const ITEMS_DATA = {
  coins: { icon: '🪙', label: 'Монеты' },
  style: { icon: '🎨', label: 'Стиль ника' }
};

function createItemEl(data) {
  const div = document.createElement('div');
  div.className = `item rarity-${data.rarity}`;
  div.innerHTML = `
    <div class="item-icon">${ITEMS_DATA[data.type].icon}</div>
    <div class="item-label">${RARITIES[data.rarity].name}</div>
    <div class="item-value">${data.value}</div>
    <div class="item-bg bg-${data.rarity}"></div>
  `;
  return div;
}

async function loadState() {
  const res = await fetch('/api/cases/state', {
    headers: { 'X-Telegram-Init-Data': tg.initData }
  });
  const data = await res.json();
  if (data.ok) {
    balance = data.balance;
    document.getElementById('balance-val').innerText = balance.toFixed(2);
    document.getElementById('pity-info').innerText = `До гаранта Редкого+: ${data.pity}`;
    
    const selector = document.getElementById('case-selector');
    selector.innerHTML = '';
    data.cases.forEach(c => {
      const card = document.createElement('div');
      card.className = `case-card ${currentCase === c.id ? 'active' : ''}`;
      if (data.user_level < c.req_level) card.style.opacity = '0.5';
      card.innerHTML = `
        <div class="case-card-icon">${c.icon}</div>
        <div class="case-card-name">${c.name}</div>
        <div class="case-card-price">${c.price} 🪙</div>
      `;
      card.onclick = () => {
        if (isSpinning) return;
        if (data.user_level < c.req_level) {
          tg.showAlert('Требуется уровень ' + c.req_level);
          return;
        }
        currentCase = c.id;
        document.getElementById('case-name-top').innerText = c.name.toUpperCase();
        document.getElementById('open-price').innerText = c.price;
        loadState(); // refresh active class
      };
      selector.appendChild(card);
    });
  }
}

async function openCase() {
  if (isSpinning) return;
  
  btnOpen.disabled = true;
  
  const res = await fetch('/api/cases/open', {
    method: 'POST',
    headers: { 
      'X-Telegram-Init-Data': tg.initData,
      'Content-Type': 'application/json' 
    },
    body: JSON.stringify({ case_id: currentCase })
  });
  const data = await res.json();
  
  if (!data.ok) {
    tg.showAlert(data.error);
    btnOpen.disabled = false;
    return;
  }
  
  isSpinning = true;
  
  // Build track
  track.innerHTML = '';
  track.style.transition = 'none';
  track.style.transform = 'translateX(0)';
  
  const totalItems = 50;
  const winningIndex = 45;
  const items = data.sequence; // Array of items from server
  
  items.forEach((item, i) => {
    track.appendChild(createItemEl(item));
  });
  
  // Calculate offset to land on winningIndex
  const itemWidth = 120;
  const containerWidth = document.querySelector('.spinner-container').clientWidth;
  const centerOffset = containerWidth / 2;
  // Random jitter within the winning item
  const jitter = Math.floor(Math.random() * 80) - 40; 
  const finalX = - (winningIndex * itemWidth + itemWidth/2 - centerOffset + jitter);
  
  setTimeout(() => {
    track.style.transition = 'transform 7s cubic-bezier(0.1, 0, 0.1, 1)';
    track.style.transform = `translateX(${finalX}px)`;
    
    // Play sound logic (visual only for now)
  }, 50);
  
  setTimeout(() => {
    showWin(data.win);
    loadState();
    isSpinning = false;
    btnOpen.disabled = false;
  }, 7500);
}

function showWin(item) {
  document.getElementById('win-icon').innerText = ITEMS_DATA[item.type].icon;
  document.getElementById('win-name').innerText = item.value + (item.type === 'style' ? '' : ' монет');
  document.getElementById('win-name').className = `win-name rarity-${item.rarity}`;
  winOverlay.style.display = 'flex';
  tg.HapticFeedback.notificationOccurred('success');
}

function closeWin() {
  winOverlay.style.display = 'none';
}

btnOpen.onclick = openCase;

loadState();
</script>
</body>
</html>
"""

async def cases_page_handler(request: web.Request) -> web.Response:
    return web.Response(text=CASES_PAGE_HTML, content_type="text/html")


async def api_cases_state(request: web.Request) -> web.Response:
    telegram_user_id = _get_webapp_user_id(request)
    if not telegram_user_id:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

    from app.services import get_user  # lookup по telegram_id, а не по PK
    async with async_session() as session:
        user = await get_user(session, telegram_user_id)
        if not user:
            return web.json_response({"ok": False, "error": "user_not_found"}, status=404)
        
        from app.config import LOOTBOX_COIN_PRICE
        cases = [
            {"id": "common", "name": "Обычный", "icon": "🎁", "price": float(LOOTBOX_COIN_PRICE), "req_level": 1},
            {"id": "elite", "name": "Элитный", "icon": "💎", "price": 1000.0, "req_level": 10},
            {"id": "legendary", "name": "Легендарный", "icon": "🔥", "price": 5000.0, "req_level": 20},
            {"id": "styles", "name": "Кейс ников", "icon": "🎨", "price": 250.0, "req_level": 1},
        ]
        
        return web.json_response({
            "ok": True,
            "balance": float(user.balance),
            "pity": 10 - (user.lootbox_pity_counter or 0),
            "user_level": user.level,
            "cases": cases
        })

async def api_cases_open(request: web.Request) -> web.Response:
    telegram_user_id = _get_webapp_user_id(request)
    if not telegram_user_id:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    
    try:
        data = await request.json()
        case_id = data.get("case_id", "common")
    except Exception:
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)

    from app.services import get_user  # lookup по telegram_id, а не по PK
    async with async_session() as session:
        user = await get_user(session, telegram_user_id)
        if not user:
             return web.json_response({"ok": False, "error": "user_not_found"}, status=404)
        
        from app.services import open_lootbox_for_coins, open_styles_lootbox, _roll_lootbox_reward_coins
        
        win_item = None
        if case_id == "styles":
            # Styles case in Mini App uses no exclusions for simplicity or uses what's in state? 
            # For now, let's say it's basic opening
            reward, kind, price = await open_styles_lootbox(session, user.id, [])
            if reward is None:
                return web.json_response({"ok": False, "error": kind})
            
            if kind == "style":
                from app.nick_styles import style_label
                win_item = {"type": "style", "value": style_label(reward), "rarity": "epic"}
            else:
                win_item = {"type": "coins", "value": float(reward), "rarity": "common" if reward < 100 else "rare"}
        else:
            reward, rarity, pity_left = await open_lootbox_for_coins(session, user.id, case_id)
            if reward is None:
                return web.json_response({"ok": False, "error": rarity})
            win_item = {"type": "coins", "value": float(reward), "rarity": rarity}

        # Generate sequence for CS2 animation
        # Index 45 is our win
        sequence = []
        rarities_pool = ["common", "rare", "epic", "jackpot"]
        for i in range(50):
            if i == 45:
                sequence.append(win_item)
            else:
                # Random fake items
                if case_id == "styles":
                    fake_kind = random.choice(["style", "coins"])
                    if fake_kind == "style":
                        from app.nick_styles import STYLES
                        fake_style = STYLES[random.randint(1, len(STYLES))]
                        sequence.append({"type": "style", "value": fake_style.label, "rarity": "epic"})
                    else:
                        fake_val = random.randint(10, 250)
                        sequence.append({"type": "coins", "value": float(fake_val), "rarity": "common"})
                else:
                    fake_rarity = random.choices(rarities_pool, weights=[70, 25, 4, 1])[0]
                    fake_val = random.randint(10, 1000)
                    sequence.append({"type": "coins", "value": float(fake_val), "rarity": fake_rarity})

        return web.json_response({
            "ok": True,
            "win": win_item,
            "sequence": sequence,
            "balance": float(user.balance)
        })
# HTML5 Galaga-подобная аркада. Все исходы считает сервер (crash-модель):
# при старте забега разыгрывается скрытая crash-волна, клиент лишь играет
# и вызывает /api/arcade/wave — накрутить выигрыш невозможно.

ARCADE_PAGE_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no"/>
<title>Космическая Аркада</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{ --accent:#8b5cf6; --gold:#fbbf24; }
*{box-sizing:border-box; margin:0; padding:0; -webkit-tap-highlight-color:transparent;}
html,body{height:100%; overflow:hidden; background:#05010f; color:#fff;
  font-family:-apple-system,'Segoe UI',Roboto,sans-serif; user-select:none;}
#game{position:fixed; inset:0; width:100%; height:100%; display:block; touch-action:none;}
.hud{position:fixed; top:0; left:0; right:0; padding:10px 12px; display:flex; gap:6px;
  justify-content:space-between; z-index:5; pointer-events:none; font-size:13px; flex-wrap:wrap;}
.hud .chip{background:rgba(20,10,40,.78); border:1px solid rgba(139,92,246,.45);
  border-radius:12px; padding:5px 9px;}
.mult{color:var(--gold); font-weight:800; font-size:16px; display:inline-block;}
.mult.pulse{animation:pulse .35s ease;}
@keyframes pulse{0%{transform:scale(1)}50%{transform:scale(1.4)}100%{transform:scale(1)}}
#cashoutBtn{position:fixed; left:50%; bottom:16px; transform:translateX(-50%); z-index:6;
  background:linear-gradient(135deg,#f59e0b,#fbbf24); color:#1a0b00; border:none;
  border-radius:16px; padding:14px 34px; font-size:17px; font-weight:800;
  box-shadow:0 6px 24px rgba(251,191,36,.4);}
#cashoutBtn:active{transform:translateX(-50%) scale(.96);}
.screen{position:fixed; inset:0; z-index:10; display:flex; flex-direction:column;
  align-items:center; justify-content:center; gap:12px; padding:22px;
  background:rgba(5,1,15,.9); text-align:center; overflow-y:auto;}
.hidden{display:none !important;}
h1{font-size:26px; background:linear-gradient(90deg,#8b5cf6,#22d3ee);
  -webkit-background-clip:text; background-clip:text; color:transparent;}
.sub{font-size:14px; opacity:.85; line-height:1.5;}
.btn{background:rgba(139,92,246,.16); border:1px solid rgba(139,92,246,.5); color:#fff;
  border-radius:14px; padding:12px 26px; font-size:16px; width:100%; max-width:300px;}
.btn.primary{background:linear-gradient(135deg,#7c3aed,#8b5cf6); border:none; font-weight:700;}
.btn:active{transform:scale(.97);}
.chips{display:flex; gap:8px; flex-wrap:wrap; justify-content:center;}
.chip-bet{background:rgba(34,211,238,.12); border:1px solid rgba(34,211,238,.5); color:#fff;
  border-radius:12px; padding:10px 16px; font-size:15px; font-weight:600;}
.chip-bet.sel{background:#22d3ee; color:#04222b;}
input{background:rgba(255,255,255,.08); border:1px solid rgba(255,255,255,.25); color:#fff;
  border-radius:12px; padding:11px 14px; font-size:16px; width:100%; max-width:300px; text-align:center;}
.limits{font-size:12px; opacity:.6; max-width:320px;}
.top-list{font-size:13px; opacity:.9; line-height:1.7; margin-top:6px;
  background:rgba(255,255,255,.05); border-radius:12px; padding:10px 16px;}
#toast{position:fixed; top:64px; left:50%; transform:translateX(-50%); z-index:30;
  background:rgba(220,38,38,.94); padding:9px 18px; border-radius:12px; font-size:14px;
  display:none; max-width:86%; text-align:center;}
#ovText{white-space:pre-line; font-size:15px; line-height:1.55;}
</style>
</head>
<body>
<canvas id="game"></canvas>

<div class="hud hidden" id="hud">
  <div class="chip">💵 <b id="hudBet">0</b></div>
  <div class="chip">📈 <span class="mult" id="hudMult">x1</span></div>
  <div class="chip">💰 <b id="hudPotential">0</b></div>
  <div class="chip">👛 <b id="hudBalance">0</b></div>
</div>
<button id="cashoutBtn" class="hidden">💰 Забрать</button>

<div id="lobby" class="screen">
  <div style="font-size:46px">🚀</div>
  <h1>Космическая Аркада</h1>
  <div class="sub">Отбивай волны флота 👾 — каждая волна растит множитель ставки.<br/>
  Успей нажать «Забрать», пока флот не прорвался! ☠️</div>
  <div>👛 Баланс: <b id="lobbyBalance">—</b> монет</div>
  <div class="chips" id="betChips"></div>
  <input id="betInput" type="number" inputmode="decimal" placeholder="Своя ставка"/>
  <div class="limits" id="limitsLine"></div>
  <button class="btn hidden" id="resumeBtn">▶️ Продолжить забег</button>
  <button class="btn primary" id="startBtn">🚀 В бой!</button>
  <div class="top-list hidden" id="topList"></div>
</div>

<div id="overlay" class="screen hidden">
  <div id="ovEmoji" style="font-size:58px">🏆</div>
  <h1 id="ovTitle" style="font-size:24px">Победа!</h1>
  <div id="ovText" class="sub"></div>
  <button class="btn primary" id="againBtn">🔁 Ещё раз</button>
  <button class="btn" id="toLobbyBtn">✏️ Сменить ставку</button>
</div>

<div id="toast"></div>

<script>
'use strict';
var tg = window.Telegram && window.Telegram.WebApp;
if (tg) { try { tg.ready(); tg.expand(); } catch (e) {} }
var initData = tg ? (tg.initData || '') : '';
function $(id){ return document.getElementById(id); }

var CFG = { min_bet:10, max_bet:250, max_multiplier:50, daily_profit_cap:500, enabled:true };
var balance = 0, bet = 0, runId = null, mult = 1, wave = 0;
var phase = 'lobby';            // lobby | playing | dying | over
var waitingServer = false;
var resumeRun = null;

function haptic(kind){
  try {
    if (!tg || !tg.HapticFeedback) return;
    if (kind==='success') tg.HapticFeedback.notificationOccurred('success');
    else if (kind==='error') tg.HapticFeedback.notificationOccurred('error');
    else tg.HapticFeedback.impactOccurred(kind==='heavy'?'heavy':'light');
  } catch(e){}
}
async function api(path, body){
  var opts = { headers: { 'X-Telegram-Init-Data': initData } };
  if (body !== undefined) {
    opts.method = 'POST';
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body || {});
  }
  var res = await fetch(path, opts);
  var data = {};
  try { data = await res.json(); } catch(e){}
  if (!res.ok || !data.ok) {
    var err = new Error((data && data.error) || ('http_' + res.status));
    err.data = data; throw err;
  }
  return data;
}
function toast(msg){
  var t = $('toast'); t.textContent = msg; t.style.display = 'block';
  clearTimeout(t._h); t._h = setTimeout(function(){ t.style.display='none'; }, 3000);
}
function fmt(v){
  v = Math.floor((+v) * 100) / 100;
  var s = v.toFixed(2).replace(/0+$/,'').replace(/\.$/,'');
  return s === '-0' ? '0' : s;
}
function errText(c){
  return { no_funds:'Не хватает монет 😢', bad_bet:'Ставка вне лимитов',
    disabled:'Аркада временно отключена', run_in_progress:'У тебя уже идёт забег',
    no_waves:'Сначала отбей хотя бы одну волну!', not_active:'Забег уже завершён' }[c] || ('Ошибка: ' + c);
}

/* ---------- HUD ---------- */
function updHud(){
  $('hudBet').textContent = fmt(bet);
  $('hudMult').textContent = 'x' + fmt(mult);
  $('hudPotential').textContent = fmt(bet * mult);
  $('hudBalance').textContent = fmt(balance);
}
function pulseMult(){
  var m = $('hudMult'); m.classList.remove('pulse'); void m.offsetWidth; m.classList.add('pulse');
}
function refreshCashoutBtn(){
  var b = $('cashoutBtn');
  if (phase==='playing' && wave >= 1) {
    b.classList.remove('hidden');
    b.textContent = '💰 Забрать ' + fmt(bet * mult);
  } else b.classList.add('hidden');
}

/* ---------- CANVAS ---------- */
var cv = $('game'), ctx = cv.getContext('2d');
var W = 0, H = 0;
function resize(){
  var dpr = Math.min(window.devicePixelRatio || 1, 2);
  W = cv.clientWidth; H = cv.clientHeight;
  cv.width = W * dpr; cv.height = H * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
window.addEventListener('resize', resize);

var stars = [], bullets = [], aliens = [], aBullets = [], parts = [];
var player = { x: 0, tx: 0, cd: 0 };
var formationY = 0, waveFlash = 0, ts0 = 0;

function initStars(){
  stars = [];
  for (var i = 0; i < 90; i++)
    stars.push({ x: Math.random(), y: Math.random(), s: Math.random()*1.6+0.4, v: Math.random()*0.03+0.008 });
}
initStars();

function spawnWave(w){
  aliens = []; aBullets = []; bullets = [];
  var cols = Math.min(4 + (w % 3), 7);
  var rows = Math.min(2 + Math.floor(w / 2), 5);
  var gap = Math.min(48, (W - 48) / cols);
  var startX = W/2 - (cols-1)*gap/2;
  var types = ['👾','🛸','👽'];
  for (var r = 0; r < rows; r++)
    for (var c = 0; c < cols; c++)
      aliens.push({ x0: startX + c*gap, y0: 78 + r*40, sx: startX + c*gap, sy: 78 + r*40,
                    alive: true, t: types[(r+c+w) % 3], ph: Math.random()*6.28 });
  formationY = 0;
}
function alienSpeed(){ return 5 + wave * 1.3; }

function setTarget(clientX){
  var rect = cv.getBoundingClientRect();
  player.tx = Math.max(18, Math.min(W - 18, clientX - rect.left));
}
var pointerActive = false;
cv.addEventListener('pointerdown', function(e){ pointerActive = true; setTarget(e.clientX); });
cv.addEventListener('pointermove', function(e){ if (pointerActive) setTarget(e.clientX); });
window.addEventListener('pointerup', function(){ pointerActive = false; });
window.addEventListener('keydown', function(e){
  if (phase !== 'playing') return;
  if (e.key === 'ArrowLeft')  player.tx = Math.max(18, player.tx - 36);
  if (e.key === 'ArrowRight') player.tx = Math.min(W - 18, player.tx + 36);
});

function boom(x, y){
  var cols = ['#fbbf24','#f87171','#8b5cf6','#ffffff'];
  for (var i = 0; i < 10; i++)
    parts.push({ x:x, y:y, vx:(Math.random()-0.5)*170, vy:(Math.random()-0.5)*170,
                 life: 0.5 + Math.random()*0.3, c: cols[i % 4] });
}

function frame(ts){
  var dt = Math.min((ts - ts0)/1000 || 0, 0.05); ts0 = ts;

  var g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, '#0b0322'); g.addColorStop(1, '#05010f');
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);

  ctx.fillStyle = '#c4b5fd';
  for (var i = 0; i < stars.length; i++){
    var s = stars[i]; s.y += s.v * dt; if (s.y > 1) s.y -= 1;
    ctx.globalAlpha = 0.3 + s.s*0.3;
    ctx.fillRect(s.x*W, s.y*H, s.s, s.s);
  }
  ctx.globalAlpha = 1;

  if (phase === 'playing' || phase === 'dying') {
    var moving = (phase === 'dying') || (phase === 'playing' && !waitingServer);
    if (moving) formationY += alienSpeed() * dt;
    var sway = Math.sin(ts/700) * 10;

    ctx.font = '26px serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    var aliveCount = 0;
    for (var j = 0; j < aliens.length; j++){
      var a = aliens[j];
      if (!a.alive) continue;
      aliveCount++;
      a.sx = a.x0 + sway + Math.sin(ts/500 + a.ph)*4;
      a.sy = a.y0 + formationY;
      ctx.fillText(a.t, a.sx, a.sy);
      if (phase === 'playing' && !waitingServer && Math.random() < dt * 0.10)
        aBullets.push({ x: a.sx, y: a.sy + 14, vy: 150 + wave*14 });
    }

    // Флот дошёл до линии игрока → сервер решает исход волны.
    if (phase === 'playing' && !waitingServer && aliveCount > 0 && formationY > H - 200)
      onWaveCleared();

    // Игрок
    player.x += (player.tx - player.x) * Math.min(dt*14, 1);
    ctx.font = '30px serif';
    ctx.fillText('🚀', player.x, H - 66);
    ctx.fillStyle = 'rgba(251,191,36,.85)';
    ctx.fillRect(player.x - 2, H - 50, 4, 8 + Math.random()*7);

    // Автострельба
    if (phase === 'playing' && !waitingServer && aliveCount > 0) {
      player.cd -= dt;
      if (player.cd <= 0) { player.cd = 0.18; bullets.push({ x: player.x, y: H - 84, vy: -440 }); }
    }

    ctx.fillStyle = '#22d3ee';
    for (var b1 = bullets.length - 1; b1 >= 0; b1--){
      var b = bullets[b1]; b.y += b.vy * dt;
      ctx.fillRect(b.x - 2, b.y - 9, 4, 11);
      if (b.y < -20) bullets.splice(b1, 1);
    }
    // Столкновения
    for (var k = 0; k < bullets.length; k++){
      var bl = bullets[k];
      for (var m = 0; m < aliens.length; m++){
        var al = aliens[m];
        if (!al.alive) continue;
        if (Math.abs(bl.x - al.sx) < 17 && Math.abs(bl.y - al.sy) < 17) {
          al.alive = false; bl.y = -100; boom(al.sx, al.sy); haptic('light');
          break;
        }
      }
    }
    if (phase === 'playing' && !waitingServer && aliens.length && aliens.every(function(x){ return !x.alive; }))
      onWaveCleared();

    // Декоративные снаряды пришельцев (исход решает сервер, они не убивают)
    ctx.fillStyle = '#f87171';
    for (var q = aBullets.length - 1; q >= 0; q--){
      var ab = aBullets[q]; ab.y += ab.vy * dt;
      ctx.fillRect(ab.x - 2, ab.y, 4, 8);
      if (ab.y > H + 20) aBullets.splice(q, 1);
    }
    // Частицы
    for (var p = parts.length - 1; p >= 0; p--){
      var pt = parts[p]; pt.x += pt.vx*dt; pt.y += pt.vy*dt; pt.life -= dt;
      ctx.globalAlpha = Math.max(pt.life*1.6, 0); ctx.fillStyle = pt.c;
      ctx.fillRect(pt.x-2, pt.y-2, 4, 4);
      if (pt.life <= 0) parts.splice(p, 1);
    }
    ctx.globalAlpha = 1;

    if (waveFlash > 0) {
      waveFlash -= dt;
      ctx.globalAlpha = Math.min(waveFlash, 1);
      ctx.fillStyle = '#fbbf24'; ctx.font = 'bold 21px sans-serif';
      ctx.fillText('ВОЛНА ' + wave + ' ОТБИТА! 💥', W/2, H/2 - 60);
      ctx.globalAlpha = 1;
    }
  }
  requestAnimationFrame(frame);
}

/* ---------- СЕТЬ ---------- */
function onWaveCleared(){
  if (waitingServer || phase !== 'playing') return;
  waitingServer = true;
  api('/api/arcade/wave', { run_id: runId }).then(function(r){
    balance = r.balance;
    if (r.outcome === 'hit') {
      wave = r.wave; mult = r.multiplier;
      pulseMult(); updHud(); refreshCashoutBtn();
      waveFlash = 1.1; spawnWave(wave); waitingServer = false;
      haptic('light');
    } else if (r.outcome === 'lost') {
      waitingServer = false; onDefeat();
    } else if (r.outcome === 'cashed_out') {
      waitingServer = false; onWin(r.payout, r.multiplier, true, r.cap_applied);
    } else {
      waitingServer = false; toLobby('Сервер отменил забег');
    }
  }).catch(function(e){ waitingServer = false; toLobby(errText(e.message)); });
}

function onDefeat(){
  phase = 'dying'; haptic('error');
  aliens = [];
  for (var i = 0; i < 9; i++)
    aliens.push({ x0: 26 + (W-52)*i/9, y0: -30 - Math.random()*80, sx:0, sy:0,
                  alive: true, t: (i%2) ? '☄️' : '👹', ph: i });
  formationY = 0;
  boom(player.x, H - 66); boom(player.x, H - 66);
  setTimeout(function(){
    phase = 'over';
    showOverlay('☠️', 'Прорыв флота!',
      'Инопланетяне прорвались на волне ' + (wave + 1) + '.\\nСтавка ' + fmt(bet) + ' монет сгорела.');
  }, 1150);
}

function onWin(payout, multiplier, capped, capApplied){
  phase = 'over'; haptic('success');
  var txt = 'Ставка ' + fmt(bet) + ' × x' + fmt(multiplier) + ' = ' + fmt(payout) + ' монет зачислено!';
  if (capped) txt = '🌟 Множитель достиг потолка x' + fmt(CFG.max_multiplier) + '!\\n' + txt;
  if (capApplied) txt += '\\n🛡 Часть прибыли срезана дневным лимитом.';
  showOverlay(capped ? '🌟' : '🏆', capped ? 'Сверхновая!' : 'Выигрыш забран!', txt);
}

function showOverlay(emoji, title, text){
  $('ovEmoji').textContent = emoji;
  $('ovTitle').textContent = title;
  $('ovText').textContent = text;
  $('overlay').classList.remove('hidden');
  $('hud').classList.add('hidden');
  $('cashoutBtn').classList.add('hidden');
}

/* ---------- ЛОББИ ---------- */
function buildChips(){
  var box = $('betChips'); box.innerHTML = '';
  [10, 25, 50, 100].forEach(function(v){
    if (v < CFG.min_bet || v > CFG.max_bet) return;
    var b = document.createElement('button');
    b.className = 'chip-bet'; b.textContent = v + ' 💵';
    if (v === bet) b.classList.add('sel');
    b.onclick = function(){
      bet = v; $('betInput').value = '';
      document.querySelectorAll('.chip-bet').forEach(function(x){ x.classList.remove('sel'); });
      b.classList.add('sel');
    };
    box.appendChild(b);
  });
  if (!bet || bet < CFG.min_bet || bet > CFG.max_bet) bet = CFG.min_bet;
}

function refreshTop(){
  api('/api/arcade/top').then(function(t){
    var el = $('topList');
    if (!t.rows || !t.rows.length) { el.classList.add('hidden'); return; }
    var medals = ['🥇','🥈','🥉'];
    el.classList.remove('hidden');
    el.innerHTML = '<b>🏆 Топ недели</b><br/>' + t.rows.slice(0,5).map(function(r, i){
      return (medals[i] || (i+1) + '.') + ' ' + r.name + ' — +' + fmt(r.net);
    }).join('<br/>');
  }).catch(function(){});
}

function refreshState(){
  api('/api/arcade/state').then(function(s){
    CFG.enabled = s.enabled; CFG.min_bet = s.min_bet; CFG.max_bet = s.max_bet;
    CFG.max_multiplier = s.max_multiplier; CFG.daily_profit_cap = s.daily_profit_cap;
    balance = s.balance;
    $('lobbyBalance').textContent = fmt(balance);
    $('limitsLine').textContent = 'Ставка от ' + fmt(CFG.min_bet) + ' до ' + fmt(CFG.max_bet) +
      ' монет · макс. x' + fmt(CFG.max_multiplier) +
      ' · кап прибыли ' + fmt(CFG.daily_profit_cap) + '/день';
    resumeRun = s.active_run;
    if (resumeRun) {
      bet = resumeRun.bet;
      $('resumeBtn').classList.remove('hidden');
      $('resumeBtn').textContent = '▶️ Продолжить (ставка ' + fmt(resumeRun.bet) +
        ', x' + fmt(resumeRun.multiplier) + ')';
    } else {
      $('resumeBtn').classList.add('hidden');
      buildChips();
    }
    if (!CFG.enabled) toast('Аркада временно отключена');
  }).catch(function(e){ toast('Нет связи с сервером: ' + e.message); });
  refreshTop();
}

function enterGame(){
  phase = 'playing'; waitingServer = false;
  $('lobby').classList.add('hidden');
  $('overlay').classList.add('hidden');
  $('hud').classList.remove('hidden');
  player.x = W/2; player.tx = W/2;
  spawnWave(wave);
  updHud(); refreshCashoutBtn();
}

function startRun(newBet){
  api('/api/arcade/start', { bet: newBet }).then(function(r){
    balance = r.balance; runId = r.run.run_id; bet = r.run.bet;
    mult = r.run.multiplier; wave = r.run.wave;
    enterGame();
  }).catch(function(e){ toast(errText(e.message)); });
}

function toLobby(msg){
  phase = 'lobby';
  if (msg) toast(msg);
  $('hud').classList.add('hidden');
  $('cashoutBtn').classList.add('hidden');
  $('overlay').classList.add('hidden');
  $('lobby').classList.remove('hidden');
  refreshState();
}

/* ---------- КНОПКИ ---------- */
$('startBtn').onclick = function(){
  if (!CFG.enabled) { toast('Аркада временно отключена'); return; }
  var v = $('betInput').value ? parseFloat($('betInput').value) : bet;
  if (!(v > 0)) { toast('Введи ставку'); return; }
  startRun(v);
};
$('resumeBtn').onclick = function(){
  if (!resumeRun) return;
  runId = resumeRun.run_id; bet = resumeRun.bet;
  mult = resumeRun.multiplier; wave = resumeRun.wave;
  enterGame();
};
$('cashoutBtn').onclick = function(){
  if (phase !== 'playing' || waitingServer || wave < 1) return;
  waitingServer = true;
  api('/api/arcade/cashout', { run_id: runId }).then(function(r){
    balance = r.balance; waitingServer = false;
    onWin(r.payout, r.multiplier, false, r.cap_applied);
  }).catch(function(e){ waitingServer = false; toast(errText(e.message)); });
};
$('againBtn').onclick = function(){ $('overlay').classList.add('hidden'); startRun(bet); };
$('toLobbyBtn').onclick = function(){ $('overlay').classList.add('hidden'); toLobby(); };
$('betInput').addEventListener('input', function(){
  document.querySelectorAll('.chip-bet').forEach(function(x){ x.classList.remove('sel'); });
});

resize();
requestAnimationFrame(frame);
refreshState();
</script>
</body>
</html>
"""


async def arcade_page_handler(request: web.Request) -> web.Response:
    return web.Response(text=ARCADE_PAGE_HTML, content_type="text/html")


def _arcade_run_public(run) -> dict:
    from app.arcade import payout_for as _af_payout_for
    return {
        "run_id": run.id,
        "bet": float(run.bet),
        "wave": int(run.wave),
        "multiplier": float(run.multiplier),
        "payout": float(_af_payout_for(run.bet, run.multiplier)),
    }


async def api_arcade_state(request: web.Request) -> web.Response:
    telegram_user_id = _get_webapp_user_id(request)
    if not telegram_user_id:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    try:
        from app.arcade import expire_stale_runs, get_active_run, load_arcade_config
        from app.db import async_session
        from app.services import get_user
        async with async_session() as session:
            cfg = await load_arcade_config(session)
            user = await get_user(session, telegram_user_id)
            if not user:
                return web.json_response({"ok": False, "error": "user_not_found"}, status=404)
            active_run = None
            if cfg.enabled:
                await expire_stale_runs(session, user.id, cfg)
                run = await get_active_run(session, user.id)
                if run:
                    active_run = _arcade_run_public(run)
            return web.json_response({
                "ok": True,
                "enabled": cfg.enabled,
                "balance": float(user.balance),
                "min_bet": float(cfg.min_bet),
                "max_bet": float(cfg.max_bet),
                "max_multiplier": float(cfg.max_multiplier),
                "daily_profit_cap": float(cfg.daily_profit_cap),
                "active_run": active_run,
                "name": user.display_name or user.first_name or "Игрок",
            })
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def api_arcade_start(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        data = {}
    telegram_user_id = _get_webapp_user_id(request, data)
    if not telegram_user_id:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    try:
        from decimal import Decimal as _Dec
        bet = _Dec(str(data.get("bet", "0")))
    except Exception:
        return web.json_response({"ok": False, "error": "bad_bet"}, status=400)
    try:
        from app.arcade import load_arcade_config, start_run
        from app.db import async_session
        from app.services import get_user
        async with async_session() as session:
            cfg = await load_arcade_config(session)
            user = await get_user(session, telegram_user_id)
            if not user:
                return web.json_response({"ok": False, "error": "user_not_found"}, status=404)
            run, err = await start_run(session, user, bet, cfg)
            if err:
                status = 402 if err == "no_funds" else 400
                return web.json_response({"ok": False, "error": err}, status=status)
            await session.refresh(user)
            return web.json_response({
                "ok": True,
                "run": _arcade_run_public(run),
                "balance": float(user.balance),
            })
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def _arcade_load_owned_run(session, telegram_user_id: int, run_id: int):
    """
    Возвращает (user, run, error_response).
    ВАЖНО: ошибку проверять через `is not None` — aiohttp Response falsy!
    """
    from app.models import ArcadeRun
    from app.services import get_user
    user = await get_user(session, telegram_user_id)
    if not user:
        return None, None, web.json_response({"ok": False, "error": "user_not_found"}, status=404)
    run = await session.get(ArcadeRun, run_id)
    if not run or run.user_id != user.id:
        return None, None, web.json_response({"ok": False, "error": "not_found"}, status=404)
    return user, run, None


async def api_arcade_wave(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        data = {}
    telegram_user_id = _get_webapp_user_id(request, data)
    if not telegram_user_id:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    try:
        run_id = int(data.get("run_id", 0))
    except (TypeError, ValueError):
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)
    try:
        from app.arcade import advance_wave, load_arcade_config
        from app.db import async_session
        async with async_session() as session:
            cfg = await load_arcade_config(session)
            user, run, err = await _arcade_load_owned_run(session, telegram_user_id, run_id)
            if err is not None:
                return err
            if run.status != "active":
                return web.json_response(
                    {"ok": False, "error": "not_active", "status": run.status}, status=409
                )
            result = await advance_wave(session, run, cfg)
            await session.refresh(user)

        outcome = result.get("outcome")
        if outcome == "stale":
            return web.json_response({"ok": False, "error": "stale"}, status=409)
        resp = {"ok": True, "outcome": outcome, "balance": float(user.balance)}
        for key in ("wave", "next_chance"):
            if key in result:
                resp[key] = int(result[key])
        if "multiplier" in result:
            resp["multiplier"] = float(result["multiplier"])
        for key in ("payout", "profit"):
            if key in result:
                resp[key] = float(result[key])
        if "cap_applied" in result:
            resp["cap_applied"] = bool(result["cap_applied"])
        if result.get("capped"):
            resp["capped"] = True
        return web.json_response(resp)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def api_arcade_cashout(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        data = {}
    telegram_user_id = _get_webapp_user_id(request, data)
    if not telegram_user_id:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    try:
        run_id = int(data.get("run_id", 0))
    except (TypeError, ValueError):
        return web.json_response({"ok": False, "error": "bad_request"}, status=400)
    try:
        from app.arcade import cashout_run, load_arcade_config
        from app.db import async_session
        async with async_session() as session:
            cfg = await load_arcade_config(session)
            user, run, err = await _arcade_load_owned_run(session, telegram_user_id, run_id)
            if err is not None:
                return err
            result = await cashout_run(session, run, cfg)
            if not result.get("ok"):
                status = 409 if result.get("error") in ("stale", "not_active") else 400
                return web.json_response(
                    {"ok": False, "error": result.get("error", "cashout_failed")}, status=status
                )
            await session.refresh(user)
            return web.json_response({
                "ok": True,
                "payout": float(result["payout"]),
                "profit": float(result["profit"]),
                "multiplier": float(result["multiplier"]),
                "wave": int(result["wave"]),
                "cap_applied": bool(result["cap_applied"]),
                "balance": float(user.balance),
            })
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def api_arcade_top(request: web.Request) -> web.Response:
    try:
        from datetime import timedelta as _td
        from sqlalchemy import func as _func, select as _select
        from app.arcade import GAME_TYPE as _ARC_GT
        from app.db import async_session
        from app.models import GameHistory, User, utc_now as _arc_utc_now
        week_ago = _arc_utc_now() - _td(days=7)
        async with async_session() as session:
            rows = (await session.execute(
                _select(
                    User.display_name,
                    _func.sum(GameHistory.result).label("net"),
                    _func.count(GameHistory.id).label("games"),
                )
                .join(User, User.id == GameHistory.user_id)
                .where(
                    GameHistory.game_type == _ARC_GT,
                    GameHistory.created_at >= week_ago,
                )
                .group_by(GameHistory.user_id, User.display_name)
                .having(_func.sum(GameHistory.result) > 0)
                .order_by(_func.sum(GameHistory.result).desc())
                .limit(10)
            )).all()
        return web.json_response({
            "ok": True,
            "rows": [
                {"name": name or "Игрок", "net": float(net), "games": int(games)}
                for (name, net, games) in rows
            ],
        })
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is empty")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    from app.middlewares import BanCheckMiddleware
    dp.message.middleware(BanCheckMiddleware())
    dp.callback_query.middleware(BanCheckMiddleware())
    dp.include_router(admin_router)
    dp.include_router(user_router)
    dp.include_router(arcade_router)
    dp.include_router(user_offer_router)
    dp.include_router(donation_router)
    dp.include_router(ai_router)

    # global error handler
    from aiogram.types import ErrorEvent
    import time as _time
    from app.db import is_db_unavailable_error, is_db_quota_error
    quota_err_state = {"last": 0.0, "count": 0}

    @dp.error()
    async def error_handler(event: ErrorEvent):
        from app.logger import log_exception, log_warning, get_logger
        lg = get_logger("dp_error")
        exc = event.exception
        if is_db_unavailable_error(exc):
            # БД недоступна (в т.ч. исчерпана compute-квота Neon).
            # Не сыпем в лог трейсбеки по 5 КБ на каждый апдейт —
            # одна короткая строка раз в минуту со счётчиком пропущенных.
            quota_err_state["count"] += 1
            now = _time.monotonic()
            if now - quota_err_state["last"] >= 60:
                quota_err_state["last"] = now
                if is_db_quota_error(exc):
                    hint = (
                        "исчерпана compute-квота Neon: дождитесь её сброса "
                        "в начале месяца, обновите тариф или смените БД"
                    )
                else:
                    hint = "БД временно недоступна (проблема соединения)"
                log_warning(
                    lg,
                    f"dp_error: {hint}. "
                    f"Подавлено повторов за минуту: {quota_err_state['count']}",
                )
            return True
        log_exception(lg, f"dp_error: {exc}")
        return True

    app = web.Application()
    app['bot'] = bot
    app.on_startup.append(on_startup)
    app.router.add_get("/", handle_health_check)
    app.router.add_get("/videofeed", videofeed_page_handler)
    app.router.add_get("/api/videofeed/feed", api_videofeed_feed)
    app.router.add_get("/api/video/{id}", api_video_stream)
    app.router.add_get("/lottery/state", lottery_state_handler)
    app.router.add_post("/lottery/draw-next", lottery_draw_next_handler)
    app.router.add_get("/lottery/live", lottery_live_page_handler)
    
    app.router.add_get("/api/user/balance", api_user_balance)
    app.router.add_post("/api/user/timezone", api_user_timezone)
    app.router.add_post("/api/lottery/buy", api_lottery_buy)
    app.router.add_post("/api/lottery/buy-coins", api_lottery_buy_coins)
    app.router.add_get("/api/lottery/offers", api_lottery_offers)
    app.router.add_post("/api/lottery/place-bet", api_lottery_place_bet)

    # 🚀 Космическая аркада (Mini App)
    app.router.add_get("/arcade", arcade_page_handler)
    app.router.add_get("/api/arcade/state", api_arcade_state)
    app.router.add_post("/api/arcade/start", api_arcade_start)
    app.router.add_post("/api/arcade/wave", api_arcade_wave)
    app.router.add_post("/api/arcade/cashout", api_arcade_cashout)
    app.router.add_get("/api/arcade/top", api_arcade_top)

    # 🎁 Кейсы (Mini App)
    app.router.add_get("/cases", cases_page_handler)
    app.router.add_get("/api/cases/state", api_cases_state)
    app.router.add_post("/api/cases/open", api_cases_open)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(PORT or 10000))
    await site.start()

    stop_event = asyncio.Event()
    audit_task = None
    lottery_task = None
    retention_task = None
    promo_task = None
    cache_task = None
    mod_notifications_task = None
    auto_broadcast_task = None

    try:
        log_info(logger, "Polling started")

        mod_notifications_task = asyncio.create_task(_mod_notification_loop(bot))
        auto_broadcast_task = asyncio.create_task(auto_broadcast_worker(bot))

        if ENABLE_SUBSCRIPTION_AUDIT:
            audit_task = asyncio.create_task(subscription_audit_worker(bot, stop_event))
            log_info(logger, "Subscription audit worker enabled")

        retention_task = asyncio.create_task(retention_worker(bot, stop_event))
        promo_task = asyncio.create_task(weekly_promo_worker(bot, stop_event))

        if ENABLE_LOTTERY:
            lottery_task = asyncio.create_task(lottery_worker(bot, stop_event))
            log_info(logger, "Lottery worker enabled")

        cache_task = asyncio.create_task(video_cache_cleanup_worker(stop_event))
        log_info(logger, "Video cache cleanup worker enabled")

        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        stop_event.set()
        await _cancel_task(audit_task)
        await _cancel_task(lottery_task)
        await _cancel_task(cache_task)
        await _cancel_task(retention_task)
        await _cancel_task(promo_task)
        await _cancel_task(mod_notifications_task)
        await _cancel_task(auto_broadcast_task)
        await runner.cleanup()
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
