"""
Core admin panel handlers.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, func, text

from app.db import async_session
from app.services import (
    get_admin_extended_stats, get_recent_feedback,
    count_pending_videos, count_active_rentals
)
from app.utils.admin import check_admin, is_super_admin
from app.keyboards import admin_main_keyboard, admin_db_keyboard, admin_after_action_keyboard

router = Router()

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

    from html import escape

    if not rows:
        body = "Нет строк."
    else:
        lines = []
        for row in rows:
            # Try to infer a natural "title" for the record
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
            
            # Format attributes compactly
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

    await _safe_edit(
        callback,
        text_out,
        parse_mode="HTML",
        reply_markup=kb,
    )
    await callback.answer()


# =========================
# QUEUE INFO
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
    await _safe_edit(
        callback,
        f"📊 <b>Очередь</b>\n\n"
        f"⏳ На модерации: <b>{p}</b>\n"
        f"✅ Одобрено: <b>{a}</b>\n"
        f"❌ Отклонено: <b>{r}</b>",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


# =========================
# EXTENDED STATS
# =========================
@router.callback_query(F.data == "admin_extended_stats")
async def admin_extended_stats(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        stats = await get_admin_extended_stats(session)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")]
    ])
    text = (
        f"📊 <b>Расширенная статистика</b>\n\n"
        f"👥 Пользователей: <b>{stats['users']}</b>\n"
        f"⭐ VIP: <b>{stats['vip']}</b>\n"
        f"🏷 С ником: <b>{stats['with_nickname']}</b>\n"
        f"💬 Комментариев: <b>{stats['comments']}</b>\n"
        f"❤ Реакций: <b>{stats['reactions']}</b>\n"
        f"🎮 Игр: <b>{stats['games']}</b>\n"
        f"📢 Офферов: <b>{stats['offers']}</b>\n"
        f"🔑 Активных аренд: <b>{stats.get('active_rentals', 0)}</b>\n\n"
        f"💰 Монет в системе: <b>{stats['total_balance_in_system']:.2f}</b>\n"
        f"🎁 Выдано админами: <b>{stats['total_admin_given']:.2f}</b>\n"
        f"🎲 Прибыль казино: <b>{stats['total_game_profit']:.2f}</b>\n"
        f"🏠 Доход от аренды: <b>{abs(float(stats.get('total_rent_income', 0))):.2f}</b>"
    )
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# =========================
@router.callback_query(F.data == "admin_get_pending")


@router.message(AdminBroadcastState.waiting_text)
