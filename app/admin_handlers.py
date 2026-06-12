from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
import os

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
    , TrustedUploader
)
from app.services import (
    get_user, get_user_by_id, get_user_by_username,
    get_user_dossier, update_user_balance, set_user_ban_status,
    count_pending_videos, count_approved_videos, count_rejected_videos,
    get_next_pending_video, approve_video, reject_video,
    get_admin_extended_stats, get_display_name,
    get_user_by_display_name, admin_create_offer,
    count_active_rentals, expire_old_rentals, log_user_action,
    get_recent_feedback,
)
from app.keyboards import (
    admin_main_keyboard, moderation_keyboard,
    rejection_reason_keyboard, admin_after_action_keyboard,
    admin_db_keyboard,
)

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


# =========================
# HELPERS
# =========================
def is_super_admin(tid: int) -> bool:
    return tid in ADMINS


async def check_admin(tid: int) -> bool:
    if tid in ADMINS:
        return True
    async with async_session() as session:
        user = await get_user(session, tid)
        if user and user.is_admin:
            return True
    return False


async def _safe_edit(callback: CallbackQuery, text: str, **kwargs):
    try:
        await callback.message.edit_text(text, **kwargs)
    except Exception:
        await callback.message.answer(text, **kwargs)


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
# INVESTIGATION
# =========================
@router.callback_query(F.data == "admin_investigation")
async def admin_investigation(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🎲 Подозрительные игры",
            callback_data="inv_suspicious_games"
        )],
        [InlineKeyboardButton(
            text="💰 Топ богачей (детально)",
            callback_data="inv_rich_detail"
        )],
        [InlineKeyboardButton(
            text="📋 Последние движения баланса",
            callback_data="inv_balance_log"
        )],
        [InlineKeyboardButton(
            text="🔍 Найти по ID/нику",
            callback_data="admin_user_dossier"
        )],
        [InlineKeyboardButton(
            text="📁 Экспорт (PDF / TXT)",
            callback_data="inv_export_menu"
        )],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")],
    ])
    await callback.message.answer(
        "🔍 <b>Центр расследований</b>\n\nВыберите инструмент:",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data == "inv_suspicious_games")
async def inv_suspicious_games(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        rows = (await session.execute(
            select(
                User,
                func.count(GameHistory.id).label("games"),
                func.sum(GameHistory.result).label("profit"),
                func.sum(GameHistory.bet).label("total_bet"),
            )
            .join(GameHistory, GameHistory.user_id == User.id)
            .where(GameHistory.created_at >= week_ago)
            .group_by(User.id)
            .having(func.sum(GameHistory.result) > 50)
            .order_by(desc("profit"))
            .limit(20)
        )).all()

    if not rows:
        await callback.message.answer("Подозрительных игроков не найдено.")
        await callback.answer()
        return

    text = "🎲 <b>Подозрительные игроки (7 дней)</b>\n\n"
    for u, games, profit, total_bet in rows:
        text += (
            f"👤 {get_display_name(u)} "
            f"(<code>{u.telegram_id}</code>)\n"
            f"  Игр: {games} | Прибыль: {profit:.2f} | "
            f"Ставки: {total_bet:.2f} | Баланс: {u.balance:.2f}\n\n"
        )
    if len(text) > 4000:
        text = text[:4000] + "\n..."

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_investigation")]
    ])
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "inv_export_menu")
async def inv_export_menu(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 PDF", callback_data="inv_export_ai_pdf")],
        [InlineKeyboardButton(text="📄 TXT", callback_data="inv_export_ai")],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_investigation")],
    ])
    await callback.message.answer(
        "📁 <b>Экспорт для анализа</b>\n\nВыберите формат:",
        parse_mode="HTML",
        reply_markup=kb,
    )
    await callback.answer()


def _find_cyrillic_font_path() -> str | None:
    candidates = [
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
        r"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        r"/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        r"/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for p in candidates:
        try:
            if os.path.exists(p):
                return p
        except Exception:
            continue
    return None


def _text_to_pdf_bytes(title: str, text: str) -> bytes:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except Exception as e:
        raise RuntimeError(f"reportlab_missing: {e}")

    buf = BytesIO()
    page_w, page_h = A4
    margin = 36
    y = page_h - margin
    line_gap = 12

    font_name = "Helvetica"
    font_path = _find_cyrillic_font_path()
    if font_path:
        try:
            pdfmetrics.registerFont(TTFont("BotFont", font_path))
            font_name = "BotFont"
        except Exception:
            font_name = "Helvetica"

    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(title)
    c.setFont(font_name, 11)

    def new_page():
        nonlocal y
        c.showPage()
        c.setFont(font_name, 11)
        y = page_h - margin

    for line in title.splitlines():
        if y < margin:
            new_page()
        c.drawString(margin, y, line)
        y -= line_gap
    y -= line_gap

    c.setFont(font_name, 9)
    max_chars = 120
    for raw in (text or "").splitlines():
        line = raw.rstrip("\n")
        if not line:
            if y < margin:
                new_page()
            y -= line_gap
            continue
        while len(line) > max_chars:
            chunk, line = line[:max_chars], line[max_chars:]
            if y < margin:
                new_page()
            c.drawString(margin, y, chunk)
            y -= line_gap
        if y < margin:
            new_page()
        c.drawString(margin, y, line)
        y -= line_gap

    c.save()
    return buf.getvalue()


@router.callback_query(F.data == "inv_rich_detail")
async def inv_rich_detail(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        users = (await session.execute(
            select(User).order_by(desc(User.balance)).limit(15)
        )).scalars().all()

        text = "💰 <b>Топ богачей (детально)</b>\n\n"
        for i, u in enumerate(users, 1):
            admin_given = (await session.execute(
                select(func.sum(BalanceLog.amount)).where(
                    BalanceLog.user_id == u.id,
                    BalanceLog.source == "admin_balance",
                    BalanceLog.amount > 0
                )
            )).scalar_one() or Decimal("0")

            game_profit = (await session.execute(
                select(func.sum(GameHistory.result)).where(
                    GameHistory.user_id == u.id
                )
            )).scalar_one() or Decimal("0")

            text += (
                f"{i}. <b>{get_display_name(u)}</b> — {u.balance:.2f}\n"
                f"  👮 Адм: {admin_given:.2f} | "
                f"🎲 Игры: {game_profit:.2f} | "
                f"🆔 <code>{u.telegram_id}</code>\n\n"
            )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_investigation")]
    ])
    if len(text) > 4000:
        text = text[:4000] + "\n..."
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "inv_balance_log")
async def inv_balance_log(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        rows = (await session.execute(
            select(BalanceLog, User)
            .join(User, User.id == BalanceLog.user_id)
            .order_by(desc(BalanceLog.created_at))
            .limit(30)
        )).all()

    if not rows:
        await callback.message.answer("Лог пуст.")
        await callback.answer()
        return

    text = "📋 <b>Последние 30 движений баланса</b>\n\n"
    for log, u in rows:
        sign = "+" if log.amount >= 0 else ""
        text += (
            f"{log.created_at.strftime('%d.%m %H:%M')} | "
            f"<b>{get_display_name(u)}</b> | "
            f"{sign}{log.amount:.2f} [{log.source}]\n"
            f"  {log.balance_before:.2f} → {log.balance_after:.2f}"
        )
        if log.details:
            text += f"\n  📝 {log.details[:60]}"
        text += "\n\n"

    if len(text) > 4000:
        text = text[:4000] + "\n..."

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_investigation")]
    ])
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "inv_export_ai")
async def inv_export_ai(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        rich_users = (await session.execute(
            select(User).order_by(desc(User.balance)).limit(10)
        )).scalars().all()

        sus_rows = (await session.execute(
            select(
                User,
                func.sum(GameHistory.result).label("profit"),
                func.count(GameHistory.id).label("games")
            )
            .join(GameHistory, GameHistory.user_id == User.id)
            .group_by(User.id)
            .having(func.sum(GameHistory.result) > 30)
            .order_by(desc("profit"))
            .limit(10)
        )).all()

        admin_rows = (await session.execute(
            select(BalanceLog, User)
            .join(User, User.id == BalanceLog.user_id)
            .where(BalanceLog.source == "admin_balance")
            .order_by(desc(BalanceLog.created_at))
            .limit(20)
        )).all()

        try:
            rental_rows = (await session.execute(
                .limit(20)
            )).all()
        except Exception:
            rental_rows = []

    report = "=== ОТЧЁТ ДЛЯ АНАЛИЗА ===\n"
    report += f"Дата: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC\n\n"

    report += "--- ТОП 10 БОГАЧЕЙ ---\n"
    for i, u in enumerate(rich_users, 1):
        report += (
            f"{i}. nick={get_display_name(u)} "
            f"tg_id={u.telegram_id} "
            f"balance={u.balance} "
            f"level={u.level} "
            f"created={u.created_at.strftime('%Y-%m-%d')}\n"
        )

    report += "\n--- ПОДОЗРИТЕЛЬНЫЕ ИГРОКИ ---\n"
    for u, profit, games in sus_rows:
        report += (
            f"nick={get_display_name(u)} "
            f"tg_id={u.telegram_id} "
            f"game_profit={profit:.2f} "
            f"games={games} "
            f"balance={u.balance}\n"
        )

    report += "\n--- ВЫДАЧИ МОНЕТ АДМИНАМИ ---\n"
    for log, u in admin_rows:
        report += (
            f"date={log.created_at.strftime('%Y-%m-%d %H:%M')} "
            f"admin_id={log.admin_id} "
            f"user={get_display_name(u)}(tg={u.telegram_id}) "
            f"amount={log.amount} "
            f"before={log.balance_before} "
            f"after={log.balance_after}\n"
        )

    report += "\n--- ИСТОРИЯ АРЕНДЫ ---\n"
    for r, u in rental_rows:
        report += (
            f"date={r.created_at.strftime('%Y-%m-%d')} "
            f"user={get_display_name(u)} "
            f"channel={r.renter_channel_title} "
            f"offer_id={r.offer_id} "
            f"days={r.rent_days} "
            f"cost={r.cost_paid} "
            f"status={r.status}\n"
        )

    report += "\n=== КОНЕЦ ОТЧЁТА ==="

    buf = BytesIO(report.encode("utf-8"))
    buf.name = f"report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.txt"
    await callback.message.answer_document(
        buf,
        caption="📁 Экспорт готов (TXT)."
    )
    await callback.answer()


@router.callback_query(F.data == "inv_export_ai_pdf")
async def inv_export_ai_pdf(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    # Build same report as TXT version
    async with async_session() as session:
        rich_users = (await session.execute(
            select(User).order_by(desc(User.balance)).limit(10)
        )).scalars().all()

        sus_rows = (await session.execute(
            select(
                User,
                func.sum(GameHistory.result).label("profit"),
                func.count(GameHistory.id).label("games")
            )
            .join(GameHistory, GameHistory.user_id == User.id)
            .group_by(User.id)
            .having(func.sum(GameHistory.result) > 30)
            .order_by(desc("profit"))
            .limit(10)
        )).all()

        admin_rows = (await session.execute(
            select(BalanceLog, User)
            .join(User, User.id == BalanceLog.user_id)
            .where(BalanceLog.source == "admin_balance")
            .order_by(desc(BalanceLog.created_at))
            .limit(20)
        )).all()

        try:
            rental_rows = (await session.execute(
                .limit(20)
            )).all()
        except Exception:
            rental_rows = []

    report = "=== ОТЧЁТ ДЛЯ АНАЛИЗА ===\n"
    report += f"Дата: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC\n\n"

    report += "--- ТОП 10 БОГАЧЕЙ ---\n"
    for i, u in enumerate(rich_users, 1):
        report += (
            f"{i}. nick={get_display_name(u)} "
            f"tg_id={u.telegram_id} "
            f"balance={u.balance} "
            f"level={u.level} "
            f"created={u.created_at.strftime('%Y-%m-%d')}\n"
        )

    report += "\n--- ПОДОЗРИТЕЛЬНЫЕ ИГРОКИ ---\n"
    for u, profit, games in sus_rows:
        report += (
            f"nick={get_display_name(u)} "
            f"tg_id={u.telegram_id} "
            f"game_profit={profit:.2f} "
            f"games={games} "
            f"balance={u.balance}\n"
        )

    report += "\n--- ВЫДАЧИ МОНЕТ АДМИНАМИ ---\n"
    for log, u in admin_rows:
        report += (
            f"date={log.created_at.strftime('%Y-%m-%d %H:%M')} "
            f"admin_id={log.admin_id} "
            f"user={get_display_name(u)}(tg={u.telegram_id}) "
            f"amount={log.amount} "
            f"before={log.balance_before} "
            f"after={log.balance_after}\n"
        )

    report += "\n--- ИСТОРИЯ АРЕНДЫ ---\n"
    for r, u in rental_rows:
        report += (
            f"date={r.created_at.strftime('%Y-%m-%d')} "
            f"user={get_display_name(u)} "
            f"channel={r.renter_channel_title} "
            f"offer_id={r.offer_id} "
            f"days={r.rent_days} "
            f"cost={r.cost_paid} "
            f"status={r.status}\n"
        )

    report += "\n=== КОНЕЦ ОТЧЁТА ==="

    try:
        pdf_bytes = _text_to_pdf_bytes("Экспорт для анализа", report)
    except Exception as e:
        # Fallback to TXT if PDF generation fails in runtime
        buf = BytesIO(report.encode("utf-8"))
        buf.name = f"report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.txt"
        await callback.message.answer_document(
            buf,
            caption=f"⚠️ PDF не удалось собрать ({e}). Отправил TXT.",
        )
        await callback.answer()
        return

    buf = BytesIO(pdf_bytes)
    buf.name = f"report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.pdf"
    await callback.message.answer_document(
        buf,
        caption="📁 Экспорт готов (PDF).",
    )
    await callback.answer()


# =========================
# MODERATION
# =========================
@router.callback_query(F.data == "admin_get_pending")
async def admin_get_pending(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        video = await get_next_pending_video(session)
        if not video:
            await _safe_edit(
                callback,
                "✅ Очередь модерации пуста!",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")]
                ])
            )
            await callback.answer()
            return

        uploader = await get_user_by_id(session, video.uploader_user_id)
        name = get_display_name(uploader) if uploader else "???"
        tg_id = uploader.telegram_id if uploader else "???"

        caption = (
            f"📹 #{video.id} | {video.content_type}\n"
            f"👤 {name} (tg: {tg_id})\n"
            f"📅 {video.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"⏱ {video.duration_seconds or '?'} сек | "
            f"📦 {round(video.file_size / 1024 / 1024, 2) if video.file_size else '?'} МБ"
        )

        try:
            if video.content_type == "photo":
                await callback.message.answer_photo(
                    video.telegram_file_id,
                    caption=caption,
                    reply_markup=moderation_keyboard(video.id)
                )
            else:
                await callback.message.answer_video(
                    video.telegram_file_id,
                    caption=caption,
                    reply_markup=moderation_keyboard(video.id)
                )
        except Exception as e:
            await callback.message.answer(
                f"⚠️ Не удалось загрузить медиа: {e}\n{caption}",
                reply_markup=moderation_keyboard(video.id)
            )
    await callback.answer()


@router.callback_query(F.data.startswith("mod_approve:"))
async def mod_approve(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    video_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        video = await approve_video(session, video_id)
        if not video:
            await callback.answer("Уже обработано.", show_alert=True)
            return
        uploader = await get_user_by_id(session, video.uploader_user_id)
        if uploader:
            try:
                await callback.bot.send_message(
                    uploader.telegram_id,
                    f"✅ Ваше видео #{video_id} одобрено! Монеты начислены."
                )
            except Exception:
                pass

    # Редактируем сообщение с видео, добавляя статус
    try:
        await callback.message.edit_caption(
            caption=f"✅ #{video_id} — ОДОБРЕНО",
            reply_markup=admin_after_action_keyboard()
        )
    except Exception:
        try:
            await callback.message.edit_reply_markup(
                reply_markup=admin_after_action_keyboard()
            )
        except Exception:
            pass
    await callback.answer(f"✅ #{video_id} одобрено!", show_alert=False)


@router.callback_query(F.data.startswith("mod_reject:"))
async def mod_reject(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    video_id = int(callback.data.split(":")[1])
    # Показываем причины прямо в inline-клавиатуре под видео
    try:
        await callback.message.edit_reply_markup(
            reply_markup=rejection_reason_keyboard(video_id)
        )
    except Exception:
        await callback.message.answer(
            f"Причина отклонения #{video_id}:",
            reply_markup=rejection_reason_keyboard(video_id)
        )
    await callback.answer()


@router.callback_query(F.data.startswith("reject_reason:"))
async def reject_reason(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    parts = callback.data.split(":")
    video_id = int(parts[1])
    reason_key = parts[2]
    reason_map = {
        "duplicate": "Дубликат",
        "off_topic": "Не по теме",
        "forbidden": "Запрещённый контент",
        "other": "Другая причина",
    }
    reason_text = reason_map.get(reason_key, reason_key)

    async with async_session() as session:
        video = await reject_video(session, video_id, reason_text)
        if not video:
            await callback.answer("Не найдено.", show_alert=True)
            return
        uploader = await get_user_by_id(session, video.uploader_user_id)
        if uploader:
            try:
                await callback.bot.send_message(
                    uploader.telegram_id,
                    f"❌ Видео #{video_id} отклонено.\nПричина: {reason_text}"
                )
            except Exception:
                pass

    # Редактируем сообщение
    try:
        await callback.message.edit_caption(
            caption=f"❌ #{video_id} — ОТКЛОНЕНО\nПричина: {reason_text}",
            reply_markup=admin_after_action_keyboard()
        )
    except Exception:
        try:
            await callback.message.edit_reply_markup(
                reply_markup=admin_after_action_keyboard()
            )
        except Exception:
            pass
    await callback.answer(f"❌ Отклонено: {reason_text}", show_alert=False)


@router.callback_query(F.data == "admin_approve_all")
async def admin_approve_all(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    await callback.answer("⏳ Одобряю все видео...", show_alert=False)

    count = 0
    errors = 0
    # Каждый approve в отдельной сессии чтобы избежать stale data
    uploader_notifications = {}
    for _ in range(200):  # защита от бесконечного цикла
        async with async_session() as session:
            video = await get_next_pending_video(session)
            if not video:
                break
            try:
                result = await approve_video(session, video.id)
                if result:
                    count += 1
                    uploader = await get_user_by_id(session, video.uploader_user_id)
                    if uploader:
                        uploader_notifications[uploader.telegram_id] = uploader_notifications.get(uploader.telegram_id, 0) + 1
                else:
                    break
            except Exception:
                errors += 1
                break

    import asyncio
    for tg_id, approved_count in uploader_notifications.items():
        try:
            await callback.bot.send_message(
                tg_id,
                f"✅ Одобрено {approved_count} ваших видео/фото! Монеты начислены."
            )
        except Exception:
            pass
        await asyncio.sleep(0.05)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀ В меню", callback_data="admin_center")]
    ])
    result_text = f"✅ Одобрено видео: <b>{count}</b>"
    if errors:
        result_text += f"\n⚠️ Ошибок: {errors}"

    await callback.message.answer(
        result_text,
        parse_mode="HTML",
        reply_markup=kb
    )


@router.callback_query(F.data == "admin_trusted_uploaders")
async def admin_trusted_uploaders(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        admin_user = await get_user(session, callback.from_user.id)
        if not admin_user:
            await callback.answer()
            return
        rows = (await session.execute(
            select(TrustedUploader, User)
            .join(User, User.id == TrustedUploader.trusted_user_id)
            .where(TrustedUploader.admin_user_id == admin_user.id)
            .order_by(desc(TrustedUploader.created_at))
            .limit(50)
        )).all()

    text_out = "🤝 <b>Доверенные авторы</b>\n\n"
    if not rows:
        text_out += "Список пуст.\n\nДобавьте ники друзей/авторов, которым доверяете — их видео будет одобряться автоматически."
    else:
        for i, (_, u) in enumerate(rows, 1):
            text_out += f"{i}. {get_display_name(u)} (<code>{u.telegram_id}</code>)\n"

    kb_rows = [
        [InlineKeyboardButton(text="➕ Добавить", callback_data="trusted_add")],
    ]
    if rows:
        kb_rows.append([InlineKeyboardButton(text="➖ Удалить", callback_data="trusted_remove_menu")])
    kb_rows.append([InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await _safe_edit(callback, text_out, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "trusted_add")
async def trusted_add_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(TrustedUploaderState.waiting_add)
    await callback.message.answer("Введите Telegram ID, @username или ник автора, которого добавить в доверенные:")
    await callback.answer()


@router.message(TrustedUploaderState.waiting_add)
async def trusted_add_process(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("❌ Пусто. Введите Telegram ID, @username или ник.")
        return

    async with async_session() as session:
        admin_user = await get_user(session, message.from_user.id)
        if not admin_user:
            await state.clear()
            return

        target = None
        if raw.isdigit():
            target = await get_user(session, int(raw))
        elif raw.startswith("@"):
            target = await get_user_by_username(session, raw)
        else:
            target = await get_user_by_display_name(session, raw)

        if not target:
            await message.answer("❌ Пользователь не найден в базе. Он должен хотя бы раз зайти в бота.")
            await state.clear()
            return

        # нельзя добавить самого себя дважды — но можно, просто игнорируем
        existing = (await session.execute(
            select(TrustedUploader).where(
                TrustedUploader.admin_user_id == admin_user.id,
                TrustedUploader.trusted_user_id == target.id,
            )
        )).scalar_one_or_none()
        if existing:
            await message.answer("ℹ️ Уже в доверенных.")
            await state.clear()
            return

        session.add(TrustedUploader(admin_user_id=admin_user.id, trusted_user_id=target.id))
        await session.commit()

    await message.answer(f"✅ Добавлено в доверенные: <b>{get_display_name(target)}</b>", parse_mode="HTML")
    await state.clear()


@router.callback_query(F.data == "trusted_remove_menu")
async def trusted_remove_menu(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        admin_user = await get_user(session, callback.from_user.id)
        if not admin_user:
            await callback.answer()
            return
        rows = (await session.execute(
            select(TrustedUploader, User)
            .join(User, User.id == TrustedUploader.trusted_user_id)
            .where(TrustedUploader.admin_user_id == admin_user.id)
            .order_by(desc(TrustedUploader.created_at))
            .limit(50)
        )).all()

    if not rows:
        await callback.answer("Список пуст.", show_alert=True)
        return

    kb_rows = []
    for tu, u in rows[:20]:
        kb_rows.append([InlineKeyboardButton(
            text=f"❌ {get_display_name(u)}",
            callback_data=f"trusted_remove:{u.id}"
        )])
    kb_rows.append([InlineKeyboardButton(text="◀ Назад", callback_data="admin_trusted_uploaders")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await _safe_edit(callback, "Выберите, кого удалить из доверенных:", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("trusted_remove:"))
async def trusted_remove(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    try:
        trusted_user_id = int(callback.data.split(":", 1)[1])
    except Exception:
        await callback.answer()
        return

    async with async_session() as session:
        admin_user = await get_user(session, callback.from_user.id)
        if not admin_user:
            await callback.answer()
            return
        await session.execute(
            text(
                "DELETE FROM trusted_uploaders WHERE admin_user_id = :a AND trusted_user_id = :t"
            ),
            {"a": admin_user.id, "t": trusted_user_id},
        )
        await session.commit()
    await callback.answer("Удалено.", show_alert=False)
    await admin_trusted_uploaders(callback)


@router.callback_query(F.data == "admin_auto_moderation")
async def admin_auto_moderation(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    await callback.answer("⏳ Авто-модерация...", show_alert=False)

    approved = 0
    considered = 0
    # ограничитель, чтобы не зависнуть
    for _ in range(200):
        async with async_session() as session:
            admin_user = await get_user(session, callback.from_user.id)
            if not admin_user:
                break

            trusted_ids = set([admin_user.id])
            trusted_rows = (await session.execute(
                select(TrustedUploader.trusted_user_id).where(TrustedUploader.admin_user_id == admin_user.id)
            )).scalars().all()
            trusted_ids.update(trusted_rows)

            video = (await session.execute(
                select(Video)
                .where(Video.status == "pending", Video.uploader_user_id.in_(trusted_ids))
                .order_by(Video.created_at.asc())
                .limit(1)
            )).scalar_one_or_none()

            if not video:
                break

            considered += 1
            try:
                res = await approve_video(session, video.id)
                if res:
                    approved += 1
                    uploader = await get_user_by_id(session, video.uploader_user_id)
                    if uploader:
                        try:
                            await callback.bot.send_message(
                                uploader.telegram_id,
                                f"✅ Ваше видео #{video.id} одобрено! Монеты начислены."
                            )
                        except Exception:
                            pass
            except Exception:
                break

    async with async_session() as session:
        remaining = await count_pending_videos(session)

    text_out = (
        "⚡ <b>Авто-модерация завершена</b>\n\n"
        f"✅ Одобрено автоматически: <b>{approved}</b>\n"
        f"👁️ Просмотрено кандидатов: <b>{considered}</b>\n\n"
        f"📝 Осталось в очереди: <b>{remaining}</b>\n"
        "Совет: оставшиеся видео лучше модерировать вручную."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Модерация контента", callback_data="admin_get_pending")],
        [InlineKeyboardButton(text="🤝 Доверенные авторы", callback_data="admin_trusted_uploaders")],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")],
    ])
    await callback.message.answer(text_out, parse_mode="HTML", reply_markup=kb)


# =========================
# USER MANAGEMENT
# =========================
@router.callback_query(F.data == "admin_manage_users")
async def admin_manage_users(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Досье", callback_data="admin_user_dossier")],
        [InlineKeyboardButton(text="💰 Выдать монеты", callback_data="admin_give_coins")],
        [InlineKeyboardButton(text="🚫 Заблокировать", callback_data="admin_ban_user")],
        [InlineKeyboardButton(text="✅ Разблокировать", callback_data="admin_unban_user")],
        [InlineKeyboardButton(text="✉ Сообщение", callback_data="admin_message_user")],
        [InlineKeyboardButton(text="✏️ Изменить ник", callback_data="admin_change_nickname")],
        [InlineKeyboardButton(text="📢 Объявление / рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")],
    ])
    await _safe_edit(
        callback,
        "👥 <b>Управление пользователями</b>",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


# --- DOSSIER ---
@router.callback_query(F.data == "admin_user_dossier")
async def admin_user_dossier_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminUserState.waiting_dossier_id)
    await callback.message.answer(
        "Введите Telegram ID, @username или ник пользователя:"
    )
    await callback.answer()


@router.message(AdminUserState.waiting_dossier_id)
async def process_dossier(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    query = message.text.strip()
    async with async_session() as session:
        user = None
        if query.startswith("@"):
            user = await get_user_by_username(session, query)
        elif query.isdigit():
            user = await get_user(session, int(query))
        else:
            user = await get_user_by_display_name(session, query)
            if not user:
                user = await get_user_by_username(session, query)

        if not user:
            await message.answer("❌ Пользователь не найден.")
            await state.clear()
            return

        dossier = await get_user_dossier(session, user.id)
        if not dossier:
            await message.answer("❌ Не удалось получить досье.")
            await state.clear()
            return

        u = dossier["user"]
        suspicion = []
        if dossier["game_profit"] > 100:
            suspicion.append(f"Аномальная прибыль: {dossier['game_profit']:.2f}")
        if dossier["admin_given"] > 200:
            suspicion.append(f"Много от администраторов: {dossier['admin_given']:.2f}")
        if dossier["suspicious_games"]:
            suspicion.append(f"Подозрит. партий игр: {len(dossier['suspicious_games'])}")

        logs_text = ""
        for log in dossier["action_logs"][:5]:
            logs_text += f" • {log.action} ({log.created_at.strftime('%d.%m %H:%M')})\n"
            if log.details:
                logs_text += f"   {str(log.details)[:50]}\n"

        balance_logs_text = ""
        for bl in dossier["balance_logs"][:5]:
            sign = "+" if bl.amount >= 0 else ""
            balance_logs_text += (
                f" {bl.created_at.strftime('%d.%m %H:%M')} "
                f"{sign}{bl.amount:.2f} [{bl.source}] "
                f"{bl.balance_before:.2f}→{bl.balance_after:.2f}\n"
            )

        text = (
            f"📋 <b>Досье: {get_display_name(u)}</b>\n\n"
            f"🆔 TG: <code>{u.telegram_id}</code>\n"
            f"🏷 Ник: {u.display_name or 'не задан'}\n"
            f"📛 Имя: {u.first_name or '???'}\n"
            f"👤 @{u.username or '???'}\n"
            f"💰 Баланс: <b>{u.balance:.2f}</b>\n"
            f"⭐ Ур.{u.level} | XP: {u.xp}\n"
            f"🔹 Статус: {u.status}\n"
            f"💎 VIP: {'да' if u.vip_until and u.vip_until > datetime.now(timezone.utc) else 'нет'}\n"
            f"📅 Рег.: {u.created_at.strftime('%d.%m.%Y')}\n\n"
            f"📤 Загружено: {dossier['videos_uploaded']}\n"
            f"📥 Просмотрено: {dossier['videos_watched']}\n"
            f"🎮 Игр: {dossier['games_count']} | "
            f"Прибыль: {dossier['game_profit']:.2f}\n"
            f"💵 Всего заработано: {dossier['total_earned']:.2f}\n"
            f"💸 Всего потрачено: {abs(float(dossier['total_spent'])):.2f}\n"
            f"🎁 От админов: {dossier['admin_given']:.2f}\n\n"
            f"⚠️ <b>Флаги:</b>\n"
            f"{'; '.join(suspicion) if suspicion else 'Подозрений нет'}\n\n"
            f"📌 <b>Действия:</b>\n{logs_text or 'нет'}\n"
            f"💳 <b>Лог баланса:</b>\n{balance_logs_text or 'нет'}"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💰 Монеты",
                    callback_data=f"give_coins_to:{u.id}"
                ),
                InlineKeyboardButton(
                    text="🚫 Бан",
                    callback_data=f"ban_user:{u.id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✅ Разбан",
                    callback_data=f"unban_user:{u.id}"
                ),
                InlineKeyboardButton(
                    text="✏️ Ник",
                    callback_data=f"admin_set_nick:{u.id}"
                ),
            ],
            [InlineKeyboardButton(
                text="📄 Полный лог баланса",
                callback_data=f"full_balance_log:{u.id}"
            )],
        ])

        if len(text) > 4000:
            text = text[:4000] + "\n..."
        await message.answer(text, parse_mode="HTML", reply_markup=kb)
    await state.clear()


@router.callback_query(F.data.startswith("full_balance_log:"))
async def full_balance_log(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    user_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        u = await get_user_by_id(session, user_id)
        if not u:
            await callback.answer("Не найдено.", show_alert=True)
            return
        logs = (await session.execute(
            select(BalanceLog)
            .where(BalanceLog.user_id == user_id)
            .order_by(desc(BalanceLog.created_at))
            .limit(100)
        )).scalars().all()

        report = (
            f"=== Лог баланса: {get_display_name(u)} "
            f"(tg={u.telegram_id}) ===\n"
            f"Текущий баланс: {u.balance}\n\n"
        )
        for log in logs:
            sign = "+" if log.amount >= 0 else ""
            report += (
                f"{log.created_at.strftime('%Y-%m-%d %H:%M:%S')} | "
                f"{sign}{log.amount} | {log.source} | "
                f"{log.balance_before}→{log.balance_after}"
            )
            if log.admin_id:
                report += f" | admin={log.admin_id}"
            if log.details:
                report += f" | {log.details}"
            report += "\n"

        buf = BytesIO(report.encode("utf-8"))
        buf.name = f"balance_{u.telegram_id}.txt"
        await callback.message.answer_document(
            buf,
            caption=f"📄 Лог баланса: {get_display_name(u)}"
        )
    await callback.answer()


# --- GIVE COINS ---
@router.callback_query(F.data == "admin_give_coins")
async def admin_give_coins_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminUserState.waiting_user_id)
    await state.update_data(action="give_coins")
    await callback.message.answer("Введите TG ID / @username / ник:")
    await callback.answer()


@router.callback_query(F.data.startswith("give_coins_to:"))
async def give_coins_to_user(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    user_id = int(callback.data.split(":")[1])
    await state.set_state(AdminUserState.waiting_coins_amount)
    await state.update_data(target_user_id=user_id)
    await callback.message.answer(
        "Введите количество монет (+начислить, -списать):"
    )
    await callback.answer()


@router.message(AdminUserState.waiting_user_id)
async def process_user_id_for_action(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    data = await state.get_data()
    action = data.get("action")
    query = message.text.strip()

    async with async_session() as session:
        user = None
        if query.startswith("@"):
            user = await get_user_by_username(session, query)
        elif query.isdigit():
            user = await get_user(session, int(query))
        else:
            user = await get_user_by_display_name(session, query)

        if not user:
            await message.answer("❌ Пользователь не найден.")
            await state.clear()
            return

        await state.update_data(
            target_user_id=user.id,
            target_tg_id=user.telegram_id
        )

        if action == "give_coins":
            await state.set_state(AdminUserState.waiting_coins_amount)
            await message.answer("Введите количество монет:")
        elif action == "ban":
            ok = await set_user_ban_status(
                session, user.id, True, message.from_user.id
            )
            await message.answer(
                f"✅ {get_display_name(user)} заблокирован." if ok else "❌ Ошибка."
            )
            if ok:
                try:
                    await message.bot.send_message(
                        user.telegram_id, "🚫 Вы заблокированы."
                    )
                except Exception:
                    pass
            await state.clear()
        elif action == "unban":
            ok = await set_user_ban_status(
                session, user.id, False, message.from_user.id
            )
            await message.answer(
                f"✅ {get_display_name(user)} разблокирован." if ok else "❌ Ошибка."
            )
            if ok:
                try:
                    await message.bot.send_message(
                        user.telegram_id, "✅ Вы разблокированы."
                    )
                except Exception:
                    pass
            await state.clear()
        elif action == "message":
            await state.set_state(AdminUserState.waiting_message_text)
            await message.answer("Введите текст сообщения:")


@router.message(AdminUserState.waiting_coins_amount)
async def process_coins_amount(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    try:
        amount = Decimal(message.text.strip())
    except Exception:
        await message.answer("❌ Введите число (50 или -10).")
        return

    data = await state.get_data()
    user_id = data.get("target_user_id")
    if not user_id:
        await message.answer("❌ Ошибка: пользователь не найден.")
        await state.clear()
        return

    async with async_session() as session:
        ok = await update_user_balance(
            session, user_id, amount, message.from_user.id
        )
        if ok:
            user = await get_user_by_id(session, user_id)
            name = get_display_name(user) if user else str(user_id)
            await message.answer(
                f"✅ Баланс обновлён!\n"
                f"👤 {name}\n"
                f"Изменение: {'+' if amount > 0 else ''}{amount}\n"
                f"Новый баланс: {user.balance if user else '???'}"
            )
            if user:
                try:
                    await message.bot.send_message(
                        user.telegram_id,
                        f"💰 Ваш баланс изменён администратором: "
                        f"{'+' if amount > 0 else ''}{amount} монет"
                    )
                except Exception:
                    pass
        else:
            await message.answer("❌ Операция не выполнена.")
    await state.clear()


# --- BAN / UNBAN ---
@router.callback_query(F.data == "admin_ban_user")
async def admin_ban_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminUserState.waiting_user_id)
    await state.update_data(action="ban")
    await callback.message.answer("Введите ID/ник/@username для блокировки:")
    await callback.answer()


@router.callback_query(F.data == "admin_unban_user")
async def admin_unban_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminUserState.waiting_user_id)
    await state.update_data(action="unban")
    await callback.message.answer("Введите ID/ник/@username для разблокировки:")
    await callback.answer()


@router.callback_query(F.data.startswith("ban_user:"))
async def ban_user_direct(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    user_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        ok = await set_user_ban_status(
            session, user_id, True, callback.from_user.id
        )
        user = await get_user_by_id(session, user_id)
    if ok:
        await callback.answer("🚫 Заблокирован!", show_alert=True)
        if user:
            try:
                await callback.bot.send_message(
                    user.telegram_id, "🚫 Вы заблокированы."
                )
            except Exception:
                pass
    else:
        await callback.answer("❌ Ошибка.", show_alert=True)


@router.callback_query(F.data.startswith("unban_user:"))
async def unban_user_direct(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    user_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        ok = await set_user_ban_status(
            session, user_id, False, callback.from_user.id
        )
        user = await get_user_by_id(session, user_id)
    if ok:
        await callback.answer("✅ Разблокирован!", show_alert=True)
        if user:
            try:
                await callback.bot.send_message(
                    user.telegram_id, "✅ Вы разблокированы."
                )
            except Exception:
                pass
    else:
        await callback.answer("❌ Ошибка.", show_alert=True)


# --- MESSAGE USER ---
@router.callback_query(F.data == "admin_message_user")
async def admin_message_user_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminUserState.waiting_user_id)
    await state.update_data(action="message")
    await callback.message.answer("Введите ID/ник/@username пользователя:")
    await callback.answer()


@router.message(AdminUserState.waiting_message_text)
async def process_message_text(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    data = await state.get_data()
    target_tg_id = data.get("target_tg_id")
    if not target_tg_id:
        await message.answer("❌ Ошибка: пользователь не найден.")
        await state.clear()
        return
    try:
        await message.bot.send_message(
            target_tg_id,
            f"📩 <b>Сообщение от администратора:</b>\n\n{message.text}",
            parse_mode="HTML"
        )
        await message.answer("✅ Сообщение отправлено!")
    except Exception as e:
        await message.answer(f"❌ Ошибка отправки: {e}")
    await state.clear()


# --- NICKNAME ---
@router.callback_query(F.data == "admin_change_nickname")
async def admin_change_nickname_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminNicknameState.waiting_user_id)
    await callback.message.answer("Введите ID/ник/@username пользователя:")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_set_nick:"))
async def admin_set_nick_direct(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    user_id = int(callback.data.split(":")[1])
    await state.set_state(AdminNicknameState.waiting_new_nick)
    await state.update_data(target_user_id=user_id)
    await callback.message.answer(
        "Введите новый ник (или 'сброс' для удаления):"
    )
    await callback.answer()


@router.message(AdminNicknameState.waiting_user_id)
async def admin_nick_process_user(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    query = message.text.strip()
    async with async_session() as session:
        user = None
        if query.startswith("@"):
            user = await get_user_by_username(session, query)
        elif query.isdigit():
            user = await get_user(session, int(query))
        else:
            user = await get_user_by_display_name(session, query)

        if not user:
            await message.answer("❌ Пользователь не найден.")
            await state.clear()
            return

        await state.update_data(target_user_id=user.id)
        await state.set_state(AdminNicknameState.waiting_new_nick)
        await message.answer(
            f"Введите новый ник для {get_display_name(user)} (или 'сброс'):"
        )


@router.message(AdminNicknameState.waiting_new_nick)
async def admin_nick_process_new(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    data = await state.get_data()
    target_user_id = data.get("target_user_id")
    new_nick = message.text.strip()

    async with async_session() as session:
        user = await get_user_by_id(session, target_user_id)
        if not user:
            await message.answer("❌ Пользователь не найден.")
            await state.clear()
            return

        if new_nick.lower() == "сброс":
            old = user.display_name
            user.display_name = None
            user.nickname_set = False
            await session.commit()
            await log_user_action(
                session, user.id,
                "admin_reset_nickname",
                f"By admin {message.from_user.id}, old={old}"
            )
            await message.answer(f"✅ Ник сброшен (был: {old}).")
        else:
            import re
            from app.config import NICKNAME_MIN_LENGTH, NICKNAME_MAX_LENGTH
            if len(new_nick) < NICKNAME_MIN_LENGTH or len(new_nick) > NICKNAME_MAX_LENGTH:
                await message.answer(
                    f"❌ Ник от {NICKNAME_MIN_LENGTH} до {NICKNAME_MAX_LENGTH} символов."
                )
                return
            if not re.match(r'^[a-zA-ZА-ЯЁа-яё0-9_\-]+$', new_nick):
                await message.answer("❌ Недопустимые символы в нике.")
                return

            existing = (await session.execute(
                select(User).where(
                    User.display_name == new_nick,
                    User.id != user.id
                )
            )).scalar_one_or_none()
            if existing:
                await message.answer("❌ Ник уже занят.")
                return

            old = user.display_name
            user.display_name = new_nick
            user.nickname_set = True
            await session.commit()
            await log_user_action(
                session, user.id,
                "admin_set_nickname",
                f"By admin {message.from_user.id}, {old} -> {new_nick}"
            )
            try:
                await message.bot.send_message(
                    user.telegram_id,
                    f"✏️ Администратор изменил ваш ник на: <b>{new_nick}</b>",
                    parse_mode="HTML"
                )
            except Exception:
                pass
            await message.answer(f"✅ Ник изменён: {old} → {new_nick}")
    await state.clear()


# --- BROADCAST ---
@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminBroadcastState.waiting_text)
    await callback.message.answer(
        "📢 Введите текст объявления для всех активных пользователей (поддерживается HTML):"
    )
    await callback.answer()


@router.message(AdminBroadcastState.waiting_text)
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
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        offers = (await session.execute(
            select(Offer).where(Offer.status == "pending")
            .order_by(Offer.created_at)
        )).scalars().all()

    if not offers:
        await callback.message.answer(
            "✅ Нет офферов на проверку.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀ Назад", callback_data="admin_offers_menu")]
            ])
        )
        await callback.answer()
        return

    kb_buttons = []
    for offer in offers:
        kb_buttons.append([InlineKeyboardButton(
            text=f"📢 {offer.title[:35]}",
            callback_data=f"admin_review_offer:{offer.id}"
        )])
    kb_buttons.append([InlineKeyboardButton(text="◀ Назад", callback_data="admin_offers_menu")])
    await callback.message.answer(
        f"⏳ <b>Офферы на проверку ({len(offers)})</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    )
    await callback.answer()


@router.callback_query(F.data == "admin_offers_all")
async def admin_offers_all(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        offers = (await session.execute(
            select(Offer).order_by(desc(Offer.created_at)).limit(25)
        )).scalars().all()

    if not offers:
        await callback.message.answer("Офферов нет.")
        await callback.answer()
        return

    text = "📋 <b>Все офферы (последние 25)</b>\n\n"
    for o in offers:
        icon = "✅" if o.is_active else ("⏳" if o.status == "pending" else "❌")
        rent_icon = "🔑" if getattr(o, "is_rentable", False) else ""
        text += (
            f"{icon}{rent_icon} #{o.id} <b>{o.title[:30]}</b>\n"
            f"  Статус: {o.status} | "
            f"Награда: {o.reward_preview}+{o.reward_final}\n"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_offers_menu")]
    ])
    if len(text) > 4000:
        text = text[:4000] + "\n..."
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_offers_active")
async def admin_offers_active(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        offers = (await session.execute(
            select(Offer).where(
                Offer.is_active,
                Offer.status == "approved"
            ).order_by(desc(Offer.created_at))
        )).scalars().all()

    if not offers:
        await callback.message.answer(
            "Нет активных офферов.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀ Назад", callback_data="admin_offers_menu")]
            ])
        )
        await callback.answer()
        return

    kb_buttons = []
    for o in offers:
        rent_icon = "🔑" if getattr(o, "is_rentable", False) else ""
        kb_buttons.append([InlineKeyboardButton(
            text=f"✅{rent_icon} #{o.id} {o.title[:30]}",
            callback_data=f"admin_review_offer:{o.id}"
        )])
    kb_buttons.append([InlineKeyboardButton(text="◀ Назад", callback_data="admin_offers_menu")])
    await callback.message.answer(
        f"✅ <b>Активные офферы ({len(offers)})</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_review_offer:"))
async def admin_review_offer(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    offer_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        offer = (await session.execute(
            select(Offer).where(Offer.id == offer_id)
        )).scalar_one_or_none()
        if not offer:
            await callback.answer("Не найдено.", show_alert=True)
            return

        participants = (await session.execute(
            select(func.count(OfferParticipation.id)).where(
                OfferParticipation.offer_id == offer_id
            )
        )).scalar_one()

        completed = (await session.execute(
            select(func.count(OfferParticipation.id)).where(
                OfferParticipation.offer_id == offer_id,
                OfferParticipation.status == "completed"
            )
        )).scalar_one()

        active_rentals_count = 0
        try:
            active_rentals_count = (await session.execute(
                )
            )).scalar_one()
        except Exception:
            pass

    is_rentable = getattr(offer, "is_rentable", False)
    rent_cost = getattr(offer, "rent_cost_per_day", 0)
    max_rentals = getattr(offer, "max_simultaneous_rentals", 0)

    text = (
        f"📢 <b>Оффер #{offer.id}</b>\n\n"
        f"Название: <b>{offer.title}</b>\n"
        f"Описание: {offer.description}\n"
        f"URL: {offer.channel_url}\n"
        f"Статус: <b>{offer.status}</b> | "
        f"Активен: {'✅' if offer.is_active else '❌'}\n"
        f"💰 Награда: {offer.reward_preview} + {offer.reward_final}\n"
        f"Участников: {participants} | Завершили: {completed}\n"
        f"🔑 Аренда: {'✅' if is_rentable else '❌'}"
    )
    if is_rentable:
        text += (
            f"\n  Цена: {rent_cost} монет/день\n"
            f"  Макс. арендаторов: {max_rentals}\n"
            f"  Активных аренд: {active_rentals_count}"
        )
    text += f"\n📅 Создан: {offer.created_at.strftime('%d.%m.%Y %H:%M')}"

    action_buttons = []
    if offer.status == "pending":
        action_buttons.append([
            InlineKeyboardButton(
                text="✅ Одобрить",
                callback_data=f"approve_offer:{offer_id}"
            ),
            InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data=f"reject_offer:{offer_id}"
            ),
        ])
    else:
        toggle_text = "🔴 Деактивировать" if offer.is_active else "🟢 Активировать"
        action_buttons.append([
            InlineKeyboardButton(
                text=toggle_text,
                callback_data=f"toggle_offer:{offer_id}"
            ),
        ])

    action_buttons.append([
        InlineKeyboardButton(
            text="🗑 Удалить",
            callback_data=f"delete_offer:{offer_id}"
        ),
    ])
    action_buttons.append([
        InlineKeyboardButton(text="◀ Назад", callback_data="admin_offers_menu")
    ])

    await callback.message.answer(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=action_buttons)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("approve_offer:"))
async def approve_offer_cb(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    offer_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        offer = (await session.execute(
            select(Offer).where(Offer.id == offer_id)
        )).scalar_one_or_none()
        if not offer:
            await callback.answer("Не найдено.", show_alert=True)
            return
        offer.status = "approved"
        offer.is_active = True
        await session.commit()

        if offer.creator_user_id:
            creator = await get_user_by_id(session, offer.creator_user_id)
            if creator:
                try:
                    await callback.bot.send_message(
                        creator.telegram_id,
                        f"✅ Ваш оффер «{offer.title}» одобрен и опубликован!"
                    )
                except Exception:
                    pass
    await callback.answer("✅ Оффер одобрен!", show_alert=True)


@router.callback_query(F.data.startswith("reject_offer:"))
async def reject_offer_cb(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    offer_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        offer = (await session.execute(
            select(Offer).where(Offer.id == offer_id)
        )).scalar_one_or_none()
        if not offer:
            await callback.answer("Не найдено.", show_alert=True)
            return
        offer.status = "rejected"
        offer.is_active = False
        await session.commit()

        if offer.creator_user_id:
            creator = await get_user_by_id(session, offer.creator_user_id)
            if creator:
                try:
                    await callback.bot.send_message(
                        creator.telegram_id,
                        f"❌ Ваш оффер «{offer.title}» отклонён."
                    )
                except Exception:
                    pass
    await callback.answer("❌ Оффер отклонён!", show_alert=True)


@router.callback_query(F.data.startswith("toggle_offer:"))
async def toggle_offer_cb(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    offer_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        offer = (await session.execute(
            select(Offer).where(Offer.id == offer_id)
        )).scalar_one_or_none()
        if not offer:
            await callback.answer("Не найдено.", show_alert=True)
            return
        offer.is_active = not offer.is_active
        await session.commit()
    status = "активирован ✅" if offer.is_active else "деактивирован 🔴"
    await callback.answer(f"Оффер {status}!", show_alert=True)


@router.callback_query(F.data.startswith("delete_offer:"))
async def delete_offer_cb(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    offer_id = int(callback.data.split(":")[1])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Да, удалить",
                callback_data=f"confirm_delete_offer:{offer_id}"
            ),
            InlineKeyboardButton(
                text="❌ Отмена",
                callback_data=f"admin_review_offer:{offer_id}"
            ),
        ]
    ])
    await callback.message.answer(
        f"⚠️ Удалить оффер #{offer_id}?\n"
        f"Это действие скроет оффер от пользователей.",
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_delete_offer:"))
async def confirm_delete_offer_cb(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    offer_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        offer = (await session.execute(
            select(Offer).where(Offer.id == offer_id)
        )).scalar_one_or_none()
        if not offer:
            await callback.answer("Не найдено.", show_alert=True)
            return
        offer.is_active = False
        offer.status = "deleted"
        await session.commit()
    await callback.answer(f"🗑 Оффер #{offer_id} удалён.", show_alert=True)


# =========================
# RENTALS MANAGEMENT
# =========================
@router.callback_query(F.data == "admin_rentals_menu")
async def admin_rentals_menu(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        try:
            active_count = await count_active_rentals(session)
            recent_rentals = (await session.execute(
                .limit(10)
            )).all()
        except Exception:
            active_count = 0
            recent_rentals = []

    text = f"🔑 <b>Управление арендой</b>\n\nАктивных аренд: {active_count}\n\n"

    kb_buttons = []
    if recent_rentals:
        text += "<b>Последние аренды:</b>\n"
        for rental, user, offer in recent_rentals:
            expires = rental.expires_at.strftime('%d.%m') if rental.expires_at else "???"
            text += (
                f"• {get_display_name(user)} → {offer.title[:20]}\n"
                f"  {rental.renter_channel_title[:25]} | "
                f"до {expires} | {rental.status}\n"
            )
            if rental.status == "pending":
                kb_buttons.append([InlineKeyboardButton(
                    text=f"⏳ Рассмотреть: {rental.renter_channel_title[:25]}",
                    callback_data=f"admin_review_rental:{rental.id}"
                )])

    kb_buttons.extend([
        [InlineKeyboardButton(
            text="⏰ Завершить просроченные",
            callback_data="admin_expire_rentals"
        )],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_offers_menu")],
    ])

    if len(text) > 4000:
        text = text[:4000] + "\n..."

    await callback.message.answer(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_review_rental:"))
async def admin_review_rental(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    rental_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        try:
            rental = (await session.execute(
            )).scalar_one_or_none()
        except Exception:
            rental = None

        if not rental:
            await callback.answer("Аренда не найдена.", show_alert=True)
            return

        renter = await get_user_by_id(session, rental.renter_user_id)
        offer = (await session.execute(
            select(Offer).where(Offer.id == rental.offer_id)
        )).scalar_one_or_none()

    text = (
        f"🔑 <b>Аренда #{rental.id}</b>\n\n"
        f"Арендатор: {get_display_name(renter) if renter else '???'}\n"
        f"Канал: {rental.renter_channel_title}\n"
        f"Ссылка: {rental.renter_channel_url}\n"
        f"Оффер: #{rental.offer_id} {offer.title if offer else '???'}\n"
        f"Дней: {rental.rent_days}\n"
        f"Оплачено: {rental.cost_paid} монет\n"
        f"Статус: {rental.status}\n"
        f"Создана: {rental.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"Истекает: {rental.expires_at.strftime('%d.%m.%Y') if rental.expires_at else '???'}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Одобрить",
                callback_data=f"approve_rental:{rental_id}"
            ),
            InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data=f"reject_rental:{rental_id}"
            ),
        ],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_rentals_menu")],
    ])
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("approve_rental:"))
async def approve_rental_cb(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    rental_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        try:
            rental = (await session.execute(
            )).scalar_one_or_none()
            if not rental:
                await callback.answer("Не найдено.", show_alert=True)
                return
            rental.status = "active"
            rental.expires_at = datetime.now(timezone.utc) + timedelta(days=rental.rent_days)
            await session.commit()

            renter = await get_user_by_id(session, rental.renter_user_id)
            if renter:
                try:
                    await callback.bot.send_message(
                        renter.telegram_id,
                        f"✅ Ваша аренда одобрена!\n"
                        f"Канал: {rental.renter_channel_title}\n"
                        f"Активна до: {rental.expires_at.strftime('%d.%m.%Y')}"
                    )
                except Exception:
                    pass
        except Exception as e:
            await callback.answer(f"Ошибка: {e}", show_alert=True)
            return
    await callback.answer("✅ Аренда одобрена!", show_alert=True)


@router.callback_query(F.data.startswith("reject_rental:"))
async def reject_rental_cb(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    rental_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        try:
            rental = (await session.execute(
            )).scalar_one_or_none()
            if not rental:
                await callback.answer("Не найдено.", show_alert=True)
                return

            rental.status = "rejected"
            renter = await get_user_by_id(session, rental.renter_user_id)
            if renter and rental.cost_paid > 0:
                from app.services import log_balance_change
                await log_balance_change(
                    session,
                    renter,
                    rental.cost_paid,
                    "rental_refund",
                    source_id=rental_id,
                    details="Возврат за отклонённую аренду",
                )
                renter.balance += rental.cost_paid
            await session.commit()

            if renter:
                try:
                    await callback.bot.send_message(
                        renter.telegram_id,
                        f"❌ Ваша аренда отклонена.\n"
                        f"Возврат: {rental.cost_paid} монет"
                    )
                except Exception:
                    pass
        except Exception as e:
            await callback.answer(f"Ошибка: {e}", show_alert=True)
            return
    await callback.answer("❌ Аренда отклонена, возврат выполнен.", show_alert=True)


@router.callback_query(F.data == "admin_expire_rentals")
async def admin_expire_rentals_cb(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        try:
            expired = await expire_old_rentals(session)
            await callback.answer(f"✅ Завершено просроченных аренд: {expired}", show_alert=True)
        except Exception as e:
            await callback.answer(f"❌ Ошибка: {e}", show_alert=True)


# =========================
# ADMIN MANAGEMENT
# =========================
@router.callback_query(F.data == "admin_manage_admins")
async def manage_admins_menu(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer()
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список", callback_data="admin_list_admins")],
        [InlineKeyboardButton(text="➕ Добавить", callback_data="admin_add_admin")],
        [InlineKeyboardButton(text="➖ Удалить", callback_data="admin_remove_admin")],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")],
    ])
    await _safe_edit(
        callback,
        "👮 <b>Управление администраторами</b>",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data == "admin_list_admins")
async def list_admins(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        admins = (await session.execute(
            select(User).where(User.is_admin)
        )).scalars().all()

    text = "👮 <b>Администраторы бота:</b>\n\n"
    if not admins:
        text += "Дополнительных администраторов нет."
    else:
        for a in admins:
            text += (
                f"• {get_display_name(a)} "
                f"(ID: <code>{a.telegram_id}</code>)\n"
            )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_manage_admins")]
    ])
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_add_admin")
async def add_admin_start(callback: CallbackQuery, state: FSMContext):
    if not is_super_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminManageState.waiting_new_admin)
    await callback.message.answer(
        "Введите Telegram ID пользователя для назначения администратором:"
    )
    await callback.answer()


@router.message(AdminManageState.waiting_new_admin)
async def process_add_admin(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        return
    if not message.text.isdigit():
        await message.answer("❌ Введите числовой Telegram ID.")
        return
    telegram_id = int(message.text)
    async with async_session() as session:
        user = await get_user(session, telegram_id)
        if not user:
            await message.answer(
                "❌ Пользователь не найден.\n"
                "Попросите его отправить боту /start."
            )
            await state.clear()
            return
        if user.is_admin:
            await message.answer("Этот пользователь уже является администратором.")
            await state.clear()
            return
        user.is_admin = True
        await session.commit()

    await message.answer(
        f"✅ Пользователь <code>{telegram_id}</code> назначен администратором.",
        parse_mode="HTML"
    )
    try:
        await message.bot.send_message(
            telegram_id,
            "🎉 Вам выдана роль администратора бота!"
        )
    except Exception:
        pass
    await state.clear()


@router.callback_query(F.data == "admin_remove_admin")
async def remove_admin_start(callback: CallbackQuery, state: FSMContext):
    if not is_super_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminManageState.waiting_remove_admin)
    await callback.message.answer(
        "Введите Telegram ID администратора для снятия прав:"
    )
    await callback.answer()


@router.message(AdminManageState.waiting_remove_admin)
async def process_remove_admin(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        return
    if not message.text.isdigit():
        await message.answer("❌ Введите числовой Telegram ID.")
        return
    telegram_id = int(message.text)
    if telegram_id in ADMINS:
        await message.answer(
            "❌ Нельзя снять права у супер-администратора."
        )
        await state.clear()
        return
    async with async_session() as session:
        user = await get_user(session, telegram_id)
        if not user or not user.is_admin:
            await message.answer("❌ Этот пользователь не является администратором.")
            await state.clear()
            return
        user.is_admin = False
        await session.commit()

    await message.answer(
        f"✅ Права администратора сняты у <code>{telegram_id}</code>.",
        parse_mode="HTML"
    )
    try:
        await message.bot.send_message(
            telegram_id,
            "Ваши права администратора были отозваны."
        )
    except Exception:
        pass
    await state.clear()


class SaleState(StatesGroup):
    waiting_percent = State()
    waiting_scope = State()
    waiting_duration = State()
    waiting_text = State()

@router.callback_query(F.data == "admin_sales")
async def admin_sales_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    from app.services import get_active_sale
    async with async_session() as session:
        sale = await get_active_sale(session)
    
    text = "🛍 <b>Управление акциями</b>\n\n"
    if sale:
        text += (
            f"🟢 <b>Текущая акция активна!</b>\n"
            f"Скидка: <b>{sale.discount_percent}%</b>\n"
            f"Действует на: <b>{sale.applies_to}</b>\n"
            f"Закончится: <b>{sale.end_date.strftime('%d.%m.%Y %H:%M')} UTC</b>\n"
            f"Текст:\n<i>{sale.announcement}</i>\n\n"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛑 Завершить акцию", callback_data="admin_sale_stop")],
            [InlineKeyboardButton(text="◀ В меню", callback_data="admin_center")]
        ])
    else:
        text += "🔴 В данный момент нет активных акций."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать акцию", callback_data="admin_sale_create")],
            [InlineKeyboardButton(text="◀ В меню", callback_data="admin_center")]
        ])

    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "admin_sale_stop")
async def admin_sale_stop(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        return
    
    from app.services import get_active_sale
    async with async_session() as session:
        sale = await get_active_sale(session)
        if sale:
            from datetime import datetime
            sale.end_date = datetime.utcnow()
            await session.commit()
            await callback.answer("✅ Акция досрочно завершена!", show_alert=True)
        else:
            await callback.answer("Акция уже неактивна.", show_alert=True)
    
    await admin_sales_start(callback, None)

@router.callback_query(F.data == "admin_sale_create")
async def admin_sale_create(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        return
    await state.set_state(SaleState.waiting_percent)
    await _safe_edit(callback, "Введите процент скидки (от 1 до 99):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="admin_center")]
    ]))

@router.message(SaleState.waiting_percent)
async def admin_sale_percent(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("Пожалуйста, введите число от 1 до 99.")
        return
    pct = int(message.text)
    if pct < 1 or pct > 99:
        await message.answer("Процент должен быть от 1 до 99.")
        return
    await state.update_data(discount_percent=pct)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="На всё", callback_data="sale_scope:all")],
        [InlineKeyboardButton(text="Только VIP", callback_data="sale_scope:vip")],
        [InlineKeyboardButton(text="Только Монеты", callback_data="sale_scope:coins")],
        [InlineKeyboardButton(text="Отмена", callback_data="admin_center")]
    ])
    await state.set_state(SaleState.waiting_scope)
    await message.answer("Выберите, на что действует скидка:", reply_markup=kb)

@router.callback_query(SaleState.waiting_scope, F.data.startswith("sale_scope:"))
async def admin_sale_scope(callback: CallbackQuery, state: FSMContext):
    scope = callback.data.split(":")[1]
    await state.update_data(applies_to=scope)
    await state.set_state(SaleState.waiting_duration)
    await _safe_edit(callback, "Введите длительность акции в часах (например, 24):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="admin_center")]
    ]))
    await callback.answer()

@router.message(SaleState.waiting_duration)
async def admin_sale_duration(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("Пожалуйста, введите количество часов числом.")
        return
    hours = int(message.text)
    if hours < 1:
        await message.answer("Минимум 1 час.")
        return
    await state.update_data(duration_hours=hours)
    
    await state.set_state(SaleState.waiting_text)
    await message.answer(
        "Напишите текст рекламного объявления (поддерживается HTML).\n"
        "Это сообщение будет разослано всем пользователям вместе с картинкой-флаером."
    )

@router.message(SaleState.waiting_text)
async def admin_sale_finish(message: Message, state: FSMContext):
    data = await state.get_data()
    from datetime import datetime, timedelta
    from app.models import ActiveSale
    import os
    from aiogram.types import FSInputFile
    
    end_date = datetime.utcnow() + timedelta(hours=data["duration_hours"])
    
    async with async_session() as session:
        sale = ActiveSale(
            discount_percent=data["discount_percent"],
            applies_to=data["applies_to"],
            end_date=end_date,
            announcement=message.text
        )
        session.add(sale)
        await session.commit()
    
    await state.clear()
    await message.answer(f"✅ Акция успешно создана и будет действовать до {end_date.strftime('%d.%m.%Y %H:%M')} UTC!")
    
    # Trigger broadcast to all users
    # In a real heavy app we'd use a background worker, but for MVP we loop here
    async with async_session() as session:
        from app.models import User
        from sqlalchemy import select
        users = (await session.execute(select(User))).scalars().all()
    
    import asyncio
    sent = 0
    await message.answer("⏳ Начинаю рассылку флаера всем пользователям...")
    for u in users:
        try:
            if os.path.exists("app/flyer_sale.jpg"):
                await message.bot.send_photo(u.telegram_id, photo=FSInputFile("app/flyer_sale.jpg"), caption=message.text, parse_mode="HTML")
            else:
                await message.bot.send_message(u.telegram_id, message.text, parse_mode="HTML")
            sent += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)
        
    await message.answer(f"✅ Рассылка завершена. Доставлено: {sent} пользователям.")

