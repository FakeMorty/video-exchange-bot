import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from app.config import ADMINS
from app.db import async_session
from app.services import (
    get_next_pending_video, approve_video, reject_video, count_pending_videos,
)
from app.keyboards import moderation_keyboard, rejection_reason_keyboard

logger = logging.getLogger(__name__)
router = Router()


def is_admin(telegram_id: int) -> bool:
    return telegram_id in ADMINS


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа.")
        return

    async with async_session() as session:
        pending_count = await count_pending_videos(session)
        video = await get_next_pending_video(session)

    if not video:
        await message.answer(f"✅ Нет видео на модерации. (Всего pending: {pending_count})")
        return

    await message.answer_video(
        video=video.telegram_file_id,
        caption=(
            f"��� <b>Модерация</b>\n"
            f"ID видео: {video.id}\n"
            f"Автор (user_id): {video.uploader_user_id}\n"
            f"Длительность: {video.duration_seconds or '?'} сек\n"
            f"В очереди: {pending_count}"
        ),
        parse_mode="HTML",
        reply_markup=moderation_keyboard(video.id),
    )


@router.callback_query(F.data.startswith("mod_approve:"))
async def cb_approve(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    video_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        video = await approve_video(session, video_id)

    if video:
        await callback.message.edit_caption(
            caption=f"✅ Видео #{video_id} одобрено! Автору начислено +0.5 монеты.",
        )
    else:
        await callback.message.edit_caption(caption=f"⚠️ Видео #{video_id} не найдено.")

    await callback.answer("Одобрено ✅")
    await _send_next_pending(callback.message, callback.from_user.id)


@router.callback_query(F.data.startswith("mod_reject:"))
async def cb_reject(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    video_id = int(callback.data.split(":")[1])

    await callback.message.edit_reply_markup(
        reply_markup=rejection_reason_keyboard(video_id),
    )
    await callback.answer("Выберите причину отклонения")


@router.callback_query(F.data.startswith("reject_reason:"))
async def cb_reject_reason(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("⛔ Нет доступа")
        return

    parts = callback.data.split(":", 2)
    video_id = int(parts[1])
    reason = parts[2]

    async with async_session() as session:
        video = await reject_video(session, video_id, reason)

    if video:
        await callback.message.edit_caption(
            caption=f"❌ Видео #{video_id} отклонено.\nПричина: {reason}",
        )
    else:
        await callback.message.edit_caption(caption=f"⚠️ Видео #{video_id} не найдено.")

    await callback.answer("Отклонено ❌")
    await _send_next_pending(callback.message, callback.from_user.id)


async def _send_next_pending(message: Message, admin_id: int):
    async with async_session() as session:
        pending_count = await count_pending_videos(session)
        video = await get_next_pending_video(session)

    if not video:
        await message.answer("✅ Очередь пуста! Все видео обработаны.")
        return

    await message.answer_video(
        video=video.telegram_file_id,
        caption=(
            f"��� <b>Модерация</b>\n"
            f"ID видео: {video.id}\n"
            f"Автор (user_id): {video.uploader_user_id}\n"
            f"Длительность: {video.duration_seconds or '?'} сек\n"
            f"В очереди: {pending_count}"
        ),
        parse_mode="HTML",
        reply_markup=moderation_keyboard(video.id),
    )
