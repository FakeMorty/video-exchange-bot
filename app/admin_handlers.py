import logging
import traceback

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from app.config import ADMINS
from app.db import async_session
from app.services import (
    get_next_pending_video,
    approve_video,
    reject_video,
    count_pending_videos,
    count_approved_videos,
    count_rejected_videos,
    format_duration,
    format_file_size,
    get_user_by_id,
    create_offer,
    get_all_offers,
    toggle_offer_active,
)
from app.keyboards import (
    moderation_keyboard,
    rejection_reason_keyboard,
    admin_center_keyboard,
    admin_after_action_keyboard,
    admin_offers_menu_keyboard,
    admin_offer_list_keyboard,
)

logger = logging.getLogger(__name__)
router = Router()

REASON_MAP = {
    "duplicate": "\u0414\u0443\u0431\u043b\u0438\u043a\u0430\u0442",
    "off_topic": "\u041d\u0435 \u043f\u043e \u0442\u0435\u043c\u0430\u0442\u0438\u043a\u0435",
    "other": "\u0414\u0440\u0443\u0433\u043e\u0435",
}


class OfferCreateState(StatesGroup):
    title = State()
    description = State()
    channel_url = State()


def is_admin(telegram_id: int) -> bool:
    return telegram_id in ADMINS


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        await message.answer("\u26d4 \u0423 \u0432\u0430\u0441 \u043d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u0430.")
        return

    await message.answer(
        "\U0001f6e0 <b>\u0410\u0434\u043c\u0438\u043d-\u0446\u0435\u043d\u0442\u0440</b>\n\n"
        "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0435:",
        parse_mode="HTML",
        reply_markup=admin_center_keyboard(),
    )


@router.callback_query(F.data == "admin_queue_info")
async def cb_admin_queue_info(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("\u041d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u0430", show_alert=True)
        return

    try:
        async with async_session() as session:
            pending = await count_pending_videos(session)
            approved = await count_approved_videos(session)
            rejected = await count_rejected_videos(session)

        text = (
            "\U0001f4ca <b>\u0421\u0442\u0430\u0442\u0443\u0441 \u043e\u0447\u0435\u0440\u0435\u0434\u0438</b>\n\n"
            f"\U0001f553 \u041d\u0430 \u043c\u043e\u0434\u0435\u0440\u0430\u0446\u0438\u0438: <b>{pending}</b>\n"
            f"\u2705 \u041e\u0434\u043e\u0431\u0440\u0435\u043d\u043e: <b>{approved}</b>\n"
            f"\u274c \u041e\u0442\u043a\u043b\u043e\u043d\u0435\u043d\u043e: <b>{rejected}</b>"
        )
        await callback.message.answer(text, parse_mode="HTML", reply_markup=admin_center_keyboard())
        await callback.answer()
    except Exception as e:
        logger.error(f"[ADMIN_QUEUE] ERROR: {e}")
        logger.error(traceback.format_exc())
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)


@router.callback_query(F.data == "admin_get_pending")
async def cb_admin_get_pending(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("\u041d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u0430", show_alert=True)
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
                    "\u2705 \u041e\u0447\u0435\u0440\u0435\u0434\u044c \u043c\u043e\u0434\u0435\u0440\u0430\u0446\u0438\u0438 \u043f\u0443\u0441\u0442\u0430.",
                    reply_markup=admin_center_keyboard(),
                )
                return

            video_file_id = video.telegram_file_id
            video_id = video.id
            uploader_id = video.uploader_user_id
            duration_text = format_duration(video.duration_seconds)
            file_size_text = format_file_size(video.file_size)

        text = (
            f"\U0001f4cb <b>\u041c\u043e\u0434\u0435\u0440\u0430\u0446\u0438\u044f \u0432\u0438\u0434\u0435\u043e</b>\n\n"
            f"ID \u0432\u0438\u0434\u0435\u043e: <b>{video_id}</b>\n"
            f"\u0410\u0432\u0442\u043e\u0440: <code>{uploader_id}</code>\n"
            f"\u0414\u043b\u0438\u0442\u0435\u043b\u044c\u043d\u043e\u0441\u0442\u044c: <b>{duration_text}</b>\n"
            f"\u0420\u0430\u0437\u043c\u0435\u0440: <b>{file_size_text}</b>\n"
            f"\u0412 \u043e\u0447\u0435\u0440\u0435\u0434\u0438: <b>{pending_count}</b>"
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
        await message.answer("\u041e\u0448\u0438\u0431\u043a\u0430 \u043f\u0440\u0438 \u043f\u043e\u043b\u0443\u0447\u0435\u043d\u0438\u0438 \u0432\u0438\u0434\u0435\u043e \u043d\u0430 \u043c\u043e\u0434\u0435\u0440\u0430\u0446\u0438\u044e.")


@router.callback_query(F.data.startswith("mod_approve:"))
async def cb_approve(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("\u041d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u0430", show_alert=True)
        return

    try:
        video_id = int(callback.data.split(":")[1])

        async with async_session() as session:
            video = await approve_video(session, video_id)
            uploader = await get_user_by_id(session, video.uploader_user_id) if video else None

        if not video:
            await callback.message.edit_caption(
                caption=f"\u26a0\ufe0f \u0412\u0438\u0434\u0435\u043e #{video_id} \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e.",
                reply_markup=admin_after_action_keyboard(),
            )
            await callback.answer("\u0412\u0438\u0434\u0435\u043e \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e")
            return

        await callback.message.edit_caption(
            caption=(
                f"\u2705 \u0412\u0438\u0434\u0435\u043e #{video_id} \u043e\u0434\u043e\u0431\u0440\u0435\u043d\u043e.\n"
                f"\u0410\u0432\u0442\u043e\u0440\u0443 \u043d\u0430\u0447\u0438\u0441\u043b\u0435\u043d\u043e +0.5 \u043c\u043e\u043d\u0435\u0442\u044b."
            ),
            reply_markup=admin_after_action_keyboard(),
        )

        if uploader:
            try:
                await callback.bot.send_message(
                    uploader.telegram_id,
                    f"\u2705 \u0412\u0430\u0448\u0435 \u0432\u0438\u0434\u0435\u043e #{video_id} \u043f\u0440\u043e\u0448\u043b\u043e \u043c\u043e\u0434\u0435\u0440\u0430\u0446\u0438\u044e.\n"
                    f"\u0412\u0430\u043c \u043d\u0430\u0447\u0438\u0441\u043b\u0435\u043d\u043e <b>0.5 \u043c\u043e\u043d\u0435\u0442\u044b</b>.",
                    parse_mode="HTML",
                )
            except Exception as notify_error:
                logger.warning(f"[APPROVE_NOTIFY] \u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0443\u0432\u0435\u0434\u043e\u043c\u0438\u0442\u044c \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044f: {notify_error}")

        await callback.answer("\u041e\u0434\u043e\u0431\u0440\u0435\u043d\u043e")
    except Exception as e:
        logger.error(f"[APPROVE] ERROR: {e}")
        logger.error(traceback.format_exc())
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430 \u043f\u0440\u0438 \u043e\u0434\u043e\u0431\u0440\u0435\u043d\u0438\u0438", show_alert=True)


@router.callback_query(F.data.startswith("mod_reject:"))
async def cb_reject(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("\u041d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u0430", show_alert=True)
        return

    try:
        video_id = int(callback.data.split(":")[1])
        await callback.message.edit_reply_markup(reply_markup=rejection_reason_keyboard(video_id))
        await callback.answer("\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043f\u0440\u0438\u0447\u0438\u043d\u0443")
    except Exception as e:
        logger.error(f"[REJECT] ERROR: {e}")
        logger.error(traceback.format_exc())
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)


@router.callback_query(F.data.startswith("reject_reason:"))
async def cb_reject_reason(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("\u041d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u0430", show_alert=True)
        return

    try:
        parts = callback.data.split(":", 2)
        video_id = int(parts[1])
        reason_key = parts[2]
        reason_text = REASON_MAP.get(reason_key, "\u0414\u0440\u0443\u0433\u043e\u0435")

        async with async_session() as session:
            video = await reject_video(session, video_id, reason_text)
            uploader = await get_user_by_id(session, video.uploader_user_id) if video else None

        if not video:
            await callback.message.edit_caption(
                caption=f"\u26a0\ufe0f \u0412\u0438\u0434\u0435\u043e #{video_id} \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e.",
                reply_markup=admin_after_action_keyboard(),
            )
            await callback.answer("\u0412\u0438\u0434\u0435\u043e \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e")
            return

        await callback.message.edit_caption(
            caption=(
                f"\u274c \u0412\u0438\u0434\u0435\u043e #{video_id} \u043e\u0442\u043a\u043b\u043e\u043d\u0435\u043d\u043e.\n"
                f"\u041f\u0440\u0438\u0447\u0438\u043d\u0430: {reason_text}"
            ),
            reply_markup=admin_after_action_keyboard(),
        )

        if uploader:
            try:
                await callback.bot.send_message(
                    uploader.telegram_id,
                    f"\u274c \u0412\u0430\u0448\u0435 \u0432\u0438\u0434\u0435\u043e #{video_id} \u043d\u0435 \u043f\u0440\u043e\u0448\u043b\u043e \u043c\u043e\u0434\u0435\u0440\u0430\u0446\u0438\u044e.\n"
                    f"\u041f\u0440\u0438\u0447\u0438\u043d\u0430: <b>{reason_text}</b>.",
                    parse_mode="HTML",
                )
            except Exception as notify_error:
                logger.warning(f"[REJECT_NOTIFY] \u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0443\u0432\u0435\u0434\u043e\u043c\u0438\u0442\u044c \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044f: {notify_error}")

        await callback.answer("\u041e\u0442\u043a\u043b\u043e\u043d\u0435\u043d\u043e")
    except Exception as e:
        logger.error(f"[REJECT_REASON] ERROR: {e}")
        logger.error(traceback.format_exc())
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430 \u043f\u0440\u0438 \u043e\u0442\u043a\u043b\u043e\u043d\u0435\u043d\u0438\u0438", show_alert=True)


# ===== OFFERS ADMIN =====

@router.callback_query(F.data == "admin_offers_menu")
async def admin_offers_menu(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("\u041d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u0430", show_alert=True)
        return

    await callback.message.answer(
        "\U0001f381 <b>\u0423\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435 \u043e\u0444\u0444\u0435\u0440\u0430\u043c\u0438</b>\n\n"
        "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0435:",
        parse_mode="HTML",
        reply_markup=admin_offers_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_offer_create")
async def admin_offer_create(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("\u041d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u0430", show_alert=True)
        return

    await state.set_state(OfferCreateState.title)
    await callback.message.answer("\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 \u043e\u0444\u0444\u0435\u0440\u0430:")
    await callback.answer()


@router.message(OfferCreateState.title)
async def offer_create_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text or "")
    await state.set_state(OfferCreateState.description)
    await message.answer("\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0442\u0435\u043a\u0441\u0442 \u0440\u0435\u043a\u043b\u0430\u043c\u044b / \u043e\u043f\u0438\u0441\u0430\u043d\u0438\u0435 \u043e\u0444\u0444\u0435\u0440\u0430:")


@router.message(OfferCreateState.description)
async def offer_create_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text or "")
    await state.set_state(OfferCreateState.channel_url)
    await message.answer("\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0441\u0441\u044b\u043b\u043a\u0443 \u043d\u0430 \u043a\u0430\u043d\u0430\u043b (\u043d\u0430\u043f\u0440\u0438\u043c\u0435\u0440 https://t.me/yourchannel):")


@router.message(OfferCreateState.channel_url)
async def offer_create_channel(message: Message, state: FSMContext):
    data = await state.get_data()

    try:
        async with async_session() as session:
            offer = await create_offer(
                session=session,
                title=data["title"],
                description=data["description"],
                channel_url=message.text or "",
            )

        await message.answer(
            f"\u2705 \u041e\u0444\u0444\u0435\u0440 \u0441\u043e\u0437\u0434\u0430\u043d.\n\n"
            f"ID: <b>{offer.id}</b>\n"
            f"\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435: <b>{offer.title}</b>",
            parse_mode="HTML",
            reply_markup=admin_offers_menu_keyboard(),
        )
    except Exception as e:
        logger.error(f"[OFFER_CREATE] ERROR: {e}")
        logger.error(traceback.format_exc())
        await message.answer("\u041e\u0448\u0438\u0431\u043a\u0430 \u043f\u0440\u0438 \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u0438 \u043e\u0444\u0444\u0435\u0440\u0430.")
    finally:
        await state.clear()


@router.callback_query(F.data == "admin_offer_list")
async def admin_offer_list(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("\u041d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u0430", show_alert=True)
        return

    try:
        async with async_session() as session:
            all_offers = await get_all_offers(session)

        if not all_offers:
            await callback.message.answer(
                "\u041e\u0444\u0444\u0435\u0440\u043e\u0432 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442.",
                reply_markup=admin_offers_menu_keyboard(),
            )
            await callback.answer()
            return

        await callback.message.answer(
            "\U0001f4cb <b>\u0421\u043f\u0438\u0441\u043e\u043a \u043e\u0444\u0444\u0435\u0440\u043e\u0432</b>\n\n"
            "\u041d\u0430\u0436\u043c\u0438\u0442\u0435 \u043d\u0430 \u043e\u0444\u0444\u0435\u0440, \u0447\u0442\u043e\u0431\u044b \u0432\u043a\u043b\u044e\u0447\u0438\u0442\u044c \u0438\u043b\u0438 \u0432\u044b\u043a\u043b\u044e\u0447\u0438\u0442\u044c \u0435\u0433\u043e.",
            parse_mode="HTML",
            reply_markup=admin_offer_list_keyboard(all_offers),
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"[OFFER_LIST] ERROR: {e}")
        logger.error(traceback.format_exc())
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)


@router.callback_query(F.data.startswith("admin_offer_toggle:"))
async def admin_offer_toggle(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("\u041d\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u0430", show_alert=True)
        return

    try:
        offer_id = int(callback.data.split(":")[1])

        async with async_session() as session:
            offer = await toggle_offer_active(session, offer_id)

        if not offer:
            await callback.answer("\u041e\u0444\u0444\u0435\u0440 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d", show_alert=True)
            return

        state_text = "\u0432\u043a\u043b\u044e\u0447\u0451\u043d" if offer.is_active else "\u0432\u044b\u043a\u043b\u044e\u0447\u0435\u043d"
        await callback.message.answer(
            f"\u041e\u0444\u0444\u0435\u0440 <b>{offer.title}</b> \u0442\u0435\u043f\u0435\u0440\u044c {state_text}.",
            parse_mode="HTML",
            reply_markup=admin_offers_menu_keyboard(),
        )
        await callback.answer("\u0413\u043e\u0442\u043e\u0432\u043e")
    except Exception as e:
        logger.error(f"[OFFER_TOGGLE] ERROR: {e}")
        logger.error(traceback.format_exc())
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)
