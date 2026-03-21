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

REASON_MAP = {
    "duplicate": "\u0414\u0443\u0431\u043b\u0438\u043a\u0430\u0442",
    "off_topic": "\u041d\u0435 \u043f\u043e \u0442\u0435\u043c\u0430\u0442\u0438\u043a\u0435",
    "other": "\u0414\u0440\u0443\u0433\u043e\u0435",
}


def is_admin(telegram_id: int) -> bool:
    return telegram_id in ADMINS


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        await message.answer("\u26d4 \u0423 \u0432\u0430\u0441 \u043d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u0430.")
        return

    async with async_session() as session:
        pending_count = await count_pending_videos(session)
        video = await get_next_pending_video(session)

    if not video:
        await message.answer(f"\u2705 \u041d\u0435\u0442 \u0432\u0438\u0434\u0435\u043e \u043d\u0430 \u043c\u043e\u0434\u0435\u0440\u0430\u0446\u0438\u0438. (\u0412\u0441\u0435\u0433\u043e pending: {pending_count})")
        return

    await message.answer_video(
        video=video.telegram_file_id,
        caption=(
            f"\U0001f4cb <b>\u041c\u043e\u0434\u0435\u0440\u0430\u0446\u0438\u044f</b>\n"
            f"ID \u0432\u0438\u0434\u0435\u043e: {video.id}\n"
            f"\u0410\u0432\u0442\u043e\u0440 (user_id): {video.uploader_user_id}\n"
            f"\u0414\u043b\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0441\u0442\u044c: {video.duration_seconds or '?'} \u0441\u0435\u043a\n"
            f"\u0412 \u043e\u0447\u0435\u0440\u0435\u0434\u0438: {pending_count}"
        ),
        parse_mode="HTML",
        reply_markup=moderation_keyboard(video.id),
    )


@router.callback_query(F.data.startswith("mod_approve:"))
async def cb_approve(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("\u26d4 \u041d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u0430")
        return

    video_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        video = await approve_video(session, video_id)

    if video:
        await callback.message.edit_caption(
            caption=f"\u2705 \u0412\u0438\u0434\u0435\u043e #{video_id} \u043e\u0434\u043e\u0431\u0440\u0435\u043d\u043e! \u0410\u0432\u0442\u043e\u0440\u0443 \u043d\u0430\u0447\u0438\u0441\u043b\u0435\u043d\u043e +0.5 \u043c\u043e\u043d\u0435\u0442\u044b.",
        )
    else:
        await callback.message.edit_caption(
            caption=f"\u26a0\ufe0f \u0412\u0438\u0434\u0435\u043e #{video_id} \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e.",
        )

    await callback.answer("\u041e\u0434\u043e\u0431\u0440\u0435\u043d\u043e \u2705")
    await _send_next_pending(callback.message, callback.from_user.id)


@router.callback_query(F.data.startswith("mod_reject:"))
async def cb_reject(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("\u26d4 \u041d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u0430")
        return

    video_id = int(callback.data.split(":")[1])

    await callback.message.edit_reply_markup(
        reply_markup=rejection_reason_keyboard(video_id),
    )
    await callback.answer("\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043f\u0440\u0438\u0447\u0438\u043d\u0443 \u043e\u0442\u043a\u043b\u043e\u043d\u0435\u043d\u0438\u044f")


@router.callback_query(F.data.startswith("reject_reason:"))
async def cb_reject_reason(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("\u26d4 \u041d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u0430")
        return

    parts = callback.data.split(":", 2)
    video_id = int(parts[1])
    reason_key = parts[2]
    reason_text = REASON_MAP.get(reason_key, reason_key)

    async with async_session() as session:
        video = await reject_video(session, video_id, reason_text)

    if video:
        await callback.message.edit_caption(
            caption=f"\u274c \u0412\u0438\u0434\u0435\u043e #{video_id} \u043e\u0442\u043a\u043b\u043e\u043d\u0435\u043d\u043e.\n\u041f\u0440\u0438\u0447\u0438\u043d\u0430: {reason_text}",
        )
    else:
        await callback.message.edit_caption(
            caption=f"\u26a0\ufe0f \u0412\u0438\u0434\u0435\u043e #{video_id} \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e.",
        )

    await callback.answer("\u041e\u0442\u043a\u043b\u043e\u043d\u0435\u043d\u043e \u274c")
    await _send_next_pending(callback.message, callback.from_user.id)


async def _send_next_pending(message: Message, admin_id: int):
    async with async_session() as session:
        pending_count = await count_pending_videos(session)
        video = await get_next_pending_video(session)

    if not video:
        await message.answer("\u2705 \u041e\u0447\u0435\u0440\u0435\u0434\u044c \u043f\u0443\u0441\u0442\u0430! \u0412\u0441\u0435 \u0432\u0438\u0434\u0435\u043e \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u0430\u043d\u044b.")
        return

    await message.answer_video(
        video=video.telegram_file_id,
        caption=(
            f"\U0001f4cb <b>\u041c\u043e\u0434\u0435\u0440\u0430\u0446\u0438\u044f</b>\n"
            f"ID \u0432\u0438\u0434\u0435\u043e: {video.id}\n"
            f"\u0410\u0432\u0442\u043e\u0440 (user_id): {video.uploader_user_id}\n"
            f"\u0414\u043b\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0441\u0442\u044c: {video.duration_seconds or '?'} \u0441\u0435\u043a\n"
            f"\u0412 \u043e\u0447\u0435\u0440\u0435\u0434\u0438: {pending_count}"
        ),
        parse_mode="HTML",
        reply_markup=moderation_keyboard(video.id),
    )
