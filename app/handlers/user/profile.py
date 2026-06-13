"""
Profile, level, VIP handlers.
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from app.db import async_session
from app.services import get_user, update_user_balance, get_display_name
from app.utils.admin import check_admin
from app.keyboards import main_menu

router = Router()

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
