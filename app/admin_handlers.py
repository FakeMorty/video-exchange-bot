from datetime import datetime
from decimal import Decimal
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, func, desc

from app.config import ADMINS
from app.db import async_session
from app.models import User, Video, Offer, BalanceLog, GameHistory, UserActionLog
from app.services import (
    get_user,
    get_user_by_id,
    get_user_by_username,
    get_user_dossier,
    update_user_balance,
    set_user_ban_status,
    count_pending_videos,
    count_approved_videos,
    count_rejected_videos,
    get_next_pending_video,
    approve_video,
    reject_video,
    get_admin_extended_stats,
    to_decimal,
    get_display_name,
)

router = Router()


# =========================
# STATES
# =========================
class AdminUserState(StatesGroup):
    waiting_user_id = State()
    waiting_coins_amount = State()
    waiting_message_text = State()
    waiting_ban_id = State()
    waiting_unban_id = State()
    waiting_dossier_id = State()


class AdminManageState(StatesGroup):
    waiting_new_admin = State()
    waiting_remove_admin = State()


class AdminBroadcastState(StatesGroup):
    waiting_text = State()


class AdminNicknameState(StatesGroup):
    waiting_user_id = State()
    waiting_new_nick = State()


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


def admin_main_keyboard(is_super: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📊 Очередь", callback_data="admin_queue_info")],
        [InlineKeyboardButton(text="📈 Статистика+", callback_data="admin_extended_stats")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_manage_users")],
        [InlineKeyboardButton(text="🎬 Модерация", callback_data="admin_get_pending")],
        [InlineKeyboardButton(text="✅ Одобрить все", callback_data="admin_approve_all")],
        [InlineKeyboardButton(text="📢 Офферы", callback_data="admin_offers_menu")],
        [InlineKeyboardButton(text="🔍 Расследование", callback_data="admin_investigation")],
    ]
    if is_super:
        buttons.append([InlineKeyboardButton(text="⚙️ Управление админами", callback_data="admin_manage_admins")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# =========================
# ADMIN PANEL ENTRY
# =========================
@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not await check_admin(message.from_user.id):
        return
    sa = is_super_admin(message.from_user.id)
    await message.answer(
        "🛡 <b>Админ-панель</b>",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard(is_super=sa)
    )


@router.callback_query(F.data == "admin_center")
async def admin_center(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    sa = is_super_admin(callback.from_user.id)
    try:
        await callback.message.edit_text(
            "🛡 <b>Админ-панель</b>",
            parse_mode="HTML",
            reply_markup=admin_main_keyboard(is_super=sa)
        )
    except Exception:
        await callback.message.answer(
            "🛡 <b>Админ-панель</b>",
            parse_mode="HTML",
            reply_markup=admin_main_keyboard(is_super=sa)
        )
    await callback.answer()


@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    await cmd_admin(callback.message)
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
        [InlineKeyboardButton(text="🎬 Начать модерацию", callback_data="admin_get_pending")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_center")]
    ])
    text = (
        f"📊 <b>Очередь</b>\n\n"
        f"⏳ На проверке: <b>{p}</b>\n"
        f"✅ Одобрено: <b>{a}</b>\n"
        f"❌ Отклонено: <b>{r}</b>"
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
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
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_center")]
    ])
    text = (
        f"📈 <b>Расширенная статистика</b>\n\n"
        f"👥 Пользователей: <b>{stats['users']}</b>\n"
        f"👑 VIP: <b>{stats['vip']}</b>\n"
        f"🏷 С никами: <b>{stats['with_nickname']}</b>\n"
        f"💬 Комментариев: <b>{stats['comments']}</b>\n"
        f"😀 Реакций: <b>{stats['reactions']}</b>\n"
        f"🎮 Игр: <b>{stats['games']}</b>\n"
        f"📢 Офферов: <b>{stats['offers']}</b>\n\n"
        f"💰 Монет в системе: <b>{stats['total_balance_in_system']:.2f}</b>\n"
        f"🎁 Выдано админами: <b>{stats['total_admin_given']:.2f}</b>\n"
        f"🎮 Профит игр (выигрыши-проигрыши): <b>{stats['total_game_profit']:.2f}</b>"
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# =========================
# INVESTIGATION (РАССЛЕДОВАНИЕ)
# =========================
@router.callback_query(F.data == "admin_investigation")
async def admin_investigation(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Подозрительные игры", callback_data="inv_suspicious_games")],
        [InlineKeyboardButton(text="💰 Топ богатых (детально)", callback_data="inv_rich_detail")],
        [InlineKeyboardButton(text="📋 Лог балансов (последние)", callback_data="inv_balance_log")],
        [InlineKeyboardButton(text="🔍 Досье по ID/нику", callback_data="admin_user_dossier")],
        [InlineKeyboardButton(text="📊 Экспорт для нейронки", callback_data="inv_export_ai")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_center")],
    ])
    await callback.message.answer(
        "🔍 <b>Центр расследований</b>\n\n"
        "Выберите инструмент:",
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
        # Игроки с аномально большим профитом за последние 7 дней
        from datetime import timedelta
        week_ago = datetime.utcnow() - timedelta(days=7)
        result = await session.execute(
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
        )
        rows = result.all()

    if not rows:
        await callback.message.answer("✅ Подозрительных игр не найдено.")
        await callback.answer()
        return

    text = "🎮 <b>Подозрительные игроки (за 7 дней)</b>\n\n"
    for row in rows:
        u, games, profit, total_bet = row
        win_rate = (float(profit) + float(total_bet)) / float(total_bet) * 100 if total_bet else 0
        text += (
            f"👤 {get_display_name(u)} (ID: <code>{u.telegram_id}</code>)\n"
            f"   Игр: {games} | Профит: {profit:.2f} | Ставки: {total_bet:.2f}\n"
            f"   💰 Баланс: {u.balance:.2f}\n\n"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_investigation")]
    ])
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "inv_rich_detail")
async def inv_rich_detail(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    async with async_session() as session:
        result = await session.execute(
            select(User).order_by(desc(User.balance)).limit(15)
        )
        users = result.scalars().all()

        text = "💰 <b>Топ богатых (детально)</b>\n\n"
        for i, u in enumerate(users, 1):
            # Источники дохода
            admin_given = (await session.execute(
                select(func.sum(BalanceLog.amount)).where(
                    BalanceLog.user_id == u.id,
                    BalanceLog.source == "admin_balance",
                    BalanceLog.amount > 0
                )
            )).scalar_one() or Decimal("0")

            game_profit = (await session.execute(
                select(func.sum(GameHistory.result)).where(GameHistory.user_id == u.id)
            )).scalar_one() or Decimal("0")

            text += (
                f"{i}. <b>{get_display_name(u)}</b> — {u.balance:.2f} монет\n"
                f"   🎁 От админа: {admin_given:.2f} | 🎮 Игры: {game_profit:.2f}\n"
                f"   🆔 <code>{u.telegram_id}</code>\n\n"
            )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_investigation")]
    ])
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "inv_balance_log")
async def inv_balance_log(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    async with async_session() as session:
        result = await session.execute(
            select(BalanceLog, User)
            .join(User, User.id == BalanceLog.user_id)
            .order_by(desc(BalanceLog.created_at))
            .limit(30)
        )
        rows = result.all()

    if not rows:
        await callback.message.answer("Лог пуст.")
        await callback.answer()
        return

    text = "📋 <b>Последние 30 изменений баланса</b>\n\n"
    for log, u in rows:
        sign = "+" if log.amount >= 0 else ""
        text += (
            f"{log.created_at.strftime('%d.%m %H:%M')} | "
            f"<b>{get_display_name(u)}</b> | "
            f"{sign}{log.amount:.2f} ({log.source})\n"
            f"  {log.balance_before:.2f} → {log.balance_after:.2f}\n"
        )
        if log.details:
            text += f"  📝 {log.details}\n"
        text += "\n"

    # Telegram лимит 4096 символов
    if len(text) > 4000:
        text = text[:4000] + "\n... (обрезано)"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_investigation")]
    ])
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "inv_export_ai")
async def inv_export_ai(callback: CallbackQuery):
    """Экспорт данных в текстовом формате для анализа нейронкой."""
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    async with async_session() as session:
        # Топ по балансу
        rich_result = await session.execute(
            select(User).order_by(desc(User.balance)).limit(10)
        )
        rich_users = rich_result.scalars().all()

        # Подозрительные игры за всё время
        from datetime import timedelta
        suspicious = await session.execute(
            select(User, func.sum(GameHistory.result).label("profit"), func.count(GameHistory.id).label("games"))
            .join(GameHistory, GameHistory.user_id == User.id)
            .group_by(User.id)
            .having(func.sum(GameHistory.result) > 30)
            .order_by(desc("profit"))
            .limit(10)
        )
        sus_rows = suspicious.all()

        # Последние выдачи от админов
        admin_logs = await session.execute(
            select(BalanceLog, User)
            .join(User, User.id == BalanceLog.user_id)
            .where(BalanceLog.source == "admin_balance")
            .order_by(desc(BalanceLog.created_at))
            .limit(20)
        )
        admin_rows = admin_logs.all()

    report = "=== ОТЧЁТ ДЛЯ АНАЛИЗА ===\n"
    report += f"Дата: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC\n\n"

    report += "--- ТОП 10 БОГАТЫХ ---\n"
    for i, u in enumerate(rich_users, 1):
        report += f"{i}. nick={get_display_name(u)} tg_id={u.telegram_id} balance={u.balance} level={u.level} created={u.created_at.strftime('%Y-%m-%d')}\n"

    report += "\n--- ПОДОЗРИТЕЛЬНЫЕ ИГРОКИ (ВЫСОКИЙ ПРОФИТ) ---\n"
    for row in sus_rows:
        u, profit, games = row
        report += f"nick={get_display_name(u)} tg_id={u.telegram_id} game_profit={profit:.2f} games={games} current_balance={u.balance}\n"

    report += "\n--- ПОСЛЕДНИЕ ВЫДАЧИ МОНЕТ АДМИНАМИ ---\n"
    for log, u in admin_rows:
        report += f"date={log.created_at.strftime('%Y-%m-%d %H:%M')} admin_id={log.admin_id} user={get_display_name(u)}(tg={u.telegram_id}) amount={log.amount} before={log.balance_before} after={log.balance_after}\n"

    report += "\n=== КОНЕЦ ОТЧЁТА ==="

    # Отправляем как документ
    from io import BytesIO
    buf = BytesIO(report.encode("utf-8"))
    buf.name = f"report_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.txt"

    await callback.message.answer_document(
        buf,
        caption="📊 Отчёт для анализа. Можно отправить нейронке для расследования."
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
            await callback.message.answer("✅ Нет видео на модерации!")
            await callback.answer()
            return

        uploader = await get_user_by_id(session, video.uploader_user_id)
        uploader_name = get_display_name(uploader) if uploader else "???"
        uploader_tg = uploader.telegram_id if uploader else "???"

    from app.keyboards import moderation_keyboard
    caption = (
        f"🎬 #{video.id}\n"
        f"👤 {uploader_name} (tg: {uploader_tg})\n"
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
            f"⚠️ Медиа недоступно: {e}\n{caption}",
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
            await callback.answer("Видео не найдено или уже обработано.", show_alert=True)
            return
        uploader = await get_user_by_id(session, video.uploader_user_id)

    if uploader:
        try:
            await callback.bot.send_message(
                uploader.telegram_id,
                f"✅ Ваш контент #{video_id} одобрен! Монеты начислены."
            )
        except Exception:
            pass

    from app.keyboards import admin_after_action_keyboard
    await callback.message.answer(
        f"✅ Видео #{video_id} одобрено!",
        reply_markup=admin_after_action_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("mod_reject:"))
async def mod_reject(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    video_id = int(callback.data.split(":")[1])
    from app.keyboards import rejection_reason_keyboard
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
    reason = parts[2]
    reason_texts = {
        "duplicate": "Дубликат",
        "off_topic": "Не по теме",
        "other": "Другая причина"
    }
    reason_text = reason_texts.get(reason, reason)

    async with async_session() as session:
        video = await reject_video(session, video_id, reason_text)
        if not video:
            await callback.answer("Видео не найдено.", show_alert=True)
            return
        uploader = await get_user_by_id(session, video.uploader_user_id)

    if uploader:
        try:
            await callback.bot.send_message(
                uploader.telegram_id,
                f"❌ Контент #{video_id} отклонён.\nПричина: {reason_text}"
            )
        except Exception:
            pass

    from app.keyboards import admin_after_action_keyboard
    await callback.message.answer(
        f"❌ #{video_id} отклонено. Причина: {reason_text}",
        reply_markup=admin_after_action_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "admin_approve_all")
async def admin_approve_all(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    count = 0
    async with async_session() as session:
        while True:
            video = await get_next_pending_video(session)
            if not video:
                break
            await approve_video(session, video.id)
            count += 1
            if count >= 100:
                break

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ В панель", callback_data="admin_center")]
    ])
    await callback.message.answer(
        f"✅ Одобрено: <b>{count}</b>",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


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
        [InlineKeyboardButton(text="📨 Написать", callback_data="admin_message_user")],
        [InlineKeyboardButton(text="✏️ Сменить ник", callback_data="admin_change_nickname")],
        [InlineKeyboardButton(text="📣 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_center")],
    ])
    try:
        await callback.message.edit_text(
            "👥 <b>Управление пользователями</b>",
            parse_mode="HTML",
            reply_markup=kb
        )
    except Exception:
        await callback.message.answer(
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
    await callback.message.answer("Введите Telegram ID или @username или ник пользователя:")
    await callback.answer()


@router.message(AdminUserState.waiting_dossier_id)
async def process_dossier(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    async with async_session() as session:
        user = None
        query = message.text.strip()
        if query.startswith("@"):
            user = await get_user_by_username(session, query)
        elif query.isdigit():
            user = await get_user(session, int(query))
        else:
            # Поиск по нику
            from app.services import get_user_by_display_name
            user = await get_user_by_display_name(session, query)
            if not user:
                # Поиск по username без @
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

    # Подозрительность
    suspicion = []
    if dossier["game_profit"] > 100:
        suspicion.append(f"⚠️ Высокий игровой профит: {dossier['game_profit']:.2f}")
    if dossier["admin_given"] > 200:
        suspicion.append(f"⚠️ Много монет от админа: {dossier['admin_given']:.2f}")
    if dossier["suspicious_games"]:
        suspicion.append(f"⚠️ Крупные выигрыши: {len(dossier['suspicious_games'])} раз")

    suspicion_text = "\n".join(suspicion) if suspicion else "✅ Подозрений нет"

    logs_text = ""
    for log in dossier["logs"][:5]:
        logs_text += f"  • {log.action} ({log.created_at.strftime('%d.%m %H:%M')})\n"
        if log.details:
            logs_text += f"    {log.details[:50]}\n"

    balance_logs_text = ""
    for bl in dossier["balance_logs"][:5]:
        sign = "+" if bl.amount >= 0 else ""
        balance_logs_text += (
            f"  {bl.created_at.strftime('%d.%m %H:%M')} "
            f"{sign}{bl.amount:.2f} [{bl.source}] "
            f"{bl.balance_before:.2f}→{bl.balance_after:.2f}\n"
        )

    text = (
        f"📋 <b>Досье: {get_display_name(u)}</b>\n\n"
        f"🆔 TG: <code>{u.telegram_id}</code>\n"
        f"🏷 Ник: {u.display_name or 'не установлен'}\n"
        f"👤 Имя: {u.first_name or '???'} {u.last_name or ''}\n"
        f"📱 @{u.username or '???'}\n"
        f"💰 Баланс: <b>{u.balance:.2f}</b>\n"
        f"🏆 Ур. {u.level} | XP: {u.xp}\n"
        f"📊 Статус: {u.status}\n"
        f"👑 VIP: {'Да' if u.vip_until and u.vip_until > datetime.utcnow() else 'Нет'}\n"
        f"📅 Рег.: {u.created_at.strftime('%d.%m.%Y')}\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"🎬 Загружено: {dossier['videos_uploaded']}\n"
        f"👁 Просмотрено: {dossier['videos_watched']}\n"
        f"🎮 Игр: {dossier['games_count']} | Профит: {dossier['game_profit']:.2f}\n"
        f"💰 Заработано всего: {dossier['total_earned']:.2f}\n"
        f"💸 Потрачено всего: {dossier['total_spent']:.2f}\n"
        f"🎁 От админов: {dossier['admin_given']:.2f}\n\n"
        f"🔍 <b>Анализ:</b>\n{suspicion_text}\n\n"
        f"📝 <b>Действия:</b>\n{logs_text or 'Нет'}\n"
        f"💳 <b>Баланс-лог:</b>\n{balance_logs_text or 'Нет'}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Монеты", callback_data=f"give_coins_to:{u.id}"),
            InlineKeyboardButton(text="🚫 Бан", callback_data=f"ban_user:{u.id}"),
        ],
        [
            InlineKeyboardButton(text="✅ Разбан", callback_data=f"unban_user:{u.id}"),
            InlineKeyboardButton(text="✏️ Ник", callback_data=f"admin_set_nick:{u.id}"),
        ],
        [InlineKeyboardButton(text="📋 Полный лог баланса", callback_data=f"full_balance_log:{u.id}")],
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
            await callback.answer("Пользователь не найден.", show_alert=True)
            return

        logs = (await session.execute(
            select(BalanceLog).where(BalanceLog.user_id == user_id)
            .order_by(desc(BalanceLog.created_at))
            .limit(50)
        )).scalars().all()

    report = f"=== ЛОГО БАЛАНСА: {get_display_name(u)} (tg={u.telegram_id}) ===\n"
    report += f"Текущий баланс: {u.balance}\n\n"
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

    from io import BytesIO
    buf = BytesIO(report.encode("utf-8"))
    buf.name = f"balance_log_{u.telegram_id}.txt"
    await callback.message.answer_document(
        buf,
        caption=f"💳 Полный лог баланса: {get_display_name(u)}"
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
    await callback.message.answer("Введите Telegram ID пользователя:")
    await callback.answer()


@router.callback_query(F.data.startswith("give_coins_to:"))
async def give_coins_to_user(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    user_id = int(callback.data.split(":")[1])
    await state.set_state(AdminUserState.waiting_coins_amount)
    await state.update_data(target_user_id=user_id)
    await callback.message.answer("Введите количество монет (+добавить, -снять):")
    await callback.answer()


@router.message(AdminUserState.waiting_user_id)
async def process_user_id_for_action(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    data = await state.get_data()
    action = data.get("action")
    query = message.text.strip()

    async with async_session() as session:
        if query.isdigit():
            user = await get_user(session, int(query))
        elif query.startswith("@"):
            user = await get_user_by_username(session, query)
        else:
            from app.services import get_user_by_display_name
            user = await get_user_by_display_name(session, query)

        if not user:
            await message.answer("❌ Пользователь не найден.")
            await state.clear()
            return
        await state.update_data(target_user_id=user.id, target_tg_id=user.telegram_id)

    if action == "give_coins":
        await state.set_state(AdminUserState.waiting_coins_amount)
        await message.answer("Введите количество монет:")
    elif action == "ban":
        async with async_session() as session:
            ok = await set_user_ban_status(session, user.id, True, message.from_user.id)
        await message.answer(f"🚫 Пользователь {user.telegram_id} заблокирован." if ok else "❌ Ошибка.")
        await state.clear()
    elif action == "unban":
        async with async_session() as session:
            ok = await set_user_ban_status(session, user.id, False, message.from_user.id)
        await message.answer(f"✅ Пользователь {user.telegram_id} разблокирован." if ok else "❌ Ошибка.")
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
        await message.answer("❌ Введите число (например: 50 или -10).")
        return

    data = await state.get_data()
    target_user_id = data.get("target_user_id")
    if not target_user_id:
        await message.answer("❌ Ошибка.")
        await state.clear()
        return

    async with async_session() as session:
        ok = await update_user_balance(session, target_user_id, amount, message.from_user.id)
        if ok:
            user = await get_user_by_id(session, target_user_id)
            name = get_display_name(user) if user else str(target_user_id)
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
                        f"💰 Ваш баланс изменён администратором: {'+' if amount > 0 else ''}{amount} монет"
                    )
                except Exception:
                    pass
        else:
            await message.answer("❌ Ошибка обновления баланса.")
    await state.clear()


# --- BAN / UNBAN ---
@router.callback_query(F.data == "admin_ban_user")
async def admin_ban_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminUserState.waiting_user_id)
    await state.update_data(action="ban")
    await callback.message.answer("Введите Telegram ID / @username / ник для блокировки:")
    await callback.answer()


@router.callback_query(F.data == "admin_unban_user")
async def admin_unban_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminUserState.waiting_user_id)
    await state.update_data(action="unban")
    await callback.message.answer("Введите Telegram ID / @username / ник для разблокировки:")
    await callback.answer()


@router.callback_query(F.data.startswith("ban_user:"))
async def ban_user_direct(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    user_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        ok = await set_user_ban_status(session, user_id, True, callback.from_user.id)
        user = await get_user_by_id(session, user_id)
    if ok:
        await callback.answer("🚫 Заблокирован!", show_alert=True)
        if user:
            try:
                await callback.bot.send_message(user.telegram_id, "🚫 Вы заблокированы.")
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
        ok = await set_user_ban_status(session, user_id, False, callback.from_user.id)
        user = await get_user_by_id(session, user_id)
    if ok:
        await callback.answer("✅ Разблокирован!", show_alert=True)
        if user:
            try:
                await callback.bot.send_message(user.telegram_id, "✅ Блокировка снята.")
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
    await callback.message.answer("Введите Telegram ID / @username / ник:")
    await callback.answer()


@router.message(AdminUserState.waiting_message_text)
async def process_message_text(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    data = await state.get_data()
    target_tg_id = data.get("target_tg_id")
    if not target_tg_id:
        await message.answer("❌ Ошибка.")
        await state.clear()
        return
    try:
        await message.bot.send_message(
            target_tg_id,
            f"📨 <b>Сообщение от администратора:</b>\n\n{message.text}",
            parse_mode="HTML"
        )
        await message.answer("✅ Сообщение отправлено!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
    await state.clear()


# --- ADMIN CHANGE NICKNAME ---
@router.callback_query(F.data == "admin_change_nickname")
async def admin_change_nickname_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminNicknameState.waiting_user_id)
    await callback.message.answer("Введите Telegram ID / @username / ник пользователя:")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_set_nick:"))
async def admin_set_nick_direct(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    user_id = int(callback.data.split(":")[1])
    await state.set_state(AdminNicknameState.waiting_new_nick)
    await state.update_data(target_user_id=user_id)
    await callback.message.answer("Введите новый ник для пользователя (или 'сброс' для удаления):")
    await callback.answer()


@router.message(AdminNicknameState.waiting_user_id)
async def admin_nick_process_user(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    query = message.text.strip()
    async with async_session() as session:
        if query.isdigit():
            user = await get_user(session, int(query))
        elif query.startswith("@"):
            user = await get_user_by_username(session, query)
        else:
            from app.services import get_user_by_display_name
            user = await get_user_by_display_name(session, query)
        if not user:
            await message.answer("❌ Пользователь не найден.")
            await state.clear()
            return
        await state.update_data(target_user_id=user.id)
    await state.set_state(AdminNicknameState.waiting_new_nick)
    await message.answer(f"Введите новый ник для {get_display_name(user)} (или 'сброс'):")


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
            from app.services import log_user_action
            await log_user_action(session, user.id, "admin_reset_nickname", f"By admin {message.from_user.id}, old={old}")
            await message.answer(f"✅ Ник пользователя сброшен (был: {old}).")
        else:
            # Используем обычную валидацию но без проверки баланса
            import re
            from app.config import NICKNAME_MIN_LENGTH, NICKNAME_MAX_LENGTH
            if len(new_nick) < NICKNAME_MIN_LENGTH or len(new_nick) > NICKNAME_MAX_LENGTH:
                await message.answer(f"❌ Ник от {NICKNAME_MIN_LENGTH} до {NICKNAME_MAX_LENGTH} символов.")
                return
            if not re.match(r'^[a-zA-Zа-яА-ЯёЁ0-9_\-]+$', new_nick):
                await message.answer("❌ Неверные символы в нике.")
                return

            existing = await session.execute(
                select(User).where(User.display_name == new_nick, User.id != user.id)
            )
            if existing.scalar_one_or_none():
                await message.answer("❌ Этот ник уже занят.")
                return

            old = user.display_name
            user.display_name = new_nick
            user.nickname_set = True
            await session.commit()
            from app.services import log_user_action
            await log_user_action(
                session, user.id, "admin_set_nickname",
                f"By admin {message.from_user.id}, {old} -> {new_nick}"
            )
            # Уведомляем
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
    await callback.message.answer("📣 Введите текст рассылки (HTML поддерживается):")
    await callback.answer()


@router.message(AdminBroadcastState.waiting_text)
async def process_broadcast(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    await state.clear()

    async with async_session() as session:
        result = await session.execute(
            select(User.telegram_id).where(User.status == "active")
        )
        tg_ids = result.scalars().all()

    sent = failed = 0
    for tg_id in tg_ids:
        try:
            await message.bot.send_message(
                tg_id,
                f"📣 <b>Объявление:</b>\n\n{message.text}",
                parse_mode="HTML"
            )
            sent += 1
        except Exception:
            failed += 1

    await message.answer(f"📣 Рассылка завершена!\n✅ {sent}\n❌ {failed}")


# =========================
# OFFERS MANAGEMENT
# =========================
@router.callback_query(F.data == "admin_offers_menu")
async def admin_offers_menu(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    async with async_session() as session:
        pending_offers = (await session.execute(
            select(Offer).where(Offer.status == "pending")
        )).scalars().all()

    kb_buttons = []
    for offer in pending_offers[:10]:
        kb_buttons.append([InlineKeyboardButton(
            text=f"⏳ {offer.title[:30]}",
            callback_data=f"admin_review_offer:{offer.id}"
        )])
    kb_buttons.append([InlineKeyboardButton(text="📋 Все офферы", callback_data="admin_all_offers")])
    kb_buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_center")])

    text = f"📢 <b>Офферы</b>\nНа проверке: {len(pending_offers)}"
    try:
        await callback.message.edit_text(
            text, parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        )
    except Exception:
        await callback.message.answer(
            text, parse_mode="HTML",
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

    text = (
        f"📢 <b>Оффер #{offer.id}</b>\n"
        f"Название: {offer.title}\n"
        f"Описание: {offer.description}\n"
        f"URL: {offer.channel_url}\n"
        f"Статус: {offer.status}\n"
        f"Дата: {offer.created_at.strftime('%d.%m.%Y %H:%M')}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve_offer:{offer_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_offer:{offer_id}")
        ],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_offers_menu")]
    ])
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("approve_offer:"))
async def approve_offer(callback: CallbackQuery):
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
                        f"✅ Ваш оффер «{offer.title}» одобрен!"
                    )
                except Exception:
                    pass
    await callback.answer("✅ Одобрен!", show_alert=True)


@router.callback_query(F.data.startswith("reject_offer:"))
async def reject_offer_admin(callback: CallbackQuery):
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
    await callback.answer("❌ Отклонён!", show_alert=True)


@router.callback_query(F.data == "admin_all_offers")
async def admin_all_offers(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        offers = (await session.execute(
            select(Offer).order_by(desc(Offer.created_at)).limit(20)
        )).scalars().all()

    if not offers:
        await callback.message.answer("Офферов нет.")
        await callback.answer()
        return

    text = "📋 <b>Все офферы (20 последних):</b>\n\n"
    for o in offers:
        icon = "✅" if o.is_active else ("⏳" if o.status == "pending" else "❌")
        text += f"{icon} #{o.id} {o.title[:25]} — {o.status}\n"

    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


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
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_center")],
    ])
    try:
        await callback.message.edit_text(
            "⚙️ <b>Управление админами</b>",
            parse_mode="HTML", reply_markup=kb
        )
    except Exception:
        await callback.message.answer(
            "⚙️ <b>Управление админами</b>",
            parse_mode="HTML", reply_markup=kb
        )
    await callback.answer()


@router.callback_query(F.data == "admin_list_admins")
async def list_admins(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        admins = (await session.execute(
            select(User).where(User.is_admin == True)
        )).scalars().all()

    text = "📋 <b>Администраторы:</b>\n\n"
    if not admins:
        text += "Нет дополнительных администраторов."
    else:
        for a in admins:
            text += f"• {get_display_name(a)} (ID: <code>{a.telegram_id}</code>)\n"
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_add_admin")
async def add_admin_start(callback: CallbackQuery, state: FSMContext):
    if not is_super_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminManageState.waiting_new_admin)
    await callback.message.answer("Введите Telegram ID для назначения администратором:")
    await callback.answer()


@router.message(AdminManageState.waiting_new_admin)
async def process_add_admin(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        return
    if not message.text.isdigit():
        await message.answer("❌ Введите числовой ID.")
        return
    telegram_id = int(message.text)
    async with async_session() as session:
        user = await get_user(session, telegram_id)
        if not user:
            await message.answer("❌ Пользователь не найден. Пусть нажмёт /start.")
            await state.clear()
            return
        user.is_admin = True
        await session.commit()
    await message.answer(f"✅ {telegram_id} назначен администратором.")
    await state.clear()


@router.callback_query(F.data == "admin_remove_admin")
async def remove_admin_start(callback: CallbackQuery, state: FSMContext):
    if not is_super_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminManageState.waiting_remove_admin)
    await callback.message.answer("Введите Telegram ID для удаления из администраторов:")
    await callback.answer()


@router.message(AdminManageState.waiting_remove_admin)
async def process_remove_admin(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        return
    if not message.text.isdigit():
        await message.answer("❌ Введите числовой ID.")
        return
    telegram_id = int(message.text)
    async with async_session() as session:
        user = await get_user(session, telegram_id)
        if not user or not user.is_admin:
            await message.answer("❌ Не является администратором.")
            await state.clear()
            return
        user.is_admin = False
        await session.commit()
    await message.answer(f"✅ {telegram_id} лишён прав администратора.")
    await state.clear()