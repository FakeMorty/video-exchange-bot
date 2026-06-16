from html import escape
import uuid
import random
import asyncio
from datetime import datetime, timedelta
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
    REFERRAL_REWARD_INVITER, REFERRAL_REWARD_NEW_USER, SMART_AD_FORCED_WATCH_SECONDS,
    DAILY_PHOTO_LIMIT,
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
)
from app.services import (
    get_or_create_user, get_user, get_user_by_id, get_setting, set_setting,
    save_video, save_photo,
    get_random_video_for_user, get_random_photo_for_user,
    record_view_and_charge_with_cost, refund_watch_and_unview, mark_content_broken,
    record_photo_view,
    rate_video, claim_daily_bonus, count_referrals,
    create_payment, create_custom_payment, apply_successful_payment,
    ensure_payment_pending, mark_payment_paid_once,
    get_payment_by_payload,
    get_active_offers, get_rentable_offers, get_offer_by_id,
    start_offer_participation, verify_offer_subscription,
    create_offer_rental, get_user_rentals,
    log_user_action, to_decimal,
    set_display_name, get_display_name, log_balance_change,
    can_play_free_game, pay_for_game_session, increment_game_played,
    get_or_create_game_session,
    check_daily_photo_limit,
    create_promocode, activate_promocode,
    calculate_promocode_star_cost,
    create_feedback,
    ensure_current_lottery_round, buy_lottery_ticket,
    get_latest_lottery_round, get_user_lottery_tickets, get_lottery_state_dict,
    is_admin_or_super, is_admin_free_eligible,
    should_show_low_balance_hint, mark_low_balance_hint_shown,
    can_show_offer_to_user, mark_offer_shown,
    get_random_active_offer, should_inject_ad_in_video,
    open_lootbox_for_coins, open_lootbox_for_stars,
    get_current_prices, get_active_events,
    should_show_ad_after_video, increment_video_watched, reset_ad_counter,
)
from app.selfcheck import run_selfcheck, format_selfcheck_report
from app.keyboards import (
    main_menu,
    video_rating_keyboard, photo_actions_keyboard,
    watch_choice_keyboard, buy_coins_keyboard, vip_buy_keyboard,
    offers_list_keyboard, rent_days_keyboard,
    games_menu_keyboard, tops_menu_keyboard,
    quests_keyboard, reaction_menu_keyboard,
    low_balance_offer_keyboard, forced_offer_keyboard,
    forced_offer_done_keyboard,
    BTN_WATCH, BTN_UPLOAD, BTN_PROFILE, BTN_BUY,
    BTN_OFFERS, BTN_REFERRALS, BTN_BONUS, BTN_ADMIN,
    BTN_GAMES, BTN_TOPS, BTN_QUESTS, BTN_VIP, BTN_LEVEL,
    BTN_PROMO, BTN_FEEDBACK, BTN_LOTTERY,
)
from app.user_offer_handlers import user_offers_menu
from app.logger import get_logger

logger = get_logger(__name__)
router = Router()

_upload_notifications = defaultdict(lambda: {"count": 0, "task": None})

async def _send_upload_notification(bot, chat_id, user_id):
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
    now = datetime.utcnow()
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
def is_any_admin(telegram_id: int, user_obj=None) -> bool:
    if telegram_id in ADMINS:
        return True
    if user_obj and user_obj.is_admin:
        return True
    return False


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
    return bool(user.vip_until and user.vip_until > datetime.utcnow())


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


async def _level_up_check(session, user, message_or_callback):
    """Проверяет апгрейд уровня и отправляет поздравление."""
    new_level = calc_level_from_xp(user.xp)
    if new_level > user.level:
        user.level = new_level
        await session.commit()
        if hasattr(message_or_callback, "answer"):
            await message_or_callback.answer(
                f"🎉 Поздравляем! Вы достигли уровня <b>{new_level}</b>!",
                parse_mode="HTML"
            )
        else:
            await message_or_callback.message.answer(
                f"🎉 Поздравляем! Вы достигли уровня <b>{new_level}</b>!",
                parse_mode="HTML"
            )


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
            admin_flag = is_any_admin(message.from_user.id, user)
        await message.answer(
            "Теперь вы можете пользоваться ботом!",
            reply_markup=main_menu(is_admin=admin_flag)
        )


# =========================
# START / RULES
# =========================
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
            await message.answer(
                f"👋 Привет, <b>{get_display_name(user)}</b>{vip_str}!\n"
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

        admin_flag = is_any_admin(message.from_user.id, user)
        vip_str = " 👑" if is_vip(user) else ""
        import os
        from aiogram.types import FSInputFile
        msg_text = (
            f"👋 Привет, <b>{get_display_name(user)}</b>{vip_str}!\n"
            f"💰 Баланс: <b>{user.balance}</b> монет"
        )
        custom_welcome = await get_setting(session, "welcome_text", "")
        if custom_welcome:
            msg_text += f"\n\n{custom_welcome}"
        
        banner_file_id = await get_setting(session, "welcome_banner_id", "")
        
        if banner_file_id:
            try:
                await message.answer_photo(
                    photo=banner_file_id,
                    caption=msg_text,
                    parse_mode="HTML",
                    reply_markup=main_menu(is_admin=admin_flag)
                )
            except Exception:
                await message.answer(
                    msg_text,
                    parse_mode="HTML",
                    reply_markup=main_menu(is_admin=admin_flag)
                )
        elif os.path.exists("app/banner.jpg"):
            await message.answer_photo(
                photo=FSInputFile("app/banner.jpg"),
                caption=msg_text,
                parse_mode="HTML",
                reply_markup=main_menu(is_admin=admin_flag)
            )
        else:
            await message.answer(
                msg_text,
                parse_mode="HTML",
                reply_markup=main_menu(is_admin=admin_flag)
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
            await process_referral_reward(session, user.id)
        await session.commit()

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
async def show_profile(message: Message):
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
        text = (
            f"👤 <b>Профиль</b>\n\n"
            f"🏷 Ник: <b>{get_display_name(user)}</b>\n"
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
async def show_level(message: Message):
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
async def show_vip(message: Message):
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
                    f"• VIP квесты",
                    parse_mode="HTML"
                )
            else:
                vip_price, packs, sale = await get_current_prices(session)
                events = await get_active_events(session)
                
                # Admin free badge
                admin_free_badge = ""
                if ENABLE_ADMIN_FREE:
                    from app.services import is_admin_or_super
                    if is_admin_or_super(message.from_user.id, user):
                        admin_free_badge = "\n🆓 <b>ADMIN FREE — бесплатно!</b>"
                
                sale_badge = ""
                if events:
                    best_ev = max(events, key=lambda e: e.discount_percent)
                    sale_badge = f"\n🔥 <b>АКЦИЯ: {escape(best_ev.name)} — скидка {best_ev.discount_percent}%!</b>"
                elif sale:
                    sale_badge = f"\n🔥 <b>АКЦИЯ: скидка {sale.discount_percent}%!</b>"
                
                await message.answer(
                    f"👑 <b>VIP статус</b>\n\n"
                    f"Стоимость: <b>{vip_price} Stars</b> (обычная: {VIP_PRICE_STARS}){sale_badge}{admin_free_badge}\n"
                    f"Длительность: {VIP_DURATION_DAYS} дней\n\n"
                    f"Привилегии:\n"
                    f"• Множитель монет x{VIP_BONUS_MULTIPLIER}\n"
                    f"• Скидка 50% на просмотр\n"
                    f"• VIP квесты",
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
            # Обычная оплата — выставляем инвойс
            await ensure_payment_pending(
                session,
                user_id=user.id,
                payload=payload,
                stars_amount=int(VIP_PRICE_STARS),
            )
            await session.commit()
            await callback.message.answer_invoice(
                title="VIP статус",
                description=f"VIP на {VIP_DURATION_DAYS} дней",
                payload=payload,
                currency="XTR",
                prices=[LabeledPrice(label="VIP", amount=VIP_PRICE_STARS)]
            )
            await callback.answer()
            return

        # Admin free — выдаём VIP бесплатно
        now = datetime.utcnow()
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
            f"• VIP квесты",
            parse_mode="HTML",
        )
        await callback.answer("🆓 VIP активирован бесплатно!")


# =========================
# WATCH
# =========================
@router.message(F.text == BTN_WATCH)
async def btn_watch(message: Message):
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

            cost = to_decimal(WATCH_COST)
            if is_vip(user):
                cost = round(cost * to_decimal(0.5), 2)

            if user.balance < cost:
                if await should_show_low_balance_hint(session, user):
                    await mark_low_balance_hint_shown(session, user.id)
                    await callback.message.answer(
                        f"💸 <b>Монеток маловато!</b>\n\n"
                        f"На счету: <b>{user.balance}</b> монет, "
                        f"а нужно <b>{cost}</b> для просмотра.\n\n"
                        f"💡 <i>Знаешь ли ты, что можно бесплатно заработать монеты, "
                        f"подписываясь на каналы в разделе «Офферы»? "
                        f"Это быстро и просто!</i>",
                        parse_mode="HTML",
                        reply_markup=low_balance_offer_keyboard()
                    )
                else:
                    await callback.message.answer(
                        f"❌ Недостаточно монет!\n"
                        f"Нужно: {cost}, у вас: {user.balance}\n"
                        f"Пополните баланс или заработайте через офферы"
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

                user = await get_user(session, callback.from_user.id)
                await _level_up_check(session, user, callback)
                await _update_quest_progress(session, user.id, "watch", 1)
                
                # Увеличиваем счётчик просмотров и проверяем нужно ли показать рекламу
                count = await increment_video_watched(session, user.id)
                
                if await should_show_ad_after_video(session, user.id):
                    await _show_ad_or_event(callback, session, user)

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
        end_text = (event.start_date + timedelta(days=event.duration_days)).strftime("%d.%m")
        
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

                await record_photo_view(session, user.id, photo.id)
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
        user.xp += XP_PER_RATING
        await _level_up_check(session, user, callback)
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
                name = get_display_name(u) if u else "???"
                text += f"👤 <b>{escape(name)}</b>: {escape(c.text)}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✏️ Написать",
            callback_data=f"add_comment:{video_id}"
        )],
        [InlineKeyboardButton(
            text="😀 Реакции",
            callback_data=f"reactions:{video_id}"
        )],
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
        ten_min_ago = datetime.utcnow() - timedelta(minutes=10)
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
        user.xp += XP_PER_COMMENT
        await _level_up_check(session, user, message)
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
            user.xp += XP_PER_REACTION
            await _level_up_check(session, user, callback)

        await session.commit()
        await _update_quest_progress(session, user.id, "react", 1)

    await callback.answer(f"{reaction} Поставлена!")


# =========================
# UPLOAD
# =========================
@router.message(F.text == BTN_UPLOAD)
async def btn_upload(message: Message):
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
            user.xp += XP_PER_UPLOAD
            await _level_up_check(session, user, message)
            await _update_quest_progress(session, user.id, "upload", 1)
            await message.answer(f"✅ Видео #{saved.id} автоматически одобрено! (доверенный автор)\n+{UPLOAD_REWARD:.0f} монет")
            return

        user.xp += XP_PER_UPLOAD
        await _level_up_check(session, user, message)
        await _update_quest_progress(session, user.id, "upload", 1)
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
            user.xp += XP_PER_UPLOAD
            await _level_up_check(session, user, message)
            await _update_quest_progress(session, user.id, "upload", 1)
            await message.answer(f"✅ Фото #{saved.id} автоматически одобрено! (доверенный автор)\n+{PHOTO_UPLOAD_REWARD:.0f} монет")
            return

        user.xp += XP_PER_UPLOAD
        await _level_up_check(session, user, message)
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
async def btn_bonus(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if not await require_nickname(message, user):
            return
        ok, result = await claim_daily_bonus(session, user.id)
    if ok:
        await message.answer(
            f"🎁 Бонус получен: <b>+{result} монет</b>!",
            parse_mode="HTML"
        )
    else:
        await message.answer(str(result))


# =========================
# REFERRALS
# =========================
@router.message(F.text == BTN_REFERRALS)
async def btn_referrals(message: Message):
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
async def btn_buy(message: Message):
    try:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                return
            if not await require_nickname(message, user):
                return

            vip_price, packs, sale = await get_current_prices(session)
            events = await get_active_events(session)

            # Admin free badge
            admin_free_badge = ""
            if await is_admin_free_eligible(session, message.from_user.id, user):
                admin_free_badge = "\n🆓 <b>ADMIN FREE — всё бесплатно!</b>"

        # Бейдж активной акции
        sale_badge = ""
        if events:
            best_ev = max(events, key=lambda e: e.discount_percent)
            sale_badge = f"\n🔥 <b>АКЦИЯ: {escape(best_ev.name)} — скидка {best_ev.discount_percent}%!</b>"
        elif sale:
            sale_badge = f"\n🔥 <b>АКЦИЯ: скидка {sale.discount_percent}%!</b>"

        # Динамический курс
        bonus_text = ""
        if DYNAMIC_STAR_DISCOUNT_ENABLED:
            try:
                start_h, end_h = map(int, DYNAMIC_STAR_DISCOUNT_HOURS.split("-"))
                now_h = datetime.utcnow().hour
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

        # Admin free — выдаём монеты без оплаты
        if await is_admin_free_eligible(session, callback.from_user.id, user):
            coins = pack["coins"]
            bonus = to_decimal(FIRST_PURCHASE_DAILY_BONUS)
            total = to_decimal(coins) + bonus
            
            await log_balance_change(session, user, total, "purchase_admin_free",
                                     details=f"ADMIN_FREE: {pack['title']} + bonus")
            user.balance += total
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

        payment = await create_payment(session, user.id, pack_key)

    await callback.message.answer_invoice(
        title=f"Покупка {pack['title']}",
        description=f"{pack['coins']} монет за {pack['stars']} Stars",
        payload=payment.payload,
        currency="XTR",
        prices=[LabeledPrice(label=pack['title'], amount=pack['stars'])]
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

            await log_balance_change(session, user, total, "purchase_admin_free",
                                     details=f"ADMIN_FREE: custom {coins} монет + bonus")
            user.balance += total
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

        payment = await create_custom_payment(session, user.id, stars)
        coins = int(stars * STARS_TO_COINS_RATE)

    await message.answer_invoice(
        title=f"Покупка {coins} монет",
        description=f"{coins} монет за {stars} Stars",
        payload=payment.payload,
        currency="XTR",
        prices=[LabeledPrice(label=f"{coins} монет", amount=stars)]
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
                    await message.answer("Ошибка платежа: пользователь не совпадает.")
                    return
                if int(payment.stars_amount) != paid_stars:
                    await session.rollback()
                    await message.answer("Ошибка платежа: сумма не совпадает.")
                    return
                if not await mark_payment_paid_once(session, payload):
                    await session.rollback()
                    await message.answer("✅ Платёж уже был обработан ранее.")
                    return
                now = datetime.utcnow()
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
                    await message.answer("Ошибка платежа: пользователь не совпадает.")
                    return
                if int(payment.stars_amount) != paid_stars:
                    await session.rollback()
                    await message.answer("Ошибка платежа: сумма не совпадает.")
                    return
                if not await mark_payment_paid_once(session, payload):
                    await session.rollback()
                    await message.answer("✅ Платёж уже был обработан ранее.")
                    return
                promo, cost, error = await create_promocode(
                    session, creator_tg_id,
                    to_decimal(amount), uses, hours,
                    auto_commit=False,
                )
                if error:
                    await session.rollback()
                    await message.answer(f"❌ Ошибка создания промокода: {error}")
                else:
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
                await message.answer("Ошибка платежа: пользователь не совпадает.")
                return
            if int(payment.stars_amount) != paid_stars:
                await session.rollback()
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
            offer_id = int(payload.split("_")[1])
            async with async_session() as session:
                offer = await session.get(Offer, offer_id)
                if offer:
                    offer.status = "pending"
                    await session.commit()
                    
                    # Уведомляем админов
                    for admin_id in ADMINS:
                        try:
                            await message.bot.send_message(
                                admin_id,
                                f"🔔 <b>Новый пользовательский оффер!</b>\n\n"
                                f"Оффер #{offer.id} оплачен и ждёт проверки.\n"
                                f"Название: {offer.title}\n"
                                f"Награды: {offer.reward_preview} + {offer.reward_final}\n"
                                f"Длительность: {offer.duration_days} дней",
                                parse_mode="HTML"
                            )
                        except Exception:
                            pass
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
            payment = await apply_successful_payment(session, payload)
        if payment:
            await message.answer(
                f"✅ Оплата успешна!\n"
                f"💰 Начислено: <b>{payment.coins_amount:,.0f}</b> монет".replace(',', ' '),
                parse_mode="HTML"
            )
        else:
            await message.answer("✅ Оплата получена!")


def _lootbox_kb() -> InlineKeyboardMarkup:
    coin_price = to_decimal(LOOTBOX_COIN_PRICE)
    star_price = int(LOOTBOX_STAR_PRICE)
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
    coin_price = to_decimal(LOOTBOX_COIN_PRICE)
    star_price = int(LOOTBOX_STAR_PRICE)
    await callback.message.answer(
        ("🎁 <b>Лутбоксы</b>\n\n"
         f"Цена: <b>{coin_price:,.0f}</b> монет или <b>{star_price}</b> Stars.\n".replace(',', ' ') +
         "Внутри — случайный выигрыш монет.\n"
         "Редкие крупные выигрыши возможны, но не гарантированы."),
        parse_mode="HTML",
        reply_markup=_lootbox_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("lootbox_buy:"))
async def lootbox_buy(callback: CallbackQuery):
    if not ENABLE_LOOTBOXES:
        await callback.answer("Лутбоксы отключены.", show_alert=True)
        return
    kind = callback.data.split(":", 1)[1]
    if kind == "coins":
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not user:
                await callback.answer()
                return

            # Admin free
            admin_free = await is_admin_free_eligible(session, callback.from_user.id, user)

            coin_price = to_decimal(LOOTBOX_COIN_PRICE)
            if not admin_free and user.balance < coin_price:
                await callback.answer(f"Недостаточно монет. Нужно: {coin_price:.0f}", show_alert=True)
                return

            if admin_free:
                # Бесплатный лутбокс для админа
                from app.services import _roll_lootbox_reward_coins, open_lootbox_for_coins
                reward, rarity = _roll_lootbox_reward_coins()
                await log_balance_change(session, user, reward, "lootbox_reward_admin_free",
                                         details=f"ADMIN_FREE rarity={rarity}")
                user.balance += reward
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
                    reply_markup=_lootbox_kb(),
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
            reply_markup=_lootbox_kb(),
        )
        await callback.answer()
        return

    if kind == "stars":
        star_price = int(LOOTBOX_STAR_PRICE)
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
                await log_balance_change(session, user, reward, "lootbox_reward_admin_free",
                                         details=f"ADMIN_FREE stars rarity={rarity}")
                user.balance += reward
                session.add(LootboxOpen(
                    user_id=user.id, payment_payload=payload, pay_currency="stars",
                    price_coins=Decimal("0"), price_stars=star_price, reward_coins=reward, rarity=rarity,
                ))
                await log_user_action(session, user.id, "lootbox_open_admin_free",
                                      f"payload={payload}, rarity={rarity}, reward={reward}")
                await session.commit()
                icon = {"common": "⚪", "rare": "🔵", "epic": "🟣", "jackpot": "🟡"}.get(rarity, "🎁")
                await callback.message.answer(
                    f"{icon} <b>Лутбокс открыт!</b> (🆓 ADMIN FREE)\n\n"
                    f"Выигрыш: <b>+{reward:,.0f}</b> монет".replace(',', ' '),
                    parse_mode="HTML",
                    reply_markup=_lootbox_kb(),
                )
                await callback.answer("🆓 Лутбокс открыт бесплатно!")
                return

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


# =========================
# OFFERS
# =========================
@router.message(F.text == BTN_OFFERS)
async def btn_offers(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if not await require_nickname(message, user):
            return
        offers = await get_active_offers(session)

    if not offers:
        await message.answer("😔 Активных офферов пока нет. Загляните позже!")
        return

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
    await message.answer(
        "📢 <b>Офферы</b>\n\nВыберите раздел:",
        parse_mode="HTML",
        reply_markup=kb
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

    await callback.answer(
        f"✅ Получено {offer.reward_preview} монет!\n"
        f"Подпишитесь и нажмите «Проверить».",
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
        result = await verify_offer_subscription(session, user.id, offer_id)
        if result:
            await callback.answer(
                f"✅ Подтверждено! Получено {offer.reward_final} монет!",
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
        active_count = 0
        async with async_session() as session:
            try:
                active_count = (await session.execute(
                    select(func.count()).where(False)
                )).scalar_one()
            except Exception:
                pass
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
    async with async_session() as session:
        await get_active_offers(session)
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
async def btn_games(message: Message):
    from app.keyboards import games_menu_keyboard
    from app.services import can_play_free_game
    from app.config import GAME_SESSION_COST
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if not await require_nickname(message, user):
            return

        can_play = await can_play_free_game(session, user.id)
        if can_play:
            await message.answer(
                "🎮 <b>Игровой центр</b>\n\nВыберите игру:",
                parse_mode="HTML",
                reply_markup=games_menu_keyboard()
            )
        else:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"💰 Продлить за {GAME_SESSION_COST} монет",
                    callback_data="game_pay_session"
                )]
            ])
            await message.answer(
                "⏳ Бесплатные игры на сегодня закончились. Продлите сессию:",
                reply_markup=kb
            )


@router.callback_query(F.data == "game_pay_session")
async def game_pay_session(callback: CallbackQuery):
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        # Админы получают новую бесплатную сессию без списания монет
        if is_admin_or_super(callback.from_user.id, user):
            gs = await get_or_create_game_session(session, user.id)
            gs.games_played = 0
            gs.window_start = datetime.utcnow()
            gs.paid_at = datetime.utcnow()
            await session.commit()
            await callback.answer("✅ Сессия продлена (админ).", show_alert=True)
            return
        ok = await pay_for_game_session(session, user.id)
        if ok:
            await callback.answer("✅ Сессия продлена! Ещё 5 игр.", show_alert=True)
        else:
            await callback.answer("❌ Недостаточно монет.", show_alert=True)
    await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data == "dice_menu")
async def game_dice(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1 монета",  callback_data="dice_bet:1"),
            InlineKeyboardButton(text="5 монет",   callback_data="dice_bet:5"),
        ],
        [
            InlineKeyboardButton(text="10 монет",  callback_data="dice_bet:10"),
            InlineKeyboardButton(text="25 монет",  callback_data="dice_bet:25"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="games_back")],
    ])
    await callback.message.answer(
        "🎲 <b>Кости</b>\n\n4, 5, 6 — выигрыш x2!\n\nСтавка:",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data.startswith("dice_bet:"))
async def dice_bet(callback: CallbackQuery):
    bet = int(callback.data.split(":")[1])
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        if user.balance < to_decimal(bet):
            await callback.answer("❌ Недостаточно монет!", show_alert=True)
            return
        if not is_admin_or_super(callback.from_user.id, user):
            can_play = await can_play_free_game(session, user.id)
            if not can_play:
                await callback.answer("Бесплатные игры закончились.", show_alert=True)
                return

        dice_msg = await callback.message.answer_dice(emoji="🎲")
        dice_value = dice_msg.dice.value

        user.balance -= to_decimal(bet)
        if not is_admin_or_super(callback.from_user.id, user):
            await increment_game_played(session, user.id)

        if dice_value >= 4:
            win = to_decimal(bet) * 2
            user.balance += win
            net = win - to_decimal(bet)
            result_text = f"🎲 Выпало: {dice_value}\n🎉 Выиграли! +{win} монет"
        else:
            net = -to_decimal(bet)
            result_text = f"🎲 Выпало: {dice_value}\n😔 Проиграли -{bet} монет"

        user.xp += XP_PER_GAME
        await _level_up_check(session, user, callback)

        session.add(GameHistory(
            user_id=user.id,
            game_type="dice",
            bet=to_decimal(bet),
            result=net,
            details=f"dice={dice_value}"
        ))
        await log_balance_change(
            session, user, net, "game_dice",
            details=f"bet={bet}, dice={dice_value}"
        )
        await session.commit()

    await callback.message.answer(
        f"{result_text}\n💰 Баланс: {user.balance}"
    )
    await callback.answer()


@router.callback_query(F.data == "game_coinflip")
async def game_coinflip(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1 монета",  callback_data="coinflip_bet:1"),
            InlineKeyboardButton(text="5 монет",   callback_data="coinflip_bet:5"),
        ],
        [
            InlineKeyboardButton(text="10 монет",  callback_data="coinflip_bet:10"),
            InlineKeyboardButton(text="25 монет",  callback_data="coinflip_bet:25"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="games_back")],
    ])
    await callback.message.answer(
        "🪙 <b>Орёл/Решка</b>\n\n50/50 шанс x2!\n\nСтавка:",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data.startswith("coinflip_bet:"))
async def coinflip_bet(callback: CallbackQuery):
    bet = int(callback.data.split(":")[1])
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        if user.balance < to_decimal(bet):
            await callback.answer("❌ Недостаточно монет!", show_alert=True)
            return
        if not is_admin_or_super(callback.from_user.id, user):
            can_play = await can_play_free_game(session, user.id)
            if not can_play:
                await callback.answer("Бесплатные игры закончились.", show_alert=True)
                return

        coin_msg = await callback.message.answer_dice(emoji="🪙")
        won = coin_msg.dice.value >= 4

        user.balance -= to_decimal(bet)
        if not is_admin_or_super(callback.from_user.id, user):
            await increment_game_played(session, user.id)
        user.xp += XP_PER_GAME

        if won:
            win = to_decimal(bet) * 2
            user.balance += win
            net = win - to_decimal(bet)
            result_text = f"🪙 Орёл! 🎉 +{win} монет"
        else:
            net = -to_decimal(bet)
            result_text = f"🪙 Решка! 😔 -{bet} монет"

        await _level_up_check(session, user, callback)
        session.add(GameHistory(
            user_id=user.id,
            game_type="coinflip",
            bet=to_decimal(bet),
            result=net,
            details=f"won={won}"
        ))
        await log_balance_change(
            session, user, net, "game_coinflip",
            details=f"bet={bet}, won={won}"
        )
        await session.commit()

    await callback.message.answer(
        f"{result_text}\n💰 Баланс: {user.balance}"
    )
    await callback.answer()


@router.callback_query(F.data == "guess_menu")
async def game_guess(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1 монета",  callback_data="guess_bet:1"),
            InlineKeyboardButton(text="5 монет",   callback_data="guess_bet:5"),
            InlineKeyboardButton(text="10 монет",  callback_data="guess_bet:10"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="games_back")],
    ])
    await callback.message.answer(
        "🎯 <b>Угадай число</b>\n\nУгадай 1–6 — x5 ставки!\n\nСтавка:",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data.startswith("guess_bet:"))
async def guess_bet_start(callback: CallbackQuery, state: FSMContext):
    bet = int(callback.data.split(":")[1])
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        if user.balance < to_decimal(bet):
            await callback.answer("❌ Недостаточно монет!", show_alert=True)
            return
        if not is_admin_or_super(callback.from_user.id, user):
            can_play = await can_play_free_game(session, user.id)
            if not can_play:
                await callback.answer("Бесплатные игры закончились.", show_alert=True)
                return

    await state.update_data(guess_bet=bet)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1", callback_data="guess_num:1"),
            InlineKeyboardButton(text="2", callback_data="guess_num:2"),
            InlineKeyboardButton(text="3", callback_data="guess_num:3"),
        ],
        [
            InlineKeyboardButton(text="4", callback_data="guess_num:4"),
            InlineKeyboardButton(text="5", callback_data="guess_num:5"),
            InlineKeyboardButton(text="6", callback_data="guess_num:6"),
        ],
    ])
    await callback.message.answer("Выберите число:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("guess_num:"))
async def guess_num(callback: CallbackQuery, state: FSMContext):
    guess = int(callback.data.split(":")[1])
    data = await state.get_data()
    bet = data.get("guess_bet", 1)

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        if user.balance < to_decimal(bet):
            await callback.answer("❌ Недостаточно монет!", show_alert=True)
            return
        if not is_admin_or_super(callback.from_user.id, user):
            can_play = await can_play_free_game(session, user.id)
            if not can_play:
                await callback.answer("Бесплатные игры закончились.", show_alert=True)
                return

        dice_msg = await callback.message.answer_dice(emoji="🎲")
        actual = dice_msg.dice.value

        user.balance -= to_decimal(bet)
        if not is_admin_or_super(callback.from_user.id, user):
            await increment_game_played(session, user.id)
        user.xp += XP_PER_GAME

        if guess == actual:
            multiplier = 5
            jackpot = False
            if random.random() < GUESS_JACKPOT_CHANCE:
                multiplier = max(6, GUESS_JACKPOT_MULTIPLIER)
                jackpot = True
            win = to_decimal(bet) * multiplier
            user.balance += win
            net = win - to_decimal(bet)
            if jackpot:
                result_text = (
                    f"🎯 Выпало {actual}! Угадали!\n"
                    f"🌟 ДЖЕКПОТ x{multiplier}! +{win} монет"
                )
            else:
                result_text = f"🎯 Выпало {actual}! Угадали! 🎉 +{win} монет"
        else:
            net = -to_decimal(bet)
            result_text = f"🎯 Выпало {actual}, вы выбрали {guess}. 😔 -{bet} монет"

        await _level_up_check(session, user, callback)
        session.add(GameHistory(
            user_id=user.id,
            game_type="guess",
            bet=to_decimal(bet),
            result=net,
            details=f"guess={guess}, actual={actual}"
        ))
        await log_balance_change(
            session, user, net, "game_guess",
            details=f"bet={bet}, guess={guess}, actual={actual}"
        )
        await session.commit()

    await callback.message.answer(
        f"{result_text}\n💰 Баланс: {user.balance}"
    )
    await state.clear()
    await callback.answer()


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
async def btn_tops(message: Message):
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
        text += f"{icon} {get_display_name(u)} — {cnt} видео\n"
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
        text += f"{icon} {get_display_name(u)} — {cnt} просмотров\n"
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
        text += f"{icon} {get_display_name(u)} — Ур.{u.level} ({u.xp} XP)\n"
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
        text += f"{icon} {get_display_name(u)} — {u.balance:.2f} монет\n"
    if not users:
        text += "Пусто"
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


# =========================
# QUESTS
# =========================
@router.message(F.text == BTN_QUESTS)
async def btn_quests(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if not await require_nickname(message, user):
            return

        today = datetime.utcnow().date()
        quests = (await session.execute(
            select(DailyQuestProgress).where(
                DailyQuestProgress.user_id == user.id,
                DailyQuestProgress.quest_date == today
            )
        )).scalars().all()

        if not quests:
            quest_list = DAILY_QUESTS.copy()
            if is_vip(user):
                quest_list += PREMIUM_DAILY_QUESTS
            for q in quest_list:
                session.add(DailyQuestProgress(
                    user_id=user.id,
                    quest_type=q["type"],
                    quest_date=today,
                    progress=0,
                    target=q["target"],
                    reward=to_decimal(q["reward"]),
                ))
            await session.commit()
            quests = (await session.execute(
                select(DailyQuestProgress).where(
                    DailyQuestProgress.user_id == user.id,
                    DailyQuestProgress.quest_date == today
                )
            )).scalars().all()

        text = "📋 <b>Ежедневные квесты</b>\n\n"
        quest_desc_map = {}
        for q in DAILY_QUESTS:
            quest_desc_map[q["type"]] = q["desc"]
        for q in PREMIUM_DAILY_QUESTS:
            quest_desc_map[q["type"]] = q["desc"]

        for q in quests:
            status = "✅" if q.completed else "⏳"
            claimed = " (получено)" if q.reward_claimed else ""
            desc = quest_desc_map.get(q.quest_type, q.quest_type)
            text += (
                f"{status} <b>{desc}</b>\n"
                f"   Прогресс: {q.progress}/{q.target} | Награда: {q.reward} 🪙{claimed}\n\n"
            )

        await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=quests_keyboard(quests)
        )


@router.callback_query(F.data.startswith("quest_claim:"))
async def quest_claim(callback: CallbackQuery):
    quest_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        quest = (await session.execute(
            select(DailyQuestProgress).where(DailyQuestProgress.id == quest_id)
        )).scalar_one_or_none()
        if not quest:
            await callback.answer("Квест не найден.", show_alert=True)
            return
        if not quest.completed:
            await callback.answer("Квест ещё не выполнен!", show_alert=True)
            return
        if quest.reward_claimed:
            await callback.answer("Награда уже получена!", show_alert=True)
            return

        user = await get_user_by_id(session, quest.user_id)
        if not user:
            await callback.answer()
            return

        quest.reward_claimed = True
        await log_balance_change(
            session, user, quest.reward,
            "quest_reward", source_id=quest.id
        )
        user.balance += quest.reward
        await session.commit()

    await callback.answer(f"🎁 Получено {quest.reward} монет!", show_alert=True)


@router.callback_query(F.data.startswith("quest_done:"))
async def quest_done(callback: CallbackQuery):
    await callback.answer("✅ Квест выполнен, награда уже получена.", show_alert=True)


@router.callback_query(F.data.startswith("quest_info:"))
async def quest_info(callback: CallbackQuery):
    await callback.answer("⏳ Квест ещё не выполнен. Продолжайте!", show_alert=True)


# =========================
# HELPER: обновление квестов
# =========================
async def _update_quest_progress(
    session,
    user_id: int,
    quest_type: str,
    amount: int = 1
):
    today = datetime.utcnow().date()
    quests = (await session.execute(
        select(DailyQuestProgress).where(
            DailyQuestProgress.user_id == user_id,
            DailyQuestProgress.quest_type == quest_type,
            DailyQuestProgress.quest_date == today,
            DailyQuestProgress.completed.is_(False)
        )
    )).scalars().all()

    for quest in quests:
        quest.progress = min(quest.progress + amount, quest.target)
        if quest.progress >= quest.target:
            quest.completed = True

    try:
        await session.commit()
    except Exception:
        await session.rollback()


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


async def _send_lottery_menu(message_or_callback_message: Message) -> None:
    if not ENABLE_LOTTERY:
        await message_or_callback_message.answer("⛔ Лотерея временно отключена.")
        return
    async with async_session() as session:
        round_obj = await ensure_current_lottery_round(session)
        state_data = get_lottery_state_dict(round_obj)
    base = (WEBHOOK_BASE or "").rstrip("/")
    live_url = f"{base}/lottery/live" if base else ""
    # UX: show both UTC and MSK (UTC+3) without timezone guessing
    try:
        start_utc = round_obj.draw_starts_at.strftime("%H:%M")
        end_utc = round_obj.draw_ends_at.strftime("%H:%M")
        start_msk = (round_obj.draw_starts_at + timedelta(hours=3)).strftime("%H:%M")
        end_msk = (round_obj.draw_ends_at + timedelta(hours=3)).strftime("%H:%M")
        draw_line = f"Розыгрыш: <b>воскресенье</b> {start_utc}–{end_utc} UTC ( {start_msk}–{end_msk} МСК )"
    except Exception:
        draw_line = "Розыгрыш: <b>воскресенье</b> (в live-режиме)"
    await message_or_callback_message.answer(
        "🎰 <b>Лотерея-лото</b>\n\n"
        f"Раунд: <b>{state_data.get('week_key')}</b>\n"
        f"Статус: <b>{state_data.get('status')}</b>\n"
        f"Цена билета: <b>{state_data.get('ticket_price')}</b> монет\n"
        f"Призовой фонд: <b>{state_data.get('prize_pool')}</b> монет\n"
        f"Уже выпало: {', '.join(map(str, state_data.get('drawn_numbers', []))) or '—'}\n\n"
        + (f"🔴 Live-ссылка: <a href=\"{live_url}\">{live_url}</a>\n" if live_url else "")
        + f"{draw_line}\n\n"
        "Нажмите «🔴 Открыть Live», чтобы посмотреть колесо/розыгрыш.",
        parse_mode="HTML",
        reply_markup=_lottery_menu_kb(),
    )


@router.message(F.text == BTN_LOTTERY)
async def btn_lottery(message: Message):
    await _send_lottery_menu(message)


@router.callback_query(F.data == "open_lottery")
async def open_lottery_from_games(callback: CallbackQuery):
    await _send_lottery_menu(callback.message)
    await callback.answer()


@router.callback_query(F.data == "lottery_menu")
async def lottery_menu(callback: CallbackQuery):
    if not ENABLE_LOTTERY:
        await callback.answer("⛔ Лотерея отключена.", show_alert=True)
        return
    await _send_lottery_menu(callback.message)
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
            now = datetime.utcnow()
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
async def btn_promo(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if not await require_nickname(message, user):
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎟 Создать промокод", callback_data="promo_create")],
            [InlineKeyboardButton(text="🔑 Активировать промокод", callback_data="promo_activate")],
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
            prices=[LabeledPrice(label="Промокод", amount=star_cost)]
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
        f"• time_utc: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}\n"
        "• db: connected\n"
        "• bot: running",
    )


@router.message(Command("version"))
async def cmd_version(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not is_admin_or_super(message.from_user.id, user):
            return
            
    version = "1.2.0"
    changes = (
        "🔥 <b>Версия:</b> " + version + "\n\n"
        "<b>Последние изменения:</b>\n"
        "• SexTok: Absolute URL Fetching & Debug logs\n"
        "• SexTok: CORS headers injected\n"
        "• Quests: Перевод на русский\n"
        "• Games: Слоты, Дартс, Баскетбол\n"
        "• Economy: x10 Scale & Fixes\n"
        "• Core: AsyncPG 0.30 & Greenlet"
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



