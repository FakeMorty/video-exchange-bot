from app.models import utc_now
import os
import asyncio
from datetime import datetime, timezone, timedelta
from html import escape
from decimal import Decimal

from aiogram import Router, F
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
)
from sqlalchemy import select, func, text


from app.config import ENABLE_AUTO_MODERATION
from app.db import async_session
from app.models import (
    Base,
    User, Video, TrustedUploader, Event, ActiveSale,
    VideoReport, ModNotification,
)
from app.services import (
    get_user, get_user_by_id, get_user_by_username,
    get_user_dossier, count_pending_videos, count_approved_videos, count_rejected_videos,
    get_next_pending_video, approve_video, reject_video,
    get_admin_extended_stats, get_display_name, get_styled_display_name,
    get_user_by_display_name, get_recent_feedback, get_active_sale,
    get_active_events, approve_all_pending,
    get_pending_reports, dismiss_report, REPORT_REASONS,
)
from app.keyboards import (
    admin_main_keyboard, moderation_keyboard,
    rejection_reason_keyboard, admin_after_action_keyboard,
    admin_db_keyboard,
)
from app.logger import get_logger
from app.reports import build_all_users_report_pdf, build_bot_report_pdf, build_user_report_pdf
from app.utils.admin import check_admin, is_super_admin, _safe_edit

logger = get_logger(__name__)

router = Router()

@router.message(Command("cancel"))
async def cmd_cancel_admin(message: Message, state: FSMContext):
    await state.clear()
    from app.keyboards import main_menu
    from app.services import get_user, is_any_admin
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        admin_flag = is_any_admin(message.from_user.id, user)
    await message.answer("❌ Действие отменено.", reply_markup=main_menu(is_admin=admin_flag))


@router.message(CommandStart())
async def cmd_start_admin(message: Message, command: CommandObject, state: FSMContext):
    await state.clear()
    from app.user_handlers import cmd_start
    await cmd_start(message, command, state)


# =========================
# STATES
# =========================
class AdminUserState(StatesGroup):
    waiting_user_id = State()
    waiting_coins_amount = State()
    waiting_message_text = State()
    waiting_dossier_id = State()
    waiting_new_nickname = State()


class ModerationRejectState(StatesGroup):
    waiting_comment = State()


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
    waiting_penalty = State()
    waiting_rentable = State()
    waiting_rent_cost = State()
    waiting_max_rentals = State()


class TrustedUploaderState(StatesGroup):
    waiting_add = State()
    waiting_remove = State()


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

    # SQL injection protection: whitelist table names
    from app.models import Base
    allowed_tables = [mapper.class_.__tablename__ for mapper in Base.registry.mappers]
    if table_name not in allowed_tables:
        await callback.answer("Недопустимая таблица", show_alert=True)
        return

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
        name = await get_styled_display_name(session, uploader) if uploader else "???"
        caption = f"📹 #{video.id} | {video.content_type}\n👤 {name}\n📅 {video.created_at.strftime('%d.%m %H:%M')}"
        try:
            if video.content_type == "photo":
                await callback.message.answer_photo(video.telegram_file_id, caption=caption, reply_markup=moderation_keyboard(video.id))
            else:
                await callback.message.answer_video(video.telegram_file_id, caption=caption, reply_markup=moderation_keyboard(video.id))
        except Exception:
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
                except Exception: pass
    await _safe_edit(callback, f"✅ #{video_id} ОДОБРЕНО", reply_markup=admin_after_action_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("mod_reject:"))
async def mod_reject(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    video_id = int(callback.data.split(":")[1])
    await _safe_edit(callback, f"Причина отклонения #{video_id}:", reply_markup=rejection_reason_keyboard(video_id))
    await callback.answer()


@router.callback_query(F.data.startswith("reject_reason:"))
async def reject_reason(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    parts = callback.data.split(":")
    video_id, reason_key = int(parts[1]), parts[2]
    reasons = {"duplicate": "Дубликат", "off_topic": "Не по теме", "forbidden": "Запрещёнка", "other": "Другое"}
    reason_text = reasons.get(reason_key, reason_key)
    await state.set_state(ModerationRejectState.waiting_comment)
    await state.update_data(reject_video_id=video_id, reject_reason_text=reason_text)
    await _safe_edit(
        callback,
        f"❌ <b>Отклонение #{video_id}</b>\n\n"
        f"Базовая причина: <b>{reason_text}</b>\n\n"
        f"Теперь отправьте <b>комментарий для пользователя</b>, где объясните, что именно не так с публикацией.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_get_pending")]
        ])
    )
    await callback.answer()


@router.message(ModerationRejectState.waiting_comment)
async def reject_reason_comment(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    comment = (message.text or "").strip()
    if len(comment) < 3:
        await message.answer("❌ Комментарий слишком короткий. Напишите понятное объяснение для пользователя.")
        return

    data = await state.get_data()
    video_id = data.get("reject_video_id")
    reason_text = data.get("reject_reason_text")
    if not video_id or not reason_text:
        await state.clear()
        await message.answer("❌ Сессия отклонения потеряна. Начните заново.")
        return

    async with async_session() as session:
        video = await reject_video(session, int(video_id), str(reason_text), comment)
        if video:
            uploader = await get_user_by_id(session, video.uploader_user_id)
            if uploader:
                try:
                    await message.bot.send_message(
                        uploader.telegram_id,
                        f"❌ Публикация #{video_id} отклонена.\n"
                        f"Причина: {reason_text}\n"
                        f"Комментарий модератора: {comment}",
                    )
                except Exception:
                    pass
    await state.clear()
    await message.answer(
        f"❌ #{video_id} отклонено\n"
        f"Причина: {reason_text}\n"
        f"Комментарий: {comment}",
        reply_markup=admin_after_action_keyboard(),
    )


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
            active = (await session.execute(select(Event).where(Event.is_active.is_(True), Event.end_date > utc_now()).order_by(Event.start_date.desc()))).scalars().all()
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
    start = utc_now()
    end = start + timedelta(days=data["duration_days"])
    async with async_session() as session:
        admin = await get_user(session, callback.from_user.id)
        ev = Event(name=data["name"], description=data["description"], discount_percent=data["discount_percent"], duration_days=data["duration_days"], applies_vip=applies.get("vip", False), applies_coins=applies.get("coins", False), applies_lootbox=applies.get("lootbox", False), image_file_id=data.get("image_file_id"), start_date=start, end_date=end, is_active=True, created_by=admin.id if admin else None)
        session.add(ev)
        await session.commit()
    await state.clear()
    
    # Рассылаем уведомление всем пользователям
    from app.services import broadcast_event_to_users
    try:
        sent = await broadcast_event_to_users(callback.bot, ev)
        await callback.message.answer(f"✅ Событие создано!\n📢 Рассылка: {sent} пользователей.")
    except Exception as e:
        logger.error(f"Ошибка рассылки события: {e}")
        await callback.message.answer(f"✅ Событие создано!\n⚠️ Рассылка не удалась: {e}")
    await callback.answer()


@router.callback_query(F.data == "event_list_all")
async def event_list_all(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    async with async_session() as session:
        events = (await session.execute(select(Event).order_by(Event.created_at.desc()).limit(20))).scalars().all()
    if not events:
        await callback.message.answer("Нет событий.")
        await callback.answer()
        return
    for ev in events:
        status = "🟢 Активно" if ev.is_active and ev.end_date > utc_now() else "🔴 Завершено"
        text = (
            f"🎉 <b>{escape(ev.name)}</b>\n"
            f"Скидка: {ev.discount_percent}% | {status}\n"
            f"До: {ev.end_date.strftime('%d.%m.%Y %H:%M')}"
        )
        kb_rows = []
        if ev.is_active and ev.end_date > utc_now():
            kb_rows.append([InlineKeyboardButton(text="🛑 Остановить", callback_data=f"event_stop:{ev.id}")])
        kb_rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_events_menu")])
        await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
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
            sale.end_date = utc_now()
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
    end_date = utc_now() + timedelta(hours=data["duration_hours"])
    async with async_session() as session:
        sale = ActiveSale(discount_percent=data["discount_percent"], applies_to=data["applies_to"], end_date=end_date, announcement=message.text)
        session.add(sale)
        await session.commit()
    await state.clear()
    
    # Рассылаем уведомление всем пользователям
    from app.services import broadcast_sale_to_users
    try:
        sent = await broadcast_sale_to_users(message.bot, sale)
        await message.answer(f"✅ Акция запущена!\n📢 Рассылка: {sent} пользователей.")
    except Exception as e:
        logger.error(f"Ошибка рассылки акции: {e}")
        await message.answer(f"✅ Акция запущена!\n⚠️ Рассылка не удалась: {e}")


# =========================
# BROADCAST
# =========================
@router.callback_query(F.data == "admin_direct_message_all")
async def admin_direct_message_all(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        return
    await state.clear()
    await state.set_state(AdminBroadcastState.waiting_text)
    await state.update_data(broadcast_mode="admin_direct")
    await _safe_edit(
        callback,
        "📨 <b>Сообщение всем от админа</b>\n\n"
        "Напишите текст, который бот отправит всем активным пользователям.\n\n"
        "Пользователь увидит это в формате:\n"
        "<code>📢 Вам сообщение от админа: ...</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_center")]
        ])
    )
    await callback.answer()


@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Еженедельная халява", callback_data="admin_broadcast_tpl:bonus")],
        [InlineKeyboardButton(text="🎰 Реклама Секслото", callback_data="admin_broadcast_tpl:lottery")],
        [InlineKeyboardButton(text="💋 Призыв поболтать с Катей", callback_data="admin_broadcast_tpl:katya")],
        [InlineKeyboardButton(text="🎟 Создание промокодов", callback_data="admin_broadcast_tpl:promo")],
        [InlineKeyboardButton(text="🎁 Лутбоксы", callback_data="admin_broadcast_tpl:games")],
        [InlineKeyboardButton(text="👥 Рефералка", callback_data="admin_broadcast_tpl:quests")],
        [InlineKeyboardButton(text="👑 Привилегии VIP-подписки", callback_data="admin_broadcast_tpl:vip")],
        [InlineKeyboardButton(text="✍️ Написать свой текст (HTML)", callback_data="admin_broadcast_custom")],
        [InlineKeyboardButton(text="◀️ Назад в админку", callback_data="admin_center")]
    ])
    
    await _safe_edit(
        callback,
        "📢 <b>Управление рассылками и пуш-уведомлениями</b>\n\n"
        "Выберите готовый шаблон для напоминания пользователям о функциях бота, или напишите свой собственный текст:",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_broadcast_tpl:"))
async def cb_admin_broadcast_tpl(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    tpl_name = callback.data.split(":", 1)[1]
    
    templates = {
        "bonus": (
            "🎁 <b>Еженедельная халява уже близко!</b>\n\n"
            "Раз в неделю мы рассылаем секретный промокод на бесплатные монеты. Следите за сообщениями бота и не пропустите раздачу! 💰\n\n"
            "👉 Перейдите в меню <b>🎟 Промокоды</b>"
        ),
        "lottery": (
            "🎰 <b>Секслото — разыгрываем миллионы!</b>\n\n"
            "Новый раунд уже открыт! Купите счастливый билет за монеты и следите за розыгрышем прямо в Mini App. 🎡\n\n"
            "👉 Зайдите в меню <b>🎮 Игры ➔ 🎰 Секслото</b>"
        ),
        "katya": (
            "💋 <b>Катя заждалась тебя...</b>\n\n"
            "Твоя виртуальная подруга Катя скучает и хочет поболтать. Она подготовила новые пикантные темы для беседы! 😏🤸‍♀️\n\n"
            "👉 Нажмите кнопку <b>💋 ИИ-Общение</b> в главном меню!"
        ),
        "promo": (
            "🎟 <b>Создавайте свои промокоды за Stars!</b>\n\n"
            "Хотите порадовать подписчиков своего канала или друзей? Создайте свой уникальный промокод на любую сумму монет и подарите его им! 🎁\n\n"
            "👉 Перейдите в меню <b>🎟 Промокоды</b>"
        ),
        "games": (
            "🎁 <b>Откройте лутбокс!</b>\n\n"
            "Иногда один лутбокс — это быстрый способ вернуться в игру и сорвать красивый дроп монет. Проверьте удачу!\n\n"
            "👉 Перейдите в меню <b>🎮 Игры</b>"
        ),
        "quests": (
            "👥 <b>Монеты закончились? Позовите друзей!</b>\n\n"
            "Разошлите свою реферальную ссылку друзьям и получайте крупные награды за новых активных пользователей. Это самый быстрый способ снова пополнить баланс.\n\n"
            "👉 Перейдите в меню <b>👥 Рефералы</b>"
        ),
        "vip": (
            "👑 <b>Получите статус VIP-пользователя!</b>\n\n"
            "VIP-подписка дает удвоенные награды за просмотры, огромные скидки в магазине, бесплатное создание промокодов и эксклюзивные элитные стили никнеймов! Позвольте себе роскошь! ⭐\n\n"
            "👉 Перейдите в меню <b>👑 VIP</b>!"
        )
    }
    
    tpl_text = templates.get(tpl_name)
    if not tpl_text:
        await callback.answer("Ошибка шаблона", show_alert=True)
        return
        
    await state.update_data(broadcast_text=tpl_text, broadcast_mode="promo")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Запустить рассылку", callback_data="admin_broadcast_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_broadcast")]
    ])
    
    await _safe_edit(
        callback,
        f"📢 <b>Предпросмотр рассылки:</b>\n\n"
        f"----------------------------------\n"
        f"{tpl_text}\n"
        f"----------------------------------\n\n"
        f"Вы действительно хотите отправить это сообщение всем активным пользователям?",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data == "admin_broadcast_custom")
async def cb_admin_broadcast_custom(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    await state.set_state(AdminBroadcastState.waiting_text)
    await state.update_data(broadcast_mode="promo")
    await callback.message.answer("📢 Введите ваш пользовательский текст для промо-рассылки (поддерживается HTML-разметка):")
    await callback.answer()


@router.message(AdminBroadcastState.waiting_text)
async def process_broadcast(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    text_val = (message.text or "").strip()
    if not text_val:
        await message.answer("❌ Текст не может быть пустым.")
        return

    data = await state.get_data()
    mode = data.get("broadcast_mode", "promo")
    await state.update_data(broadcast_text=text_val)

    if mode == "admin_direct":
        preview_text = (
            "📢 <b>Вам сообщение от админа:</b>\n\n"
            f"{text_val}"
        )
        cancel_target = "admin_center"
        header = "📨 <b>Предпросмотр сообщения от админа:</b>"
    else:
        preview_text = text_val
        cancel_target = "admin_broadcast"
        header = "📢 <b>Предпросмотр вашей рассылки:</b>"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Запустить рассылку", callback_data="admin_broadcast_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=cancel_target)]
    ])

    await message.answer(
        f"{header}\n\n"
        f"----------------------------------\n"
        f"{preview_text}\n"
        f"----------------------------------\n\n"
        f"Вы действительно хотите отправить это сообщение всем активным пользователям?",
        parse_mode="HTML",
        reply_markup=kb
    )


@router.callback_query(F.data == "admin_broadcast_confirm")
async def cb_admin_broadcast_confirm(callback: CallbackQuery, state: FSMContext, bot):
    if not await check_admin(callback.from_user.id):
        return

    data = await state.get_data()
    text_val = data.get("broadcast_text")
    mode = data.get("broadcast_mode", "promo")
    await state.clear()

    if not text_val:
        await callback.answer("Ошибка: Текст пуст.", show_alert=True)
        return

    if mode == "admin_direct":
        outgoing_text = f"📢 <b>Вам сообщение от админа:</b>\n\n{text_val}"
        start_text = "⏳ <b>Сообщение от админа отправляется всем активным пользователям...</b>"
        done_text = "✅ <b>Сообщение от админа успешно отправлено!</b>"
    else:
        outgoing_text = text_val
        start_text = "⏳ <b>Рассылка запущена в фоновом режиме...</b>"
        done_text = "✅ <b>Рассылка успешно завершена!</b>"

    await callback.message.edit_text(start_text, parse_mode="HTML")
    await callback.answer()

    async def run_broadcast_task():
        async with async_session() as session:
            users = (await session.execute(select(User.telegram_id).where(User.status == "active"))).scalars().all()

        sent = 0
        for tid in users:
            try:
                await bot.send_message(tid, outgoing_text, parse_mode="HTML")
                sent += 1
                if sent % 30 == 0:
                    await asyncio.sleep(0.5)
            except Exception:
                pass

        try:
            await bot.send_message(
                callback.from_user.id,
                f"{done_text}\n\n"
                f"Сообщение доставлено <b>{sent}</b> активным пользователям.",
                parse_mode="HTML"
            )
        except Exception:
            pass

    asyncio.create_task(run_broadcast_task())


# =========================
# USER MGMT
# =========================
@router.callback_query(F.data.startswith("admin_manage_users"))
async def admin_manage_users(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    
    parts = callback.data.split(":")
    offset = int(parts[1]) if len(parts) > 1 else 0
    limit = 8
    
    async with async_session() as session:
        total = (await session.execute(select(func.count(User.id)))).scalar_one()
        users = (await session.execute(select(User).order_by(User.id.desc()).offset(offset).limit(limit))).scalars().all()
        
    text = f"👥 <b>Управление пользователями ({offset + 1}-{min(offset + limit, total)} из {total})</b>\n\nВыберите пользователя для управления:"
    
    kb_rows = []
    for u in users:
        name = u.display_name or u.username or f"User {u.telegram_id}"
        status_icon = "🚫" if u.status == "banned" else "👤"
        kb_rows.append([InlineKeyboardButton(
            text=f"{status_icon} {name[:18]} (ID: {u.telegram_id})",
            callback_data=f"admin_select_user:{u.id}"
        )])
        
    # Navigation row
    nav_row = []
    if offset > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_manage_users:{max(0, offset - limit)}"))
    if offset + limit < total:
        nav_row.append(InlineKeyboardButton(text="Вперед ▶️", callback_data=f"admin_manage_users:{offset + limit}"))
        
    if nav_row:
        kb_rows.append(nav_row)
        
    kb_rows.append([InlineKeyboardButton(text="◀ Назад в админку", callback_data="admin_center")])
    
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await callback.answer()


async def show_user_profile(callback: CallbackQuery, user_id: int):
    async with async_session() as session:
        user = await get_user_by_id(session, user_id)
        if not user:
            return False
            
    from app.user_handlers import is_vip
    status_text = "🚫 Забанен" if user.status == "banned" else "✅ Активен"
    vip_text = "👑 Да" if is_vip(user) else "❌ Нет"
    
    text = (

        f"👤 <b>Управление пользователем:</b> <a href='tg://user?id={user.telegram_id}'>{user.display_name or user.username or user_id}</a>\n\n"

        f"• <b>Telegram ID:</b> <code>{user.telegram_id}</code>\n"

        f"• <b>Username:</b> {('@' + user.username) if user.username else 'отсутствует'}\n"

        f"• <b>Никнейм в БД:</b> {user.display_name or 'отсутствует'}\n"

        f"• <b>Баланс:</b> <b>{user.balance}</b> монет\n"

        f"• <b>Серия бонусов:</b> {user.bonus_streak} дней\n"

        f"• <b>Уровень/XP:</b> Lvl {user.level} ({user.xp} XP)\n"

        f"• <b>Статус:</b> {status_text}\n"

        f"• <b>VIP статус:</b> {vip_text}\n"

    )
    
    ban_label = "✅ Разбанить" if user.status == "banned" else "🚫 Забанить"
    
    kb_rows = [
        [
            InlineKeyboardButton(text="✏️ Поменять ник", callback_data=f"admin_user_edit_nick_start:{user_id}"),
            InlineKeyboardButton(text="💰 Выдать монеты", callback_data=f"admin_user_give_coins_start:{user_id}"),
        ],
        [
            InlineKeyboardButton(text=ban_label, callback_data=f"admin_user_toggle_ban:{user_id}"),
            InlineKeyboardButton(text="✉️ Личное сообщение", callback_data=f"admin_user_send_msg_start:{user_id}"),
        ],
        [InlineKeyboardButton(text="🔎 Всеобъемлющее досье", callback_data=f"admin_user_dossier_detailed:{user_id}")],
    ]
    if is_super_admin(callback.from_user.id):
        kb_rows.append([InlineKeyboardButton(text="📄 Экспорт PDF", callback_data=f"admin_user_export_pdf:{user_id}")])
    kb_rows.append([InlineKeyboardButton(text="◀️ Назад к списку", callback_data="admin_manage_users:0")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    return True


@router.callback_query(F.data.startswith("admin_select_user:"))
async def admin_select_user(callback: CallbackQuery):

    if not await check_admin(callback.from_user.id): return
    
    user_id = int(callback.data.split(":", 1)[1])
    async with async_session() as session:
        user = await get_user_by_id(session, user_id)
        if not user:
            await callback.answer("Пользователь не найден в базе.", show_alert=True)
            return
            
    from app.user_handlers import is_vip
    status_text = "🚫 Забанен" if user.status == "banned" else "✅ Активен"
    vip_text = "👑 Да" if is_vip(user) else "❌ Нет"
    
    text = (

        f"👤 <b>Управление пользователем:</b> <a href='tg://user?id={user.telegram_id}'>{user.display_name or user.username or user_id}</a>\n\n"

        f"• <b>Telegram ID:</b> <code>{user.telegram_id}</code>\n"

        f"• <b>Username:</b> {('@' + user.username) if user.username else 'отсутствует'}\n"

        f"• <b>Никнейм в БД:</b> {user.display_name or 'отсутствует'}\n"

        f"• <b>Баланс:</b> <b>{user.balance}</b> монет\n"

        f"• <b>Серия бонусов:</b> {user.bonus_streak} дней\n"

        f"• <b>Уровень/XP:</b> Lvl {user.level} ({user.xp} XP)\n"

        f"• <b>Статус:</b> {status_text}\n"

        f"• <b>VIP статус:</b> {vip_text}\n"

    )
    
    ban_label = "✅ Разбанить" if user.status == "banned" else "🚫 Забанить"
    
    kb_rows = [
        [
            InlineKeyboardButton(text="✏️ Поменять ник", callback_data=f"admin_user_edit_nick_start:{user_id}"),
            InlineKeyboardButton(text="💰 Выдать монеты", callback_data=f"admin_user_give_coins_start:{user_id}"),
        ],
        [
            InlineKeyboardButton(text=ban_label, callback_data=f"admin_user_toggle_ban:{user_id}"),
            InlineKeyboardButton(text="✉️ Личное сообщение", callback_data=f"admin_user_send_msg_start:{user_id}"),
        ],
        [InlineKeyboardButton(text="🔎 Всеобъемлющее досье", callback_data=f"admin_user_dossier_detailed:{user_id}")],
    ]
    if is_super_admin(callback.from_user.id):
        kb_rows.append([InlineKeyboardButton(text="📄 Экспорт PDF", callback_data=f"admin_user_export_pdf:{user_id}")])
    kb_rows.append([InlineKeyboardButton(text="◀️ Назад к списку", callback_data="admin_manage_users:0")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_user_export_pdf:"))
async def admin_user_export_pdf(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Только супер-админ.", show_alert=True)
        return

    user_id = int(callback.data.split(":", 1)[1])
    await callback.answer()
    await callback.message.answer("⏳ Готовлю подробный PDF-отчёт по пользователю...")

    async def _runner() -> None:
        pdf_path = None
        try:
            async with async_session() as session:
                user = await get_user_by_id(session, user_id)
                if not user:
                    await callback.bot.send_message(callback.from_user.id, "❌ Пользователь не найден.")
                    return
                telegram_id = user.telegram_id

            pdf_path, filename = await build_user_report_pdf(telegram_id)
            await callback.bot.send_document(
                callback.from_user.id,
                FSInputFile(str(pdf_path), filename=filename),
                caption=f"📄 PDF-отчёт по пользователю <code>{telegram_id}</code> готов.",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.exception("Failed to build admin user PDF report")
            await callback.bot.send_message(
                callback.from_user.id,
                f"❌ Не удалось собрать PDF по пользователю. Ошибка: {escape(str(e))}",
                parse_mode="HTML",
            )
        finally:
            if pdf_path:
                try:
                    os.remove(pdf_path)
                except Exception:
                    pass

    asyncio.create_task(_runner())


@router.callback_query(F.data.startswith("admin_user_edit_nick_start:"))
async def cb_admin_user_edit_nick_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    user_id = int(callback.data.split(":", 1)[1])
    await state.update_data(target_user_id=user_id)
    await state.set_state(AdminUserState.waiting_new_nickname)
    await _safe_edit(
        callback,
        "✏️ <b>Изменение никнейма пользователя</b>\n\n"
        "Отправьте мне <b>новый никнейм</b> для этого пользователя:\n"
        "• От 3 до 20 символов\n"
        "• Буквы, цифры, _ и -",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin_select_user:{user_id}")]
        ])
    )
    await callback.answer()


@router.message(AdminUserState.waiting_new_nickname)
async def process_admin_user_edit_nick(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    new_nick = (message.text or "").strip()
    
    data = await state.get_data()
    user_id = data.get("target_user_id")
    if not user_id:
        await state.clear()
        return
        
    import re
    if not re.match(r"^[a-zA-Zа-яА-ЯёЁ0-9_-]+$", new_nick) or len(new_nick) < 3 or len(new_nick) > 20:
        await message.answer("❌ Недопустимый формат ника. Допустимы только буквы, цифры, _ и - от 3 до 20 символов. Введите снова:")
        return
        
    async with async_session() as session:
        exists = (await session.execute(
            select(User).where(User.display_name == new_nick, User.telegram_id != user_id)
        )).scalars().first()
        if exists:
            await message.answer("❌ Этот ник уже занят другим пользователем. Введите другой ник:")
            return
            
        user = await get_user_by_id(session, user_id)
        if not user:
            await message.answer("Пользователь не найден.")
            await state.clear()
            return
            
        old_nick = user.display_name
        user.display_name = new_nick
        user.nickname_set = True
        await session.commit()
        
    await message.answer(
        f"✅ Никнейм пользователя успешно изменен!\n\n"
        f"• Старый ник: <b>{old_nick or 'не задан'}</b>\n"
        f"• Новый ник: <b>{new_nick}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад к пользователю", callback_data=f"admin_select_user:{user_id}")]
        ])
    )
    await state.clear()


@router.callback_query(F.data.startswith("admin_user_give_coins_start:"))
async def cb_admin_user_give_coins_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    user_id = int(callback.data.split(":", 1)[1])
    await state.update_data(target_user_id=user_id)
    await state.set_state(AdminUserState.waiting_coins_amount)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="+10 🪙", callback_data=f"admin_user_give_coins_exec:{user_id}:10"),
            InlineKeyboardButton(text="+50 🪙", callback_data=f"admin_user_give_coins_exec:{user_id}:50"),
            InlineKeyboardButton(text="+100 🪙", callback_data=f"admin_user_give_coins_exec:{user_id}:100"),
            InlineKeyboardButton(text="+500 🪙", callback_data=f"admin_user_give_coins_exec:{user_id}:500"),
        ],
        [
            InlineKeyboardButton(text="-10 🪙", callback_data=f"admin_user_give_coins_exec:{user_id}:-10"),
            InlineKeyboardButton(text="-50 🪙", callback_data=f"admin_user_give_coins_exec:{user_id}:-50"),
            InlineKeyboardButton(text="-100 🪙", callback_data=f"admin_user_give_coins_exec:{user_id}:-100"),
            InlineKeyboardButton(text="-500 🪙", callback_data=f"admin_user_give_coins_exec:{user_id}:-500"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin_select_user:{user_id}")]
    ])
    
    await _safe_edit(
        callback,
        "💰 <b>Начисление или списание монет</b>\n\n"
        "Используйте быстрые кнопки ниже для начисления/списания монет в один клик,\n"
        "либо отправьте число сообщением (например, <code>150</code> или <code>-50</code>).",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_user_give_coins_exec:"))
async def cb_admin_user_give_coins_exec(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    parts = callback.data.split(":")
    user_id = int(parts[1])
    amount = Decimal(parts[2])
    
    async with async_session() as session:
        user = await get_user_by_id(session, user_id)
        if not user:
            await callback.answer("Пользователь не найден.", show_alert=True)
            return
            
        from app.services import change_balance_atomic
        user = await change_balance_atomic(
            session,
            user.id,
            amount,
            "admin_balance",
            admin_id=callback.from_user.id,
            details="Быстрые кнопки баланса"
        ) or user
        await session.commit()
        
    await callback.answer(f"✅ Успешно { 'начислено' if amount > 0 else 'списано' } {abs(amount)} монет!", show_alert=True)
    await state.clear()
    await show_user_profile(callback, user_id)


@router.message(AdminUserState.waiting_coins_amount)
async def process_admin_user_give_coins(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    try:
        val = (message.text or "").strip().replace(",", ".")
        try:
            amount = Decimal(val)
        except Exception:
            await message.answer("❌ Некорректное число монет. Отправьте число (например, 100 или -50):")
            return
            
        data = await state.get_data()
        user_id = data.get("target_user_id")
        if not user_id:
            await state.clear()
            return
            
        async with async_session() as session:
            user = await get_user_by_id(session, user_id)
            if not user:
                await message.answer("Пользователь не найден.")
                await state.clear()
                return
                
            from app.services import change_balance_atomic
            user = await change_balance_atomic(
                session,
                user.id,
                amount,
                "admin_balance",
                admin_id=message.from_user.id,
                details="Изменено администратором"
            ) or user
            await session.commit()
            
        status_msg = "начислено" if amount >= 0 else "списано"
        abs_amount = abs(amount)
        await message.answer(
            f"✅ Пользователю успешно {status_msg} <b>{abs_amount}</b> монет!\n\n"
            f"• Новый баланс: <b>{user.balance}</b> монет.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад к пользователю", callback_data=f"admin_select_user:{user_id}")]
            ])
        )
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Произошла системная ошибка при начислении монет: <code>{e}</code>", parse_mode="HTML")
        await state.clear()


@router.callback_query(F.data.startswith("admin_user_toggle_ban:"))
async def cb_admin_user_toggle_ban(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    
    user_id = int(callback.data.split(":", 1)[1])
    async with async_session() as session:
        user = await get_user_by_id(session, user_id)
        if not user:
            await callback.answer("Пользователь не найден.")
            return
            
        if user.status == "banned":
            user.status = "active"
            action = "unbanned"
            msg = f"Пользователь {user.display_name or user_id} разбанен."
        else:
            user.status = "banned"
            action = "banned"
            msg = f"Пользователь {user.display_name or user_id} заблокирован!"
            
        await session.commit()
        await callback.answer(msg, show_alert=True)
        
    await show_user_profile(callback, user_id)


@router.callback_query(F.data.startswith("admin_user_send_msg_start:"))
async def cb_admin_user_send_msg_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    user_id = int(callback.data.split(":", 1)[1])
    await state.update_data(target_user_id=user_id)
    await state.set_state(AdminUserState.waiting_message_text)
    await _safe_edit(
        callback,
        "✉️ <b>Личное сообщение от бота</b>\n\n"
        "Отправьте мне текст сообщения, которое хотите доставить этому пользователю лично от имени бота:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin_select_user:{user_id}")]
        ])
    )
    await callback.answer()


@router.message(AdminUserState.waiting_message_text)
async def process_admin_user_send_msg(message: Message, state: FSMContext, bot):
    if not await check_admin(message.from_user.id):
        return
    text_val = (message.text or "").strip()
    if not text_val:
        await message.answer("❌ Сообщение не может быть пустым. Введите текст:")
        return

    data = await state.get_data()
    user_id = data.get("target_user_id")
    if not user_id:
        await state.clear()
        return

    async with async_session() as session:
        user = await get_user_by_id(session, user_id)
        if not user:
            await message.answer("❌ Пользователь не найден.")
            await state.clear()
            return
        telegram_id = user.telegram_id

    try:
        await bot.send_message(
            telegram_id,
            f"✉️ <b>Сообщение от администрации бота:</b>\n\n{text_val}",
            parse_mode="HTML",
        )
        await message.answer(
            "✅ Сообщение успешно отправлено в личные сообщения пользователю!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ К админам", callback_data="admin_manage_users:0")]
            ])
        )
    except Exception as e:
        await message.answer(
            f"❌ Не удалось отправить сообщение в Telegram. Ошибка: {e}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ К админам", callback_data="admin_manage_users:0")]
            ])
        )
    await state.clear()


@router.callback_query(F.data.startswith("admin_user_dossier_detailed:"))
async def cb_admin_user_dossier_detailed(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    
    user_id = int(callback.data.split(":", 1)[1])
    async with async_session() as session:
        d = await get_user_dossier(session, user_id)
        if not d:
            await callback.answer("Пользователь не найден.", show_alert=True)
            return
            
    from app.user_handlers import is_vip
    user = d["user"]
    styled_name = await get_styled_display_name(session, user, card=True)
    
    text = (
        f"🔍 <b>ПОЛНОЕ СЛЕДСТВЕННОЕ ДОСЬЕ ПОЛЬЗОВАТЕЛЯ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Профиль:</b> <a href='tg://user?id={user.telegram_id}'>{styled_name}</a>\n"
        f"• <b>Telegram ID:</b> <code>{user.telegram_id}</code>\n"
        f"• <b>Username:</b> {('@' + user.username) if user.username else 'нет'}\n"
        f"• <b>Никнейм в БД:</b> {user.display_name or 'не установлен'}\n"
        f"• <b>Роль доступа:</b> {d['role_label']}\n"
        f"• <b>Баланс:</b> <b>{user.balance}</b> монет\n"
        f"• <b>VIP статус:</b> {'👑 Активен до ' + user.vip_until.strftime('%d.%m.%Y') if is_vip(user) else '❌ Нет'}\n"
        f"• <b>Рефералы:</b> пригласил <b>{user.referrals_count}</b> юзеров (заработал {user.referral_earnings} монет)\n"
        f"• <b>Дата регистрации:</b> {user.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"📈 <b>Активность и контент:</b>\n"
        f"• <b>Загружено файлов:</b> {d['videos_uploaded']} шт. (Средний рейтинг: ★ {d['avg_rating']})\n"
        f"• <b>Просмотрено файлов:</b> {d['videos_watched']} шт.\n"
        f"• <b>Оставлено комментариев:</b> {d['comments_count']} шт.\n"
        f"• <b>Поставлено реакций:</b> {d['reactions_count']} шт.\n\n"
        f"💰 <b>Финансовый аудит:</b>\n"
        f"• <b>Заработано (за всё время):</b> +{d['total_earned']} монет\n"
        f"• <b>Потрачено (за всё время):</b> {d['total_spent']} монет\n"
        f"• <b>Заработано за неделю:</b> +{d['weekly_earned']} монет\n"
        f"• <b>Потрачено за неделю:</b> {d['weekly_spent']} монет\n"
        f"• <b>Выдано администратором:</b> +{d['admin_given']} монет\n\n"
        f"🎮 <b>Игровая статистика:</b>\n"
        f"• <b>Сыграно игр:</b> {d['games_count']} раз (Чистая прибыль: {d['game_profit']} монет)\n"
        f"• <b>Крупные выигрыши (>50):</b> {len(d['suspicious_games'])} раз\n"
    )
    
    if d["action_logs"]:
        text += "\n📝 <b>Последние действия в системе:</b>\n"
        for log in d["action_logs"][:5]:
            text += f" • <code>{log.created_at.strftime('%H:%M')}</code> | {log.action}: {log.details or ''}\n"
            
    if d["balance_logs"]:
        text += "\n💸 <b>Последние изменения баланса:</b>\n"
        for log in d["balance_logs"][:5]:
            sign = "+" if log.amount >= 0 else ""
            text += f" • <code>{log.created_at.strftime('%d.%m %H:%M')}</code> | <b>{sign}{log.amount}</b> ({log.source})\n"
            
    buttons = []
    if d['videos_uploaded'] > 0:
        buttons.append([InlineKeyboardButton(text="🎬 Загруженные видео", callback_data=f"admin_view_user_videos:{user_id}:0")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад к управлению", callback_data=f"admin_select_user:{user_id}")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    if len(text) > 4000:
        text = text[:4000] + "\n..."
        
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_view_user_videos:"))
async def cb_admin_view_user_videos(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    
    parts = callback.data.split(":")
    user_id = int(parts[1])
    offset = int(parts[2])
    
    async with async_session() as session:
        user = await get_user_by_id(session, user_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
            
        total = (await session.execute(
            select(func.count(Video.id)).where(Video.uploader_user_id == user.id)
        )).scalar_one()
        
        if total == 0:
            await callback.answer("Нет загруженных видео", show_alert=True)
            return
            
        video = (await session.execute(
            select(Video).where(Video.uploader_user_id == user.id).order_by(Video.id.desc()).offset(offset).limit(1)
        )).scalar_one_or_none()
        
        if not video:
            await callback.answer("Видео не найдено", show_alert=True)
            return

    nav_row = []
    if offset > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ Пред.", callback_data=f"admin_view_user_videos:{user_id}:{offset-1}"))
    if offset < total - 1:
        nav_row.append(InlineKeyboardButton(text="След. ▶️", callback_data=f"admin_view_user_videos:{user_id}:{offset+1}"))
        
    kb_rows = []
    if nav_row:
        kb_rows.append(nav_row)
    kb_rows.append([InlineKeyboardButton(text="🔎 Назад к досье", callback_data=f"admin_user_dossier_detailed:{user_id}")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    
    caption = f"🎬 <b>Загруженное видео пользователя</b> ({offset+1}/{total})\nID: {video.id} | Статус: {video.status}\nОпубликовано: {video.created_at.strftime('%d.%m.%Y %H:%M')}"
    
    try:
        await callback.message.delete()
    except Exception:
        pass

    try:

        if video.content_type == "photo":

            await callback.message.answer_photo(

                video.telegram_file_id,

                caption=caption,

                parse_mode="HTML",

                reply_markup=kb

            )

        else:

            await callback.message.answer_video(

                video.telegram_file_id,

                caption=caption,

                parse_mode="HTML",

                reply_markup=kb

            )

    except Exception as e:
        await callback.message.answer(f"⚠️ Ошибка при отправке видео: {e}")

    await callback.answer()


@router.callback_query(F.data == "admin_extended_stats")
async def admin_extended_stats(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        return
    async with async_session() as session:
        stats = await get_admin_extended_stats(session)

    rows = []
    if is_super_admin(callback.from_user.id):
        rows.append([InlineKeyboardButton(text="📊 Экспорт PDF по боту", callback_data="admin_export_bot_pdf")])
        rows.append([InlineKeyboardButton(text="👥 Экспорт PDF по всем пользователям", callback_data="admin_export_all_users_pdf")])
    rows.append([InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")])

    await _safe_edit(
        callback,
        f"📊 <b>Статистика</b>\n\n👥 Юзеров: {stats['users']}\n💰 Баланс: {stats['total_balance_in_system']:.2f}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    await callback.answer()


@router.callback_query(F.data == "admin_export_bot_pdf")
async def admin_export_bot_pdf(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Только супер-админ.", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer("⏳ Готовлю большой отчёт по всему боту: собираю данные и строю диаграммы...")

    async def _runner() -> None:
        pdf_path = None
        try:
            pdf_path, filename = await build_bot_report_pdf()
            await callback.bot.send_document(
                callback.from_user.id,
                FSInputFile(str(pdf_path), filename=filename),
                caption="📊 Подробный PDF-отчёт по боту готов.",
            )
        except Exception as e:
            logger.exception("Failed to build bot PDF report")
            await callback.bot.send_message(
                callback.from_user.id,
                f"❌ Не удалось собрать PDF по боту. Ошибка: {escape(str(e))}",
                parse_mode="HTML",
            )
        finally:
            if pdf_path:
                try:
                    os.remove(pdf_path)
                except Exception:
                    pass

    asyncio.create_task(_runner())


@router.callback_query(F.data == "admin_export_all_users_pdf")
async def admin_export_all_users_pdf(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Только супер-админ.", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer("⏳ Готовлю единый PDF-отчёт по всем пользователям бота. Это может занять время...")

    async def _runner() -> None:
        pdf_path = None
        try:
            pdf_path, filename = await build_all_users_report_pdf()
            await callback.bot.send_document(
                callback.from_user.id,
                FSInputFile(str(pdf_path), filename=filename),
                caption="👥 PDF-отчёт по всем пользователям готов.",
            )
        except Exception as e:
            logger.exception("Failed to build all users PDF report")
            await callback.bot.send_message(
                callback.from_user.id,
                f"❌ Не удалось собрать PDF по всем пользователям. Ошибка: {escape(str(e))}",
                parse_mode="HTML",
            )
        finally:
            if pdf_path:
                try:
                    os.remove(pdf_path)
                except Exception:
                    pass

    asyncio.create_task(_runner())


@router.callback_query(F.data == "admin_offers_menu")
async def admin_offers_menu(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать", callback_data="admin_create_offer")],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")]
    ])
    await _safe_edit(callback, "📢 <b>Офферы</b>", reply_markup=kb)
    await callback.answer()

# ============================
# НАСТРОЙКИ БОТА
# ============================

class BotSettingsState(StatesGroup):
    waiting_value = State()
    waiting_welcome_text = State()
    waiting_welcome_banner = State()


# ---------- Главное меню настроек ----------
@router.callback_query(F.data == "admin_bot_settings")
async def admin_bot_settings(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Экономика", callback_data="settings_economy")],
        [InlineKeyboardButton(text="👑 VIP", callback_data="settings_vip")],
        [InlineKeyboardButton(text="🎁 Лутбоксы", callback_data="settings_games")],
        [InlineKeyboardButton(text="🎁 Еженедельный Промокод", callback_data="settings_weekly_promo")],
        [InlineKeyboardButton(text="📺 Реклама", callback_data="settings_ads")],
        [InlineKeyboardButton(text="✏️ Никнеймы", callback_data="settings_nicks")],
        [InlineKeyboardButton(text="🎟 Промокоды", callback_data="settings_promos")],
        [InlineKeyboardButton(text="🖼 Приветствие и баннер", callback_data="settings_welcome")],
        [InlineKeyboardButton(text="🆓 ADMIN FREE", callback_data="settings_admin_free")],
        [InlineKeyboardButton(text="📊 Текущие значения", callback_data="settings_show_all")],
        [InlineKeyboardButton(text="🗑 Сбросить все настройки", callback_data="settings_reset_all")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_center")],
    ])
    await _safe_edit(callback, "🔧 <b>Настройки бота</b>\n\nВыберите категорию:", parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------- ЭКОНОМИКА ----------
@router.callback_query(F.data == "settings_economy")
async def settings_economy(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        from app.services import get_setting
        sb = await get_setting(session, "starting_balance", "")
        wc = await get_setting(session, "watch_cost", "")
        ur = await get_setting(session, "upload_reward", "")
        pr = await get_setting(session, "photo_upload_reward", "")
        str_c = await get_setting(session, "stars_to_coins_rate", "")
        ri = await get_setting(session, "referral_reward_inviter", "")
        rn = await get_setting(session, "referral_reward_new_user", "")
        fp = await get_setting(session, "first_purchase_daily_bonus", "")
    from app.config import (
        STARTING_BALANCE, WATCH_COST, UPLOAD_REWARD, PHOTO_UPLOAD_REWARD,
        STARS_TO_COINS_RATE, REFERRAL_REWARD_INVITER, REFERRAL_REWARD_NEW_USER,
        FIRST_PURCHASE_DAILY_BONUS,
    )
    def v(db_val, default):
        return f"{db_val or default}"
    text = (
        f"💰 <b>Экономика</b>\n\n"
        f"Стартовый баланс: {v(sb, STARTING_BALANCE)}\n"
        f"Просмотр видео: {v(wc, WATCH_COST)}\n"
        f"Награда за видео: {v(ur, UPLOAD_REWARD)}\n"
        f"Награда за фото: {v(pr, PHOTO_UPLOAD_REWARD)}\n"
        f"Курс Stars→Coins: {v(str_c, STARS_TO_COINS_RATE)}\n"
        f"Реферал (пригласивший): {v(ri, REFERRAL_REWARD_INVITER)}\n"
        f"Реферал (новый): {v(rn, REFERRAL_REWARD_NEW_USER)}\n"
        f"Бонус 1-й покупки: {v(fp, FIRST_PURCHASE_DAILY_BONUS)}\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Стартовый баланс", callback_data="settings_edit:starting_balance")],
        [InlineKeyboardButton(text="✏️ Цена просмотра", callback_data="settings_edit:watch_cost")],
        [InlineKeyboardButton(text="✏️ Награда за видео", callback_data="settings_edit:upload_reward")],
        [InlineKeyboardButton(text="✏️ Награда за фото", callback_data="settings_edit:photo_upload_reward")],
        [InlineKeyboardButton(text="✏️ Курс Stars→Coins", callback_data="settings_edit:stars_to_coins_rate")],
        [InlineKeyboardButton(text="✏️ Реферал (пригл.)", callback_data="settings_edit:referral_reward_inviter")],
        [InlineKeyboardButton(text="✏️ Реферал (новый)", callback_data="settings_edit:referral_reward_new_user")],
        [InlineKeyboardButton(text="✏️ Бонус 1-й покупки", callback_data="settings_edit:first_purchase_daily_bonus")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_bot_settings")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------- VIP ----------
@router.callback_query(F.data == "settings_vip")
async def settings_vip(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        from app.services import get_setting
        vp = await get_setting(session, "vip_price_stars", "")
        vd = await get_setting(session, "vip_duration_days", "")
        vb = await get_setting(session, "vip_bonus_multiplier", "")
        vw = await get_setting(session, "vip_watch_discount", "")
    from app.config import VIP_PRICE_STARS, VIP_DURATION_DAYS, VIP_BONUS_MULTIPLIER, VIP_WATCH_DISCOUNT
    def v(db_val, default):
        return f"{db_val or default}"
    text = (
        f"👑 <b>VIP</b>\n\n"
        f"Цена (Stars): {v(vp, VIP_PRICE_STARS)}\n"
        f"Длительность (дней): {v(vd, VIP_DURATION_DAYS)}\n"
        f"Множитель монет: {v(vb, VIP_BONUS_MULTIPLIER)}\n"
        f"Скидка на просмотр: {v(vw, VIP_WATCH_DISCOUNT)}\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Цена VIP (Stars)", callback_data="settings_edit:vip_price_stars")],
        [InlineKeyboardButton(text="✏️ Длительность VIP", callback_data="settings_edit:vip_duration_days")],
        [InlineKeyboardButton(text="✏️ Множитель монет", callback_data="settings_edit:vip_bonus_multiplier")],
        [InlineKeyboardButton(text="✏️ Скидка на просмотр", callback_data="settings_edit:vip_watch_discount")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_bot_settings")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------- ЛУТБОКСЫ ----------
@router.callback_query(F.data == "settings_games")
async def settings_games(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        from app.services import get_setting
        lc = await get_setting(session, "lootbox_coin_price", "")
        ls = await get_setting(session, "lootbox_star_price", "")
        eb = await get_setting(session, "enable_lootboxes", "")
    from app.config import LOOTBOX_COIN_PRICE, LOOTBOX_STAR_PRICE, ENABLE_LOOTBOXES
    def v(db_val, default):
        return f"{db_val or default}"
    text = (
        f"🎁 <b>Лутбоксы</b>\n\n"
        f"Цена лутбокса (монеты): {v(lc, LOOTBOX_COIN_PRICE)}\n"
        f"Цена лутбокса (Stars): {v(ls, LOOTBOX_STAR_PRICE)}\n"
        f"Лутбоксы: {v(eb, 'on' if ENABLE_LOOTBOXES else 'off')}\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Цена лутбокса (монеты)", callback_data="settings_edit:lootbox_coin_price")],
        [InlineKeyboardButton(text="✏️ Цена лутбокса (Stars)", callback_data="settings_edit:lootbox_star_price")],
        [InlineKeyboardButton(text="🔘 Лутбоксы " + ("выкл" if eb == "off" else "вкл"), callback_data="settings_toggle:enable_lootboxes")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_bot_settings")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------- РЕКЛАМА ----------
@router.callback_query(F.data == "settings_ads")
async def settings_ads(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        from app.services import get_setting
        vc = await get_setting(session, "smart_ad_video_chance", "")
        fs = await get_setting(session, "smart_ad_forced_watch_seconds", "")
        mi = await get_setting(session, "smart_ad_min_interval_minutes", "")
        lb = await get_setting(session, "smart_ad_low_balance_threshold", "")
        li = await get_setting(session, "smart_ad_low_balance_hint_interval", "")
        od = await get_setting(session, "offer_daily_reward_cap", "")
        vi = await get_setting(session, "videos_per_ad_interval", "")
    from app.config import (
        SMART_AD_VIDEO_CHANCE, SMART_AD_FORCED_WATCH_SECONDS,
        SMART_AD_MIN_INTERVAL_MINUTES, SMART_AD_LOW_BALANCE_THRESHOLD,
        SMART_AD_LOW_BALANCE_HINT_INTERVAL_MINUTES, OFFER_DAILY_REWARD_CAP,
    )
    def v(db_val, default):
        return f"{db_val or default}"
    text = (
        f"📺 <b>Реклама и офферы</b>\n\n"
        f"Шанс рекламы в видео: {v(vc, SMART_AD_VIDEO_CHANCE)}\n"
        f"Секунды ожидания: {v(fs, SMART_AD_FORCED_WATCH_SECONDS)}\n"
        f"Мин. интервал (мин): {v(mi, SMART_AD_MIN_INTERVAL_MINUTES)}\n"
        f"Порог низкого баланса: {v(lb, SMART_AD_LOW_BALANCE_THRESHOLD)}\n"
        f"Интервал подсказки (мин): {v(li, SMART_AD_LOW_BALANCE_HINT_INTERVAL_MINUTES)}\n"
        f"Лимит наград за офферы/день: {v(od, OFFER_DAILY_REWARD_CAP)}\n"
        f"Реклама каждые N видео: {v(vi, '10')}\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Шанс рекламы", callback_data="settings_edit:smart_ad_video_chance")],
        [InlineKeyboardButton(text="✏️ Секунды ожидания", callback_data="settings_edit:smart_ad_forced_watch_seconds")],
        [InlineKeyboardButton(text="✏️ Мин. интервал", callback_data="settings_edit:smart_ad_min_interval_minutes")],
        [InlineKeyboardButton(text="✏️ Порог низкого баланса", callback_data="settings_edit:smart_ad_low_balance_threshold")],
        [InlineKeyboardButton(text="✏️ Интервал подсказки", callback_data="settings_edit:smart_ad_low_balance_hint_interval")],
        [InlineKeyboardButton(text="✏️ Лимит наград за офферы", callback_data="settings_edit:offer_daily_reward_cap")],
        [InlineKeyboardButton(text="✏️ Реклама каждые N видео", callback_data="settings_edit:videos_per_ad_interval")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_bot_settings")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------- НИКНЕЙМЫ ----------
@router.callback_query(F.data == "settings_nicks")
async def settings_nicks(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        from app.services import get_setting
        nc = await get_setting(session, "nickname_change_cost", "")
        nm = await get_setting(session, "nickname_min_length", "")
        nx = await get_setting(session, "nickname_max_length", "")
        dl = await get_setting(session, "daily_photo_limit", "")
    from app.config import NICKNAME_CHANGE_COST, NICKNAME_MIN_LENGTH, NICKNAME_MAX_LENGTH, DAILY_PHOTO_LIMIT
    def v(db_val, default):
        return f"{db_val or default}"
    text = (
        f"✏️ <b>Никнеймы</b>\n\n"
        f"Цена смены ника: {v(nc, NICKNAME_CHANGE_COST)}\n"
        f"Мин. длина ника: {v(nm, NICKNAME_MIN_LENGTH)}\n"
        f"Макс. длина ника: {v(nx, NICKNAME_MAX_LENGTH)}\n"
        f"Лимит фото в день: {v(dl, DAILY_PHOTO_LIMIT)}\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Цена смены ника", callback_data="settings_edit:nickname_change_cost")],
        [InlineKeyboardButton(text="✏️ Мин. длина ника", callback_data="settings_edit:nickname_min_length")],
        [InlineKeyboardButton(text="✏️ Макс. длина ника", callback_data="settings_edit:nickname_max_length")],
        [InlineKeyboardButton(text="✏️ Лимит фото в день", callback_data="settings_edit:daily_photo_limit")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_bot_settings")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------- ПРОМОКОДЫ ----------
@router.callback_query(F.data == "settings_promos")
async def settings_promos(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        from app.services import get_setting
        sr = await get_setting(session, "promocode_creation_star_rate", "")
        bt = await get_setting(session, "promocode_bulk_discount_threshold", "")
        br = await get_setting(session, "promocode_bulk_discount_rate", "")
        cb = await get_setting(session, "promocode_creator_bonus_percent", "")
        mx = await get_setting(session, "promocode_max_amount", "")
        mu = await get_setting(session, "promocode_max_uses", "")
        mh = await get_setting(session, "promocode_max_hours", "")
        vp = await get_setting(session, "vip_free_promo_per_month", "")
    from app.config import (
        PROMOCODE_CREATION_STAR_RATE, PROMOCODE_BULK_DISCOUNT_THRESHOLD,
        PROMOCODE_BULK_DISCOUNT_RATE, PROMOCODE_CREATOR_BONUS_PERCENT,
        PROMOCODE_MAX_AMOUNT, PROMOCODE_MAX_USES, PROMOCODE_MAX_HOURS,
        VIP_FREE_PROMO_PER_MONTH,
    )
    def v(db_val, default):
        return f"{db_val or default}"
    text = (
        f"🎟 <b>Промокоды</b>\n\n"
        f"Цена (Stars за 1 монету): {v(sr, PROMOCODE_CREATION_STAR_RATE)}\n"
        f"Порог bulk скидки: {v(bt, PROMOCODE_BULK_DISCOUNT_THRESHOLD)}\n"
        f"Rate bulk скидки: {v(br, PROMOCODE_BULK_DISCOUNT_RATE)}\n"
        f"Бонус создателю (%): {v(cb, PROMOCODE_CREATOR_BONUS_PERCENT)}\n"
        f"Макс. сумма: {v(mx, PROMOCODE_MAX_AMOUNT)}\n"
        f"Макс. использований: {v(mu, PROMOCODE_MAX_USES)}\n"
        f"Макс. часов: {v(mh, PROMOCODE_MAX_HOURS)}\n"
        f"Бесплатных промо VIP/мес: {v(vp, VIP_FREE_PROMO_PER_MONTH)}\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Цена Stars за 1 монету", callback_data="settings_edit:promocode_creation_star_rate")],
        [InlineKeyboardButton(text="✏️ Порог bulk скидки", callback_data="settings_edit:promocode_bulk_discount_threshold")],
        [InlineKeyboardButton(text="✏️ Rate bulk скидки", callback_data="settings_edit:promocode_bulk_discount_rate")],
        [InlineKeyboardButton(text="✏️ Бонус создателю", callback_data="settings_edit:promocode_creator_bonus_percent")],
        [InlineKeyboardButton(text="✏️ Макс. сумма", callback_data="settings_edit:promocode_max_amount")],
        [InlineKeyboardButton(text="✏️ Макс. использований", callback_data="settings_edit:promocode_max_uses")],
        [InlineKeyboardButton(text="✏️ Макс. часов", callback_data="settings_edit:promocode_max_hours")],
        [InlineKeyboardButton(text="✏️ Бесплатных промо VIP", callback_data="settings_edit:vip_free_promo_per_month")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_bot_settings")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------- ЛОТЕРЕЯ (СЕКРЕТНЫЕ НАСТРОЙКИ СЕКЛОТО) ----------
@router.callback_query(F.data == "settings_lottery")
async def settings_lottery(callback: CallbackQuery):
    await callback.answer(
        "Настройки Секслото убраны из админки: расписание и длительность теперь зафиксированы в коде.",
        show_alert=True,
    )
    await admin_bot_settings(callback)


# ---------- ЕЖЕНЕДЕЛЬНЫЙ ПРОМОКОД ----------
@router.callback_query(F.data == "settings_weekly_promo")
async def settings_weekly_promo(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        from app.services import get_setting
        wd = await get_setting(session, "weekly_promo_day", "")
        wh = await get_setting(session, "weekly_promo_hour", "")
        wa = await get_setting(session, "weekly_promo_amount", "")
    from app.config import WEEKLY_PROMO_DAY, WEEKLY_PROMO_HOUR, WEEKLY_PROMO_AMOUNT
    def v(db_val, default):
        return f"{db_val or default}"
    day_names = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]
    current_day = int(wd) if str(wd).isdigit() else WEEKLY_PROMO_DAY

    text = (
        "🎁 <b>Настройки Еженедельного Промокода</b>\n\n"
        f"<b>День недели:</b> {day_names[current_day] if 0 <= current_day < 7 else current_day}\n"
        f"<b>Час по UTC (0-23):</b> {v(wh, WEEKLY_PROMO_HOUR)}\n"
        f"<b>Сумма монет:</b> {v(wa, WEEKLY_PROMO_AMOUNT)}\n"
        f"<b>Кол-во активаций:</b> ∞\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Выбрать день недели", callback_data="settings_edit:weekly_promo_day")],
        [InlineKeyboardButton(text="✏️ Час по UTC", callback_data="settings_edit:weekly_promo_hour")],
        [InlineKeyboardButton(text="✏️ Сумма", callback_data="settings_edit:weekly_promo_amount")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_bot_settings")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------- ПРИВЕТСТВИЕ И БАННЕР ----------
@router.callback_query(F.data == "settings_welcome")
async def settings_welcome(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        from app.services import get_setting
        welcome_text = await get_setting(session, "welcome_text", "")
        welcome_banner_id = await get_setting(session, "welcome_banner_id", "")
    text = (
        "🖼 <b>Приветствие и баннер</b>\n\n"
        f"<b>Текст:</b>\n{escape(welcome_text) if welcome_text else '<i>(Не задан, используется стандартный)</i>'}\n\n"
        f"<b>Баннер установлен:</b> {'✅ Да' if welcome_banner_id else '❌ Нет (или локальный app/banner.jpg)'}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить текст приветствия", callback_data="admin_set_welcome_text")],
        [InlineKeyboardButton(text="🖼 Изменить картинку (баннер)", callback_data="admin_set_welcome_banner")],
        [InlineKeyboardButton(text="🗑 Сбросить баннер", callback_data="admin_reset_welcome_banner")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_bot_settings")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------- ADMIN FREE ----------
@router.callback_query(F.data == "settings_admin_free")
async def settings_admin_free(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        from app.services import get_setting
        val = await get_setting(session, "admin_free_enabled", "false")
    status = "🟢 ВКЛЮЧЕНО (админы покупают всё бесплатно)" if val.lower() == "true" else "🔴 ВЫКЛЮЧЕНО"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔘 " + ("Отключить" if val.lower() == "true" else "Включить"), callback_data="toggle_admin_free")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_bot_settings")],
    ])
    await _safe_edit(callback, f"🆓 <b>ADMIN FREE</b>\n\n{status}", parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------- ПОКАЗАТЬ ВСЕ НАСТРОЙКИ ----------
@router.callback_query(F.data == "settings_show_all")
async def settings_show_all(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        from app.models import BotSetting
        result = await session.execute(select(BotSetting).order_by(BotSetting.key))
        settings = result.scalars().all()
    if not settings:
        text = "📊 <b>Все настройки</b>\n\nНет пользовательских настроек. Используются значения из config.py."
    else:
        text = "📊 <b>Все пользовательские настройки</b>\n\n"
        for s in settings:
            text += f"• <code>{s.key}</code> = <b>{s.value}</b>\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Сбросить все", callback_data="settings_reset_all")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_bot_settings")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------- СБРОСИТЬ ВСЕ НАСТРОЙКИ ----------
@router.callback_query(F.data == "settings_reset_all")
async def settings_reset_all(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, сбросить", callback_data="settings_reset_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_bot_settings")],
    ])
    await _safe_edit(callback, "⚠️ <b>Вы уверены?</b>\n\nЭто удалит все пользовательские настройки бота. Значения вернутся к дефолтным из config.py.", parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "settings_reset_confirm")
async def settings_reset_confirm(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        from sqlalchemy import delete
        from app.models import BotSetting
        await session.execute(delete(BotSetting))
        await session.commit()
    await callback.answer("✅ Все настройки сброшены!", show_alert=True)
    await admin_bot_settings(callback)


# ---------- РЕДАКТИРОВАНИЕ НАСТРОЕК ----------
@router.callback_query(F.data.startswith("settings_edit:"))
async def settings_edit_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    key = callback.data.split(":", 1)[1]
    await state.update_data(settings_key=key)
    
    if key == "weekly_promo_day":
        days = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]
        kb_rows = [
            [
                InlineKeyboardButton(text=days[0], callback_data="settings_set_day:0"),
                InlineKeyboardButton(text=days[1], callback_data="settings_set_day:1"),
                InlineKeyboardButton(text=days[2], callback_data="settings_set_day:2"),
                InlineKeyboardButton(text=days[3], callback_data="settings_set_day:3"),
            ],
            [
                InlineKeyboardButton(text=days[4], callback_data="settings_set_day:4"),
                InlineKeyboardButton(text=days[5], callback_data="settings_set_day:5"),
                InlineKeyboardButton(text=days[6], callback_data="settings_set_day:6"),
            ],
            [InlineKeyboardButton(text="Отмена", callback_data="admin_bot_settings")],
        ]
        await callback.message.answer("📅 <b>Выберите день недели для рассылки промокода:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
        await callback.answer()
        return

    await state.set_state(BotSettingsState.waiting_value)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="admin_bot_settings")]])
    await callback.message.answer(
        f"✏️ Введите новое значение для <code>{key}</code>:\n\n"
        f"Для сброса к дефолту отправьте <code>-</code> (дефис).",
        parse_mode="HTML",
        reply_markup=kb,
    )
    await callback.answer()

@router.callback_query(F.data.startswith("settings_set_day:"))
async def settings_set_day(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    day_val = callback.data.split(":")[1]
    day_names = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]

    data = await state.get_data()
    key = data.get("settings_key", "weekly_promo_day")

    async with async_session() as session:
        from app.services import set_setting
        await set_setting(session, key, day_val)
        await session.commit()

    label = day_names[int(day_val)] if day_val.isdigit() and 0 <= int(day_val) < 7 else day_val
    await callback.message.answer(f"✅ Настройка {key} успешно изменена: {label}!")
    await callback.answer()



@router.message(BotSettingsState.waiting_value)
async def settings_edit_save(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    data = await state.get_data()
    key = data.get("settings_key", "")
    value = message.text.strip()
    
    async with async_session() as session:
        from app.services import set_setting
        if value == "-":
            # Удаляем настройку — вернётся к дефолту
            from sqlalchemy import delete
            from app.models import BotSetting
            await session.execute(delete(BotSetting).where(BotSetting.key == key))
            await session.commit()
            await message.answer(f"✅ Настройка <code>{key}</code> сброшена к дефолтному значению.", parse_mode="HTML")
        else:
            await set_setting(session, key, value)
            await message.answer(f"✅ Настройка <code>{key}</code> = <b>{value}</b>", parse_mode="HTML")
    await state.clear()


# ---------- ПЕРЕКЛЮЧАТЕЛИ ----------
@router.callback_query(F.data.startswith("settings_toggle:"))
async def settings_toggle(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    key = callback.data.split(":", 1)[1]
    async with async_session() as session:
        from app.services import get_setting, set_setting
        current = await get_setting(session, key, "on")
        new_val = "off" if current.lower() == "on" else "on"
        await set_setting(session, key, new_val)
    status = "включён" if new_val == "on" else "отключён"
    await callback.answer(f"✅ {key} {status}!", show_alert=True)
    # Перезапускаем текущее меню
    if key in ("enable_lottery", "enable_lootboxes"):
        await settings_games(callback)
    else:
        await admin_bot_settings(callback)


# ---------- СТАРЫЕ ОБРАБОТЧИКИ БАННЕРА ----------
@router.callback_query(F.data == "admin_set_welcome_text")
async def admin_set_welcome_text_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(BotSettingsState.waiting_welcome_text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="settings_welcome")]])
    await _safe_edit(
        callback,
        "Введите новый текст приветствия.\n"
        "Можно использовать HTML теги.\n"
        "Для сброса текста отправьте <code>-</code> (дефис).",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


@router.message(BotSettingsState.waiting_welcome_text)
async def admin_set_welcome_text_finish(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    text = message.html_text.strip()
    if text == "-":
        text = ""
    
    async with async_session() as session:
        from app.services import set_setting
        await set_setting(session, "welcome_text", text)
    
    await message.answer("✅ Текст приветствия успешно обновлен!")
    await state.clear()


@router.callback_query(F.data == "admin_set_welcome_banner")
async def admin_set_welcome_banner_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(BotSettingsState.waiting_welcome_banner)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="settings_welcome")]])
    await _safe_edit(
        callback,
        "Отправьте новую картинку (фото), которая будет использоваться как приветственный баннер.",
        reply_markup=kb
    )
    await callback.answer()


@router.message(BotSettingsState.waiting_welcome_banner, F.photo)
async def admin_set_welcome_banner_finish(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    photo_id = message.photo[-1].file_id
    
    async with async_session() as session:
        from app.services import set_setting
        await set_setting(session, "welcome_banner_id", photo_id)
        
    await message.answer("✅ Приветственный баннер успешно обновлен!")
    await state.clear()


@router.callback_query(F.data == "admin_reset_welcome_banner")
async def admin_reset_welcome_banner(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    
    async with async_session() as session:
        from app.services import set_setting
        await set_setting(session, "welcome_banner_id", "")
        
    await callback.answer("✅ Баннер сброшен! Теперь используется стандартный app/banner.jpg", show_alert=True)
    await settings_welcome(callback)


# ============================
# АВТО-МОДЕРАЦИЯ И ДОВЕРЕННЫЕ АВТОРЫ
# ============================
@router.callback_query(F.data == "admin_auto_moderation")
async def admin_auto_moderation(callback: CallbackQuery):
    """Показать статистику авто-модерации и переключатель"""
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    async with async_session() as session:
        from app.services import get_setting
        db_val = await get_setting(session, "auto_moderation_enabled", "")
        if db_val:
            is_enabled = db_val.lower() == "true"
        else:
            is_enabled = ENABLE_AUTO_MODERATION

        trusted_count = (await session.execute(
            select(func.count(TrustedUploader.id))
        )).scalar_one()
        # Auto-approved is no longer marked by rejection_reason; use 0 or join via UserActionLog if needed
        auto_approved_count = 0

    status_icon = "🟢" if is_enabled else "🔴"
    status_text = "включена" if is_enabled else "отключена"

    text = (
        f"⚡ <b>Авто-модерация</b>\n\n"
        f"Статус: {status_icon} {status_text}\n"
        f"Доверенных авторов: {trusted_count}\n"
        f"Авто-одобрено видео: {auto_approved_count}\n\n"
        f"Доверенные авторы загружают контент без премодерации.\n"
        f"Управляйте списком в разделе «🤝 Доверенные авторы»."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🔘 " + ("Отключить" if is_enabled else "Включить"),
            callback_data="toggle_auto_mod"
        )],
        [InlineKeyboardButton(text="🤝 Доверенные авторы", callback_data="admin_trusted_uploaders")],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "toggle_auto_mod")
async def toggle_auto_moderation(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    async with async_session() as session:
        from app.services import get_setting, set_setting
        current = await get_setting(session, "auto_moderation_enabled", "")
        # Если пусто — берём из ENV
        if current:
            new_val = "false" if current.lower() == "true" else "true"
        else:
            new_val = "false" if ENABLE_AUTO_MODERATION else "true"
        await set_setting(session, "auto_moderation_enabled", new_val)

    status = "включена" if new_val == "true" else "отключена"
    await callback.answer(f"⚡ Авто-модерация {status}!", show_alert=True)
    await admin_auto_moderation(callback)


@router.callback_query(F.data == "toggle_admin_free")
async def toggle_admin_free(callback: CallbackQuery):
    """Переключить ADMIN FREE — админы покупают всё бесплатно"""
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    async with async_session() as session:
        from app.services import get_setting, set_setting
        current = await get_setting(session, "admin_free_enabled", "false")
        new_val = "true" if current.lower() != "true" else "false"
        await set_setting(session, "admin_free_enabled", new_val)

    status = "включён" if new_val == "true" else "отключён"
    await callback.answer(f"🆓 ADMIN FREE {status}!", show_alert=True)
    await admin_bot_settings(callback)


@router.callback_query(F.data == "admin_trusted_uploaders")
async def admin_trusted_uploaders(callback: CallbackQuery):
    """Список доверенных авторов + возможность добавить/удалить"""
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    async with async_session() as session:
        trusted_rows = (await session.execute(
            select(TrustedUploader, User)
            .join(User, TrustedUploader.trusted_user_id == User.id)
            .order_by(TrustedUploader.created_at.desc())
        )).all()

        admin_ids = {tu.admin_user_id for tu, _ in trusted_rows}
        admin_map = {}
        if admin_ids:
            admins = (await session.execute(
                select(User).where(User.id.in_(admin_ids))
            )).scalars().all()
            admin_map = {admin.id: admin for admin in admins}

    if not trusted_rows:
        text = "🤝 <b>Доверенные авторы</b>\n\nНет доверенных авторов.\n\nДобавьте автора по ID или @username:"
    else:
        text = "🤝 <b>Доверенные авторы</b>\n\n"
        for tu, user_obj in trusted_rows:
            admin_obj = admin_map.get(tu.admin_user_id)
            admin_name = get_display_name(admin_obj) if admin_obj else "?"
            text += f"• {get_display_name(user_obj)} (добавил {admin_name})\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить автора", callback_data="trusted_add_start")],
        [InlineKeyboardButton(text="➖ Удалить автора", callback_data="trusted_remove_start")],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "trusted_add_start")
async def trusted_add_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(TrustedUploaderState.waiting_add)
    await callback.message.answer(
        "🤝 <b>Добавить доверенного автора</b>\n\n"
        "Введите ID пользователя или @username:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="admin_trusted_uploaders")]
        ])
    )
    await callback.answer()


@router.message(TrustedUploaderState.waiting_add)
async def trusted_add_process(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return

    query = message.text.strip()
    async with async_session() as session:
        if query.isdigit():
            # Здесь ожидается Telegram ID, а не внутренний users.id.
            user = await get_user(session, int(query))
        else:
            if query.startswith("@"):
                query = query[1:]
            user = await get_user_by_username(session, query)

        if not user:
            await message.answer("❌ Пользователь не найден.")
            await state.clear()
            return

        # Проверяем, не добавлен ли уже
        existing = (await session.execute(
            select(TrustedUploader).where(
                TrustedUploader.trusted_user_id == user.id
            )
        )).scalar_one_or_none()

        if existing:
            await message.answer(f"⚠️ {get_display_name(user)} уже в списке доверенных.")
            await state.clear()
            return

        admin_user = await get_user(session, message.from_user.id)
        session.add(TrustedUploader(
            admin_user_id=admin_user.id,
            trusted_user_id=user.id,
        ))
        await session.commit()

    await message.answer(f"✅ {get_display_name(user)} добавлен как доверенный автор!\nТеперь его видео одобряются автоматически.")
    await state.clear()


@router.callback_query(F.data == "trusted_remove_start")
async def trusted_remove_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(TrustedUploaderState.waiting_remove)
    await callback.message.answer(
        "➖ <b>Удалить доверенного автора</b>\n\n"
        "Введите ID пользователя или @username:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="admin_trusted_uploaders")]
        ])
    )
    await callback.answer()


@router.message(TrustedUploaderState.waiting_remove)
async def trusted_remove_process(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return

    query = message.text.strip()
    async with async_session() as session:
        if query.isdigit():
            # Здесь ожидается Telegram ID, а не внутренний users.id.
            user = await get_user(session, int(query))
        else:
            if query.startswith("@"):
                query = query[1:]
            user = await get_user_by_username(session, query)

        if not user:
            await message.answer("❌ Пользователь не найден.")
            await state.clear()
            return

        result = await session.execute(
            select(TrustedUploader).where(
                TrustedUploader.trusted_user_id == user.id
            )
        )
        trusted = result.scalar_one_or_none()

        if not trusted:
            await message.answer(f"⚠️ {get_display_name(user)} не в списке доверенных.")
            await state.clear()
            return

        await session.delete(trusted)
        await session.commit()

    await message.answer(f"✅ {get_display_name(user)} удалён из списка доверенных авторов.")
    await state.clear()


# ============================
# ДОСРОЧНАЯ ОСТАНОВКА СОБЫТИЙ
# ============================
@router.callback_query(F.data == "admin_events_list_full")
async def admin_events_list_full(callback: CallbackQuery):
    """Полный список событий с кнопками остановки."""
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        events = (await session.execute(
            select(Event).order_by(Event.created_at.desc()).limit(20)
        )).scalars().all()

    if not events:
        await callback.message.answer("Нет событий.")
        await callback.answer()
        return

    for ev in events:
        status = "🟢 Активно" if ev.is_active and ev.end_date > utc_now() else "🔴 Завершено"
        text = (
            f"🎉 <b>{escape(ev.name)}</b>\n"
            f"Скидка: {ev.discount_percent}% | {status}\n"
            f"До: {ev.end_date.strftime('%d.%m.%Y %H:%M')}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[])
        if ev.is_active and ev.end_date > utc_now():
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🛑 Остановить", callback_data=f"event_stop:{ev.id}")],
            ])
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("event_stop:"))
async def event_stop(callback: CallbackQuery):
    """Досрочно остановить событие."""
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    event_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        ev = (await session.execute(
            select(Event).where(Event.id == event_id)
        )).scalar_one_or_none()
        if not ev:
            await callback.answer("Событие не найдено.", show_alert=True)
            return
        ev.is_active = False
        ev.end_date = utc_now()
        await session.commit()
    await callback.message.edit_text(
        f"🛑 Событие «{escape(ev.name)}» остановлено.",
        parse_mode="HTML",
    )
    await callback.answer("Остановлено!")


# ============================
# ДОСРОЧНАЯ ОСТАНОВКА АКЦИЙ
# ============================
@router.callback_query(F.data == "admin_sales_list_full")
async def admin_sales_list_full(callback: CallbackQuery):
    """Полный список акций с кнопками остановки."""
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        sales = (await session.execute(
            select(ActiveSale).order_by(ActiveSale.id.desc()).limit(20)
        )).scalars().all()

    if not sales:
        await callback.message.answer("Нет акций.")
        await callback.answer()
        return

    for sale in sales:
        status = "🟢 Активна" if sale.end_date > utc_now() else "🔴 Завершена"
        text = (
            f"🛍 <b>Акция #{sale.id}</b>\n"
            f"Скидка: {sale.discount_percent}% на {sale.applies_to} | {status}\n"
            f"До: {sale.end_date.strftime('%d.%m.%Y %H:%M')}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[])
        if sale.end_date > utc_now():
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🛑 Остановить", callback_data=f"sale_stop:{sale.id}")],
            ])
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("sale_stop:"))
async def sale_stop_force(callback: CallbackQuery):
    """Досрочно остановить акцию."""
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    sale_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        sale = (await session.execute(
            select(ActiveSale).where(ActiveSale.id == sale_id)
        )).scalar_one_or_none()
        if not sale:
            await callback.answer("Акция не найдена.", show_alert=True)
            return
        sale.end_date = utc_now()
        await session.commit()
    await callback.message.edit_text(
        f"🛑 Акция #{sale_id} остановлена.",
        parse_mode="HTML",
    )
    await callback.answer("Остановлена!")


# ============================
# ОДОБРИТЬ ВСЁ (APPROVE ALL)
# ============================
@router.callback_query(F.data == "admin_approve_all")
async def admin_approve_all(callback: CallbackQuery):
    """Показать подтверждение одобрения всех pending-видео."""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Только супер-админ.", show_alert=True)
        return
    async with async_session() as session:
        pending_count = await count_pending_videos(session)

    if pending_count == 0:
        await callback.message.answer("✅ Очередь пуста — нечего одобрять.")
        await callback.answer()
        return

    await callback.message.answer(
        f"⚠️ <b>Одобрить ВСЕ видео?</b>\n\n"
        f"В очереди: <b>{pending_count}</b> файлов.\n"
        f"Все будут одобрены, загрузчики получат награды.\n"
        f"Действие необратимо.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, одобрить всё", callback_data="admin_approve_all_confirm"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="admin_center"),
            ],
        ]),
    )
    await callback.answer()


async def approve_all_pending_background_task(admin_chat_id: int, admin_user_id: int, bot):
    import asyncio
    from app.db import async_session
    
    total_approved = 0
    BATCH_SIZE = 50
    
    while True:
        try:
            async with async_session() as session:
                count = await approve_all_pending(session, admin_user_id, limit=BATCH_SIZE)
                total_approved += count
                if count < BATCH_SIZE:
                    break
            await asyncio.sleep(0.5)
        except Exception as e:
            try:
                await bot.send_message(
                    admin_chat_id,
                    f"⚠️ <b>Произошла ошибка во время фонового одобрения:</b> {e}\n"
                    f"Одобрено файлов на момент сбоя: <b>{total_approved}</b>",
                    parse_mode="HTML"
                )
            except Exception:
                pass
            return
            
    try:
        await bot.send_message(
            admin_chat_id,
            f"🎉 <b>Фоновое одобрение успешно завершено!</b>\n\n"
            f"Всего одобрено файлов: <b>{total_approved}</b>.\n"
            f"Награды начислены всем загрузчикам.",
            parse_mode="HTML"
        )
    except Exception:
        pass


@router.callback_query(F.data == "admin_approve_all_confirm")
async def admin_approve_all_confirm(callback: CallbackQuery, bot):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Только супер-админ.", show_alert=True)
        return
    
    async with async_session() as session:
        admin = await get_user(session, callback.from_user.id)
        admin_id = admin.id if admin else 0
        total_pending = await count_pending_videos(session)
        
    if total_pending == 0:
        await callback.message.edit_text("Очередь модерации пуста!")
        await callback.answer("Очередь пуста!")
        return
        
    await callback.message.edit_text(
        f"⏳ <b>Запущено фоновое одобрение!</b>\n\n"
        f"Бот начал обрабатывать <b>{total_pending}</b> файлов в фоновом режиме.\n"
        f"Вы можете закрыть бота и заниматься своими делами. По завершении вы получите личное сообщение от бота! 🚀",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В админку", callback_data="admin_center")]
        ])
    )
    await callback.answer("Фоновое одобрение запущено!")
    
    asyncio.create_task(
        approve_all_pending_background_task(
            admin_chat_id=callback.message.chat.id,
            admin_user_id=admin_id,
            bot=bot
        )
    )


# ============================
# ЖАЛОБЫ НА ВИДЕО
# ============================
@router.callback_query(F.data == "admin_reports")
async def admin_reports_menu(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        reports = await get_pending_reports(session, limit=20)

    if not reports:
        await callback.message.answer(
            "✅ Нет жалоб на рассмотрении.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_center")],
            ]),
        )
        await callback.answer()
        return

    text = "🚨 <b>Жалобы на контент</b>\n\n"
    for r in reports[:10]:
        reason_label = REPORT_REASONS.get(r.reason, r.reason)
        text += (
            f"#{r.id} | {reason_label}\n"
            f"  Видео #{r.video_id} | От user_id={r.reporter_user_id}\n"
        )
        if r.comment:
            text += f"  💬 {escape(r.comment[:80])}\n"
        text += "\n"

    # Кнопки для каждой жалобы
    kb_rows = []
    for r in reports[:10]:
        reason_label = REPORT_REASONS.get(r.reason, r.reason)
        kb_rows.append([
            InlineKeyboardButton(
                text=f"✅ Отклонить #{r.id}",
                callback_data=f"report_dismiss:{r.id}",
            ),
            InlineKeyboardButton(
                text=f"🗑 Удалить видео #{r.video_id}",
                callback_data=f"report_remove_video:{r.id}:{r.video_id}",
            ),
        ])
    kb_rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_center")])

    await callback.message.answer(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("report_dismiss:"))
async def report_dismiss(callback: CallbackQuery):
    """Отклонить жалобу (оставить видео)."""
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    report_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        admin = await get_user(session, callback.from_user.id)
        ok = await dismiss_report(session, report_id, admin.id if admin else 0)
    if ok:
        await callback.answer("Жалоба отклонена ✅")
    else:
        await callback.answer("Жалоба не найдена.", show_alert=True)


@router.callback_query(F.data.startswith("report_remove_video:"))
async def report_remove_video(callback: CallbackQuery):
    """Удалить видео по жалобе и закрыть жалобу."""
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Неверный формат.", show_alert=True)
        return
    report_id = int(parts[1])
    video_id = int(parts[2])
    async with async_session() as session:
        admin = await get_user(session, callback.from_user.id)
        # Удаляем видео (помечаем как rejected)
        v = (await session.execute(
            select(Video).where(Video.id == video_id)
        )).scalar_one_or_none()
        if v:
            v.status = "rejected"
            v.rejection_reason = "removed_by_report"
        # Закрываем ВСЕ pending-жалобы на это видео
        pending_reports = (await session.execute(
            select(VideoReport).where(
                VideoReport.video_id == video_id,
                VideoReport.status == "pending",
            )
        )).scalars().all()
        for r in pending_reports:
            r.status = "reviewed"
            r.reviewed_by = admin.id if admin else 0
        await session.commit()
    await callback.answer(f"Видео #{video_id} удалено, жалобы закрыты 🗑", show_alert=True)


# ====================================================
# УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ (👑 Только Super-Admin)
# ====================================================
@router.callback_query(F.data == "admin_manage_admins")
async def cb_admin_manage_admins(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Только для супер-админов.", show_alert=True)
        return
        
    async with async_session() as session:
        admins = (await session.execute(select(User).where(User.is_admin == True))).scalars().all()
        
    text = "👑 <b>Управление администраторами</b>\n\n"
    if not admins:
        text += "В базе данных нет администраторов. Только супер-админы из .env."
    else:
        text += "Список администраторов в базе данных:\n"
        for i, adm in enumerate(admins, 1):
            name = adm.display_name or adm.username or f"ID {adm.telegram_id}"
            text += f"{i}. {name} (ID: <code>{adm.telegram_id}</code>)\n"
            
    kb_rows = []
    kb_rows.append([InlineKeyboardButton(text="➕ Назначить админа", callback_data="admin_add_admin_start")])
    
    for adm in admins:
        name = adm.display_name or adm.username or f"ID {adm.telegram_id}"
        kb_rows.append([InlineKeyboardButton(text=f"❌ Снять: {name[:20]}", callback_data=f"admin_remove_admin:{adm.telegram_id}")])
        
    kb_rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_center")])
    
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await callback.answer()


@router.callback_query(F.data == "admin_add_admin_start")
async def cb_admin_add_admin_start(callback: CallbackQuery, state: FSMContext):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Только для супер-админов.", show_alert=True)
        return
        
    await state.set_state(AdminManageState.waiting_new_admin)
    await _safe_edit(
        callback,
        "✏️ <b>Назначение администратора</b>\n\n"
        "Отправьте мне <b>Telegram ID</b> пользователя, которого хотите назначить администратором в боте.\n\n"
        "<i>Пользователь должен хотя бы раз запустить бота перед этим, чтобы запись о нём была в базе данных.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_manage_admins")]
        ])
    )
    await callback.answer()


@router.message(AdminManageState.waiting_new_admin)
async def process_add_admin(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        return
        
    text_val = (message.text or "").strip()
    if not text_val.isdigit():
        await message.answer("❌ Telegram ID должен состоять только из цифр. Пожалуйста, попробуйте снова или отправьте команду отмены.")
        return
        
    tid = int(text_val)
    async with async_session() as session:
        user = await get_user(session, tid)
        if not user:
            await message.answer(
                f"❌ Пользователь с Telegram ID <code>{tid}</code> не найден в базе данных.\n"
                f"Убедитесь, что он запустил бота и создал профиль.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ К админам", callback_data="admin_manage_admins")]
                ])
            )
            return
            
        if user.is_admin:
            await message.answer(
                f"ℹ️ Пользователь <b>{user.display_name or user.username or tid}</b> уже является администратором.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ К админам", callback_data="admin_manage_admins")]
                ])
            )
            await state.clear()
            return
            
        user.is_admin = True
        await session.commit()
        
    await message.answer(
        f"✅ Пользователь <b>{user.display_name or user.username or tid}</b> успешно назначен администратором!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ К админам", callback_data="admin_manage_admins")]
        ])
    )
    await state.clear()


@router.callback_query(F.data.startswith("admin_remove_admin:"))
async def cb_admin_remove_admin(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Только для супер-админов.", show_alert=True)
        return
        
    tid = int(callback.data.split(":", 1)[1])
    async with async_session() as session:
        user = await get_user(session, tid)
        if user:
            user.is_admin = False
            await session.commit()
            await callback.answer(f"Администратор {user.display_name or tid} удален.")
        else:
            await callback.answer("Пользователь не найден.")
            
    await cb_admin_manage_admins(callback)


# ====================================================
# СОЗДАНИЕ ОФФЕРОВ (FSM)
# ====================================================
@router.callback_query(F.data == "admin_create_offer")
async def cb_admin_create_offer_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
        
    await state.set_state(AdminOfferCreateState.waiting_title)
    
    text = (
        "📝 <b>Создание оффера (Шаг 1/6)</b>\n\n"
        "⚠️ <b>Важно:</b> можно рекламировать каналы, группы, чаты и ботов Telegram.\n"
        "• публичные каналы / группы / чаты с username бот может проверять автоматически\n"
        "• для ботов, приватных инвайтов и некоторых ссылок авто-проверка недоступна — там подтверждение будет ручным\n"
        "• серые, мутные и запрещённые проекты не допускаются\n\n"
        "Введите <b>название оффера</b> (например, <i>Подписка на игровой канал</i>):"
    )
    
    await _safe_edit(
        callback,
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_offers_menu")]
        ])
    )
    await callback.answer()


@router.message(AdminOfferCreateState.waiting_title)
async def process_offer_title(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    title = (message.text or "").strip()
    if not title:
        await message.answer("❌ Название не должно быть пустым. Введите название:")
        return
        
    await state.update_data(title=title)
    await state.set_state(AdminOfferCreateState.waiting_description)
    await message.answer(
        "📝 <b>Создание оффера (Шаг 2/6)</b>\n\n"
        "Введите <b>описание оффера</b> (что нужно сделать пользователю):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_offers_menu")]
        ])
    )


@router.message(AdminOfferCreateState.waiting_description)
async def process_offer_description(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    description = (message.text or "").strip()
    if not description:
        await message.answer("❌ Описание не должно быть пустым. Введите описание:")
        return
        
    await state.update_data(description=description)
    await state.set_state(AdminOfferCreateState.waiting_url)
    await message.answer(
        "🔗 <b>Создание оффера (Шаг 3/6)</b>\n\n"
        "Введите <b>ссылку на Telegram-проект</b> — канал, группу, чат или бота\n"
        "(например, <code>https://t.me/my_channel</code>, <code>https://t.me/MyBot?start=promo</code>, <code>https://t.me/+invite</code>):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_offers_menu")]
        ])
    )


@router.message(AdminOfferCreateState.waiting_url)
async def process_offer_url(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    url = (message.text or "").strip()
    if not url or ("t.me/" not in url and not url.startswith("@")):
        await message.answer("❌ Ссылка должна вести на Telegram-проект: канал, группу, чат или бота. Используйте t.me/... или @username")
        return
        
    await state.update_data(channel_url=url)
    await state.set_state(AdminOfferCreateState.waiting_reward_preview)
    await message.answer(
        "💰 <b>Создание оффера (Шаг 4/6)</b>\n\n"
        "Введите <b>награду за старт</b> (число монет, например, <code>50</code>):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_offers_menu")]
        ])
    )


@router.message(AdminOfferCreateState.waiting_reward_preview)
async def process_offer_reward_preview(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    val = (message.text or "").strip().replace(",", ".")
    try:
        reward = Decimal(val)
        if reward < 0: raise ValueError()
    except Exception:
        await message.answer("❌ Некорректное число монет. Введите положительное число:")
        return
        
    await state.update_data(reward_preview=str(reward))
    await state.set_state(AdminOfferCreateState.waiting_reward_final)
    await message.answer(
        "💰 <b>Создание оффера (Шаг 5/6)</b>\n\n"
        "Введите <b>награду за финальную подписку</b> (число монет, например, <code>350</code>):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_offers_menu")]
        ])
    )


@router.message(AdminOfferCreateState.waiting_reward_final)
async def process_offer_reward_final(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    val = (message.text or "").strip().replace(",", ".")
    try:
        reward = Decimal(val)
        if reward < 0: raise ValueError()
    except Exception:
        await message.answer("❌ Некорректное число монет. Введите положительное число:")
        return
        
    await state.update_data(reward_final=str(reward))
    await state.set_state(AdminOfferCreateState.waiting_penalty)
    await message.answer(
        "💰 <b>Создание оффера (Шаг 6/9)</b>\n\n"
        "Введите <b>штраф за отписку</b> (сколько монет спишется дополнительно, если пользователь отпишется):\n"
        "<i>Рекомендуется: сумма, превышающая награду, чтобы отписка была невыгодной.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_offers_menu")]
        ])
    )


@router.message(AdminOfferCreateState.waiting_penalty)
async def process_offer_penalty(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    val = (message.text or "").strip().replace(",", ".")
    try:
        penalty = Decimal(val)
        if penalty < 0: raise ValueError()
    except Exception:
        await message.answer("❌ Некорректное число монет. Введите положительное число:")
        return
        
    await state.update_data(penalty_unsubscribe=str(penalty))
    await state.set_state(AdminOfferCreateState.waiting_rentable)
    await message.answer(
        "📣 <b>Создание оффера (Шаг 7/9)</b>\n\n"
        "Будет ли этот оффер доступен для <b>аренды</b> обычными пользователями?\n"
        "Если да, любой пользователь сможет заплатить, чтобы рекламировать свой канал в этом оффере.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да", callback_data="offer_rent_yes")],
            [InlineKeyboardButton(text="❌ Нет", callback_data="offer_rent_no")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_offers_menu")]
        ])
    )


@router.callback_query(AdminOfferCreateState.waiting_rentable, F.data == "offer_rent_yes")
async def process_offer_rentable_yes(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    await state.update_data(is_rentable=True)
    await state.set_state(AdminOfferCreateState.waiting_rent_cost)
    await callback.message.answer(
        "💰 <b>Создание оффера (Шаг 8/9)</b>\n\n"
        "Введите <b>стоимость аренды одного слота в день</b> (монеты):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_offers_menu")]
        ])
    )
    await callback.answer()


@router.callback_query(AdminOfferCreateState.waiting_rentable, F.data == "offer_rent_no")
async def process_offer_rentable_no(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    await state.update_data(is_rentable=False, rent_cost=0, max_rentals=1)
    await finalize_admin_offer(callback, state)
    await callback.answer()


async def finalize_admin_offer(callback_or_message, state: FSMContext):
    data = await state.get_data()
    async with async_session() as session:
        from app.services import admin_create_offer
        offer = await admin_create_offer(
            session,
            title=data["title"],
            description=data["description"],
            channel_url=data["channel_url"],
            reward_preview=Decimal(data["reward_preview"]),
            reward_final=Decimal(data["reward_final"]),
            penalty_unsubscribe=Decimal(data.get("penalty_unsubscribe", 0)),
            is_rentable=data.get("is_rentable", False),
            rent_cost_per_day=Decimal(data.get("rent_cost", 0)),
            max_simultaneous_rentals=int(data.get("max_rentals", 1)),
        )
        await session.commit()
        
    text = (
        f"🎉 <b>Оффер успешно создан!</b>\n\n"
        f"• Название: <b>{offer.title}</b>\n"
        f"• Награды: {offer.reward_preview} + {offer.reward_final} монет\n"
        f"• Штраф отписки: {offer.penalty_unsubscribe} монет\n"
        f"• Ссылка: {offer.channel_url}"
    )
    
    if isinstance(callback_or_message, CallbackQuery):
        await callback_or_message.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ К офферам", callback_data="admin_offers_menu")]
            ])
        )
    else:
        await callback_or_message.answer(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ К офферам", callback_data="admin_offers_menu")]
            ])
        )
    await state.clear()


@router.message(AdminOfferCreateState.waiting_rent_cost)
async def process_offer_rent_cost(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    val = (message.text or "").strip().replace(",", ".")
    try:
        cost = Decimal(val)
        if cost < 0: raise ValueError()
    except Exception:
        await message.answer("❌ Некорректное число монет. Введите положительное число:")
        return
        
    await state.update_data(rent_cost=str(cost))
    await state.set_state(AdminOfferCreateState.waiting_max_rentals)
    await message.answer(
        "🔢 <b>Создание оффера (Шаг 9/9)</b>\n\n"
        "Введите <b>максимальное количество рекламных слотов</b> (сколько каналов может рекламироваться одновременно):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_offers_menu")]
        ])
    )


@router.message(AdminOfferCreateState.waiting_max_rentals)
async def process_offer_max_rentals(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    if not message.text or not message.text.isdigit():
        await message.answer("❌ Введите целое число слотов:")
        return

    await state.update_data(max_rentals=int(message.text))
    await finalize_admin_offer(message, state)


# Remove the process_offer_penalty_unsubscribe function completely
