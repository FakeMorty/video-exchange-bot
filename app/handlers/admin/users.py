"""
User management handlers (give coins, ban, message, etc).
"""
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, desc

from app.db import async_session
from app.models import User
from app.services import (
    get_user, get_user_by_id, get_user_by_username, get_user_by_display_name,
    update_user_balance, set_user_ban_status, get_user_dossier, log_user_action
)
from app.utils.admin import check_admin
from app.keyboards import admin_after_action_keyboard

router = Router()

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
