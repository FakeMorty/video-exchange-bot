import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
import os
from html import escape

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
)
from sqlalchemy import select, func, desc, text


from app.config import ADMINS, OFFER_DEFAULT_RENT_COST_PER_DAY, ENABLE_ADMIN_BROADCAST
from app.db import async_session
from app.models import (
    Base,
    User, Video, Offer, BalanceLog, GameHistory,
    TrustedUploader, Event, ActiveSale, OfferParticipation
)
from app.services import (
    get_user, get_user_by_id, get_user_by_username,
    get_user_dossier, update_user_balance, set_user_ban_status,
    count_pending_videos, count_approved_videos, count_rejected_videos,
    get_next_pending_video, approve_video, reject_video,
    get_admin_extended_stats, get_display_name,
    get_user_by_display_name, admin_create_offer,
    expire_old_rentals, log_user_action,
    get_recent_feedback, get_active_sale
)
from app.keyboards import (
    admin_main_keyboard, moderation_keyboard,
    rejection_reason_keyboard, admin_after_action_keyboard,
    admin_db_keyboard,
)
from app.utils.admin import check_admin, is_super_admin, _safe_edit

router = Router()


# =========================
# STATES
# =========================
class AdminUserState(StatesGroup):
    waiting_user_id = State()
    waiting_coins_amount = State()
    waiting_message_text = State()
    waiting_dossier_id = State()


class AdminManageState(StatesGroup):
    waiting_new_admin = State()
    waiting_remove_admin = State()


class AdminBroadcastState(StatesGroup):
    waiting_text = State()


class AdminNicknameState(StatesGroup):
    waiting_user_id = State()
    waiting_new_nick = State()


class AdminOfferCreateState(StatesGroup):
    waiting_title = State()
    waiting_description = State()
    waiting_url = State()
    waiting_reward_preview = State()
    waiting_reward_final = State()
    waiting_penalty_unsubscribe = State()
    waiting_rentable = State()
    waiting_rent_cost = State()
    waiting_max_rentals = State()


class TrustedUploaderState(StatesGroup):
    waiting_add = State()


class SaleState(StatesGroup):
    waiting_percent = State()
    waiting_scope = State()
    waiting_duration = State()
    waiting_text = State()


class EventCreationState(StatesGroup):
    waiting_name = State()
    waiting_description = State()
    waiting_discount = State()
    waiting_duration = State()
    waiting_applies = State()
    waiting_image = State()      # опциональная картинка
    confirm = State()


# =========================
# ADMIN PANEL
# =========================
@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not await check_admin(message.from_user.id):
        return
    sa = is_super_admin(message.from_user.id)
    await message.answer(
        "⚙️ <b>Панель администратора</b>\n\nВыберите нужный раздел:",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard(is_super=sa)
    )


@router.callback_query(F.data == "admin_center")
async def admin_center(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    sa = is_super_admin(callback.from_user.id)
    await _safe_edit(
        callback,
        "⚙️ <b>Панель администратора</b>\n\nВыберите нужный раздел:",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard(is_super=sa)
    )
    await callback.answer()


@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    await admin_center(callback)


@router.callback_query(F.data == "admin_feedback_menu")
async def admin_feedback_menu(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    async with async_session() as session:
        feedback_items = await get_recent_feedback(session, limit=15)

    if not feedback_items:
        await callback.message.answer(
            "💬 Обращений пока нет.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")]
            ]),
        )
        await callback.answer()
        return

    kind_name = {"bug": "🐞 Баг", "suggestion": "💡 Идея", "praise": "❤️ Благодарность"}
    text_out = "💬 <b>Последние обращения</b>\n\n"
    for item in feedback_items:
        preview = (item.text or "").strip().replace("\n", " ")[:140]
        text_out += f"#{item.id} {kind_name.get(item.kind, item.kind)}\nuser_id={item.user_id} | {item.created_at.strftime('%d.%m %H:%M')}\n{preview}\n\n"

    await callback.message.answer(text_out, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_feedback_menu")],
        [InlineKeyboardButton(text="◀ К панели", callback_data="admin_center")],
    ]))
    await callback.answer()


@router.callback_query(F.data == "admin_db_menu")
async def admin_db_menu(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer()
        return
    table_labels = {"users": "Пользователи", "videos": "Контент", "offers": "Офферы", "events": "События", "balance_logs": "Лог баланса"}
    all_tables = sorted(Base.metadata.tables.keys())
    tables = [(t, table_labels.get(t, t)) for t in all_tables]
    await _safe_edit(callback, "🗄 <b>База данных</b>", parse_mode="HTML", reply_markup=admin_db_keyboard(tables))
    await callback.answer()


@router.callback_query(F.data.startswith("db_open:"))
async def db_open(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id): return
    parts = callback.data.split(":")
    table_name = parts[1]
    offset = int(parts[2]) if len(parts) > 2 else 0
    page_size = 8

    async with async_session() as session:
        try:
            total = (await session.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))).scalar_one()
            rows = (await session.execute(text(f'SELECT * FROM "{table_name}" ORDER BY 1 DESC LIMIT {page_size} OFFSET {offset}'))).mappings().all()
        except Exception as e:
            await callback.answer(f"Ошибка: {e}", show_alert=True)
            return

    body = ""
    for r in rows:
        body += f"<b>#{r.get('id','?')}</b> | {escape(str(dict(r))[:120])}\n\n"
    
    text_out = f"🗄 <b>{escape(table_name)}</b>\nВсего: {total}\n\n{body or 'Нет строк.'}"
    
    nav = []
    if offset > 0: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"db_open:{table_name}:{max(0, offset-page_size)}"))
    if offset + page_size < total: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"db_open:{table_name}:{offset+page_size}"))
    
    kb = InlineKeyboardMarkup(inline_keyboard=[nav, [InlineKeyboardButton(text="📋 Список", callback_data="admin_db_menu")]])
    await _safe_edit(callback, text_out, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# =========================
# MODERATION
# =========================
@router.callback_query(F.data == "admin_queue_info")
async def cb_queue(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    async with async_session() as session:
        p, a, r = await count_pending_videos(session), await count_approved_videos(session), await count_rejected_videos(session)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶ Модерировать", callback_data="admin_get_pending")],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")],
    ])
    await _safe_edit(callback, f"📊 <b>Очередь</b>\n\n⏳ Ожидает: {p}\n✅ Одобрено: {a}\n❌ Отклонено: {r}", parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_get_pending")
async def admin_get_pending(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    async with async_session() as session:
        video = await get_next_pending_video(session)
        if not video:
            await _safe_edit(callback, "✅ Очередь пуста!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")]]))
            await callback.answer()
            return
        uploader = await get_user_by_id(session, video.uploader_user_id)
        name = get_display_name(uploader) if uploader else "???"
        caption = f"📹 #{video.id} | {video.content_type}\n👤 {name}\n📅 {video.created_at.strftime('%d.%m %H:%M')}"
        try:
            if video.content_type == "photo":
                await callback.message.answer_photo(video.telegram_file_id, caption=caption, reply_markup=moderation_keyboard(video.id))
            else:
                await callback.message.answer_video(video.telegram_file_id, caption=caption, reply_markup=moderation_keyboard(video.id))
        except:
            await callback.message.answer(f"⚠️ Ошибка медиа #{video.id}\n{caption}", reply_markup=moderation_keyboard(video.id))
    await callback.answer()


@router.callback_query(F.data.startswith("mod_approve:"))
async def mod_approve(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    video_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        video = await approve_video(session, video_id)
        if video:
            uploader = await get_user_by_id(session, video.uploader_user_id)
            if uploader:
                try: await callback.bot.send_message(uploader.telegram_id, f"✅ Публикация #{video_id} одобрена!")
                except: pass
    await _safe_edit(callback, f"✅ #{video_id} ОДОБРЕНО", reply_markup=admin_after_action_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("mod_reject:"))
async def mod_reject(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    video_id = int(callback.data.split(":")[1])
    await _safe_edit(callback, f"Причина отклонения #{video_id}:", reply_markup=rejection_reason_keyboard(video_id))
    await callback.answer()


@router.callback_query(F.data.startswith("reject_reason:"))
async def reject_reason(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    parts = callback.data.split(":")
    video_id, reason_key = int(parts[1]), parts[2]
    reasons = {"duplicate": "Дубликат", "off_topic": "Не по теме", "forbidden": "Запрещёнка", "other": "Другое"}
    reason_text = reasons.get(reason_key, reason_key)
    async with async_session() as session:
        video = await reject_video(session, video_id, reason_text)
        if video:
            uploader = await get_user_by_id(session, video.uploader_user_id)
            if uploader:
                try: await callback.bot.send_message(uploader.telegram_id, f"❌ Публикация #{video_id} отклонена: {reason_text}")
                except: pass
    await _safe_edit(callback, f"❌ #{video_id} ОТКЛОНЕНО ({reason_text})", reply_markup=admin_after_action_keyboard())
    await callback.answer()


# =========================
# EVENTS
# =========================
def event_applies_keyboard(selected: dict) -> InlineKeyboardMarkup:
    def icon(k): return "✅" if selected.get(k) else "❌"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{icon('vip')} VIP", callback_data="event_toggle:vip")],
        [InlineKeyboardButton(text=f"{icon('coins')} Монеты", callback_data="event_toggle:coins")],
        [InlineKeyboardButton(text=f"{icon('lootbox')} Лутбоксы", callback_data="event_toggle:lootbox")],
        [InlineKeyboardButton(text="✅ Готово", callback_data="event_applies_done"), InlineKeyboardButton(text="❌ Отмена", callback_data="admin_events_menu")]
    ])


@router.callback_query(F.data == "admin_events_menu")
async def admin_events_menu(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    try:
        async with async_session() as session:
            active = (await session.execute(select(Event).where(Event.is_active == True, Event.end_date > datetime.utcnow()).order_by(Event.start_date.desc()))).scalars().all()
        text = "🎉 <b>События</b>\n\n" + ("\n".join([f"• {escape(ev.name)} ({ev.discount_percent}%)" for ev in active[:5]]) if active else "Нет активных событий.")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать", callback_data="event_create_start")],
            [InlineKeyboardButton(text="📋 Все", callback_data="event_list_all")],
            [InlineKeyboardButton(text="🛍 Акции (Sale)", callback_data="admin_sales")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_center")]
        ])
        await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)
    finally:
        await callback.answer()


@router.callback_query(F.data == "event_create_start")
async def event_create_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    await state.set_state(EventCreationState.waiting_name)
    await callback.message.answer("🎉 Шаг 1: Введите название:")
    await callback.answer()


@router.message(EventCreationState.waiting_name)
async def event_name(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    await state.update_data(name=message.text.strip()[:255])
    await state.set_state(EventCreationState.waiting_description)
    await message.answer("Шаг 2: Описание:")


@router.message(EventCreationState.waiting_description)
async def event_description(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    await state.update_data(description=message.text.strip()[:2000])
    await state.set_state(EventCreationState.waiting_discount)
    await message.answer("Шаг 3: Скидка (1-99%):")


@router.message(EventCreationState.waiting_discount)
async def event_discount(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    if not message.text.isdigit(): return
    await state.update_data(discount_percent=int(message.text))
    await state.set_state(EventCreationState.waiting_duration)
    await message.answer("Шаг 4: Длительность (дней):")


@router.message(EventCreationState.waiting_duration)
async def event_duration(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
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
    if not await check_admin(message.from_user.id): return
    file_id = message.photo[-1].file_id if message.photo else None
    await state.update_data(image_file_id=file_id)
    data = await state.get_data()
    await state.set_state(EventCreationState.confirm)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Создать", callback_data="event_confirm_yes"), InlineKeyboardButton(text="❌ Отмена", callback_data="admin_events_menu")]])
    await message.answer(f"Создать событие {escape(data['name'])}?", reply_markup=kb)


@router.callback_query(EventCreationState.confirm, F.data == "event_confirm_yes")
async def event_confirm_yes(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    data = await state.get_data()
    applies = data.get("applies", {})
    start = datetime.utcnow()
    end = start + timedelta(days=data["duration_days"])
    async with async_session() as session:
        admin = await get_user(session, callback.from_user.id)
        ev = Event(name=data["name"], description=data["description"], discount_percent=data["discount_percent"], duration_days=data["duration_days"], applies_vip=applies.get("vip", False), applies_coins=applies.get("coins", False), applies_lootbox=applies.get("lootbox", False), image_file_id=data.get("image_file_id"), start_date=start, end_date=end, is_active=True, created_by=admin.id if admin else None)
        session.add(ev)
        await session.commit()
    await state.clear()
    await callback.message.answer("✅ Событие создано!")
    await callback.answer()


@router.callback_query(F.data == "event_list_all")
async def event_list_all(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    async with async_session() as session:
        events = (await session.execute(select(Event).order_by(Event.created_at.desc()).limit(20))).scalars().all()
    text = "📋 Последние 20 событий:\n" + "\n".join([f"• {escape(ev.name)} ({ev.discount_percent}%)" for ev in events])
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin_events_menu")]])
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# =========================
# SALES
# =========================
@router.callback_query(F.data == "admin_sales")
async def admin_sales_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    async with async_session() as session:
        sale = await get_active_sale(session)
    text = "🛍 <b>Глобальные акции</b>\n\n" + (f"🟢 Активна: {sale.discount_percent}%" if sale else "🔴 Нет активных акций.")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🛑 Остановить", callback_data="admin_sale_stop")] if sale else [InlineKeyboardButton(text="➕ Создать", callback_data="admin_sale_create")], [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")]])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_sale_stop")
async def admin_sale_stop(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    async with async_session() as session:
        sale = await get_active_sale(session)
        if sale:
            sale.end_date = datetime.utcnow()
            await session.commit()
    await admin_sales_start(callback, None)


@router.callback_query(F.data == "admin_sale_create")
async def admin_sale_create(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    await state.set_state(SaleState.waiting_percent)
    await _safe_edit(callback, "Введите % (1-99):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="admin_center")]]))


@router.message(SaleState.waiting_percent)
async def admin_sale_percent(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    if not message.text.isdigit(): return
    await state.update_data(discount_percent=int(message.text))
    await state.set_state(SaleState.waiting_scope)
    await message.answer("Сфера применения:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Все", callback_data="sale_scope:all")]]))


@router.callback_query(SaleState.waiting_scope, F.data.startswith("sale_scope:"))
async def admin_sale_scope(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    await state.update_data(applies_to=callback.data.split(":")[1])
    await state.set_state(SaleState.waiting_duration)
    await _safe_edit(callback, "Длительность (часов):")
    await callback.answer()


@router.message(SaleState.waiting_duration)
async def admin_sale_duration(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    if not message.text.isdigit(): return
    await state.update_data(duration_hours=int(message.text))
    await state.set_state(SaleState.waiting_text)
    await message.answer("Текст рассылки:")


@router.message(SaleState.waiting_text)
async def admin_sale_finish(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    data = await state.get_data()
    end_date = datetime.utcnow() + timedelta(hours=data["duration_hours"])
    async with async_session() as session:
        session.add(ActiveSale(discount_percent=data["discount_percent"], applies_to=data["applies_to"], end_date=end_date, announcement=message.text))
        await session.commit()
    await state.clear()
    await message.answer("✅ Акция запущена!")


# =========================
# BROADCAST
# =========================
@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    await state.set_state(AdminBroadcastState.waiting_text)
    await callback.message.answer("📢 Введите текст рассылки (HTML):")
    await callback.answer()


@router.message(AdminBroadcastState.waiting_text)
async def process_broadcast(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    text_val = message.text
    await state.clear()
    async with async_session() as session:
        users = (await session.execute(select(User.telegram_id).where(User.status == "active"))).scalars().all()
    sent = 0
    for tid in users:
        try:
            await message.bot.send_message(tid, f"📢 <b>Объявление:</b>\n\n{text_val}", parse_mode="HTML")
            sent += 1
            if sent % 20 == 0: await asyncio.sleep(0.5)
        except: pass
    await message.answer(f"✅ Рассылка завершена: {sent}")


# =========================
# USER MGMT
# =========================
@router.callback_query(F.data == "admin_manage_users")
async def admin_manage_users(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Досье", callback_data="admin_user_dossier")],
        [InlineKeyboardButton(text="💰 Выдать монеты", callback_data="admin_give_coins")],
        [InlineKeyboardButton(text="🚫 Бан", callback_data="admin_ban_user")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")],
    ])
    await _safe_edit(callback, "👥 <b>Управление пользователями</b>", parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_user_dossier")
async def dossier_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminUserState.waiting_dossier_id)
    await callback.message.answer("Введите ID или ник:")
    await callback.answer()


@router.message(AdminUserState.waiting_dossier_id)
async def process_dossier(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    query = message.text.strip()
    async with async_session() as session:
        user = await get_user(session, int(query)) if query.isdigit() else await get_user_by_display_name(session, query)
        if not user:
            await message.answer("❌ Не найден")
            return
        d = await get_user_dossier(session, user.id)
    text_out = f"📋 <b>Досье: {escape(get_display_name(user))}</b>\n💰 Баланс: {user.balance}\n📤 Загрузок: {d['videos_uploaded']}"
    await message.answer(text_out, parse_mode="HTML")
    await state.clear()


@router.callback_query(F.data == "admin_extended_stats")
async def admin_extended_stats(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    async with async_session() as session:
        stats = await get_admin_extended_stats(session)
    await _safe_edit(callback, f"📊 <b>Статистика</b>\n\n👥 Юзеров: {stats['users']}\n💰 Баланс: {stats['total_balance_in_system']:.2f}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")]]))
    await callback.answer()


@router.callback_query(F.data == "admin_offers_menu")
async def admin_offers_menu(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать", callback_data="admin_create_offer")],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")]
    ])
    await _safe_edit(callback, "📢 <b>Офферы</b>", reply_markup=kb)
    await callback.answer()
