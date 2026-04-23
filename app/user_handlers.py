from decimal import Decimal
from aiogram import Router, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import (
    Message, CallbackQuery, LabeledPrice, PreCheckoutQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func, desc

from app.config import (
    ADMINS, WATCH_COST, STARS_PACKAGES, STARS_TO_COINS_RATE, REACTION_TYPES,
    XP_PER_WATCH, XP_PER_UPLOAD, XP_PER_RATING, XP_PER_COMMENT, XP_PER_REACTION, XP_PER_GAME,
    PIN_OFFER_COST, VIP_PRICE_STARS, VIP_DURATION_DAYS, VIP_BONUS_MULTIPLIER,
    LEVEL_XP_BASE, LEVEL_XP_MULTIPLIER, DAILY_QUESTS, PREMIUM_DAILY_QUESTS,
    COMMENTS_PER_10_MIN, COMMENT_MIN_INTERVAL_SEC
)
from app.db import async_session
from app.models import (
    User, Video, VideoView, Comment, ContentReaction,
    DailyQuestProgress, GameHistory, GameSession
)
from app.services import (
    get_or_create_user, get_user, get_user_by_id, save_video, save_photo,
    get_random_video_for_user, get_random_photo_for_user,
    record_view_and_charge, record_photo_view,
    count_photo_views_last_4h, rate_video, claim_daily_bonus, count_referrals,
    create_payment, create_custom_payment, apply_successful_payment,
    get_active_offers, get_offer_by_id, start_offer_participation,
    verify_offer_subscription, log_user_action, to_decimal
)
from app.keyboards import (
    rules_keyboard, main_menu, video_rating_keyboard, photo_actions_keyboard,
    watch_choice_keyboard, buy_coins_keyboard, vip_buy_keyboard,
    offers_list_keyboard, offer_view_keyboard, games_menu_keyboard,
    tops_menu_keyboard, quests_keyboard, reaction_menu_keyboard,
    BTN_WATCH, BTN_UPLOAD, BTN_PROFILE, BTN_BUY, BTN_OFFERS, BTN_REFERRALS,
    BTN_BONUS, BTN_ADMIN, BTN_GAMES, BTN_TOPS, BTN_QUESTS, BTN_VIP, BTN_LEVEL
)
from app.logger import get_logger, log_info, log_warning, log_exception

import random
import uuid
from datetime import datetime, timedelta

logger = get_logger(__name__)
router = Router()


# =========================
# STATES
# =========================
class UserOfferState(StatesGroup):
    waiting_title = State()
    waiting_description = State()
    waiting_url = State()
    waiting_payment = State()


class CommentState(StatesGroup):
    waiting_text = State()


class CustomBuyState(StatesGroup):
    waiting_stars = State()


class AdminMessageState(StatesGroup):
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
    """Сколько XP нужно для перехода на следующий уровень."""
    return int(LEVEL_XP_BASE * (LEVEL_XP_MULTIPLIER ** (level - 1)))


def calc_level_from_xp(xp: int) -> int:
    """Вычислить уровень по XP."""
    level = 1
    while True:
        required = calc_level_xp_required(level)
        if xp < required:
            break
        xp -= required
        level += 1
    return level


def is_vip(user) -> bool:
    if user.vip_until and user.vip_until > datetime.utcnow():
        return True
    return False


# =========================
# START / RULES
# =========================
@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext):
    if not message.from_user:
        return
    await state.clear()
    referral_code = command.args.strip() if command and command.args else None
    async with async_session() as session:
        user, is_new = await get_or_create_user(
            session, message.from_user.id, message.from_user.username,
            message.from_user.first_name, message.from_user.last_name, referral_code
        )
        if user.status == "banned":
            await message.answer("🚫 Вы заблокированы в боте.")
            return

        if not user.agreed_to_rules:
            await message.answer(
                "📋 <b>Правила бота</b>\n\n"
                "1. Запрещён контент 18+, насилие, спам.\n"
                "2. Загружайте только собственный контент.\n"
                "3. Не злоупотребляйте системой монет.\n\n"
                "Нажмите кнопку ниже, чтобы принять правила и начать.",
                parse_mode="HTML",
                reply_markup=rules_keyboard()
            )
            return

        admin_flag = is_any_admin(message.from_user.id, user)
        vip_str = " 👑 VIP" if is_vip(user) else ""
        await message.answer(
            f"👋 Добро пожаловать{vip_str}!\n💰 Баланс: <b>{user.balance}</b> монет",
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
        admin_flag = is_any_admin(callback.from_user.id, user)
        await callback.message.answer(
            f"✅ Правила приняты! Добро пожаловать!\n💰 Баланс: <b>{user.balance}</b> монет\n\n"
            f"Выберите действие:",
            parse_mode="HTML",
            reply_markup=main_menu(is_admin=admin_flag)
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

        refs = await count_referrals(session, user.id)
        vip_str = ""
        if is_vip(user):
            vip_str = f"\n👑 VIP до: {user.vip_until.strftime('%d.%m.%Y')}"

        # Подсчёт XP до следующего уровня
        level = user.level
        xp = user.xp
        xp_spent = sum(calc_level_xp_required(l) for l in range(1, level))
        xp_current = xp - xp_spent
        xp_needed = calc_level_xp_required(level)

        text = (
            f"👤 <b>Профиль</b>\n\n"
            f"🆔 ID: <code>{user.telegram_id}</code>\n"
            f"👤 Имя: {user.first_name or 'Не указано'}\n"
            f"💰 Баланс: <b>{user.balance}</b> монет\n"
            f"🏆 Уровень: <b>{user.level}</b>\n"
            f"⭐ XP: {xp_current}/{xp_needed}\n"
            f"👥 Рефералов: {refs}\n"
            f"💎 Реф. заработок: {user.referral_earnings} монет\n"
            f"📊 Статус: {user.status}"
            f"{vip_str}"
        )
        await message.answer(text, parse_mode="HTML")
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

        level = user.level
        xp = user.xp
        xp_spent = sum(calc_level_xp_required(l) for l in range(1, level))
        xp_current = xp - xp_spent
        xp_needed = calc_level_xp_required(level)
        progress = int((xp_current / xp_needed) * 10)
        bar = "█" * progress + "░" * (10 - progress)

        text = (
            f"🏆 <b>Ваш уровень</b>\n\n"
            f"Уровень: <b>{level}</b>\n"
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

        if is_vip(user):
            text = (
                f"👑 <b>Вы уже VIP!</b>\n\n"
                f"VIP активен до: <b>{user.vip_until.strftime('%d.%m.%Y %H:%M')}</b>\n\n"
                f"Преимущества VIP:\n"
                f"• Множитель монет x{VIP_BONUS_MULTIPLIER}\n"
                f"• Бесплатная загрузка фото\n"
                f"• Скидка 50% на просмотр\n"
                f"• Доступ к VIP квестам"
            )
            await message.answer(text, parse_mode="HTML")
        else:
            text = (
                f"👑 <b>VIP статус</b>\n\n"
                f"Стоимость: <b>{VIP_PRICE_STARS} Telegram Stars</b>\n"
                f"Длительность: {VIP_DURATION_DAYS} дней\n\n"
                f"Преимущества:\n"
                f"• Множитель монет x{VIP_BONUS_MULTIPLIER}\n"
                f"• Бесплатная загрузка фото\n"
                f"• Скидка 50% на просмотр\n"
                f"• Доступ к VIP квестам"
            )
            await message.answer(text, parse_mode="HTML", reply_markup=vip_buy_keyboard())


@router.callback_query(F.data == "buy_vip")
async def buy_vip(callback: CallbackQuery):
    await callback.message.answer_invoice(
        title="VIP статус",
        description=f"VIP на {VIP_DURATION_DAYS} дней с множителем x{VIP_BONUS_MULTIPLIER}",
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
        if not user.agreed_to_rules:
            await message.answer("Сначала примите правила /start")
            return
    await message.answer("Что хотите смотреть?", reply_markup=watch_choice_keyboard())


@router.callback_query(F.data == "watch_video_content")
async def watch_video_content(callback: CallbackQuery):
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return

        cost = to_decimal(WATCH_COST)
        if is_vip(user):
            cost = cost * to_decimal(0.5)

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
                "😔 Нет доступных видео для просмотра.\n"
                "Загрузите своё видео или попробуйте позже!"
            )
            await callback.answer()
            return

        ok = await record_view_and_charge(session, user.id, video.id)
        if not ok:
            await callback.message.answer("❌ Ошибка списания монет.")
            await callback.answer()
            return

        # Обновляем уровень
        user = await get_user(session, callback.from_user.id)
        new_level = calc_level_from_xp(user.xp)
        if new_level > user.level:
            user.level = new_level
            await session.commit()
            await callback.message.answer(f"🎉 Вы достигли уровня {new_level}!")

        await callback.message.answer_video(
            video.telegram_file_id,
            caption=f"🎬 Видео #{video.id}\n💰 Списано: {cost} монет",
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
    video_id = int(parts[1])
    rating = int(parts[2])

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        await rate_video(session, user.id, video_id, rating)
        user.xp += XP_PER_RATING
        new_level = calc_level_from_xp(user.xp)
        if new_level > user.level:
            user.level = new_level
            await session.commit()
            await callback.message.answer(f"🎉 Вы достигли уровня {new_level}!")
        else:
            await session.commit()

        # Обновляем квест
        await _update_quest_progress(session, user.id, "rate", 1)

    await callback.answer(f"⭐ Оценка {rating} сохранена!")


# =========================
# COMMENTS
# =========================
@router.callback_query(F.data.startswith("comments:"))
async def cb_comments(callback: CallbackQuery, state: FSMContext):
    video_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        # Показываем комментарии
        result = await session.execute(
            select(Comment).where(Comment.video_id == video_id)
            .order_by(desc(Comment.created_at)).limit(10)
        )
        comments = result.scalars().all()

        text = f"💬 <b>Комментарии к видео #{video_id}</b>\n\n"
        if not comments:
            text += "Комментариев пока нет. Будьте первым!"
        else:
            for c in comments:
                user_obj = await get_user_by_id(session, c.user_id)
                name = user_obj.first_name if user_obj else "???"
                text += f"👤 <b>{name}</b>: {c.text}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Оставить комментарий", callback_data=f"add_comment:{video_id}")],
        [InlineKeyboardButton(text="😀 Реакции", callback_data=f"reactions:{video_id}")]
    ])
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("add_comment:"))
async def add_comment_start(callback: CallbackQuery, state: FSMContext):
    video_id = int(callback.data.split(":")[1])
    await state.set_state(CommentState.waiting_text)
    await state.update_data(video_id=video_id)
    await callback.message.answer("✏️ Напишите ваш комментарий:")
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

        # Антиспам: не более COMMENTS_PER_10_MIN за 10 мин
        ten_min_ago = datetime.utcnow() - timedelta(minutes=10)
        recent_count_result = await session.execute(
            select(func.count(Comment.id)).where(
                Comment.user_id == user.id,
                Comment.created_at >= ten_min_ago
            )
        )
        recent_count = recent_count_result.scalar_one()
        if recent_count >= COMMENTS_PER_10_MIN:
            await message.answer(f"⚠️ Вы можете оставлять не более {COMMENTS_PER_10_MIN} комментариев за 10 минут.")
            await state.clear()
            return

        comment = Comment(user_id=user.id, video_id=video_id, text=message.text)
        session.add(comment)
        user.xp += XP_PER_COMMENT
        new_level = calc_level_from_xp(user.xp)
        if new_level > user.level:
            user.level = new_level
            await session.commit()
            await message.answer(f"🎉 Вы достигли уровня {new_level}!")
        else:
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
    video_id = int(parts[1])
    reaction = parts[2]

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return

        # Проверяем существующую реакцию
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
                user_id=user.id, video_id=video_id, reaction_type=reaction
            ))
            user.xp += XP_PER_REACTION
            new_level = calc_level_from_xp(user.xp)
            if new_level > user.level:
                user.level = new_level

        await session.commit()
        await _update_quest_progress(session, user.id, "react", 1)

    await callback.answer(f"{reaction} Реакция добавлена!")


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

    await message.answer(
        "📤 Отправьте видео или фото для загрузки.\n\n"
        "📋 Требования:\n"
        "• Видео: до 50 МБ\n"
        "• Фото: любой формат\n"
        "• Без запрещённого контента\n\n"
        "После проверки модератором вы получите монеты!"
    )


@router.message(F.video)
async def handle_video_upload(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user or user.status == "banned":
            return
        if not user.agreed_to_rules:
            await message.answer("Сначала примите правила /start")
            return

        video = message.video
        saved = await save_video(
            session, user.id, video.file_id, video.file_unique_id,
            video.duration, video.file_size
        )

        user.xp += XP_PER_UPLOAD
        new_level = calc_level_from_xp(user.xp)
        if new_level > user.level:
            user.level = new_level
            await session.commit()
            await message.answer(f"🎉 Вы достигли уровня {new_level}!")
        else:
            await session.commit()

        await _update_quest_progress(session, user.id, "upload", 1)

    await message.answer(
        f"✅ Видео #{saved.id} отправлено на модерацию!\n"
        f"После проверки вы получите монеты."
    )


@router.message(F.photo)
async def handle_photo_upload(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user or user.status == "banned":
            return
        if not user.agreed_to_rules:
            await message.answer("Сначала примите правила /start")
            return

        photo = message.photo[-1]
        saved = await save_photo(
            session, user.id, photo.file_id, photo.file_unique_id, photo.file_size
        )

        user.xp += XP_PER_UPLOAD
        new_level = calc_level_from_xp(user.xp)
        if new_level > user.level:
            user.level = new_level
        await session.commit()

        await _update_quest_progress(session, user.id, "upload", 1)

    await message.answer(
        f"✅ Фото #{saved.id} отправлено на модерацию!\n"
        f"После проверки вы получите монеты."
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
        ok, result = await claim_daily_bonus(session, user.id)
        if ok:
            await message.answer(f"🎁 Ежедневный бонус получен: <b>+{result} монет</b>!", parse_mode="HTML")
        else:
            await message.answer(f"⏳ {result}")


# =========================
# REFERRALS
# =========================
@router.message(F.text == BTN_REFERRALS)
async def btn_referrals(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        refs = await count_referrals(session, user.id)
        from app.config import REFERRAL_REWARD_INVITER, REFERRAL_REWARD_NEW_USER
        bot_info = await message.bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start={user.referral_code}"
        text = (
            f"👥 <b>Реферальная программа</b>\n\n"
            f"Ваша ссылка:\n<code>{ref_link}</code>\n\n"
            f"Приглашено: <b>{refs}</b> человек\n"
            f"Заработано: <b>{user.referral_earnings}</b> монет\n\n"
            f"💡 За каждого приглашённого:\n"
            f"• Вы получаете: +{REFERRAL_REWARD_INVITER} монет\n"
            f"• Новый пользователь: +{REFERRAL_REWARD_NEW_USER} монет"
        )
        await message.answer(text, parse_mode="HTML")


# =========================
# BUY COINS
# =========================
@router.message(F.text == BTN_BUY)
async def btn_buy(message: Message):
    await message.answer(
        "💳 <b>Пополнение баланса</b>\n\n"
        "Выберите пакет монет:",
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
        description=f"{pack['coins']} монет за {pack['stars']} Telegram Stars",
        payload=payment.payload,
        currency="XTR",
        prices=[LabeledPrice(label=pack['title'], amount=pack['stars'])]
    )
    await callback.answer()


@router.callback_query(F.data == "buy_custom")
async def cb_buy_custom(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CustomBuyState.waiting_stars)
    await callback.message.answer(
        "💫 Введите количество Telegram Stars (минимум 1):"
    )
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
        description=f"{coins} монет за {stars} Telegram Stars",
        payload=payment.payload,
        currency="XTR",
        prices=[LabeledPrice(label=f"{coins} монет", amount=stars)]
    )
    await state.clear()


@router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload

    # VIP покупка
    if payload.startswith("vip_"):
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if user:
                now = datetime.utcnow()
                if user.vip_until and user.vip_until > now:
                    user.vip_until = user.vip_until + timedelta(days=VIP_DURATION_DAYS)
                else:
                    user.vip_until = now + timedelta(days=VIP_DURATION_DAYS)
                await log_user_action(session, user.id, "buy_vip", f"Until: {user.vip_until}")
                await session.commit()
        await message.answer(
            f"👑 VIP статус активирован на {VIP_DURATION_DAYS} дней!\n"
            f"Наслаждайтесь привилегиями!"
        )
    else:
        # Обычная покупка монет
        async with async_session() as session:
            payment = await apply_successful_payment(session, payload)
            if payment:
                await message.answer(
                    f"✅ Оплата прошла успешно!\n"
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
        offers = await get_active_offers(session)
        if not offers:
            await message.answer("😔 Активных офферов пока нет.\nЗагляните позже!")
            return
        await message.answer(
            "📢 <b>Доступные офферы</b>\n\nВыберите оффер:",
            parse_mode="HTML",
            reply_markup=offers_list_keyboard(offers)
        )


@router.callback_query(F.data.startswith("offer_open:"))
async def cb_offer_open(callback: CallbackQuery):
    offer_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        offer = await get_offer_by_id(session, offer_id)
        if not offer:
            await callback.answer("Оффер не найден.", show_alert=True)
            return
        text = (
            f"📢 <b>{offer.title}</b>\n\n"
            f"{offer.description}\n\n"
            f"💰 Предварительный бонус: <b>{offer.reward_preview}</b> монет\n"
            f"🎁 Финальный бонус: <b>{offer.reward_final}</b> монет\n"
            f"⚠️ Штраф за отписку: {offer.penalty_unsubscribe} монет"
        )
        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=offer_view_keyboard(offer_id, offer.channel_url)
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
            await callback.answer("Вы уже участвуете в этом оффере!", show_alert=True)
            return
        offer = await get_offer_by_id(session, offer_id)
    await callback.answer(
        f"✅ Вы получили {offer.reward_preview} монет! Подпишитесь на канал и нажмите 'Проверить'.",
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
                f"✅ Подписка подтверждена! Получено {offer.reward_final} монет!",
                show_alert=True
            )
        else:
            await callback.answer("❌ Не удалось подтвердить подписку.", show_alert=True)


# =========================
# USER OFFERS (создание оффера пользователем)
# =========================
@router.message(F.text == "📝 Создать оффер")
async def create_user_offer_start(message: Message, state: FSMContext):
    await state.set_state(UserOfferState.waiting_title)
    await message.answer("Введите название вашего канала/группы (максимум 100 символов):")


@router.message(UserOfferState.waiting_title)
async def process_offer_title(message: Message, state: FSMContext):
    if len(message.text) > 100:
        await message.answer("❌ Слишком длинное название. Максимум 100 символов.")
        return
    await state.update_data(title=message.text)
    await state.set_state(UserOfferState.waiting_description)
    await message.answer("Введите описание оффера:")


@router.message(UserOfferState.waiting_description)
async def process_offer_desc(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(UserOfferState.waiting_url)
    await message.answer("Введите ссылку на канал (t.me/...):")


@router.message(UserOfferState.waiting_url)
async def process_offer_url(message: Message, state: FSMContext):
    if not message.text.startswith("https://t.me/") and not message.text.startswith("t.me/"):
        await message.answer("❌ Ссылка должна начинаться с t.me/ или https://t.me/")
        return
    await state.update_data(url=message.text)
    cost = PIN_OFFER_COST
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💰 Оплатить монетами ({cost})", callback_data="pay_offer_coins")],
        [InlineKeyboardButton(text="⭐ Оплатить Stars (50 Stars)", callback_data="pay_offer_stars")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_offer")]
    ])
    await message.answer(
        f"Стоимость размещения: <b>{cost} монет</b> или <b>50 Telegram Stars</b>.\n"
        f"Выберите способ оплаты:",
        parse_mode="HTML",
        reply_markup=kb
    )
    await state.set_state(UserOfferState.waiting_payment)


@router.callback_query(UserOfferState.waiting_payment, F.data == "pay_offer_coins")
async def pay_offer_coins(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer("Пользователь не найден!", show_alert=True)
            return
        if user.balance < to_decimal(PIN_OFFER_COST):
            await callback.answer("Недостаточно монет!", show_alert=True)
            return
        user.balance -= to_decimal(PIN_OFFER_COST)
        from app.models import Offer
        new_offer = Offer(
            creator_user_id=user.id,
            title=data['title'],
            description=data['description'],
            channel_url=data['url'],
            status="pending",
            is_active=False
        )
        session.add(new_offer)
        await log_user_action(session, user.id, "create_offer", f"Offer: {data['title']}, Paid: {PIN_OFFER_COST} coins")
        await session.commit()
    await callback.message.answer(
        "✅ Оффер отправлен на проверку! После одобрения модератором он появится в списке."
    )
    await state.clear()
    await callback.answer()


@router.callback_query(UserOfferState.waiting_payment, F.data == "pay_offer_stars")
async def pay_offer_stars(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    payload = f"offer_{callback.from_user.id}_{data.get('title', '')[:10]}_{uuid.uuid4().hex[:6]}"
    await state.update_data(offer_payload=payload)
    await callback.message.answer_invoice(
        title="Размещение оффера",
        description=f"Оффер: {data.get('title', '')}",
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(label="Размещение оффера", amount=50)]
    )
    await callback.answer()


@router.callback_query(UserOfferState.waiting_payment, F.data == "cancel_offer")
async def cancel_offer(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Создание оффера отменено.")
    await callback.answer()


# =========================
# GAMES
# =========================
@router.message(F.text == BTN_GAMES)
async def btn_games(message: Message):
    await message.answer(
        "🎮 <b>Игровой центр</b>\n\n"
        "Выберите игру:",
        parse_mode="HTML",
        reply_markup=games_menu_keyboard()
    )


@router.callback_query(F.data == "game_dice")
async def game_dice(callback: CallbackQuery):
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1 монета", callback_data="dice_bet:1"),
            InlineKeyboardButton(text="5 монет", callback_data="dice_bet:5"),
        ],
        [
            InlineKeyboardButton(text="10 монет", callback_data="dice_bet:10"),
            InlineKeyboardButton(text="25 монет", callback_data="dice_bet:25"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="games_back")]
    ])
    await callback.message.answer(
        "🎲 <b>Игра в кости</b>\n\n"
        "Бросаем кубик! Если выпадет 4, 5 или 6 — вы выигрываете двойную ставку!\n\n"
        "Выберите ставку:",
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

        # Бросаем кости через Telegram
        dice_msg = await callback.message.answer_dice(emoji="🎲")
        dice_value = dice_msg.dice.value

        user.balance -= to_decimal(bet)
        user.xp += XP_PER_GAME

        if dice_value >= 4:
            win = to_decimal(bet) * 2
            user.balance += win
            result_text = f"🎲 Выпало: {dice_value}\n🎉 Вы выиграли! +{win} монет"
            net = win - to_decimal(bet)
        else:
            result_text = f"🎲 Выпало: {dice_value}\n😔 Вы проиграли -{bet} монет"
            net = -to_decimal(bet)

        # Обновляем уровень
        new_level = calc_level_from_xp(user.xp)
        if new_level > user.level:
            user.level = new_level

        from app.models import GameHistory
        session.add(GameHistory(
            user_id=user.id, game_type="dice",
            bet=to_decimal(bet), result=net,
            details=f"Dice value: {dice_value}"
        ))
        await session.commit()

    await callback.message.answer(
        f"{result_text}\n💰 Баланс: {user.balance}"
    )
    await callback.answer()


@router.callback_query(F.data == "game_coinflip")
async def game_coinflip(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1 монета", callback_data="coinflip_bet:1"),
            InlineKeyboardButton(text="5 монет", callback_data="coinflip_bet:5"),
        ],
        [
            InlineKeyboardButton(text="10 монет", callback_data="coinflip_bet:10"),
            InlineKeyboardButton(text="25 монет", callback_data="coinflip_bet:25"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="games_back")]
    ])
    await callback.message.answer(
        "🪙 <b>Орёл или решка</b>\n\n"
        "50/50 шанс удвоить ставку!\n\n"
        "Выберите ставку:",
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
        # 1-3 = решка, 4-6 = орёл (условно)
        result = coin_msg.dice.value
        won = result >= 4

        user.balance -= to_decimal(bet)
        user.xp += XP_PER_GAME

        if won:
            win = to_decimal(bet) * 2
            user.balance += win
            result_text = f"🪙 Орёл! 🎉 Вы выиграли +{win} монет"
            net = win - to_decimal(bet)
        else:
            result_text = f"🪙 Решка! 😔 Вы проиграли -{bet} монет"
            net = -to_decimal(bet)

        new_level = calc_level_from_xp(user.xp)
        if new_level > user.level:
            user.level = new_level

        from app.models import GameHistory
        session.add(GameHistory(
            user_id=user.id, game_type="coinflip",
            bet=to_decimal(bet), result=net,
            details=f"Won: {won}"
        ))
        await session.commit()

    await callback.message.answer(f"{result_text}\n💰 Баланс: {user.balance}")
    await callback.answer()


@router.callback_query(F.data == "game_guess")
async def game_guess(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1 монета", callback_data="guess_bet:1"),
            InlineKeyboardButton(text="5 монет", callback_data="guess_bet:5"),
        ],
        [
            InlineKeyboardButton(text="10 монет", callback_data="guess_bet:10"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="games_back")]
    ])
    await callback.message.answer(
        "🎯 <b>Угадай число</b>\n\n"
        "Угадайте число от 1 до 6 — выиграйте x5 ставки!\n\n"
        "Выберите ставку:",
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
        ]
    ])
    await callback.message.answer("Выберите число от 1 до 6:", reply_markup=kb)
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
            result_text = f"🎯 Выпало {actual}! Вы угадали! 🎉 +{win} монет"
            net = win - to_decimal(bet)
        else:
            result_text = f"🎯 Выпало {actual}, вы выбрали {guess}. 😔 -{bet} монет"
            net = -to_decimal(bet)

        new_level = calc_level_from_xp(user.xp)
        if new_level > user.level:
            user.level = new_level

        from app.models import GameHistory
        session.add(GameHistory(
            user_id=user.id, game_type="guess",
            bet=to_decimal(bet), result=net,
            details=f"Guess: {guess}, Actual: {actual}"
        ))
        await session.commit()

    await callback.message.answer(f"{result_text}\n💰 Баланс: {user.balance}")
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "games_back")
async def games_back(callback: CallbackQuery):
    await callback.message.answer("🎮 Игровой центр:", reply_markup=games_menu_keyboard())
    await callback.answer()


# =========================
# TOPS
# =========================
@router.message(F.text == BTN_TOPS)
async def btn_tops(message: Message):
    await message.answer(
        "🏆 <b>Топы</b>\n\nВыберите рейтинг:",
        parse_mode="HTML",
        reply_markup=tops_menu_keyboard()
    )


@router.callback_query(F.data == "top_uploaders")
async def top_uploaders(callback: CallbackQuery):
    async with async_session() as session:
        result = await session.execute(
            select(User.first_name, User.username, func.count(Video.id).label("cnt"))
            .join(Video, Video.uploader_user_id == User.id)
            .where(Video.status == "approved")
            .group_by(User.id)
            .order_by(desc("cnt"))
            .limit(10)
        )
        rows = result.all()

    text = "🎬 <b>Топ загрузчиков</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, row in enumerate(rows):
        icon = medals[i] if i < 3 else f"{i+1}."
        name = row.first_name or row.username or "???"
        text += f"{icon} {name} — {row.cnt} видео\n"
    if not rows:
        text += "Пусто"
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "top_viewers")
async def top_viewers(callback: CallbackQuery):
    async with async_session() as session:
        result = await session.execute(
            select(User.first_name, User.username, func.count(VideoView.id).label("cnt"))
            .join(VideoView, VideoView.user_id == User.id)
            .group_by(User.id)
            .order_by(desc("cnt"))
            .limit(10)
        )
        rows = result.all()

    text = "👁 <b>Топ зрителей</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, row in enumerate(rows):
        icon = medals[i] if i < 3 else f"{i+1}."
        name = row.first_name or row.username or "???"
        text += f"{icon} {name} — {row.cnt} просмотров\n"
    if not rows:
        text += "Пусто"
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "top_levels")
async def top_levels(callback: CallbackQuery):
    async with async_session() as session:
        result = await session.execute(
            select(User.first_name, User.username, User.level, User.xp)
            .order_by(desc(User.xp))
            .limit(10)
        )
        rows = result.all()

    text = "⭐ <b>Топ по XP</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, row in enumerate(rows):
        icon = medals[i] if i < 3 else f"{i+1}."
        name = row.first_name or row.username or "???"
        text += f"{icon} {name} — Ур.{row.level} ({row.xp} XP)\n"
    if not rows:
        text += "Пусто"
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "top_richest")
async def top_richest(callback: CallbackQuery):
    async with async_session() as session:
        result = await session.execute(
            select(User.first_name, User.username, User.balance)
            .order_by(desc(User.balance))
            .limit(10)
        )
        rows = result.all()

    text = "💰 <b>Топ богатых</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, row in enumerate(rows):
        icon = medals[i] if i < 3 else f"{i+1}."
        name = row.first_name or row.username or "???"
        text += f"{icon} {name} — {row.balance} монет\n"
    if not rows:
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

        today = datetime.utcnow().date()
        quests = (await session.execute(
            select(DailyQuestProgress).where(
                DailyQuestProgress.user_id == user.id,
                DailyQuestProgress.quest_date == today
            )
        )).scalars().all()

        # Создаём квесты если их нет
        if not quests:
            quest_list = DAILY_QUESTS.copy()
            if is_vip(user):
                quest_list += PREMIUM_DAILY_QUESTS
            for q in quest_list:
                dq = DailyQuestProgress(
                    user_id=user.id,
                    quest_type=q["type"],
                    quest_date=today,
                    progress=0,
                    target=q["target"],
                    reward=to_decimal(q["reward"]),
                    completed=False,
                    reward_claimed=False
                )
                session.add(dq)
            await session.commit()
            quests = (await session.execute(
                select(DailyQuestProgress).where(
                    DailyQuestProgress.user_id == user.id,
                    DailyQuestProgress.quest_date == today
                )
            )).scalars().all()

        if not quests:
            await message.answer("📋 Квесты недоступны.")
            return

        text = "📋 <b>Ежедневные квесты</b>\n\n"
        for q in quests:
            status = "✅" if q.completed else "⏳"
            claimed = " (получено)" if q.reward_claimed else ""
            text += f"{status} {q.quest_type}: {q.progress}/{q.target} — {q.reward} монет{claimed}\n"

        await message.answer(text, parse_mode="HTML", reply_markup=quests_keyboard(quests))


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
        user.balance += quest.reward
        await session.commit()

    await callback.answer(f"🎁 Получено {quest.reward} монет!", show_alert=True)


# =========================
# HELPER: обновление прогресса квестов
# =========================
async def _update_quest_progress(session, user_id: int, quest_type: str, amount: int = 1):
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