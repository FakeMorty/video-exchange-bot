"""
Moderation handlers.
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select

from app.db import async_session
from app.services import (
    get_next_pending_video, approve_video, reject_video,
    get_user_by_id, get_display_name
)
from app.utils.admin import check_admin
from app.keyboards import moderation_keyboard, rejection_reason_keyboard, admin_after_action_keyboard

router = Router()

async def admin_get_pending(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        video = await get_next_pending_video(session)
        if not video:
            await _safe_edit(
                callback,
                "✅ Очередь модерации пуста!",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")]
                ])
            )
            await callback.answer()
            return

        uploader = await get_user_by_id(session, video.uploader_user_id)
        name = get_display_name(uploader) if uploader else "???"
        tg_id = uploader.telegram_id if uploader else "???"

        caption = (
            f"📹 #{video.id} | {video.content_type}\n"
            f"👤 {name} (tg: {tg_id})\n"
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
            await callback.answer("Уже обработано.", show_alert=True)
            return
        uploader = await get_user_by_id(session, video.uploader_user_id)
        if uploader:
            try:
                await callback.bot.send_message(
                    uploader.telegram_id,
                    f"✅ Ваше видео #{video_id} одобрено! Монеты начислены."
                )
            except Exception:
                pass

    # Редактируем сообщение с видео, добавляя статус
    try:
        await callback.message.edit_caption(
            caption=f"✅ #{video_id} — ОДОБРЕНО",
            reply_markup=admin_after_action_keyboard()
        )
    except Exception:
        try:
            await callback.message.edit_reply_markup(
                reply_markup=admin_after_action_keyboard()
            )
        except Exception:
            pass
    await callback.answer(f"✅ #{video_id} одобрено!", show_alert=False)


@router.callback_query(F.data.startswith("mod_reject:"))
async def mod_reject(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    video_id = int(callback.data.split(":")[1])
    # Показываем причины прямо в inline-клавиатуре под видео
    try:
        await callback.message.edit_reply_markup(
            reply_markup=rejection_reason_keyboard(video_id)
        )
    except Exception:
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
    reason_key = parts[2]
    reason_map = {
        "duplicate": "Дубликат",
        "off_topic": "Не по теме",
        "forbidden": "Запрещённый контент",
        "other": "Другая причина",
    }
    reason_text = reason_map.get(reason_key, reason_key)

    async with async_session() as session:
        video = await reject_video(session, video_id, reason_text)
        if not video:
            await callback.answer("Не найдено.", show_alert=True)
            return
        uploader = await get_user_by_id(session, video.uploader_user_id)
        if uploader:
            try:
                await callback.bot.send_message(
                    uploader.telegram_id,
                    f"❌ Видео #{video_id} отклонено.\nПричина: {reason_text}"
                )
            except Exception:
                pass

    # Редактируем сообщение
    try:
        await callback.message.edit_caption(
            caption=f"❌ #{video_id} — ОТКЛОНЕНО\nПричина: {reason_text}",
            reply_markup=admin_after_action_keyboard()
        )
    except Exception:
        try:
            await callback.message.edit_reply_markup(
                reply_markup=admin_after_action_keyboard()
            )
        except Exception:
            pass
    await callback.answer(f"❌ Отклонено: {reason_text}", show_alert=False)


@router.callback_query(F.data == "admin_approve_all")
async def admin_approve_all(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    await callback.answer("⏳ Одобряю все видео...", show_alert=False)

    count = 0
    errors = 0
    # Каждый approve в отдельной сессии чтобы избежать stale data
    uploader_notifications = {}
    for _ in range(200):  # защита от бесконечного цикла
        async with async_session() as session:
            video = await get_next_pending_video(session)
            if not video:
                break
            try:
                result = await approve_video(session, video.id)
                if result:
                    count += 1
                    uploader = await get_user_by_id(session, video.uploader_user_id)
                    if uploader:
                        uploader_notifications[uploader.telegram_id] = uploader_notifications.get(uploader.telegram_id, 0) + 1
                else:
                    break
            except Exception:
                errors += 1
                break

    import asyncio
    for tg_id, approved_count in uploader_notifications.items():
        try:
            await callback.bot.send_message(
                tg_id,
                f"✅ Одобрено {approved_count} ваших видео/фото! Монеты начислены."
            )
        except Exception:
            pass
        await asyncio.sleep(0.05)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀ В меню", callback_data="admin_center")]
    ])
    result_text = f"✅ Одобрено видео: <b>{count}</b>"
    if errors:
        result_text += f"\n⚠️ Ошибок: {errors}"

    await callback.message.answer(
        result_text,
        parse_mode="HTML",
        reply_markup=kb
    )


@router.callback_query(F.data == "admin_trusted_uploaders")
