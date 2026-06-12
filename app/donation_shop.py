"""
Донатный магазин — все фичи
"""

from datetime import datetime, timedelta
from decimal import Decimal
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select

from app.db import async_session
from app.models import User
from app.services import get_user, log_balance_change, log_user_action, get_display_name

router = Router()


class DonationState(StatesGroup):
    waiting_confirm = State()


DONATION_ITEMS = [
    {
        "id": "color_nick",
        "name": "🎨 Цветной ник",
        "price": 3500,
        "description": "Твой ник будет выделяться цветом в чате и профиле",
        "duration_days": 30,
        "type": "permanent_color"
    },
    {
        "id": "gold_nick",
        "name": "👑 Золотой ник",
        "price": 10000,
        "description": "Престижный золотой цвет ника (самый крутой)",
        "duration_days": 30,
        "type": "permanent_gold"
    },
    {
        "id": "coin_booster",
        "name": "💰 Бустер монет x1.5",
        "price": 4500,
        "description": "Получаешь на 50% больше монет за просмотры и квесты",
        "duration_days": 7,
        "type": "coin_multiplier"
    },
    {
        "id": "xp_booster",
        "name": "📈 Бустер XP x2",
        "price": 4000,
        "description": "Получаешь в 2 раза больше XP",
        "duration_days": 7,
        "type": "xp_multiplier"
    },
    {
        "id": "stars_discount",
        "name": "⭐ Скидка 25% на Stars",
        "price": 7500,
        "description": "Все покупки за Stars стоят на 25% дешевле",
        "duration_days": 30,
        "type": "stars_discount"
    },
    {
        "id": "priority_moderation",
        "name": "⚡ Приоритетная модерация",
        "price": 2000,
        "description": "Твои видео проверяют в первую очередь",
        "duration_days": 14,
        "type": "priority"
    },
    {
        "id": "exclusive_reactions",
        "name": "✨ Эксклюзивные реакции",
        "price": 2800,
        "description": "Доступ к уникальным реакциям (💎, 🔥, 👑 и др.)",
        "duration_days": 30,
        "type": "reactions"
    },
]


def donation_shop_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for item in DONATION_ITEMS:
        buttons.append([
            InlineKeyboardButton(
                text=f"{item['name']} — {item['price']} 🪙",
                callback_data=f"donate_buy:{item['id']}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="btn_profile")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data == "donation_shop")
async def show_donation_shop(callback: CallbackQuery):
    text = (
        "🛍 <b>Донатный магазин</b>\n\n"
        "Здесь ты можешь приобрести крутые привилегии за монеты.\n"
        "Все цены указаны в монетах.\n\n"
        "Выбери, что хочешь купить:"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=donation_shop_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("donate_buy:"))
async def donate_buy(callback: CallbackQuery, state: FSMContext):
    item_id = callback.data.split(":")[1]
    item = next((i for i in DONATION_ITEMS if i["id"] == item_id), None)
    
    if not item:
        await callback.answer("Товар не найден", show_alert=True)
        return
    
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        
        if user.balance < item["price"]:
            await callback.answer(f"❌ Недостаточно монет. Нужно: {item['price']}", show_alert=True)
            return
        
        # Показываем подтверждение
        text = (
            f"🛍 <b>Покупка: {item['name']}</b>\n\n"
            f"{item['description']}\n\n"
            f"💰 Цена: <b>{item['price']} монет</b>\n"
            f"⏳ Длительность: <b>{item['duration_days']} дней</b>\n\n"
            f"Твой баланс: {user.balance:.0f} → {user.balance - item['price']:.0f}"
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Купить", callback_data=f"donate_confirm:{item_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="donation_shop")
            ]
        ])
        
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await state.update_data(selected_item=item_id)
    await callback.answer()


@router.callback_query(F.data.startswith("donate_confirm:"))
async def donate_confirm(callback: CallbackQuery, state: FSMContext):
    item_id = callback.data.split(":")[1]
    item = next((i for i in DONATION_ITEMS if i["id"] == item_id), None)
    
    if not item:
        await callback.answer("Ошибка", show_alert=True)
        return
    
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user or user.balance < item["price"]:
            await callback.answer("Недостаточно монет", show_alert=True)
            return
        
        # Списываем деньги
        await log_balance_change(session, user, -item["price"], "donation_purchase", details=item["name"])
        user.balance -= item["price"]
        
        # Применяем эффект
        now = datetime.utcnow()
        expires = now + timedelta(days=item["duration_days"])
        
        # Здесь должна быть логика применения перков
        # Пока просто логируем
        await log_user_action(session, user.id, "donation_bought", f"{item['name']} до {expires.strftime('%d.%m')}")
        
        await session.commit()
    
    await state.clear()
    
    await callback.message.edit_text(
        f"✅ <b>Покупка успешна!</b>\n\n"
        f"Вы приобрели: <b>{item['name']}</b>\n"
        f"Действует до: <b>{expires.strftime('%d.%m.%Y')}</b>\n\n"
        f"Спасибо за поддержку! 💙",
        parse_mode="HTML"
    )
    await callback.answer("Покупка совершена!", show_alert=True)


# Вспомогательные функции для применения бонусов (пример)
async def has_active_perk(user_id: int, perk_type: str) -> bool:
    """Проверка активного перка (заглушка)"""
    # В реальной реализации — проверка в БД
    return False


async def get_coin_multiplier(user_id: int) -> float:
    """Множитель монет (если есть бустер)"""
    if await has_active_perk(user_id, "coin_multiplier"):
        return 1.5
    return 1.0


async def get_xp_multiplier(user_id: int) -> float:
    """Множитель XP"""
    if await has_active_perk(user_id, "xp_multiplier"):
        return 2.0
    return 1.0
