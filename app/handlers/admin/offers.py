"""
Offers and broadcast handlers.
"""
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select

from app.db import async_session
from app.models import User, Offer
from app.services import admin_create_offer
from app.utils.admin import check_admin
from app.keyboards import admin_after_action_keyboard
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
async def admin_create_offer_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminOfferCreateState.waiting_title)
    await callback.message.answer(
        "📢 <b>Создание оффера (шаг 1/9)</b>\n\n"
        "Введите название оффера (название канала/группы):",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(AdminOfferCreateState.waiting_title)
async def admin_offer_title(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    if len(message.text) > 100:
        await message.answer("❌ Название слишком длинное. Макс. 100 символов.")
        return
    await state.update_data(title=message.text.strip())
    await state.set_state(AdminOfferCreateState.waiting_description)
    await message.answer(
        "📝 <b>Шаг 2/9</b>\n\nВведите описание оффера:",
        parse_mode="HTML"
    )


@router.message(AdminOfferCreateState.waiting_description)
async def admin_offer_description(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    await state.update_data(description=message.text.strip())
    await state.set_state(AdminOfferCreateState.waiting_url)
    await message.answer(
        "🔗 <b>Шаг 3/9</b>\n\nВведите ссылку на канал (https://t.me/...):",
        parse_mode="HTML"
    )


@router.message(AdminOfferCreateState.waiting_url)
async def admin_offer_url(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    url = message.text.strip()
    if not (url.startswith("https://t.me/") or url.startswith("t.me/")):
        await message.answer(
            "❌ Ссылка должна начинаться с https://t.me/ или t.me/"
        )
        return
    await state.update_data(url=url)
    await state.set_state(AdminOfferCreateState.waiting_reward_preview)
    await message.answer(
        "💰 <b>Шаг 4/9</b>\n\n"
        "Введите предварительную награду (монеты, выдаётся сразу при старте):\n"
        "Рекомендуется: 5",
        parse_mode="HTML"
    )


@router.message(AdminOfferCreateState.waiting_reward_preview)
async def admin_offer_reward_preview(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    try:
        val = Decimal(message.text.strip())
        if val < 0:
            raise ValueError
    except Exception:
        await message.answer("❌ Введите корректное число.")
        return
    await state.update_data(reward_preview=val)
    await state.set_state(AdminOfferCreateState.waiting_reward_final)
    await message.answer(
        "💎 <b>Шаг 5/9</b>\n\n"
        "Введите итоговую награду (монеты, выдаётся после проверки подписки):\n"
        "Рекомендуется: 35",
        parse_mode="HTML"
    )


@router.message(AdminOfferCreateState.waiting_reward_final)
async def admin_offer_reward_final(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    try:
        val = Decimal(message.text.strip())
        if val < 0:
            raise ValueError
    except Exception:
        await message.answer("❌ Введите корректное число.")
        return
    await state.update_data(reward_final=val)
    data = await state.get_data()
    reward_preview = Decimal(data.get("reward_preview", 0))
    max_penalty = (reward_preview + val) * Decimal("0.5")
    await state.set_state(AdminOfferCreateState.waiting_penalty_unsubscribe)
    await message.answer(
        "⚠️ <b>Шаг 6/9</b>\n\n"
        "Введите штраф за отписку (дополнительно к возврату всех бонусов).\n"
        f"Максимум: {max_penalty} монет (50% от суммы бонусов).",
        parse_mode="HTML"
    )


@router.message(AdminOfferCreateState.waiting_penalty_unsubscribe)
async def admin_offer_penalty_unsubscribe(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    try:
        penalty = Decimal(message.text.strip())
        if penalty < 0:
            raise ValueError
    except Exception:
        await message.answer("❌ Введите корректное число >= 0.")
        return
    data = await state.get_data()
    reward_preview = Decimal(data.get("reward_preview", 0))
    reward_final = Decimal(data.get("reward_final", 0))
    max_penalty = (reward_preview + reward_final) * Decimal("0.5")
    if penalty > max_penalty:
        await message.answer(
            f"❌ Слишком большой штраф. Максимум: {max_penalty} монет."
        )
        return
    await state.update_data(penalty_unsubscribe=penalty)
    await state.set_state(AdminOfferCreateState.waiting_rentable)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data="offer_rentable_yes"),
            InlineKeyboardButton(text="❌ Нет", callback_data="offer_rentable_no"),
        ]
    ])
    await message.answer(
        "🏠 <b>Шаг 7/9</b>\n\n"
        "Разрешить рекламодателям арендовать этот оффер\n"
        "(размещать рекламу своего канала вместе с этим)?",
        parse_mode="HTML",
        reply_markup=kb
    )


@router.callback_query(AdminOfferCreateState.waiting_rentable, F.data == "offer_rentable_yes")
async def admin_offer_rentable_yes(callback: CallbackQuery, state: FSMContext):
    await state.update_data(is_rentable=True)
    await state.set_state(AdminOfferCreateState.waiting_rent_cost)
    await callback.message.answer(
        f"💵 <b>Шаг 8/9</b>\n\n"
        f"Введите стоимость аренды за 1 день (монеты):\n"
        f"По умолчанию: {OFFER_DEFAULT_RENT_COST_PER_DAY}",
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(AdminOfferCreateState.waiting_rentable, F.data == "offer_rentable_no")
async def admin_offer_rentable_no(callback: CallbackQuery, state: FSMContext):
    await state.update_data(is_rentable=False, rent_cost_per_day=Decimal("0"), max_simultaneous_rentals=0)
    await state.set_state(AdminOfferCreateState.waiting_max_rentals)
    await _finish_offer_creation(callback.message, state, skip_rentals=True)
    await callback.answer()


@router.message(AdminOfferCreateState.waiting_rent_cost)
async def admin_offer_rent_cost(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    try:
        val = Decimal(message.text.strip())
        if val <= 0:
            raise ValueError
    except Exception:
        await message.answer("❌ Введите корректное число.")
        return
    await state.update_data(rent_cost_per_day=val)
    await state.set_state(AdminOfferCreateState.waiting_max_rentals)
    await message.answer(
        "🔢 <b>Шаг 9/9</b>\n\n"
        "Максимальное число одновременных арендаторов?\n"
        "Рекомендуется: 1-5",
        parse_mode="HTML"
    )


@router.message(AdminOfferCreateState.waiting_max_rentals)
async def admin_offer_max_rentals(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    try:
        val = int(message.text.strip())
        if val < 1:
            raise ValueError
    except Exception:
        await message.answer("❌ Введите целое число >= 1.")
        return
    await state.update_data(max_simultaneous_rentals=val)
    await _finish_offer_creation(message, state)


async def _finish_offer_creation(
        message: Message,
        state: FSMContext,
        skip_rentals: bool = False
):
    data = await state.get_data()
    async with async_session() as session:
        await admin_create_offer(
            session,
            title=data["title"],
            description=data["description"],
            channel_url=data["url"],
            reward_preview=data["reward_preview"],
            reward_final=data["reward_final"],
            penalty_unsubscribe=data.get("penalty_unsubscribe", Decimal("0")),
            is_rentable=data.get("is_rentable", False),
            rent_cost_per_day=data.get("rent_cost_per_day", Decimal("0")),
            max_simultaneous_rentals=data.get("max_simultaneous_rentals", 0),
        )

    rentable_text = ""
    if data.get("is_rentable"):
        rentable_text = (
            f"\n🔑 Аренда: {data.get('rent_cost_per_day')} монет/день\n"
            f"Макс. арендаторов: {data.get('max_simultaneous_rentals')}"
        )

    await message.answer(
        f"✅ <b>Оффер создан!</b>\n\n"
        f"📢 {data['title']}\n"
        f"💰 Старт. награда: {data['reward_preview']}\n"
        f"💎 Итог. награда: {data['reward_final']}"
        f"\n⚠️ Штраф за отписку: {data.get('penalty_unsubscribe', Decimal('0'))}"
        f"{rentable_text}\n\n"
        f"Оффер сразу активен и виден пользователям.",
        parse_mode="HTML"
    )
    await state.clear()


@router.callback_query(F.data == "admin_offers_pending")
async def admin_offers_pending(callback: CallbackQuery):
