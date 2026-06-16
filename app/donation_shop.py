"""
Донатный магазин — покупка привилегий за монеты
"""

from datetime import datetime
from decimal import Decimal
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from app.db import async_session
from app.services import (
    get_user, log_balance_change, log_user_action, activate_perk, has_active_perk, get_active_perks,
    PERK_ICONS, PERK_NAMES, is_admin_free_eligible,
)

router = Router()

DONATION_ITEMS = [
    {
        "id": "color_nick",
        "name": "🎨 Цветной ник",
        "price": 500,
        "description": "Твой ник будет выделяться цветом в чате и профиле",
        "duration_days": 30,
    },
    {
        "id": "gold_nick",
        "name": "👑 Золотой ник",
        "price": 1500,
        "description": "Престижный золотой цвет ника (самый крутой)",
        "duration_days": 30,
    },
    {
        "id": "coin_multiplier",
        "name": "💰 Бустер монет x1.5",
        "price": 600,
        "description": "Получаешь на 50% больше монет за просмотры и квесты",
        "duration_days": 7,
    },
    {
        "id": "xp_multiplier",
        "name": "📈 Бустер XP x2",
        "price": 500,
        "description": "Получаешь в 2 раза больше XP за все действия",
        "duration_days": 7,
    },
    {
        "id": "stars_discount",
        "name": "⭐ Скидка 25% на Stars",
        "price": 1000,
        "description": "Все покупки за Stars стоят на 25% дешевле",
        "duration_days": 30,
    },
    {
        "id": "priority_moderation",
        "name": "⚡ Приоритетная модерация",
        "price": 300,
        "description": "Твои видео проверяют в первую очередь",
        "duration_days": 14,
    },
    {
        "id": "exclusive_reactions",
        "name": "✨ Эксклюзивные реакции",
        "price": 400,
        "description": "Доступ к уникальным реакциям (💎, 🔥, 👑 и др.)",
        "duration_days": 30,
    },
]


def donation_shop_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for item in DONATION_ITEMS:
        label = f"{item['name']} — {item['price']:,} 🪙".replace(',', ' ')
        buttons.append([
            InlineKeyboardButton(text=label, callback_data=f"donate_buy:{item['id']}")
        ])
    buttons.append([InlineKeyboardButton(text="📋 Мои привилегии", callback_data="donate_my_perks")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="btn_profile")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data == "donation_shop")
async def show_donation_shop(callback: CallbackQuery):
    text = (
        "🛍 <b>Магазин привилегий</b>\n\n"
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

        admin_free = await is_admin_free_eligible(session, callback.from_user.id, user)

        # Проверяем, есть ли уже активный такой перк
        has_perk = await has_active_perk(session, user.id, item["id"])
        extra_info = ""
        if has_perk:
            extra_info = "\n⚠️ У тебя уже активна эта привилегия!\nПокупка <b>продлит</b> действие."

        if not admin_free and user.balance < item["price"]:
            await callback.answer(
                f"❌ Недостаточно монет. Нужно: {item['price']:,}".replace(',', ' '),
                show_alert=True,
            )
            return

        # Показываем подтверждение
        if admin_free:
            price_line = f"💰 Цена: <b>{item['price']:,} монет</b> <i>(🆓 бесплатно для админа)</i>\n".replace(',', ' ')
            balance_line = f"💳 Твой баланс: {user.balance:,.0f}".replace(',', ' ')
        else:
            price_line = f"💰 Цена: <b>{item['price']:,} монет</b>\n".replace(',', ' ')
            balance_line = f"💳 Твой баланс: {user.balance:,.0f} → {user.balance - item['price']:,.0f}".replace(',', ' ')

        text = (
            f"🛍 <b>Покупка: {item['name']}</b>\n\n"
            f"{item['description']}\n\n"
            f"{price_line}"
            f"⏳ Длительность: <b>{item['duration_days']} дней</b>\n"
            f"{balance_line}" +
            extra_info
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Купить", callback_data=f"donate_confirm:{item_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="donation_shop"),
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
        if not user:
            await callback.answer()
            return

        admin_free = await is_admin_free_eligible(session, callback.from_user.id, user)
        if not admin_free and user.balance < item["price"]:
            await callback.answer("Недостаточно монет", show_alert=True)
            return

        # Списываем деньги (или помечаем как бесплатно для админа)
        if admin_free:
            await log_balance_change(session, user, Decimal("0"), "donation_purchase_admin_free", details=f"{item['name']} (ADMIN_FREE)")
        else:
            await log_balance_change(session, user, -item["price"], "donation_purchase", details=item["name"])
            user.balance -= item["price"]

        # Активируем перк
        perk = await activate_perk(session, user.id, item["id"], item["duration_days"])
        expires = perk.active_until

        await log_user_action(session, user.id, "perk_activated", f"{item['name']} до {expires.strftime('%d.%m')}")
        await session.commit()

        await state.clear()

        free_badge = "\n🆓 <b>(Бесплатно для админа)</b>" if admin_free else ""
        await callback.message.edit_text(
            f"✅ <b>Покупка успешна!</b>{free_badge}\n\n"
            f"Вы приобрели: <b>{item['name']}</b>\n"
            f"Действует до: <b>{expires.strftime('%d.%m.%Y %H:%M')}</b>\n\n"
            f"Спасибо за поддержку! 💙",
            parse_mode="HTML",
        )
        await callback.answer("Привилегия активирована!", show_alert=True)


@router.callback_query(F.data == "donate_my_perks")
async def donate_my_perks(callback: CallbackQuery):
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return

        perks = await get_active_perks(session, user.id)

        if not perks:
            text = "🎖 <b>Мои привилегии</b>\n\nУ тебя пока нет активных привилегий.\nЗагляни в магазин!"
        else:
            text = "🎖 <b>Мои привилегии</b>\n\n"
            for perk in perks:
                icon = PERK_ICONS.get(perk.perk_type, "🔹")
                name = PERK_NAMES.get(perk.perk_type, perk.perk_type)
                days_left = (perk.active_until - datetime.utcnow()).days
                text += f"{icon} {name}\n"
                text += f"   ⏰ Осталось: <b>{days_left} дн.</b> (до {perk.active_until.strftime('%d.%m')})\n\n"

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛍 В магазин", callback_data="donation_shop")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="btn_profile")],
        ])
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
        await callback.answer()
