from html import escape
import os
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
    InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
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
    VIP_PRICE_STARS, VIP_DURATION_DAYS, VIP_BONUS_MULTIPLIER, VIP_WATCH_DISCOUNT,
    LEVEL_XP_BASE, LEVEL_XP_MULTIPLIER,
    DAILY_QUESTS, PREMIUM_DAILY_QUESTS,
    COMMENTS_PER_10_MIN,
    NICKNAME_CHANGE_COST, NICKNAME_MIN_LENGTH, NICKNAME_MAX_LENGTH,
    OFFER_MIN_RENT_DAYS, OFFER_MAX_RENT_DAYS,
    REFERRAL_REWARD_INVITER, REFERRAL_REWARD_NEW_USER, REFERRAL_MILESTONES, DAILY_PHOTO_LIMIT,
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
    AI_ASSISTANT_PRICE, LOTTERY_DRAW_HOUR_MSK, LOTTERY_SECONDS_PER_BALL,
)
from app.db import async_session
from app.models import (
    User, Video, VideoView, Comment, ContentReaction,
    DailyQuestProgress, GameHistory, Offer, Payment, Promocode,
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
    get_active_offers, get_offer_by_id, get_rentable_offers,
    start_offer_participation, verify_offer_subscription, is_offer_available,
    create_offer_rental, get_user_rentals, count_reserved_rentals,
    get_active_rentals_for_offer, normalize_telegram_url,
    change_balance_atomic, log_user_action, to_decimal,
    set_display_name, get_display_name, get_styled_display_name, log_balance_change,
    has_valid_nickname,
    can_play_free_game, pay_for_game_session, increment_game_played,
    get_or_create_game_session,
    check_daily_photo_limit,
    create_promocode, activate_promocode,
    calculate_promocode_star_cost,
    create_feedback, process_referral_reward,
    ensure_current_lottery_round, buy_lottery_ticket, buy_lottery_tickets,
    get_latest_lottery_round, get_user_lottery_tickets, get_weekly_lottery_leaderboard, get_lottery_state_dict,
    get_lottery_draw_duration_seconds, get_lottery_max_tickets_for_balance,
    LOTTERY_MAX_TICKETS_PER_PURCHASE,
    classify_offer_url, notify_admins,
    is_admin_or_super, is_admin_free_eligible,
    should_show_low_balance_hint, mark_low_balance_hint_shown,
    can_show_offer_to_user, mark_offer_shown,
    get_random_active_offer, open_lootbox_for_stars,
    get_current_prices, get_active_events,
    should_show_ad_after_video, increment_video_watched, reset_ad_counter,
    create_video_report, schedule_mod_notification, REPORT_REASONS,
    block_user,
)
from app.selfcheck import run_selfcheck, format_selfcheck_report
from app.keyboards import (
    main_menu,
    video_rating_keyboard, photo_actions_keyboard,
    watch_choice_keyboard, buy_coins_keyboard, vip_buy_keyboard,
    offers_list_keyboard, games_menu_keyboard,
    tops_menu_keyboard,
    reaction_menu_keyboard,
    low_balance_offer_keyboard,
    video_error_keyboard, photo_error_keyboard, photo_limit_reached_keyboard,
    rent_days_keyboard,
    BTN_WATCH, BTN_UPLOAD, BTN_PROFILE, BTN_BUY,
    BTN_OFFERS, BTN_REFERRALS, BTN_ADMIN,
    BTN_GAMES, BTN_TOPS, BTN_VIP, BTN_LEVEL,
    BTN_PROMO, BTN_FEEDBACK, BTN_LOTTERY, BTN_RULES, BTN_FAQ, BTN_AI,
)
from app.user_offer_handlers import user_offers_menu
from app.logger import get_logger
from app.release_notes import build_version_text
from app.rules_text import FULL_RULES_TEXT, SHORT_RULES_TEXT
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
                await message.answer("🚫 Доступ к боту для тебя заблокирован.")
                return
            result = await activate_promocode(session, user.id, promo_code)
            await message.answer(result)
            if not user.agreed_to_rules:
                from app.keyboards import rules_keyboard
                await message.answer(
                    SHORT_RULES_TEXT,
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
            await message.answer("🚫 Доступ к боту для тебя заблокирован.")
            return

        if is_new:
            try:
                username_line = f"Username: @{escape(message.from_user.username)}\n" if message.from_user.username else ""
                ref_line = f"Реф-код: <code>{escape(referral_code)}</code>\n" if referral_code else ""
                await notify_admins(
                    message.bot,
                    f"🆕 <b>Новый пользователь</b>\n"
                    f"ID: <code>{message.from_user.id}</code>\n"
                    f"{username_line}"
                    f"{ref_line}"
                    f"Имя: {escape(message.from_user.first_name or '—')}",
                )
            except Exception:
                pass

        if not user.agreed_to_rules:
            from app.keyboards import rules_keyboard
            await message.answer(
                SHORT_RULES_TEXT,
                parse_mode="HTML",
                reply_markup=rules_keyboard()
            )
            return

        if not has_valid_nickname(user):
            needs_fix = bool(user.nickname_set and user.display_name)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="✏️ Сменить ник" if needs_fix else "✏️ Установить ник",
                    callback_data="set_nickname_start"
                )]
            ])
            from app.config import NICKNAME_MIN_LENGTH, NICKNAME_MAX_LENGTH
            if needs_fix:
                await message.answer(
                    "👋 С возвращением!\n\n"
                    "⚠️ У тебя недопустимый ник (например <code>User&lt;id&gt;</code>).\n"
                    "Нужно поставить <b>нормальный ник</b> — это бесплатно.\n\n"
                    f"• От {NICKNAME_MIN_LENGTH} до {NICKNAME_MAX_LENGTH} символов\n"
                    f"• Только буквы (рус/лат), цифры, _ и -\n"
                    f"• Без точек, пробелов, ? и спецсимволов\n"
                    f"• Нельзя User&lt;id&gt;",
                    parse_mode="HTML",
                    reply_markup=kb
                )
            else:
                await message.answer(
                    "👋 Добро пожаловать!\n\n"
                    "⚠️ Перед началом нужно установить нормальный ник.\n"
                    f"Первая установка бесплатна!\n"
                    f"• От {NICKNAME_MIN_LENGTH} до {NICKNAME_MAX_LENGTH} символов\n"
                    f"• Только буквы (рус/лат), цифры, _ и -\n"
                    f"• Без точек, пробелов, ? и спецсимволов\n"
                    f"• Нельзя User&lt;id&gt;",
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
    meta = classify_offer_url(channel_url)
    if not meta.get("auto_verify"):
        return None
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


class LotteryBuyState(StatesGroup):
    waiting_quantity = State()


class StylesCaseState(StatesGroup):
    configuring = State()


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
    """Проверяет наличие нормального ника. False = ник не задан/невалидный."""
    if has_valid_nickname(user):
        return True
    needs_fix = bool(user.nickname_set and user.display_name)
    title = (
        "⚠️ <b>Нужно сменить ник на нормальный!</b>"
        if needs_fix
        else "⚠️ <b>Необходимо установить ник!</b>"
    )
    extra = (
        "\nНик вида <code>User&lt;id&gt;</code>, точки, ? и слишком короткие ники запрещены."
        if needs_fix
        else ""
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✏️ Сменить ник" if needs_fix else "✏️ Установить ник",
            callback_data="set_nickname_start"
        )]
    ])
    await message.answer(
        f"{title}\n\n"
        f"• От {NICKNAME_MIN_LENGTH} до {NICKNAME_MAX_LENGTH} символов\n"
        f"• Только буквы (рус/лат), цифры, _ и -\n"
        f"• Без точек, пробелов, ? и спецсимволов\n"
        f"• Уникальный, не User&lt;id&gt;{extra}\n\n"
        f"Первая установка / замена недопустимого ника — бесплатно!\n"
        f"Обычная смена ника стоит {NICKNAME_CHANGE_COST} монет.",
        parse_mode="HTML",
        reply_markup=kb
    )
    return False


def _fmt_coins(value) -> str:
    amount = to_decimal(value)
    if amount == amount.to_integral_value():
        return f"{amount:,.0f}".replace(',', ' ')
    return f"{amount:,.2f}".replace(',', ' ')


def _build_referral_milestone_text(refs: int) -> str:
    milestones = sorted((int(level), cfg) for level, cfg in REFERRAL_MILESTONES.items())
    completed = []
    next_goal = None
    for level, cfg in milestones:
        if refs >= level:
            completed.append(f"• {level} друзей — {_fmt_coins(cfg.get('amount', 0))} монет")
        elif next_goal is None:
            next_goal = (level, cfg)
    text = ""
    if completed:
        text += "\n\n🏁 <b>Открытые этапы:</b>\n" + "\n".join(completed[-3:])
    if next_goal:
        need_more = max(0, next_goal[0] - refs)
        text += (
            f"\n\n🎯 <b>Следующая цель:</b> {next_goal[0]} друзей\n"
            f"Награда: <b>{_fmt_coins(next_goal[1].get('amount', 0))}</b> монет\n"
            f"Осталось пригласить: <b>{need_more}</b>"
        )
    return text


def _suggest_viewer_pack(packs: dict, *, need: Decimal | None = None) -> dict | None:
    priority = ["pack_50", "pack_100", "pack_200"]
    ordered = [packs[p] for p in priority if p in packs]
    if not ordered:
        ordered = list(packs.values())
    if not ordered:
        return None
    if need is None:
        return ordered[0]
    need_value = float(need)
    for pack in ordered:
        if float(pack.get("coins", 0)) >= need_value:
            return pack
    return ordered[-1]


async def _notify_admins_about_first_payment(bot, user: User, *, stars: int, payload: str) -> None:
    try:
        await notify_admins(
            bot,
            f"💳 <b>Первая успешная оплата</b>\n"
            f"Пользователь: <code>{user.telegram_id}</code>\n"
            f"Ник: {escape(user.display_name or user.username or '—')}\n"
            f"Stars: <b>{stars}</b>\n"
            f"Payload: <code>{escape(payload)}</code>",
        )
    except Exception:
        pass


async def _is_first_paid_payment(session, user_id: int) -> bool:
    paid_count = (await session.execute(
        select(func.count(Payment.id)).where(Payment.user_id == user_id, Payment.status == "paid")
    )).scalar_one()
    return int(paid_count or 0) == 1


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
                f"🎉 Поздравляем! Ты достиг уровня <b>{new_level}</b>!",
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
        # Первая установка или замена placeholder/невалидного ника — бесплатно
        is_free = (not user.nickname_set) or (not has_valid_nickname(user))
        cost_text = "бесплатно" if is_free else f"{NICKNAME_CHANGE_COST} монет"

    await state.set_state(NicknameState.waiting_nickname)
    await callback.message.answer(
        f"✏️ Введи ник ({cost_text}):\n\n"
        f"• От {NICKNAME_MIN_LENGTH} до {NICKNAME_MAX_LENGTH} символов\n"
        f"• Буквы (рус/лат), цифры, _ или -\n"
        f"• Без точек, пробелов, ? и спецсимволов\n"
        f"• Нельзя User&lt;id&gt; и ник только из цифр"
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
            "Забери бесплатный стартовый лутбокс. Внутри — красивое круглое число от 50 до 400 монет.\n"
            "Это твой приветственный бонус на старт!",
            parse_mode="HTML",
            reply_markup=lootbox_kb,
        )


@router.callback_query(F.data == "show_full_rules")
async def show_full_rules_callback(callback: CallbackQuery):
    await callback.message.answer(FULL_RULES_TEXT, parse_mode="HTML")
    await callback.answer()


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

        # If user already has a valid nickname, show main menu immediately while session is still alive.
        if has_valid_nickname(user):
            await send_welcome_banner(callback, session, user)
            await callback.answer()
            return

    needs_fix = bool(user.nickname_set and user.display_name)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✏️ Сменить ник" if needs_fix else "✏️ Установить ник",
            callback_data="set_nickname_start"
        )]
    ])
    await callback.message.answer(
        "✅ Правила приняты!\n\n"
        + (
            "У тебя недопустимый ник — поставь нормальный. Это бесплатно.\n"
            if needs_fix else
            "Теперь установи нормальный ник. Первая установка бесплатна.\n"
        )
        + f"• От {NICKNAME_MIN_LENGTH} до {NICKNAME_MAX_LENGTH} символов\n"
        + f"• Только буквы (рус/лат), цифры, _ и -\n"
        + f"• Без точек, пробелов, ? и спецсимволов\n"
        + f"• Нельзя User&lt;id&gt;",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


# =========================
# ADMIN REDIRECT
# =========================
@router.callback_query(F.data == "btn_main_menu")
async def cb_main_menu(callback: CallbackQuery):
    """Возвращает пользователя из inline-меню к главному меню бота."""
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        admin_flag = is_any_admin(callback.from_user.id, user)
    await callback.message.answer(
        "🏠 <b>Главное меню</b>\n\nВыбери нужный раздел:",
        parse_mode="HTML",
        reply_markup=main_menu(is_admin=admin_flag),
    )
    await callback.answer()


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
@router.message(F.text == BTN_RULES)
async def show_rules(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(FULL_RULES_TEXT, parse_mode="HTML")


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

            vip_discount = VIP_WATCH_DISCOUNT
            db_vip_discount = await get_setting(session, "vip_watch_discount", "")
            if db_vip_discount:
                try:
                    vip_discount = float(db_vip_discount)
                except (TypeError, ValueError):
                    pass
            vip_discount_percent = max(0, min(100, round((1 - vip_discount) * 100)))

            if is_vip(user):
                await message.answer(
                    f"👑 <b>Ты VIP!</b>\n\n"
                    f"До: <b>{user.vip_until.strftime('%d.%m.%Y %H:%M')}</b>\n\n"
                    f"Привилегии:\n"
                    f"• Множитель монет x{VIP_BONUS_MULTIPLIER}\n"
                    f"• Скидка {vip_discount_percent}% на просмотр\n"
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
                    f"• Скидка {vip_discount_percent}% на просмотр\n"
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

        vip_discount = VIP_WATCH_DISCOUNT
        db_vip_discount = await get_setting(session, "vip_watch_discount", "")
        if db_vip_discount:
            try:
                vip_discount = float(db_vip_discount)
            except (TypeError, ValueError):
                pass
        vip_discount_percent = max(0, min(100, round((1 - vip_discount) * 100)))

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
            f"• Скидка {vip_discount_percent}% на просмотр\n"
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
            await message.answer("🚫 Доступ к боту для тебя заблокирован.")
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
                missing = max(to_decimal(cost) - to_decimal(user.balance), Decimal("0"))
                _, packs, _ = await get_current_prices(session, user.id)
                suggested_pack = _suggest_viewer_pack(packs, need=missing + to_decimal(cost * 8))
                suggested_text = ""
                if suggested_pack:
                    approx_views = int(float(suggested_pack.get("coins", 0)) // max(float(cost), 1.0))
                    suggested_text = (
                        f"\n⚡ <b>Быстрый вариант:</b> {suggested_pack['coins']} монет за {suggested_pack['stars']} Stars"
                        f" — хватит примерно на <b>{approx_views}</b> просмотров."
                    )
                if await should_show_low_balance_hint(session, user):
                    await mark_low_balance_hint_shown(session, user.id)
                    await callback.message.answer(
                        f"💸 <b>Монет не хватает</b>\n\n"
                        f"Для просмотра нужно: <b>{_fmt_coins(cost)}</b> монет\n"
                        f"У тебя сейчас: <b>{_fmt_coins(user.balance)}</b> монет\n"
                        f"Не хватает: <b>{_fmt_coins(missing)}</b> монет\n"
                        f"{suggested_text}\n\n"
                        f"Что можно сделать прямо сейчас:\n"
                        f"• <b>пополнить баланс</b> и сразу вернуться к просмотру\n"
                        f"• <b>взять оффер</b> и быстро добрать монеты\n"
                        f"• <b>позвать друга</b> и получить <b>+{_fmt_coins(REFERRAL_REWARD_INVITER)}</b> монет\n\n"
                        f"Твоя ссылка:\n<code>{ref_link}</code>",
                        parse_mode="HTML",
                        reply_markup=low_balance_offer_keyboard()
                    )
                else:
                    await callback.message.answer(
                        f"❌ <b>Недостаточно монет.</b>\n\n"
                        f"Нужно: <b>{_fmt_coins(cost)}</b>, у тебя: <b>{_fmt_coins(user.balance)}</b>."
                        f"{suggested_text}\n\n"
                        f"Реферальная ссылка:\n<code>{ref_link}</code>",
                        parse_mode="HTML",
                        reply_markup=low_balance_offer_keyboard(),
                    )
                return

            # Обычный показ видео (с безопасной отправкой и возвратом при ошибке)
            # Пытаемся несколько раз: бракованное видео не значит, что следующее такое же.
            last_send_error: str | None = None
            videos_tried = 0
            for _ in range(5):
                video = await get_random_video_for_user(session, user.id)
                if not video:
                    break

                videos_tried += 1
                ok = await record_view_and_charge_with_cost(session, user.id, video.id, cost)
                if not ok:
                    # Списание не прошло (гонка баланса / уже просмотрено) — не тупик:
                    # даём понятное объяснение и кнопку продолжить.
                    await callback.message.answer(
                        "⚠️ <b>Не удалось начать просмотр.</b>\n\n"
                        "Возможно, баланс изменился или это видео уже просмотрено.\n"
                        "Нажми кнопку ниже — попробуем другое видео.",
                        parse_mode="HTML",
                        reply_markup=video_error_keyboard(),
                    )
                    return

                try:
                    uploader = await get_user_by_id(session, video.uploader_user_id)
                    uploader_name = await get_styled_display_name(session, uploader) if uploader else "Автор"

                    await callback.message.answer_video(
                        video.telegram_file_id,
                        caption=(
                            f"🎬 Видео #{video.id}\n"
                            f"👤 Автор: <b>{uploader_name}</b>\n"
                            f"💰 Списано: {cost} монет"
                        ),
                        parse_mode="HTML",
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

            # Цикл завершился без удачной отправки. Техническую ошибку прячем
            # в лог (она непонятна пользователю), а человеку показываем понятный
            # текст и ВСЕГДА — кнопки продолжения.
            if last_send_error:
                logger.warning(
                    "watch_video_content: %d видео не отправилось, last_error=%s",
                    videos_tried, last_send_error,
                )
                await callback.message.answer(
                    "😵‍💫 <b>Несколько видео подряд не удалось показать.</b>\n\n"
                    "Это временный сбой, проблемные ролики мы уже пометили.\n"
                    "Следующее видео может быть совершенно рабочим — попробуйте ещё раз!",
                    parse_mode="HTML",
                    reply_markup=video_error_keyboard(),
                )
            else:
                await callback.message.answer(
                    "😔 <b>Пока нет новых видео для вас.</b>\n\n"
                    "Доступный контент закончился!\n"
                    "Загрузи своё видео (кнопка 📤 Загрузить в меню), чтобы другие тоже смотрели.\n"
                    "А пока можно посмотреть фото.",
                    parse_mode="HTML",
                    reply_markup=video_error_keyboard(),
                )
    except Exception:
        logger.exception("watch_video_content failed")
        try:
            await callback.message.answer(
                "🛠 <b>Не получилось показать видео.</b>\n\n"
                "Произошёл кратковременный сбой — это не значит, что видео нет.\n"
                "Попробуй ещё раз, следующее должно открыться нормально.",
                parse_mode="HTML",
                reply_markup=video_error_keyboard(),
            )
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
                f"💰 За подписку получи <b>{offer.reward_preview} монет</b>!"
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
                        f"📸 <b>Дневной лимит фото исчерпан ({DAILY_PHOTO_LIMIT} шт.).</b>\n\n"
                        f"👑 VIP-пользователи смотрят фото без ограничений.\n"
                        f"А видео можно смотреть без лимита — переходите туда!",
                        parse_mode="HTML",
                        reply_markup=photo_limit_reached_keyboard(),
                    )
                    return

            last_send_error: str | None = None
            photos_tried = 0
            for _ in range(5):
                photo = await get_random_photo_for_user(session, user.id)
                if not photo:
                    break
                photos_tried += 1
                try:
                    uploader = await get_user_by_id(session, photo.uploader_user_id)
                    uploader_name = await get_styled_display_name(session, uploader) if uploader else "Автор"

                    await callback.message.answer_photo(
                        photo.telegram_file_id,
                        caption=(
                            f"🖼 Фото #{photo.id}\n"
                            f"👤 Автор: <b>{uploader_name}</b>"
                        ),
                        parse_mode="HTML",
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

            # Цикл завершился без удачной отправки: понятный текст + кнопки выхода.
            if last_send_error:
                logger.warning(
                    "watch_photo_content: %d фото не отправилось, last_error=%s",
                    photos_tried, last_send_error,
                )
                await callback.message.answer(
                    "😵‍💫 <b>Несколько фото подряд не удалось показать.</b>\n\n"
                    "Временный сбой — мы пометили проблемные фото.\n"
                    "Следующее может открыться нормально, попробуйте ещё раз!",
                    parse_mode="HTML",
                    reply_markup=photo_error_keyboard(),
                )
            else:
                await callback.message.answer(
                    "😔 <b>Пока нет новых фото для вас.</b>\n\n"
                    "Доступный контент закончился!\n"
                    "Загрузи своё фото (кнопка 📤 Загрузить в меню) или посмотри видео.",
                    parse_mode="HTML",
                    reply_markup=photo_error_keyboard(),
                )
    except Exception:
        logger.exception("watch_photo_content failed")
        try:
            await callback.message.answer(
                "🛠 <b>Не получилось показать фото.</b>\n\n"
                "Кратковременный сбой — это не значит, что фото нет.\n"
                "Попробуй ещё раз или перейди к видео.",
                parse_mode="HTML",
                reply_markup=photo_error_keyboard(),
            )
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
    await callback.message.answer("✏️ Напиши комментарий:")
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
        "Выбери реакцию:",
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
            await message.answer("🚫 Доступ к боту для тебя заблокирован.")
            return
        if not await require_nickname(message, user):
            return
    await message.answer(
        "📤 Отправь видео или фото.\n\n"
        "После проверки модератором ты получишь монеты!"
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
        auto_approved, reward = await auto_approve_if_trusted(session, saved.id, user.id)

        if auto_approved:
            xp_mult = await get_xp_multiplier(session, user.id)
            user.xp += int(XP_PER_UPLOAD * xp_mult)
            await _level_up_check(session, user, message)
            await session.commit()
            await _update_quest_progress(session, user.id, "upload", 1)
            await message.answer(
                f"✅ Видео #{saved.id} автоматически одобрено! (доверенный автор)\n+{_fmt_coins(reward)} монет"
            )
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
        if not has_valid_nickname(user):
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
        auto_approved, reward = await auto_approve_if_trusted(session, saved.id, user.id)

        if auto_approved:
            xp_mult = await get_xp_multiplier(session, user.id)
            user.xp += int(XP_PER_UPLOAD * xp_mult)
            await _level_up_check(session, user, message)
            await session.commit()
            await _update_quest_progress(session, user.id, "upload", 1)
            await message.answer(
                f"✅ Фото #{saved.id} автоматически одобрено! (доверенный автор)\n+{_fmt_coins(reward)} монет"
            )
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
    milestone_text = _build_referral_milestone_text(refs)
    await message.answer(
        f"👥 <b>Рефералы</b>\n\n"
        f"Приглашай друзей и получай монеты.\n"
        f"• за каждого активного друга: <b>+{_fmt_coins(REFERRAL_REWARD_INVITER)}</b> монет\n"
        f"• новый пользователь тоже получает стартовый бонус: <b>+{_fmt_coins(REFERRAL_REWARD_NEW_USER)}</b> монет\n"
        f"• ссылку можно отправить в 1 тап любому знакомому\n\n"
        f"Статусы реферала:\n"
        f"• перешёл по ссылке\n"
        f"• зарегистрировался\n"
        f"• стал активным\n"
        f"• награда начислена\n\n"
        f"Твоя ссылка:\n<code>{ref_link}</code>\n\n"
        f"Приглашено: <b>{refs}</b>\n"
        f"Заработано: <b>{_fmt_coins(user.referral_earnings)}</b> монет"
        f"{milestone_text}",
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
            f"💳 <b>Пополнение баланса</b>{sale_badge}{admin_free_badge}{bonus_text}\n\n"
            f"Собрали 3 понятных пакета под тех, кто хочет быстро вернуться к просмотру:\n"
            f"• <b>500 монет</b> — быстрый старт\n"
            f"• <b>1 000 монет</b> — популярный пакет\n"
            f"• <b>2 200 монет</b> — самый выгодный\n\n"
            f"Выбери пакет:",
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
                f"Твой баланс: <b>{_fmt_coins(user.balance)}</b> монет",
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
    await callback.message.answer("💫 Введи количество Stars (мин. 1):")
    await callback.answer()


@router.message(CustomBuyState.waiting_stars)
async def process_custom_stars(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("❌ Введи целое число.")
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
                f"Твой баланс: <b>{_fmt_coins(user.balance)}</b> монет",
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
                if await _is_first_paid_payment(session, user.id):
                    await _notify_admins_about_first_payment(message.bot, user, stars=paid_stars, payload=payload)
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
                    if await _is_first_paid_payment(session, user.id):
                        await _notify_admins_about_first_payment(message.bot, user, stars=paid_stars, payload=payload)
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
            reward, rarity_or_err, new_pity = await open_lootbox_for_stars(
                session,
                telegram_user_id=message.from_user.id,
                payment_payload=payload,
            )
            # Keep Payment status aligned with idempotent lootbox processing.
            if await mark_payment_paid_once(session, payload):
                await session.commit()
                if await _is_first_paid_payment(session, user.id):
                    await _notify_admins_about_first_payment(message.bot, user, stars=paid_stars, payload=payload)
        if reward is None:
            await message.answer(f"⚠️ {rarity_or_err}")
        else:
            rarity = rarity_or_err
            icon = {"common": "⚪", "rare": "🔵", "epic": "🟣", "jackpot": "🟡"}.get(rarity, "🎁")
            await message.answer(
                f"{icon} <b>Лутбокс открыт!</b>\n\n"
                f"Выигрыш: <b>+{reward:,.0f}</b> монет\n"
                f"До гарантированного Редкого+: <b>{new_pity}</b>".replace(',', ' '),
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
                    await message.answer("Ошибка платежа: оффер не найден или не принадлежит тебе.")
                    return

                offer.status = "pending"
                await session.commit()
                if await _is_first_paid_payment(session, user.id):
                    await _notify_admins_about_first_payment(message.bot, user, stars=paid_stars, payload=payload)

                from app.services import schedule_mod_notification
                await schedule_mod_notification(session, "offer")
                try:
                    await notify_admins(
                        message.bot,
                        f"📣 <b>Новый оффер после оплаты</b>\n"
                        f"Автор: <code>{user.telegram_id}</code>\n"
                        f"Название: <b>{escape(offer.title)}</b>\n"
                        f"Тип цели: {classify_offer_url(offer.channel_url)['label']}\n"
                        f"Статус: отправлен на модерацию\n\n"
                        f"Открыть очередь: /admin",
                    )
                except Exception:
                    pass

                await message.answer(
                    "✅ Оплата прошла успешно! Твой оффер отправлен на модерацию.\n"
                    "Он появится в списке, как только администратор его одобрит."
                )
        except Exception:
            logger.exception("Failed to process paid user offer")
            await message.answer("⚠️ Не удалось обработать оплату оффера. Администраторы уже могут проверить журнал ошибок.")
    else:
        notify_first_payment = False
        notify_user = None
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
            if payment and await _is_first_paid_payment(session, user.id):
                notify_first_payment = True
                notify_user = user
        if payment:
            if notify_first_payment and notify_user is not None:
                await _notify_admins_about_first_payment(message.bot, notify_user, stars=paid_stars, payload=payload)
            await message.answer(
                f"✅ Оплата успешна!\n"
                f"💰 Начислено: <b>{_fmt_coins(credited_total)}</b> монет",
                parse_mode="HTML"
            )
        else:
            await message.answer("✅ Оплата получена!")


def _lootbox_kb(coin_price: Decimal | None = None, star_price: int | None = None, user_level: int = 1) -> InlineKeyboardMarkup:
    from app.config import WEBHOOK_BASE
    base = (WEBHOOK_BASE or "").rstrip("/")
    cases_url = f"{base}/cases" if base else ""
    
    coin_price = to_decimal(coin_price if coin_price is not None else LOOTBOX_COIN_PRICE)
    star_price = int(star_price if star_price is not None else LOOTBOX_STAR_PRICE)
    
    kb = []
    if cases_url:
        from aiogram.types.web_app_info import WebAppInfo
        kb.append([InlineKeyboardButton(text="🔥 ОТКРЫТЬ С АНИМАЦИЕЙ (Mini App)", web_app=WebAppInfo(url=cases_url))])
        
    kb.extend([
        [InlineKeyboardButton(
            text=f"🪙 Обычный кейс ({coin_price:,.0f} монет)".replace(',', ' '),
            callback_data="lootbox_buy:coins:common"
        )],
        [InlineKeyboardButton(
            text=f"⭐ Обычный кейс ({star_price} Stars)",
            callback_data="lootbox_buy:stars"
        )],
        [InlineKeyboardButton(
            text=f"🎨 Кейс ников (250+ монет)",
            callback_data="styles_lootbox_menu"
        )],
    ])
    
    if user_level >= 10:
        kb.append([InlineKeyboardButton(
            text=f"💎 Элитный кейс (1 000 монет)",
            callback_data="lootbox_buy:coins:elite"
        )])
    if user_level >= 20:
        kb.append([InlineKeyboardButton(
            text=f"🔥 Легендарный кейс (5 000 монет)",
            callback_data="lootbox_buy:coins:legendary"
        )])
        
    return InlineKeyboardMarkup(inline_keyboard=kb)


@router.callback_query(F.data == "lootbox_menu")
async def lootbox_menu(callback: CallbackQuery):
    if not ENABLE_LOOTBOXES:
        await callback.message.answer("⛔ Лутбоксы временно отключены.")
        await callback.answer()
        return

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        discount = await get_stars_discount(session, user.id) if user else 0.0
        pity = 10 - (user.lootbox_pity_counter if user else 0)
        level = user.level if user else 1

    coin_price = to_decimal(LOOTBOX_COIN_PRICE)
    base_star_price = int(LOOTBOX_STAR_PRICE)
    star_price = max(1, int(math.ceil(base_star_price * (1 - discount)))) if discount > 0 else base_star_price
    
    pity_text = f"\n✨ До гарантированного <b>Редкого+</b>: <b>{pity}</b> прокрутов."
    
    text = (
        "🎁 <b>Лутбоксы</b>\n\n"
        f"Обычный кейс: <b>{coin_price:,.0f}</b> монет или <b>{star_price}</b> Stars.\n".replace(',', ' ') +
        "Внутри — случайный выигрыш монет.\n" +
        pity_text + "\n\n"
        "🎨 <b>Кейс ников</b>: шанс 50% получить кастомный стиль или 50% вернуть монеты.\n"
    )
    
    if level < 10:
        text += "\n🔓 <i>Элитный кейс откроется на 10 уровне.</i>"
    if level < 20:
        text += "\n🔓 <i>Легендарный кейс откроется на 20 уровне.</i>"
    
    await callback.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=_lootbox_kb(coin_price, star_price, level),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("lootbox_buy:"))
async def lootbox_buy(callback: CallbackQuery):
    if not ENABLE_LOOTBOXES:
        await callback.answer("Лутбоксы отключены.", show_alert=True)
        return
    from app.services import _roll_lootbox_reward_coins, open_lootbox_for_coins
    parts = callback.data.split(":")
    kind = parts[1]
    case_type = parts[2] if len(parts) > 2 else "common"
    
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
            
            if admin_free:
                # Бесплатный лутбокс для админа
                reward, rarity, new_pity = _roll_lootbox_reward_coins(user.lootbox_pity_counter, case_type)
                user.lootbox_pity_counter = new_pity
                user = await change_balance_atomic(
                    session,
                    user.id,
                    reward,
                    "lootbox_reward_admin_free",
                    details=f"ADMIN_FREE kind={case_type} rarity={rarity}"
                ) or user
                session.add(LootboxOpen(
                    user_id=user.id, payment_payload=None, pay_currency="coins",
                    price_coins=Decimal("0"), price_stars=0, reward_coins=reward, rarity=rarity,
                ))
                await log_user_action(session, user.id, "lootbox_open_admin_free",
                                      f"kind={case_type}, rarity={rarity}, reward={reward}")
                await session.commit()
                icon = {"common": "⚪", "rare": "🔵", "epic": "🟣", "jackpot": "🟡"}.get(rarity, "🎁")
                await callback.message.answer(
                    f"{icon} <b>Лутбокс открыт!</b> (🆓 ADMIN FREE)\n\n"
                    f"Выигрыш: <b>+{reward:,.0f}</b> монет\n"
                    f"До гарантированного Редкого+: <b>{10 - new_pity}</b>".replace(',', ' '),
                    parse_mode="HTML",
                    reply_markup=_lootbox_kb(coin_price, display_star_price, user.level),
                )
                await callback.answer("🆓 Лутбокс открыт бесплатно!")
                return

            reward, rarity_or_err, new_pity = await open_lootbox_for_coins(session, user.id, case_type)
        if reward is None:
            await callback.answer(rarity_or_err, show_alert=True)
            return
        rarity = rarity_or_err
        icon = {"common": "⚪", "rare": "🔵", "epic": "🟣", "jackpot": "🟡"}.get(rarity, "🎁")
        await callback.message.answer(
            f"{icon} <b>Лутбокс открыт!</b>\n\n"
            f"Выигрыш: <b>+{reward:,.0f}</b> монет\n"
            f"До гарантированного Редкого+: <b>{new_pity}</b>".replace(',', ' '),
            parse_mode="HTML",
            reply_markup=_lootbox_kb(coin_price, display_star_price, user.level),
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


from app.nick_styles import (
    CATEGORIES, STYLES, STYLES_BY_CAT,
    style_inline_preview, style_label
)

def _styles_case_kb(excluded_ids: list[int], current_price: Decimal) -> InlineKeyboardMarkup:
    from app.nick_styles import CATEGORIES, STYLES_BY_CAT
    kb = []
    
    # Сетка категорий
    row = []
    for cat_id, (icon, name) in CATEGORIES.items():
        cat_styles = STYLES_BY_CAT[cat_id]
        cat_ids = [s.id for s in cat_styles]
        excluded_in_cat = len([sid for sid in cat_ids if sid in excluded_ids])
        
        if excluded_in_cat == len(cat_ids):
            status = "❌"
        elif excluded_in_cat > 0:
            status = "⚠️"
        else:
            status = "✅"
            
        # Кнопка открывает список стилей категории
        row.append(InlineKeyboardButton(
            text=f"{status} {icon} {name}", 
            callback_data=f"styles_case_view_cat:{cat_id}"
        ))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
        
    kb.append([InlineKeyboardButton(text=f"🎲 ОТКРЫТЬ ({current_price:.0f} монет)", callback_data="styles_case_open")])
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="lootbox_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _styles_list_kb(cat_id: int, excluded_ids: list[int]) -> InlineKeyboardMarkup:
    from app.nick_styles import STYLES_BY_CAT, style_label
    kb = []
    cat_styles = STYLES_BY_CAT[cat_id]
    
    # По 2 стиля в ряд
    row = []
    for s in cat_styles:
        status = "❌" if s.id in excluded_ids else "✅"
        row.append(InlineKeyboardButton(
            text=f"{status} {s.label}", 
            callback_data=f"styles_case_toggle_style:{s.id}"
        ))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
        
    # Управление всей категорией
    cat_ids = [s.id for s in cat_styles]
    all_excluded = all(sid in excluded_ids for sid in cat_ids)
    cat_toggle_text = "✅ Включить все" if all_excluded else "❌ Исключить все"
    
    kb.append([InlineKeyboardButton(text=cat_toggle_text, callback_data=f"styles_case_toggle_cat_all:{cat_id}")])
    kb.append([InlineKeyboardButton(text="◀️ К категориям", callback_data="styles_lootbox_menu_refresh")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


@router.callback_query(F.data == "styles_lootbox_menu")
async def styles_lootbox_menu(callback: CallbackQuery, state: FSMContext):
    await state.set_state(StylesCaseState.configuring)
    data = await state.get_data()
    excluded_ids = data.get("excluded_ids", [])
    
    from app.nick_styles import STYLES
    total = len(STYLES)
    remaining = total - len(excluded_ids)
    price = (Decimal("250") * Decimal(total) / Decimal(remaining)).quantize(Decimal("1"), rounding=ROUND_DOWN)
    
    text = (
        "🎨 <b>Кейс ников</b>\n\n"
        "В этом кейсе ты можешь выбить кастомный стиль для ника на 7 дней.\n"
        "• Шанс 50%: Рандомный стиль\n"
        "• Шанс 50%: Утешительный приз 10-250 монет\n\n"
        f"<b>Текущая цена:</b> {price:.0f} монет\n"
        f"<b>Доступно стилей:</b> {remaining}/{total}\n\n"
        "Выбери категорию ниже, чтобы настроить доступные стили точечно. "
        "Удаление стилей повышает шанс на остальные, но <b>увеличивает цену</b>."
    )
    
    await callback.message.answer(text, parse_mode="HTML", reply_markup=_styles_case_kb(excluded_ids, price))
    await callback.answer()


@router.callback_query(F.data == "styles_lootbox_menu_refresh")
async def styles_lootbox_menu_refresh(callback: CallbackQuery, state: FSMContext):
    """Возврат к категориям с редактированием сообщения"""
    data = await state.get_data()
    excluded_ids = data.get("excluded_ids", [])
    
    from app.nick_styles import STYLES
    total = len(STYLES)
    remaining = total - len(excluded_ids)
    price = (Decimal("250") * Decimal(total) / Decimal(remaining)).quantize(Decimal("1"), rounding=ROUND_DOWN)
    
    text = (
        "🎨 <b>Кейс ников</b>\n\n"
        f"<b>Текущая цена:</b> {price:.0f} монет\n"
        f"<b>Доступно стилей:</b> {remaining}/{total}\n\n"
        "Выбери категорию для точечной настройки:"
    )
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_styles_case_kb(excluded_ids, price))
    await callback.answer()


@router.callback_query(StylesCaseState.configuring, F.data.startswith("styles_case_view_cat:"))
async def styles_case_view_cat(callback: CallbackQuery, state: FSMContext):
    cat_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    excluded_ids = data.get("excluded_ids", [])
    
    from app.nick_styles import CATEGORIES
    icon, name = CATEGORIES[cat_id]
    
    text = (
        f"{icon} <b>Категория: {name}</b>\n\n"
        "Нажми на стиль, чтобы включить или исключить его из кейса."
    )
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_styles_list_kb(cat_id, excluded_ids))
    await callback.answer()


@router.callback_query(StylesCaseState.configuring, F.data.startswith("styles_case_toggle_style:"))
async def styles_case_toggle_style(callback: CallbackQuery, state: FSMContext):
    style_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    excluded_ids = list(data.get("excluded_ids", []))
    
    from app.nick_styles import STYLES, STYLES_BY_CAT
    
    if style_id in excluded_ids:
        excluded_ids.remove(style_id)
    else:
        # Safeguard: cannot exclude ALL styles
        if len(excluded_ids) >= len(STYLES) - 1:
            await callback.answer("В кейсе должен остаться хотя бы один стиль!", show_alert=True)
            return
        excluded_ids.append(style_id)
        
    await state.update_data(excluded_ids=excluded_ids)
    
    # Рефреш списка стилей в текущей категории
    s_obj = STYLES[style_id]
    await callback.message.edit_reply_markup(reply_markup=_styles_list_kb(s_obj.cat_id, excluded_ids))
    await callback.answer()


@router.callback_query(StylesCaseState.configuring, F.data.startswith("styles_case_toggle_cat_all:"))
async def styles_case_toggle_cat_all(callback: CallbackQuery, state: FSMContext):
    cat_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    excluded_ids = list(data.get("excluded_ids", []))
    
    from app.nick_styles import STYLES_BY_CAT, STYLES
    cat_styles = STYLES_BY_CAT[cat_id]
    cat_style_ids = [s.id for s in cat_styles]
    
    all_excluded = all(sid in excluded_ids for sid in cat_style_ids)
    if all_excluded:
        # Включаем все стили категории обратно
        excluded_ids = [sid for sid in excluded_ids if sid not in cat_style_ids]
    else:
        # Исключаем все стили категории (с проверкой на последний выживший)
        other_excluded_count = len([sid for sid in excluded_ids if sid not in cat_style_ids])
        if other_excluded_count + len(cat_style_ids) >= len(STYLES):
             # Оставляем хотя бы один
             available_to_exclude = (len(STYLES) - 1) - other_excluded_count
             if available_to_exclude <= 0:
                 await callback.answer("Нельзя исключить все стили!", show_alert=True)
                 return
             # Исключаем только часть? Нет, лучше просто запретить.
             await callback.answer("Нельзя исключить все стили в боте!", show_alert=True)
             return
             
        for sid in cat_style_ids:
            if sid not in excluded_ids:
                excluded_ids.append(sid)
                
    await state.update_data(excluded_ids=excluded_ids)
    await callback.message.edit_reply_markup(reply_markup=_styles_list_kb(cat_id, excluded_ids))
    await callback.answer()


@router.callback_query(StylesCaseState.configuring, F.data == "styles_case_open")
async def styles_case_open(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    excluded_ids = data.get("excluded_ids", [])
    
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            return
            
        from app.services import open_styles_lootbox
        reward, kind, price = await open_styles_lootbox(session, user.id, excluded_ids)
        
    if reward is None:
        await callback.answer(kind, show_alert=True)
        return
        
    if kind == "style":
        from app.nick_styles import style_inline_preview, style_label
        preview = style_inline_preview(reward)
        label = style_label(reward)
        msg = (
            f"✨ <b>ВЫ ВЫИГРАЛИ СТИЛЬ!</b>\n\n"
            f"Название: <b>{label}</b>\n"
            f"Вид: <code>{preview}</code>\n\n"
            f"Стиль активирован на 7 дней! Ты можешь увидеть его в профиле."
        )
    else:
        msg = (
            f"🪙 <b>Утешительный приз!</b>\n\n"
            f"Тебе начислено <b>{reward:.0f} монет</b>."
        )
        
    await callback.message.answer(msg, parse_mode="HTML")
    # Reset to main lootbox menu
    await state.clear()
    await lootbox_menu(callback)
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
        "📢 <b>Офферы</b>\n\nВыбери раздел:",
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
        "📢 <b>Офферы для участия</b>\n\nВыбери оффер:",
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
        if not is_offer_available(offer):
            await callback.answer("Оффер больше не активен.", show_alert=True)
            return

        from sqlalchemy import select as sa_select
        from app.models import OfferParticipation
        participants = (await session.execute(
            sa_select(func.count(OfferParticipation.id)).where(
                OfferParticipation.offer_id == offer_id
            )
        )).scalar_one()
        rented_ads = await get_active_rentals_for_offer(session, offer_id, limit=10)

    target_meta = classify_offer_url(offer.channel_url)
    target_url = normalize_telegram_url(offer.channel_url)
    if not target_url:
        await callback.answer("У оффера некорректная ссылка. Сообщи администратору.", show_alert=True)
        return
    verify_text = (
        "Финальная награда выдаётся после автоматической проверки участия."
        if target_meta["auto_verify"]
        else "Финальная награда выдаётся по кнопке подтверждения: для ботов, приватных инвайтов и некоторых чатов авто-проверка недоступна."
    )
    text = (
        f"📢 <b>{escape(offer.title)}</b>\n\n"
        f"{escape(offer.description)}\n\n"
        f"🔗 <b>Тип цели:</b> {target_meta['label']}\n"
        f"💰 Предварительно: <b>{offer.reward_preview}</b> монет\n"
        f"🎁 После подтверждения: <b>{offer.reward_final}</b> монет\n"
        f"👥 Участников: {participants}\n\n"
        f"ℹ️ {verify_text}"
    )
    if rented_ads:
        text += "\n\n📣 <b>Реклама партнёров:</b>"

    kb_rows = [
        [InlineKeyboardButton(
            text=target_meta["cta"],
            url=target_url
        )],
        [InlineKeyboardButton(
            text="▶️ Участвовать",
            callback_data=f"offer_start_confirm:{offer_id}"
        )],
        [InlineKeyboardButton(
            text=target_meta["claim_text"],
            callback_data=f"offer_check:{offer_id}"
        )],
    ]
    for rental in rented_ads:
        rental_url = normalize_telegram_url(rental.renter_channel_url)
        if rental_url:
            kb_rows.append([InlineKeyboardButton(
                text=f"📣 {rental.renter_channel_title[:45]}",
                url=rental_url,
            )])
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


@router.callback_query(F.data.startswith("offer_start_confirm:"))
async def cb_offer_start_confirm(callback: CallbackQuery):
    offer_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        offer = await get_offer_by_id(session, offer_id)
        if not is_offer_available(offer):
            await callback.answer("Оффер больше не активен.", show_alert=True)
            return
    target_meta = classify_offer_url(offer.channel_url)
    verification_block = (
        "• после участия бот сам проверит подписку и выдаст финальную награду\n"
        if target_meta["auto_verify"]
        else "• для этого типа цели авто-проверка недоступна, поэтому финальная награда выдаётся по кнопке подтверждения\n"
    )
    text = (
        "⚠️ <b>Важно перед участием</b>\n\n"
        "Ты получишь монеты за участие в оффере.\n"
        "Если после получения награды ты отпишешься:\n"
        "• награда будет забрана назад\n"
        "• при повторных нарушениях может быть дополнительный штраф\n"
        "• первые 15 минут после входа считаются grace period без доп. штрафа\n"
        f"{verification_block}\n"
        f"Оффер: <b>{escape(offer.title)}</b>\n"
        f"Тип цели: <b>{target_meta['label']}</b>\n"
        f"Предварительная награда: <b>{_fmt_coins(offer.reward_preview)}</b> монет\n"
        f"Финальная награда: <b>{_fmt_coins(offer.reward_final)}</b> монет"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Понятно, участвовать", callback_data=f"offer_start:{offer_id}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"offer_open:{offer_id}")],
    ])
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("offer_start:"))
async def cb_offer_start(callback: CallbackQuery):
    if not _cooldown_ok(
        _offer_action_last_ts,
        (callback.from_user.id, "offer_start"),
        OFFER_ACTION_COOLDOWN_SECONDS,
    ):
        await callback.answer("⏳ Слишком часто. Попробуй через пару секунд.", show_alert=True)
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
            await callback.answer("Ты уже участвуешь!", show_alert=True)
            return
        offer = await get_offer_by_id(session, offer_id)

    paid = to_decimal(part.reward_given)
    target_meta = classify_offer_url(offer.channel_url)
    cap_note = "" if paid == to_decimal(offer.reward_preview) else "\n⚠️ Сработал дневной лимит наград."
    next_step = "Открой проект и потом нажми кнопку подтверждения." if not target_meta["auto_verify"] else "Подпишитесь и нажми кнопку проверки."
    await callback.answer(
        f"✅ Получено {paid} монет!\n"
        f"{next_step}{cap_note}",
        show_alert=True
    )


@router.callback_query(F.data.startswith("offer_check:"))
async def cb_offer_check(callback: CallbackQuery):
    if not _cooldown_ok(
        _offer_action_last_ts,
        (callback.from_user.id, "offer_check"),
        OFFER_ACTION_COOLDOWN_SECONDS,
    ):
        await callback.answer("⏳ Слишком часто. Попробуй через пару секунд.", show_alert=True)
        return
    offer_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        offer = await get_offer_by_id(session, offer_id)
        if not is_offer_available(offer):
            await callback.answer("Оффер больше не активен.", show_alert=True)
            return
        target_meta = classify_offer_url(offer.channel_url)
        if target_meta["auto_verify"]:
            if not await _check_user_offer_subscription(callback, offer):
                await callback.answer(
                    "❌ Подписка не найдена. Подпишитесь на проект и попробуйте снова.",
                    show_alert=True,
                )
                return
        ok, paid = await verify_offer_subscription(session, user.id, offer_id)
        if ok:
            if paid > 0:
                success_text = "✅ Подтверждено! Получено {paid} монет!" if target_meta["auto_verify"] else "✅ Подтверждение принято! Получено {paid} монет!"
                await callback.answer(success_text.format(paid=paid), show_alert=True)
            else:
                neutral_text = "✅ Подписка подтверждена. Награда уже выдана или дневной лимит исчерпан." if target_meta["auto_verify"] else "✅ Участие уже подтверждено или дневной лимит исчерпан."
                await callback.answer(neutral_text, show_alert=True)
        else:
            await callback.answer(
                "❌ Не удалось подтвердить участие.",
                show_alert=True
            )


# =========================
# АРЕНДА РЕКЛАМНОГО СЛОТА
# =========================
@router.callback_query(F.data == "offers_rent_list")
async def offers_rent_list(callback: CallbackQuery):
    async with async_session() as session:
        offers = await get_rentable_offers(session)
        offer_rows = [
            (offer, await count_reserved_rentals(session, offer.id))
            for offer in offers
        ]

    if not offers:
        await callback.message.answer(
            "😔 Нет офферов доступных для аренды."
        )
        await callback.answer()
        return

    text = "📣 <b>Аренда рекламных слотов</b>\n\n"
    text += (
        "Арендуйте слот в оффере и рекламируйте свой канал!\n"
        "Твой канал будет показан всем участникам оффера.\n\n"
        "Выбери оффер:"
    )
    kb_buttons = []
    for offer, reserved_count in offer_rows:
        slots_left = max(0, int(offer.max_simultaneous_rentals or 1) - reserved_count)
        kb_buttons.append([InlineKeyboardButton(
            text=(
                f"📣 {offer.title[:30]} | "
                f"{offer.rent_cost_per_day} монет/день | "
                f"Слотов: {slots_left}/{offer.max_simultaneous_rentals}"
            ),
            callback_data=f"rent_offer:{offer.id}"
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
    from app.user_offer_handlers import user_offers_menu
    await callback.message.answer(
        "📢 <b>Офферы</b>\n\nВыбери раздел:",
        parse_mode="HTML",
        reply_markup=user_offers_menu()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("rent_offer:"))
async def rent_offer_start(callback: CallbackQuery, state: FSMContext):
    offer_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        offer = await get_offer_by_id(session, offer_id)
        if not is_offer_available(offer) or not offer.is_rentable:
            await callback.answer("Аренда недоступна.", show_alert=True)
            return

        reserved_count = await count_reserved_rentals(session, offer_id)
        slots_left = int(offer.max_simultaneous_rentals or 1) - reserved_count

    if slots_left <= 0:
        await callback.answer(
            "❌ Все слоты заняты. Попробуй позже.",
            show_alert=True
        )
        return

    await state.set_state(RentOfferState.waiting_channel_title)
    await state.update_data(offer_id=offer_id)
    await callback.message.answer(
        f"📣 <b>Аренда слота в: {escape(offer.title)}</b>\n\n"
        f"💰 Стоимость: {offer.rent_cost_per_day} монет/день\n"
        f"Свободных слотов: {slots_left}/{offer.max_simultaneous_rentals}\n\n"
        f"Шаг 1/3: Введи название твоего канала:",
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
        "Шаг 2/3: Введи ссылку на твой канал (https://t.me/...):"
    )


@router.message(RentOfferState.waiting_channel_url)
async def rent_channel_url(message: Message, state: FSMContext):
    url = normalize_telegram_url(message.text or "")
    if not url:
        await message.answer("❌ Нужна корректная ссылка t.me/... или @username.")
        return
    await state.update_data(channel_url=url)
    await state.set_state(RentOfferState.waiting_days)

    data = await state.get_data()
    offer_id = data.get("offer_id")

    await message.answer(
        f"Шаг 3/3: Выбери количество дней аренды\n"
        f"(от {OFFER_MIN_RENT_DAYS} до {OFFER_MAX_RENT_DAYS}):",
        reply_markup=rent_days_keyboard(offer_id)
    )


@router.callback_query(RentOfferState.waiting_days, F.data.startswith("rent_days:"))
async def rent_days_selected(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    offer_id = int(parts[1])
    days = int(parts[2])

    data = await state.get_data()
    if data.get("offer_id") != offer_id or not (OFFER_MIN_RENT_DAYS <= days <= OFFER_MAX_RENT_DAYS):
        await callback.answer("Некорректные параметры аренды.", show_alert=True)
        await state.clear()
        return
    channel_title = data.get("channel_title", "")
    channel_url = data.get("channel_url", "")

    async with async_session() as session:
        offer = await get_offer_by_id(session, offer_id)
        if not is_offer_available(offer) or not offer.is_rentable:
            await callback.answer("Оффер больше не доступен для аренды.", show_alert=True)
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
        f"Оффер: {escape(offer.title)}\n"
        f"Твой канал: {escape(channel_title)}\n"
        f"Ссылка: {escape(channel_url)}\n"
        f"Дней: {days}\n"
        f"Стоимость: <b>{cost} монет</b>\n"
        f"Твой баланс: {user.balance} монет\n\n"
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
    if (
        data.get("offer_id") != offer_id
        or data.get("days") != days
        or not (OFFER_MIN_RENT_DAYS <= days <= OFFER_MAX_RENT_DAYS)
    ):
        await callback.answer("Сессия аренды устарела. Начните заново.", show_alert=True)
        await state.clear()
        return
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
        if rental:
            await schedule_mod_notification(session, "offer")

    if error:
        await callback.message.answer(error)
        await state.clear()
        await callback.answer()
        return

    try:
        await notify_admins(
            callback.bot,
            f"🧾 <b>Новая аренда на модерации</b>\n"
            f"Заявка: <b>#{rental.id}</b>\n"
            f"Канал: <b>{escape(rental.renter_channel_title)}</b>\n"
            f"Автор: <code>{callback.from_user.id}</code>\n\n"
            "Открыть очередь: /admin",
        )
    except Exception:
        logger.warning("Failed to notify admins about rental_id=%s", rental.id)

    await callback.message.answer(
        f"✅ <b>Заявка на аренду отправлена!</b>\n\n"
        f"Канал: {escape(channel_title)}\n"
        f"Дней: {days}\n"
        f"Стоимость: {rental.cost_paid} монет\n\n"
        f"После одобрения администратором твой канал будет активен в оффере.\n"
        f"Ты получишь уведомление.",
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
                "У тебя нет аренд.\n"
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
                f"{status_icon} {escape(offer_name)}\n"
                f"   Канал: {escape(r.renter_channel_title)}\n"
                f"   Дней: {r.rent_days} | Стоимость: {r.cost_paid}\n"
                f"   Статус: {escape(r.status)} | До: {expires}\n"
            )
            if r.status == "rejected" and r.rejection_reason:
                text += f"   Причина: {escape(r.rejection_reason)}\n"
            text += "\n"

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
        "🎮 <b>Игровой центр</b>\n\nВыбери раздел:",
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
                f"Хочешь заработать?",
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


@router.callback_query(F.data == "low_balance_referrals")
async def low_balance_referrals(callback: CallbackQuery, state: FSMContext):
    await btn_referrals(callback.message, state)
    await callback.answer()


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
        [InlineKeyboardButton(text="🎫 Купить билеты", callback_data="lottery_buy")],
        [InlineKeyboardButton(text="📋 Мои билеты", callback_data="lottery_my_tickets")],
        [InlineKeyboardButton(text="🏆 Рейтинг недели", callback_data="lottery_weekly_leaderboard")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="lottery_menu")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _lottery_buy_kb(max_count: int) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="1", callback_data="lottery_buy_qty:1"),
            InlineKeyboardButton(text="5", callback_data="lottery_buy_qty:5"),
            InlineKeyboardButton(text="10", callback_data="lottery_buy_qty:10"),
        ],
        [InlineKeyboardButton(text=f"🎯 Максимум ({max_count})", callback_data="lottery_buy_max")],
        [InlineKeyboardButton(text="✏️ Ввести количество", callback_data="lottery_buy_custom")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="lottery_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_lottery_menu(message_or_callback_message: Message, telegram_user_id: int | None = None) -> None:
    if not ENABLE_LOTTERY:
        await message_or_callback_message.answer("⛔ Секслото временно отключено.")
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

    status_map = {
        "open": "приём билетов открыт",
        "drawing": "идёт розыгрыш",
        "completed": "розыгрыш завершён",
    }
    status_text = status_map.get(state_data.get("status"), str(state_data.get("status")))

    draw_date_msk = (round_obj.draw_starts_at + timedelta(hours=3)).strftime("%d.%m.%Y")
    duration_seconds = get_lottery_draw_duration_seconds(round_obj.numbers_per_ticket)
    minutes = duration_seconds // 60
    seconds = duration_seconds % 60
    duration_text = f"{minutes} мин {seconds} сек" if minutes else f"{seconds} сек"
    drawn_text = ", ".join(map(str, state_data.get("drawn_numbers", []))) or "пока ничего"

    text = (
        "🎰 <b>Секслото</b>\n\n"
        f"📅 <b>Розыгрыш:</b> {draw_date_msk}\n"
        f"📌 <b>Статус:</b> {status_text}\n"
        f"🎟 <b>Цена билета:</b> {_fmt_coins(state_data.get('ticket_price'))} монет\n"
        f"💰 <b>Призовой фонд:</b> {_fmt_coins(state_data.get('prize_pool'))} монет\n"
        f"🔵 <b>Уже выпало:</b> {drawn_text}\n\n"
        "<b>Как это работает:</b>\n"
        f"• в одном билете — <b>{round_obj.numbers_per_ticket} чисел из {round_obj.numbers_pool}</b>\n"
        f"• каждый день в <b>{LOTTERY_DRAW_HOUR_MSK}:00 по МСК</b> начинается розыгрыш\n"
        f"• на каждый бочонок уходит около <b>{LOTTERY_SECONDS_PER_BALL} секунд</b>, весь розыгрыш длится примерно <b>{duration_text}</b>\n"
        "• <b>1 совпадение — не выигрыш</b>\n"
        "• <b>2 совпадения — 10 монет</b>\n"
        "• <b>3 совпадения — 20 монет</b>\n"
        "• <b>4, 5 и 6 совпадений</b> делят основной призовой фонд\n"
        "• призовой фонд делится так: <b>6 совпадений — 70%</b>, <b>5 совпадений — 20%</b>, <b>4 совпадения — 10%</b>\n"
        "• если в одной категории несколько выигрышных билетов, её доля делится между ними поровну\n"
        "• каждую неделю действует <b>рейтинг активности</b> с дополнительными призами для топ-3 игроков\n\n"
        + (f"🔴 <b>Live:</b> <a href=\"{live_url}\">открыть трансляцию</a>\n" if live_url else "")
        + f"{draw_line}\n\n"
        "Нажми «🎫 Купить билеты», чтобы выбрать количество билетов, или открой Live и следи за розыгрышем в реальном времени."
    )

    await message_or_callback_message.answer(
        text,
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
def _format_lottery_purchase_summary(tickets: list[LotteryTicket], total_cost: Decimal, balance_after: Decimal, *, admin_free: bool) -> str:
    qty = len(tickets)
    lines = [
        f"🎫 <b>Куплено билетов:</b> {qty}",
    ]
    if admin_free:
        lines.append("🆓 <b>ADMIN FREE</b> — без списания монет")
    else:
        lines.append(f"💸 <b>Списано:</b> {_fmt_coins(total_cost)} монет")
        lines.append(f"💰 <b>Баланс:</b> {_fmt_coins(balance_after)} монет")

    preview_limit = 5
    lines.append("")
    lines.append("<b>Твои билеты:</b>")
    for ticket in tickets[:preview_limit]:
        lines.append(f"• #{ticket.id}: <code>{ticket.numbers}</code>")
    if qty > preview_limit:
        lines.append(f"• … и ещё {qty - preview_limit} билет(ов)")
    return "\n".join(lines)


async def _lottery_buy_execute(target, telegram_user_id: int, quantity: int, *, is_callback: bool = False) -> tuple[bool, str]:
    async with async_session() as session:
        user = await get_user(session, telegram_user_id)
        if not user:
            return False, "Пользователь не найден."

        admin_free = await is_admin_free_eligible(session, telegram_user_id, user)
        tickets, total_cost, error = await buy_lottery_tickets(session, user, quantity, is_admin_free=admin_free)
        if error:
            return False, error
        await session.refresh(user)
        text = _format_lottery_purchase_summary(tickets, total_cost, user.balance, admin_free=admin_free)

    await target.answer(text, parse_mode="HTML")
    return True, f"Куплено {len(tickets)} билет(ов)!"


@router.callback_query(F.data == "lottery_buy")
async def lottery_buy(callback: CallbackQuery, state: FSMContext):
    if not ENABLE_LOTTERY:
        await callback.answer("⛔ Лотерея отключена.", show_alert=True)
        return

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        round_obj = await ensure_current_lottery_round(session)
        now = utc_now()
        if round_obj.status != "open" or now >= round_obj.draw_starts_at:
            await callback.answer("Продажа билетов закрыта до следующего розыгрыша.", show_alert=True)
            return

        admin_free = await is_admin_free_eligible(session, callback.from_user.id, user)
        max_count = LOTTERY_MAX_TICKETS_PER_PURCHASE if admin_free else get_lottery_max_tickets_for_balance(user.balance, to_decimal(round_obj.ticket_price))
        if max_count <= 0:
            await callback.answer(f"Недостаточно монет. Билет стоит {round_obj.ticket_price}.", show_alert=True)
            return

        await state.clear()
        await state.set_state(LotteryBuyState.waiting_quantity)
        await callback.message.answer(
            "🎫 <b>Покупка билетов</b>\n\n"
            f"Цена одного билета: <b>{_fmt_coins(round_obj.ticket_price)}</b> монет\n"
            f"Сейчас можно купить до: <b>{max_count}</b> билет(ов)\n\n"
            "Выбери количество, нажми «Максимум» или введи своё число.",
            parse_mode="HTML",
            reply_markup=_lottery_buy_kb(max_count),
        )
        await callback.answer()


@router.callback_query(F.data.startswith("lottery_buy_qty:"))
async def lottery_buy_qty(callback: CallbackQuery, state: FSMContext):
    quantity = int(callback.data.split(":", 1)[1])
    ok, msg = await _lottery_buy_execute(callback.message, callback.from_user.id, quantity, is_callback=True)
    await callback.answer(msg, show_alert=not ok)
    if ok:
        await state.clear()


@router.callback_query(F.data == "lottery_buy_max")
async def lottery_buy_max(callback: CallbackQuery, state: FSMContext):
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer("Пользователь не найден.", show_alert=True)
            return
        round_obj = await ensure_current_lottery_round(session)
        admin_free = await is_admin_free_eligible(session, callback.from_user.id, user)
        quantity = LOTTERY_MAX_TICKETS_PER_PURCHASE if admin_free else get_lottery_max_tickets_for_balance(user.balance, to_decimal(round_obj.ticket_price))
    if quantity <= 0:
        await callback.answer("Сейчас нельзя купить ни одного билета.", show_alert=True)
        return
    ok, msg = await _lottery_buy_execute(callback.message, callback.from_user.id, quantity, is_callback=True)
    await callback.answer(msg, show_alert=not ok)
    if ok:
        await state.clear()


@router.callback_query(F.data == "lottery_buy_custom")
async def lottery_buy_custom(callback: CallbackQuery, state: FSMContext):
    await state.set_state(LotteryBuyState.waiting_quantity)
    await callback.message.answer("✏️ Введи количество билетов, которое хочешь купить:")
    await callback.answer()


@router.message(LotteryBuyState.waiting_quantity)
async def lottery_buy_custom_input(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    if not value.isdigit():
        await message.answer("❌ Введи целое число билетов.")
        return
    quantity = int(value)
    ok, msg = await _lottery_buy_execute(message, message.from_user.id, quantity)
    if not ok:
        await message.answer(f"❌ {msg}")
        return
    await state.clear()


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
        await callback.message.answer("😔 У тебя пока нет билетов в текущем раунде.")
        await callback.answer()
        return
    text = "📋 <b>Твои билеты</b>\n\n"
    for t in tickets:
        text += f"#{t.id}: {t.numbers} | совпадений: {t.matched_count}\n"
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "lottery_weekly_leaderboard")
async def lottery_weekly_leaderboard(callback: CallbackQuery):
    async with async_session() as session:
        rows = await get_weekly_lottery_leaderboard(session, limit=10)
    if not rows:
        await callback.message.answer("🏆 Пока нет недельного рейтинга — как только появятся участники, здесь появится таблица лидеров.")
        await callback.answer()
        return
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    text = "🏆 <b>Рейтинг недели в Секслото</b>\n\n"
    text += "Топ формируется по количеству купленных билетов за текущую неделю. При равенстве выше тот, у кого лучшее совпадение.\n\n"
    for row in rows:
        icon = medals.get(row["place"], f"{row['place']}.")
        name = row["user"].display_name or row["user"].username or str(row["user"].telegram_id)
        reward_text = f" | приз: { _fmt_coins(row['reward']) }" if row["reward"] else ""
        text += f"{icon} <b>{escape(str(name))}</b> — {row['tickets']} бил. | лучший матч: {row['best_match']}{reward_text}\n"
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "lottery_live_info")
async def lottery_live_info(callback: CallbackQuery):
    base = (WEBHOOK_BASE or "").rstrip("/")
    if not base:
        text = (
            "🔴 <b>Live-розыгрыш Секслото</b>\n\n"
            "Live пока недоступен: владелец бота ещё не настроил публичный адрес Mini App."
        )
    else:
        live_url = f"{base}/lottery/live"
        text = (
            "🔴 <b>Live-розыгрыш Секслото</b>\n\n"
            "В прямом эфире ты увидишь, как лототрон по очереди вытягивает все бочонки.\n"
            f"Открыть Live: {live_url}"
        )
    await callback.message.answer(text, parse_mode="HTML")
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
        "Напиши нам бесплатно: о баге, идее или просто поддержке.\n"
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
        "Опиши твоё сообщение одним текстом (5-2000 символов).",
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
        "✅ Спасибо! Твойе обращение отправлено команде.\n"
        "Если нужно, мы свяжемся с тебеи в Telegram."
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
            "Создай код на монеты и поделись им с друзьями!\n"
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
            f"Введи сумму монет (1–{PROMOCODE_MAX_AMOUNT}):"
        )
    await callback.answer()


@router.message(PromoCreateState.waiting_amount)
async def promo_amount(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("Введи число.")
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
        await message.answer("Введи число.")
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
        await message.answer("Введи число.")
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
    await callback.message.answer("Введи промокод:")
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
                "Убедись, что ты правильно ввёл слово (регистр не важен), или поищи актуальное слово в наших соцсетях!",
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
                await message.answer("❌ Халява уже была получена на этой неделе!")
                await state.clear()
                return
                
            import random
            # Награда: случайно от 200 до 1500 монет, строго кратно 10
            reward = Decimal(str(random.randint(20, 150) * 10))
            
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
            f"Тебе начислено <b>{reward:.0f}</b> монет!\n"
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
        await message.answer("⏳ Слишком часто. Попробуй чуть позже.")
        return
    code = (message.text or "").strip()
    if not code:
        await message.answer("Введи промокод.")
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
            await callback.message.answer("📭 У тебя пока нет промокодов.")
            await callback.answer()
            return
        text = "🎟 <b>Твои промокоды:</b>\n\n"
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
    await message.answer(build_version_text(admin=False), parse_mode="HTML")


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
        "🚨 <b>Пожаловаться на видео</b>\n\nВыбери причину:",
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
        "💬 Опиши проблему (или отправь «-» чтобы пропустить):",
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
        await message.answer("❌ Не удалось отправить жалобу (возможно, жалоба на это видео уже была отправлена).")


@router.callback_query(ReportState.picking_reason, F.data == "report_cancel")
async def report_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Жалоба отменена.")
    await callback.answer()


@router.callback_query(F.data.startswith("block_author:"))
async def cb_block_author(callback: CallbackQuery):
    video_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        video = await get_video_by_id(session, video_id)
        if not user or not video:
            await callback.answer("Ошибка.")
            return
        
        if video.uploader_user_id == user.id:
            await callback.answer("Нельзя заблокировать самого себя.", show_alert=True)
            return

        success = await block_user(session, user.id, video.uploader_user_id)
        if success:
            await callback.answer("Автор заблокирован. Ты больше не увидишь его контент.", show_alert=True)
            # Можно предложить переключиться на следующее видео
            await callback.message.answer(
                "✅ Автор заблокирован. Ты больше не увидишь его видео и фото.\n"
                "Нажми «Следующее», чтобы продолжить просмотр других авторов.",
                reply_markup=video_error_keyboard() if video.content_type == "video" else photo_error_keyboard()
            )
        else:
            await callback.answer("Этот автор уже заблокирован для вас.", show_alert=True)


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
        "Загружайте видео и фото, выполняй офферы и приглашайте друзей по реферальной ссылке. Точные награды зависят от текущих настроек бота.\n\n"
        "<b>2. Как смотреть контент других авторов?</b>\n"
        "Нажми кнопку 🎬 Смотреть и выбери интересующий формат.\n\n"
        "<b>3. Что дает подписка VIP?</b>\n"
        "Множитель начисления монет ×2, скидка на просмотр видео, фото без дневного лимита и дополнительные бонусы в экономике. Размер скидки указан в разделе VIP.\n\n"
        "<b>4. Что такое Секслото?</b>\n"
        "Это ежедневный розыгрыш: каждый день в 20:00 по МСК бот вытягивает 6 бочонков из 36, а на каждый бочонок уходит около 15 секунд. 1 совпадение — без выигрыша, 2 совпадения дают 10 монет, 3 совпадения — 20 монет, а 4/5/6 совпадений делят основной призовой фонд.\n\n"
        "<b>5. Как общаться с ИИ?</b>\n"
        f"Нажми кнопку 💋 ИИ-общение. Одно сообщение стоит {AI_ASSISTANT_PRICE} монет.\n\n"
        "<b>6. Как работают промокоды?</b>\n"
        "Ты можешь создавать промокоды за Stars, активировать чужие и забирать еженедельную халяву.\n\n"
        "<b>7. Как работает реферальная система?</b>\n"
        f"Открой раздел 👥 Рефералы, скопируй свою ссылку и отправь друзьям. За активного приглашённого ты получаешь <b>+{REFERRAL_REWARD_INVITER}</b> монет.\n\n"
        "<b>8. Как работает еженедельная халява?</b>\n"
        "Каждую неделю выпадает новое секретное слово (в течение года слова не повторяются). Введи его в разделе 🎁 <b>Еженедельная Халява</b> (меню 🎟 Промокоды) и получи случайно от 200 до 1500 монет. Актуальное слово ищи в наших соцсетях!\n\n"
        "<b>9. Есть ли квесты?</b>\n"
        "Нет. Ежедневные квесты убраны из актуального UX, чтобы не захламлять меню.\n\n"
        "<b>10. Где посмотреть топы игроков?</b>\n"
        "В меню 🏆 Топы собраны текущие рейтинги загрузчиков, зрителей, XP и баланса. Рейтинг загрузчиков и зрителей считается за всё время.\n\n"
        "<b>11. Что находится внутри лутбоксов?</b>\n"
        "Случайный выигрыш монет разной степени редкости.\n\n"
        "<b>12. Как сменить никнейм?</b>\n"
        "В твоем Профиле. Первая установка ника бесплатна, последующие изменения — за монеты.\n\n"
        "<b>13. Что такое Уровень и XP?</b>\n"
        "За активность ты получаешь XP. Повышение уровня открывает приятную косметику и прогресс профиля.\n\n"
        "<b>14. Безопасны ли мои данные?</b>\n"
        "Бот не просит лишние персональные данные: используется в основном Telegram ID и сервисная информация профиля.\n\n"
        "<b>15. Что такое Космическая аркада?</b>\n"
        "Это мини-игра (Mini App) в разделе 🎮 Игры: делаете ставку, отбиваете волны инопланетного флота, и каждая волна увеличивает множитель ставки. Забрать выигрыш можно в любой момент, но рано или поздно флот прорвётся — и ставка сгорит. Есть дневной кап чистой прибыли.\n\n"
        "<b>16. Как связаться с техподдержкой?</b>\n"
        "Нажми кнопку 💬 Жалобы и предложения и отправь сообщение команде."
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

    await callback.message.answer(build_version_text(admin=admin_flag), parse_mode="HTML")
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
    """Секретное слово текущей ISO-недели.

    Реестр из 53 слов перемешивается детерминированным рандомом с сидом на
    текущий год: внутри года порядок случайный и слова НЕ повторяются
    (53 слова ≥ 53 недель, неделя N ↦ индекс N-1 перестановки), а с нового
    года — новая перестановка. Сид одинаков во всех процессах, поэтому слово
    стабильно без хранения состояния в БД.
    """
    import random as _random
    from app.models import utc_now
    iso = utc_now().isocalendar()
    year, week = iso[0], iso[1]
    words = FREEBIE_WORDS.copy()
    _random.Random(f"freebie-weekly-{year}").shuffle(words)
    return words[(week - 1) % len(words)]


@router.callback_query(F.data == "promo_freebie_start")
async def cb_promo_freebie_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    # Уже забирал халяву на этой неделе?
    from app.models import utc_now
    iso = utc_now().isocalendar()
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
    if user and user.last_freebie_week == iso[1] and user.last_freebie_year == iso[0]:
        await callback.message.answer(
            "🎁 <b>Еженедельная халява</b>\n\n"
            "Ты уже забирал награду на этой неделе! Возвращайся на следующей — слово будет новое. 😉",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="btn_promo_back")],
            ])
        )
        await callback.answer()
        return

    # Запускаем ввод секретного слова (обработка — в promo_activate_code)
    await state.set_state(PromoActivateState.waiting_code)
    await state.update_data(freebie_mode=True)
    await callback.message.answer(
        "🎁 <b>Еженедельная халява</b>\n\n"
        "Введи <b>секретное слово недели</b> (регистр не важен).\n"
        "Угадаешь — получишь случайную награду от 200 до 1500 монет!\n\n"
        "<i>Слово меняется каждую неделю и не повторяется в течение года.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
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
            await callback.answer("Стартовый лутбокс уже открыт!", show_alert=True)
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
