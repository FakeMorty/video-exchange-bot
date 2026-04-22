from datetime import datetime
from decimal import Decimal

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from sqlalchemy import select

from app.config import ADMINS
from app.db import async_session
from app.models import User
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
)

router = Router()


# =========================
# STATES
# =========================

class AdminUserState(StatesGroup):
    waiting_user_id = State()
    waiting_coins_amount = State()
    waiting_message_text = State()


class AdminManageState(StatesGroup):
    waiting_new_admin = State()
    waiting_remove_admin = State()


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


# =========================
# ADMIN PANEL ENTRY
# =========================

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not await check_admin(message.from_user.id):
        return

    sa = is_super_admin(message.from_user.id)

    buttons = [
        [InlineKeyboardButton(text="📊 Очередь", callback_data="admin_queue_info")],
        [InlineKeyboardButton(text="👤 Пользователь", callback_data="admin_manage_users")],
    ]

    if sa:
        buttons.append(
            [InlineKeyboardButton(text="👑 Управление админами", callback_data="admin_manage_admins")]
        )

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await message.answer("🔧 <b>Админ-панель</b>", parse_mode="HTML", reply_markup=kb)


# =========================
# QUEUE INFO
# =========================

@router.callback_query(F.data == "admin_queue_info")
async def cb_queue(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        return

    async with async_session() as session:
        p = await count_pending_videos(session)
        a = await count_approved_videos(session)
        r = await count_rejected_videos(session)

    text = (
        f"📊 <b>Статистика видео</b>\n\n"
        f"⏳ В очереди: <b>{p}</b>\n"
        f"✅ Одобрено: <b>{a}</b>\n"
        f"❌ Отклонено: <b>{r}</b>"
    )

    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()


# =========================
# ADMIN MANAGEMENT SYSTEM
# =========================

@router.callback_query(F.data == "admin_manage_admins")
async def manage_admins_menu(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список", callback_data="admin_list_admins")],
        [InlineKeyboardButton(text="➕ Добавить", callback_data="admin_add_admin")],
        [InlineKeyboardButton(text="➖ Удалить", callback_data="admin_remove_admin")],
        [InlineKeyboardButton(text="⬅ Назад", callback_data="admin_back")],
    ])

    await callback.message.edit_text(
        "👑 <b>Управление админами</b>",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    await cmd_admin(callback.message)
    await callback.answer()


# 📋 LIST ADMINS
@router.callback_query(F.data == "admin_list_admins")
async def list_admins(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        return

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.is_admin == True)
        )
        admins = result.scalars().all()

    if not admins:
        text = "Админов нет."
    else:
        text = "👑 <b>Список админов:</b>\n\n"
        for admin in admins:
            text += f"• {admin.first_name or 'Без имени'} (ID: <code>{admin.telegram_id}</code>)\n"

    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


# ➕ ADD ADMIN
@router.callback_query(F.data == "admin_add_admin")
async def add_admin_start(callback: CallbackQuery, state: FSMContext):
    if not is_super_admin(callback.from_user.id):
        return

    await state.set_state(AdminManageState.waiting_new_admin)
    await callback.message.answer(
        "Введите Telegram ID пользователя для добавления в админы:"
    )
    await callback.answer()


@router.message(AdminManageState.waiting_new_admin)
async def process_add_admin(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        return

    if not message.text.isdigit():
        await message.answer("Нужно ввести числовой Telegram ID.")
        return

    telegram_id = int(message.text)

    async with async_session() as session:
        user = await get_user(session, telegram_id)
        if not user:
            await message.answer(
                "Пользователь не найден.\n"
                "Он должен сначала написать боту /start."
            )
            await state.clear()
            return

        user.is_admin = True
        await session.commit()

    await message.answer(f"✅ Пользователь {telegram_id} теперь админ.")
    await state.clear()


# ➖ REMOVE ADMIN
@router.callback_query(F.data == "admin_remove_admin")
async def remove_admin_start(callback: CallbackQuery, state: FSMContext):
    if not is_super_admin(callback.from_user.id):
        return

    await state.set_state(AdminManageState.waiting_remove_admin)
    await callback.message.answer(
        "Введите Telegram ID админа для удаления:"
    )
    await callback.answer()


@router.message(AdminManageState.waiting_remove_admin)
async def process_remove_admin(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        return

    if not message.text.isdigit():
        await message.answer("Нужно ввести числовой Telegram ID.")
        return

    telegram_id = int(message.text)

    async with async_session() as session:
        user = await get_user(session, telegram_id)
        if not user or not user.is_admin:
            await message.answer("Этот пользователь не является админом.")
            await state.clear()
            return

        user.is_admin = False
        await session.commit()

    await message.answer(f"✅ Пользователь {telegram_id} больше не админ.")
    await state.clear()