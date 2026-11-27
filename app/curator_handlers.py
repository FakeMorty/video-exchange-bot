"""Private curator workflow and viewer category preferences."""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select

from app.db import async_session
from app.i18n import t
from app.models import Video
from app.keyboards import menu_button_variants
from app.services import (
    VIDEO_VIEW_CATEGORIES, get_user, get_next_video_for_curation,
    set_video_view_category, parse_video_category_preferences,
)

router = Router()


def _advanced_keyboard(user):
    selected = set(parse_video_category_preferences(user.advanced_video_categories))
    rows = [[InlineKeyboardButton(
        text=f"{'✅' if key in selected else '▫️'} {label}",
        callback_data=f"advanced_category:{key}",
    )] for key, label in VIDEO_VIEW_CATEGORIES.items()]
    rows.append([InlineKeyboardButton(
        text=("Выключить расширенный просмотр" if user.advanced_view_enabled else "Включить расширенный просмотр"),
        callback_data="advanced_toggle",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text.in_(menu_button_variants("advanced_view")))
@router.message(Command("advanced"))
async def advanced_view_settings(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        await message.answer(
            "🔎 <b>Расширенный просмотр</b>\n\nВыбери несколько категорий состава видео. В ленте будут только одобренные ролики с выбранной меткой. Метка описывает состав видео, а не ориентацию людей. Если подходящих видео нет, подборка будет пустой.\n\nВыбранные категории отмечены ✅.",
            parse_mode="HTML", reply_markup=_advanced_keyboard(user),
        )


@router.callback_query(F.data.startswith("advanced_category:"))
async def advanced_category_toggle(callback: CallbackQuery):
    key = callback.data.split(":", 1)[1]
    if key not in VIDEO_VIEW_CATEGORIES:
        await callback.answer("Неизвестная категория", show_alert=True)
        return
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        selected = set(parse_video_category_preferences(user.advanced_video_categories))
        if key in selected:
            selected.remove(key)
        else:
            selected.add(key)
        user.advanced_video_categories = ",".join(k for k in VIDEO_VIEW_CATEGORIES if k in selected)
        await session.commit()
        await callback.message.edit_reply_markup(reply_markup=_advanced_keyboard(user))
    await callback.answer("Настройки сохранены")


@router.callback_query(F.data == "advanced_toggle")
async def advanced_toggle(callback: CallbackQuery):
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if user:
            user.advanced_view_enabled = not bool(user.advanced_view_enabled)
            await session.commit()
            await callback.message.edit_reply_markup(reply_markup=_advanced_keyboard(user))
    await callback.answer("Режим включён" if user and user.advanced_view_enabled else "Режим выключен")


@router.callback_query(F.data.startswith("curator_accept:"))
async def curator_accept(callback: CallbackQuery):
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user or user.curator_status != "invited":
            await callback.answer("Приглашение больше не активно", show_alert=True)
            return
        decision = callback.data.rsplit(":", 1)[1]
        user.curator_status = "active" if decision == "yes" else "declined"
        await session.commit()
    if decision == "yes":
        await callback.message.edit_text("✅ Роль смотрящего принята. Чтобы открыть инструменты, используй /curator.\n\nМожно классифицировать только одобренные видео. Это не даёт права публиковать или модерировать ожидающий контент.")
    else:
        await callback.message.edit_text("Роль смотрящего отклонена.")
    await callback.answer()


@router.message(Command("curator"))
async def curator_home(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user or user.curator_status != "active":
            await message.answer("Эти инструменты доступны только пользователям, которые приняли приглашение смотрящего.")
            return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏷 Разметить следующее видео", callback_data="curator_next")],
        [InlineKeyboardButton(text="ℹ️ Возможности смотрящего", callback_data="curator_info")],
    ])
    await message.answer("🧭 <b>Возможности смотрящего</b>\n\nСмотрящий назначает нейтральную метку состава одобренному видео. Он не одобряет, не отклоняет и не публикует ожидающие видео.", parse_mode="HTML", reply_markup=keyboard)


@router.callback_query(F.data == "curator_info")
async def curator_info(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("Смотрящий может только присвоить метку уже одобренному видео: «Только мужчины», «Только женщины» или «Мужчины и женщины». Метка должна описывать видимый состав видео, не ориентацию. Не уверен — пропусти; жалобы пользователей и админ-модерация остаются отдельными.")


@router.callback_query(F.data == "curator_next")
async def curator_next(callback: CallbackQuery):
    async with async_session() as session:
        video = await get_next_video_for_curation(session, callback.from_user.id)
        if not video:
            await callback.answer("Сейчас нет одобренных видео без метки.", show_alert=True)
            return
        video_id = video.id
        file_id = video.telegram_file_id
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, callback_data=f"curator_label:{video_id}:{key}")
    ] for key, label in VIDEO_VIEW_CATEGORIES.items()] + [[
        InlineKeyboardButton(text="⏭ Пропустить", callback_data="curator_next")
    ]])
    await callback.message.answer_video(file_id, caption=f"Видео #{video_id} — выбери нейтральную метку состава:", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("curator_label:"))
async def curator_label(callback: CallbackQuery):
    _, raw_video_id, category = callback.data.split(":", 2)
    try:
        video_id = int(raw_video_id)
    except ValueError:
        await callback.answer("Некорректное видео", show_alert=True)
        return
    async with async_session() as session:
        ok, _ = await set_video_view_category(session, callback.from_user.id, video_id, category)
    if ok:
        await callback.answer("Метка сохранена")
        await callback.message.edit_caption(caption=f"✅ Видео #{video_id}: {VIDEO_VIEW_CATEGORIES[category]}")
    else:
        await callback.answer("Не удалось сохранить: роль неактивна, видео уже размечено или больше не одобрено.", show_alert=True)
