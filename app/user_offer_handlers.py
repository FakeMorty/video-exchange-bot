"""Пользовательское создание офферов и просмотр своих заявок."""

from html import escape
from decimal import Decimal, ROUND_CEILING
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice
)
from sqlalchemy import select

from app.db import async_session
from app.models import Offer
from app.services import (
    get_user, change_balance_atomic,
    ensure_payment_pending, get_stars_discount,
    notify_admins, classify_offer_url, normalize_telegram_url,
)
from app.config import STARS_TO_COINS_RATE

router = Router()


def _calc_offer_stars_price(cost: Decimal, discount: float = 0.0) -> int:
    """Конвертация цены размещения из монет в Stars без занижения стоимости."""
    if STARS_TO_COINS_RATE <= 0:
        return 1
    stars = (Decimal(cost) / Decimal(str(STARS_TO_COINS_RATE))).quantize(Decimal("1"), rounding=ROUND_CEILING)
    base = max(1, int(stars))
    if discount > 0:
        discounted = (Decimal(str(base)) * Decimal(str(1 - discount))).quantize(Decimal("1"), rounding=ROUND_CEILING)
        return max(1, int(discounted))
    return base


class UserOfferState(StatesGroup):
    waiting_title = State()
    waiting_description = State()
    waiting_url = State()
    waiting_reward_preview = State()
    waiting_reward_final = State()
    waiting_penalty = State()
    waiting_duration = State()
    waiting_payment_method = State()


# =========================
# КНОПКА В МЕНЮ ОФФЕРОВ
# =========================
def user_offers_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Офферы (участие)", callback_data="offers_participation")],
        [InlineKeyboardButton(text="➕ Создать свой оффер", callback_data="user_create_offer")],
        [InlineKeyboardButton(text="📋 Мои офферы", callback_data="user_my_offers")],
        [InlineKeyboardButton(text="📣 Арендовать рекламный слот", callback_data="offers_rent_list")],
        [InlineKeyboardButton(text="🧾 Мои аренды", callback_data="my_rentals")],
    ])


# =========================
# СОЗДАНИЕ ПОЛЬЗОВАТЕЛЬСКОГО ОФФЕРА
# =========================
@router.callback_query(F.data == "user_create_offer")
async def user_create_offer_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(UserOfferState.waiting_title)
    
    text = (
        "➕ <b>Создание своего оффера</b>\n\n"
        "Можно рекламировать каналы, группы, чаты и ботов Telegram.\n\n"
        "⚠️ <b>Важно:</b>\n"
        "• публичные каналы/группы/чаты с username бот может проверять автоматически\n"
        "• для ботов, приватных инвайтов и некоторых ссылок авто-проверка недоступна, поэтому подтверждение будет ручным по кнопке пользователя\n"
        "• мутные, серые и запрещённые проекты в модерацию не пройдут\n\n"
        "Шаг 1/8: Введите название проекта/оффера:"
    )
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.message(UserOfferState.waiting_title)
async def user_offer_title(message: Message, state: FSMContext):
    title = (message.text or "").strip()
    if not title or len(title) > 100:
        await message.answer("❌ Введите название длиной от 1 до 100 символов.")
        return
    await state.update_data(title=title)
    await state.set_state(UserOfferState.waiting_description)
    await message.answer("Шаг 2/8: Введите описание оффера (что получат подписчики):")


@router.message(UserOfferState.waiting_description)
async def user_offer_description(message: Message, state: FSMContext):
    description = (message.text or "").strip()
    if not description or len(description) > 1500:
        await message.answer("❌ Введите описание длиной от 1 до 1500 символов.")
        return
    await state.update_data(description=description)
    await state.set_state(UserOfferState.waiting_url)
    await message.answer("Шаг 3/8: Введите ссылку на Telegram-проект (канал / группа / чат / бот / invite link):")


@router.message(UserOfferState.waiting_url)
async def user_offer_url(message: Message, state: FSMContext):
    url = normalize_telegram_url(message.text or "")
    if not url:
        await message.answer("❌ Нужна корректная ссылка t.me/... или @username Telegram-проекта.")
        return
    meta = classify_offer_url(url)
    await state.update_data(url=url, target_label=meta["label"], auto_verify=meta["auto_verify"])
    await state.set_state(UserOfferState.waiting_reward_preview)
    
    await message.answer(
        "Шаг 4/8: Введите <b>предварительную награду</b> (монеты, выдаётся сразу):\n\n"
        "Рекомендуется: 10, 20, 30",
        parse_mode="HTML"
    )


@router.message(UserOfferState.waiting_reward_preview)
async def user_offer_preview(message: Message, state: FSMContext):
    try:
        val = Decimal(message.text.strip())
        if not val.is_finite() or val < 10:
            raise ValueError
    except Exception:
        await message.answer("❌ Введите число ≥ 10")
        return
    await state.update_data(reward_preview=val)
    await state.set_state(UserOfferState.waiting_reward_final)
    await message.answer(
        "Шаг 5/8: Введите <b>итоговую награду</b> (после проверки подписки):\n\n"
        "Рекомендуется: 70, 100, 160",
        parse_mode="HTML"
    )


@router.message(UserOfferState.waiting_reward_final)
async def user_offer_final(message: Message, state: FSMContext):
    try:
        val = Decimal(message.text.strip())
        if not val.is_finite() or val < 50:
            raise ValueError
    except Exception:
        await message.answer("❌ Введите число ≥ 50")
        return
    await state.update_data(reward_final=val)
    await state.set_state(UserOfferState.waiting_penalty)
    await message.answer(
        "💰 <b>Шаг 6/8: Штраф за отписку</b>\n\n"
        "Введите сумму штрафа (монеты), которая будет списана дополнительно, "
        "если пользователь прекратит участие в оффере там, где это можно проверить автоматически.\n\n"
        "⚠️ Штраф <b>не может превышать итоговую награду</b> — "
        "иначе нарушение становится дороже, чем возможный выигрыш, и это несправедливо.",
        parse_mode="HTML"
    )


@router.message(UserOfferState.waiting_penalty)
async def user_offer_penalty(message: Message, state: FSMContext):
    try:
        val = Decimal(message.text.strip())
        if not val.is_finite() or val < 0:
            raise ValueError
    except Exception:
        await message.answer("❌ Введите неотрицательное число.")
        return
    # Штраф за отписку не должен превышать итоговую награду.
    data = await state.get_data()
    reward_final = data.get("reward_final")
    if reward_final is not None and val > Decimal(reward_final):
        await message.answer(
            f"❌ Штраф ({val}) не может быть больше итоговой награды ({reward_final}). "
            "Сумма штрафа должна быть меньше или равна награде."
        )
        return
    await state.update_data(penalty_unsubscribe=val)
    await state.set_state(UserOfferState.waiting_duration)
    await message.answer(
        "📅 <b>Шаг 7/8: Срок активности</b>\n\n"
        "На сколько дней сделать оффер активным?\n\n"
        "Рекомендуется: 30, 60, 90"
    )


@router.message(UserOfferState.waiting_duration)
async def user_offer_duration(message: Message, state: FSMContext):
    try:
        days = int(message.text.strip())
        if days < 7 or days > 365:
            raise ValueError
    except Exception:
        await message.answer("❌ Введите число от 7 до 365")
        return
    
    await state.update_data(duration_days=days)
    
    # Расчёт стоимости
    data = await state.get_data()
    total_reward = data["reward_preview"] + data["reward_final"]
    cost = max(Decimal("50"), (total_reward * Decimal("0.20") * Decimal(days) / Decimal("30")).quantize(Decimal("1")))
    
    await state.update_data(placement_cost=cost)
    
    text = (
        f"💰 <b>Стоимость размещения:</b> <b>{cost:.0f} монет</b>\n\n"
        f"• Награды: {data['reward_preview']} + {data['reward_final']}\n"
        f"• Штраф: {data['penalty_unsubscribe']}\n"
        f"• Длительность: {days} дней\n"
        f"• Коэффициент: 20%\n\n"
        "Выберите способ оплаты:"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🪙 Монеты ({cost:.0f})", callback_data="user_offer_pay:coins")],
        [InlineKeyboardButton(text="⭐ Stars", callback_data="user_offer_pay:stars")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="offers_participation")],
    ])
    
    await state.set_state(UserOfferState.waiting_payment_method)
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(UserOfferState.waiting_payment_method, F.data.startswith("user_offer_pay:"))
async def user_offer_payment(callback: CallbackQuery, state: FSMContext):
    method = callback.data.split(":")[1]
    data = await state.get_data()
    cost: Decimal = data["placement_cost"]

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return

        if method == "coins":
            if user.balance < cost:
                await callback.message.answer(
                    f"❌ Недостаточно монет. Нужно: {cost:.0f}, у вас: {user.balance:.0f}"
                )
                await callback.answer()
                return

            await change_balance_atomic(
                session,
                user.id,
                -cost,
                "user_offer_placement",
                details=f"Оффер: {data['title']}",
            )

            offer = Offer(
                creator_user_id=user.id,
                title=data["title"],
                description=data["description"],
                channel_url=data["url"],
                reward_preview=data["reward_preview"],
                reward_final=data["reward_final"],
                penalty_unsubscribe=Decimal(data.get("penalty_unsubscribe", 0)),
                duration_days=data["duration_days"],
                placement_cost=cost,
                status="pending",
                is_active=False,
            )
            session.add(offer)
            await session.commit()

            from app.services import schedule_mod_notification
            await schedule_mod_notification(session, "offer")
            try:
                await notify_admins(
                    callback.bot,
                    f"📣 <b>Новый пользовательский оффер</b>\n"
                    f"Автор: <code>{user.telegram_id}</code>\n"
                    f"Название: <b>{escape(offer.title)}</b>\n"
                    f"Тип цели: {classify_offer_url(offer.channel_url)['label']}\n"
                    f"Статус: отправлен на модерацию\n\n"
                    f"Открыть очередь: /admin",
                )
            except Exception:
                pass

            await callback.message.answer("✅ Оффер создан и отправлен на модерацию!")
            await state.clear()
            await callback.answer()
            return

        if method == "stars":
            offer = Offer(
                creator_user_id=user.id,
                title=data["title"],
                description=data["description"],
                channel_url=data["url"],
                reward_preview=data["reward_preview"],
                reward_final=data["reward_final"],
                penalty_unsubscribe=Decimal(data.get("penalty_unsubscribe", 0)),
                duration_days=data["duration_days"],
                placement_cost=cost,
                status="payment_pending",
                is_active=False,
            )
            session.add(offer)
            await session.flush()

            payload = f"user_offer_{offer.id}"
            discount = await get_stars_discount(session, user.id)
            stars_price = _calc_offer_stars_price(cost, discount)
            await ensure_payment_pending(
                session,
                user_id=user.id,
                payload=payload,
                stars_amount=stars_price,
                coins_amount=cost,
            )
            await session.commit()

            await callback.message.answer_invoice(
                title="Размещение оффера",
                description=f"Оффер «{data['title']}» на {data['duration_days']} дней",
                payload=payload,
                currency="XTR",
                prices=[LabeledPrice(label="Размещение", amount=stars_price)],
            )
            await state.clear()
            await callback.answer()
            return

    await callback.answer("Неизвестный способ оплаты", show_alert=True)


# =========================
# МОИ ОФФЕРЫ
# =========================
@router.callback_query(F.data == "user_my_offers")
async def user_my_offers(callback: CallbackQuery):
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        
        offers = (await session.execute(
            select(Offer).where(Offer.creator_user_id == user.id).order_by(Offer.created_at.desc()).limit(10)
        )).scalars().all()
    
    if not offers:
        await callback.message.answer("У вас пока нет своих офферов.")
        await callback.answer()
        return
    
    text = "📋 <b>Ваши офферы:</b>\n\n"
    status_labels = {
        "payment_pending": "💳 ожидает оплаты",
        "pending": "⏳ на модерации",
        "approved": "✅ одобрен",
        "rejected": "❌ отклонён",
    }
    for offer in offers:
        text += (
            f"<b>#{offer.id} {escape(offer.title)}</b>\n"
            f"Статус: {status_labels.get(offer.status, escape(offer.status))}\n"
            f"Награда: {offer.reward_preview}+{offer.reward_final} монет\n"
        )
        if offer.status == "rejected" and offer.rejection_reason:
            text += f"Причина: {escape(offer.rejection_reason)}\n"
        text += "\n"

    await callback.message.answer(text[:4000], parse_mode="HTML")
    await callback.answer()
