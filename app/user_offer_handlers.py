"""Пользовательское создание офферов и просмотр своих заявок."""

import math
from html import escape
from decimal import Decimal
from app.i18n import t
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
    coins_to_stars_price,
)

router = Router()


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
        [InlineKeyboardButton(text=t('📢 Офферы (участие)'), callback_data="offers_participation")],
        [InlineKeyboardButton(text=t('➕ Создать свой оффер'), callback_data="user_create_offer")],
        [InlineKeyboardButton(text=t('📋 Мои офферы'), callback_data="user_my_offers")],
    ])


# =========================
# СОЗДАНИЕ ПОЛЬЗОВАТЕЛЬСКОГО ОФФЕРА
# =========================
@router.callback_query(F.data == "user_create_offer")
async def user_create_offer_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(UserOfferState.waiting_title)
    
    text = (
        t('➕ <b>Создание своего оффера</b>\n\nМожно рекламировать каналы, группы, чаты и ботов Telegram.\n\n⚠️ <b>Важно:</b>\n• публичные каналы/группы/чаты с username бот может проверять автоматически\n• для ботов, приватных инвайтов и некоторых ссылок авто-проверка недоступна, поэтому подтверждение будет ручным по кнопке пользователя\n• мутные, серые и запрещённые проекты в модерацию не пройдут\n\nШаг 1/8: Введи название проекта/оффера:')
    )
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.message(UserOfferState.waiting_title)
async def user_offer_title(message: Message, state: FSMContext):
    title = (message.text or "").strip()
    if not title or len(title) > 100:
        await message.answer(t('❌ Введи название длиной от 1 до 100 символов.'))
        return
    await state.update_data(title=title)
    await state.set_state(UserOfferState.waiting_description)
    await message.answer(t('Шаг 2/8: Введи описание оффера (что получат подписчики):'))


@router.message(UserOfferState.waiting_description)
async def user_offer_description(message: Message, state: FSMContext):
    description = (message.text or "").strip()
    if not description or len(description) > 1500:
        await message.answer(t('❌ Введи описание длиной от 1 до 1500 символов.'))
        return
    await state.update_data(description=description)
    await state.set_state(UserOfferState.waiting_url)
    await message.answer(t('Шаг 3/8: Введи ссылку на Telegram-проект (канал / группа / чат / бот / invite link):'))


@router.message(UserOfferState.waiting_url)
async def user_offer_url(message: Message, state: FSMContext):
    url = normalize_telegram_url(message.text or "")
    if not url:
        await message.answer(t('❌ Нужна корректная ссылка t.me/... или @username Telegram-проекта.'))
        return
    meta = classify_offer_url(url)
    await state.update_data(url=url, target_label=meta["label"], auto_verify=meta["auto_verify"])
    await state.set_state(UserOfferState.waiting_reward_preview)
    
    await message.answer(
        t('Шаг 4/8: Введи <b>предварительную награду</b> (монеты, выдаётся сразу):\n\nРекомендуется: 10, 20, 30'),
        parse_mode="HTML"
    )


@router.message(UserOfferState.waiting_reward_preview)
async def user_offer_preview(message: Message, state: FSMContext):
    try:
        val = Decimal(message.text.strip())
        if not val.is_finite() or val < 10:
            raise ValueError
    except Exception:
        await message.answer(t('❌ Введи число ≥ 10'))
        return
    await state.update_data(reward_preview=val)
    await state.set_state(UserOfferState.waiting_reward_final)
    await message.answer(
        t('Шаг 5/8: Введи <b>итоговую награду</b> (после проверки подписки):\n\nРекомендуется: 70, 100, 160'),
        parse_mode="HTML"
    )


@router.message(UserOfferState.waiting_reward_final)
async def user_offer_final(message: Message, state: FSMContext):
    try:
        val = Decimal(message.text.strip())
        if not val.is_finite() or val < 50:
            raise ValueError
    except Exception:
        await message.answer(t('❌ Введи число ≥ 50'))
        return
    await state.update_data(reward_final=val)
    await state.set_state(UserOfferState.waiting_penalty)
    await message.answer(
        t('💰 <b>Шаг 6/8: Штраф за отписку</b>\n\nВведи сумму штрафа (монеты), которая будет списана дополнительно, если пользователь прекратит участие в оффере там, где это можно проверить автоматически.\n\n⚠️ Штраф <b>не может превышать итоговую награду</b> — иначе нарушение становится дороже, чем возможный выигрыш, и это несправедливо.'),
        parse_mode="HTML"
    )


@router.message(UserOfferState.waiting_penalty)
async def user_offer_penalty(message: Message, state: FSMContext):
    try:
        val = Decimal(message.text.strip())
        if not val.is_finite() or val < 0:
            raise ValueError
    except Exception:
        await message.answer(t('❌ Введи неотрицательное число.'))
        return
    # Штраф за отписку не должен превышать итоговую награду.
    data = await state.get_data()
    reward_final = data.get("reward_final")
    if reward_final is not None and val > Decimal(reward_final):
        await message.answer(
            t('❌ Штраф ({val}) не может быть больше итоговой награды ({reward_final}). Сумма штрафа должна быть меньше или равна награде.', val=val, reward_final=reward_final)
        )
        return
    await state.update_data(penalty_unsubscribe=val)
    await state.set_state(UserOfferState.waiting_duration)
    await message.answer(
        t('📅 <b>Шаг 7/8: Срок активности</b>\n\nНа сколько дней сделать оффер активным?\n\nРекомендуется: 30, 60, 90')
    )


@router.message(UserOfferState.waiting_duration)
async def user_offer_duration(message: Message, state: FSMContext):
    try:
        days = int(message.text.strip())
        if days < 7 or days > 365:
            raise ValueError
    except Exception:
        await message.answer(t('❌ Введи число от 7 до 365'))
        return
    
    await state.update_data(duration_days=days)
    
    # Расчёт стоимости
    data = await state.get_data()
    total_reward = data["reward_preview"] + data["reward_final"]
    cost = max(Decimal("50"), (total_reward * Decimal("0.20") * Decimal(days) / Decimal("30")).quantize(Decimal("1")))
    
    await state.update_data(placement_cost=cost)
    
    text = (
        t('💰 <b>Стоимость размещения:</b> <b>{cost:.0f} монет</b>\n\n• Награды: {arg1} + {arg2}\n• Штраф: {arg3}\n• Длительность: {days} дней\n• Коэффициент: 20%\n\nВыбери способ оплаты:', cost=cost, arg1=data['reward_preview'], arg2=data['reward_final'], arg3=data['penalty_unsubscribe'], days=days)
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t('🪙 Монеты ({cost:.0f})', cost=cost), callback_data="user_offer_pay:coins")],
        [InlineKeyboardButton(text="⭐ Stars", callback_data="user_offer_pay:stars")],
        [InlineKeyboardButton(text=t('❌ Отмена'), callback_data="offers_participation")],
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
                    t('❌ Недостаточно монет. Нужно: {cost:.0f}, у тебя: {balance:.0f}', cost=cost, balance=user.balance)
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
                    t('📣 <b>Новый пользовательский оффер</b>\nАвтор: <code>{telegram_id}</code>\nНазвание: <b>{arg1}</b>\nТип цели: {arg2}\nСтатус: отправлен на модерацию\n\nОткрыть очередь: /admin', telegram_id=user.telegram_id, arg1=escape(offer.title), arg2=classify_offer_url(offer.channel_url)['label']),
                )
            except Exception:
                pass

            await callback.message.answer(t('✅ Оффер создан и отправлен на модерацию!'))
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
            stars_price = await coins_to_stars_price(session, cost)
            if discount > 0:
                stars_price = max(1, math.ceil(stars_price * (1 - discount)))
            await ensure_payment_pending(
                session,
                user_id=user.id,
                payload=payload,
                stars_amount=stars_price,
                coins_amount=cost,
            )
            await session.commit()

            await callback.message.answer_invoice(
                title=t('Размещение оффера'),
                description=t('Оффер «{arg0}» на {arg1} дней', arg0=data['title'], arg1=data['duration_days']),
                payload=payload,
                currency="XTR",
                prices=[LabeledPrice(label=t('Размещение'), amount=stars_price)],
            )
            await state.clear()
            await callback.answer()
            return

    await callback.answer(t('Неизвестный способ оплаты'), show_alert=True)


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
        await callback.message.answer(t('У тебя пока нет своих офферов.'))
        await callback.answer()
        return
    
    text = t("📋 <b>Твои офферы:</b>\n\n")
    status_labels = {
        "payment_pending": t("💳 ожидает оплаты"),
        "pending": t("⏳ на модерации"),
        "approved": t("✅ одобрен"),
        "rejected": t("❌ отклонён"),
    }
    for offer in offers:
        text += (
            f"<b>#{offer.id} {escape(offer.title)}</b>\n"
            + t("Статус: {status}\n", status=status_labels.get(offer.status, escape(offer.status)))
            + t("Награда: {preview}+{final} монет\n", preview=offer.reward_preview, final=offer.reward_final)
        )
        if offer.status == "rejected" and offer.rejection_reason:
            text += t("Причина: {reason}\n", reason=escape(offer.rejection_reason))
        text += "\n"

    await callback.message.answer(text[:4000], parse_mode="HTML")
    await callback.answer()
