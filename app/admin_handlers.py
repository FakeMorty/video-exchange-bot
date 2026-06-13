from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
import os
import asyncio
from html import escape

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from sqlalchemy import select, func, desc, text


from app.config import ADMINS, OFFER_DEFAULT_RENT_COST_PER_DAY, ENABLE_ADMIN_BROADCAST
from app.db import async_session
from app.models import (
    Base,
    User, Video, Offer, BalanceLog, GameHistory,
    TrustedUploader, ActiveSale, Event, OfferParticipation
)
from app.services import (
    get_user, get_user_by_id, get_user_by_username,
    get_user_dossier, update_user_balance, set_user_ban_status,
    count_pending_videos, count_approved_videos, count_rejected_videos,
    get_next_pending_video, approve_video, reject_video,
    get_admin_extended_stats, get_display_name,
    get_user_by_display_name, admin_create_offer,
    count_active_rentals, expire_old_rentals, log_user_action,
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
    waiting_image = State()
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

    kind_name = {
        "bug": "🐞 Баг",
        "suggestion": "💡 Идея",
        "praise": "❤️ Благодарность",
    }
    text_out = "💬 <b>Последние обращения пользователей</b>\n\n"
    for item in feedback_items:
        preview = (item.text or "").strip().replace("\n", " ")
        if len(preview) > 140:
            preview = preview[:140] + "..."
        text_out += (
            f"#{item.id} {kind_name.get(item.kind, item.kind)}\n"
            f"user_id={item.user_id} | {item.created_at.strftime('%d.%m %H:%M')}\n"
            f"{preview}\n\n"
        )

    if len(text_out) > 3900:
        text_out = text_out[:3900] + "\n..."

    await callback.message.answer(
        text_out,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_feedback_menu")],
            [InlineKeyboardButton(text="◀ К панели", callback_data="admin_center")],
        ]),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_db_menu")
async def admin_db_menu(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer()
        return

    table_labels: dict[str, str] = {
        "users": "Пользователи",
        "videos": "Контент (видео/фото)",
        "video_views": "Просмотры",
        "video_ratings": "Оценки",
        "comments": "Комментарии",
        "content_reactions": "Реакции",
        "balance_logs": "Лог баланса",
        "user_action_logs": "Лог действий",
        "offers": "Офферы",
        "offer_participations": "Участия в офферах",
        "offer_rentals": "Аренда офферов",
        "payments": "Платежи",
        "feedback": "Обращения",
        "games_history": "История игр",
        "game_sessions": "Игровые сессии",
        "daily_quest_progress": "Прогресс квестов",
        "promocodes": "Промокоды",
        "promocode_activations": "Активации промокодов",
        "lottery_rounds": "Лотерея: раунды",
        "lottery_tickets": "Лотерея: билеты",
        "events": "События",
    }

    all_tables = sorted(Base.metadata.tables.keys())
    tables = [(t, table_labels.get(t, t)) for t in all_tables]
    await _safe_edit(
        callback,
        "🗄 <b>База данных</b>\n\nВыберите таблицу для просмотра:",
        parse_mode="HTML",
        reply_markup=admin_db_keyboard(tables)
    )
    await callback.answer()


def _format_db_value(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "Да" if v else "Нет"
    if isinstance(v, datetime):
        return v.strftime("%d.%m.%Y %H:%M")
    if isinstance(v, Decimal):
        return f"{v:.2f}"
    s = str(v)
    s = s.replace("\n", " ").strip()
    if len(s) > 80:
        s = s[:80] + "…"
    return s


@router.callback_query(F.data.startswith("db_open:"))
async def db_open(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer()
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    table_name = parts[1]
    try:
        offset = max(0, int(parts[2]))
    except Exception:
        offset = 0
    if table_name not in Base.metadata.tables:
        await callback.answer("Таблица не найдена.", show_alert=True)
        return
    page_size = 8

    async with async_session() as session:
        try:
            total = (await session.execute(
                text(f'SELECT COUNT(*) FROM "{table_name}"')
            )).scalar_one()
            rows = (await session.execute(
                text(f'SELECT * FROM "{table_name}" ORDER BY 1 DESC LIMIT {page_size} OFFSET {offset}')
            )).mappings().all()
        except Exception as e:
            await callback.answer(f"Ошибка чтения таблицы: {e}", show_alert=True)
            return

    if not rows:
        body = "Нет строк."
    else:
        lines = []
        for row in rows:
            row_id = row.get("id", "?")
            title = ""
            if "telegram_id" in row and "username" in row:
                title = f"Юзер @{row.get('username') or '?'}"
            elif "telegram_file_id" in row:
                title = f"Видео/Фото от {row.get('uploader_user_id')}"
            elif "action" in row:
                title = f"Действие: {row.get('action')}"
            elif "amount" in row and "source" in row:
                title = f"Транзакция: {row.get('amount')}"
            elif "title" in row:
                title = f"Оффер: {row.get('title')}"
            
            lines.append(f"<b>#{row_id}</b> <i>{escape(title)}</i>")
            attrs = []
            for key, value in row.items():
                if key == "id" or value is None:
                    continue
                attrs.append(f"<b>{escape(str(key))}</b>: {escape(_format_db_value(value))}")
            lines.append("  " + " | ".join(attrs))
            lines.append("")
        body = "\n".join(lines).rstrip()

    text_out = (
        f"🗄 <b>{escape(table_name)}</b>\n"
        f"Всего строк: <b>{total}</b>\n"
        f"Страница: <b>{(offset // page_size) + 1}</b>\n"
        f"Показано: <b>{len(rows)}</b>\n\n"
        f"{body}"
    )
    if len(text_out) > 3900:
        text_out = text_out[:3900] + "\n..."

    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"db_open:{table_name}:{max(0, offset - page_size)}"))
    if offset + page_size < total:
        nav.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"db_open:{table_name}:{offset + page_size}"))

    kb_rows = []
    if nav:
        kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data=f"db_open:{table_name}:{offset}")])
    kb_rows.append([InlineKeyboardButton(text="📋 К списку таблиц", callback_data="admin_db_menu")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    await _safe_edit(callback, text_out, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# =========================
# MODERATION
# =========================
@router.callback_query(F.data == "admin_queue_info")
async def cb_queue(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        p = await count_pending_videos(session)
        a = await count_approved_videos(session)
        r = await count_rejected_videos(session)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶ Модерировать", callback_data="admin_get_pending")],
        [InlineKeyboardButton(text="✅ Одобрить всё", callback_data="admin_approve_all")],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")],
    ])
    await _safe_edit(callback, f"📊 <b>Очередь</b>\n\n⏳ На модерации: <b>{p}</b>\n✅ Одобрено: <b>{a}</b>\n❌ Отклонено: <b>{r}</b>", parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_get_pending")
async def admin_get_pending(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        video = await get_next_pending_video(session)
        if not video:
            await _safe_edit(callback, "✅ Очередь модерации пуста!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")]]))
            await callback.answer()
            return
        uploader = await get_user_by_id(session, video.uploader_user_id)
        name = get_display_name(uploader) if uploader else "???"
        tg_id = uploader.telegram_id if uploader else "???"
        caption = (f"📹 #{video.id} | {video.content_type}\n👤 {name} (tg: {tg_id})\n📅 {video.created_at.strftime('%d.%m.%Y %H:%M')}\n⏱ {video.duration_seconds or '?'} сек | 📦 {round(video.file_size / 1024 / 1024, 2) if video.file_size else '?'} МБ")
        try:
            if video.content_type == "photo":
                await callback.message.answer_photo(video.telegram_file_id, caption=caption, reply_markup=moderation_keyboard(video.id))
            else:
                await callback.message.answer_video(video.telegram_file_id, caption=caption, reply_markup=moderation_keyboard(video.id))
        except Exception as e:
            await callback.message.answer(f"⚠️ Не удалось загрузить медиа: {e}\n{caption}", reply_markup=moderation_keyboard(video.id))
    await callback.answer()


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
        [InlineKeyboardButton(text="✅ Готово", callback_data="event_applies_done"), InlineKeyboardButton(text="❌ Отмена", callback_data="admin_events_menu")]
    ])


@router.callback_query(F.data == "admin_events_menu")
async def admin_events_menu(callback: CallbackQuery):
    try:
        if not await check_admin(callback.from_user.id):
            await callback.answer("У вас нет прав!", show_alert=True)
            return
        async with async_session() as session:
            try:
                active = (await session.execute(select(Event).where(Event.is_active == True, Event.end_date > datetime.utcnow()).order_by(Event.start_date.desc()))).scalars().all()
            except Exception as e:
                print(f"DB Error: {e}")
                active = []
        text = "🎉 <b>Управление событиями</b>\n\n"
        if active:
            text += "Активные события:\n"
            for ev in active[:5]:
                text += f"• {escape(ev.name)} — {ev.discount_percent}% до {ev.end_date.strftime('%d.%m')}\n"
        else:
            text += "Нет активных событий.\n"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать новое событие", callback_data="event_create_start")],
            [InlineKeyboardButton(text="📋 Все события", callback_data="event_list_all")],
            [InlineKeyboardButton(text="🛍 Акции (Sale)", callback_data="admin_sales")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_center")]
        ])
        await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        print(f"Events menu error: {e}")
    finally:
        await callback.answer()


@router.callback_query(F.data == "event_create_start")
async def event_create_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    await state.set_state(EventCreationState.waiting_name)
    await callback.message.answer("🎉 <b>Создание события — шаг 1/7</b>\n\nВведите <b>название события</b>:", parse_mode="HTML")
    await callback.answer()


@router.message(EventCreationState.waiting_name)
async def event_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip()[:255])
    await state.set_state(EventCreationState.waiting_description)
    await message.answer("📝 <b>Шаг 2/7</b>\n\nВведите <b>текст события</b>:")


@router.message(EventCreationState.waiting_description)
async def event_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip()[:2000])
    await state.set_state(EventCreationState.waiting_discount)
    await message.answer("💰 <b>Шаг 3/7</b>\n\nРазмер <b>скидки (%)</b> (1-99):")


@router.message(EventCreationState.waiting_discount)
async def event_discount(message: Message, state: FSMContext):
    try:
        pct = int(message.text.strip())
        if not (1 <= pct <= 99): raise ValueError
    except:
        await message.answer("❌ Введите число от 1 до 99.")
        return
    await state.update_data(discount_percent=pct)
    await state.set_state(EventCreationState.waiting_duration)
    await message.answer("📅 <b>Шаг 4/7</b>\n\nСколько <b>дней</b> длится событие?")


@router.message(EventCreationState.waiting_duration)
async def event_duration(message: Message, state: FSMContext):
    try:
        days = int(message.text.strip())
        if days < 1: raise ValueError
    except:
        await message.answer("❌ Введите число ≥ 1.")
        return
    await state.update_data(duration_days=days)
    applies = {"vip": False, "coins": False, "lootbox": False, "cases": False}
    await state.update_data(applies=applies)
    await state.set_state(EventCreationState.waiting_applies)
    await message.answer("✅ <b>Шаг 5/7 — На что скидка?</b>", reply_markup=event_applies_keyboard(applies))


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
    if not any(data.get("applies", {}).values()):
        await callback.answer("❌ Выберите хотя бы одно!", show_alert=True)
        return
    await state.set_state(EventCreationState.waiting_image)
    await callback.message.answer("🖼 <b>Шаг 6/7</b>\n\nОтправьте фото или напишите 'пропустить':", parse_mode="HTML")
    await callback.answer()


@router.message(EventCreationState.waiting_image)
async def event_image(message: Message, state: FSMContext):
    if message.photo:
        await state.update_data(image_file_id=message.photo[-1].file_id)
    else:
        await state.update_data(image_file_id=None)
    
    data = await state.get_data()
    await state.set_state(EventCreationState.confirm)
    summary = f"🎉 <b>Предпросмотр</b>\n\n📌 Название: {data['name']}\n💰 Скидка: {data['discount_percent']}%\n📅 Дней: {data['duration_days']}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Создать", callback_data="event_confirm_yes"), InlineKeyboardButton(text="❌ Отмена", callback_data="admin_events_menu")]])
    await message.answer(summary, parse_mode="HTML", reply_markup=kb)


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
            applies_cases=applies.get("cases", False), image_file_id=data.get("image_file_id"),
            start_date=start, end_date=end, is_active=True, created_by=admin_user.id if admin_user else None
        )
        session.add(event)
        await session.commit()
    await state.clear()
    await callback.message.answer("✅ Событие создано и рассылка запущена!")
    await callback.answer()


# =========================
# SALES (Sale)
# =========================
@router.callback_query(F.data == "admin_sales")
async def admin_sales_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    async with async_session() as session:
        sale = await get_active_sale(session)
    text = "🛍 <b>Глобальные акции</b>\n\n"
    if sale:
        text += f"🟢 Активна: {sale.discount_percent}% на {sale.applies_to}\nДо: {sale.end_date.strftime('%d.%m %H:%M')}\n"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🛑 Остановить", callback_data="admin_sale_stop")], [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")]])
    else:
        text += "🔴 Нет активных акций."
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Создать", callback_data="admin_sale_create")], [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")]])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_sale_stop")
async def admin_sale_stop(callback: CallbackQuery):
    async with async_session() as session:
        sale = await get_active_sale(session)
        if sale:
            sale.end_date = datetime.utcnow()
            await session.commit()
            await callback.answer("✅ Остановлено", show_alert=True)
    await admin_sales_start(callback, None)


@router.callback_query(F.data == "admin_sale_create")
async def admin_sale_create(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SaleState.waiting_percent)
    await _safe_edit(callback, "Введите % скидки (1-99):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="admin_center")]]))


@router.message(SaleState.waiting_percent)
async def admin_sale_percent(message: Message, state: FSMContext):
    if not message.text.isdigit(): return
    await state.update_data(discount_percent=int(message.text))
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Всё", callback_data="sale_scope:all")], [InlineKeyboardButton(text="VIP", callback_data="sale_scope:vip")], [InlineKeyboardButton(text="Монеты", callback_data="sale_scope:coins")]])
    await state.set_state(SaleState.waiting_scope)
    await message.answer("На что скидка?", reply_markup=kb)


@router.callback_query(SaleState.waiting_scope, F.data.startswith("sale_scope:"))
async def admin_sale_scope(callback: CallbackQuery, state: FSMContext):
    await state.update_data(applies_to=callback.data.split(":")[1])
    await state.set_state(SaleState.waiting_duration)
    await _safe_edit(callback, "Длительность в часах:")
    await callback.answer()


@router.message(SaleState.waiting_duration)
async def admin_sale_duration(message: Message, state: FSMContext):
    if not message.text.isdigit(): return
    await state.update_data(duration_hours=int(message.text))
    await state.set_state(SaleState.waiting_text)
    await message.answer("Текст объявления:")


@router.message(SaleState.waiting_text)
async def admin_sale_finish(message: Message, state: FSMContext):
    data = await state.get_data()
    end_date = datetime.utcnow() + timedelta(hours=data["duration_hours"])
    async with async_session() as session:
        sale = ActiveSale(discount_percent=data["discount_percent"], applies_to=data["applies_to"], end_date=end_date, announcement=message.text)
        session.add(sale)
        await session.commit()
    await state.clear()
    await message.answer(f"✅ Акция создана до {end_date.strftime('%d.%m %H:%M')}!")


# =========================
# STATS
# =========================
@router.callback_query(F.data == "admin_extended_stats")
async def admin_extended_stats_v2(callback: CallbackQuery):
    async with async_session() as session:
        stats = await get_admin_extended_stats(session)
    text = (f"📊 <b>Статистика</b>\n\n👥 Юзеров: {stats['users']}\n⭐ VIP: {stats['vip']}\n💰 Монет: {stats['total_balance_in_system']:.2f}")
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")]]))
    await callback.answer()


# =========================
# OFFERS
# =========================
@router.callback_query(F.data == "admin_offers_menu")
async def admin_offers_menu_v2(callback: CallbackQuery):
    async with async_session() as session:
        total = (await session.execute(select(func.count(Offer.id)))).scalar_one()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать оффер", callback_data="admin_create_offer")],
        [InlineKeyboardButton(text="📋 Все офферы", callback_data="admin_offers_all")],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")]
    ])
    await _safe_edit(callback, f"📢 <b>Офферы</b> (Всего: {total})", parse_mode="HTML", reply_markup=kb)
    await callback.answer()
