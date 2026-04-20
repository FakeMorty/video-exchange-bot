from datetime import datetime
from decimal import Decimal
from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from app.config import ADMINS, LOG_CHAT_ID
from app.db import async_session
from app.services import (
    get_user,
    get_user_by_id,
    get_user_by_username,
    get_user_dossier,
    update_user_balance,
    set_user_ban_status,
    get_next_pending_video,
    approve_video,
    reject_video,
    count_pending_videos,
    count_approved_videos,
    count_rejected_videos,
    get_admin_extended_stats,
    log_user_action,
)
from app.keyboards import (
    moderation_keyboard,
    rejection_reason_keyboard,
    admin_center_keyboard,
    admin_after_action_keyboard,
)
from app.logger import get_logger, log_info, log_warning, log_exception

logger = get_logger(__name__)
router = Router()

class AdminUserState(StatesGroup):
    waiting_user_id = State()
    waiting_coins_amount = State()
    waiting_message_text = State()

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

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not await check_admin(message.from_user.id):
        return
    sa = is_super_admin(message.from_user.id)
    await message.answer(
        "🛠 <b>Админ-панель</b>",
        parse_mode="HTML",
        reply_markup=admin_center_keyboard(is_super_admin=sa),
    )

@router.callback_query(F.data == "admin_manage_users")
async def cb_manage_users(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        return
    await state.set_state(AdminUserState.waiting_user_id)
    await callback.message.answer("Введите ID пользователя или его @username для поиска досье:")
    await callback.answer()

@router.message(AdminUserState.waiting_user_id)
async def process_user_search(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    
    query = message.text.strip()
    async with async_session() as session:
        if query.isdigit():
            user = await get_user_by_id(session, int(query))
        else:
            user = await get_user_by_username(session, query)
        
        if not user:
            await message.answer("Пользователь не найден.")
            await state.clear()
            return
        
        dossier = await get_user_dossier(session, user.id)
        
        header = (
            f"👤 <b>Досье: {user.first_name}</b>\n"
            f"ID: <code>{user.id}</code>\n"
            f"TG ID: <code>{user.telegram_id}</code>\n"
            f"Username: @{user.username or '—'}\n"
            f"Баланс: <b>{user.balance}</b>\n"
            f"Статус: <b>{user.status}</b>\n"
            f"Уровень: {user.level} (XP: {user.xp})\n"
            f"Игр сыграно: {dossier['games_count']}\n"
            f"Загружено: {dossier['videos_uploaded']}\n"
            f"Просмотрено: {dossier['videos_watched']}\n\n"
            f"📜 <b>Полный лог действий:</b>\n"
        )
        
        log_lines = []
        for log in dossier['logs']:
            log_lines.append(f"• {log.created_at.strftime('%d.%m %H:%M')} - {log.action} ({log.details or ''})")
            
        # Если логов очень много, Telegram может не пропустить сообщение по длине (4096 символов)
        # В таком случае разбиваем на части
        full_text = header + "\n".join(log_lines)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Монеты", callback_data=f"adm_add_coins:{user.id}"),
                InlineKeyboardButton(text="➖ Монеты", callback_data=f"adm_rem_coins:{user.id}")
            ],
            [
                InlineKeyboardButton(text="🚫 Бан", callback_data=f"adm_ban:{user.id}"),
                InlineKeyboardButton(text="✅ Разбан", callback_data=f"adm_unban:{user.id}")
            ],
            [
                InlineKeyboardButton(text="✉️ Написать", callback_data=f"adm_msg:{user.id}")
            ],
            [
                InlineKeyboardButton(text="🔙 Назад", callback_data="admin_center")
            ]
        ])
        
        if len(full_text) > 4000:
            # Отправляем частями, если лог слишком длинный
            await message.answer(header, parse_mode="HTML")
            chunk = ""
            for line in log_lines:
                if len(chunk) + len(line) > 3900:
                    await message.answer(chunk)
                    chunk = ""
                chunk += line + "\n"
            await message.answer(chunk, reply_markup=kb)
        else:
            await message.answer(full_text, parse_mode="HTML", reply_markup=kb)
            
        await state.clear()

@router.callback_query(F.data.startswith("adm_add_coins:"))
async def cb_add_coins_start(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split(":")[1])
    await state.update_data(target_user_id=user_id, action_type="add")
    await state.set_state(AdminUserState.waiting_coins_amount)
    await callback.message.answer("Сколько монет добавить?")
    await callback.answer()

@router.callback_query(F.data.startswith("adm_rem_coins:"))
async def cb_rem_coins_start(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split(":")[1])
    await state.update_data(target_user_id=user_id, action_type="rem")
    await state.set_state(AdminUserState.waiting_coins_amount)
    await callback.message.answer("Сколько монет убрать?")
    await callback.answer()

@router.message(AdminUserState.waiting_coins_amount)
async def process_coins_update(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    
    try:
        amount = Decimal(message.text.strip())
        data = await state.get_data()
        user_id = data['target_user_id']
        action = data['action_type']
        
        if action == "rem":
            amount = -amount
            
        async with async_session() as session:
            success = await update_user_balance(session, user_id, amount, message.from_user.id)
            if success:
                await message.answer(f"Баланс пользователя изменен на {amount}.")
            else:
                await message.answer("Ошибка при обновлении баланса.")
    except Exception:
        await message.answer("Некорректная сумма.")
    finally:
        await state.clear()

@router.callback_query(F.data.startswith("adm_ban:"))
async def cb_ban_user(callback: CallbackQuery):
    user_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        await set_user_ban_status(session, user_id, True, callback.from_user.id)
        await callback.message.answer("Пользователь забанен.")
    await callback.answer()

@router.callback_query(F.data.startswith("adm_unban:"))
async def cb_unban_user(callback: CallbackQuery):
    user_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        await set_user_ban_status(session, user_id, False, callback.from_user.id)
        await callback.message.answer("Пользователь разбанен.")
    await callback.answer()

@router.callback_query(F.data.startswith("adm_msg:"))
async def cb_msg_user_start(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split(":")[1])
    await state.update_data(target_user_id=user_id)
    await state.set_state(AdminUserState.waiting_message_text)
    await callback.message.answer("Введите текст сообщения для пользователя:")
    await callback.answer()

@router.message(AdminUserState.waiting_message_text)
async def process_msg_user(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    
    data = await state.get_data()
    user_id = data['target_user_id']
    text = message.text.strip()
    
    async with async_session() as session:
        user = await get_user_by_id(session, user_id)
        if user:
            try:
                await message.bot.send_message(user.telegram_id, f"✉️ <b>Сообщение от администрации:</b>\n\n{text}", parse_mode="HTML")
                await message.answer("Сообщение отправлено.")
                await log_user_action(session, user.id, "msg_from_admin", f"By admin {message.from_user.id}: {text[:50]}...")
            except Exception as e:
                await message.answer(f"Не удалось отправить сообщение: {e}")
        else:
            await message.answer("Пользователь не найден.")
    await state.clear()

@router.callback_query(F.data == "admin_queue_info")
async def cb_queue(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    async with async_session() as session:
        p = await count_pending_videos(session)
        a = await count_approved_videos(session)
        r = await count_rejected_videos(session)
        sa = is_super_admin(callback.from_user.id)
        text = (
            f"📊 <b>Статистика</b>\n\n"
            f"⏳ На модерации: <b>{p}</b>\n"
            f"✅ Одобрено: <b>{a}</b>\n"
            f"❌ Отклонено: <b>{r}</b>"
        )
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_center_keyboard(is_super_admin=sa))
    await callback.answer()
