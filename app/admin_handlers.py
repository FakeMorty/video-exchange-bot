import logging
import traceback
from decimal import Decimal

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
    get_active_offers,
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
    "duplicate": "Дубликат",
    "off_topic": "Не по тематике",
    "other": "Другое",
}


class OfferCreateState(StatesGroup):
    title = State()
    description = State()
    channel_url = State()
    reward_preview = State()
    reward_final = State()
    penalty = State()


def is_admin(telegram_id: int) -> bool:
    return telegram_id in ADMINS


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа.")
        return

    await message.answer(
        "🛠 <b>Админ-центр</b>\n\n"
        "Выберите действие:",
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
            duration_text = format_duration(video.duration_seconds)
            file_size_text = format_file_size(video.file_size)

        text = (
            f"📋 <b>Модерация видео</b>\n\n"
            f"ID видео: <b>{video_id}</b>\n"
            f"Автор: <code>{uploader_id}</code>\n"
            f"Длительность: <b>{duration_text}</b>\n"
            f"Размер: <b>{file_size_text}</b>\n"
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
            uploader = await get_user_by_id(session, video.uploader_user_id) if video else None

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

        if uploader:
            try:
                await callback.bot.send_message(
                    uploader.telegram_id,
                    f"✅ Ваше видео #{video_id} прошло модерацию.\n"
                    f"Вам начислено <b>0.5 монеты</b>.",
                    parse_mode="HTML",
                )
            except Exception as notify_error:
                logger.warning(f"[APPROVE_NOTIFY] Не удалось уведомить пользователя: {notify_error}")

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
            uploader = await get_user_by_id(session, video.uploader_user_id) if video else None

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

        if uploader:
            try:
                await callback.bot.send_message(
                    uploader.telegram_id,
                    f"❌ Ваше видео #{video_id} не прошло модерацию.\n"
                    f"Причина: <b>{reason_text}</b>.",
                    parse_mode="HTML",
                )
            except Exception as notify_error:
                logger.warning(f"[REJECT_NOTIFY] Не удалось уведомить пользователя: {notify_error}")

        await callback.answer("Отклонено")
    except Exception as e:
        logger.error(f"[REJECT_REASON] ERROR: {e}")
        logger.error(traceback.format_exc())
        await callback.answer("Ошибка при отклонении", show_alert=True)


# ===== OFFERS ADMIN =====

@router.callback_query(F.data == "admin_offers_menu")
async def admin_offers_menu(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await callback.message.answer(
        "🎁 <b>Управление офферами</b>\n\n"
        "Выберите действие:",
        parse_mode="HTML",
        reply_markup=admin_offers_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_offer_create")
async def admin_offer_create(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(OfferCreateState.title)
    await callback.message.answer("Введите название оффера:")
    await callback.answer()


@router.message(OfferCreateState.title)
async def offer_create_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text or "")
    await state.set_state(OfferCreateState.description)
    await message.answer("Введите текст рекламы / описание оффера:")


@router.message(OfferCreateState.description)
async def offer_create_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text or "")
    await state.set_state(OfferCreateState.channel_url)
    await message.answer("Введите ссылку на канал (например https://t.me/yourchannel):")


@router.message(OfferCreateState.channel_url)
async def offer_create_channel(message: Message, state: FSMContext):
    await state.update_data(channel_url=message.text or "")
    await state.set_state(OfferCreateState.reward_preview)
    await message.answer("Введите награду за старт оффера (например 10):")


@router.message(OfferCreateState.reward_preview)
async def offer_create_preview(message: Message, state: FSMContext):
    try:
        value = Decimal((message.text or "").replace(",", "."))
    except Exception:
        await message.answer("Введите число, например 10")
        return

    await state.update_data(reward_preview=value)
    await state.set_state(OfferCreateState.reward_final)
    await message.answer("Введите финальную награду после подтверждения подписки (например 30):")


@router.message(OfferCreateState.reward_final)
async def offer_create_final(message: Message, state: FSMContext):
    try:
        value = Decimal((message.text or "").replace(",", "."))
    except Exception:
        await message.answer("Введите число, например 30")
        return

    await state.update_data(reward_final=value)
    await state.set_state(OfferCreateState.penalty)
    await message.answer("Введите штраф за отписку (например 40):")


@router.message(OfferCreateState.penalty)
async def offer_create_penalty(message: Message, state: FSMContext):
    try:
        penalty = Decimal((message.text or "").replace(",", "."))
    except Exception:
        await message.answer("Введите число, например 40")
        return

    data = await state.get_data()

    try:
        async with async_session() as session:
            offer = await create_offer(
                session=session,
                title=data["title"],
                description=data["description"],
                channel_url=data["channel_url"],
                reward_preview=data["reward_preview"],
                reward_final=data["reward_final"],
                penalty_unsubscribe=penalty,
            )

        await message.answer(
            f"✅ Оффер создан.\n\n"
            f"ID: <b>{offer.id}</b>\n"
            f"Название: <b>{offer.title}</b>",
            parse_mode="HTML",
            reply_markup=admin_offers_menu_keyboard(),
        )
    except Exception as e:
        logger.error(f"[OFFER_CREATE] ERROR: {e}")
        logger.error(traceback.format_exc())
        await message.answer("Ошибка при создании оффера.")
    finally:
        await state.clear()


@router.callback_query(F.data == "admin_offer_list")
async def admin_offer_list(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    try:
        async with async_session() as session:
            offers = await get_active_offers(session)

            # Чтобы показать и активные, и неактивные, запросим вручную
            from sqlalchemy import select
            from app.models import Offer
            result = await session.execute(select(Offer).order_by(Offer.created_at.desc()))
            all_offers = list(result.scalars().all())

        if not all_offers:
            await callback.message.answer(
                "Офферов пока нет.",
                reply_markup=admin_offers_menu_keyboard(),
            )
            await callback.answer()
            return

        await callback.message.answer(
            "📋 <b>Список офферов</b>\n\n"
            "Нажмите на оффер, чтобы включить или выключить его.",
            parse_mode="HTML",
            reply_markup=admin_offer_list_keyboard(all_offers),
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"[OFFER_LIST] ERROR: {e}")
        logger.error(traceback.format_exc())
        await callback.answer("Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("admin_offer_toggle:"))
async def admin_offer_toggle(callback: CallbackQuery):
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    try:
        offer_id = int(callback.data.split(":")[1])

        async with async_session() as session:
            offer = await toggle_offer_active(session, offer_id)

        if not offer:
            await callback.answer("Оффер не найден", show_alert=True)
            return

        state_text = "включён" if offer.is_active else "выключен"
        await callback.message.answer(
            f"Оффер <b>{offer.title}</b> теперь {state_text}.",
            parse_mode="HTML",
            reply_markup=admin_offers_menu_keyboard(),
        )
        await callback.answer("Готово")
    except Exception as e:
        logger.error(f"[OFFER_TOGGLE] ERROR: {e}")
        logger.error(traceback.format_exc())
        await callback.answer("Ошибка", show_alert=True)