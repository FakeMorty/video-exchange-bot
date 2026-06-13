"""
Broadcast handlers.
"""
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select

from app.db import async_session
from app.models import User
from app.utils.admin import check_admin, _safe_edit
from app.config import ENABLE_ADMIN_BROADCAST

router = Router()

async def process_broadcast(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    if not ENABLE_ADMIN_BROADCAST:
        await message.answer("⛔ Рассылка отключена в конфигурации.")
        await state.clear()
        return
    await state.clear()
    async with async_session() as session:
        tg_ids = (await session.execute(
            select(User.telegram_id).where(User.status == "active")
        )).scalars().all()

    sent = failed = 0
    for tg_id in tg_ids:
        try:
            await message.bot.send_message(
                tg_id,
                f"📢 <b>Объявление:</b>\n\n{message.text}",
                parse_mode="HTML"
            )
            sent += 1
        except Exception:
            failed += 1

    await message.answer(
        f"✅ Рассылка завершена!\n📨 Отправлено: {sent}\n❌ Ошибок: {failed}"
    )


# =========================
# OFFERS MANAGEMENT (ADMIN)
# =========================
@router.callback_query(F.data == "admin_offers_menu")
async def admin_offers_menu(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        pending_count = (await session.execute(
            select(func.count(Offer.id)).where(Offer.status == "pending")
        )).scalar_one()
        total_count = (await session.execute(
            select(func.count(Offer.id))
        )).scalar_one()
        active_count = (await session.execute(
            select(func.count(Offer.id)).where(
                Offer.is_active,
                Offer.status == "approved"
            )
        )).scalar_one()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="➕ Создать оффер (системный)",
            callback_data="admin_create_offer"
        )],
        [InlineKeyboardButton(
            text=f"⏳ На проверку ({pending_count})",
            callback_data="admin_offers_pending"
        )],
        [InlineKeyboardButton(
            text=f"📋 Все офферы ({total_count})",
            callback_data="admin_offers_all"
        )],
        [InlineKeyboardButton(
            text=f"✅ Активные ({active_count})",
            callback_data="admin_offers_active"
        )],
        [InlineKeyboardButton(
            text="🔑 Управление арендой",
            callback_data="admin_rentals_menu"
        )],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")],
    ])
    await _safe_edit(
        callback,
        f"📢 <b>Управление офферами</b>\n\n"
        f"Всего: {total_count} | Активных: {active_count} | "
        f"На проверке: {pending_count}",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data == "admin_create_offer")
