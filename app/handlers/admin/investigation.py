"""
Investigation / admin detective tools.
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, func, desc, text
from datetime import datetime, timedelta
import asyncio

from app.db import async_session
from app.models import User, GameHistory, BalanceLog
from app.services import get_user, get_user_by_id, get_display_name, get_user_dossier
from app.utils.admin import check_admin
from app.keyboards import admin_after_action_keyboard

router = Router()

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

        rental_rows = []  # Rentals disabled

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

        rental_rows = []  # Rentals disabled

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
