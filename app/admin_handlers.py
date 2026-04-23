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
from app.models import User, Video, Offer
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
        [InlineKeyboardButton(text="👥 Управление пользователями", callback_data="admin_manage_users")],
        [InlineKeyboardButton(text="🎬 Взять на модерацию", callback_data="admin_get_pending")],
        [InlineKeyboardButton(text="✅ Одобрить все", callback_data="admin_approve_all")],
        [InlineKeyboardButton(text="📢 Офферы", callback_data="admin_offers_menu")],
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
    await callback.message.edit_text(
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
        f"📊 <b>Статистика очереди</b>\n\n"
        f"⏳ На проверке: <b>{p}</b>\n"
        f"✅ Одобрено: <b>{a}</b>\n"
        f"❌ Отклонено: <b>{r}</b>"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
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
        f"👑 VIP пользователей: <b>{stats['vip']}</b>\n"
        f"💬 Комментариев: <b>{stats['comments']}</b>\n"
        f"😀 Реакций: <b>{stats['reactions']}</b>\n"
        f"🎮 Игр сыграно: <b>{stats['games']}</b>\n"
        f"📢 Офферов: <b>{stats['offers']}</b>"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
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
        uploader_name = uploader.first_name if uploader else "???"
        uploader_id = uploader.telegram_id if uploader else "???"

    from app.keyboards import moderation_keyboard
    caption = (
        f"🎬 Видео #{video.id}\n"
        f"👤 Загрузчик: {uploader_name} (ID: {uploader_id})\n"
        f"📅 Загружено: {video.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"⏱ Длительность: {video.duration_seconds or '?'} сек\n"
        f"📦 Размер: {round(video.file_size / 1024 / 1024, 2) if video.file_size else '?'} МБ"
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
            await callback.answer("Видео не найдено или уже обработано.", show_alert=True)
            return
        uploader = await get_user_by_id(session, video.uploader_user_id)

    # Уведомляем загрузчика
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
        f"Выберите причину отклонения видео #{video_id}:",
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
        "duplicate": "Дубликат контента",
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
                f"❌ Ваш контент #{video_id} отклонён.\nПричина: {reason_text}"
            )
        except Exception:
            pass

    from app.keyboards import admin_after_action_keyboard
    await callback.message.answer(
        f"❌ Видео #{video_id} отклонено. Причина: {reason_text}",
        reply_markup=admin_after_action_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "admin_approve_all")
async def admin_approve_all(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    approved_count = 0
    async with async_session() as session:
        while True:
            video = await get_next_pending_video(session)
            if not video:
                break
            await approve_video(session, video.id)
            approved_count += 1
            if approved_count >= 50:  # Защита от бесконечного цикла
                break

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ В панель", callback_data="admin_center")]
    ])
    await callback.message.answer(
        f"✅ Одобрено видео: <b>{approved_count}</b>",
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
        [InlineKeyboardButton(text="🔍 Досье пользователя", callback_data="admin_user_dossier")],
        [InlineKeyboardButton(text="💰 Выдать монеты", callback_data="admin_give_coins")],
        [InlineKeyboardButton(text="🚫 Заблокировать", callback_data="admin_ban_user")],
        [InlineKeyboardButton(text="✅ Разблокировать", callback_data="admin_unban_user")],
        [InlineKeyboardButton(text="📨 Написать пользователю", callback_data="admin_message_user")],
        [InlineKeyboardButton(text="📣 Рассылка всем", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_center")],
    ])
    await callback.message.edit_text(
        "👥 <b>Управление пользователями</b>",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


# --- ДOSSIER ---
@router.callback_query(F.data == "admin_user_dossier")
async def admin_user_dossier_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminUserState.waiting_dossier_id)
    await callback.message.answer("Введите Telegram ID или @username пользователя:")
    await callback.answer()


@router.message(AdminUserState.waiting_dossier_id)
async def process_dossier(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    async with async_session() as session:
        if message.text.startswith("@"):
            user = await get_user_by_username(session, message.text)
        elif message.text.isdigit():
            user = await get_user(session, int(message.text))
        else:
            await message.answer("❌ Введите корректный ID или @username")
            return

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
    logs_text = ""
    for log in dossier["logs"][:5]:
        logs_text += f"  • {log.action}: {log.details or ''} ({log.created_at.strftime('%d.%m %H:%M')})\n"

    text = (
        f"📋 <b>Досье пользователя</b>\n\n"
        f"🆔 TG ID: <code>{u.telegram_id}</code>\n"
        f"👤 Имя: {u.first_name or '???'}\n"
        f"📱 Username: @{u.username or '???'}\n"
        f"💰 Баланс: {u.balance} монет\n"
        f"🏆 Уровень: {u.level} (XP: {u.xp})\n"
        f"📊 Статус: {u.status}\n"
        f"👑 VIP: {'Да' if u.vip_until and u.vip_until > datetime.utcnow() else 'Нет'}\n"
        f"🎬 Видео загружено: {dossier['videos_uploaded']}\n"
        f"👁 Видео просмотрено: {dossier['videos_watched']}\n"
        f"🎮 Игр сыграно: {dossier['games_count']}\n"
        f"📅 Регистрация: {u.created_at.strftime('%d.%m.%Y')}\n\n"
        f"📝 Последние действия:\n{logs_text or 'Нет'}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Выдать монеты", callback_data=f"give_coins_to:{u.id}")],
        [InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"ban_user:{u.id}")],
        [InlineKeyboardButton(text="✅ Разблокировать", callback_data=f"unban_user:{u.id}")],
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)
    await state.clear()


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
    await callback.message.answer("Введите количество монет (положительное — добавить, отрицательное — снять):")
    await callback.answer()


@router.message(AdminUserState.waiting_user_id)
async def process_user_id_for_coins(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    data = await state.get_data()
    action = data.get("action")

    if not message.text.lstrip("-").isdigit():
        await message.answer("❌ Введите числовой ID.")
        return

    telegram_id = int(message.text)
    async with async_session() as session:
        user = await get_user(session, telegram_id)
        if not user:
            await message.answer("❌ Пользователь не найден.")
            await state.clear()
            return
        await state.update_data(target_user_id=user.id, target_tg_id=telegram_id)

    if action == "give_coins":
        await state.set_state(AdminUserState.waiting_coins_amount)
        await message.answer("Введите количество монет:")
    elif action == "ban":
        async with async_session() as session:
            ok = await set_user_ban_status(session, user.id, True, message.from_user.id)
        if ok:
            await message.answer(f"🚫 Пользователь {telegram_id} заблокирован.")
        else:
            await message.answer("❌ Ошибка.")
        await state.clear()
    elif action == "unban":
        async with async_session() as session:
            ok = await set_user_ban_status(session, user.id, False, message.from_user.id)
        if ok:
            await message.answer(f"✅ Пользователь {telegram_id} разблокирован.")
        else:
            await message.answer("❌ Ошибка.")
        await state.clear()


@router.message(AdminUserState.waiting_coins_amount)
async def process_coins_amount(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    try:
        amount = Decimal(message.text)
    except Exception:
        await message.answer("❌ Введите число (например: 10 или -5).")
        return

    data = await state.get_data()
    target_user_id = data.get("target_user_id")
    if not target_user_id:
        await message.answer("❌ Ошибка: не указан пользователь.")
        await state.clear()
        return

    async with async_session() as session:
        ok = await update_user_balance(session, target_user_id, amount, message.from_user.id)
        if ok:
            user = await get_user_by_id(session, target_user_id)
            await message.answer(
                f"✅ Баланс обновлён!\n"
                f"Пользователь ID: {target_user_id}\n"
                f"Изменение: {'+' if amount > 0 else ''}{amount} монет\n"
                f"Новый баланс: {user.balance if user else '???'}"
            )
            # Уведомляем пользователя
            if user:
                try:
                    await message.bot.send_message(
                        user.telegram_id,
                        f"💰 Администратор изменил ваш баланс: {'+' if amount > 0 else ''}{amount} монет"
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
    await callback.message.answer("Введите Telegram ID пользователя для блокировки:")
    await callback.answer()


@router.callback_query(F.data == "admin_unban_user")
async def admin_unban_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminUserState.waiting_user_id)
    await state.update_data(action="unban")
    await callback.message.answer("Введите Telegram ID пользователя для разблокировки:")
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
        await callback.answer(f"🚫 Пользователь заблокирован!", show_alert=True)
        if user:
            try:
                await callback.bot.send_message(user.telegram_id, "🚫 Вы заблокированы в боте.")
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
        await callback.answer(f"✅ Пользователь разблокирован!", show_alert=True)
        if user:
            try:
                await callback.bot.send_message(user.telegram_id, "✅ Ваша блокировка снята.")
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
    await callback.message.answer("Введите Telegram ID пользователя:")
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
        await message.answer(f"❌ Ошибка отправки: {e}")
    await state.clear()


# --- BROADCAST ---
@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminBroadcastState.waiting_text)
    await callback.message.answer(
        "📣 Введите текст для рассылки всем пользователям:\n"
        "(Поддерживается HTML разметка)"
    )
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

    sent = 0
    failed = 0
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

    await message.answer(f"📣 Рассылка завершена!\n✅ Отправлено: {sent}\n❌ Ошибок: {failed}")


# =========================
# OFFERS MANAGEMENT
# =========================
@router.callback_query(F.data == "admin_offers_menu")
async def admin_offers_menu(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    async with async_session() as session:
        # Pending offers
        pending_offers = (await session.execute(
            select(Offer).where(Offer.status == "pending")
        )).scalars().all()

    if not pending_offers:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Все офферы", callback_data="admin_all_offers")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_center")]
        ])
        await callback.message.edit_text(
            "📢 <b>Управление офферами</b>\n\nНет офферов на проверке.",
            parse_mode="HTML",
            reply_markup=kb
        )
        await callback.answer()
        return

    kb_buttons = []
    for offer in pending_offers[:10]:
        kb_buttons.append([InlineKeyboardButton(
            text=f"⏳ {offer.title[:30]}",
            callback_data=f"admin_review_offer:{offer.id}"
        )])
    kb_buttons.append([InlineKeyboardButton(text="📋 Все офферы", callback_data="admin_all_offers")])
    kb_buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_center")])

    await callback.message.edit_text(
        f"📢 <b>Управление офферами</b>\n\nОфферов на проверке: {len(pending_offers)}",
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
            await callback.answer("Оффер не найден.", show_alert=True)
            return

    text = (
        f"📢 <b>Оффер #{offer.id}</b>\n\n"
        f"Название: {offer.title}\n"
        f"Описание: {offer.description}\n"
        f"URL: {offer.channel_url}\n"
        f"Статус: {offer.status}\n"
        f"Создан: {offer.created_at.strftime('%d.%m.%Y %H:%M')}"
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
            await callback.answer("Оффер не найден.", show_alert=True)
            return
        offer.status = "approved"
        offer.is_active = True
        await session.commit()

        # Уведомляем создателя
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
            await callback.answer("Оффер не найден.", show_alert=True)
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
                        f"❌ Ваш оффер «{offer.title}» отклонён модератором."
                    )
                except Exception:
                    pass

    await callback.answer("❌ Оффер отклонён!", show_alert=True)


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

    text = "📋 <b>Все офферы (последние 20):</b>\n\n"
    for o in offers:
        icon = "✅" if o.is_active else ("⏳" if o.status == "pending" else "❌")
        text += f"{icon} #{o.id} {o.title[:30]} — {o.status}\n"

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
    await callback.message.edit_text(
        "⚙️ <b>Управление админами</b>",
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
        result = await session.execute(
            select(User).where(User.is_admin == True)
        )
        admins = result.scalars().all()

    if not admins:
        text = "Администраторов нет."
    else:
        text = "📋 <b>Список администраторов:</b>\n\n"
        for admin in admins:
            text += f"• {admin.first_name or 'Без имени'} (ID: <code>{admin.telegram_id}</code>)\n"

    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_add_admin")
async def add_admin_start(callback: CallbackQuery, state: FSMContext):
    if not is_super_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminManageState.waiting_new_admin)
    await callback.message.answer("Введите Telegram ID пользователя для назначения администратором:")
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
                "Пользователь должен сначала нажать /start."
            )
            await state.clear()
            return
        user.is_admin = True
        await session.commit()
    await message.answer(f"✅ Пользователь {telegram_id} назначен администратором.")
    await state.clear()


@router.callback_query(F.data == "admin_remove_admin")
async def remove_admin_start(callback: CallbackQuery, state: FSMContext):
    if not is_super_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminManageState.waiting_remove_admin)
    await callback.message.answer("Введите Telegram ID админа для удаления:")
    await callback.answer()


@router.message(AdminManageState.waiting_remove_admin)
async def process_remove_admin(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        return
    if not message.text.isdigit():
        await message.answer("❌ Введите числовой Telegram ID.")
        return
    telegram_id = int(message.text)
    async with async_session() as session:
        user = await get_user(session, telegram_id)
        if not user or not user.is_admin:
            await message.answer("❌ Этот пользователь не является администратором.")
            await state.clear()
            return
        user.is_admin = False
        await session.commit()
    await message.answer(f"✅ Пользователь {telegram_id} лишён прав администратора.")
    await state.clear()