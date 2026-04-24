import re
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from aiogram import Router, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    LabeledPrice, PreCheckoutQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from sqlalchemy import select, func, desc

from app.config import (
    ADMINS, WATCH_COST, STARS_PACKAGES, STARS_TO_COINS_RATE,
    XP_PER_WATCH, XP_PER_UPLOAD, XP_PER_RATING,
    XP_PER_COMMENT, XP_PER_REACTION, XP_PER_GAME,
    PIN_OFFER_COST, VIP_PRICE_STARS, VIP_DURATION_DAYS, VIP_BONUS_MULTIPLIER,
    LEVEL_XP_BASE, LEVEL_XP_MULTIPLIER,
    DAILY_QUESTS, PREMIUM_DAILY_QUESTS,
    COMMENTS_PER_10_MIN,
    NICKNAME_CHANGE_COST, NICKNAME_MIN_LENGTH, NICKNAME_MAX_LENGTH,
    OFFER_DEFAULT_RENT_COST_PER_DAY, OFFER_MIN_RENT_DAYS, OFFER_MAX_RENT_DAYS,
    REFERRAL_REWARD_INVITER, REFERRAL_REWARD_NEW_USER,
)
from app.db import async_session
from app.models import (
    User, Video, VideoView, Comment, ContentReaction,
    DailyQuestProgress, GameHistory, OfferRental, Offer,
)
from app.services import (
    get_or_create_user, get_user, get_user_by_id,
    save_video, save_photo,
    get_random_video_for_user, get_random_photo_for_user,
    record_view_and_charge, record_photo_view,
    rate_video, claim_daily_bonus, count_referrals,
    create_payment, create_custom_payment, apply_successful_payment,
    get_active_offers, get_rentable_offers, get_offer_by_id,
    start_offer_participation, verify_offer_subscription,
    create_offer_rental, get_user_rentals,
    log_user_action, to_decimal,
    set_display_name, get_display_name, log_balance_change,
)
from app.keyboards import (
    rules_keyboard, main_menu,
    video_rating_keyboard, photo_actions_keyboard,
    watch_choice_keyboard, buy_coins_keyboard, vip_buy_keyboard,
    offers_list_keyboard, offer_view_keyboard,
    offer_rent_keyboard, rent_days_keyboard,
    games_menu_keyboard, tops_menu_keyboard,
    quests_keyboard, reaction_menu_keyboard,
    BTN_WATCH, BTN_UPLOAD, BTN_PROFILE, BTN_BUY,
    BTN_OFFERS, BTN_REFERRALS, BTN_BONUS, BTN_ADMIN,
    BTN_GAMES, BTN_TOPS, BTN_QUESTS, BTN_VIP, BTN_LEVEL,
)
from app.logger import get_logger

logger = get_logger(__name__)
router = Router()


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
        ok, msg = await set_display_name(session, user, name)

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
    referral_code = (command.args or "").strip() or None

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
            await message.answer(
                "📋 <b>Правила бота</b>\n\n"
                "1. Вы все знаете для чего этот бот. Вот и не кидайте хрень всякую (Я про шок-контент).\n"
                "2. Не багоюзте, и будет вам кайф.\n"
                "3. Наслаждайтесь, самым уникальным и проработанным проектом в данной тематике.\n\n"
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
        await message.answer(
            f"👋 Привет, <b>{get_display_name(user)}</b>{vip_str}!\n"
            f"💰 Баланс: <b>{user.balance}</b> монет",
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
        await session.commit()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✏️ Установить ник",
            callback_data="set_nickname_start"
        )]
    ])
    await callback.message.answer(
        "✅ Правила приняты!\n\n"
        "⚠️ Теперь установите ник. Первая установка бесплатна!\n"
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
        xp_spent = sum(calc_level_xp_required(l) for l in range(1, level))
        xp_current = user.xp - xp_spent
        xp_needed = calc_level_xp_required(level)
        progress = max(0, min(10, int((xp_current / max(xp_needed, 1)) * 10)))
        bar = "█" * progress + "░" * (10 - progress)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="✏️ Сменить ник",
                callback_data="set_nickname_start"
            )]
        ])
        text = (
            f"👤 <b>Профиль</b>\n\n"
            f"🏷 Ник: <b>{get_display_name(user)}</b>\n"
            f"🆔 TG ID: <code>{user.telegram_id}</code>\n"
            f"💰 Баланс: <b>{user.balance}</b> монет\n"
            f"🏆 Уровень: <b>{user.level}</b>\n"
            f"⭐ XP: {xp_current}/{xp_needed} [{bar}]\n"
            f"👥 Рефералов: {refs}\n"
            f"💎 Реф. заработок: {user.referral_earnings} монет\n"
            f"📊 Статус: {user.status}"
            f"{vip_str}\n\n"
            f"Смена ника: {NICKNAME_CHANGE_COST} монет"
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
        xp_spent = sum(calc_level_xp_required(l) for l in range(1, level))
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
            await message.answer(
                f"👑 <b>VIP статус</b>\n\n"
                f"Стоимость: <b>{VIP_PRICE_STARS} Stars</b>\n"
                f"Длительность: {VIP_DURATION_DAYS} дней\n\n"
                f"Привилегии:\n"
                f"• Множитель монет x{VIP_BONUS_MULTIPLIER}\n"
                f"• Скидка 50% на просмотр\n"
                f"• VIP квесты",
                parse_mode="HTML",
                reply_markup=vip_buy_keyboard()
            )


@router.callback_query(F.data == "buy_vip")
async def buy_vip(callback: CallbackQuery):
    await callback.message.answer_invoice(
        title="VIP статус",
        description=f"VIP на {VIP_DURATION_DAYS} дней",
        payload=f"vip_{callback.from_user.id}_{uuid.uuid4().hex[:6]}",
        currency="XTR",
        prices=[LabeledPrice(label="VIP", amount=VIP_PRICE_STARS)]
    )
    await callback.answer()


# =========================
# WATCH
# =========================
@router.message(F.text == BTN_WATCH)
async def btn_watch(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if user.status == "banned":
            await message.answer("🚫 Вы заблокированы.")
            return
        if not await require_nickname(message, user):
            return
    await message.answer("Что смотреть?", reply_markup=watch_choice_keyboard())


@router.callback_query(F.data == "watch_video_content")
async def watch_video_content(callback: CallbackQuery):
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return

        cost = to_decimal(WATCH_COST)
        if is_vip(user):
            cost = round(cost * to_decimal(0.5), 2)

        if user.balance < cost:
            await callback.message.answer(
                f"❌ Недостаточно монет!\n"
                f"Нужно: {cost}, у вас: {user.balance}\n"
                f"Пополните баланс в разделе 💳 Купить"
            )
            await callback.answer()
            return

        video = await get_random_video_for_user(session, user.id)
        if not video:
            await callback.message.answer(
                "😔 Нет доступных видео.\n"
                "Загрузите своё видео или попробуйте позже!"
            )
            await callback.answer()
            return

        ok = await record_view_and_charge(session, user.id, video.id)
        if not ok:
            await callback.message.answer("❌ Ошибка списания монет.")
            await callback.answer()
            return

        user = await get_user(session, callback.from_user.id)
        await _level_up_check(session, user, callback)
        await _update_quest_progress(session, user.id, "watch", 1)

    await callback.message.answer_video(
        video.telegram_file_id,
        caption=(
            f"🎬 Видео #{video.id}\n"
            f"💰 Списано: {cost} монет"
        ),
        reply_markup=video_rating_keyboard(video.id)
    )
    await callback.answer()


@router.callback_query(F.data == "watch_next")
async def watch_next(callback: CallbackQuery):
    await watch_video_content(callback)


@router.callback_query(F.data == "watch_photo_content")
async def watch_photo_content(callback: CallbackQuery):
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        photo = await get_random_photo_for_user(session, user.id)
        if not photo:
            await callback.message.answer("😔 Нет доступных фото.")
            await callback.answer()
            return
        await record_photo_view(session, user.id, photo.id)

    await callback.message.answer_photo(
        photo.telegram_file_id,
        caption=f"🖼 Фото #{photo.id}",
        reply_markup=photo_actions_keyboard(photo.id)
    )
    await callback.answer()


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
                text += f"👤 <b>{name}</b>: {c.text}\n"

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

    await callback.answer(f"{reaction} Реакция!")


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
            await message.answer(
                "⚠️ Это видео уже есть в базе и не может быть загружено повторно."
            )
            return

        user.xp += XP_PER_UPLOAD
        await _level_up_check(session, user, message)
        await _update_quest_progress(session, user.id, "upload", 1)
        await message.answer(
            f"✅ Видео #{saved.id} отправлено на модерацию!"
        )


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
            await message.answer(
                "⚠️ Это фото уже есть в базе и не может быть загружено повторно."
            )
            return

        user.xp += XP_PER_UPLOAD
        await _level_up_check(session, user, message)
        await _update_quest_progress(session, user.id, "upload", 1)
        await message.answer(
            f"✅ Фото #{saved.id} отправлено на модерацию!"
        )
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
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if not await require_nickname(message, user):
            return
    await message.answer(
        "💳 <b>Пополнение баланса</b>\n\nВыберите пакет:",
        parse_mode="HTML",
        reply_markup=buy_coins_keyboard()
    )


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
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload

    if payload.startswith("vip_"):
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if user:
                now = datetime.utcnow()
                user.vip_until = (
                    user.vip_until + timedelta(days=VIP_DURATION_DAYS)
                    if user.vip_until and user.vip_until > now
                    else now + timedelta(days=VIP_DURATION_DAYS)
                )
                await log_user_action(
                    session, user.id,
                    "buy_vip",
                    f"until={user.vip_until}"
                )
                await session.commit()
        await message.answer(
            f"👑 VIP активирован на {VIP_DURATION_DAYS} дней!"
        )
    else:
        async with async_session() as session:
            payment = await apply_successful_payment(session, payload)
        if payment:
            await message.answer(
                f"✅ Оплата успешна!\n"
                f"💰 Начислено: <b>{payment.coins_amount}</b> монет",
                parse_mode="HTML"
            )
        else:
            await message.answer("✅ Оплата получена!")


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

        # Кол-во участников
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
        f"👥 Участников: {participants}"
    )

    # Если оффер поддерживает аренду — показываем кнопку
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
    offer_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        result = await verify_offer_subscription(session, user.id, offer_id)
        if result:
            offer = await get_offer_by_id(session, offer_id)
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
                    select(func.count(OfferRental.id)).where(
                        OfferRental.offer_id == o.id,
                        OfferRental.status.in_(["active", "pending"])
                    )
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
        offers = await get_active_offers(session)
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

        # Проверяем слоты
        active_count = (await session.execute(
            select(func.count(OfferRental.id)).where(
                OfferRental.offer_id == offer_id,
                OfferRental.status.in_(["active", "pending"])
            )
        )).scalar_one()
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

    # Показываем итог
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
# GAMES
# =========================
@router.message(F.text == BTN_GAMES)
async def btn_games(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if not await require_nickname(message, user):
            return
    await message.answer(
        "🎮 <b>Игровой центр</b>",
        parse_mode="HTML",
        reply_markup=games_menu_keyboard()
    )


@router.callback_query(F.data == "game_dice")
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

        dice_msg = await callback.message.answer_dice(emoji="🎲")
        dice_value = dice_msg.dice.value

        user.balance -= to_decimal(bet)

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

        coin_msg = await callback.message.answer_dice(emoji="🪙")
        won = coin_msg.dice.value >= 4

        user.balance -= to_decimal(bet)
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


@router.callback_query(F.data == "game_guess")
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

        dice_msg = await callback.message.answer_dice(emoji="🎲")
        actual = dice_msg.dice.value

        user.balance -= to_decimal(bet)
        user.xp += XP_PER_GAME

        if guess == actual:
            win = to_decimal(bet) * 5
            user.balance += win
            net = win - to_decimal(bet)
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
        for q in quests:
            status = "✅" if q.completed else "⏳"
            claimed = " ✔ получено" if q.reward_claimed else ""
            text += (
                f"{status} {q.quest_type}: "
                f"{q.progress}/{q.target} — "
                f"{q.reward} монет{claimed}\n"
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
            DailyQuestProgress.completed == False
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