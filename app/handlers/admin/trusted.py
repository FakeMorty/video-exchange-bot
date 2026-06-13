"""
Trusted uploaders handlers.
"""
from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, desc

from app.db import async_session
from app.models import TrustedUploader, User
from app.services import get_user, get_user_by_username, get_user_by_display_name, get_display_name
from app.utils.admin import check_admin

router = Router()

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
