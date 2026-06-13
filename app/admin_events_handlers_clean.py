"""
Модуль обработки Событий (Events) для админки.
- Название, текст, скидка, дни
- Гибкий выбор применения (VIP, Монеты, Лутбоксы, Кейсы)
- Опциональная картинка
- Предпросмотр + подтверждение
- Автоматическая рассылка
"""

import asyncio
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
)
from sqlalchemy import select

from app.db import async_session
from app.models import Event, User
from app.services import get_user, get_display_name

router = Router()


class EventCreationState(StatesGroup):
    waiting_name = State()
    waiting_description = State()
    waiting_discount = State()
    waiting_duration = State()
    waiting_applies = State()
    waiting_image = State()      # опциональная картинка
    confirm = State()


def event_applies_keyboard(selected: dict) -> InlineKeyboardMarkup:
    def icon(key):
        return "✅" if selected.get(key, False) else "❌"

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{icon('vip')} Покупка VIP", callback_data="event_toggle:vip")],
        [InlineKeyboardButton(text=f"{icon('coins')} Покупка монет", callback_data="event_toggle:coins")],
        [InlineKeyboardButton(text=f"{icon('lootbox')} Покупка лутбоксов", callback_data="event_toggle:lootbox")],
        [InlineKeyboardButton(text=f"{icon('cases')} Покупка кейсов", callback_data="event_toggle:cases")],
        [
            InlineKeyboardButton(text="✅ Готово", callback_data="event_applies_done"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_events_menu")
        ]
    ])


def event_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Создать событие", callback_data="event_confirm_yes"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_events_menu")
        ]
    ])


@router.callback_query(F.data == "admin_events_menu")
async def admin_events_menu(callback: CallbackQuery):
    if not await _check_admin(callback.from_user.id):
        await callback.answer()
        return

    async with async_session() as session:
        active = (await session.execute(
            select(Event).where(Event.is_active == True, Event.end_date > datetime.utcnow())
            .order_by(Event.start_date.desc())
        )).scalars().all()

    text = "🎉 <b>Управление событиями</b>\n\n"
    if active:
        text += "Активные события:\n"
        for ev in active[:5]:
            text += f"• {ev.name} — {ev.discount_percent}% до {ev.end_date.strftime('%d.%m')}\n"
    else:
        text += "Нет активных событий.\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать новое событие", callback_data="event_create_start")],
        [InlineKeyboardButton(text="📋 Все события", callback_data="event_list_all")],
        [InlineKeyboardButton(text="🛍 Глобальные акции (Sale)", callback_data="admin_sales")],
        [InlineKeyboardButton(text="◀️ Назад в админку", callback_data="admin_center")]
    ])

    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


async def _check_admin(tg_id: int) -> bool:
    from app.utils.admin import check_admin
    return await check_admin(tg_id)


@router.callback_query(F.data == "event_create_start")
async def event_create_start(callback: CallbackQuery, state: FSMContext):
    if not await _check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(EventCreationState.waiting_name)
    await callback.message.answer(
        "🎉 <b>Создание события — шаг 1/7</b>\n\n"
        "Введите <b>название события</b> (например: «День России»):",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(EventCreationState.waiting_name)
async def event_name(message: Message, state: FSMContext):
    if not await _check_admin(message.from_user.id):
        return
    await state.update_data(name=message.text.strip()[:255])
    await state.set_state(EventCreationState.waiting_description)
    await message.answer("📝 <b>Шаг 2/7</b>\n\nВведите <b>текст события</b>:")


@router.message(EventCreationState.waiting_description)
async def event_description(message: Message, state: FSMContext):
    if not await _check_admin(message.from_user.id):
        return
    await state.update_data(description=message.text.strip()[:2000])
    await state.set_state(EventCreationState.waiting_discount)
    await message.answer("💰 <b>Шаг 3/7</b>\n\nВведите размер <b>скидки в процентах</b> (1-99):")


@router.message(EventCreationState.waiting_discount)
async def event_discount(message: Message, state: FSMContext):
    if not await _check_admin(message.from_user.id):
        return
    try:
        pct = int(message.text.strip())
        if not (1 <= pct <= 99):
            raise ValueError
    except:
        await message.answer("❌ Введите число от 1 до 99.")
        return
    await state.update_data(discount_percent=pct)
    await state.set_state(EventCreationState.waiting_duration)
    await message.answer("📅 <b>Шаг 4/7</b>\n\nСколько <b>дней</b> будет длиться событие?")


@router.message(EventCreationState.waiting_duration)
async def event_duration(message: Message, state: FSMContext):
    if not await _check_admin(message.from_user.id):
        return
    try:
        days = int(message.text.strip())
        if days < 1:
            raise ValueError
    except:
        await message.answer("❌ Введите число дней ≥ 1.")
        return
    await state.update_data(duration_days=days)
    await state.update_data(applies={"vip": False, "coins": False, "lootbox": False, "cases": False})
    await state.set_state(EventCreationState.waiting_applies)
    await message.answer(
        "✅ <b>Шаг 5/7 — На что применяется скидка?</b>",
        reply_markup=event_applies_keyboard({"vip": False, "coins": False, "lootbox": False, "cases": False})
    )


@router.callback_query(EventCreationState.waiting_applies, F.data.startswith("event_toggle:"))
async def event_toggle_applies(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(":")[1]
    data = await state.get_data()
    applies = data.get("applies", {})
    applies[key] = not applies.get(key, False)
    await state.update_data(applies=applies)
    await callback.message.edit_reply_markup(reply_markup=event_applies_keyboard(applies))
    await callback.answer()


@router.callback_query(EventCreationState.waiting_applies, F.data == "event_applies_done")
async def event_applies_done(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    applies = data.get("applies", {})
    if not any(applies.values()):
        await callback.answer("❌ Выберите хотя бы одно применение!", show_alert=True)
        return

    await state.set_state(EventCreationState.waiting_image)
    await callback.message.answer(
        "🖼 <b>Шаг 6/7 — Картинка (опционально)</b>\n\n"
        "Отправьте URL картинки или напишите 'пропустить':",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(EventCreationState.waiting_image)
async def event_image(message: Message, state: FSMContext):
    if not await _check_admin(message.from_user.id):
        return
    
    if message.photo:
        # Берём самое большое фото
        file_id = message.photo[-1].file_id
        await state.update_data(image_file_id=file_id)
    else:
        text = (message.text or "").strip().lower()
        if text in ["пропустить", "нет", "skip", "no"]:
            await state.update_data(image_file_id=None)
        else:
            await message.answer("🖼 Пожалуйста, отправьте фото или напишите 'пропустить'")
            return
    
    await state.set_state(EventCreationState.confirm)
    
    data = await state.get_data()
    applies = data.get("applies", {})
    
    summary = (
        f"🎉 <b>Предпросмотр события</b>\n\n"
        f"📌 Название: <b>{data['name']}</b>\n"
        f"📝 Текст: {data['description']}\n"
        f"💰 Скидка: <b>{data['discount_percent']}%</b>\n"
        f"📅 Длительность: <b>{data['duration_days']} дней</b>\n"
    )
    if data.get("image_file_id"):
        summary += "🖼 Картинка: ✅ прикреплена\n"
    else:
        summary += "🖼 Картинка: ❌ нет\n"
    summary += "\nПрименяется к:\n"
    for k, v in applies.items():
        icon = "✅" if v else "❌"
        label = {"vip": "VIP", "coins": "Монеты", "lootbox": "Лутбоксы", "cases": "Кейсы"}[k]
        summary += f"  {icon} {label}\n"

    await message.answer(summary, parse_mode="HTML", reply_markup=event_confirm_keyboard())


@router.callback_query(EventCreationState.confirm, F.data == "event_confirm_yes")
async def event_confirm_yes(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    applies = data.get("applies", {})

    start = datetime.utcnow()
    end = start + timedelta(days=data["duration_days"])

    async with async_session() as session:
        admin_user = await get_user(session, callback.from_user.id)
        event = Event(
            name=data["name"],
            description=data["description"],
            discount_percent=data["discount_percent"],
            duration_days=data["duration_days"],
            applies_vip=applies.get("vip", False),
            applies_coins=applies.get("coins", False),
            applies_lootbox=applies.get("lootbox", False),
            applies_cases=applies.get("cases", False),
            image_file_id=data.get("image_file_id"),
            start_date=start,
            end_date=end,
            is_active=True,
            created_by=admin_user.id if admin_user else None
        )
        session.add(event)
        await session.commit()
        event_id = event.id

    await state.clear()
    await _broadcast_event_start(callback.bot, event)

    await callback.message.answer(
        f"✅ <b>Событие создано!</b>\n\n"
        f"ID: #{event_id}\n"
        f"Название: {data['name']}\n"
        f"Действует до: {end.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"📢 Рассылка отправлена всем пользователям.",
        parse_mode="HTML"
    )
    await callback.answer("Событие создано!", show_alert=True)


async def _broadcast_event_start(bot, event: Event):
    """Рассылка события (с поддержкой фото по file_id)"""
    async with async_session() as session:
        users = (await session.execute(
            select(User.telegram_id).where(User.status == "active")
        )).scalars().all()

    text = (
        f"🎉 <b>Новое событие!</b>\n\n"
        f"<b>{event.name}</b>\n"
        f"{event.description}\n\n"
        f"💰 Скидка <b>{event.discount_percent}%</b> на:\n"
    )
    applies = []
    if event.applies_vip: applies.append("VIP")
    if event.applies_coins: applies.append("покупку монет")
    if event.applies_lootbox: applies.append("лутбоксы")
    if event.applies_cases: applies.append("кейсы")
    text += " • ".join(applies) + "\n\n"
    text += f"⏳ До {event.end_date.strftime('%d.%m %H:%M')}"

    sent = 0
    for tg_id in users:
        try:
            if event.image_file_id:
                await bot.send_photo(tg_id, photo=event.image_file_id, caption=text, parse_mode="HTML")
            else:
                await bot.send_message(tg_id, text, parse_mode="HTML")
            sent += 1
            if sent % 20 == 0:
                await asyncio.sleep(0.8)
        except:
            pass

    print(f"[EVENT] Broadcast sent to {sent} users")


@router.callback_query(F.data == "event_list_all")
async def event_list_all(callback: CallbackQuery):
    if not await _check_admin(callback.from_user.id):
        await callback.answer()
        return

    async with async_session() as session:
        events = (await session.execute(
            select(Event).order_by(Event.created_at.desc()).limit(20)
        )).scalars().all()

    if not events:
        await callback.message.answer("Событий пока нет.")
        await callback.answer()
        return

    text = "📋 <b>Последние 20 событий</b>\n\n"
    for ev in events:
        status = "✅" if ev.is_active and ev.end_date > datetime.utcnow() else "❌"
        text += f"{status} <b>{ev.name}</b> — {ev.discount_percent}%\n"
        text += f"   {ev.start_date.strftime('%d.%m')} — {ev.end_date.strftime('%d.%m')}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_events_menu")]
    ])
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()