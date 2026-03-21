import logging
import traceback

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from app.config import ADMINS
from app.db import async_session
from app.keyboards import (
    moderation_keyboard,
    rejection_reason_keyboard,
    admin_center_keyboard,
    admin_after_action_keyboard,
)
from app.services import (
    get_next_pending_video,
    approve_video,
    reject_video,
    count_pending_videos,
    count_approved_videos,
    count_rejected_videos,
)

logger = logging.getLogger(__name__)
router = Router()

REASON_MAP = {
    "duplicate": "Дубликат",
    "off_topic": "Не по тематике",
    "other": "Другое",
}


def is_admin(telegram_id: int) -> bool:
    return telegram_id in ADMINS


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа.")
        return

    await message.answer(
        "🛠 <b>Админ-центр</b>\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=admin_center_keyboard(),
    )


@router.callback_query(F.data == "admin_queue_info")
async def cb_admin_queue_info(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    try:
        async with async_session() as session:
            pending = await count_pending_videos(session)
            approved = await count_approved_videos(session)
            rejected = await count_rejected_videos(session)

        text = (
            "📊 <b>Статус очереди</b>\n\n"
            f"🕓 На модерации: <b>{pending}</b>\n"
            f"✅ Одобрено: <b>{approved}</b>\n"
            f"❌ Отклонено: <b>{rejected}</b>"
        )
        await callback.message.answer(text, parse_mode="HTML", reply_markup=admin_center_keyboard())
        await callback.answer()
    except Exception as e:
        logger.error(f"[ADMIN_QUEUE] ERROR: {e}")
        logger.error(traceback.format_exc())
        await callback.answer("Ошибка", show_alert=True)


@router.callback_query(F.data == "admin_get_pending")
async def cb_admin_get_pending(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await callback.answer()
    await send_next_pending_video(callback.message)


async def send_next_pending_video(message: Message):
    try:
        async with async_session() as session:
            pending_count = await count_pending_videos(session)
            video = await get_next_pending_video(session)

            if not video:
                await message.answer(
                    "✅ Очередь модерации пуста.",
                    reply_markup=admin_center_keyboard(),
                )
                return

            video_file_id = video.telegram_file_id
            video_id = video.id
            uploader_id = video.uploader_user_id
            duration = video.duration_seconds
            file_size = video.file_size

        text = (
            f"📋 <b>Модерация видео</b>\n\n"
            f"ID видео: <b>{video_id}</b>\n"
            f"Автор: <code>{uploader_id}</code>\n"
            f"Длительность: <b>{duration or 0}</b> сек.\n"
            f"Размер: <b>{file_size or 0}</b> байт\n"
            f"В очереди: <b>{pending_count}</b>"
        )

        await message.answer_video(
            video=video_file_id,
            caption=text,
            parse_mode="HTML",
            reply_markup=moderation_keyboard(video_id),
        )
    except Exception as e:
        logger.error(f"[SEND_PENDING] ERROR: {e}")
        logger.error(traceback.format_exc())
        await message.answer("Ошибка при получении видео на модерацию.")


@router.callback_query(F.data.startswith("mod_approve:"))
async def cb_approve(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    try:
        video_id = int(callback.data.split(":")[1])

        async with async_session() as session:
            video = await approve_video(session, video_id)

        if not video:
            await callback.message.edit_caption(
                caption=f"⚠️ Видео #{video_id} не найдено.",
                reply_markup=admin_after_action_keyboard(),
            )
            await callback.answer("Видео не найдено")
            return

        await callback.message.edit_caption(
            caption=(
                f"✅ Видео #{video_id} одобрено.\n"
                f"Автору начислено +0.5 монеты."
            ),
            reply_markup=admin_after_action_keyboard(),
        )
        await callback.answer("Одобрено")
    except Exception as e:
        logger.error(f"[APPROVE] ERROR: {e}")
        logger.error(traceback.format_exc())
        await callback.answer("Ошибка при одобрении", show_alert=True)


@router.callback_query(F.data.startswith("mod_reject:"))
async def cb_reject(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    try:
        video_id = int(callback.data.split(":")[1])
        await callback.message.edit_reply_markup(reply_markup=rejection_reason_keyboard(video_id))
        await callback.answer("Выберите причину")
    except Exception as e:
        logger.error(f"[REJECT] ERROR: {e}")
        logger.error(traceback.format_exc())
        await callback.answer("Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("reject_reason:"))
async def cb_reject_reason(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    try:
        parts = callback.data.split(":", 2)
        video_id = int(parts[1])
        reason_key = parts[2]
        reason_text = REASON_MAP.get(reason_key, "Другое")

        async with async_session() as session:
            video = await reject_video(session, video_id, reason_text)

        if not video:
            await callback.message.edit_caption(
                caption=f"⚠️ Видео #{video_id} не найдено.",
                reply_markup=admin_after_action_keyboard(),
            )
            await callback.answer("Видео не найдено")
            return

        await callback.message.edit_caption(
            caption=(
                f"❌ Видео #{video_id} отклонено.\n"
                f"Причина: {reason_text}"
            ),
            reply_markup=admin_after_action_keyboard(),
        )
        await callback.answer("Отклонено")
    except Exception as e:
        logger.error(f"[REJECT_REASON] ERROR: {e}")
        logger.error(traceback.format_exc())
        await callback.answer("Ошибка при отклонении", show_alert=True)