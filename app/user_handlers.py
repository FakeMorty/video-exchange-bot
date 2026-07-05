from html import escape
import uuid
import random
import math
import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from collections import defaultdict

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    LabeledPrice, PreCheckoutQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from sqlalchemy import select, func, desc


def is_any_admin(telegram_id: int, user_obj=None) -> bool:

    if telegram_id in ADMINS:

        return True

    if user_obj and getattr(user_obj, "is_admin", False):

        return True

    return False


from app.config import (
    ADMINS, WATCH_COST, UPLOAD_REWARD, PHOTO_UPLOAD_REWARD, STARS_PACKAGES, STARS_TO_COINS_RATE,
    ENABLE_ADMIN_FREE,
    XP_PER_WATCH, XP_PER_UPLOAD, XP_PER_RATING,
    XP_PER_COMMENT, XP_PER_REACTION, XP_PER_GAME,
    VIP_PRICE_STARS, VIP_DURATION_DAYS, VIP_BONUS_MULTIPLIER,
    LEVEL_XP_BASE, LEVEL_XP_MULTIPLIER,
    DAILY_QUESTS, PREMIUM_DAILY_QUESTS,
    COMMENTS_PER_10_MIN,
    NICKNAME_CHANGE_COST, NICKNAME_MIN_LENGTH, NICKNAME_MAX_LENGTH,
    OFFER_MIN_RENT_DAYS, OFFER_MAX_RENT_DAYS,
    REFERRAL_REWARD_INVITER, REFERRAL_REWARD_NEW_USER, DAILY_PHOTO_LIMIT,
    PROMOCODE_CREATION_STAR_RATE,
    PROMOCODE_MAX_AMOUNT, PROMOCODE_MAX_USES, PROMOCODE_MAX_HOURS,
    VIP_FREE_PROMO_PER_MONTH,
    DYNAMIC_STAR_DISCOUNT_ENABLED,
    DYNAMIC_STAR_DISCOUNT_HOURS,
    DYNAMIC_STAR_DISCOUNT_MULTIPLIER,
    FIRST_PURCHASE_DAILY_BONUS,
    ENABLE_PROMOCODES,
    OFFER_ACTION_COOLDOWN_SECONDS,
    PROMO_ACTIVATE_COOLDOWN_SECONDS,
    GUESS_JACKPOT_CHANCE, GUESS_JACKPOT_MULTIPLIER,
    ENABLE_LOTTERY,
    WEBHOOK_BASE,
    ENABLE_LOOTBOXES, LOOTBOX_COIN_PRICE, LOOTBOX_STAR_PRICE,
)
from app.db import async_session
from app.models import (
    User, Video, VideoView, Comment, ContentReaction,
    DailyQuestProgress, GameHistory, Offer, Promocode,
    LootboxOpen, LotteryTicket, UserActionLog,
    utc_now,
)
from app.services import (
    get_or_create_user, get_user, get_user_by_id, get_setting, save_video, save_photo,
    get_xp_multiplier, get_coin_multiplier, get_stars_discount,
    get_random_video_for_user, get_random_photo_for_user,
    record_view_and_charge_with_cost, refund_watch_and_unview, mark_content_broken,
    record_photo_view,
    rate_video, count_referrals,
    create_payment, create_custom_payment, apply_successful_payment,
    ensure_payment_pending, mark_payment_paid_once,
    get_payment_by_payload,
    get_active_offers, get_rentable_offers, get_offer_by_id,
    start_offer_participation, verify_offer_subscription,
    create_offer_rental, get_user_rentals,
    change_balance_atomic, log_user_action, to_decimal,
    set_display_name, get_display_name, get_styled_display_name, log_balance_change,
    can_play_free_game, pay_for_game_session, increment_game_played,
    get_or_create_game_session,
    check_daily_photo_limit,
    create_promocode, activate_promocode,
    calculate_promocode_star_cost,
    create_feedback, process_referral_reward,
    ensure_current_lottery_round, buy_lottery_ticket,
    get_latest_lottery_round, get_user_lottery_tickets, get_lottery_state_dict,
    is_admin_or_super, is_admin_free_eligible,
    should_show_low_balance_hint, mark_low_balance_hint_shown,
    can_show_offer_to_user, mark_offer_shown,
    get_random_active_offer, open_lootbox_for_stars,
    get_current_prices, get_active_events,
    should_show_ad_after_video, increment_video_watched, reset_ad_counter,
    create_video_report, schedule_mod_notification, REPORT_REASONS,
)
from app.selfcheck import run_selfcheck, format_selfcheck_report
from app.keyboards import (
    main_menu,
    video_rating_keyboard, photo_actions_keyboard,
    watch_choice_keyboard, buy_coins_keyboard, vip_buy_keyboard,
    offers_list_keyboard, rent_days_keyboard,
    games_menu_keyboard, tops_menu_keyboard,
    quests_keyboard, reaction_menu_keyboard,
    low_balance_offer_keyboard, BTN_WATCH, BTN_UPLOAD, BTN_PROFILE, BTN_BUY,
    BTN_OFFERS, BTN_REFERRALS, BTN_BONUS, BTN_ADMIN,
    BTN_GAMES, BTN_TOPS, BTN_QUESTS, BTN_VIP, BTN_LEVEL,
    BTN_PROMO, BTN_FEEDBACK, BTN_LOTTERY, BTN_FAQ, BTN_AI,
)
from app.logger import get_logger
from app.utils.messaging import format_time_for_user

logger = get_logger(__name__)
router = Router()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Глобально сбрасывает любой FSM-сценарий.

    Хендлер зарегистрирован в user_router раньше state-specific обработчиков,
    поэтому /cancel не застревает внутри меню/чата Кати или других сценариев.
    """
    await state.clear()
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        admin_flag = is_admin_or_super(message.from_user.id, user) if user else False
    await message.answer(
        "✅ Режим сброшен. Нажми /start или выбери действие в меню.",
        reply_markup=main_menu(is_admin=admin_flag),
    )


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext):
    if not message.from_user:
        return
    await state.clear()
    args = (command.args or "").strip()

    if args.startswith("promo_"):
        promo_code = args.replace("promo_", "")
        async with async_session() as session:
            user, is_new = await get_or_create_user(
                session, message.from_user.id,
                message.from_user.username,
                message.from_user.first_name,
                message.from_user.last_name,
            )
            if user.status == "banned":
                await message.answer("🚫 Вы заблокированы в боте.")
                return
            result = await activate_promocode(session, user.id, promo_code)
            await message.answer(result)
            if not user.agreed_to_rules:
                from app.keyboards import rules_keyboard
                await message.answer(
                    "📋 <b>Правила бота</b>\n\n"
                    "1. Нельзя публиковать запрещённый или шок-контент.\n"
                    "2. Нельзя использовать баги и накручивать награды.\n"
                    "3. Уважайте других пользователей и соблюдайте правила Telegram.\n\n"
                    "Нажмите кнопку ниже, чтобы принять правила.",
                    parse_mode="HTML",
                    reply_markup=rules_keyboard()
                )
                return
            admin_flag = is_any_admin(message.from_user.id, user)
            vip_str = " 👑" if is_vip(user) else ""
            styled_name = await get_styled_display_name(session, user)
            await message.answer(
                f"👋 Привет, <b>{styled_name}</b>{vip_str}!\n"
                f"💰 Баланс: <b>{user.balance}</b> монет",
                parse_mode="HTML",
                reply_markup=main_menu(is_admin=admin_flag)
            )
            return

    referral_code = args if args else None
    async with async_session() as session:
        user, is_new = await get_or_create_user(
            session,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            message.from_user.last_name,
            referral_code,
        )
        if user.status == "banned":
            await message.answer("🚫 Вы заблокированы в боте.")
            return

        if not user.agreed_to_rules:
            from app.keyboards import rules_keyboard
            await message.answer(
                "📋 <b>Правила бота</b>\n\n"
                "1. Нельзя публиковать запрещённый или шок-контент.\n"
                "2. Нельзя использовать баги и накручивать награды.\n"
                "3. Уважайте других пользователей и соблюдайте правила Telegram.\n\n"
                "Нажмите кнопку ниже, чтобы принять правила.",
                parse_mode="HTML",
                reply_markup=rules_keyboard()
            )
            return

        if not user.nickname_set or not user.display_name:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="✏️ Установить ник",
                    callback_data="set_nickname_start"
                )]
            ])
            from app.config import NICKNAME_MIN_LENGTH, NICKNAME_MAX_LENGTH
            await message.answer(
                "👋 Добро пожаловать!\n\n"
                "⚠️ Перед началом нужно установить ник.\n"
                f"Первая установка бесплатна!\n"
                f"• От {NICKNAME_MIN_LENGTH} до {NICKNAME_MAX_LENGTH} символов\n"
                f"• Только буквы, цифры, _ и -",
                parse_mode="HTML",
                reply_markup=kb
            )
            return

        await send_welcome_banner(message, session, user)


@router.message(Command("katya"))
async def cmd_katya(message: Message, state: FSMContext):
    """Открывает Катю командой, даже если ReplyKeyboard в клиенте не обновилась."""
    from app.ai_assistant import btn_katya
    await btn_katya(message, state)


_upload_notifications = defaultdict(lambda: {"count": 0, "task": None})

async def _send_upload_notification(bot, chat_id, user_id):
    try:
        await asyncio.sleep(2.0)
        data = _upload_notifications[user_id]
        count = data.get("count", 0)
        dup = data.get("dup_count", 0)
        
        msg = ""
        if count > 0:
            msg += f"✅ Отправлено на модерацию: <b>{count}</b> файлов!\n"
        if dup > 0:
            msg += f"⚠️ Пропущено дубликатов: <b>{dup}</b>."
            
        if msg:
            try:
                await bot.send_message(chat_id, msg.strip(), parse_mode="HTML")
            except Exception:
                pass
    finally:
        # Prevent memory leak - cleanup even on exception
        if user_id in _upload_notifications:
            del _upload_notifications[user_id]
_offer_action_last_ts: dict[tuple[int, str], datetime] = {}
_promo_activate_last_ts: dict[int, datetime] = {}

async def _safe_callback_answer(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
    except Exception:
        pass


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


async def _check_user_offer_subscription(callback: CallbackQuery, offer: Offer) -> bool:
    chat_id = _chat_id_from_offer_url(offer.channel_url)
    if not chat_id:
        return False
    try:
        member = await callback.bot.get_chat_member(chat_id=chat_id, user_id=callback.from_user.id)
        return member.status in {"member", "administrator", "creator"}
    except TelegramBadRequest:
        return False
    except Exception:
        return False


def _cooldown_ok(
    cache: dict,
    key,
    cooldown_seconds: int,
) -> bool:
    now = utc_now()
    last = cache.get(key)
    if last and (now - last).total_seconds() < cooldown_seconds:
        return False
    cache[key] = now
    return True


# =========================
# STATES
# =========================


class NicknameState(StatesGroup):
    waiting_nickname = State()


class CommentState(StatesGroup):
    waiting_text = State()


class CustomBuyState(StatesGroup):
    waiting_stars = State()


class RentOfferState(StatesGroup):
    waiting_channel_title = State()
    waiting_channel_url = State()
    waiting_days = State()


class PromoCreateState(StatesGroup):
    waiting_amount = State()
    waiting_uses = State()
    waiting_hours = State()


class PromoActivateState(StatesGroup):
    waiting_code = State()


class FeedbackState(StatesGroup):
    waiting_text = State()


# =========================
# HELPERS
# =========================


def calc_level_xp_required(level: int) -> int:
    return int(LEVEL_XP_BASE * (LEVEL_XP_MULTIPLIER ** (level - 1)))


def calc_level_from_xp(xp: int) -> int:
    level = 1
    remaining = xp
    while True:
        required = calc_level_xp_required(level)
        if remaining < required:
            break
        remaining -= required
        level += 1
    return level


def is_vip(user) -> bool:
    return bool(user.vip_until and user.vip_until > utc_now())


async def require_nickname(message: Message, user) -> bool:
    """Проверяет наличие ника. False = ник не задан, показано предупреждение."""
    if user.nickname_set and user.display_name:
        return True
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✏️ Установить ник",
            callback_data="set_nickname_start"
        )]
    ])
    await message.answer(
        f"⚠️ <b>Необходимо установить ник!</b>\n\n"
        f"• От {NICKNAME_MIN_LENGTH} до {NICKNAME_MAX_LENGTH} символов\n"
        f"• Только буквы (рус/лат), цифры, _ и -\n"
        f"• Уникальный\n\n"
        f"Первая установка — бесплатно!\n"
        f"Смена ника стоит {NICKNAME_CHANGE_COST} монет.",
        parse_mode="HTML",
        reply_markup=kb
    )
    return False


def _best_event_badge(events: list, target: str) -> str:
    """Выбирает лучший бейдж акции только для релевантного типа покупки."""
    if target == "vip":
        relevant = [e for e in events if getattr(e, "applies_vip", False)]
    elif target == "coins":
        relevant = [e for e in events if getattr(e, "applies_coins", False)]
    else:
        relevant = []

    if not relevant:
        return ""

    best_ev = max(relevant, key=lambda e: e.discount_percent)
    return f"\n🔥 <b>АКЦИЯ: {escape(best_ev.name)} — скидка {best_ev.discount_percent}%!</b>"


async def _level_up_check(session, user, message_or_callback):
    """Проверяет апгрейд уровня и отправляет поздравление."""
    new_level = calc_level_from_xp(user.xp)
    if new_level > user.level:
        user.level = new_level
        await session.commit()
        # Отправляем полноценное сообщение в чат, а не popup-уведомление
        target = message_or_callback.message if isinstance(message_or_callback, CallbackQuery) else message_or_callback
        try:
            await target.answer(
                f"🎉 Поздравляем! Вы достигли уровня <b>{new_level}</b>!",
                parse_mode="HTML"
            )
        except Exception:
            logger.exception("Failed to send level-up message")


# =========================
# NICKNAME FLOW
# =========================
@router.callback_query(F.data == "set_nickname_start")
async def set_nickname_start(callback: CallbackQuery, state: FSMContext):
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        is_first = not user.nickname_set
        cost_text = "бесплатно" if is_first else f"{NICKNAME_CHANGE_COST} монет"

    await state.set_state(NicknameState.waiting_nickname)
    await callback.message.answer(
        f"✏️ Введите ник ({cost_text}):\n\n"
        f"• От {NICKNAME_MIN_LENGTH} до {NICKNAME_MAX_LENGTH} символов\n"
        f"• Буквы (рус/лат), цифры, _ или -\n"
        f"• Без точек, пробелов, спецсимволов"
    )
    await callback.answer()


@router.message(NicknameState.waiting_nickname)
async def process_nickname(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await state.clear()
            return
        admin_free = await is_admin_free_eligible(session, message.from_user.id, user)
        ok, msg = await set_display_name(session, user, name, admin_free=admin_free)

    await message.answer(msg, parse_mode="HTML")
    if ok:
        await state.clear()
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            await send_welcome_banner(message, session, user)


# =========================
# START / RULES
# =========================
async def send_welcome_banner(message_or_callback, session, user):
    target = message_or_callback.message if isinstance(message_or_callback, CallbackQuery) else message_or_callback
    admin_flag = is_any_admin(user.telegram_id, user)
    vip_str = " 👑" if is_vip(user) else ""
    import os
    from aiogram.types import FSInputFile

    styled_name = await get_styled_display_name(session, user)
    msg_text = (
        f"👋 Привет, <b>{styled_name}</b>{vip_str}!\n"
        f"💰 Баланс: <b>{user.balance}</b> монет"
    )
    custom_welcome = await get_setting(session, "welcome_text", "")
    if custom_welcome:
        msg_text += f"\n\n{custom_welcome}"

    banner_file_id = await get_setting(session, "welcome_banner_id", "")

    if banner_file_id:
        try:
            await target.answer_photo(
                photo=banner_file_id,
                caption=msg_text,
                parse_mode="HTML",
                reply_markup=main_menu(is_admin=admin_flag)
            )
        except Exception:
            await target.answer(
                msg_text,
                parse_mode="HTML",
                reply_markup=main_menu(is_admin=admin_flag)
            )
    elif os.path.exists("app/banner.jpg"):
        try:
            await target.answer_photo(
                photo=FSInputFile("app/banner.jpg"),
                caption=msg_text,
                parse_mode="HTML",
                reply_markup=main_menu(is_admin=admin_flag)
            )
        except Exception:
            await target.answer(
                msg_text,
                parse_mode="HTML",
                reply_markup=main_menu(is_admin=admin_flag)
            )
    else:
        await target.answer(
            msg_text,
            parse_mode="HTML",
            reply_markup=main_menu(is_admin=admin_flag)
        )

    # Стартовый лутбокс показываем только новым пользователям (до 24 часов с регистрации)
    # и только один раз.
    is_recent_user = (utc_now() - user.created_at) <= timedelta(days=1)
    already_claimed = (await session.execute(
        select(UserActionLog).where(
            UserActionLog.user_id == user.id,
            UserActionLog.action == "welcome_lootbox",
        )
    )).scalars().first()
    if is_recent_user and not already_claimed:
        lootbox_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Открыть стартовый лутбокс", callback_data="welcome_lootbox_claim")]
        ])
        await target.answer(
            "🎁 <b>Подарок новичку!</b>\n\n"
            "Заберите бесплатный стартовый лутбокс. Внутри — красивое круглое число от 50 до 400 монет.\n"
            "Это ваш приветственный бонус на старт!",
            parse_mode="HTML",
            reply_markup=lootbox_kb,
        )


@router.callback_query(F.data == "accept_rules")
async def accept_rules(callback: CallbackQuery):
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        user.agreed_to_rules = True
        from app.services import process_referral_reward
        if user.referred_by_user_id:
            await process_referral_reward(session, user.referred_by_user_id)
        await session.commit()

        # If user already has nickname, show main menu immediately while session is still alive.
        if user.nickname_set and user.display_name:
            await send_welcome_banner(callback, session, user)
            await callback.answer()
            return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✏️ Установить ник",
            callback_data="set_nickname_start"
        )]
    ])
    await callback.message.answer(
        "✅ Правила приняты!\n\n"
        "Теперь установите ник. Первая установка бесплатна.\n"
        f"• От {NICKNAME_MIN_LENGTH} до {NICKNAME_MAX_LENGTH} символов\n"
        f"• Только буквы (рус/лат), цифры, _ и -",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


# =========================
# ADMIN REDIRECT
# =========================
@router.message(F.text == BTN_ADMIN)
async def cmd_admin_redirect(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if is_any_admin(message.from_user.id, user):
            from app.admin_handlers import cmd_admin
            await cmd_admin(message)


# =========================
# PROFILE
# =========================
@router.message(F.text == BTN_PROFILE)
async def show_profile(message: Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if not await require_nickname(message, user):
            return

        refs = await count_referrals(session, user.id)
        vip_str = ""
        if is_vip(user):
            vip_str = f"\n👑 VIP до: {user.vip_until.strftime('%d.%m.%Y')}"

        level = user.level
        xp_spent = sum(calc_level_xp_required(lvl) for lvl in range(1, level))
        xp_current = user.xp - xp_spent
        xp_needed = calc_level_xp_required(level)
        progress = max(0, min(10, int((xp_current / max(xp_needed, 1)) * 10)))
        bar = "█" * progress + "░" * (10 - progress)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="✏️ Сменить ник",
                callback_data="set_nickname_start"
            )],
            [InlineKeyboardButton(
                text="🛍 Донатный магазин",
                callback_data="donation_shop"
            )]
        ])
        # Стилизованный ник (card-режим для профиля)
        styled_nick = await get_styled_display_name(session, user, card=True)
        text = (
            f"👤 <b>Профиль</b>\n\n"
            f"🏷 Ник:\n{styled_nick}\n\n"
            f"🆔 Telegram ID: <code>{user.telegram_id}</code>\n"
            f"💰 Баланс: <b>{user.balance}</b> монет\n"
            f"🏆 Уровень: <b>{user.level}</b>\n"
            f"⭐ XP: {xp_current}/{xp_needed} [{bar}]\n"
            f"👥 Приглашено друзей: {refs}\n"
            f"💎 Заработано с рефералов: {user.referral_earnings} монет\n"
            f"📊 Статус: {user.status}"
            f"{vip_str}\n\n"
            f"Смена ника стоит {NICKNAME_CHANGE_COST} монет"
        )
        await message.answer(text, parse_mode="HTML", reply_markup=kb)
        await log_user_action(session, user.id, "view_profile")


# =========================
# LEVEL
# =========================
@router.message(F.text == BTN_LEVEL)
async def show_level(message: Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if not await require_nickname(message, user):
            return

        level = user.level
        xp_spent = sum(calc_level_xp_required(lvl) for lvl in range(1, level))
        xp_current = user.xp - xp_spent
        xp_needed = calc_level_xp_required(level)
        progress = max(0, min(10, int((xp_current / max(xp_needed, 1)) * 10)))
        bar = "█" * progress + "░" * (10 - progress)

        text = (
            f"🏆 <b>Уровень: {level}</b>\n\n"
            f"XP: {xp_current}/{xp_needed}\n"
            f"[{bar}]\n\n"
            f"📈 Как получить XP:\n"
            f"• Просмотр видео: +{XP_PER_WATCH} XP\n"
            f"• Загрузка контента: +{XP_PER_UPLOAD} XP\n"
            f"• Оценка видео: +{XP_PER_RATING} XP\n"
            f"• Комментарий: +{XP_PER_COMMENT} XP\n"
            f"• Реакция: +{XP_PER_REACTION} XP\n"
            f"• Игра: +{XP_PER_GAME} XP"
        )
        await message.answer(text, parse_mode="HTML")


# =========================
# VIP
# =========================
@router.message(F.text == BTN_VIP)
async def show_vip(message: Message, state: FSMContext):
    await state.clear()
    try:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                return
            if not await require_nickname(message, user):
                return

            if is_vip(user):
                await message.answer(
                    f"👑 <b>Вы VIP!</b>\n\n"
                    f"До: <b>{user.vip_until.strftime('%d.%m.%Y %H:%M')}</b>\n\n"
                    f"Привилегии:\n"
                    f"• Множитель монет x{VIP_BONUS_MULTIPLIER}\n"
                    f"• Скидка 50% на просмотр\n"
                    f"• Приоритет и бонусы в экономике",
                    parse_mode="HTML"
                )
            else:
                vip_price, packs, sale = await get_current_prices(session, user.id)
                events = await get_active_events(session)
                
                # Admin free badge должен учитывать runtime-настройку из БД
                admin_free_badge = ""
                if await is_admin_free_eligible(session, message.from_user.id, user):
                    admin_free_badge = "\n🆓 <b>ADMIN FREE — бесплатно!</b>"

                sale_badge = _best_event_badge(events, "vip") if events else ""
                if not sale_badge and sale and sale.applies_to in ("all", "vip"):
                    sale_badge = f"\n🔥 <b>АКЦИЯ: скидка {sale.discount_percent}%!</b>"
                
                await message.answer(
                    f"👑 <b>VIP статус</b>\n\n"
                    f"Стоимость: <b>{vip_price} Stars</b> (обычная: {VIP_PRICE_STARS}){sale_badge}{admin_free_badge}\n"
                    f"Длительность: {VIP_DURATION_DAYS} дней\n\n"
                    f"Привилегии:\n"
                    f"• Множитель монет x{VIP_BONUS_MULTIPLIER}\n"
                    f"• Скидка 50% на просмотр\n"
                    f"• Приоритет и бонусы в экономике",
                    parse_mode="HTML",
                    reply_markup=vip_buy_keyboard(vip_price)
                )
    except Exception as e:
        import traceback
        err_detail = traceback.format_exc()
        logger.error(f"Error in show_vip: {err_detail}")
        await message.answer(f"⚠️ Ошибка при получении информации о VIP:\n<code>{escape(str(e))}</code>")


@router.callback_query(F.data == "buy_vip")
async def buy_vip(callback: CallbackQuery):
    payload = f"vip_{callback.from_user.id}_{uuid.uuid4().hex[:6]}"
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return

        admin_free = await is_admin_free_eligible(session, callback.from_user.id, user)
        if not admin_free:
            vip_price_final, _, _ = await get_current_prices(session, user.id)
            await ensure_payment_pending(
                session,
                user_id=user.id,
                payload=payload,
                stars_amount=vip_price_final,
            )
            await session.commit()
            await callback.message.answer_invoice(
                title="VIP статус",
                description=f"VIP на {VIP_DURATION_DAYS} дней",
                payload=payload,
                currency="XTR",
                prices=[LabeledPrice(label="VIP", amount=vip_price_final)]
            )
            await callback.answer()
            return

        # Admin free — выдаём VIP бесплатно
        now = utc_now()
        if user.vip_until and user.vip_until > now:
            user.vip_until += timedelta(days=VIP_DURATION_DAYS)
        else:
            user.vip_until = now + timedelta(days=VIP_DURATION_DAYS)
        
        await log_balance_change(session, user, Decimal("0"), "vip_admin_free",
                                 details=f"ADMIN_FREE: VIP на {VIP_DURATION_DAYS} дней")
        await log_user_action(session, user.id, "vip_admin_free",
                              f"VIP до {user.vip_until.strftime('%d.%m.%Y')}")
        await session.commit()
        
        await callback.message.answer(
            f"👑 <b>VIP активирован бесплатно!</b>\n\n"
            f"🆓 (ADMIN_FREE для админов)\n"
            f"VIP до: <b>{user.vip_until.strftime('%d.%m.%Y %H:%M')}</b>\n\n"
            f"Привилегии:\n"
            f"• Множитель монет x{VIP_BONUS_MULTIPLIER}\n"
            f"• Скидка 50% на просмотр\n"
            f"• Приоритет и бонусы в экономике",
            parse_mode="HTML",
        )
        await callback.answer("🆓 VIP активирован бесплатно!")


# =========================
# WATCH
# =========================
@router.message(F.text == BTN_WATCH)
async def btn_watch(message: Message, state: FSMContext):
    await state.clear()
    from app.services import is_admin_or_super
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if user.status == "banned":
            await message.answer("🚫 Вы заблокированы.")
            return
        if not await require_nickname(message, user):
            return
        admin_flag = is_admin_or_super(message.from_user.id, user)
    await message.answer("👀 Что смотреть?", reply_markup=watch_choice_keyboard(is_admin=admin_flag))


@router.callback_query(F.data == "watch_video_content")
async def watch_video_content(callback: CallbackQuery):
    # Stop Telegram "loading" ASAP
    await _safe_callback_answer(callback)
    try:
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not user:
                return

            # Получаем цену просмотра динамически из настроек БД
            db_cost = await get_setting(session, "watch_cost", "")
            if db_cost:
                try:
                    cost = to_decimal(db_cost)
                except Exception:
                    cost = to_decimal(WATCH_COST)
            else:
                cost = to_decimal(WATCH_COST)

            if is_vip(user):
                db_discount = await get_setting(session, "vip_watch_discount", "")
                if db_discount:
                    try:
                        discount = to_decimal(db_discount)
                    except Exception:
                        discount = to_decimal(0.5)
                else:
                    discount = to_decimal(0.5)
                cost = round(cost * discount, 2)

            if user.balance < cost:
                bot_info = await callback.bot.get_me()
                ref_link = f"https://t.me/{bot_info.username}?start={user.referral_code}"
                if await should_show_low_balance_hint(session, user):
                    await mark_low_balance_hint_shown(session, user.id)
                    await callback.message.answer(
                        f"💸 <b>Монеток маловато!</b>\n\n"
                        f"На счету: <b>{user.balance}</b> монет, "
                        f"а нужно <b>{cost}</b> для просмотра.\n\n"
                        f"🔥 Быстрые варианты вернуть баланс:\n"
                        f"• <b>Офферы</b> — подписки за монеты\n"
                        f"• <b>Рефералка</b> — разошли друзьям свою ссылку и получи <b>+{REFERRAL_REWARD_INVITER}</b> монет\n\n"
                        f"Твоя ссылка:\n<code>{ref_link}</code>",
                        parse_mode="HTML",
                        reply_markup=low_balance_offer_keyboard()
                    )
                else:
                    await callback.message.answer(
                        f"❌ <b>Недостаточно монет.</b>\n\n"
                        f"Нужно: <b>{cost}</b>, у вас: <b>{user.balance}</b>.\n\n"
                        f"Разошли друзьям свою ссылку и получи <b>+{REFERRAL_REWARD_INVITER}</b> монет:\n"
                        f"<code>{ref_link}</code>",
                        parse_mode="HTML",
                    )
                return

            # Обычный показ видео (с безопасной отправкой и возвратом при ошибке)
            last_send_error: str | None = None
            for _ in range(3):
                video = await get_random_video_for_user(session, user.id)
                if not video:
                    break

                ok = await record_view_and_charge_with_cost(session, user.id, video.id, cost)
                if not ok:
                    await callback.message.answer("❌ Ошибка списания монет.")
                    return

                try:
                    await callback.message.answer_video(
                        video.telegram_file_id,
                        caption=(
                            f"🎬 Видео #{video.id}\n"
                            f"💰 Списано: {cost} монет"
                        ),
                        reply_markup=video_rating_keyboard(video.id)
                    )
                except Exception as e:
                    last_send_error = str(e)
                    await mark_content_broken(session, video.id, f"send_failed: {e}")
                    await refund_watch_and_unview(
                        session,
                        user.id,
                        video.id,
                        cost,
                        reason=f"send_failed: {e}",
                    )
                    continue

                # Видео успешно отправлено — возвращаем управление сразу,
                # чтобы внешняя ошибка НЕ показывалась пользователю.
                # Вся пост-обработка выполняется в фоне с защитой от сбоев.
                try:
                    user = await get_user(session, callback.from_user.id)
                    await _level_up_check(session, user, callback)
                    await _update_quest_progress(session, user.id, "watch", 1)

                    if user.referred_by_user_id:
                        await process_referral_reward(session, user.referred_by_user_id)

                    # Увеличиваем счётчик просмотров и проверяем нужно ли показать рекламу
                    await increment_video_watched(session, user.id)

                    if await should_show_ad_after_video(session, user.id):
                        await _show_ad_or_event(callback, session, user)
                except Exception:
                    logger.exception("Post-video processing failed (non-critical)")
                    # Не показываем пользователю ошибку — видео уже успешно отправлено

                return

            await callback.message.answer(
                "😔 Нет доступных видео.\n"
                "Загрузите своё видео, чтобы другие смотрели!"
                + (f"\n\n⚠️ Ошибка отправки: {last_send_error}" if last_send_error else "")
            )
    except Exception:
        logger.exception("watch_video_content failed")
        try:
            await callback.message.answer("⚠️ Ошибка при показе видео. Попробуйте ещё раз через пару секунд.")
        except Exception:
            pass


async def _show_ad_or_event(callback: CallbackQuery, session, user):
    """
    Показывает рекламу после каждых 10 видео.
    Приоритет: сначала событие (если есть), потом оффер.
    """
    events = await get_active_events(session)
    
    # Сначала показываем событие, если есть активное
    if events:
        event = max(events, key=lambda e: e.discount_percent)
        applies = []
        if event.applies_vip:
            applies.append("VIP")
        if event.applies_coins:
            applies.append("монеты")
        if event.applies_lootbox:
            applies.append("лутбоксы")
        if event.applies_cases:
            applies.append("кейсы")
        applies_text = ", ".join(applies) if applies else "всё"
        end_text = event.end_date.strftime("%d.%m")
        
        ad_text = (
            f"🎉 <b>Акция: {event.name}</b>\n\n"
            f"{event.description}\n\n"
            f"🔥 Скидка <b>{event.discount_percent}%</b> на {applies_text}!\n"
            f"⏰ До {end_text}\n\n"
            f"Скорее в магазин, пока действует акция!"
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛍 В магазин", callback_data="btn_buy")],
            [InlineKeyboardButton(text="▶ Смотреть дальше", callback_data="watch_video_content")],
        ])
        
        if event.image_file_id:
            await callback.message.answer_photo(event.image_file_id, caption=ad_text, parse_mode="HTML", reply_markup=kb)
        else:
            await callback.message.answer(ad_text, parse_mode="HTML", reply_markup=kb)
        
        await reset_ad_counter(session, user.id)
        await log_user_action(session, user.id, "event_ad_shown", f"event={event.name}")
        return

    # Если нет событий — показываем оффер
    if await can_show_offer_to_user(session, user.id):
        offer = await get_random_active_offer(session)
        if offer:
            await mark_offer_shown(session, user.id, offer.id, forced=True)
            ad_text = (
                f"📢 <b>Рекомендация</b>\n\n"
                f"<b>{offer.title}</b>\n"
                f"{offer.description}\n\n"
                f"💰 За подписку получите <b>{offer.reward_preview} монет</b>!"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="👉 Подписаться", url=offer.channel_url)],
                [InlineKeyboardButton(text="▶ Смотреть дальше", callback_data="watch_video_content")],
            ])
            await callback.message.answer(ad_text, parse_mode="HTML", reply_markup=kb)
            await reset_ad_counter(session, user.id)
            await log_user_action(session, user.id, "offer_ad_shown", f"offer={offer.id}")
            return

    # Если нет ни событий, ни офферов — просто сбрасываем счётчик
    await reset_ad_counter(session, user.id)


@router.callback_query(F.data == "watch_next")
async def watch_next(callback: CallbackQuery):
    await watch_video_content(callback)


@router.callback_query(F.data == "watch_photo_content")
async def watch_photo_content(callback: CallbackQuery):
    await _safe_callback_answer(callback)
    try:
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not user:
                return

            # Проверка дневного лимита фото для обычных пользователей
            if not is_vip(user):
                can_view = await check_daily_photo_limit(session, user.id)
                if not can_view:
                    await callback.message.answer(
                        f"📸 Вы исчерпали лимит просмотра фото на сегодня ({DAILY_PHOTO_LIMIT} шт.).\n"
                        f"👑 VIP пользователи смотрят без ограничений.",
                        parse_mode="HTML"
                    )
                    return

            last_send_error: str | None = None
            for _ in range(3):
                photo = await get_random_photo_for_user(session, user.id)
                if not photo:
                    break
                try:
                    await callback.message.answer_photo(
                        photo.telegram_file_id,
                        caption=f"🖼 Фото #{photo.id}",
                        reply_markup=photo_actions_keyboard(photo.id)
                    )
                except Exception as e:
                    last_send_error = str(e)
                    await mark_content_broken(session, photo.id, f"send_failed: {e}")
                    continue

                # Фото успешно отправлено — пост-обработка в фоне
                try:
                    await record_photo_view(session, user.id, photo.id)
                    if user.referred_by_user_id:
                        await process_referral_reward(session, user.referred_by_user_id)
                except Exception:
                    logger.exception("Post-photo processing failed (non-critical)")
                return

            await callback.message.answer(
                "😔 Нет доступных фото."
                + (f"\n\n⚠️ Ошибка отправки: {last_send_error}" if last_send_error else "")
            )
    except Exception:
        logger.exception("watch_photo_content failed")
        try:
            await callback.message.answer("⚠️ Ошибка при показе фото. Попробуйте ещё раз через пару секунд.")
        except Exception:
            pass


@router.callback_query(F.data == "watch_next_photo")
async def watch_next_photo(callback: CallbackQuery):
    await watch_photo_content(callback)


# =========================
# RATING
# =========================
@router.callback_query(F.data.startswith("rate:"))
async def cb_rate(callback: CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    video_id, rating = int(parts[1]), int(parts[2])

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        await rate_video(session, user.id, video_id, rating)
        xp_mult = await get_xp_multiplier(session, user.id)
        user.xp += int(XP_PER_RATING * xp_mult)
        await _level_up_check(session, user, callback)
        await session.commit()
        await _update_quest_progress(session, user.id, "rate", 1)

    await callback.answer(f"⭐ Оценка {rating} сохранена!")


# =========================
# COMMENTS
# =========================
@router.callback_query(F.data.startswith("comments:"))
async def cb_comments(callback: CallbackQuery):
    video_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        comments = (await session.execute(
            select(Comment)
            .where(Comment.video_id == video_id)
            .order_by(desc(Comment.created_at))
            .limit(10)
        )).scalars().all()

        text = f"💬 <b>Комментарии к видео #{video_id}</b>\n\n"
        if not comments:
            text += "Комментариев пока нет. Будьте первым!"
        else:
            for c in comments:
                u = await get_user_by_id(session, c.user_id)
                name = await get_styled_display_name(session, u) if u else "???"
                text += f"👤 <b>{escape(name)}</b>: {escape(c.text)}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✏️ Написать",
            callback_data=f"add_comment:{video_id}"
        )],
        [
            InlineKeyboardButton(
                text="😀 Реакции",
                callback_data=f"reactions:{video_id}"
            ),
            InlineKeyboardButton(
                text="🚨 Жалоба",
                callback_data=f"report_video:{video_id}"
            ),
        ],
    ])
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("add_comment:"))
async def add_comment_start(callback: CallbackQuery, state: FSMContext):
    video_id = int(callback.data.split(":")[1])
    await state.set_state(CommentState.waiting_text)
    await state.update_data(video_id=video_id)
    await callback.message.answer("✏️ Напишите комментарий:")
    await callback.answer()


@router.message(CommentState.waiting_text)
async def process_comment(message: Message, state: FSMContext):
    data = await state.get_data()
    video_id = data.get("video_id")
    if not video_id:
        await state.clear()
        return

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await state.clear()
            return

        # Антиспам
        ten_min_ago = utc_now() - timedelta(minutes=10)
        recent = (await session.execute(
            select(func.count(Comment.id)).where(
                Comment.user_id == user.id,
                Comment.created_at >= ten_min_ago
            )
        )).scalar_one()
        if recent >= COMMENTS_PER_10_MIN:
            await message.answer(
                f"⚠️ Не более {COMMENTS_PER_10_MIN} комментариев за 10 минут."
            )
            await state.clear()
            return

        from app.models import Comment as CommentModel
        session.add(CommentModel(
            user_id=user.id,
            video_id=video_id,
            text=message.text
        ))
        xp_mult = await get_xp_multiplier(session, user.id)
        user.xp += int(XP_PER_COMMENT * xp_mult)
        await _level_up_check(session, user, message)
        await session.commit()
        await _update_quest_progress(session, user.id, "comment", 1)

    await message.answer("✅ Комментарий опубликован!")
    await state.clear()


# =========================
# REACTIONS
# =========================
@router.callback_query(F.data.startswith("reactions:"))
async def cb_reactions_menu(callback: CallbackQuery):
    video_id = int(callback.data.split(":")[1])
    await callback.message.answer(
        "Выберите реакцию:",
        reply_markup=reaction_menu_keyboard(video_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("react:"))
async def cb_react(callback: CallbackQuery):
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    video_id, reaction = int(parts[1]), parts[2]

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return

        # Check exclusive reactions perk
        exclusive_list = {"💎", "👑", "🔥", "⚡"}
        if reaction in exclusive_list:
            from app.services import has_active_perk
            if not await has_active_perk(session, user.id, "exclusive_reactions"):
                await callback.answer("❌ Эта реакция доступна только с перком «Эксклюзивные реакции»", show_alert=True)
                return

        existing = (await session.execute(
            select(ContentReaction).where(
                ContentReaction.user_id == user.id,
                ContentReaction.video_id == video_id
            )
        )).scalar_one_or_none()

        if existing:
            existing.reaction_type = reaction
        else:
            session.add(ContentReaction(
                user_id=user.id,
                video_id=video_id,
                reaction_type=reaction
            ))
            xp_mult = await get_xp_multiplier(session, user.id)
            user.xp += int(XP_PER_REACTION * xp_mult)
            await _level_up_check(session, user, callback)
            # Commit XP and reaction immediately
            await session.commit()

        await session.commit()
        await _update_quest_progress(session, user.id, "react", 1)

    await callback.answer(f"{reaction} Поставлена!")


# =========================
# UPLOAD
# =========================
@router.message(F.text == BTN_UPLOAD)
async def btn_upload(message: Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if user.status == "banned":
            await message.answer("🚫 Вы заблокированы.")
            return
        if not await require_nickname(message, user):
            return
    await message.answer(
        "📤 Отправьте видео или фото.\n\n"
        "После проверки модератором вы получите монеты!"
    )


@router.message(F.video)
async def handle_video_upload(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user or user.status == "banned":
            return
        if not user.agreed_to_rules:
            await message.answer("Примите правила командой /start")
            return
        if not user.nickname_set:
            await require_nickname(message, user)
            return

        v = message.video
        saved, is_duplicate = await save_video(
            session, user.id,
            v.file_id, v.file_unique_id,
            v.duration, v.file_size
        )

        if is_duplicate:
            data = _upload_notifications[user.id]
            if "dup_count" not in data:
                data["dup_count"] = 0
            data["dup_count"] += 1
            if data["task"] is None or data["task"].done():
                data["task"] = asyncio.create_task(_send_upload_notification(message.bot, message.chat.id, user.id))
            return

        # Авто-модерация для доверенных авторов
        from app.services import auto_approve_if_trusted
        auto_approved = await auto_approve_if_trusted(session, saved.id, user.id)
        
        if auto_approved:
            xp_mult = await get_xp_multiplier(session, user.id)
            user.xp += int(XP_PER_UPLOAD * xp_mult)
            await _level_up_check(session, user, message)
            await session.commit()
            await _update_quest_progress(session, user.id, "upload", 1)
            await message.answer(f"✅ Видео #{saved.id} автоматически одобрено! (доверенный автор)\n+{UPLOAD_REWARD:.0f} монет")
            return

        xp_mult = await get_xp_multiplier(session, user.id)
        user.xp += int(XP_PER_UPLOAD * xp_mult)
        await _level_up_check(session, user, message)
        await session.commit()
        await _update_quest_progress(session, user.id, "upload", 1)
        # Запланировать агрегированное уведомление админам
        await schedule_mod_notification(session, "video")
        data = _upload_notifications[user.id]
        if "count" not in data:
            data["count"] = 0
        data["count"] += 1
        if data["task"] is None or data["task"].done():
            data["task"] = asyncio.create_task(_send_upload_notification(message.bot, message.chat.id, user.id))


@router.message(F.photo)
async def handle_photo_upload(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user or user.status == "banned":
            return
        if not user.agreed_to_rules:
            await message.answer("Примите правила командой /start")
            return
        if not user.nickname_set:
            await require_nickname(message, user)
            return

        p = message.photo[-1]
        saved, is_duplicate = await save_photo(
            session, user.id,
            p.file_id, p.file_unique_id,
            p.file_size
        )

        if is_duplicate:
            data = _upload_notifications[user.id]
            # Initialize safely
            if "dup_count" not in data:
                data["dup_count"] = 0
            data["dup_count"] += 1
            if data["task"] is None or data["task"].done():
                data["task"] = asyncio.create_task(_send_upload_notification(message.bot, message.chat.id, user.id))
            return

        # Авто-модерация для доверенных авторов
        from app.services import auto_approve_if_trusted
        auto_approved = await auto_approve_if_trusted(session, saved.id, user.id)
        
        if auto_approved:
            xp_mult = await get_xp_multiplier(session, user.id)
            user.xp += int(XP_PER_UPLOAD * xp_mult)
            await _level_up_check(session, user, message)
            await session.commit()
            await _update_quest_progress(session, user.id, "upload", 1)
            await message.answer(f"✅ Фото #{saved.id} автоматически одобрено! (доверенный автор)\n+{PHOTO_UPLOAD_REWARD:.0f} монет")
            return

        xp_mult = await get_xp_multiplier(session, user.id)
        user.xp += int(XP_PER_UPLOAD * xp_mult)
        await _level_up_check(session, user, message)
        await session.commit()
        await _update_quest_progress(session, user.id, "upload", 1)
        data = _upload_notifications[user.id]
        if "count" not in data:
            data["count"] = 0
        data["count"] += 1
        if data["task"] is None or data["task"].done():
            data["task"] = asyncio.create_task(_send_upload_notification(message.bot, message.chat.id, user.id))


# =========================
# BONUS
# =========================
@router.message(F.text == BTN_BONUS)
async def btn_bonus(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🎁 <b>Ежедневный бонус отключён.</b>\n\n"
        "Теперь вместо него работает еженедельная халява: секретный промокод, который бот рассылает автоматически.\n"
        "Откройте раздел <b>🎟 Промокоды</b> и следите за рассылкой.",
        parse_mode="HTML",
    )


# =========================
# REFERRALS
# =========================
@router.message(F.text == BTN_REFERRALS)
async def btn_referrals(message: Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if not await require_nickname(message, user):
            return
        refs = await count_referrals(session, user.id)

    bot_info = await message.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user.referral_code}"
    await message.answer(
        f"👥 <b>Рефералы</b>\n\n"
        f"Ваша ссылка:\n<code>{ref_link}</code>\n\n"
        f"Приглашено: <b>{refs}</b>\n"
        f"Заработано: <b>{user.referral_earnings}</b> монет\n\n"
        f"За каждого приглашённого:\n"
        f"• Вы получаете: +{REFERRAL_REWARD_INVITER} монет\n"
        f"• Новый пользователь: +{REFERRAL_REWARD_NEW_USER} монет",
        parse_mode="HTML"
    )


# =========================
# BUY COINS
# =========================
@router.message(F.text == BTN_BUY)
async def btn_buy(message: Message, state: FSMContext):
    await state.clear()
    try:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                return
            if not await require_nickname(message, user):
                return

            vip_price, packs, sale = await get_current_prices(session, user.id)
            events = await get_active_events(session)

            # Admin free badge
            admin_free_badge = ""
            if await is_admin_free_eligible(session, message.from_user.id, user):
                admin_free_badge = "\n🆓 <b>ADMIN FREE — всё бесплатно!</b>"

        # Бейдж активной акции только для покупок монет
        sale_badge = _best_event_badge(events, "coins") if events else ""
        if not sale_badge and sale and sale.applies_to in ("all", "coins"):
            sale_badge = f"\n🔥 <b>АКЦИЯ: скидка {sale.discount_percent}%!</b>"

        # Динамический курс
        bonus_text = ""
        if DYNAMIC_STAR_DISCOUNT_ENABLED:
            try:
                start_h, end_h = map(int, DYNAMIC_STAR_DISCOUNT_HOURS.split("-"))
                now_h = utc_now().hour
                if start_h <= now_h < end_h:
                    bonus_text = f"\n🔥 <b>Сейчас действует бонус +{int((DYNAMIC_STAR_DISCOUNT_MULTIPLIER - 1) * 100)}% монет!</b>"
                else:
                    bonus_text = f"\n💡 Часы бонуса: {start_h}:00–{end_h}:00 UTC (+{int((DYNAMIC_STAR_DISCOUNT_MULTIPLIER - 1) * 100)}%)"
            except Exception:
                pass
        bonus_text += f"\n🎁 Первая покупка дня: +{FIRST_PURCHASE_DAILY_BONUS} монет бонусом."

        await message.answer(
            f"💳 <b>Пополнение баланса</b>{sale_badge}{admin_free_badge}{bonus_text}\n\nВыберите пакет:",
            parse_mode="HTML",
            reply_markup=buy_coins_keyboard(packs)
        )
    except Exception as e:
        import traceback
        err_detail = traceback.format_exc()
        logger.error(f"Error in btn_buy: {err_detail}")
        await message.answer(f"⚠️ Ошибка при получении пакетов пополнения:\n<code>{escape(str(e))}</code>")


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy_pack(callback: CallbackQuery):
    pack_key = callback.data.split(":")[1]
    pack = STARS_PACKAGES.get(pack_key)
    if not pack:
        await callback.answer("Пакет не найден.", show_alert=True)
        return

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return

        _, current_packs, _ = await get_current_prices(session, user.id)
        current_pack = current_packs.get(pack_key)
        if not current_pack:
            await callback.answer("Пакет не найден.", show_alert=True)
            return

        # Admin free — выдаём монеты без оплаты
        if await is_admin_free_eligible(session, callback.from_user.id, user):
            coins = pack["coins"]
            bonus = to_decimal(FIRST_PURCHASE_DAILY_BONUS)
            total = to_decimal(coins) + bonus
            
            user = await change_balance_atomic(
                session,
                user.id,
                total,
                "purchase_admin_free",
                details=f"ADMIN_FREE: {pack['title']} + bonus"
            ) or user
            await log_user_action(session, user.id, "admin_free_purchase",
                                  f"pack={pack_key}, coins={total}")
            await session.commit()

            await callback.message.answer(
                f"✅ <b>Пополнение баланса</b>\n\n"
                f"🆓 <b>ADMIN FREE</b> — бесплатно!\n\n"
                f"Получено: <b>{coins} монет</b>\n"
                f"Бонус первой покупки: +<b>{int(bonus)} монет</b>\n\n"
                f"Ваш баланс: <b>{user.balance:.0f}</b> монет",
                parse_mode="HTML",
            )
            await callback.answer("🆓 Пополнено бесплатно!", show_alert=True)
            return

        payment = await create_payment(
            session,
            user.id,
            pack_key,
            stars_amount_override=current_pack["stars"],
        )

    await callback.message.answer_invoice(
        title=f"Покупка {pack['title']}",
        description=f"{pack['coins']} монет за {current_pack['stars']} Stars",
        payload=payment.payload,
        currency="XTR",
        prices=[LabeledPrice(label=pack['title'], amount=current_pack['stars'])]
    )
    await callback.answer()


@router.callback_query(F.data == "buy_custom")
async def cb_buy_custom(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CustomBuyState.waiting_stars)
    await callback.message.answer("💫 Введите количество Stars (мин. 1):")
    await callback.answer()


@router.message(CustomBuyState.waiting_stars)
async def process_custom_stars(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("❌ Введите целое число.")
        return
    stars = int(message.text)
    if stars < 1:
        await message.answer("❌ Минимум 1 Star.")
        return

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await state.clear()
            return

        # Admin free — выдаём монеты без оплаты
        if await is_admin_free_eligible(session, message.from_user.id, user):
            coins = int(stars * STARS_TO_COINS_RATE)
            bonus = to_decimal(FIRST_PURCHASE_DAILY_BONUS)
            total = to_decimal(coins) + bonus

            user = await change_balance_atomic(
                session,
                user.id,
                total,
                "purchase_admin_free",
                details=f"ADMIN_FREE: custom {coins} монет + bonus"
            ) or user
            await log_user_action(session, user.id, "admin_free_purchase",
                                  f"custom_stars={stars}, coins={total}")
            await session.commit()

            await message.answer(
                f"✅ <b>Пополнение баланса</b>\n\n"
                f"🆓 <b>ADMIN FREE</b> — бесплатно!\n\n"
                f"Получено: <b>{coins} монет</b>\n"
                f"Бонус первой покупки: +<b>{int(bonus)} монет</b>\n\n"
                f"Ваш баланс: <b>{user.balance:.0f}</b> монет",
                parse_mode="HTML",
            )
            await state.clear()
            return

        discount = await get_stars_discount(session, user.id)
        billed_stars = max(1, int(math.ceil(stars * (1 - discount)))) if discount > 0 else stars
        payment = await create_custom_payment(session, user.id, stars, billed_stars_amount=billed_stars)
        coins = int(stars * STARS_TO_COINS_RATE)

    await message.answer_invoice(
        title=f"Покупка {coins} монет",
        description=f"{coins} монет за {billed_stars} Stars",
        payload=payment.payload,
        currency="XTR",
        prices=[LabeledPrice(label=f"{coins} монет", amount=billed_stars)]
    )
    await state.clear()


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    payload = query.invoice_payload or ""
    allowed = (
        payload.startswith("pack_")
        or payload.startswith("custom_")
        or payload.startswith("vip_")
        or payload.startswith("promo_")
        or payload.startswith("lootbox_")
        or payload.startswith("user_offer_")
    )
    if not allowed:
        await query.answer(ok=False, error_message="Неверный платёжный payload.")
        return
    async with async_session() as session:
        user = await get_user(session, query.from_user.id)
        if not user:
            await query.answer(ok=False, error_message="Пользователь не найден.")
            return
        payment = await get_payment_by_payload(session, payload)
        if not payment:
            await query.answer(ok=False, error_message="Платёж не найден.")
            return
        if payment.user_id != user.id:
            await query.answer(ok=False, error_message="Платёж принадлежит другому пользователю.")
            return
        if payment.status != "pending":
            await query.answer(ok=False, error_message="Платёж уже обработан.")
            return
        if int(payment.stars_amount) != int(query.total_amount):
            await query.answer(ok=False, error_message="Сумма платежа не совпадает.")
            return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    paid_stars = int(message.successful_payment.total_amount)

    if payload.startswith("vip_"):
        parts = payload.split("_")
        if len(parts) < 3 or not parts[1].isdigit() or int(parts[1]) != message.from_user.id:
            await message.answer("Ошибка платежа: некорректный payload.")
            return
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if user:
                payment = await get_payment_by_payload(session, payload)
                if not payment:
                    await ensure_payment_pending(
                        session,
                        user_id=user.id,
                        payload=payload,
                        stars_amount=paid_stars,
                    )
                    payment = await get_payment_by_payload(session, payload)
                if not payment or payment.user_id != user.id:
                    await session.rollback()
                    session.expunge_all()
                    await message.answer("Ошибка платежа: пользователь не совпадает.")
                    return
                if int(payment.stars_amount) != paid_stars:
                    await session.rollback()
                    session.expunge_all()
                    await message.answer("Ошибка платежа: сумма не совпадает.")
                    return
                if not await mark_payment_paid_once(session, payload):
                    await session.rollback()
                    session.expunge_all()
                    await message.answer("✅ Платёж уже был обработан ранее.")
                    return
                now = utc_now()
                user.vip_until = (
                    user.vip_until + timedelta(days=VIP_DURATION_DAYS)
                    if user.vip_until and user.vip_until > now
                    else now + timedelta(days=VIP_DURATION_DAYS)
                )
                await log_user_action(
                    session, user.id,
                    "buy_vip",
                    f"payload={payload};until={user.vip_until}",
                    auto_commit=False,
                )
                await session.commit()
        await message.answer(
            f"👑 VIP активирован на {VIP_DURATION_DAYS} дней!"
        )
    elif payload.startswith("promo_"):
        # Инвойс на создание промокода (платный)
        parts = payload.split("_")
        if len(parts) >= 5:
            try:
                creator_tg_id = int(parts[1])
                amount = int(parts[2])
                uses = int(parts[3])
                hours = int(parts[4])
            except Exception:
                await message.answer("Ошибка платежа: некорректный payload.")
                return
            async with async_session() as session:
                user = await get_user(session, creator_tg_id)
                if not user or user.telegram_id != message.from_user.id:
                    await message.answer("Ошибка платежа: пользователь не найден.")
                    return
                payment = await get_payment_by_payload(session, payload)
                if not payment:
                    await ensure_payment_pending(
                        session,
                        user_id=user.id,
                        payload=payload,
                        stars_amount=paid_stars,
                    )
                    payment = await get_payment_by_payload(session, payload)
                if not payment or payment.user_id != user.id:
                    await session.rollback()
                    session.expunge_all()
                    await message.answer("Ошибка платежа: пользователь не совпадает.")
                    return
                if int(payment.stars_amount) != paid_stars:
                    await session.rollback()
                    session.expunge_all()
                    await message.answer("Ошибка платежа: сумма не совпадает.")
                    return
                if not await mark_payment_paid_once(session, payload):
                    await session.rollback()
                    session.expunge_all()
                    await message.answer("✅ Платёж уже был обработан ранее.")
                    return
                promo, cost, error = await create_promocode(
                    session, creator_tg_id,
                    to_decimal(amount), uses, hours,
                    auto_commit=False,
                )
                if error:
                    await session.rollback()
                    session.expunge_all()
                    await message.answer(f"❌ Ошибка создания промокода: {error}")
                else:
                    # Фиксируем фактически оплаченные Stars, чтобы учёт не врал при скидках.
                    promo.stars_paid = paid_stars
                    await session.commit()
                    bot = await message.bot.get_me()
                    await message.answer(
                        f"✅ Промокод создан:\n"
                        f"<code>{promo.code}</code>\n"
                        f"Сумма: {amount} монет, использований: {uses}/{promo.max_uses}\n"
                        f"Ссылка: t.me/{bot.username}?start=promo_{promo.code}",
                        parse_mode="HTML"
                    )
        else:
            await message.answer("Ошибка платежа.")
    elif payload.startswith("lootbox_"):
        parts = payload.split("_")
        if len(parts) < 3 or not parts[1].isdigit() or int(parts[1]) != message.from_user.id:
            await message.answer("Ошибка платежа: некорректный payload.")
            return
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                await message.answer("⚠️ Пользователь не найден.")
                return
            payment = await get_payment_by_payload(session, payload)
            if not payment:
                await ensure_payment_pending(
                    session,
                    user_id=user.id,
                    payload=payload,
                    stars_amount=paid_stars,
                )
                payment = await get_payment_by_payload(session, payload)
            if not payment or payment.user_id != user.id:
                await session.rollback()
                session.expunge_all()
                await message.answer("Ошибка платежа: пользователь не совпадает.")
                return
            if int(payment.stars_amount) != paid_stars:
                await session.rollback()
                session.expunge_all()
                await message.answer("Ошибка платежа: сумма не совпадает.")
                return
            reward, rarity_or_err = await open_lootbox_for_stars(
                session,
                telegram_user_id=message.from_user.id,
                payment_payload=payload,
            )
            # Keep Payment status aligned with idempotent lootbox processing.
            if await mark_payment_paid_once(session, payload):
                await session.commit()
        if reward is None:
            await message.answer(f"⚠️ {rarity_or_err}")
        else:
            rarity = rarity_or_err
            icon = {"common": "⚪", "rare": "🔵", "epic": "🟣", "jackpot": "🟡"}.get(rarity, "🎁")
            await message.answer(
                f"{icon} <b>Лутбокс открыт!</b>\n\n"
                f"Выигрыш: <b>+{reward:,.0f}</b> монет".replace(',', ' '),
                parse_mode="HTML",
            )
    elif payload.startswith("user_offer_"):
        try:
            # payload format: "user_offer_{offer_id}"
            offer_id = int(payload.split("_")[2])
            async with async_session() as session:
                user = await get_user(session, message.from_user.id)
                if not user:
                    await message.answer("⚠️ Пользователь не найден.")
                    return

                payment = await get_payment_by_payload(session, payload)
                if not payment or payment.user_id != user.id:
                    await message.answer("Ошибка платежа: платёж не найден или принадлежит другому пользователю.")
                    return
                if int(payment.stars_amount) != paid_stars:
                    await message.answer("Ошибка платежа: сумма не совпадает.")
                    return
                if not await mark_payment_paid_once(session, payload):
                    await session.rollback()
                    session.expunge_all()
                    await message.answer("✅ Платёж уже был обработан ранее.")
                    return

                offer = await session.get(Offer, offer_id)
                if not offer or offer.creator_user_id != user.id:
                    await session.rollback()
                    session.expunge_all()
                    await message.answer("Ошибка платежа: оффер не найден или не принадлежит вам.")
                    return

                offer.status = "pending"
                await session.commit()

                from app.services import schedule_mod_notification
                await schedule_mod_notification(session, "offer")

                await message.answer(
                    "✅ Оплата прошла успешно! Ваш оффер отправлен на модерацию.\n"
                    "Он появится в списке, как только администратор его одобрит."
                )
        except Exception as e:
            await message.answer(f"⚠️ Ошибка при обработке оффера: {e}")
    else:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                await message.answer("⚠️ Пользователь не найден.")
                return
            payment_row = await get_payment_by_payload(session, payload)
            if not payment_row or payment_row.user_id != user.id:
                await message.answer("Ошибка платежа: не найден в системе.")
                return
            if int(payment_row.stars_amount) != paid_stars:
                await message.answer("Ошибка платежа: сумма не совпадает.")
                return
            payment, credited_total = await apply_successful_payment(session, payload)
        if payment:
            await message.answer(
                f"✅ Оплата успешна!\n"
                f"💰 Начислено: <b>{credited_total:,.0f}</b> монет".replace(',', ' '),
                parse_mode="HTML"
            )
        else:
            await message.answer("✅ Оплата получена!")


def _lootbox_kb(coin_price: Decimal | None = None, star_price: int | None = None) -> InlineKeyboardMarkup:
    coin_price = to_decimal(coin_price if coin_price is not None else LOOTBOX_COIN_PRICE)
    star_price = int(star_price if star_price is not None else LOOTBOX_STAR_PRICE)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"🪙 Купить за {coin_price:,.0f} монет".replace(',', ' '),
            callback_data="lootbox_buy:coins"
        )],
        [InlineKeyboardButton(
            text=f"⭐ Купить за {star_price} Stars",
            callback_data="lootbox_buy:stars"
        )],
    ])


@router.callback_query(F.data == "lootbox_menu")
async def lootbox_menu(callback: CallbackQuery):
    if not ENABLE_LOOTBOXES:
        await callback.message.answer("⛔ Лутбоксы временно отключены.")
        await callback.answer()
        return

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        discount = await get_stars_discount(session, user.id) if user else 0.0

    coin_price = to_decimal(LOOTBOX_COIN_PRICE)
    base_star_price = int(LOOTBOX_STAR_PRICE)
    star_price = max(1, int(math.ceil(base_star_price * (1 - discount)))) if discount > 0 else base_star_price
    await callback.message.answer(
        ("🎁 <b>Лутбоксы</b>\n\n"
         f"Цена: <b>{coin_price:,.0f}</b> монет или <b>{star_price}</b> Stars.\n".replace(',', ' ') +
         "Внутри — случайный выигрыш монет.\n"
         "Редкие крупные выигрыши возможны, но не гарантированы."),
        parse_mode="HTML",
        reply_markup=_lootbox_kb(coin_price, star_price),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("lootbox_buy:"))
async def lootbox_buy(callback: CallbackQuery):
    if not ENABLE_LOOTBOXES:
        await callback.answer("Лутбоксы отключены.", show_alert=True)
        return
    from app.services import _roll_lootbox_reward_coins, open_lootbox_for_coins
    kind = callback.data.split(":", 1)[1]
    if kind == "coins":
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not user:
                await callback.answer()
                return

            # Admin free
            admin_free = await is_admin_free_eligible(session, callback.from_user.id, user)
            discount = await get_stars_discount(session, user.id)
            coin_price = to_decimal(LOOTBOX_COIN_PRICE)
            base_star_price = int(LOOTBOX_STAR_PRICE)
            display_star_price = max(1, int(math.ceil(base_star_price * (1 - discount)))) if discount > 0 else base_star_price
            if not admin_free and user.balance < coin_price:
                await callback.answer(f"Недостаточно монет. Нужно: {coin_price:.0f}", show_alert=True)
                return

            if admin_free:
                # Бесплатный лутбокс для админа
                reward, rarity = _roll_lootbox_reward_coins()
                user = await change_balance_atomic(
                    session,
                    user.id,
                    reward,
                    "lootbox_reward_admin_free",
                    details=f"ADMIN_FREE rarity={rarity}"
                ) or user
                session.add(LootboxOpen(
                    user_id=user.id, payment_payload=None, pay_currency="coins",
                    price_coins=Decimal("0"), price_stars=0, reward_coins=reward, rarity=rarity,
                ))
                await log_user_action(session, user.id, "lootbox_open_admin_free",
                                      f"rarity={rarity}, reward={reward}")
                await session.commit()
                icon = {"common": "⚪", "rare": "🔵", "epic": "🟣", "jackpot": "🟡"}.get(rarity, "🎁")
                await callback.message.answer(
                    f"{icon} <b>Лутбокс открыт!</b> (🆓 ADMIN FREE)\n\n"
                    f"Выигрыш: <b>+{reward:,.0f}</b> монет".replace(',', ' '),
                    parse_mode="HTML",
                    reply_markup=_lootbox_kb(coin_price, display_star_price),
                )
                await callback.answer("🆓 Лутбокс открыт бесплатно!")
                return

            reward, rarity_or_err = await open_lootbox_for_coins(session, user.id)
        if reward is None:
            await callback.answer(rarity_or_err, show_alert=True)
            return
        rarity = rarity_or_err
        icon = {"common": "⚪", "rare": "🔵", "epic": "🟣", "jackpot": "🟡"}.get(rarity, "🎁")
        await callback.message.answer(
            f"{icon} <b>Лутбокс открыт!</b>\n\n"
            f"Выигрыш: <b>+{reward:,.0f}</b> монет".replace(',', ' '),
            parse_mode="HTML",
            reply_markup=_lootbox_kb(coin_price, display_star_price),
        )
        await callback.answer()
        return

    if kind == "stars":
        base_star_price = int(LOOTBOX_STAR_PRICE)
        payload = f"lootbox_{callback.from_user.id}_{uuid.uuid4().hex[:8]}"
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not user:
                await callback.answer()
                return

            # Admin free — выдаём результат сразу, без оплаты
            if await is_admin_free_eligible(session, callback.from_user.id, user):
                from app.services import _roll_lootbox_reward_coins
                reward, rarity = _roll_lootbox_reward_coins()
                user = await change_balance_atomic(
                    session,
                    user.id,
                    reward,
                    "lootbox_reward_admin_free",
                    details=f"ADMIN_FREE stars rarity={rarity}"
                ) or user
                session.add(LootboxOpen(
                    user_id=user.id, payment_payload=payload, pay_currency="stars",
                    price_coins=Decimal("0"), price_stars=base_star_price, reward_coins=reward, rarity=rarity,
                ))
                await log_user_action(session, user.id, "lootbox_open_admin_free",
                                      f"payload={payload}, rarity={rarity}, reward={reward}")
                await session.commit()
                icon = {"common": "⚪", "rare": "🔵", "epic": "🟣", "jackpot": "🟡"}.get(rarity, "🎁")
                await callback.message.answer(
                    f"{icon} <b>Лутбокс открыт!</b> (🆓 ADMIN FREE)\n\n"
                    f"Выигрыш: <b>+{reward:,.0f}</b> монет".replace(',', ' '),
                    parse_mode="HTML",
                    reply_markup=_lootbox_kb(to_decimal(LOOTBOX_COIN_PRICE), base_star_price),
                )
                await callback.answer("🆓 Лутбокс открыт бесплатно!")
                return

            discount = await get_stars_discount(session, user.id)
            star_price = max(1, int(math.ceil(base_star_price * (1 - discount)))) if discount > 0 else base_star_price
            await ensure_payment_pending(
                session,
                user_id=user.id,
                payload=payload,
                stars_amount=star_price,
            )
            await session.commit()
        await callback.message.answer_invoice(
            title="Лутбокс",
            description=f"Открытие лутбокса за {star_price} Stars",
            payload=payload,
            currency="XTR",
            prices=[LabeledPrice(label="Лутбокс", amount=star_price)],
        )
        await callback.answer()
        return

    await callback.answer()



@router.callback_query(F.data == "btn_buy")
async def cb_btn_buy(callback: CallbackQuery, state: FSMContext):
    # Reuse btn_buy logic
    from aiogram.types import Message as TGMessage
    # create a fake message proxy – easier: call internal logic directly
    await btn_buy(callback.message, state)  # type: ignore
    await callback.answer()

# =========================
# OFFERS
# =========================
@router.message(F.text == BTN_OFFERS)
async def btn_offers(message: Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if not await require_nickname(message, user):
            return

    from app.user_offer_handlers import user_offers_menu
    await message.answer(
        "📢 <b>Офферы</b>\n\nВыберите раздел:",
        parse_mode="HTML",
        reply_markup=user_offers_menu()
    )


@router.callback_query(F.data == "offers_participation")
async def offers_participation(callback: CallbackQuery):
    async with async_session() as session:
        offers = await get_active_offers(session)

    if not offers:
        await callback.message.answer("😔 Активных офферов нет.")
        await callback.answer()
        return

    await callback.message.answer(
        "📢 <b>Офферы для участия</b>\n\nВыберите оффер:",
        parse_mode="HTML",
        reply_markup=offers_list_keyboard(offers)
    )
    await callback.answer()


@router.callback_query(F.data == "back_to_offers")
async def back_to_offers(callback: CallbackQuery):
    await offers_participation(callback)


@router.callback_query(F.data.startswith("offer_open:"))
async def cb_offer_open(callback: CallbackQuery):
    offer_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        offer = await get_offer_by_id(session, offer_id)
        if not offer:
            await callback.answer("Оффер не найден.", show_alert=True)
            return

        from sqlalchemy import select as sa_select
        from app.models import OfferParticipation
        participants = (await session.execute(
            sa_select(func.count(OfferParticipation.id)).where(
                OfferParticipation.offer_id == offer_id
            )
        )).scalar_one()

    text = (
        f"📢 <b>{offer.title}</b>\n\n"
        f"{offer.description}\n\n"
        f"💰 Предварительно: <b>{offer.reward_preview}</b> монет\n"
        f"🎁 После подтверждения: <b>{offer.reward_final}</b> монет\n"
        f"⚠️ Штраф за отписку: <b>{offer.penalty_unsubscribe}</b> монет\n"
        f"👥 Участников: {participants}"
    )

    kb_rows = [
        [InlineKeyboardButton(
            text="📢 Перейти в канал",
            url=offer.channel_url
        )],
        [InlineKeyboardButton(
            text="▶️ Участвовать",
            callback_data=f"offer_start:{offer_id}"
        )],
        [InlineKeyboardButton(
            text="✅ Проверить подписку",
            callback_data=f"offer_check:{offer_id}"
        )],
    ]
    if getattr(offer, "is_rentable", False):
        kb_rows.append([InlineKeyboardButton(
            text="📣 Арендовать слот",
            callback_data=f"rent_offer:{offer_id}"
        )])
    kb_rows.append([InlineKeyboardButton(
        text="◀️ Назад",
        callback_data="offers_participation"
    )])

    await callback.message.answer(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("offer_start:"))
async def cb_offer_start(callback: CallbackQuery):
    if not _cooldown_ok(
        _offer_action_last_ts,
        (callback.from_user.id, "offer_start"),
        OFFER_ACTION_COOLDOWN_SECONDS,
    ):
        await callback.answer("⏳ Слишком часто. Попробуйте через пару секунд.", show_alert=True)
        return
    offer_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        part, is_new = await start_offer_participation(session, user.id, offer_id)
        if part is None:
            await callback.answer("Оффер не найден.", show_alert=True)
            return
        if not is_new:
            await callback.answer("Вы уже участвуете!", show_alert=True)
            return
        offer = await get_offer_by_id(session, offer_id)

    paid = to_decimal(part.reward_given)
    cap_note = "" if paid == to_decimal(offer.reward_preview) else "\n⚠️ Сработал дневной лимит наград."
    await callback.answer(
        f"✅ Получено {paid} монет!\n"
        f"Подпишитесь и нажмите «Проверить».{cap_note}",
        show_alert=True
    )


@router.callback_query(F.data.startswith("offer_check:"))
async def cb_offer_check(callback: CallbackQuery):
    if not _cooldown_ok(
        _offer_action_last_ts,
        (callback.from_user.id, "offer_check"),
        OFFER_ACTION_COOLDOWN_SECONDS,
    ):
        await callback.answer("⏳ Слишком часто. Попробуйте через пару секунд.", show_alert=True)
        return
    offer_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        offer = await get_offer_by_id(session, offer_id)
        if not offer:
            await callback.answer("Оффер не найден.", show_alert=True)
            return
        if not await _check_user_offer_subscription(callback, offer):
            await callback.answer(
                "❌ Подписка не найдена. Подпишитесь на канал и попробуйте снова.",
                show_alert=True,
            )
            return
        ok, paid = await verify_offer_subscription(session, user.id, offer_id)
        if ok:
            if paid > 0:
                await callback.answer(
                    f"✅ Подтверждено! Получено {paid} монет!",
                    show_alert=True
                )
            else:
                await callback.answer(
                    "✅ Подписка подтверждена. Награда уже выдана или дневной лимит исчерпан.",
                    show_alert=True
                )
        else:
            await callback.answer(
                "❌ Не удалось подтвердить подписку.",
                show_alert=True
            )


# =========================
# АРЕНДА РЕКЛАМНОГО СЛОТА
# =========================
@router.callback_query(F.data == "offers_rent_list")
async def offers_rent_list(callback: CallbackQuery):
    async with async_session() as session:
        offers = await get_rentable_offers(session)

    if not offers:
        await callback.message.answer(
            "😔 Нет офферов доступных для аренды."
        )
        await callback.answer()
        return

    text = "📣 <b>Аренда рекламных слотов</b>\n\n"
    text += (
        "Арендуйте слот в оффере и рекламируйте свой канал!\n"
        "Ваш канал будет показан всем участникам оффера.\n\n"
        "Выберите оффер:"
    )
    kb_buttons = []
    for o in offers:
        # Rental system is disabled in this build — always show full available slots
        active_count = 0
        slots_left = o.max_simultaneous_rentals - active_count
        kb_buttons.append([InlineKeyboardButton(
            text=(
                f"📣 {o.title[:30]} | "
                f"{o.rent_cost_per_day} монет/день | "
                f"Слотов: {slots_left}/{o.max_simultaneous_rentals}"
            ),
            callback_data=f"rent_offer:{o.id}"
        )])

    kb_buttons.append([InlineKeyboardButton(
        text="◀️ Назад",
        callback_data="btn_offers_back"
    )])

    await callback.message.answer(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    )
    await callback.answer()


@router.callback_query(F.data == "btn_offers_back")
async def btn_offers_back(callback: CallbackQuery):
    # Removed useless DB query - get_active_offers result was never used
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📢 Офферы (участие)",
            callback_data="offers_participation"
        )],
        [InlineKeyboardButton(
            text="📣 Арендовать рекламный слот",
            callback_data="offers_rent_list"
        )],
        [InlineKeyboardButton(
            text="📋 Мои аренды",
            callback_data="my_rentals"
        )],
    ])
    await callback.message.answer(
        "📢 <b>Офферы</b>\n\nВыберите раздел:",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data.startswith("rent_offer:"))
async def rent_offer_start(callback: CallbackQuery, state: FSMContext):
    offer_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        offer = await get_offer_by_id(session, offer_id)
        if not offer or not offer.is_rentable:
            await callback.answer("Аренда недоступна.", show_alert=True)
            return

        active_count = 0  # Rentals system disabled - always 0 slots used
        slots_left = offer.max_simultaneous_rentals - active_count

    if slots_left <= 0:
        await callback.answer(
            "❌ Все слоты заняты. Попробуйте позже.",
            show_alert=True
        )
        return

    await state.set_state(RentOfferState.waiting_channel_title)
    await state.update_data(offer_id=offer_id)
    await callback.message.answer(
        f"📣 <b>Аренда слота в: {offer.title}</b>\n\n"
        f"💰 Стоимость: {offer.rent_cost_per_day} монет/день\n"
        f"Свободных слотов: {slots_left}/{offer.max_simultaneous_rentals}\n\n"
        f"Шаг 1/3: Введите название вашего канала:",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(RentOfferState.waiting_channel_title)
async def rent_channel_title(message: Message, state: FSMContext):
    title = (message.text or "").strip()
    if len(title) < 2 or len(title) > 100:
        await message.answer("❌ Название от 2 до 100 символов.")
        return
    await state.update_data(channel_title=title)
    await state.set_state(RentOfferState.waiting_channel_url)
    await message.answer(
        "Шаг 2/3: Введите ссылку на ваш канал (https://t.me/...):"
    )


@router.message(RentOfferState.waiting_channel_url)
async def rent_channel_url(message: Message, state: FSMContext):
    url = (message.text or "").strip()
    if not (url.startswith("https://t.me/") or url.startswith("t.me/")):
        await message.answer(
            "❌ Ссылка должна начинаться с https://t.me/ или t.me/"
        )
        return
    await state.update_data(channel_url=url)
    await state.set_state(RentOfferState.waiting_days)

    data = await state.get_data()
    offer_id = data.get("offer_id")

    await message.answer(
        f"Шаг 3/3: Выберите количество дней аренды\n"
        f"(от {OFFER_MIN_RENT_DAYS} до {OFFER_MAX_RENT_DAYS}):",
        reply_markup=rent_days_keyboard(offer_id)
    )


@router.callback_query(RentOfferState.waiting_days, F.data.startswith("rent_days:"))
async def rent_days_selected(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    offer_id = int(parts[1])
    days = int(parts[2])

    data = await state.get_data()
    channel_title = data.get("channel_title", "")
    channel_url = data.get("channel_url", "")

    async with async_session() as session:
        offer = await get_offer_by_id(session, offer_id)
        if not offer:
            await callback.answer("Оффер не найден.", show_alert=True)
            await state.clear()
            return

        cost = to_decimal(offer.rent_cost_per_day) * days
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            await state.clear()
            return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"✅ Оплатить {cost} монет",
                callback_data=f"confirm_rent:{offer_id}:{days}"
            ),
            InlineKeyboardButton(
                text="❌ Отмена",
                callback_data=f"rent_offer:{offer_id}"
            ),
        ]
    ])
    await callback.message.answer(
        f"📣 <b>Подтверждение аренды</b>\n\n"
        f"Оффер: {offer.title}\n"
        f"Ваш канал: {channel_title}\n"
        f"Ссылка: {channel_url}\n"
        f"Дней: {days}\n"
        f"Стоимость: <b>{cost} монет</b>\n"
        f"Ваш баланс: {user.balance} монет\n\n"
        f"После оплаты аренда уйдёт на проверку администратору.",
        parse_mode="HTML",
        reply_markup=kb
    )
    await state.update_data(days=days)
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_rent:"))
async def confirm_rent(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    offer_id, days = int(parts[1]), int(parts[2])

    data = await state.get_data()
    channel_title = data.get("channel_title", "")
    channel_url = data.get("channel_url", "")

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            await state.clear()
            return

        rental, error = await create_offer_rental(
            session,
            offer_id=offer_id,
            user_id=user.id,
            channel_title=channel_title,
            channel_url=channel_url,
            rent_days=days,
        )

    if error:
        await callback.message.answer(error)
        await state.clear()
        await callback.answer()
        return

    await callback.message.answer(
        f"✅ <b>Заявка на аренду отправлена!</b>\n\n"
        f"Канал: {channel_title}\n"
        f"Дней: {days}\n"
        f"Стоимость: {rental.cost_paid} монет\n\n"
        f"После одобрения администратором ваш канал будет активен в оффере.\n"
        f"Вы получите уведомление.",
        parse_mode="HTML"
    )
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "my_rentals")
async def my_rentals(callback: CallbackQuery):
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        rentals = await get_user_rentals(session, user.id)

        if not rentals:
            await callback.message.answer(
                "У вас нет аренд.\n"
                "Арендуйте рекламный слот в разделе 📣 Офферы!"
            )
            await callback.answer()
            return

        text = "📋 <b>Мои аренды</b>\n\n"
        for r in rentals:
            offer = await get_offer_by_id(session, r.offer_id)
            offer_name = offer.title if offer else f"#{r.offer_id}"
            status_icon = {
                "pending": "⏳",
                "active": "✅",
                "expired": "⌛",
                "rejected": "❌",
            }.get(r.status, "❓")
            expires = r.expires_at.strftime('%d.%m.%Y') if r.expires_at else "—"
            text += (
                f"{status_icon} {offer_name}\n"
                f"   Канал: {r.renter_channel_title}\n"
                f"   Дней: {r.rent_days} | Стоимость: {r.cost_paid}\n"
                f"   Статус: {r.status} | До: {expires}\n\n"
            )

    if len(text) > 4000:
        text = text[:4000] + "\n..."
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


# =========================
# GAMES (с игровыми сессиями)
# =========================
@router.message(F.text == BTN_GAMES)
async def btn_games(message: Message, state: FSMContext):
    await state.clear()

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if not await require_nickname(message, user):
            return

    await message.answer(
        "🎮 <b>Игровой центр</b>\n\nВыберите раздел:",
        parse_mode="HTML",
        reply_markup=games_menu_keyboard()
    )


@router.callback_query(F.data == "game_pay_session")
async def game_pay_session(callback: CallbackQuery):
    await callback.answer(
        "Продление игровой сессии больше не требуется: в меню остались только Секслото и лутбоксы.",
        show_alert=True,
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


@router.callback_query(F.data == "dice_menu")
async def game_dice(callback: CallbackQuery):
    await callback.answer("Кости отключены. Сейчас основной фокус — Секслото.", show_alert=True)


@router.callback_query(F.data.startswith("dice_bet:"))
async def dice_bet(callback: CallbackQuery):
    await callback.answer("Кости отключены. Сейчас основной фокус — Секслото.", show_alert=True)


@router.callback_query(F.data == "game_coinflip")
async def game_coinflip(callback: CallbackQuery):
    await callback.answer("Орёл/решка отключены. Сейчас основной фокус — Секслото.", show_alert=True)


@router.callback_query(F.data.startswith("coinflip_bet:"))
async def coinflip_bet(callback: CallbackQuery):
    await callback.answer("Орёл/решка отключены. Сейчас основной фокус — Секслото.", show_alert=True)


@router.callback_query(F.data == "guess_menu")
async def game_guess(callback: CallbackQuery):
    await callback.answer("Угадай число отключена. Сейчас основной фокус — Секслото.", show_alert=True)


@router.callback_query(F.data.startswith("guess_bet:"))
async def guess_bet_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("Угадай число отключена. Сейчас основной фокус — Секслото.", show_alert=True)


@router.callback_query(F.data.startswith("guess_num:"))
async def guess_num(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer("Угадай число отключена. Сейчас основной фокус — Секслото.", show_alert=True)


@router.callback_query(F.data == "games_back")
async def games_back(callback: CallbackQuery):
    await callback.message.answer(
        "🎮 Игры:",
        reply_markup=games_menu_keyboard()
    )
    await callback.answer()


# =========================
# TOPS
# =========================
@router.message(F.text == BTN_TOPS)
async def btn_tops(message: Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if not await require_nickname(message, user):
            return
    await message.answer(
        "🏆 <b>Топы</b>",
        parse_mode="HTML",
        reply_markup=tops_menu_keyboard()
    )


@router.callback_query(F.data == "top_uploaders")
async def top_uploaders(callback: CallbackQuery):
    async with async_session() as session:
        rows = (await session.execute(
            select(User, func.count(Video.id).label("cnt"))
            .join(Video, Video.uploader_user_id == User.id)
            .where(Video.status == "approved")
            .group_by(User.id)
            .order_by(desc("cnt"))
            .limit(10)
        )).all()

        text = "🎬 <b>Топ загрузчиков</b>\n\n"
        medals = ["🥇", "🥈", "🥉"]
        seen, rank = set(), 0
        for u, cnt in rows:
            if u.id in seen:
                continue
            seen.add(u.id)
            rank += 1
            icon = medals[rank - 1] if rank <= 3 else f"{rank}."
            name = await get_styled_display_name(session, u)
            text += f"{icon} {name} — {cnt} видео\n"
        if not rows:
            text += "Пусто"
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "top_viewers")
async def top_viewers(callback: CallbackQuery):
    async with async_session() as session:
        rows = (await session.execute(
            select(User, func.count(VideoView.id).label("cnt"))
            .join(VideoView, VideoView.user_id == User.id)
            .group_by(User.id)
            .order_by(desc("cnt"))
            .limit(10)
        )).all()

        text = "👁 <b>Топ зрителей</b>\n\n"
        medals = ["🥇", "🥈", "🥉"]
        seen, rank = set(), 0
        for u, cnt in rows:
            if u.id in seen:
                continue
            seen.add(u.id)
            rank += 1
            icon = medals[rank - 1] if rank <= 3 else f"{rank}."
            name = await get_styled_display_name(session, u)
            text += f"{icon} {name} — {cnt} просмотров\n"
        if not rows:
            text += "Пусто"
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "top_levels")
async def top_levels(callback: CallbackQuery):
    async with async_session() as session:
        users = (await session.execute(
            select(User).order_by(desc(User.xp)).limit(10)
        )).scalars().all()

        text = "⭐ <b>Топ по XP</b>\n\n"
        medals = ["🥇", "🥈", "🥉"]
        seen, rank = set(), 0
        for u in users:
            if u.id in seen:
                continue
            seen.add(u.id)
            rank += 1
            icon = medals[rank - 1] if rank <= 3 else f"{rank}."
            name = await get_styled_display_name(session, u)
            text += f"{icon} {name} — Ур.{u.level} ({u.xp} XP)\n"
        if not users:
            text += "Пусто"
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "top_richest")
async def top_richest(callback: CallbackQuery):
    async with async_session() as session:
        users = (await session.execute(
            select(User).order_by(desc(User.balance)).limit(10)
        )).scalars().all()

        text = "💰 <b>Топ богатых</b>\n\n"
        medals = ["🥇", "🥈", "🥉"]
        seen, rank = set(), 0
        for u in users:
            if u.id in seen:
                continue
            seen.add(u.id)
            rank += 1
            icon = medals[rank - 1] if rank <= 3 else f"{rank}."
            name = await get_styled_display_name(session, u)
            text += f"{icon} {name} — {u.balance:.2f} монет\n"
        if not users:
            text += "Пусто"
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


# =========================
# QUESTS
# =========================
@router.message(F.text == BTN_QUESTS)
async def btn_quests(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "📋 <b>Квесты отключены.</b>\n\n"
        "Мы убрали ежедневные задания, чтобы не захламлять меню и не раздавать лишние монеты.\n"
        "Сейчас основной фокус — Секслото, офферы и рефералка.",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("quest_claim:"))
async def quest_claim(callback: CallbackQuery):
    await callback.answer("Квесты отключены.", show_alert=True)


@router.callback_query(F.data.startswith("quest_done:"))
async def quest_done(callback: CallbackQuery):
    await callback.answer("Квесты отключены.", show_alert=True)


@router.callback_query(F.data.startswith("quest_info:"))
async def quest_info(callback: CallbackQuery):
    await callback.answer("Квесты отключены.", show_alert=True)


# =========================
# HELPER: обновление квестов
# =========================
async def _update_quest_progress(
    session,
    user_id: int,
    quest_type: str,
    amount: int = 1
):
    # Квесты отключены. Оставляем заглушку, чтобы не трогать старые вызовы.
    return


# =========================
# УМНАЯ РЕКЛАМА — FORCED OFFER
# =========================

@router.callback_query(F.data == "forced_offer_wait")
async def forced_offer_wait(callback: CallbackQuery):
    await callback.answer(
        "⏳ Подождите ещё немного...",
        show_alert=False
    )


@router.callback_query(F.data.startswith("forced_offer_continue:"))
async def forced_offer_continue(callback: CallbackQuery):
    offer_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        offer = await get_offer_by_id(session, offer_id)
        if offer:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="✅ Я подписался — получить монеты",
                    callback_data=f"offer_start:{offer_id}"
                )],
                [InlineKeyboardButton(
                    text="▶️ Смотреть видео",
                    callback_data="watch_video_content"
                )],
            ])
            await callback.message.answer(
                f"💡 Кстати, за подписку на <b>{offer.title}</b> "
                f"можно получить <b>{offer.reward_preview} монет</b>!\n"
                f"Хотите заработать?",
                parse_mode="HTML",
                reply_markup=kb
            )
        else:
            await watch_video_content(callback)
            return

    await callback.answer()


@router.callback_query(F.data == "dismiss_low_balance_hint")
async def dismiss_low_balance_hint(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("Хорошо! Офферы всегда доступны в меню 💰")


# =========================
# ЛОТЕРЕЯ-ЛОТО
# =========================
def _lottery_menu_kb() -> InlineKeyboardMarkup:
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from app.config import WEBHOOK_BASE
    base = (WEBHOOK_BASE or "").rstrip("/")
    live_url = f"{base}/lottery/live" if base else ""

    buttons = []
    if live_url:
        from aiogram.types.web_app_info import WebAppInfo
        buttons.append([InlineKeyboardButton(text="🔴 Открыть Live (Mini App)", web_app=WebAppInfo(url=live_url))])
    else:
        buttons.append([InlineKeyboardButton(text="🔴 Как открыть Live", callback_data="lottery_live_info")])

    buttons.extend([
        [InlineKeyboardButton(text="🎫 Купить билет", callback_data="lottery_buy")],
        [InlineKeyboardButton(text="📋 Мои билеты", callback_data="lottery_my_tickets")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="lottery_menu")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _send_lottery_menu(message_or_callback_message: Message, telegram_user_id: int | None = None) -> None:
    if not ENABLE_LOTTERY:
        await message_or_callback_message.answer("⛔ Лотерея временно отключена.")
        return
    async with async_session() as session:
        round_obj = await ensure_current_lottery_round(session)
        state_data = get_lottery_state_dict(round_obj)
        if telegram_user_id is None:
            telegram_user_id = getattr(getattr(message_or_callback_message, "from_user", None), "id", None)
        user = await get_user(session, telegram_user_id) if telegram_user_id else None
    base = (WEBHOOK_BASE or "").rstrip("/")
    live_url = f"{base}/lottery/live" if base else ""
    try:
        draw_line = f"Следующий розыгрыш: <b>{format_time_for_user(round_obj.draw_starts_at, getattr(user, 'timezone', None))}</b>"
    except Exception:
        draw_line = "Следующий розыгрыш скоро стартует в live-режиме."
    await message_or_callback_message.answer(
        "🎰 <b>Лотерея-лото</b>\n\n"
        f"Раунд: <b>{state_data.get('week_key')}</b>\n"
        f"Статус: <b>{state_data.get('status')}</b>\n"
        f"Цена билета: <b>{state_data.get('ticket_price')}</b> монет\n"
        f"Призовой фонд: <b>{state_data.get('prize_pool')}</b> монет\n"
        f"Уже выпало: {', '.join(map(str, state_data.get('drawn_numbers', []))) or '—'}\n\n"
        + (f"🔴 Live-ссылка: <a href=\"{live_url}\">{live_url}</a>\n" if live_url else "")
        + f"{draw_line}\n\n"
        "Нажмите «🔴 Открыть Live», чтобы посмотреть колесо и ход розыгрыша.",
        parse_mode="HTML",
        reply_markup=_lottery_menu_kb(),
    )


@router.message(F.text == BTN_LOTTERY)
async def btn_lottery(message: Message, state: FSMContext):
    await state.clear()
    await _send_lottery_menu(message, message.from_user.id)


@router.callback_query(F.data == "open_lottery")
async def open_lottery_from_games(callback: CallbackQuery):
    await _send_lottery_menu(callback.message, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "lottery_menu")
async def lottery_menu(callback: CallbackQuery):
    if not ENABLE_LOTTERY:
        await callback.answer("⛔ Лотерея отключена.", show_alert=True)
        return
    await _send_lottery_menu(callback.message, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "lottery_buy")
async def lottery_buy(callback: CallbackQuery):
    if not ENABLE_LOTTERY:
        await callback.answer("⛔ Лотерея отключена.", show_alert=True)
        return
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return

        # Admin free — лотерейный билет бесплатно
        admin_free = await is_admin_free_eligible(session, callback.from_user.id, user)
        if admin_free:
            round_obj = await ensure_current_lottery_round(session)
            now = utc_now()
            if round_obj.status != "open" or now >= round_obj.draw_starts_at:
                await callback.answer("Продажа билетов закрыта до следующей недели.", show_alert=True)
                return

            pool = list(range(1, round_obj.numbers_pool + 1))
            pick_count = min(round_obj.numbers_per_ticket, len(pool))
            numbers = sorted(random.sample(pool, k=pick_count))
            from app.services import _serialize_numbers
            ticket = LotteryTicket(
                round_id=round_obj.id,
                user_id=user.id,
                numbers=_serialize_numbers(numbers),
            )
            round_obj.prize_pool += to_decimal(round_obj.ticket_price)
            await log_balance_change(
                session, user, to_decimal(0), "lottery_ticket_admin_free",
                details=f"ADMIN_FREE numbers={ticket.numbers}",
            )
            session.add(ticket)
            await log_user_action(session, user.id, "lottery_admin_free",
                                  f"round={round_obj.week_key}, numbers={ticket.numbers}")
            await session.commit()
            await callback.answer("🆓 Билет куплен бесплатно (ADMIN FREE)!", show_alert=True)
            await callback.message.answer(
                f"🎫 Билет #{ticket.id} куплен (🆓 ADMIN FREE)\n"
                f"Ваши числа: <b>{ticket.numbers}</b>",
                parse_mode="HTML",
            )
            return

        ticket, error = await buy_lottery_ticket(session, user)
        if error:
            await callback.answer(error, show_alert=True)
            return
        await callback.answer("Билет куплен!", show_alert=True)
        await callback.message.answer(
            f"🎫 Билет #{ticket.id} куплен\n"
            f"Ваши числа: <b>{ticket.numbers}</b>",
            parse_mode="HTML",
        )


@router.callback_query(F.data == "lottery_my_tickets")
async def lottery_my_tickets(callback: CallbackQuery):
    if not ENABLE_LOTTERY:
        await callback.answer("⛔ Лотерея отключена.", show_alert=True)
        return
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        round_obj = await get_latest_lottery_round(session)
        tickets = await get_user_lottery_tickets(session, user.id, round_obj.id if round_obj else None, limit=20)
    if not tickets:
        await callback.message.answer("😔 У вас пока нет билетов в текущем раунде.")
        await callback.answer()
        return
    text = "📋 <b>Ваши билеты</b>\n\n"
    for t in tickets:
        text += f"#{t.id}: {t.numbers} | совпадений: {t.matched_count}\n"
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "lottery_live_info")
async def lottery_live_info(callback: CallbackQuery):
    base = (WEBHOOK_BASE or "").rstrip("/")
    live_url = f"{base}/lottery/live" if base else "/lottery/live"
    await callback.message.answer(
        "🔴 <b>Live-розыгрыш</b>\n\n"
        f"Ссылка: {live_url}",
        parse_mode="HTML",
    )
    await callback.answer()


# =========================
# ЖАЛОБЫ И ПРЕДЛОЖЕНИЯ
# =========================
@router.message(F.text == BTN_FEEDBACK)
async def feedback_start(message: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐞 Сообщить о баге", callback_data="feedback_kind:bug")],
        [InlineKeyboardButton(text="💡 Предложить идею", callback_data="feedback_kind:suggestion")],
        [InlineKeyboardButton(text="❤️ Поблагодарить команду", callback_data="feedback_kind:praise")],
    ])
    await message.answer(
        "💬 <b>Жалобы и предложения</b>\n\n"
        "Напишите нам бесплатно: о баге, идее или просто поддержке.\n"
        "Мы читаем все обращения.",
        parse_mode="HTML",
        reply_markup=kb,
    )
    await state.clear()


@router.callback_query(F.data.startswith("feedback_kind:"))
async def feedback_pick_kind(callback: CallbackQuery, state: FSMContext):
    kind = callback.data.split(":", 1)[1]
    kind_title = {
        "bug": "Баг",
        "suggestion": "Идея",
        "praise": "Благодарность",
    }.get(kind)
    if not kind_title:
        await callback.answer("Неизвестный тип обращения.", show_alert=True)
        return
    await state.set_state(FeedbackState.waiting_text)
    await state.update_data(feedback_kind=kind)
    await callback.message.answer(
        f"✍️ Тип: <b>{kind_title}</b>\n\n"
        "Опишите ваше сообщение одним текстом (5-2000 символов).",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(FeedbackState.waiting_text)
async def feedback_submit(message: Message, state: FSMContext):
    text_value = (message.text or "").strip()
    if len(text_value) < 5:
        await message.answer("Сообщение слишком короткое. Минимум 5 символов.")
        return
    if len(text_value) > 2000:
        await message.answer("Сообщение слишком длинное. Максимум 2000 символов.")
        return

    data = await state.get_data()
    kind = data.get("feedback_kind", "suggestion")
    kind_title = {
        "bug": "Баг",
        "suggestion": "Идея",
        "praise": "Благодарность",
    }.get(kind, kind)

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await state.clear()
            return
        feedback = await create_feedback(session, user.id, kind, text_value)
        author_name = get_display_name(user)

    for admin_tg in ADMINS:
        try:
            await message.bot.send_message(
                admin_tg,
                (
                    "💬 <b>Новое обращение пользователя</b>\n\n"
                    f"Тип: <b>{kind_title}</b>\n"
                    f"Обращение: <code>#{feedback.id}</code>\n"
                    f"Пользователь: {author_name}\n"
                    f"TG ID: <code>{message.from_user.id}</code>\n\n"
                    f"{escape(text_value)}"
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    await message.answer(
        "✅ Спасибо! Ваше обращение отправлено команде.\n"
        "Если нужно, мы свяжемся с вами в Telegram."
    )
    await state.clear()


# =========================
# ПРОМОКОДЫ (НОВЫЙ РАЗДЕЛ)
# =========================
@router.message(F.text == BTN_PROMO)
async def btn_promo(message: Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if not await require_nickname(message, user):
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎟 Создать промокод", callback_data="promo_create")],
            [InlineKeyboardButton(text="🔑 Активировать промокод", callback_data="promo_activate")],
            [InlineKeyboardButton(text="🎁 Еженедельная Халява", callback_data="promo_freebie_start")],
            [InlineKeyboardButton(text="📋 Мои промокоды", callback_data="promo_my")],
        ])
        await message.answer(
            "🎟 <b>Промокоды</b>\n\n"
            "Создайте код на монеты и поделитесь с друзьями!\n"
            f"Стоимость создания: {PROMOCODE_CREATION_STAR_RATE} Stars за 1 монету × использования.\n"
            f"VIP: {VIP_FREE_PROMO_PER_MONTH} бесплатный код в месяц.",
            parse_mode="HTML",
            reply_markup=kb
        )


@router.callback_query(F.data == "promo_create")
async def promo_create_start(callback: CallbackQuery, state: FSMContext):
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        await state.set_state(PromoCreateState.waiting_amount)
        await callback.message.answer(
            f"Введите сумму монет (1–{PROMOCODE_MAX_AMOUNT}):"
        )
    await callback.answer()


@router.message(PromoCreateState.waiting_amount)
async def promo_amount(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("Введите число.")
        return
    amount = int(message.text)
    if amount < 1 or amount > PROMOCODE_MAX_AMOUNT:
        await message.answer(f"От 1 до {PROMOCODE_MAX_AMOUNT}.")
        return
    await state.update_data(promo_amount=amount)
    await state.set_state(PromoCreateState.waiting_uses)
    await message.answer(f"Количество использований (1–{PROMOCODE_MAX_USES}):")


@router.message(PromoCreateState.waiting_uses)
async def promo_uses(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("Введите число.")
        return
    uses = int(message.text)
    if uses < 1 or uses > PROMOCODE_MAX_USES:
        await message.answer(f"От 1 до {PROMOCODE_MAX_USES}.")
        return
    await state.update_data(promo_uses=uses)
    await state.set_state(PromoCreateState.waiting_hours)
    await message.answer(f"Срок действия в часах (1–{PROMOCODE_MAX_HOURS}):")


@router.message(PromoCreateState.waiting_hours)
async def promo_hours(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("Введите число.")
        return
    hours = int(message.text)
    if hours < 1 or hours > PROMOCODE_MAX_HOURS:
        await message.answer(f"От 1 до {PROMOCODE_MAX_HOURS}.")
        return
    data = await state.get_data()
    amount = data["promo_amount"]
    uses = data["promo_uses"]
    star_cost = calculate_promocode_star_cost(to_decimal(amount), uses)

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await state.clear()
            return
        admin_free = is_admin_or_super(message.from_user.id, user)
        if admin_free:
            promo, _, error = await create_promocode(session, message.from_user.id,
                                                      to_decimal(amount), uses, hours,
                                                      admin_free=True)
            if error:
                await message.answer(error)
            else:
                await message.answer(
                    f"✅ Промокод создан (админ-режим):\n"
                    f"<code>{promo.code}</code>\n"
                    f"Сумма: {amount} монет, использований: {uses}/{promo.max_uses}\n"
                    f"Ссылка: t.me/{(await message.bot.get_me()).username}?start=promo_{promo.code}",
                    parse_mode="HTML"
                )
            await state.clear()
            return

        # VIP бесплатный
        if is_vip(user) and user.promo_created_this_month < VIP_FREE_PROMO_PER_MONTH:
            promo, cost, error = await create_promocode(session, message.from_user.id,
                                                         to_decimal(amount), uses, hours)
            if error:
                await message.answer(error)
            else:
                await message.answer(
                    f"✅ Бесплатный VIP-промокод:\n"
                    f"<code>{promo.code}</code>\n"
                    f"Сумма: {amount} монет, использований: {uses}\n"
                    f"Осталось бесплатных в этом месяце: {VIP_FREE_PROMO_PER_MONTH - user.promo_created_this_month}",
                    parse_mode="HTML"
                )
            await state.clear()
            return

        # Платный – выставляем инвойс
        discount = await get_stars_discount(session, user.id)
        billed_star_cost = max(1, int(math.ceil(star_cost * (1 - discount)))) if discount > 0 else star_cost
        payload = f"promo_{message.from_user.id}_{amount}_{uses}_{hours}_{uuid.uuid4().hex[:4]}"
        await ensure_payment_pending(
            session,
            user_id=user.id,
            payload=payload,
            stars_amount=billed_star_cost,
        )
        await session.commit()
        await message.answer_invoice(
            title="Создание промокода",
            description=f"{amount} монет × {uses} исп. на {hours}ч",
            payload=payload,
            currency="XTR",
            prices=[LabeledPrice(label="Промокод", amount=billed_star_cost)]
        )
    await state.clear()


@router.callback_query(F.data == "promo_activate")
async def promo_activate_start(callback: CallbackQuery, state: FSMContext):
    if not ENABLE_PROMOCODES:
        await callback.answer("⛔ Промокоды временно отключены.", show_alert=True)
        return
    await state.set_state(PromoActivateState.waiting_code)
    await callback.message.answer("Введите промокод:")
    await callback.answer()


@router.message(PromoActivateState.waiting_code)
async def promo_activate_code(message: Message, state: FSMContext):
    data = await state.get_data()
    is_freebie = data.get("freebie_mode", False)
    
    if is_freebie:
        code_input = (message.text or "").strip().lower()
        current_word = get_current_freebie_word()
        
        if code_input != current_word:
            await message.answer(
                "❌ <b>Неверное секретное слово!</b>\n\n"
                "Убедитесь, что вы правильно списали слово (регистр не важен), или поищите актуальное слово в наших соцсетях!",
                parse_mode="HTML"
            )
            await state.clear()
            return
            
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                await state.clear()
                return
                
            from app.models import utc_now
            current_week = utc_now().isocalendar()[1]
            current_year = utc_now().isocalendar()[0]
            
            if user.last_freebie_week == current_week and user.last_freebie_year == current_year:
                await message.answer("❌ Вы уже забирали Халяву на этой неделе!")
                await state.clear()
                return
                
            import random
            reward_multiplier = random.randint(1, 20)
            reward = Decimal(str(reward_multiplier * 10))
            
            user = await change_balance_atomic(
                session,
                user.id,
                reward,
                "freebie_reward",
                details=f"word={current_word}; week={current_week}"
            ) or user
            user.last_freebie_week = current_week
            user.last_freebie_year = current_year
            await session.commit()
            
        await message.answer(
            f"🎉 <b>Секретное слово угадано!</b>\n\n"
            f"Вам начислено <b>{reward:.0f}</b> монет на баланс!\n"
            f"Приходите в следующий понедельник за новой Халявой! 🎁",
            parse_mode="HTML"
        )
        await state.clear()
        return

    if not ENABLE_PROMOCODES:
        await message.answer("⛔ Промокоды временно отключены.")
        await state.clear()
        return
    if not _cooldown_ok(
        _promo_activate_last_ts,
        message.from_user.id,
        PROMO_ACTIVATE_COOLDOWN_SECONDS,
    ):
        await message.answer("⏳ Слишком часто. Попробуйте чуть позже.")
        return
    code = (message.text or "").strip()
    if not code:
        await message.answer("Введите промокод.")
        return
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await state.clear()
            return
        result = await activate_promocode(session, user.id, code)
        await message.answer(result)
    await state.clear()


@router.callback_query(F.data == "promo_my")
async def promo_my(callback: CallbackQuery):
    if not ENABLE_PROMOCODES:
        await callback.answer("⛔ Промокоды временно отключены.", show_alert=True)
        return
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        promos = (await session.execute(
            select(Promocode).where(Promocode.creator_user_id == user.id)
            .order_by(desc(Promocode.created_at)).limit(10)
        )).scalars().all()
        if not promos:
            await callback.message.answer("📭 У вас пока нет промокодов.")
            await callback.answer()
            return
        text = "🎟 <b>Ваши промокоды:</b>\n\n"
        for p in promos:
            status = "✅" if p.is_active else "❌"
            text += (
                f"{status} <code>{p.code}</code>\n"
                f"Сумма: {p.coin_amount} | Исп: {p.used_count}/{p.max_uses}\n"
                f"До: {p.expires_at.strftime('%d.%m %H:%M') if p.expires_at else '∞'}\n\n"
            )
        await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.message(Command("health"))
async def cmd_health(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        admin_flag = is_admin_or_super(message.from_user.id, user)
    if not admin_flag:
        return
    await message.answer(
        "✅ Health OK\n"
        f"• time_utc: {utc_now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        "• db: connected\n"
        "• bot: running",
    )


@router.message(Command("version"))
async def cmd_version(message: Message):
    version = "3.3.0"
    changes = (
        f"🔥 <b>Версия:</b> {version}\n\n"
        "<b>Последние изменения:</b>\n"
        "• Секслото переведено на настраиваемый интервал и длительность розыгрыша через админку\n"
        "• Mini App синхронизируется с настройками розыгрыша и снова умеет покупать билеты/монеты\n"
        "• Исправлены ставки в Mini App: теперь это реальная ставка на 10 монет, а не бесплатный клик\n"
        "• Добавлены локальные часовые пояса в уведомлениях о розыгрыше\n"
        "• Новичкам показывается стартовый лутбокс\n"
        "• При нехватке монет бот агрессивно подсказывает реферальную ссылку\n"
        "• Ежедневные квесты и ежедневный бонус окончательно убраны из актуального UX"
    )
    await message.answer(changes, parse_mode="HTML")


@router.message(Command("selfcheck"))
async def cmd_selfcheck(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        admin_flag = is_admin_or_super(message.from_user.id, user)
        if not admin_flag:
            return
        items = await run_selfcheck(session)
    await message.answer(format_selfcheck_report(items))





# ════════════════════════════════════════════════
#  ЖАЛОБЫ НА ВИДЕО
# ════════════════════════════════════════════════

class ReportState(StatesGroup):
    picking_reason = State()
    writing_comment = State()


@router.callback_query(F.data.startswith("report_video:"))
async def report_video_start(callback: CallbackQuery, state: FSMContext):
    video_id = int(callback.data.split(":")[1])
    await state.set_state(ReportState.picking_reason)
    await state.update_data(report_video_id=video_id)

    kb_rows = []
    for key, label in REPORT_REASONS.items():
        kb_rows.append([InlineKeyboardButton(text=label, callback_data=f"report_reason:{key}")])
    kb_rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="report_cancel")])

    await callback.message.answer(
        "🚨 <b>Пожаловаться на видео</b>\n\nВыберите причину:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
    )
    await callback.answer()


@router.callback_query(ReportState.picking_reason, F.data.startswith("report_reason:"))
async def report_reason_picked(callback: CallbackQuery, state: FSMContext):
    reason = callback.data.split(":")[1]
    await state.update_data(report_reason=reason)
    await state.set_state(ReportState.writing_comment)
    await callback.message.answer(
        "💬 Опишите проблему (или отправьте «-» чтобы пропустить):",
    )
    await callback.answer()


@router.message(ReportState.writing_comment)
async def report_comment(message: Message, state: FSMContext):
    data = await state.get_data()
    video_id = data.get("report_video_id")
    reason = data.get("report_reason")

    if not video_id or not reason:
        await state.clear()
        return

    comment = None if message.text.strip() == "-" else message.text.strip()

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await state.clear()
            return

        report = await create_video_report(
            session, user.id, video_id, reason, comment,
        )

    await state.clear()

    if report:
        # Запланировать уведомление админам
        async with async_session() as session:
            await schedule_mod_notification(session, "report")
        await message.answer("✅ Жалоба отправлена. Администрация разберётся.")
    else:
        await message.answer("❌ Не удалось отправить жалобу (возможно, вы уже жаловались на это видео).")


@router.callback_query(ReportState.picking_reason, F.data == "report_cancel")
async def report_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Жалоба отменена.")
    await callback.answer()


# ====================================================
# ЕЖЕДНЕВНЫЙ БОНУС, ЛОТЕРЕЯ, ПРОМОКОДЫ ТЕМПЛЕЙТЫ И ХАЛЯВА
# ====================================================
@router.message(F.text == BTN_FAQ)
async def btn_faq(message: Message, state: FSMContext):
    await state.clear()
    
    faq_text = (
        "ℹ️ <b>Часто задаваемые вопросы (FAQ) и Помощь</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>1. Как зарабатывать монеты?</b>\n"
        "Загружайте видео (+30 монет) или фото (+15 монет), выполняйте офферы и приглашайте друзей по реферальной ссылке.\n\n"
        "<b>2. Как смотреть контент других авторов?</b>\n"
        "Нажмите кнопку 🎬 Смотреть и выберите интересующий формат.\n\n"
        "<b>3. Что дает подписка VIP?</b>\n"
        "Удвоенные награды за просмотры, скидки в магазине и бонусы в экономике.\n\n"
        "<b>4. Что такое Секслото?</b>\n"
        "Это главный азартный режим бота: покупайте билеты, следите за live-розыгрышем в Mini App и ловите джекпот.\n\n"
        "<b>5. Как общаться с ИИ?</b>\n"
        "Нажмите кнопку 💋 ИИ-Общение. Одно сообщение стоит 5 монет.\n\n"
        "<b>6. Как работают промокоды?</b>\n"
        "Вы можете создавать промокоды за Stars, активировать чужие и забирать еженедельную халяву.\n\n"
        "<b>7. Как работает реферальная система?</b>\n"
        f"Откройте раздел 👥 Рефералы, скопируйте свою ссылку и отправьте друзьям. За активного приглашённого вы получаете <b>+{REFERRAL_REWARD_INVITER}</b> монет.\n\n"
        "<b>8. Есть ли ежедневный бонус?</b>\n"
        "Нет. Ежедневная халява отключена — вместо неё теперь работает еженедельный секретный промокод.\n\n"
        "<b>9. Есть ли квесты?</b>\n"
        "Нет. Ежедневные квесты убраны из актуального UX, чтобы не захламлять меню.\n\n"
        "<b>10. Где посмотреть топы игроков?</b>\n"
        "В меню 🏆 Топы собраны лучшие авторы контента и самые богатые игроки.\n\n"
        "<b>11. Что находится внутри лутбоксов?</b>\n"
        "Случайный выигрыш монет разной степени редкости.\n\n"
        "<b>12. Как сменить никнейм?</b>\n"
        "В вашем Профиле. Первая установка ника бесплатна, последующие изменения — за монеты.\n\n"
        "<b>13. Что такое Уровень и XP?</b>\n"
        "За активность вы получаете XP. Повышение уровня открывает приятную косметику и прогресс профиля.\n\n"
        "<b>14. Безопасны ли мои данные?</b>\n"
        "Бот не просит лишние персональные данные: используется в основном Telegram ID и сервисная информация профиля.\n\n"
        "<b>15. Как связаться с техподдержкой?</b>\n"
        "Нажмите кнопку 💬 Жалобы и предложения и отправьте сообщение команде."
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Версия бота и Изменения", callback_data="bot_version_info")]
    ])
    
    await message.answer(faq_text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data == "bot_version_info")
async def cb_bot_version_info(callback: CallbackQuery):
    from app.services import is_admin_or_super
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        admin_flag = is_admin_or_super(callback.from_user.id, user)
        
    version_text = (
        "🤖 <b>ИНФОРМАЦИЯ О ВЕРСИИ И ИЗМЕНЕНИЯХ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "• <b>Текущая версия:</b> <code>v3.3.0-stable</code>\n"
        "• <b>Статус:</b> Актуальная боевая сборка\n\n"
        "📢 <b>Последние изменения для пользователей:</b>\n"
        "✅ <b>Секслото:</b> теперь время розыгрышей настраивается из админки и корректно показывается в Mini App.\n"
        "✅ <b>Mini App:</b> внутри live-интерфейса снова работают покупка билетов и покупка монет за Telegram Stars.\n"
        "✅ <b>Часовые пояса:</b> бот учитывает локальное время пользователя и пишет его в напоминаниях о розыгрыше.\n"
        "✅ <b>Стартовый лутбокс:</b> новичок получает приветственный лутбокс с круглой наградой от 50 до 400 монет.\n"
        "✅ <b>Рефералка:</b> при нехватке монет бот теперь сразу подсовывает готовую реферальную ссылку.\n"
        "✅ <b>Халява:</b> ежедневный бонус убран, вместо него работает еженедельный секретный промокод.\n"
        "✅ <b>Квесты и старые мини-игры:</b> в актуальном UX больше не продвигаются и не засоряют интерфейс.\n"
    )
    
    if admin_flag:
        version_text += (
            "\n👑 <b>Административный список изменений:</b>\n"
            "⚙️ <b>Секслото из Telegram:</b> интервал и длительность розыгрыша редактируются в админке без правки кода.\n"
            "⚙️ <b>День weekly promo:</b> выбор дня недели переведён на удобные кнопки ПН–ВС.\n"
            "⚙️ <b>Startup cleanup:</b> убран дублирующий startup-flow, который мог ломать запуск приложения.\n"
            "⚙️ <b>Mini App API:</b> исправлены серверные эндпоинты покупки билетов и ставок.\n"
            "⚙️ <b>Changelog:</b> системный файл истории изменений в корне проекта поддерживается в актуальном состоянии."
        )
        
    await callback.message.answer(version_text, parse_mode="HTML")
    await callback.answer()


# ====================================================
# ХАЛЯВА (ЕЖЕНЕДЕЛЬНЫЕ СЕКРЕТНЫЕ СЛОВА)
# ====================================================
FREEBIE_WORDS = [
    "алмаз", "корона", "призма", "монета", "руна", "катана", "сакура", "дракон", "один", "тор",
    "локи", "анубис", "сфинкс", "пирамида", "фараон", "клеопатра", "цезарь", "сенат", "гладиатор", "колизей",
    "спарта", "леонид", "афины", "олимп", "зевс", "гермес", "аид", "посейдон", "феникс", "пегас",
    "грифон", "кентавр", "спрут", "кракен", "комет", "астероид", "галактика", "небула", "квазар", "пульсар",
    "орбита", "спутник", "телескоп", "космонавт", "шаттл", "ракета", "марс", "юпитер", "сатурн", "уран",
    "нептун", "плутон", "халява"
]

def get_current_freebie_word() -> str:
    from app.models import utc_now
    week = utc_now().isocalendar()[1]
    idx = (week - 1) % 53
    return FREEBIE_WORDS[idx]


@router.callback_query(F.data == "promo_freebie_start")
async def cb_promo_freebie_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(
        "🎁 <b>Еженедельная халява</b>\n\n"
        "Теперь она работает через автоматическую рассылку секретного промокода.\n"
        "Бот сам пришлёт код в заданный день и час — вам останется только активировать его через <b>/start promo_...</b> или в разделе <b>🔑 Активировать промокод</b>.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔑 Активировать промокод", callback_data="promo_activate")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="btn_promo_back")],
        ])
    )
    await callback.answer()


@router.callback_query(F.data == "btn_promo_back")
async def cb_btn_promo_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    # Call main promo menu
    from aiogram.types import Message as TGMessage
    await btn_promo(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "welcome_lootbox_claim")
async def welcome_lootbox_claim(callback: CallbackQuery):
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            return
        from app.models import UserActionLog
        from sqlalchemy import select
        already_claimed = (await session.execute(select(UserActionLog).where(UserActionLog.user_id == user.id, UserActionLog.action == "welcome_lootbox"))).scalars().first()
        if already_claimed:
            await callback.answer("Вы уже открыли свой стартовый лутбокс!", show_alert=True)
            try:
                await callback.message.delete()
            except:
                pass
            return
        from app.services import change_balance_atomic
        import random
        reward = random.choice(range(50, 410, 10))
        await change_balance_atomic(session, user.id, Decimal(reward), "welcome_lootbox")
        log = UserActionLog(user_id=user.id, action="welcome_lootbox", details=f"Reward: {reward}")
        session.add(log)
        await session.commit()
        await session.refresh(user)
        msg_cap = "🎁 <b>СТАРТОВЫЙ ЛУТБОКС ОТКРЫТ!</b>\n\nТебе выпало <b>+" + str(reward) + " монет</b>! 🤑\nТеперь твой баланс: <b>" + str(user.balance) + "</b>.\n\nЭтого хватит, чтобы насладиться контентом — скорее жми '🎬 Смотреть'!"
        try:
            if getattr(callback.message, "caption", None):
                await callback.message.edit_caption(caption=msg_cap, parse_mode="HTML")
            else:
                await callback.message.edit_text(msg_cap, parse_mode="HTML")
        except Exception:
            await callback.message.answer(msg_cap, parse_mode="HTML")
        await callback.answer(f"+{reward} монет!", show_alert=True)
