from html import escape
import os
import uuid
import math
import asyncio
import json
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN
from collections import defaultdict
from functools import wraps
from weakref import WeakValueDictionary

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
    ADMINS, WATCH_COST, XP_PER_WATCH, XP_PER_UPLOAD, XP_PER_RATING,
    XP_PER_COMMENT, XP_PER_REACTION, XP_PER_GAME,
    VIP_DURATION_DAYS, VIP_BONUS_MULTIPLIER, VIP_WATCH_DISCOUNT,
    LEVEL_XP_BASE, LEVEL_XP_MULTIPLIER,
    COMMENTS_PER_10_MIN,
    NICKNAME_CHANGE_COST, NICKNAME_MIN_LENGTH, NICKNAME_MAX_LENGTH,
    REFERRAL_REWARD_INVITER, REFERRAL_REWARD_NEW_USER, REFERRAL_MILESTONES, DAILY_PHOTO_LIMIT,
    PROMOCODE_MAX_AMOUNT, PROMOCODE_MAX_USES, PROMOCODE_MAX_HOURS,
    VIP_FREE_PROMO_PER_MONTH,
    VIP_FREE_PROMO_MAX_COINS,
    VIP_FREE_PROMO_MAX_USES,
    FIRST_PURCHASE_DAILY_BONUS,
    ENABLE_PROMOCODES,
    OFFER_ACTION_COOLDOWN_SECONDS,
    PROMO_ACTIVATE_COOLDOWN_SECONDS,
    ENABLE_LOTTERY,
    WEBHOOK_BASE,
    ENABLE_LOOTBOXES, LOOTBOX_COIN_PRICE, LOOTBOX_STAR_PRICE,
    LOTTERY_DRAW_HOUR_MSK, LOTTERY_SECONDS_PER_BALL,
)
from app.db import async_session
from app.models import (
    User, Video, VideoView, Comment, ContentReaction,
    Offer, Payment, Promocode,
    LootboxOpen, LotteryTicket, UserActionLog, DonationAlertOrder,
    AdminPoll, AdminPollResponse, utc_now,
)
from app.services import (
    get_or_create_user, get_user, get_user_by_id, get_video_by_id, reject_video, get_setting, save_video, save_photo,
    get_xp_multiplier, get_stars_discount,
    get_random_video_for_user, get_random_photo_for_user,
    record_view_and_charge_with_cost, refund_watch_and_unview, mark_content_broken,
    record_photo_view,
    rate_video, count_referrals,
    create_payment, create_custom_payment, apply_successful_payment,
    ensure_payment_pending, mark_payment_paid_once,
    get_payment_by_payload, stars_to_coins_amount,
    get_active_offers, get_offer_by_id,
    start_offer_participation, verify_offer_subscription, is_offer_available,
    normalize_telegram_url,
    change_balance_atomic, log_user_action, to_decimal,
    set_display_name, get_display_name, get_styled_display_name, log_balance_change,
    has_valid_nickname,
    check_daily_photo_limit,
    create_promocode, activate_promocode,
    calculate_promocode_star_cost, get_runtime_value,
    create_feedback, process_referral_reward,
    ensure_current_lottery_round, buy_lottery_tickets,
    get_unanswered_active_poll,
    get_latest_lottery_round, get_user_lottery_tickets, get_weekly_lottery_leaderboard, get_lottery_state_dict,
    get_lottery_draw_duration_seconds, get_lottery_max_tickets_for_balance,
    LOTTERY_MAX_TICKETS_PER_PURCHASE,
    classify_offer_url, notify_admins,
    is_admin_or_super, is_admin_free_eligible,
    should_show_low_balance_hint, mark_low_balance_hint_shown,
    can_show_offer_to_user, mark_offer_shown,
    get_random_active_offer, open_lootbox_for_stars,
    get_current_prices, get_active_events,
    get_shop_rub_packages, get_shop_star_packages, get_promocode_star_rate_effective,
    should_show_ad_after_video, increment_video_watched, reset_ad_counter,
    create_video_report, schedule_mod_notification, REPORT_REASONS,
    BLOCK_AUTHOR_REASONS, block_user, get_blocked_author_entries,
    count_blocked_authors, unblock_user, unblock_all_authors,
    is_starter_pack_eligible, count_views_today, maybe_send_zalip_upsell,
    check_daily_video_upload_possible,
    create_donationalerts_order, submit_admin_poll_response,
)
from app.selfcheck import run_selfcheck, format_selfcheck_report
from app.keyboards import (
    main_menu,
    video_rating_keyboard, photo_actions_keyboard,
    watch_choice_keyboard, donationalerts_order_keyboard,
    offers_list_keyboard, games_menu_keyboard,
    tops_menu_keyboard,
    reaction_menu_keyboard,
    low_balance_offer_keyboard,
    video_error_keyboard, photo_error_keyboard, photo_limit_reached_keyboard,
    poll_answer_keyboard,
    language_keyboard, menu_button_variants,
    # Кнопки главного меню матчатся по menu_button_variants() (все языки),
    # поэтому их константы здесь не нужны. Оставлены только кнопки вне меню.
    BTN_VIP, BTN_LEVEL, BTN_LOTTERY,
)
from app.i18n import current_language, get_user_language, normalize_language, t
from app.logger import get_logger
from app.release_notes import build_version_text
from app.rules_text import get_full_rules_text, get_short_rules_text
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
        lang = get_user_language(user)
    await message.answer(
        t(lang, "cancel.done"),
        reply_markup=main_menu(is_admin=admin_flag, lang=lang),
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
                await message.answer(t('🚫 Доступ к боту для тебя заблокирован.'))
                return
            result = await activate_promocode(session, user.id, promo_code)
            await message.answer(result)
            if not user.agreed_to_rules:
                from app.keyboards import rules_keyboard
                await message.answer(
                    get_short_rules_text(),
                    parse_mode="HTML",
                    reply_markup=rules_keyboard()
                )
                return
            admin_flag = is_any_admin(message.from_user.id, user)
            lang = get_user_language(user)
            vip_str = " 👑" if is_vip(user) else ""
            styled_name = await get_styled_display_name(session, user)
            await message.answer(
                t(lang, "welcome.greeting", name=styled_name, vip=vip_str, balance=user.balance),
                parse_mode="HTML",
                reply_markup=main_menu(is_admin=admin_flag, lang=lang)
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
            await message.answer(t('🚫 Доступ к боту для тебя заблокирован.'))
            return

        # Уведомление админам о новом пользователе уходит НЕ на первый /start,
        # а когда пользователь впервые установит себе ник (см. process_nickname).

        if not user.agreed_to_rules:
            from app.keyboards import rules_keyboard
            await message.answer(
                get_short_rules_text(),
                parse_mode="HTML",
                reply_markup=rules_keyboard()
            )
            return

        await send_welcome_banner(message, session, user)


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


class UserPollState(StatesGroup):
    waiting_text = State()
    selecting_multiple = State()


class BlockedAuthorsState(StatesGroup):
    browsing = State()
    waiting_search = State()


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


async def require_view_access(message: Message, user, session) -> bool:
    """Без валидного ника доступны только три просмотра суммарно."""
    if user.status == "banned":
        await message.answer(t('🚫 Доступ к боту для тебя заблокирован.'))
        return False
    if not user.agreed_to_rules:
        from app.keyboards import rules_keyboard
        await message.answer(get_short_rules_text(), parse_mode="HTML", reply_markup=rules_keyboard())
        return False
    if not has_valid_nickname(user):
        views = await session.scalar(
            select(func.count(VideoView.id)).where(VideoView.user_id == user.id)
        )
        if views >= 3:
            await message.answer(
                t('👀 Ты уже посмотрел 3 фото или видео без ника. Чтобы продолжить, установи ник — первая установка бесплатна.')
            )
            await require_nickname(message, user)
            return False
    return True


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
        t('{title}\n\n• От {NICKNAME_MIN_LENGTH} до {NICKNAME_MAX_LENGTH} символов\n• Только буквы (рус/лат), цифры, _ и -\n• Без точек, пробелов, ? и спецсимволов\n• Уникальный, не User&lt;id&gt;{extra}\n\nПервая установка / замена недопустимого ника — бесплатно!\nОбычная смена ника стоит {NICKNAME_CHANGE_COST} монет.', title=title, NICKNAME_MIN_LENGTH=NICKNAME_MIN_LENGTH, NICKNAME_MAX_LENGTH=NICKNAME_MAX_LENGTH, extra=extra, NICKNAME_CHANGE_COST=NICKNAME_CHANGE_COST),
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
            t('💳 <b>Первая успешная оплата</b>\nПользователь: <code>{telegram_id}</code>\nНик: {arg1}\nStars: <b>{stars}</b>\nPayload: <code>{arg3}</code>', telegram_id=user.telegram_id, arg1=escape(user.display_name or user.username or '—'), stars=stars, arg3=escape(payload)),
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
                t('🎉 Поздравляем! Ты достиг уровня <b>{new_level}</b>!', new_level=new_level),
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
        t('✏️ Введи ник ({cost_text}):\n\n• От {NICKNAME_MIN_LENGTH} до {NICKNAME_MAX_LENGTH} символов\n• Буквы (рус/лат), цифры, _ или -\n• Без точек, пробелов, ? и спецсимволов\n• Нельзя User&lt;id&gt; и ник только из цифр', cost_text=cost_text, NICKNAME_MIN_LENGTH=NICKNAME_MIN_LENGTH, NICKNAME_MAX_LENGTH=NICKNAME_MAX_LENGTH)
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
        had_valid_nick = has_valid_nickname(user)
        admin_free = await is_admin_free_eligible(session, message.from_user.id, user)
        ok, msg = await set_display_name(session, user, name, admin_free=admin_free)

    await message.answer(msg, parse_mode="HTML")
    if ok:
        await state.clear()
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            await send_welcome_banner(message, session, user)
        # Первый валидный ник = пользователь реально «появился» в боте.
        # Только теперь уведомляем админов о новом пользователе.
        if not had_valid_nick:
            try:
                username_line = f"Username: @{escape(message.from_user.username)}\n" if message.from_user.username else ""
                await notify_admins(
                    message.bot,
                    t('🆕 <b>Новый пользователь</b>\nID: <code>{id}</code>\n{username_line}Ник: <b>{arg2}</b>\nИмя: {arg3}', id=message.from_user.id, username_line=username_line, arg2=escape(user.display_name or '—'), arg3=escape(message.from_user.first_name or '—')),
                )
            except Exception:
                pass


# =========================
# START / RULES
# =========================
async def send_welcome_banner(message_or_callback, session, user):
    target = message_or_callback.message if isinstance(message_or_callback, CallbackQuery) else message_or_callback
    admin_flag = is_any_admin(user.telegram_id, user)
    lang = get_user_language(user)
    vip_str = " 👑" if is_vip(user) else ""
    styled_name = await get_styled_display_name(session, user)
    msg_text = t(
        lang, "welcome.greeting",
        name=styled_name, vip=vip_str, balance=user.balance,
    )
    if not has_valid_nickname(user):
        msg_text += "\n\n" + t(lang, "welcome.no_nickname_hint")
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
                reply_markup=main_menu(is_admin=admin_flag, lang=lang)
            )
        except Exception:
            await target.answer(
                msg_text,
                parse_mode="HTML",
                reply_markup=main_menu(is_admin=admin_flag, lang=lang)
            )
    elif os.path.exists("app/banner.jpg"):
        try:
            await target.answer_photo(
                photo=FSInputFile("app/banner.jpg"),
                caption=msg_text,
                parse_mode="HTML",
                reply_markup=main_menu(is_admin=admin_flag, lang=lang)
            )
        except Exception:
            await target.answer(
                msg_text,
                parse_mode="HTML",
                reply_markup=main_menu(is_admin=admin_flag, lang=lang)
            )
    else:
        await target.answer(
            msg_text,
            parse_mode="HTML",
            reply_markup=main_menu(is_admin=admin_flag, lang=lang)
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
            [InlineKeyboardButton(text=t('🎁 Открыть стартовый лутбокс'), callback_data="welcome_lootbox_claim")]
        ])
        await target.answer(
            t('🎁 <b>Подарок новичку!</b>\n\nЗабери бесплатный стартовый лутбокс. Внутри — красивое круглое число от 50 до 400 монет.\nЭто твой приветственный бонус на старт!'),
            parse_mode="HTML",
            reply_markup=lootbox_kb,
        )


@router.callback_query(F.data == "show_full_rules")
async def show_full_rules_callback(callback: CallbackQuery):
    await callback.message.answer(get_full_rules_text(), parse_mode="HTML")
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

        await send_welcome_banner(callback, session, user)
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
        lang = get_user_language(user)
    await callback.message.answer(
        t(lang, "main_menu.title"),
        parse_mode="HTML",
        reply_markup=main_menu(is_admin=admin_flag, lang=lang),
    )
    await callback.answer()


# =========================
# ЯЗЫК ИНТЕРФЕЙСА
# =========================
@router.message(F.text.in_(menu_button_variants("lang")))
async def cmd_language_menu(message: Message, state: FSMContext):
    """Кнопка «🌐 Язык» в главном меню — открывает выбор языка бота."""
    await state.clear()
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        lang = get_user_language(user)
        await log_user_action(session, user.id, "open_language_menu")
    await message.answer(
        t(lang, "lang.title"),
        parse_mode="HTML",
        reply_markup=language_keyboard(lang),
    )


@router.callback_query(F.data == "lang_menu")
async def cb_language_menu(callback: CallbackQuery):
    """Выбор языка по инлайн-кнопке (например, из профиля)."""
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        lang = get_user_language(user)
    await callback.message.answer(
        t(lang, "lang.title"),
        parse_mode="HTML",
        reply_markup=language_keyboard(lang),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("lang_set:"))
async def cb_language_set(callback: CallbackQuery):
    """Сохраняет выбранный язык и отвечает пользователю на этом языке."""
    parts = (callback.data or "").split(":", 1)
    lang = normalize_language(parts[1] if len(parts) > 1 else None)
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        user.language = lang
        await session.commit()
        admin_flag = is_any_admin(callback.from_user.id, user)
        await log_user_action(session, user.id, "set_language", lang)
    await callback.answer(t(lang, "lang.changed_alert"), show_alert=True)
    await callback.message.answer(
        t(lang, "main_menu.title"),
        parse_mode="HTML",
        reply_markup=main_menu(is_admin=admin_flag, lang=lang),
    )


@router.message(F.text.in_(menu_button_variants("admin")))
async def cmd_admin_redirect(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if is_any_admin(message.from_user.id, user):
            from app.admin_handlers import cmd_admin
            await cmd_admin(message)


# =========================
# PROFILE
# =========================
@router.message(F.text.in_(menu_button_variants("rules")))
async def show_rules(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(get_full_rules_text(), parse_mode="HTML")


@router.message(F.text.in_(menu_button_variants("profile")))
async def show_profile(message: Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if not await require_nickname(message, user):
            return

        lang = get_user_language(user)
        refs = await count_referrals(session, user.id)
        blocked_count = await count_blocked_authors(session, user.id)
        vip_str = ""
        if is_vip(user):
            vip_str = "\n" + t(lang, "profile.vip_until", date=user.vip_until.strftime('%d.%m.%Y'))

        level = user.level
        xp_spent = sum(calc_level_xp_required(lvl) for lvl in range(1, level))
        xp_current = user.xp - xp_spent
        xp_needed = calc_level_xp_required(level)
        progress = max(0, min(10, int((xp_current / max(xp_needed, 1)) * 10)))
        bar = "█" * progress + "░" * (10 - progress)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=t(lang, "profile.change_nick"),
                callback_data="set_nickname_start"
            )],
            [InlineKeyboardButton(
                text=t(lang, "menu.buy"),
                callback_data="store_menu"
            )],
            [InlineKeyboardButton(
                text=t(lang, "profile.blocked_authors", count=blocked_count),
                callback_data="blocked_authors:0"
            )],
            [InlineKeyboardButton(
                text=t(lang, "menu.lang"),
                callback_data="lang_menu"
            )]
        ])
        # Стилизованный ник (card-режим для профиля)
        styled_nick = await get_styled_display_name(session, user, card=True)
        text = (
            f"{t(lang, 'profile.title')}\n\n"
            f"{t(lang, 'profile.nick')}\n{styled_nick}\n\n"
            f"{t(lang, 'profile.telegram_id')} <code>{user.telegram_id}</code>\n"
            f"{t(lang, 'profile.balance', balance=user.balance)}\n"
            f"{t(lang, 'profile.level', level=user.level)}\n"
            f"{t(lang, 'profile.xp', current=xp_current, needed=xp_needed, bar=bar)}\n"
            f"{t(lang, 'profile.referrals', count=refs)}\n"
            f"{t(lang, 'profile.earned', amount=user.referral_earnings)}\n"
            f"{t(lang, 'profile.status', status=user.status)}"
            f"{vip_str}\n\n"
            f"{t(lang, 'profile.nick_cost', cost=NICKNAME_CHANGE_COST)}"
        )
        await message.answer(text, parse_mode="HTML", reply_markup=kb)
        await log_user_action(session, user.id, "view_profile")


_BLOCKED_AUTHORS_PAGE_SIZE = 8


async def _show_blocked_authors(
    callback: CallbackQuery,
    state: FSMContext,
    page: int,
) -> None:
    """Показывает пользователю только его персональный список скрытых авторов."""
    data = await state.get_data()
    search = " ".join((data.get("blocked_authors_search") or "").split())[:32]

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            return

        total = await count_blocked_authors(session, user.id, search=search)
        max_page = max(0, (total - 1) // _BLOCKED_AUTHORS_PAGE_SIZE)
        page = max(0, min(page, max_page))
        entries = await get_blocked_author_entries(
            session,
            user.id,
            limit=_BLOCKED_AUTHORS_PAGE_SIZE,
            offset=page * _BLOCKED_AUTHORS_PAGE_SIZE,
            search=search,
        )

    buttons = []
    for author, reason in entries:
        author_name = " ".join(get_display_name(author).split())[:42] or f"ID {author.telegram_id}"
        reason_label = BLOCK_AUTHOR_REASONS.get(reason or "other", "Другое")
        buttons.append([
            InlineKeyboardButton(
                text=f"✅ {author_name} · {reason_label}",
                callback_data=f"unblock_author:{author.id}:{page}",
            )
        ])

    search_note = f"\n🔎 Поиск: <code>{escape(search)}</code>" if search else ""
    if not entries:
        text = (
            "🚫 <b>Заблокированные авторы</b>\n\n"
            + (
                "По этому запросу авторов не найдено."
                if search else
                "Ты ещё никого не заблокировал. Здесь появятся авторы, скрытые тобой из ленты."
            )
        )
    else:
        first = page * _BLOCKED_AUTHORS_PAGE_SIZE + 1
        last = first + len(entries) - 1
        text = (
            "🚫 <b>Заблокированные авторы</b>\n\n"
            "Нажми на автора, чтобы снова видеть его контент в ленте.\n\n"
            f"Показано: <b>{first}–{last}</b> из <b>{total}</b>."
        )
    text += search_note

    buttons.append([InlineKeyboardButton(text=t('🔎 Найти автора'), callback_data="blocked_authors_search")])
    if entries:
        buttons.append([InlineKeyboardButton(text=t('🧹 Разблокировать всех'), callback_data="unblock_all_authors_confirm")])
    if search:
        buttons.append([InlineKeyboardButton(text=t('✖️ Сбросить поиск'), callback_data="blocked_authors_search_clear")])

    navigation = []
    if page > 0:
        navigation.append(InlineKeyboardButton(text="◀️", callback_data=f"blocked_authors:{page - 1}"))
    if page < max_page:
        navigation.append(InlineKeyboardButton(text="▶️", callback_data=f"blocked_authors:{page + 1}"))
    if navigation:
        buttons.append(navigation)
    buttons.append([InlineKeyboardButton(text=t('✖️ Закрыть'), callback_data="blocked_authors_close")])

    try:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise


@router.callback_query(F.data.startswith("blocked_authors:"))
async def cb_blocked_authors(callback: CallbackQuery, state: FSMContext):
    try:
        page = max(0, int(callback.data.rsplit(":", 1)[1]))
    except (TypeError, ValueError):
        await callback.answer(t('Некорректный запрос.'), show_alert=True)
        return

    await state.set_state(BlockedAuthorsState.browsing)
    await _show_blocked_authors(callback, state, page)
    await callback.answer()


@router.callback_query(F.data == "blocked_authors_search")
async def cb_blocked_authors_search(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BlockedAuthorsState.waiting_search)
    await callback.message.edit_text(
        t('🔎 <b>Поиск заблокированного автора</b>\n\nОтправь ник или имя автора. Поиск выполняется только в твоём списке блокировок.'),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t('✖️ Отмена'), callback_data="blocked_authors:0")]
        ]),
    )
    await callback.answer()


@router.message(BlockedAuthorsState.waiting_search)
async def process_blocked_authors_search(message: Message, state: FSMContext):
    search = " ".join((message.text or "").split())[:32]
    if not search:
        await message.answer(t('Введите ник или имя автора, либо воспользуйся отменой.'))
        return

    await state.update_data(blocked_authors_search=search)
    await state.set_state(BlockedAuthorsState.browsing)
    await message.answer(
        t('🔎 Поиск по списку блокировок: <code>{arg0}</code>', arg0=escape(search)),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t('Показать результаты'), callback_data="blocked_authors:0")]
        ]),
    )


@router.callback_query(F.data == "blocked_authors_search_clear")
async def cb_blocked_authors_search_clear(callback: CallbackQuery, state: FSMContext):
    await state.update_data(blocked_authors_search="")
    await state.set_state(BlockedAuthorsState.browsing)
    await _show_blocked_authors(callback, state, 0)
    await callback.answer()


@router.callback_query(F.data.startswith("unblock_author:"))
async def cb_unblock_author(callback: CallbackQuery, state: FSMContext):
    try:
        _, author_id_raw, page_raw = callback.data.split(":", 2)
        author_id = int(author_id_raw)
        page = max(0, int(page_raw))
    except (AttributeError, TypeError, ValueError):
        await callback.answer(t('Некорректный запрос.'), show_alert=True)
        return

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer(t('Пользователь не найден.'), show_alert=True)
            return
        success = await unblock_user(session, user.id, author_id)

    await callback.answer(
        "Автор разблокирован." if success else "Этот автор уже разблокирован.",
        show_alert=True,
    )
    await _show_blocked_authors(callback, state, page)


@router.callback_query(F.data == "unblock_all_authors_confirm")
async def cb_unblock_all_authors_confirm(callback: CallbackQuery):
    await callback.message.edit_text(
        t('🧹 <b>Разблокировать всех авторов?</b>\n\nВсе авторы из твоего списка снова появятся в ленте. Это действие нельзя отменить автоматически.'),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t('✅ Да, разблокировать всех'), callback_data="unblock_all_authors")],
            [InlineKeyboardButton(text=t('✖️ Отмена'), callback_data="blocked_authors:0")],
        ]),
    )
    await callback.answer()


@router.callback_query(F.data == "unblock_all_authors")
async def cb_unblock_all_authors(callback: CallbackQuery, state: FSMContext):
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer(t('Пользователь не найден.'), show_alert=True)
            return
        removed = await unblock_all_authors(session, user.id)

    await state.clear()
    await callback.answer(t('Разблокировано авторов: {removed}.', removed=removed), show_alert=True)
    await _show_blocked_authors(callback, state, 0)


@router.callback_query(F.data == "blocked_authors_close")
async def cb_blocked_authors_close(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await callback.answer()


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
                    t('👑 <b>Ты VIP!</b>\n\nДо: <b>{arg0}</b>\n\nПривилегии:\n• Множитель монет x{VIP_BONUS_MULTIPLIER}\n• Скидка {vip_discount_percent}% на просмотр\n• Приоритет и бонусы в экономике', arg0=user.vip_until.strftime('%d.%m.%Y %H:%M'), VIP_BONUS_MULTIPLIER=VIP_BONUS_MULTIPLIER, vip_discount_percent=vip_discount_percent),
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
                
                from app.services import get_runtime_value
                from app.config import VIP_PRICE_RUB
                vip_price_rub = int(float(await get_runtime_value(session, "vip_price_rub") or VIP_PRICE_RUB))
                await message.answer(
                    t('👑 <b>VIP статус через DonationAlerts</b>\n\n💰 Стоимость на 30 дней: <b>{vip_price_rub} руб.</b>{sale_badge}{admin_free_badge}\n\nПривилегии:\n• 🚀 Множитель монет x{VIP_BONUS_MULTIPLIER}\n• 🎬 Просмотр фото без дневного лимита\n• ⭐️ Скидка {vip_discount_percent}% на просмотр\n• 👑 Эксклюзивная плашка VIP в профиле\n\nНажмите кнопку ниже: бот создаст одноразовый код, который нужно вставить в поле «Сообщение» DonationAlerts вместе с точной суммой.', vip_price_rub=vip_price_rub, sale_badge=sale_badge, admin_free_badge=admin_free_badge, VIP_BONUS_MULTIPLIER=VIP_BONUS_MULTIPLIER, vip_discount_percent=vip_discount_percent),
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text=t('👑 Получить код VIP за {vip_price_rub} ₽', vip_price_rub=vip_price_rub), callback_data="da_order:vip_150")],
                        [InlineKeyboardButton(text=t('⭐️ Резерв: VIP за {vip_price} Stars', vip_price=vip_price), callback_data="buy_vip")],
                    ])
                )
    except Exception as e:
        import traceback
        err_detail = traceback.format_exc()
        logger.error(f"Error in show_vip: {err_detail}")
        await message.answer(t('⚠️ Ошибка при получении информации о VIP:\n<code>{arg0}</code>', arg0=escape(str(e))))


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
            t('👑 <b>VIP активирован бесплатно!</b>\n\n🆓 (ADMIN_FREE для админов)\nVIP до: <b>{arg0}</b>\n\nПривилегии:\n• Множитель монет x{VIP_BONUS_MULTIPLIER}\n• Скидка {vip_discount_percent}% на просмотр\n• Приоритет и бонусы в экономике', arg0=user.vip_until.strftime('%d.%m.%Y %H:%M'), VIP_BONUS_MULTIPLIER=VIP_BONUS_MULTIPLIER, vip_discount_percent=vip_discount_percent),
            parse_mode="HTML",
        )
        await callback.answer(t('🆓 VIP активирован бесплатно!'))


# =========================
# WATCH
# =========================
@router.message(F.text.in_(menu_button_variants("watch")))
async def btn_watch(message: Message, state: FSMContext):
    await state.clear()
    from app.services import is_admin_or_super
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if user.status == "banned":
            await message.answer(t('🚫 Доступ к боту для тебя заблокирован.'))
            return
        if not await require_view_access(message, user, session):
            return
        admin_flag = is_admin_or_super(message.from_user.id, user)
    await message.answer(t('👀 Что смотреть?'), reply_markup=watch_choice_keyboard(is_admin=admin_flag))


# Общая очередь фото/видео одного пользователя: двойной клик не обходит лимит.
_view_locks = WeakValueDictionary()


def _serialize_views(handler):
    @wraps(handler)
    async def wrapped(callback: CallbackQuery):
        key = callback.from_user.id
        lock = _view_locks.setdefault(key, asyncio.Lock())
        async with lock:
            return await handler(callback)
    return wrapped


@router.callback_query(F.data == "watch_video_content")
@_serialize_views
async def watch_video_content(callback: CallbackQuery):
    # Stop Telegram "loading" ASAP
    await _safe_callback_answer(callback)
    try:
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not user:
                return
            if not await require_view_access(callback.message, user, session):
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
                starter_ok = await is_starter_pack_eligible(session, user)
                if not starter_ok:
                    packs = {k: v for k, v in packs.items() if k != "starterpack"}
                suggested_pack = _suggest_viewer_pack(packs, need=missing + to_decimal(cost * 8))
                suggested_text = ""
                if starter_ok and "starterpack" in packs:
                    sp = packs["starterpack"]
                    suggested_text = (
                        f"\n🎁 <b>Первое пополнение — старт-пак:</b> {sp['coins']} монет "
                        f"всего за {sp['stars']} Stars! <i>(один раз и только для тебя)</i>"
                    )
                elif suggested_pack:
                    approx_views = int(float(suggested_pack.get("coins", 0)) // max(float(cost), 1.0))
                    suggested_text = (
                        f"\n⚡ <b>Быстрый вариант:</b> {suggested_pack['coins']} монет за {suggested_pack['stars']} Stars"
                        f" — хватит примерно на <b>{approx_views}</b> просмотров."
                    )
                if await should_show_low_balance_hint(session, user):
                    await mark_low_balance_hint_shown(session, user.id)
                    await callback.message.answer(
                        t('💸 <b>Монет не хватает</b>\n\nДля просмотра нужно: <b>{arg0}</b> монет\nУ тебя сейчас: <b>{arg1}</b> монет\nНе хватает: <b>{arg2}</b> монет\n{suggested_text}\n\nЧто можно сделать прямо сейчас:\n• <b>пополнить баланс</b> и сразу вернуться к просмотру\n• <b>взять оффер</b> и быстро добрать монеты\n• <b>позвать друга</b> и получить <b>+{arg4}</b> монет\n\nТвоя ссылка:\n<code>{ref_link}</code>', arg0=_fmt_coins(cost), arg1=_fmt_coins(user.balance), arg2=_fmt_coins(missing), suggested_text=suggested_text, arg4=_fmt_coins(REFERRAL_REWARD_INVITER), ref_link=ref_link),
                        parse_mode="HTML",
                        reply_markup=low_balance_offer_keyboard()
                    )
                else:
                    await callback.message.answer(
                        t('❌ <b>Недостаточно монет.</b>\n\nНужно: <b>{arg0}</b>, у тебя: <b>{arg1}</b>.{suggested_text}\n\nРеферальная ссылка:\n<code>{ref_link}</code>', arg0=_fmt_coins(cost), arg1=_fmt_coins(user.balance), suggested_text=suggested_text, ref_link=ref_link),
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
                        t('⚠️ <b>Не удалось начать просмотр.</b>\n\nВозможно, баланс изменился или это видео уже просмотрено.\nНажми кнопку ниже — попробуем другое видео.'),
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
                            t('🎬 Видео #{id}\n👤 Автор: <b>{uploader_name}</b>\n💰 Списано: {cost} монет', id=video.id, uploader_name=uploader_name, cost=cost)
                        ),
                        parse_mode="HTML",
                        reply_markup=video_rating_keyboard(
                            video.id,
                            is_admin=is_any_admin(callback.from_user.id, user),
                        )
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

                    # «Залип»-триггер: мягкий оффер первого платежа в момент вовлечённости
                    try:
                        views_today = await count_views_today(session, user.id)
                        await maybe_send_zalip_upsell(
                            session, callback.bot, user,
                            views_today=views_today,
                            reply_markup=low_balance_offer_keyboard(),
                        )
                    except Exception:
                        logger.exception("Zalip upsell failed (non-critical)")

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
                    t('😵\u200d💫 <b>Несколько видео подряд не удалось показать.</b>\n\nЭто временный сбой, проблемные ролики мы уже пометили.\nСледующее видео может быть совершенно рабочим — попробуйте ещё раз!'),
                    parse_mode="HTML",
                    reply_markup=video_error_keyboard(),
                )
            else:
                await callback.message.answer(
                    t('😔 <b>Пока нет новых видео для вас.</b>\n\nДоступный контент закончился!\nЗагрузи своё видео (кнопка 📤 Загрузить в меню), чтобы другие тоже смотрели.\nА пока можно посмотреть фото.'),
                    parse_mode="HTML",
                    reply_markup=video_error_keyboard(),
                )
    except Exception:
        logger.exception("watch_video_content failed")
        try:
            await callback.message.answer(
                t('🛠 <b>Не получилось показать видео.</b>\n\nПроизошёл кратковременный сбой — это не значит, что видео нет.\nПопробуй ещё раз, следующее должно открыться нормально.'),
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
            [InlineKeyboardButton(text=t('🛍 В магазин'), callback_data="btn_buy")],
            [InlineKeyboardButton(text=t('▶ Смотреть дальше'), callback_data="watch_video_content")],
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
                [InlineKeyboardButton(text=t('👉 Подписаться'), url=offer.channel_url)],
                [InlineKeyboardButton(text=t('▶ Смотреть дальше'), callback_data="watch_video_content")],
            ])
            await callback.message.answer(ad_text, parse_mode="HTML", reply_markup=kb)
            await reset_ad_counter(session, user.id)
            await log_user_action(session, user.id, "offer_ad_shown", f"offer={offer.id}")
            return

    # Если нет ни событий, ни офферов — предложим пройти активный опрос за награду
    try:
        poll = await get_unanswered_active_poll(session, user.id)
    except Exception:
        logger.exception("Poll ad lookup failed (non-critical)")
        poll = None
    if poll:
        try:
            options = json.loads(poll.options_json or "[]")
        except (TypeError, json.JSONDecodeError):
            options = []
        reward = int(Decimal(str(poll.reward or 100)))
        ad_text = (
            "📊 <b>Опрос от администрации</b>\n\n"
            f"{escape(poll.question)}\n\n"
            f"Пройди опрос один раз и получи <b>{reward} монет</b>."
        )
        kb = poll_answer_keyboard(poll.poll_type, poll.id, options)
        await callback.message.answer(ad_text, parse_mode="HTML", reply_markup=kb)
        await reset_ad_counter(session, user.id)
        await log_user_action(session, user.id, "poll_ad_shown", f"poll={poll.id}")
        return

    # Если нет ни событий, ни офферов, ни опросов — просто сбрасываем счётчик
    await reset_ad_counter(session, user.id)


@router.callback_query(F.data == "watch_next")
async def watch_next(callback: CallbackQuery):
    await watch_video_content(callback)


@router.callback_query(F.data == "watch_photo_content")
@_serialize_views
async def watch_photo_content(callback: CallbackQuery):
    await _safe_callback_answer(callback)
    try:
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not user:
                return
            if not await require_view_access(callback.message, user, session):
                return

            # Проверка дневного лимита фото для обычных пользователей
            if not is_vip(user):
                can_view = await check_daily_photo_limit(session, user.id)
                if not can_view:
                    await callback.message.answer(
                        t('📸 <b>Дневной лимит фото исчерпан ({DAILY_PHOTO_LIMIT} шт.).</b>\n\n👑 VIP-пользователи смотрят фото без ограничений.\nА видео можно смотреть без лимита — переходите туда!', DAILY_PHOTO_LIMIT=DAILY_PHOTO_LIMIT),
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
                            t('🖼 Фото #{id}\n👤 Автор: <b>{uploader_name}</b>', id=photo.id, uploader_name=uploader_name)
                        ),
                        parse_mode="HTML",
                        reply_markup=photo_actions_keyboard(
                            photo.id,
                            is_admin=is_any_admin(callback.from_user.id, user),
                        )
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
                    t('😵\u200d💫 <b>Несколько фото подряд не удалось показать.</b>\n\nВременный сбой — мы пометили проблемные фото.\nСледующее может открыться нормально, попробуйте ещё раз!'),
                    parse_mode="HTML",
                    reply_markup=photo_error_keyboard(),
                )
            else:
                await callback.message.answer(
                    t('😔 <b>Пока нет новых фото для вас.</b>\n\nДоступный контент закончился!\nЗагрузи своё фото (кнопка 📤 Загрузить в меню) или посмотри видео.'),
                    parse_mode="HTML",
                    reply_markup=photo_error_keyboard(),
                )
    except Exception:
        logger.exception("watch_photo_content failed")
        try:
            await callback.message.answer(
                t('🛠 <b>Не получилось показать фото.</b>\n\nКратковременный сбой — это не значит, что фото нет.\nПопробуй ещё раз или перейди к видео.'),
                parse_mode="HTML",
                reply_markup=photo_error_keyboard(),
            )
        except Exception:
            pass


@router.callback_query(F.data == "watch_next_photo")
async def watch_next_photo(callback: CallbackQuery):
    await watch_photo_content(callback)


@router.callback_query(F.data.startswith("admin_remove_from_feed:"))
async def admin_remove_from_feed_prompt(callback: CallbackQuery):
    """Запрашивает подтверждение снятия уже показанного контента из ленты."""
    try:
        video_id = int(callback.data.rsplit(":", 1)[1])
    except (AttributeError, TypeError, ValueError):
        await callback.answer(t('Некорректный запрос.'), show_alert=True)
        return

    async with async_session() as session:
        admin = await get_user(session, callback.from_user.id)
        video = await get_video_by_id(session, video_id)
        if not admin or not is_any_admin(callback.from_user.id, admin):
            await callback.answer(t('Доступно только администрации.'), show_alert=True)
            return
        if not video or video.status != "approved":
            await callback.answer(t('Контент уже снят с ленты или недоступен.'), show_alert=True)
            return

    await callback.message.answer(
        t('🗑 <b>Снять контент #{video_id} из ленты?</b>\n\nОн перестанет показываться новым зрителям, а автор получит уведомление без указания администратора.', video_id=video_id),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t('🗑 Да, снять из ленты'), callback_data=f"admin_confirm_remove_from_feed:{video_id}")],
            [InlineKeyboardButton(text=t('✖️ Отмена'), callback_data="admin_cancel_remove_from_feed")],
        ]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_confirm_remove_from_feed:"))
async def admin_remove_from_feed_confirm(callback: CallbackQuery):
    try:
        video_id = int(callback.data.rsplit(":", 1)[1])
    except (AttributeError, TypeError, ValueError):
        await callback.answer(t('Некорректный запрос.'), show_alert=True)
        return

    async with async_session() as session:
        admin = await get_user(session, callback.from_user.id)
        if not admin or not is_any_admin(callback.from_user.id, admin):
            await callback.answer(t('Доступно только администрации.'), show_alert=True)
            return
        video = await reject_video(session, video_id, "removed_from_feed_by_admin")
        if not video:
            await callback.answer(t('Контент уже снят с ленты или недоступен.'), show_alert=True)
            return
        author = await get_user_by_id(session, video.uploader_user_id)

    if author:
        try:
            await callback.bot.send_message(
                author.telegram_id,
                t('📢 Ваш контент #{video_id} снят администрацией с общей ленты.\n\nОн больше не будет показываться новым зрителям. Если вы считаете, что это ошибка, обратитесь в раздел «Жалобы и предложения».', video_id=video_id),
            )
        except Exception:
            pass

    await callback.message.edit_text(
        t('✅ Контент #{video_id} снят из ленты. Автор уведомлён.', video_id=video_id),
    )
    await callback.answer(t('Контент снят из ленты.'), show_alert=True)


@router.callback_query(F.data == "admin_cancel_remove_from_feed")
async def admin_remove_from_feed_cancel(callback: CallbackQuery):
    await callback.message.edit_text(t('❌ Снятие контента из ленты отменено.'))
    await callback.answer()


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
        ok, is_new, err = await rate_video(session, user.id, video_id, rating)
        if not ok:
            await callback.answer(err or "Не удалось оценить видео.", show_alert=True)
            return
        if is_new:
            xp_mult = await get_xp_multiplier(session, user.id)
            user.xp += int(XP_PER_RATING * xp_mult)
            await _level_up_check(session, user, callback)
            await session.commit()
            await _update_quest_progress(session, user.id, "rate", 1)

    await callback.answer(t('⭐ Оценка {rating} сохранена!', rating=rating))


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
            text=t('✏️ Написать'),
            callback_data=f"add_comment:{video_id}"
        )],
        [
            InlineKeyboardButton(
                text=t('😀 Реакции'),
                callback_data=f"reactions:{video_id}"
            ),
            InlineKeyboardButton(
                text=t('🚨 Жалоба'),
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
    await callback.message.answer(t('✏️ Напиши комментарий:'))
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
                t('⚠️ Не более {COMMENTS_PER_10_MIN} комментариев за 10 минут.', COMMENTS_PER_10_MIN=COMMENTS_PER_10_MIN)
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

    await message.answer(t('✅ Комментарий опубликован!'))
    await state.clear()


# =========================
# REACTIONS
# =========================
@router.callback_query(F.data.startswith("reactions:"))
async def cb_reactions_menu(callback: CallbackQuery):
    video_id = int(callback.data.split(":")[1])
    await callback.message.answer(
        t('Выбери реакцию:'),
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
                await callback.answer(t('❌ Эта реакция доступна только с перком «Эксклюзивные реакции»'), show_alert=True)
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

    await callback.answer(t('{reaction} Поставлена!', reaction=reaction))


# =========================
# UPLOAD
# =========================
@router.message(F.text.in_(menu_button_variants("upload")))
async def btn_upload(message: Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if user.status == "banned":
            await message.answer(t('🚫 Доступ к боту для тебя заблокирован.'))
            return
        if not await require_nickname(message, user):
            return
    await message.answer(
        t('📤 Отправь видео или фото.\n\nПосле проверки модератором ты получишь монеты!')
    )


@router.message(F.video)
async def handle_video_upload(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user or user.status == "banned":
            return
        if not user.agreed_to_rules:
            await message.answer(t('Примите правила командой /start'))
            return
        if not user.nickname_set:
            await require_nickname(message, user)
            return

        # Дневной лимит загрузок видео (админы — без ограничений)
        if not is_admin_or_super(message.from_user.id, user):
            allowed, done_today, limit = await check_daily_video_upload_possible(session, user.id)
            if not allowed:
                await message.answer(
                    t('📤 <b>Дневной лимит загрузок исчерпан.</b>\n\nСегодня ты уже загрузил {done_today} видео (лимит {limit} в сутки).\nВернись завтра — и спасибо за контент! 🙂', done_today=done_today, limit=limit),
                    parse_mode="HTML",
                )
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
                t('✅ Видео #{id} автоматически одобрено! (доверенный автор)\n+{arg1} монет', id=saved.id, arg1=_fmt_coins(reward))
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
            await message.answer(t('Примите правила командой /start'))
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
                t('✅ Фото #{id} автоматически одобрено! (доверенный автор)\n+{arg1} монет', id=saved.id, arg1=_fmt_coins(reward))
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


# =========================
# REFERRALS
# =========================
@router.message(F.text.in_(menu_button_variants("referrals")))
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
        t('👥 <b>Рефералы</b>\n\nПриглашай друзей и получай увеличенные бонусы.\n• друг получает на старте: <b>+{arg0}</b> монет\n• ты получаешь за активного друга: <b>+{arg1}</b> монет\n• активный друг — это 3 просмотра видео или фото\n• за 1, 3, 5 и 10 активных друзей открываются дополнительные этапы\n\nСтатусы реферала:\n• перешёл по ссылке\n• зарегистрировался\n• посмотрел контент и стал активным\n• награда начислена\n\nТвоя ссылка:\n<code>{ref_link}</code>\n\nПриглашено: <b>{refs}</b>\nЗаработано: <b>{arg4}</b> монет{milestone_text}', arg0=_fmt_coins(REFERRAL_REWARD_NEW_USER), arg1=_fmt_coins(REFERRAL_REWARD_INVITER), ref_link=ref_link, refs=refs, arg4=_fmt_coins(user.referral_earnings), milestone_text=milestone_text),
        parse_mode="HTML"
    )


# =========================
# BUY COINS
# =========================
async def _show_store(target: Message, user: User) -> None:
    """Единая витрина: пополнение, VIP и покупка привилегий за монеты."""
    vip_status = (
        f"активен до {user.vip_until.strftime('%d.%m.%Y')}"
        if is_vip(user) else
        "не активен"
    )
    text = (
        "🛍 <b>Магазин</b>\n\n"
        f"💰 Баланс: <b>{_fmt_coins(user.balance)}</b> монет\n"
        f"👑 VIP: <b>{vip_status}</b>\n\n"
        "Выберите нужный раздел: пополнение монет, VIP или оформление профиля."
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t('⭐ Пополнить монеты'), callback_data="show_stars_menu")],
        [InlineKeyboardButton(text=t('👑 VIP на 30 дней'), callback_data="store_vip")],
        [InlineKeyboardButton(text=t('💎 Стили и привилегии'), callback_data="donation_shop")],
        [InlineKeyboardButton(text=t('💳 Карта / СБП'), callback_data="btn_buy_callback")],
    ])
    await target.answer(text, parse_mode="HTML", reply_markup=keyboard)


@router.message(F.text.in_(menu_button_variants("buy")))
async def btn_store(message: Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user or not await require_nickname(message, user):
            return
        await _show_store(message, user)


@router.callback_query(F.data == "store_menu")
async def cb_store_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        await _show_store(callback.message, user)
    await callback.answer()


@router.callback_query(F.data == "store_vip")
async def cb_store_vip(callback: CallbackQuery):
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        vip_price, _, _ = await get_current_prices(session, user.id)
        discount = VIP_WATCH_DISCOUNT
        db_discount = await get_setting(session, "vip_watch_discount", "")
        if db_discount:
            try:
                discount = float(db_discount)
            except (TypeError, ValueError):
                pass
        discount_percent = max(0, min(100, round((1 - discount) * 100)))
        if is_vip(user):
            text = (
                f"👑 <b>VIP активен до {user.vip_until.strftime('%d.%m.%Y %H:%M')}</b>\n\n"
                f"• Множитель монет ×{VIP_BONUS_MULTIPLIER}\n"
                "• Фото без дневного лимита\n"
                f"• Скидка {discount_percent}% на просмотр"
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t('🛍 В магазин'), callback_data="store_menu")],
            ])
        else:
            text = (
                "👑 <b>VIP на 30 дней</b>\n\n"
                f"Стоимость: <b>{vip_price} Stars</b>\n\n"
                f"• Множитель монет ×{VIP_BONUS_MULTIPLIER}\n"
                "• Фото без дневного лимита\n"
                f"• Скидка {discount_percent}% на просмотр"
            )
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t('👑 Оформить за {vip_price} Stars', vip_price=vip_price), callback_data="buy_vip")],
                [InlineKeyboardButton(text=t('🛍 В магазин'), callback_data="store_menu")],
            ])
    await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


async def _show_legacy_donationalerts(message: Message, state: FSMContext):
    """Показывает выбор пакета (цены — актуальные, из настроек бота).

    Проверка пользователя и создание защищённого одноразового заказа происходят
    после выбора пакета.
    """
    await state.clear()
    try:
        async with async_session() as session:
            rub_packages = await get_shop_rub_packages(session)
    except Exception:
        logger.exception("Error while building DonationAlerts packages")
        await message.answer(t('⚠️ Не удалось загрузить пакеты. Попробуйте ещё раз через несколько секунд.'))
        return
    if not rub_packages:
        await message.answer(t('⚠️ Пакеты временно недоступны. Попробуйте ещё раз.'))
        return

    text = (
        "💳 <b>Пополнение через DonationAlerts</b>\n\n"
        "Выберите фиксированный пакет. После выбора бот создаст одноразовый "
        "код заказа: вставьте <b>только этот код</b> в поле «Сообщение» на странице оплаты. "
        "Так платёж автоматически и безопасно привяжется к вашему аккаунту.\n\n"
        "⚠️ Код действует ограниченное время, а сумма должна совпадать с выбранным пакетом."
    )
    rows = [
        [InlineKeyboardButton(text=f"{p_data['amount']} ₽ — {p_data['title']}", callback_data=f"da_order:{p_id}")]
        for p_id, p_data in rub_packages.items()
    ]
    rows.append([InlineKeyboardButton(text=t('🌐 Telegram Stars (резерв)'), callback_data="show_stars_menu")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data.startswith("da_order:"))
async def cb_create_donationalerts_order(callback: CallbackQuery):
    package_key = callback.data.split(":", 1)[1]
    async with async_session() as session:
        package = (await get_shop_rub_packages(session)).get(package_key)
        if not package:
            await callback.answer(t('Пакет не найден.'), show_alert=True)
            return
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        order = await create_donationalerts_order(
            session,
            user_id=user.id,
            amount_rub=package["amount"],
            reward_type=package.get("reward_type", "coins"),
            coins_amount=package["coins"],
        )

    expires_at = order.expires_at.strftime("%H:%M")
    await callback.message.answer(
        t('✅ <b>Заказ создан: {arg0}</b>\n\nСумма: <b>{arg1} ₽</b>\nКод заказа: <code>{order_code}</code>\n\n1️⃣ Нажмите «Перейти к оплате».\n2️⃣ Укажите точную сумму заказа.\n3️⃣ Вставьте код в поле «Сообщение» DonationAlerts.\n\nКод действует до <b>{expires_at}</b>. После подтверждённой оплаты награда зачислится автоматически.', arg0=package['title'], arg1=int(package['amount']), order_code=order.order_code, expires_at=expires_at),
        parse_mode="HTML",
        reply_markup=donationalerts_order_keyboard(order.order_code),
    )
    await callback.answer(t('Код заказа создан!'))


@router.callback_query(F.data.startswith("da_copy_order:"))
async def cb_copy_donationalerts_order(callback: CallbackQuery):
    code = callback.data.split(":", 1)[1]
    await callback.message.answer(
        t('📋 <b>Ваш код заказа DonationAlerts:</b>\n\n<code>{code}</code>\n\nСкопируйте его и вставьте в поле «Сообщение» на странице оплаты.', code=code),
        parse_mode="HTML",
    )
    await callback.answer(t('Код отправлен отдельным сообщением.'))


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy_pack(callback: CallbackQuery):
    pack_key = callback.data.split(":")[1]

    async with async_session() as session:
        base_pack = (await get_shop_star_packages(session)).get(pack_key)
        if not base_pack:
            await callback.answer(t('Пакет не найден.'), show_alert=True)
            return
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return

        if pack_key == "starterpack" and not await is_starter_pack_eligible(session, user):
            await callback.answer(t('Старт-пак доступен только первым платежом.'), show_alert=True)
            return

        _, current_packs, _ = await get_current_prices(session, user.id)
        current_pack = current_packs.get(pack_key)
        if not current_pack:
            await callback.answer(t('Пакет не найден.'), show_alert=True)
            return

        pack = base_pack

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
                t('✅ <b>Пополнение баланса</b>\n\n🆓 <b>ADMIN FREE</b> — бесплатно!\n\nПолучено: <b>{coins} монет</b>\nБонус первой покупки: +<b>{arg1} монет</b>\n\nТвой баланс: <b>{arg2}</b> монет', coins=coins, arg1=int(bonus), arg2=_fmt_coins(user.balance)),
                parse_mode="HTML",
            )
            await callback.answer(t('🆓 Пополнено бесплатно!'), show_alert=True)
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


@router.callback_query(F.data.startswith("copy_id:"))
async def cb_copy_id(callback: CallbackQuery):
    val = callback.data.split(":", 1)[1]
    await callback.message.answer(
        t('📋 <b>Ваш код для поля «Ваше сообщение» в DonationAlerts:</b>\n\n<code>{val}</code>\n\n<i>Нажмите на текст выше, чтобы скопировать его в один клик!</i>', val=val),
        parse_mode="HTML"
    )
    await callback.answer(t('ID скопирован в сообщение!'), show_alert=False)


@router.callback_query(F.data == "da_check_payment")
async def cb_da_check_payment(callback: CallbackQuery):
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return

        order = (await session.execute(
            select(DonationAlertOrder)
            .where(DonationAlertOrder.user_id == user.id)
            .order_by(DonationAlertOrder.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        if order:
            if order.status == "completed":
                await callback.answer(t('✅ Заказ оплачен и награда уже зачислена!'), show_alert=True)
                return
            if order.status == "pending" and order.expires_at >= utc_now():
                await callback.answer(
                    t('⏳ Заказ {order_code} ждёт подтверждения DonationAlerts. Проверьте точную сумму и код в поле «Сообщение».', order_code=order.order_code),
                    show_alert=True,
                )
                return
            if order.status == "pending":
                order.status = "expired"
                await session.commit()
            await callback.answer(t('⌛ Срок последнего заказа истёк. Создайте новый пакет в магазине.'), show_alert=True)
            return

        payment = (await session.execute(
            select(Payment)
            .where(Payment.user_id == user.id, Payment.payload.startswith("donationalerts_"))
            .order_by(Payment.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        if payment:
            await callback.answer(
                t('✅ Последний платёж от {arg0} успешно зачислен!', arg0=payment.created_at.strftime('%d.%m %H:%M')),
                show_alert=True,
            )
        else:
            await callback.answer(t('ℹ️ У вас пока нет созданного заказа DonationAlerts.'), show_alert=True)


@router.callback_query(F.data == "show_stars_menu")
async def cb_show_stars_menu(callback: CallbackQuery, state: FSMContext):
    # Отвечаем на callback до обращения к БД: Telegram не будет показывать
    # зависшую загрузку, даже если запрос цен временно медленный.
    await callback.answer()
    try:
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not user:
                await callback.message.answer(t('⚠️ Не удалось найти ваш профиль. Откройте магазин ещё раз.'))
                return
            _, packs, _ = await get_current_prices(session, user.id)
            starter_eligible = await is_starter_pack_eligible(session, user)
            if not starter_eligible:
                packs = {k: v for k, v in packs.items() if k != "starterpack"}
    except Exception:
        logger.exception("Error while building Telegram Stars packages")
        await callback.message.answer(
            t('⚠️ Не удалось загрузить пакеты Stars. Попробуйте ещё раз через несколько секунд.')
        )
        return

    buttons = [
        [InlineKeyboardButton(text=t('🔥 Купить в 9 раз дешевле через DonationAlerts'), callback_data="btn_buy_callback")]
    ]
    for p_id, p_data in packs.items():
        # Используем название пакета, чтобы старт-пак не выглядел как второй
        # «500 монет» по иной цене рядом с обычным пакетом на те же 500 монет.
        buttons.append([InlineKeyboardButton(text=f"⭐️ {p_data['title']} ({p_data['stars']} Stars)", callback_data=f"buy:{p_id}")])
    buttons.append([InlineKeyboardButton(text=t('✏️ Другая сумма (Stars)'), callback_data="buy_custom_stars")])
    buttons.append([InlineKeyboardButton(text=t('👈 Назад к выгодной оплате'), callback_data="btn_buy_callback")])

    text = (
        "⭐️ <b>Пополнение через Telegram Stars (Резервный раздел)</b>\n\n"
        "⚠️ <b>ВНИМАНИЕ:</b> Из-за комиссий App Store / Google Play и Telegram, "
        "цена при оплате через Stars <b>в 9 раз выше</b>, чем через DonationAlerts.\n\n"
        "💡 <i>Рекомендуем оплачивать через DonationAlerts — это в 9 раз дешевле, без комиссий и зачисляется моментально с любой карты или СБП!</i>\n\n"
        "Выберите пакет Stars:"
    )
    await callback.message.answer(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data == "buy_custom_stars")
async def cb_buy_custom_stars(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CustomBuyState.waiting_stars)
    await callback.message.answer(
        t('✏️ <b>Кастомное пополнение Stars</b>\\n\\nВведите количество Stars, на которое хотите пополнить баланс.\\nМонеты будут начислены по актуальному курсу магазина.')
    )
    await callback.answer()


@router.callback_query(F.data == "btn_buy_callback")
async def cb_btn_buy_callback(callback: CallbackQuery, state: FSMContext):
    # Снимаем индикатор загрузки Telegram сразу: показ пакетов может занять
    # время из-за обращения к БД, но пользователь не должен видеть зависшую кнопку.
    await callback.answer()
    await _show_legacy_donationalerts(callback.message, state)


@router.callback_query(F.data == "buy_vip_stars")
async def cb_buy_vip_stars(callback: CallbackQuery):
    await buy_vip(callback)


@router.message(CustomBuyState.waiting_stars)
async def process_custom_stars(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer(t('❌ Введи целое число.'))
        return
    stars = int(message.text)
    if stars < 1:
        await message.answer(t('❌ Минимум 1 Star.'))
        return

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await state.clear()
            return

        # Admin free — выдаём монеты без оплаты
        if await is_admin_free_eligible(session, message.from_user.id, user):
            coins = int(await stars_to_coins_amount(session, stars))
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
                t('✅ <b>Пополнение баланса</b>\n\n🆓 <b>ADMIN FREE</b> — бесплатно!\n\nПолучено: <b>{coins} монет</b>\nБонус первой покупки: +<b>{arg1} монет</b>\n\nТвой баланс: <b>{arg2}</b> монет', coins=coins, arg1=int(bonus), arg2=_fmt_coins(user.balance)),
                parse_mode="HTML",
            )
            await state.clear()
            return

        discount = await get_stars_discount(session, user.id)
        billed_stars = max(1, int(math.ceil(stars * (1 - discount)))) if discount > 0 else stars
        payment = await create_custom_payment(session, user.id, stars, billed_stars_amount=billed_stars)
        coins = int(await stars_to_coins_amount(session, stars))

    await message.answer_invoice(
        title=f"Покупка {coins} монет",
        description=f"{coins} монет за {billed_stars} Stars",
        payload=payment.payload,
        currency="XTR",
        prices=[LabeledPrice(label=t('{coins} монет', coins=coins), amount=billed_stars)]
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
        await query.answer(ok=False, error_message=t('Неверный платёжный payload.'))
        return
    async with async_session() as session:
        user = await get_user(session, query.from_user.id)
        if not user:
            await query.answer(ok=False, error_message=t('Пользователь не найден.'))
            return
        payment = await get_payment_by_payload(session, payload)
        if not payment:
            await query.answer(ok=False, error_message=t('Платёж не найден.'))
            return
        if payment.user_id != user.id:
            await query.answer(ok=False, error_message=t('Платёж принадлежит другому пользователю.'))
            return
        if payment.status != "pending":
            await query.answer(ok=False, error_message=t('Платёж уже обработан.'))
            return
        if int(payment.stars_amount) != int(query.total_amount):
            await query.answer(ok=False, error_message=t('Сумма платежа не совпадает.'))
            return
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    paid_stars = int(message.successful_payment.total_amount)

    if payload.startswith("vip_"):
        parts = payload.split("_")
        if len(parts) < 3 or not parts[1].isdigit() or int(parts[1]) != message.from_user.id:
            await message.answer(t('Ошибка платежа: некорректный payload.'))
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
                    await message.answer(t('Ошибка платежа: пользователь не совпадает.'))
                    return
                if int(payment.stars_amount) != paid_stars:
                    await session.rollback()
                    session.expunge_all()
                    await message.answer(t('Ошибка платежа: сумма не совпадает.'))
                    return
                if not await mark_payment_paid_once(session, payload):
                    await session.rollback()
                    session.expunge_all()
                    await message.answer(t('✅ Платёж уже был обработан ранее.'))
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
            t('👑 VIP активирован на {VIP_DURATION_DAYS} дней!', VIP_DURATION_DAYS=VIP_DURATION_DAYS)
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
                await message.answer(t('Ошибка платежа: некорректный payload.'))
                return
            async with async_session() as session:
                user = await get_user(session, creator_tg_id)
                if not user or user.telegram_id != message.from_user.id:
                    await message.answer(t('Ошибка платежа: пользователь не найден.'))
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
                    await message.answer(t('Ошибка платежа: пользователь не совпадает.'))
                    return
                if int(payment.stars_amount) != paid_stars:
                    await session.rollback()
                    session.expunge_all()
                    await message.answer(t('Ошибка платежа: сумма не совпадает.'))
                    return
                if not await mark_payment_paid_once(session, payload):
                    await session.rollback()
                    session.expunge_all()
                    await message.answer(t('✅ Платёж уже был обработан ранее.'))
                    return
                promo, cost, error = await create_promocode(
                    session, creator_tg_id,
                    to_decimal(amount), uses, hours,
                    auto_commit=False,
                    is_paid=True,
                    stars_paid=paid_stars,
                )
                if error:
                    await session.rollback()
                    session.expunge_all()
                    await message.answer(t('❌ Ошибка создания промокода: {error}', error=error))
                else:
                    promo.stars_paid = paid_stars
                    await session.commit()
                    if await _is_first_paid_payment(session, user.id):
                        await _notify_admins_about_first_payment(message.bot, user, stars=paid_stars, payload=payload)
                    bot = await message.bot.get_me()
                    await message.answer(
                        t('✅ Промокод создан:\n<code>{code}</code>\nСумма: {amount} монет, использований: {uses}/{max_uses}\nСсылка: t.me/{username}?start=promo_{code}\n\n⚠️ Поделись ссылкой с другом. Активировать собственный промокод нельзя.', code=promo.code, amount=amount, uses=uses, max_uses=promo.max_uses, username=bot.username),
                        parse_mode="HTML"
                    )
        else:
            await message.answer(t('Ошибка платежа.'))
    elif payload.startswith("lootbox_"):
        parts = payload.split("_")
        if len(parts) < 3 or not parts[1].isdigit() or int(parts[1]) != message.from_user.id:
            await message.answer(t('Ошибка платежа: некорректный payload.'))
            return
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                await message.answer(t('⚠️ Пользователь не найден.'))
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
                await message.answer(t('Ошибка платежа: пользователь не совпадает.'))
                return
            if int(payment.stars_amount) != paid_stars:
                await session.rollback()
                session.expunge_all()
                await message.answer(t('Ошибка платежа: сумма не совпадает.'))
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
                    await message.answer(t('⚠️ Пользователь не найден.'))
                    return

                payment = await get_payment_by_payload(session, payload)
                if not payment or payment.user_id != user.id:
                    await message.answer(t('Ошибка платежа: платёж не найден или принадлежит другому пользователю.'))
                    return
                if int(payment.stars_amount) != paid_stars:
                    await message.answer(t('Ошибка платежа: сумма не совпадает.'))
                    return
                if not await mark_payment_paid_once(session, payload):
                    await session.rollback()
                    session.expunge_all()
                    await message.answer(t('✅ Платёж уже был обработан ранее.'))
                    return

                offer = await session.get(Offer, offer_id)
                if not offer or offer.creator_user_id != user.id:
                    await session.rollback()
                    session.expunge_all()
                    await message.answer(t('Ошибка платежа: оффер не найден или не принадлежит тебе.'))
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
                        t('📣 <b>Новый оффер после оплаты</b>\nАвтор: <code>{telegram_id}</code>\nНазвание: <b>{arg1}</b>\nТип цели: {arg2}\nСтатус: отправлен на модерацию\n\nОткрыть очередь: /admin', telegram_id=user.telegram_id, arg1=escape(offer.title), arg2=classify_offer_url(offer.channel_url)['label']),
                    )
                except Exception:
                    pass

                await message.answer(
                    t('✅ Оплата прошла успешно! Твой оффер отправлен на модерацию.\nОн появится в списке, как только администратор его одобрит.')
                )
        except Exception:
            logger.exception("Failed to process paid user offer")
            await message.answer(t('⚠️ Не удалось обработать оплату оффера. Администраторы уже могут проверить журнал ошибок.'))
    else:
        notify_first_payment = False
        notify_user = None
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                await message.answer(t('⚠️ Пользователь не найден.'))
                return
            payment_row = await get_payment_by_payload(session, payload)
            if not payment_row or payment_row.user_id != user.id:
                await message.answer(t('Ошибка платежа: не найден в системе.'))
                return
            if int(payment_row.stars_amount) != paid_stars:
                await message.answer(t('Ошибка платежа: сумма не совпадает.'))
                return
            payment, credited_total = await apply_successful_payment(session, payload)
            if payment and await _is_first_paid_payment(session, user.id):
                notify_first_payment = True
                notify_user = user
        if payment:
            if notify_first_payment and notify_user is not None:
                await _notify_admins_about_first_payment(message.bot, notify_user, stars=paid_stars, payload=payload)
            await message.answer(
                t('✅ Оплата успешна!\n💰 Начислено: <b>{arg0}</b> монет', arg0=_fmt_coins(credited_total)),
                parse_mode="HTML"
            )
        else:
            await message.answer(t('✅ Оплата получена!'))


def _lootbox_kb(coin_price: Decimal | None = None, star_price: int | None = None, user_level: int = 1) -> InlineKeyboardMarkup:
    from app.config import WEBHOOK_BASE
    base = (WEBHOOK_BASE or "").rstrip("/")
    cases_url = f"{base}/cases?lang={current_language()}" if base else ""
    
    coin_price = to_decimal(coin_price if coin_price is not None else LOOTBOX_COIN_PRICE)
    star_price = int(star_price if star_price is not None else LOOTBOX_STAR_PRICE)
    
    kb = []
    if cases_url:
        from aiogram.types.web_app_info import WebAppInfo
        kb.append([InlineKeyboardButton(text=t('🔥 ОТКРЫТЬ С АНИМАЦИЕЙ (Mini App)'), web_app=WebAppInfo(url=cases_url))])
        
    kb.extend([
        [InlineKeyboardButton(
            text=f"🪙 Обычный кейс ({coin_price:,.0f} монет)".replace(',', ' '),
            callback_data="lootbox_buy:coins:common"
        )],
        [InlineKeyboardButton(
            text=t('⭐ Обычный кейс ({star_price} Stars)', star_price=star_price),
            callback_data="lootbox_buy:stars"
        )],
        [InlineKeyboardButton(
            text=t('🎨 Кейс ников (250+ монет)'),
            callback_data="styles_lootbox_menu"
        )],
    ])
    
    if user_level >= 10:
        kb.append([InlineKeyboardButton(
            text=t('💎 Элитный кейс (1 000 монет)'),
            callback_data="lootbox_buy:coins:elite"
        )])
    if user_level >= 20:
        kb.append([InlineKeyboardButton(
            text=t('🔥 Легендарный кейс (5 000 монет)'),
            callback_data="lootbox_buy:coins:legendary"
        )])
        
    return InlineKeyboardMarkup(inline_keyboard=kb)


@router.callback_query(F.data == "lootbox_menu")
async def lootbox_menu(callback: CallbackQuery):
    if not ENABLE_LOOTBOXES:
        await callback.message.answer(t('⛔ Лутбоксы временно отключены.'))
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
        await callback.answer(t('Лутбоксы отключены.'), show_alert=True)
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
                await callback.answer(t('🆓 Лутбокс открыт бесплатно!'))
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
                await callback.answer(t('🆓 Лутбокс открыт бесплатно!'))
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
            prices=[LabeledPrice(label=t('Лутбокс'), amount=star_price)],
        )
        await callback.answer()
        return

    await callback.answer()



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
        
    kb.append([InlineKeyboardButton(text=t('🎲 ОТКРЫТЬ ({current_price:.0f} монет)', current_price=current_price), callback_data="styles_case_open")])
    kb.append([InlineKeyboardButton(text=t('◀️ Назад'), callback_data="lootbox_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _styles_list_kb(cat_id: int, excluded_ids: list[int]) -> InlineKeyboardMarkup:
    from app.nick_styles import STYLES_BY_CAT
    kb = []
    cat_styles = STYLES_BY_CAT[cat_id]
    
    # По 2 стиля в ряд
    row = []
    for s in cat_styles:
        status = "❌" if s.id in excluded_ids else "✅"
        row.append(InlineKeyboardButton(
            text=f"{status} {t(s.label)}", 
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
    kb.append([InlineKeyboardButton(text=t('◀️ К категориям'), callback_data="styles_lootbox_menu_refresh")])
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
    name = t(name)
    
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
    
    from app.nick_styles import STYLES
    
    if style_id in excluded_ids:
        excluded_ids.remove(style_id)
    else:
        # Safeguard: cannot exclude ALL styles
        if len(excluded_ids) >= len(STYLES) - 1:
            await callback.answer(t('В кейсе должен остаться хотя бы один стиль!'), show_alert=True)
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
                 await callback.answer(t('Нельзя исключить все стили!'), show_alert=True)
                 return
             # Исключаем только часть? Нет, лучше просто запретить.
             await callback.answer(t('Нельзя исключить все стили в боте!'), show_alert=True)
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


@router.callback_query(F.data == "btn_buy")
async def cb_btn_buy(callback: CallbackQuery, state: FSMContext):
    # Точки входа из рекламы и low-balance сценариев ведут в единый магазин.
    await btn_store(callback.message, state)  # type: ignore
    await callback.answer()

# =========================
# OFFERS
# =========================
@router.message(F.text.in_(menu_button_variants("offers")))
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
        t('📢 <b>Офферы</b>\n\nВыбери раздел:'),
        parse_mode="HTML",
        reply_markup=user_offers_menu()
    )


@router.callback_query(F.data == "offers_participation")
async def offers_participation(callback: CallbackQuery):
    async with async_session() as session:
        offers = await get_active_offers(session)

    if not offers:
        await callback.message.answer(t('😔 Активных офферов нет.'))
        await callback.answer()
        return

    await callback.message.answer(
        t('📢 <b>Офферы для участия</b>\n\nВыбери оффер:'),
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
            await callback.answer(t('Оффер больше не активен.'), show_alert=True)
            return

        from sqlalchemy import select as sa_select
        from app.models import OfferParticipation
        participants = (await session.execute(
            sa_select(func.count(OfferParticipation.id)).where(
                OfferParticipation.offer_id == offer_id
            )
        )).scalar_one()

    target_meta = classify_offer_url(offer.channel_url)
    target_url = normalize_telegram_url(offer.channel_url)
    if not target_url:
        await callback.answer(t('У оффера некорректная ссылка. Сообщи администратору.'), show_alert=True)
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

    kb_rows = [
        [InlineKeyboardButton(
            text=target_meta["cta"],
            url=target_url
        )],
        [InlineKeyboardButton(
            text=t('▶️ Участвовать'),
            callback_data=f"offer_start_confirm:{offer_id}"
        )],
        [InlineKeyboardButton(
            text=target_meta["claim_text"],
            callback_data=f"offer_check:{offer_id}"
        )],
    ]
    kb_rows.append([InlineKeyboardButton(
        text=t('◀️ Назад'),
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
            await callback.answer(t('Оффер больше не активен.'), show_alert=True)
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
        [InlineKeyboardButton(text=t('✅ Понятно, участвовать'), callback_data=f"offer_start:{offer_id}")],
        [InlineKeyboardButton(text=t('❌ Отмена'), callback_data=f"offer_open:{offer_id}")],
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
        await callback.answer(t('⏳ Слишком часто. Попробуй через пару секунд.'), show_alert=True)
        return
    offer_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        part, is_new = await start_offer_participation(session, user.id, offer_id)
        if part is None:
            await callback.answer(t('Оффер не найден.'), show_alert=True)
            return
        if not is_new:
            await callback.answer(t('Ты уже участвуешь!'), show_alert=True)
            return
        offer = await get_offer_by_id(session, offer_id)

    paid = to_decimal(part.reward_given)
    target_meta = classify_offer_url(offer.channel_url)
    cap_note = "" if paid == to_decimal(offer.reward_preview) else "\n⚠️ Сработал дневной лимит наград."
    next_step = "Открой проект и потом нажми кнопку подтверждения." if not target_meta["auto_verify"] else "Подпишитесь и нажми кнопку проверки."
    await callback.answer(
        t('✅ Получено {paid} монет!\n{next_step}{cap_note}', paid=paid, next_step=next_step, cap_note=cap_note),
        show_alert=True
    )


@router.callback_query(F.data.startswith("offer_check:"))
async def cb_offer_check(callback: CallbackQuery):
    if not _cooldown_ok(
        _offer_action_last_ts,
        (callback.from_user.id, "offer_check"),
        OFFER_ACTION_COOLDOWN_SECONDS,
    ):
        await callback.answer(t('⏳ Слишком часто. Попробуй через пару секунд.'), show_alert=True)
        return
    offer_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        offer = await get_offer_by_id(session, offer_id)
        if not is_offer_available(offer):
            await callback.answer(t('Оффер больше не активен.'), show_alert=True)
            return
        target_meta = classify_offer_url(offer.channel_url)
        if target_meta["auto_verify"]:
            if not await _check_user_offer_subscription(callback, offer):
                await callback.answer(
                    t('❌ Подписка не найдена. Подпишитесь на проект и попробуйте снова.'),
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
                t('❌ Не удалось подтвердить участие.'),
                show_alert=True
            )


@router.callback_query(F.data == "btn_offers_back")
async def btn_offers_back(callback: CallbackQuery):
    from app.user_offer_handlers import user_offers_menu
    await callback.message.answer(
        t('📢 <b>Офферы</b>\n\nВыбери раздел:'),
        parse_mode="HTML",
        reply_markup=user_offers_menu()
    )
    await callback.answer()


# =========================
# GAMES (с игровыми сессиями)
# =========================
@router.message(F.text.in_(menu_button_variants("games")))
async def btn_games(message: Message, state: FSMContext):
    await state.clear()

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if not await require_nickname(message, user):
            return

    await message.answer(
        t('🎮 <b>Игровой центр</b>\n\nВыбери раздел:'),
        parse_mode="HTML",
        reply_markup=games_menu_keyboard()
    )


@router.callback_query(F.data == "game_pay_session")
async def game_pay_session(callback: CallbackQuery):
    await callback.answer(
        t('Продление игровой сессии больше не требуется: в меню остались только Секслото и лутбоксы.'),
        show_alert=True,
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


# =========================
# TOPS
# =========================
@router.message(F.text.in_(menu_button_variants("tops")))
async def btn_tops(message: Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if not await require_nickname(message, user):
            return
    await message.answer(
        t('🏆 <b>Топы</b>'),
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
        t('⏳ Подождите ещё немного...'),
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
                    text=t('✅ Я подписался — получить монеты'),
                    callback_data=f"offer_start:{offer_id}"
                )],
                [InlineKeyboardButton(
                    text=t('▶️ Смотреть видео'),
                    callback_data="watch_video_content"
                )],
            ])
            await callback.message.answer(
                t('💡 Кстати, за подписку на <b>{title}</b> можно получить <b>{reward_preview} монет</b>!\nХочешь заработать?', title=offer.title, reward_preview=offer.reward_preview),
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
    await callback.answer(t('Хорошо! Офферы всегда доступны в меню 💰'))


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
    live_url = f"{base}/lottery/live?lang={current_language()}" if base else ""

    buttons = []
    if live_url:
        from aiogram.types.web_app_info import WebAppInfo
        buttons.append([InlineKeyboardButton(text=t('🔴 Открыть Live (Mini App)'), web_app=WebAppInfo(url=live_url))])
    else:
        buttons.append([InlineKeyboardButton(text=t('🔴 Как открыть Live'), callback_data="lottery_live_info")])

    buttons.extend([
        [InlineKeyboardButton(text=t('🎫 Купить билеты'), callback_data="lottery_buy")],
        [InlineKeyboardButton(text=t('📋 Мои билеты'), callback_data="lottery_my_tickets")],
        [InlineKeyboardButton(text=t('🏆 Рейтинг недели'), callback_data="lottery_weekly_leaderboard")],
        [InlineKeyboardButton(text=t('🔄 Обновить'), callback_data="lottery_menu")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _lottery_buy_kb(max_count: int) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="1", callback_data="lottery_buy_qty:1"),
            InlineKeyboardButton(text="5", callback_data="lottery_buy_qty:5"),
            InlineKeyboardButton(text="10", callback_data="lottery_buy_qty:10"),
        ],
        [InlineKeyboardButton(text=t('🎯 Максимум ({max_count})', max_count=max_count), callback_data="lottery_buy_max")],
        [InlineKeyboardButton(text=t('✏️ Ввести количество'), callback_data="lottery_buy_custom")],
        [InlineKeyboardButton(text=t('◀️ Назад'), callback_data="lottery_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_lottery_menu(message_or_callback_message: Message, telegram_user_id: int | None = None) -> None:
    if not ENABLE_LOTTERY:
        await message_or_callback_message.answer(t('⛔ Секслото временно отключено.'))
        return

    async with async_session() as session:
        round_obj = await ensure_current_lottery_round(session)
        state_data = get_lottery_state_dict(round_obj)
        if telegram_user_id is None:
            telegram_user_id = getattr(getattr(message_or_callback_message, "from_user", None), "id", None)
        user = await get_user(session, telegram_user_id) if telegram_user_id else None

    base = (WEBHOOK_BASE or "").rstrip("/")
    live_url = f"{base}/lottery/live?lang={current_language()}" if base else ""

    try:
        draw_line = t(
            "Следующий розыгрыш: <b>{time_str}</b>",
            time_str=format_time_for_user(round_obj.draw_starts_at, getattr(user, 'timezone', None)),
        )
    except Exception:
        draw_line = t("Следующий розыгрыш скоро стартует в live-режиме.")

    status_map = {
        "open": t("приём билетов открыт"),
        "drawing": t("идёт розыгрыш"),
        "completed": t("розыгрыш завершён"),
    }
    status_text = status_map.get(state_data.get("status"), str(state_data.get("status")))

    draw_date_msk = (round_obj.draw_starts_at + timedelta(hours=3)).strftime("%d.%m.%Y")
    duration_seconds = get_lottery_draw_duration_seconds(round_obj.numbers_per_ticket)
    minutes = duration_seconds // 60
    seconds = duration_seconds % 60
    duration_text = (
        t("{minutes} мин {seconds} сек", minutes=minutes, seconds=seconds)
        if minutes
        else t("{seconds} сек", seconds=seconds)
    )
    drawn_text = ", ".join(map(str, state_data.get("drawn_numbers", []))) or t("пока ничего")

    text = t(
        "🎰 <b>Секслото</b>\n\n"
        "📅 <b>Розыгрыш:</b> {draw_date}\n"
        "📌 <b>Статус:</b> {status_text}\n"
        "🎟 <b>Цена билета:</b> {ticket_price} монет\n"
        "💰 <b>Призовой фонд:</b> {prize_pool} монет\n"
        "🔵 <b>Уже выпало:</b> {drawn_text}\n\n"
        "<b>Как это работает:</b>\n"
        "• в одном билете — <b>{per_ticket} чисел из {pool}</b>\n"
        "• каждый день в <b>{hour}:00 по МСК</b> начинается розыгрыш\n"
        "• на каждый бочонок уходит около <b>{ball_seconds} секунд</b>, весь розыгрыш длится примерно <b>{duration_text}</b>\n"
        "• <b>1 совпадение — не выигрыш</b>\n"
        "• <b>2 совпадения — 10 монет</b>\n"
        "• <b>3 совпадения — 20 монет</b>\n"
        "• <b>4, 5 и 6 совпадений</b> делят основной призовой фонд\n"
        "• призовой фонд делится так: <b>6 совпадений — 70%</b>, <b>5 совпадений — 20%</b>, <b>4 совпадения — 10%</b>\n"
        "• если в одной категории несколько выигрышных билетов, её доля делится между ними поровну\n"
        "• каждую неделю действует <b>рейтинг активности</b> с дополнительными призами для топ-3 игроков\n\n"
        "{live_line}"
        "{draw_line}\n\n"
        "Нажми «🎫 Купить билеты», чтобы выбрать количество билетов, или открой Live и следи за розыгрышем в реальном времени.",
        draw_date=draw_date_msk,
        status_text=status_text,
        ticket_price=_fmt_coins(state_data.get('ticket_price')),
        prize_pool=_fmt_coins(state_data.get('prize_pool')),
        drawn_text=drawn_text,
        per_ticket=round_obj.numbers_per_ticket,
        pool=round_obj.numbers_pool,
        hour=LOTTERY_DRAW_HOUR_MSK,
        ball_seconds=LOTTERY_SECONDS_PER_BALL,
        duration_text=duration_text,
        live_line=(
            t("🔴 <b>Live:</b> <a href=\"{live_url}\">открыть трансляцию</a>\n", live_url=live_url)
            if live_url
            else ""
        ),
        draw_line=draw_line,
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
        await callback.answer(t('⛔ Лотерея отключена.'), show_alert=True)
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
        await callback.answer(t('⛔ Лотерея отключена.'), show_alert=True)
        return

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        round_obj = await ensure_current_lottery_round(session)
        now = utc_now()
        if round_obj.status != "open" or now >= round_obj.draw_starts_at:
            await callback.answer(t('Продажа билетов закрыта до следующего розыгрыша.'), show_alert=True)
            return

        admin_free = await is_admin_free_eligible(session, callback.from_user.id, user)
        max_count = LOTTERY_MAX_TICKETS_PER_PURCHASE if admin_free else get_lottery_max_tickets_for_balance(user.balance, to_decimal(round_obj.ticket_price))
        if max_count <= 0:
            await callback.answer(t('Недостаточно монет. Билет стоит {ticket_price}.', ticket_price=round_obj.ticket_price), show_alert=True)
            return

        await state.clear()
        await state.set_state(LotteryBuyState.waiting_quantity)
        await callback.message.answer(
            t('🎫 <b>Покупка билетов</b>\n\nЦена одного билета: <b>{arg0}</b> монет\nСейчас можно купить до: <b>{max_count}</b> билет(ов)\n\nВыбери количество, нажми «Максимум» или введи своё число.', arg0=_fmt_coins(round_obj.ticket_price), max_count=max_count),
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
            await callback.answer(t('Пользователь не найден.'), show_alert=True)
            return
        round_obj = await ensure_current_lottery_round(session)
        admin_free = await is_admin_free_eligible(session, callback.from_user.id, user)
        quantity = LOTTERY_MAX_TICKETS_PER_PURCHASE if admin_free else get_lottery_max_tickets_for_balance(user.balance, to_decimal(round_obj.ticket_price))
    if quantity <= 0:
        await callback.answer(t('Сейчас нельзя купить ни одного билета.'), show_alert=True)
        return
    ok, msg = await _lottery_buy_execute(callback.message, callback.from_user.id, quantity, is_callback=True)
    await callback.answer(msg, show_alert=not ok)
    if ok:
        await state.clear()


@router.callback_query(F.data == "lottery_buy_custom")
async def lottery_buy_custom(callback: CallbackQuery, state: FSMContext):
    await state.set_state(LotteryBuyState.waiting_quantity)
    await callback.message.answer(t('✏️ Введи количество билетов, которое хочешь купить:'))
    await callback.answer()


@router.message(LotteryBuyState.waiting_quantity)
async def lottery_buy_custom_input(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    if not value.isdigit():
        await message.answer(t('❌ Введи целое число билетов.'))
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
        await callback.answer(t('⛔ Лотерея отключена.'), show_alert=True)
        return
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        round_obj = await get_latest_lottery_round(session)
        tickets = await get_user_lottery_tickets(session, user.id, round_obj.id if round_obj else None, limit=20)
    if not tickets:
        await callback.message.answer(t('😔 У тебя пока нет билетов в текущем раунде.'))
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
        await callback.message.answer(t('🏆 Пока нет недельного рейтинга — как только появятся участники, здесь появится таблица лидеров.'))
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
        text = t(
            "🔴 <b>Live-розыгрыш Секслото</b>\n\n"
            "Live пока недоступен: владелец бота ещё не настроил публичный адрес Mini App."
        )
    else:
        live_url = f"{base}/lottery/live?lang={current_language()}"
        text = t(
            "🔴 <b>Live-розыгрыш Секслото</b>\n\n"
            "В прямом эфире ты увидишь, как лототрон по очереди вытягивает все бочонки.\n"
            "Открыть Live: {live_url}",
            live_url=live_url,
        )
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


# =========================
# ЖАЛОБЫ И ПРЕДЛОЖЕНИЯ
# =========================
@router.message(F.text.in_(menu_button_variants("feedback")))
async def feedback_start(message: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t('🐞 Сообщить о баге'), callback_data="feedback_kind:bug")],
        [InlineKeyboardButton(text=t('💡 Предложить идею'), callback_data="feedback_kind:suggestion")],
        [InlineKeyboardButton(text=t('❤️ Поблагодарить команду'), callback_data="feedback_kind:praise")],
    ])
    await message.answer(
        t('💬 <b>Жалобы и предложения</b>\n\nНапиши нам бесплатно: о баге, идее или просто поддержке.\nМы читаем все обращения.'),
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
        await callback.answer(t('Неизвестный тип обращения.'), show_alert=True)
        return
    await state.set_state(FeedbackState.waiting_text)
    await state.update_data(feedback_kind=kind)
    await callback.message.answer(
        t('✍️ Тип: <b>{kind_title}</b>\n\nОпиши твоё сообщение одним текстом (5-2000 символов).', kind_title=kind_title),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(FeedbackState.waiting_text)
async def feedback_submit(message: Message, state: FSMContext):
    text_value = (message.text or "").strip()
    if len(text_value) < 5:
        await message.answer(t('Сообщение слишком короткое. Минимум 5 символов.'))
        return
    if len(text_value) > 2000:
        await message.answer(t('Сообщение слишком длинное. Максимум 2000 символов.'))
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
                    t('💬 <b>Новое обращение пользователя</b>\n\nТип: <b>{kind_title}</b>\nОбращение: <code>#{id}</code>\nПользователь: {author_name}\nTG ID: <code>{id2}</code>\n\n{arg4}', kind_title=kind_title, id=feedback.id, author_name=author_name, id2=message.from_user.id, arg4=escape(text_value))
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    await message.answer(
        t('✅ Спасибо! Твойе обращение отправлено команде.\nЕсли нужно, мы свяжемся с тебеи в Telegram.')
    )
    await state.clear()


# =========================
# ПРОМОКОДЫ (НОВЫЙ РАЗДЕЛ)
# =========================
@router.message(F.text.in_(menu_button_variants("promo")))
async def btn_promo(message: Message, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if not await require_nickname(message, user):
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t('🎟 Создать промокод'), callback_data="promo_create")],
            [InlineKeyboardButton(text=t('🔑 Активировать промокод'), callback_data="promo_activate")],
            [InlineKeyboardButton(text=t('🎁 Еженедельная Халява'), callback_data="promo_freebie_start")],
            [InlineKeyboardButton(text=t('📋 Мои промокоды'), callback_data="promo_my")],
        ])
        rate = await get_promocode_star_rate_effective(session)
        max_free_coins = int(await get_runtime_value(session, "vip_free_promo_max_coins") or VIP_FREE_PROMO_MAX_COINS)
        max_free_uses = int(await get_runtime_value(session, "vip_free_promo_max_uses") or VIP_FREE_PROMO_MAX_USES)
        await message.answer(
            t('🎟 <b>Промокоды</b>\n\nСоздай код на монеты и поделись им с друзьями!\nСтоимость создания: ≈ <b>{rate:.2f} Stars</b> за 1 монету × использования.\nЦена пересчитывается от актуального прайса магазина — промокод не может быть дешевле магазина.\nVIP: {VIP_FREE_PROMO_PER_MONTH} бесплатный код в месяц (до {max_free_coins} монет, {max_free_uses} исп.).\n⚠️ Активировать свой собственный промокод нельзя — промокоды предназначены для друзей.', rate=rate, VIP_FREE_PROMO_PER_MONTH=VIP_FREE_PROMO_PER_MONTH, max_free_coins=max_free_coins, max_free_uses=max_free_uses),
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
            t('Введи сумму монет (1–{PROMOCODE_MAX_AMOUNT}):', PROMOCODE_MAX_AMOUNT=PROMOCODE_MAX_AMOUNT)
        )
    await callback.answer()


@router.message(PromoCreateState.waiting_amount)
async def promo_amount(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer(t('Введи число.'))
        return
    amount = int(message.text)
    if amount < 1 or amount > PROMOCODE_MAX_AMOUNT:
        await message.answer(t('От 1 до {PROMOCODE_MAX_AMOUNT}.', PROMOCODE_MAX_AMOUNT=PROMOCODE_MAX_AMOUNT))
        return
    await state.update_data(promo_amount=amount)
    await state.set_state(PromoCreateState.waiting_uses)
    await message.answer(t('Количество использований (1–{PROMOCODE_MAX_USES}):', PROMOCODE_MAX_USES=PROMOCODE_MAX_USES))


@router.message(PromoCreateState.waiting_uses)
async def promo_uses(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer(t('Введи число.'))
        return
    uses = int(message.text)
    if uses < 1 or uses > PROMOCODE_MAX_USES:
        await message.answer(t('От 1 до {PROMOCODE_MAX_USES}.', PROMOCODE_MAX_USES=PROMOCODE_MAX_USES))
        return
    await state.update_data(promo_uses=uses)
    await state.set_state(PromoCreateState.waiting_hours)
    await message.answer(t('Срок действия в часах (1–{PROMOCODE_MAX_HOURS}):', PROMOCODE_MAX_HOURS=PROMOCODE_MAX_HOURS))


@router.message(PromoCreateState.waiting_hours)
async def promo_hours(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer(t('Введи число.'))
        return
    hours = int(message.text)
    if hours < 1 or hours > PROMOCODE_MAX_HOURS:
        await message.answer(t('От 1 до {PROMOCODE_MAX_HOURS}.', PROMOCODE_MAX_HOURS=PROMOCODE_MAX_HOURS))
        return
    data = await state.get_data()
    amount = data["promo_amount"]
    uses = data["promo_uses"]

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await state.clear()
            return
        # Цена пересчитывается от актуального прайса магазина (floor + markup):
        # промокод всегда дороже (или равен) покупке тех же монет в магазине.
        star_cost = await calculate_promocode_star_cost(session, to_decimal(amount), uses)
        admin_free = is_admin_or_super(message.from_user.id, user)
        if admin_free:
            promo, _, error = await create_promocode(session, message.from_user.id,
                                                      to_decimal(amount), uses, hours,
                                                      admin_free=True)
            if error:
                await message.answer(error)
            else:
                await message.answer(
                    t('✅ Промокод создан (админ-режим):\n<code>{code}</code>\nСумма: {amount} монет, использований: {uses}/{max_uses}\nСсылка: t.me/{username}?start=promo_{code}\n\n⚠️ Поделись ссылкой с пользователями. Активировать собственный промокод нельзя.', code=promo.code, amount=amount, uses=uses, max_uses=promo.max_uses, username=(await message.bot.get_me()).username),
                    parse_mode="HTML"
                )
            await state.clear()
            return

        # VIP бесплатный (строго в пределах лимита)
        max_free_coins = int(await get_runtime_value(session, "vip_free_promo_max_coins") or VIP_FREE_PROMO_MAX_COINS)
        max_free_uses = int(await get_runtime_value(session, "vip_free_promo_max_uses") or VIP_FREE_PROMO_MAX_USES)
        is_vip_user = is_vip(user)
        has_free_left = is_vip_user and (getattr(user, "promo_created_this_month", 0) or 0) < VIP_FREE_PROMO_PER_MONTH
        within_limits = (amount * uses) <= max_free_coins and uses <= max_free_uses

        if has_free_left and within_limits:
            promo, cost, error = await create_promocode(session, message.from_user.id,
                                                         to_decimal(amount), uses, hours)
            if error:
                await message.answer(error)
            else:
                await message.answer(
                    t('✅ Бесплатный VIP-промокод:\n<code>{code}</code>\nСумма: {amount} монет, использований: {uses}\nОсталось бесплатных в этом месяце: {arg3}\n\n⚠️ Поделись кодом с другом! Активировать собственный промокод нельзя.', code=promo.code, amount=amount, uses=uses, arg3=VIP_FREE_PROMO_PER_MONTH - user.promo_created_this_month),
                    parse_mode="HTML"
                )
            await state.clear()
            return

        if has_free_left and not within_limits:
            await message.answer(
                t('ℹ️ Бесплатный VIP-промокод ограничен: максимум <b>{max_free_coins}</b> монет и <b>{max_free_uses}</b> исп.\nТвой запрос ({amount} монет × {uses} исп.) превышает лимит бесплатного кода и оформляется как платный через Stars.', max_free_coins=max_free_coins, max_free_uses=max_free_uses, amount=amount, uses=uses),
                parse_mode="HTML"
            )

        # Платный – выставляем инвойс.
        # ВАЖНО: скидка за перк на цену промокода НЕ применяется — floor
        # уже считает от базового прайса магазина, а пересдача кода
        # пользователю без скидки должна оставаться невыгодной.
        payload = f"promo_{message.from_user.id}_{amount}_{uses}_{hours}_{uuid.uuid4().hex[:4]}"
        await ensure_payment_pending(
            session,
            user_id=user.id,
            payload=payload,
            stars_amount=star_cost,
        )
        await session.commit()
        await message.answer_invoice(
            title="Создание промокода",
            description=f"{amount} монет × {uses} исп. на {hours}ч",
            payload=payload,
            currency="XTR",
            prices=[LabeledPrice(label=t('Промокод'), amount=star_cost)]
        )
    await state.clear()


@router.callback_query(F.data == "promo_activate")
async def promo_activate_start(callback: CallbackQuery, state: FSMContext):
    if not ENABLE_PROMOCODES:
        await callback.answer(t('⛔ Промокоды временно отключены.'), show_alert=True)
        return
    await state.set_state(PromoActivateState.waiting_code)
    await callback.message.answer(t('Введи промокод:'))
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
                t('❌ <b>Неверное секретное слово!</b>\n\nУбедись, что ты правильно ввёл слово (регистр не важен), или поищи актуальное слово в наших соцсетях!'),
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
            from sqlalchemy import update, or_
            current_week = utc_now().isocalendar()[1]
            current_year = utc_now().isocalendar()[0]
            
            # Атомарно помечаем получение халявы на этой неделе
            claim_res = await session.execute(
                update(User)
                .where(
                    User.id == user.id,
                    or_(
                        User.last_freebie_week != current_week,
                        User.last_freebie_year != current_year,
                        User.last_freebie_week.is_(None),
                        User.last_freebie_year.is_(None),
                    )
                )
                .values(last_freebie_week=current_week, last_freebie_year=current_year)
            )
            if claim_res.rowcount == 0:
                await message.answer(t('❌ Халява уже была получена на этой неделе!'))
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
            await session.commit()
            
        await message.answer(
            t('🎉 <b>Секретное слово угадано!</b>\n\nТебе начислено <b>{reward:.0f}</b> монет!\nПриходите в следующий понедельник за новой Халявой! 🎁', reward=reward),
            parse_mode="HTML"
        )
        await state.clear()
        return

    if not ENABLE_PROMOCODES:
        await message.answer(t('⛔ Промокоды временно отключены.'))
        await state.clear()
        return
    if not _cooldown_ok(
        _promo_activate_last_ts,
        message.from_user.id,
        PROMO_ACTIVATE_COOLDOWN_SECONDS,
    ):
        await message.answer(t('⏳ Слишком часто. Попробуй чуть позже.'))
        return
    code = (message.text or "").strip()
    if not code:
        await message.answer(t('Введи промокод.'))
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
        await callback.answer(t('⛔ Промокоды временно отключены.'), show_alert=True)
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
            await callback.message.answer(t('📭 У тебя пока нет промокодов.'))
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
    kb_rows.append([InlineKeyboardButton(text=t('❌ Отмена'), callback_data="report_cancel")])

    await callback.message.answer(
        t('🚨 <b>Пожаловаться на видео</b>\n\nВыбери причину:'),
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
        t('💬 Опиши проблему (или отправь «-» чтобы пропустить):'),
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
        await message.answer(t('✅ Жалоба отправлена. Администрация разберётся.'))
    else:
        await message.answer(t('❌ Не удалось отправить жалобу (возможно, жалоба на это видео уже была отправлена).'))


@router.callback_query(ReportState.picking_reason, F.data == "report_cancel")
async def report_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(t('❌ Жалоба отменена.'))
    await callback.answer()


@router.callback_query(F.data.startswith("block_author:"))
async def cb_block_author(callback: CallbackQuery):
    try:
        video_id = int(callback.data.split(":", 1)[1])
    except (AttributeError, TypeError, ValueError):
        await callback.answer(t('Некорректный запрос.'), show_alert=True)
        return

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        video = await get_video_by_id(session, video_id)
        if not user or not video:
            await callback.answer(t('Контент больше недоступен.'), show_alert=True)
            return
        if video.uploader_user_id == user.id:
            await callback.answer(t('Нельзя заблокировать самого себя.'), show_alert=True)
            return
        author = await get_user_by_id(session, video.uploader_user_id)
        author_name = escape(get_display_name(author)) if author else "этого автора"

    await callback.message.answer(
        t('🚫 <b>Скрыть {author_name} из ленты?</b>\n\nВыбери причину — она нужна только для твоего управления списком блокировок.', author_name=author_name),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t('🚫 Спам'), callback_data=f"confirm_block_author:{video_id}:spam")],
            [InlineKeyboardButton(text=t('🙈 Неинтересно'), callback_data=f"confirm_block_author:{video_id}:not_interesting")],
            [InlineKeyboardButton(text=t('❓ Другое'), callback_data=f"confirm_block_author:{video_id}:other")],
            [InlineKeyboardButton(text=t('✖️ Отмена'), callback_data="block_author_cancel")],
        ]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_block_author:"))
async def cb_confirm_block_author(callback: CallbackQuery):
    try:
        _, video_id_raw, reason = callback.data.split(":", 2)
        video_id = int(video_id_raw)
    except (AttributeError, TypeError, ValueError):
        await callback.answer(t('Некорректный запрос.'), show_alert=True)
        return
    if reason not in BLOCK_AUTHOR_REASONS:
        await callback.answer(t('Некорректная причина.'), show_alert=True)
        return

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        video = await get_video_by_id(session, video_id)
        if not user or not video:
            await callback.answer(t('Контент больше недоступен.'), show_alert=True)
            return
        if video.uploader_user_id == user.id:
            await callback.answer(t('Нельзя заблокировать самого себя.'), show_alert=True)
            return
        author = await get_user_by_id(session, video.uploader_user_id)
        success = await block_user(
            session,
            user.id,
            video.uploader_user_id,
            reason=reason,
        )

    if not success:
        await callback.answer(t('Этот автор уже заблокирован для вас.'), show_alert=True)
        return

    # Показываем факт скрытия автору, но не раскрываем личность блокировавшего.
    # Так уведомление не превращается в инструмент давления или травли.
    if author:
        try:
            await callback.bot.send_message(
                author.telegram_id,
                t('ℹ️ Один из пользователей скрыл ваш профиль из личной ленты.\n\nЭто не влияет на доступ к боту или ваши публикации и не раскрывает, кто принял такое решение.'),
            )
        except Exception:
            pass

    next_keyboard = video_error_keyboard() if video.content_type == "video" else photo_error_keyboard()
    next_keyboard.inline_keyboard.insert(0, [
        InlineKeyboardButton(
            text=t('↩️ Отменить блокировку'),
            callback_data=f"undo_block_author:{video.uploader_user_id}",
        )
    ])
    await callback.message.edit_text(
        t('✅ Автор заблокирован. Ты больше не увидишь его видео и фото.\n\nЕсли это произошло случайно, нажми «Отменить блокировку».'),
        reply_markup=next_keyboard,
    )
    await callback.answer(t('Автор заблокирован.'), show_alert=True)


@router.callback_query(F.data.startswith("undo_block_author:"))
async def cb_undo_block_author(callback: CallbackQuery):
    try:
        author_id = int(callback.data.split(":", 1)[1])
    except (AttributeError, TypeError, ValueError):
        await callback.answer(t('Некорректный запрос.'), show_alert=True)
        return

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer(t('Пользователь не найден.'), show_alert=True)
            return
        success = await unblock_user(session, user.id, author_id)

    if success:
        rows = [
            [button for button in row if not (button.callback_data or "").startswith("undo_block_author:")]
            for row in (callback.message.reply_markup.inline_keyboard if callback.message.reply_markup else [])
        ]
        rows = [row for row in rows if row]
        await callback.message.edit_text(
            t('↩️ Блокировка отменена. Контент автора снова будет появляться в ленте.'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None,
        )
    await callback.answer(
        "Блокировка отменена." if success else "Автор уже разблокирован.",
        show_alert=True,
    )


@router.callback_query(F.data == "block_author_cancel")
async def cb_block_author_cancel(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await callback.answer(t('Блокировка отменена.'))


# ====================================================
# ЕЖЕДНЕВНЫЙ БОНУС, ЛОТЕРЕЯ, ПРОМОКОДЫ ТЕМПЛЕЙТЫ И ХАЛЯВА
# ====================================================
@router.message(F.text.in_(menu_button_variants("faq")))
async def btn_faq(message: Message, state: FSMContext):
    await state.clear()
    
    faq_text = (
        "ℹ️ <b>Часто задаваемые вопросы (FAQ) и Помощь</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>1. Как зарабатывать монеты?</b>\n"
        "Загружайте видео и фото, выполняй офферы и приглашайте друзей по реферальной ссылке. А ещё просто заходи каждый день — бот сам начислит бонус за серию дней подряд! Точные награды зависят от текущих настроек бота.\n\n"
        "<b>2. Как смотреть контент других авторов?</b>\n"
        "Нажми кнопку 🎬 Смотреть и выбери интересующий формат.\n\n"
        "<b>3. Что дает подписка VIP?</b>\n"
        "Множитель начисления монет ×2, скидка на просмотр видео, фото без дневного лимита и дополнительные бонусы в экономике. VIP оформляется в разделе 🛍 Магазин.\n\n"
        "<b>4. Что такое Секслото?</b>\n"
        "Это ежедневный розыгрыш: каждый день в 20:00 по МСК бот вытягивает 6 бочонков из 36, а на каждый бочонок уходит около 15 секунд. 1 совпадение — без выигрыша, 2 совпадения дают 10 монет, 3 совпадения — 20 монет, а 4/5/6 совпадений делят основной призовой фонд.\n\n"
        "<b>5. Где пополнить баланс, оформить VIP или выбрать стиль?</b>\n"
        "Всё находится в разделе 🛍 Магазин: монеты, VIP и стили профиля собраны в одном месте.\n\n"
        "<b>6. Как работают промокоды?</b>\n"
        "Ты можешь создавать промокоды за Stars, активировать чужие и забирать еженедельную халяву.\n\n"
        "<b>7. Как работает реферальная система?</b>\n"
        f"Открой раздел 👥 Рефералы, скопируй свою ссылку и отправь друзьям. За активного приглашённого ты получаешь <b>+{REFERRAL_REWARD_INVITER}</b> монет.\n\n"
        "<b>8. Как работает еженедельная халява?</b>\n"
        "Каждую неделю выпадает новое секретное слово (в течение года слова не повторяются). Введи его в разделе 🎁 <b>Еженедельная Халява</b> (меню 🎟 Промокоды) и получи случайно от 200 до 1500 монет. Секретное слово бот присылает сам — следи за еженедельной рассылкой!\n\n"
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
        [InlineKeyboardButton(text=t('🤖 Версия бота и Изменения'), callback_data="bot_version_info")]
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
            t('🎁 <b>Еженедельная халява</b>\n\nТы уже забирал награду на этой неделе! Возвращайся на следующей — слово будет новое. 😉'),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t('◀️ Назад'), callback_data="btn_promo_back")],
            ])
        )
        await callback.answer()
        return

    # Запускаем ввод секретного слова (обработка — в promo_activate_code)
    await state.set_state(PromoActivateState.waiting_code)
    await state.update_data(freebie_mode=True)
    await callback.message.answer(
        t('🎁 <b>Еженедельная халява</b>\n\nВведи <b>секретное слово недели</b> (регистр не важен).\nУгадаешь — получишь случайную награду от 200 до 1500 монет!\n\n<i>Слово меняется каждую неделю и не повторяется в течение года.</i>'),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t('◀️ Назад'), callback_data="btn_promo_back")],
        ])
    )
    await callback.answer()


@router.callback_query(F.data == "btn_promo_back")
async def cb_btn_promo_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    # Call main promo menu
    await btn_promo(callback.message, state)
    await callback.answer()


_welcome_claim_lock = asyncio.Lock()


@router.callback_query(F.data == "welcome_lootbox_claim")
async def welcome_lootbox_claim(callback: CallbackQuery):
    async with _welcome_claim_lock:
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not user:
                return
            from app.models import UserActionLog
            from sqlalchemy import select
            already_claimed = (await session.execute(select(UserActionLog).where(UserActionLog.user_id == user.id, UserActionLog.action == "welcome_lootbox"))).scalars().first()
            if already_claimed:
                await callback.answer(t('Стартовый лутбокс уже открыт!'), show_alert=True)
                try:
                    await callback.message.delete()
                except Exception:
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
            await callback.answer(t('+{reward} монет!', reward=reward), show_alert=True)


# ====================================================
# ОПРОСЫ АДМИНИСТРАТОРА С НАГРАДОЙ
# ====================================================
async def _get_poll_for_user(poll_id: int) -> AdminPoll | None:
    async with async_session() as session:
        return await session.scalar(
            select(AdminPoll).where(AdminPoll.id == poll_id, AdminPoll.is_active == True)
        )


def _multiple_poll_keyboard(poll_id: int, options: list[str], selected: set[int]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, option in enumerate(options):
        marker = "☑️" if index in selected else "▫️"
        rows.append([
            InlineKeyboardButton(
                text=f"{marker} {option}",
                callback_data=f"poll_multi_toggle:{poll_id}:{index}",
            )
        ])
    rows.extend([
        [InlineKeyboardButton(text=t('✅ Отправить ответ'), callback_data=f"poll_multi_submit:{poll_id}")],
        [InlineKeyboardButton(text=t('❌ Отмена'), callback_data=f"poll_multi_cancel:{poll_id}")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _complete_poll_answer(
    callback: CallbackQuery,
    *,
    poll_id: int,
    answer_text: str | None = None,
    option_indexes: list[int] | None = None,
) -> tuple[bool, str]:
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            return False, "Сначала открой бота командой /start."
        _poll, reward, error = await submit_admin_poll_response(
            session,
            poll_id,
            user.id,
            answer_text=answer_text,
            option_indexes=option_indexes,
        )
    if error:
        return False, error
    reward_text = f"{reward:.0f}" if reward is not None else "100"
    return True, f"✅ Спасибо за ответ! Тебе начислено {reward_text} монет."


@router.callback_query(F.data.startswith("poll_single:"))
async def poll_single_answer(callback: CallbackQuery):
    try:
        _, poll_id_raw, option_raw = callback.data.split(":", 2)
        poll_id = int(poll_id_raw)
        option_index = int(option_raw)
    except (AttributeError, ValueError):
        await callback.answer(t('Некорректный вариант ответа.'), show_alert=True)
        return
    ok, text = await _complete_poll_answer(
        callback,
        poll_id=poll_id,
        option_indexes=[option_index],
    )
    if ok:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.answer(t('Награда начислена.'))
        await callback.message.answer(text)
    else:
        await callback.answer(text, show_alert=True)


@router.callback_query(F.data.startswith("poll_text:"))
async def poll_text_start(callback: CallbackQuery, state: FSMContext):
    try:
        poll_id = int(callback.data.split(":", 1)[1])
    except (AttributeError, ValueError):
        await callback.answer(t('Некорректный опрос.'), show_alert=True)
        return
    poll = await _get_poll_for_user(poll_id)
    if not poll or poll.poll_type != "text":
        await callback.answer(t('Опрос уже завершён или недоступен.'), show_alert=True)
        return
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        already_answered = bool(user and await session.scalar(
            select(AdminPollResponse.id).where(
                AdminPollResponse.poll_id == poll_id,
                AdminPollResponse.user_id == user.id,
            )
        ))
    if already_answered:
        await callback.answer(t('Вы уже прошли этот опрос.'), show_alert=True)
        return
    await state.set_state(UserPollState.waiting_text)
    await state.update_data(poll_id=poll_id)
    await callback.message.answer(
        t('✍️ Напиши свой ответ одним сообщением. После отправки тебе будет начислено 20 монет.'),
    )
    await callback.answer()


@router.message(UserPollState.waiting_text)
async def poll_text_submit(message: Message, state: FSMContext):
    poll_id = (await state.get_data()).get("poll_id")
    answer_text = (message.text or "").strip()
    if not poll_id:
        await state.clear()
        await message.answer(t('Опрос не найден. Открой его заново.'))
        return
    if not answer_text:
        await message.answer(t('❌ Ответ не может быть пустым.'))
        return
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await state.clear()
            await message.answer(t('Сначала открой бота командой /start.'))
            return
        _poll, reward, error = await submit_admin_poll_response(
            session,
            int(poll_id),
            user.id,
            answer_text=answer_text,
        )
    if error:
        await message.answer(f"❌ {error}")
        if "уже" in error or "недоступен" in error:
            await state.clear()
        return
    await state.clear()
    await message.answer(t('✅ Спасибо за ответ! Тебе начислено {reward:.0f} монет.', reward=reward))


@router.callback_query(F.data.startswith("poll_multi_open:"))
async def poll_multi_open(callback: CallbackQuery, state: FSMContext):
    try:
        poll_id = int(callback.data.split(":", 1)[1])
    except (AttributeError, ValueError):
        await callback.answer(t('Некорректный опрос.'), show_alert=True)
        return
    poll = await _get_poll_for_user(poll_id)
    if not poll or poll.poll_type != "multiple":
        await callback.answer(t('Опрос уже завершён или недоступен.'), show_alert=True)
        return
    try:
        options = json.loads(poll.options_json or "[]")
    except (TypeError, json.JSONDecodeError):
        options = []
    if not options:
        await callback.answer(t('В опросе нет вариантов.'), show_alert=True)
        return
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        already_answered = bool(user and await session.scalar(
            select(AdminPollResponse.id).where(
                AdminPollResponse.poll_id == poll_id,
                AdminPollResponse.user_id == user.id,
            )
        ))
    if already_answered:
        await callback.answer(t('Вы уже прошли этот опрос.'), show_alert=True)
        return
    await state.set_state(UserPollState.selecting_multiple)
    await state.update_data(poll_id=poll_id, poll_selected=[])
    await callback.message.answer(
        t('📊 <b>{arg0}</b>\n\nВыбери один или несколько вариантов, затем нажми «Отправить ответ».', arg0=escape(poll.question)),
        parse_mode="HTML",
        reply_markup=_multiple_poll_keyboard(poll_id, options, set()),
    )
    await callback.answer()


@router.callback_query(UserPollState.selecting_multiple, F.data.startswith("poll_multi_toggle:"))
async def poll_multi_toggle(callback: CallbackQuery, state: FSMContext):
    try:
        _, poll_id_raw, option_raw = callback.data.split(":", 2)
        poll_id = int(poll_id_raw)
        option_index = int(option_raw)
    except (AttributeError, ValueError):
        await callback.answer(t('Некорректный вариант.'), show_alert=True)
        return
    data = await state.get_data()
    if data.get("poll_id") != poll_id:
        await callback.answer(t('Открой опрос заново.'), show_alert=True)
        return
    poll = await _get_poll_for_user(poll_id)
    if not poll or poll.poll_type != "multiple":
        await state.clear()
        await callback.answer(t('Опрос уже завершён или недоступен.'), show_alert=True)
        return
    try:
        options = json.loads(poll.options_json or "[]")
    except (TypeError, json.JSONDecodeError):
        options = []
    if option_index < 0 or option_index >= len(options):
        await callback.answer(t('Некорректный вариант.'), show_alert=True)
        return
    selected = {int(index) for index in data.get("poll_selected", [])}
    if option_index in selected:
        selected.remove(option_index)
    else:
        selected.add(option_index)
    await state.update_data(poll_selected=sorted(selected))
    await callback.message.edit_reply_markup(
        reply_markup=_multiple_poll_keyboard(poll_id, options, selected)
    )
    await callback.answer()


@router.callback_query(UserPollState.selecting_multiple, F.data.startswith("poll_multi_submit:"))
async def poll_multi_submit(callback: CallbackQuery, state: FSMContext):
    try:
        poll_id = int(callback.data.split(":", 1)[1])
    except (AttributeError, ValueError):
        await callback.answer(t('Некорректный опрос.'), show_alert=True)
        return
    data = await state.get_data()
    if data.get("poll_id") != poll_id:
        await callback.answer(t('Открой опрос заново.'), show_alert=True)
        return
    selected = data.get("poll_selected", [])
    if not selected:
        await callback.answer(t('Выберите хотя бы один вариант.'), show_alert=True)
        return
    ok, text = await _complete_poll_answer(callback, poll_id=poll_id, option_indexes=selected)
    if ok:
        await state.clear()
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.answer(t('Награда начислена.'))
        await callback.message.answer(text)
    else:
        if "уже" in text or "недоступен" in text:
            await state.clear()
        await callback.answer(text, show_alert=True)


@router.callback_query(UserPollState.selecting_multiple, F.data.startswith("poll_multi_cancel:"))
async def poll_multi_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer(t('Выбор отменён.'))
