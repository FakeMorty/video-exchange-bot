import re

with open("app/admin_handlers_clean.py", "r", encoding="utf-8") as f:
    code = f.read()

# Fix imports
code = code.replace("from aiogram import Router, F", "import asyncio\nfrom aiogram import Router, F")
code = code.replace("from html import escape", "") # Avoid duplicates
code = code.replace("import os", "import os\nfrom html import escape")

code = re.sub(r"TrustedUploader\s*\)", "TrustedUploader, Event, ActiveSale, OfferParticipation)", code)
code = re.sub(r"get_recent_feedback,\s*\)", "get_recent_feedback, get_active_sale, get_active_events)", code)

# Inject State
event_state = """
class EventCreationState(StatesGroup):
    waiting_name = State()
    waiting_description = State()
    waiting_discount = State()
    waiting_duration = State()
    waiting_applies = State()
    waiting_image = State()
    confirm = State()
"""
code = code.replace("class TrustedUploaderState(StatesGroup):", event_state + "\n\nclass TrustedUploaderState(StatesGroup):")

# Event handlers
events_handlers = """
# =========================
# EVENTS
# =========================

def event_applies_keyboard(selected: dict) -> InlineKeyboardMarkup:
    def icon(key): return "✅" if selected.get(key, False) else "❌"
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

@router.callback_query(F.data == "admin_events_menu")
async def admin_events_menu(callback: CallbackQuery):
    try:
        if not await check_admin(callback.from_user.id):
            await callback.answer("Нет прав!", show_alert=True)
            return
        async with async_session() as session:
            active = (await session.execute(
                select(Event).where(Event.is_active == True, Event.end_date > datetime.utcnow())
                .order_by(Event.start_date.desc())
            )).scalars().all()

        text = "🎉 <b>События</b>\\n\\n"
        if active:
            for ev in active[:5]:
                text += f"• {escape(ev.name)} — {ev.discount_percent}% до {ev.end_date.strftime('%d.%m')}\\n"
        else: text += "Нет активных событий.\\n"

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать", callback_data="event_create_start")],
            [InlineKeyboardButton(text="📋 Все события", callback_data="event_list_all")],
            [InlineKeyboardButton(text="🛍 Глобальные акции", callback_data="admin_sales")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_center")]
        ])
        await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        print(f"Events menu error: {e}")
        await callback.answer("Ошибка в меню событий", show_alert=True)
    finally:
        await callback.answer()

@router.callback_query(F.data == "event_create_start")
async def event_create_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    await state.set_state(EventCreationState.waiting_name)
    await callback.message.answer("🎉 Шаг 1: Название:")
    await callback.answer()

@router.message(EventCreationState.waiting_name)
async def event_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip()[:255])
    await state.set_state(EventCreationState.waiting_description)
    await message.answer("Шаг 2: Описание:")

@router.message(EventCreationState.waiting_description)
async def event_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip()[:2000])
    await state.set_state(EventCreationState.waiting_discount)
    await message.answer("Шаг 3: Скидка (1-99%):")

@router.message(EventCreationState.waiting_discount)
async def event_discount(message: Message, state: FSMContext):
    if not message.text.isdigit(): return
    await state.update_data(discount_percent=int(message.text))
    await state.set_state(EventCreationState.waiting_duration)
    await message.answer("Шаг 4: Длительность (дней):")

@router.message(EventCreationState.waiting_duration)
async def event_duration(message: Message, state: FSMContext):
    if not message.text.isdigit(): return
    await state.update_data(duration_days=int(message.text), applies={"vip": False, "coins": False, "lootbox": False})
    await state.set_state(EventCreationState.waiting_applies)
    await message.answer("Шаг 5: На что?", reply_markup=event_applies_keyboard({"vip": False, "coins": False, "lootbox": False}))

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
    await state.set_state(EventCreationState.waiting_image)
    await callback.message.answer("Шаг 6: Фото или 'пропустить':")
    await callback.answer()

@router.message(EventCreationState.waiting_image)
async def event_image(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id if message.photo else None
    await state.update_data(image_file_id=file_id)
    data = await state.get_data()
    await state.set_state(EventCreationState.confirm)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Создать", callback_data="event_confirm_yes"), InlineKeyboardButton(text="❌ Отмена", callback_data="admin_events_menu")]])
    await message.answer(f"Создать событие {data['name']}?", reply_markup=kb)

@router.callback_query(EventCreationState.confirm, F.data == "event_confirm_yes")
async def event_confirm_yes(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    applies = data.get("applies", {})
    start = datetime.utcnow()
    end = start + timedelta(days=data["duration_days"])
    async with async_session() as session:
        admin_user = await get_user(session, callback.from_user.id)
        event = Event(
            name=data["name"], description=data["description"], discount_percent=data["discount_percent"],
            duration_days=data["duration_days"], applies_vip=applies.get("vip", False),
            applies_coins=applies.get("coins", False), applies_lootbox=applies.get("lootbox", False),
            image_file_id=data.get("image_file_id"), start_date=start, end_date=end, is_active=True,
            created_by=admin_user.id if admin_user else None
        )
        session.add(event)
        await session.commit()
    await state.clear()
    await callback.message.answer("✅ Готово!")
    await callback.answer()

@router.callback_query(F.data == "event_list_all")
async def event_list_all(callback: CallbackQuery):
    async with async_session() as session:
        events = (await session.execute(select(Event).order_by(Event.created_at.desc()).limit(20))).scalars().all()
    text = "📋 Все события:\\n" + "\\n".join([f"• {escape(ev.name)} ({ev.discount_percent}%)" for ev in events])
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin_events_menu")]])
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()
"""

code += "\n" + events_handlers

with open("app/admin_handlers.py", "w", encoding="utf-8") as f:
    f.write(code)
