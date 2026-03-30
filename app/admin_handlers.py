import traceback
from datetime import datetime

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from app.config import ADMINS, LOG_CHAT_ID
from app.db import async_session
from app.services import (
    get_user,
    get_next_pending_video,
    approve_video,
    reject_video,
    approve_all_pending,
    count_pending_videos,
    count_approved_videos,
    count_rejected_videos,
    format_duration,
    format_file_size,
    get_user_by_id,
    create_offer,
    get_all_offers,
    toggle_offer_active,
    get_user_by_username,
    set_user_admin,
    get_db_admins,
    get_admin_extended_stats,
)
from app.keyboards import (
    moderation_keyboard,
    rejection_reason_keyboard,
    admin_center_keyboard,
    admin_after_action_keyboard,
    admin_offers_menu_keyboard,
    admin_offer_list_keyboard,
    admin_manage_keyboard,
    back_to_admin_manage_keyboard,
)
from app.logger import get_logger, log_info, log_warning, log_exception

logger = get_logger(__name__)
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


class AdminManageState(StatesGroup):
    waiting_add_username = State()
    waiting_remove_username = State()


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


async def send_admin_log(bot, text: str):
    if not LOG_CHAT_ID:
        return

    try:
        await bot.send_message(int(LOG_CHAT_ID), text, parse_mode="HTML")
    except Exception as e:
        log_warning(
            logger,
            "Не удалось отправить лог в Telegram",
            error=str(e),
            log_chat_id=LOG_CHAT_ID,
        )


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not message.from_user:
        return

    ok = await check_admin(message.from_user.id)
    if not ok:
        await message.answer("\u26d4")
        return

    sa = is_super_admin(message.from_user.id)

    log_info(
        logger,
        "Открыта админ-панель через команду /admin",
        tg_id=message.from_user.id,
        is_super_admin=sa,
    )

    await message.answer(
        "\U0001f6e0 <b>\u0410\u0434\u043c\u0438\u043d</b>",
        parse_mode="HTML",
        reply_markup=admin_center_keyboard(is_super_admin=sa),
    )


@router.callback_query(F.data == "admin_queue_info")
async def cb_queue(callback: CallbackQuery):
    if not callback.from_user:
        return

    ok = await check_admin(callback.from_user.id)
    if not ok:
        await callback.answer("\u26d4", show_alert=True)
        return

    try:
        async with async_session() as session:
            p = await count_pending_videos(session)
            a = await count_approved_videos(session)
            r = await count_rejected_videos(session)

        sa = is_super_admin(callback.from_user.id)

        text = (
            f"\U0001f4ca <b>\u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430</b>\n\n"
            f"\u23f3 \u041d\u0430 \u043c\u043e\u0434\u0435\u0440\u0430\u0446\u0438\u0438: <b>{p}</b>\n"
            f"\u2705 \u041e\u0434\u043e\u0431\u0440\u0435\u043d\u043e: <b>{a}</b>\n"
            f"\u274c \u041e\u0442\u043a\u043b\u043e\u043d\u0435\u043d\u043e: <b>{r}</b>"
        )

        log_info(
            logger,
            "Открыта статистика очереди модерации",
            tg_id=callback.from_user.id,
            pending=p,
            approved=a,
            rejected=r,
        )

        try:
            await callback.message.edit_text(
                text,
                parse_mode="HTML",
                reply_markup=admin_center_keyboard(is_super_admin=sa),
            )
        except Exception:
            await callback.message.answer(
                text,
                parse_mode="HTML",
                reply_markup=admin_center_keyboard(is_super_admin=sa),
            )

        await callback.answer()
    except Exception:
        log_exception(
            logger,
            "Ошибка при открытии статистики очереди",
            tg_id=callback.from_user.id if callback.from_user else None,
        )
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)


@router.callback_query(F.data == "admin_extended_stats")
async def cb_extended_stats(callback: CallbackQuery):
    if not callback.from_user:
        return

    ok = await check_admin(callback.from_user.id)
    if not ok:
        await callback.answer("\u26d4", show_alert=True)
        return

    try:
        async with async_session() as session:
            stats = await get_admin_extended_stats(session)

        text = (
            "\U0001f4ca <b>\u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430+</b>\n\n"
            f"\U0001f465 \u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0438: <b>{stats['users']}</b>\n"
            f"\U0001f48e VIP: <b>{stats['vip']}</b>\n"
            f"\U0001f4ac \u041a\u043e\u043c\u043c\u0435\u043d\u0442\u044b: <b>{stats['comments']}</b>\n"
            f"\u2764\ufe0f \u0420\u0435\u0430\u043a\u0446\u0438\u0438: <b>{stats['reactions']}</b>\n"
            f"\U0001f3ae \u0418\u0433\u0440\u044b: <b>{stats['games']}</b>\n"
            f"\U0001f381 \u041e\u0444\u0444\u0435\u0440\u044b: <b>{stats['offers']}</b>"
        )

        log_info(
            logger,
            "Открыта расширенная статистика",
            tg_id=callback.from_user.id,
            **stats,
        )

        await callback.message.answer(text, parse_mode="HTML")
        await callback.answer()
    except Exception:
        log_exception(
            logger,
            "Ошибка при открытии расширенной статистики",
            tg_id=callback.from_user.id if callback.from_user else None,
        )
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)


@router.callback_query(F.data == "admin_logs")
async def cb_admin_logs(callback: CallbackQuery):
    if not callback.from_user:
        return

    if not await check_admin(callback.from_user.id):
        await callback.answer("\u26d4", show_alert=True)
        return

    if not LOG_CHAT_ID:
        await callback.answer("LOG_CHAT_ID \u043d\u0435 \u0437\u0430\u0434\u0430\u043d", show_alert=True)
        return

    log_info(
        logger,
        "Открыт лог-центр",
        tg_id=callback.from_user.id,
        log_chat_id=LOG_CHAT_ID,
    )

    text = (
        "\U0001f4dc <b>\u041b\u043e\u0433-\u0446\u0435\u043d\u0442\u0440</b>\n\n"
        f"\u041b\u043e\u0433\u0438 \u0438\u0434\u0443\u0442 \u0432 chat_id: <code>{LOG_CHAT_ID}</code>\n"
        "\u0412\u0430\u0436\u043d\u044b\u0435 \u0441\u043e\u0431\u044b\u0442\u0438\u044f \u0431\u0443\u0434\u0443\u0442 \u043f\u0440\u0438\u0445\u043e\u0434\u0438\u0442\u044c \u0442\u0443\u0434\u0430."
    )
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin_approve_all")
async def cb_approve_all(callback: CallbackQuery):
    if not callback.from_user:
        return

    ok = await check_admin(callback.from_user.id)
    if not ok:
        await callback.answer("\u26d4", show_alert=True)
        return

    try:
        async with async_session() as session:
            count = await approve_all_pending(session)

        sa = is_super_admin(callback.from_user.id)
        text = f"\u2705 \u041e\u0434\u043e\u0431\u0440\u0435\u043d\u043e \u0432\u0441\u0451: <b>{count}</b> \u0435\u0434."

        log_info(
            logger,
            "Выполнено массовое одобрение контента",
            tg_id=callback.from_user.id,
            approved_count=count,
        )

        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=admin_center_keyboard(is_super_admin=sa),
        )

        await send_admin_log(
            callback.bot,
            f"\U0001f7e2 <b>APPROVE ALL</b>\n"
            f"\u0410\u0434\u043c\u0438\u043d: <code>{callback.from_user.id}</code>\n"
            f"\u041e\u0434\u043e\u0431\u0440\u0435\u043d\u043e: <b>{count}</b>\n"
            f"\u0412\u0440\u0435\u043c\u044f: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )

        await callback.answer()
    except Exception:
        log_exception(
            logger,
            "Ошибка при массовом одобрении контента",
            tg_id=callback.from_user.id if callback.from_user else None,
        )
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)


@router.callback_query(F.data == "admin_get_pending")
async def cb_pending(callback: CallbackQuery):
    if not callback.from_user:
        return

    ok = await check_admin(callback.from_user.id)
    if not ok:
        await callback.answer("\u26d4", show_alert=True)
        return

    log_info(
        logger,
        "Запрошен следующий pending-контент",
        tg_id=callback.from_user.id,
    )

    await callback.answer()
    await _send_pending(callback.message, callback.from_user.id)


async def _send_pending(message, admin_id: int | None = None):
    try:
        async with async_session() as session:
            pc = await count_pending_videos(session)
            video = await get_next_pending_video(session)

            if not video:
                await message.answer(
                    "\u2705 \u041f\u0443\u0441\u0442\u043e.",
                    reply_markup=admin_center_keyboard(
                        is_super_admin=admin_id in ADMINS if admin_id else False
                    ),
                )
                return

            fid = video.telegram_file_id
            vid = video.id
            uid = video.uploader_user_id
            ct = video.content_type
            dur = format_duration(video.duration_seconds) if ct == "video" else "\u2014"
            sz = format_file_size(video.file_size)
            label = "\U0001f5bc \u0424\u043e\u0442\u043e" if ct == "photo" else "\U0001f3ac \u0412\u0438\u0434\u0435\u043e"

            cap = (
                f"\U0001f4cb <b>\u041c\u043e\u0434\u0435\u0440\u0430\u0446\u0438\u044f</b>\n\n"
                f"{label} #{vid}\n"
                f"\u0410\u0432\u0442\u043e\u0440: {uid}\n"
                f"\u0414\u043b\u0438\u0442.: {dur}\n"
                f"\u0420\u0430\u0437\u043c.: {sz}\n"
                f"\u041e\u0447\u0435\u0440\u0435\u0434\u044c: {pc}"
            )

            log_info(
                logger,
                "Отправлен следующий pending-контент модератору",
                admin_id=admin_id,
                video_id=vid,
                uploader_id=uid,
                content_type=ct,
                pending_total=pc,
            )

            if ct == "photo":
                await message.answer_photo(
                    photo=fid,
                    caption=cap,
                    parse_mode="HTML",
                    reply_markup=moderation_keyboard(vid),
                )
            else:
                await message.answer_video(
                    video=fid,
                    caption=cap,
                    parse_mode="HTML",
                    reply_markup=moderation_keyboard(vid),
                )
    except Exception:
        log_exception(
            logger,
            "Ошибка при отправке pending-контента модератору",
            admin_id=admin_id,
        )
        await message.answer("\u041e\u0448\u0438\u0431\u043a\u0430.")


@router.callback_query(F.data.startswith("mod_approve:"))
async def cb_approve(callback: CallbackQuery):
    if not callback.from_user:
        return

    ok = await check_admin(callback.from_user.id)
    if not ok:
        await callback.answer("\u26d4", show_alert=True)
        return

    try:
        vid = int(callback.data.split(":")[1])

        async with async_session() as session:
            video = await approve_video(session, vid)
            uploader = await get_user_by_id(session, video.uploader_user_id) if video else None

            if not video:
                await callback.message.edit_caption(
                    caption=f"#{vid} \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d.",
                    reply_markup=admin_after_action_keyboard(),
                )
                await callback.answer()
                return

            rw = "0.1" if video.content_type == "photo" else "0.5"

            log_info(
                logger,
                "Контент одобрен модератором",
                tg_id=callback.from_user.id,
                video_id=vid,
                content_type=video.content_type,
                reward=rw,
                uploader_id=video.uploader_user_id,
            )

            await callback.message.edit_caption(
                caption=f"\u2705 #{vid} +{rw}",
                reply_markup=admin_after_action_keyboard(),
            )

            if uploader:
                try:
                    await callback.bot.send_message(
                        uploader.telegram_id,
                        f"\u2705 #{vid} \u043e\u0434\u043e\u0431\u0440\u0435\u043d. +<b>{rw}</b>",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass

            await send_admin_log(
                callback.bot,
                f"\U0001f7e2 <b>APPROVED</b>\n"
                f"\u0410\u0434\u043c\u0438\u043d: <code>{callback.from_user.id}</code>\n"
                f"\u041a\u043e\u043d\u0442\u0435\u043d\u0442: <b>#{vid}</b>\n"
                f"\u0422\u0438\u043f: {video.content_type}\n"
                f"\u0410\u0432\u0442\u043e\u0440: <code>{video.uploader_user_id}</code>"
            )

            await callback.answer("\u041e\u0434\u043e\u0431\u0440\u0435\u043d\u043e")
    except Exception:
        log_exception(
            logger,
            "Ошибка при одобрении контента",
            tg_id=callback.from_user.id if callback.from_user else None,
        )
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)


@router.callback_query(F.data.startswith("mod_reject:"))
async def cb_reject(callback: CallbackQuery):
    if not callback.from_user:
        return

    ok = await check_admin(callback.from_user.id)
    if not ok:
        await callback.answer("\u26d4", show_alert=True)
        return

    vid = int(callback.data.split(":")[1])

    log_info(
        logger,
        "Открыт выбор причины отклонения",
        tg_id=callback.from_user.id,
        video_id=vid,
    )

    await callback.message.edit_reply_markup(reply_markup=rejection_reason_keyboard(vid))
    await callback.answer()


@router.callback_query(F.data.startswith("reject_reason:"))
async def cb_reject_reason(callback: CallbackQuery):
    if not callback.from_user:
        return

    ok = await check_admin(callback.from_user.id)
    if not ok:
        await callback.answer("\u26d4", show_alert=True)
        return

    try:
        parts = callback.data.split(":", 2)
        vid = int(parts[1])
        rk = parts[2]
        rt = REASON_MAP.get(rk, "\u0414\u0440\u0443\u0433\u043e\u0435")

        async with async_session() as session:
            video = await reject_video(session, vid, rt)
            uploader = await get_user_by_id(session, video.uploader_user_id) if video else None

            if not video:
                await callback.message.edit_caption(
                    caption=f"#{vid} \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d.",
                    reply_markup=admin_after_action_keyboard(),
                )
                await callback.answer()
                return

            log_info(
                logger,
                "Контент отклонён модератором",
                tg_id=callback.from_user.id,
                video_id=vid,
                reason=rt,
                uploader_id=video.uploader_user_id,
            )

            await callback.message.edit_caption(
                caption=f"\u274c #{vid}: {rt}",
                reply_markup=admin_after_action_keyboard(),
            )

            if uploader:
                try:
                    await callback.bot.send_message(
                        uploader.telegram_id,
                        f"\u274c #{vid}: <b>{rt}</b>",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass

            await send_admin_log(
                callback.bot,
                f"\U0001f534 <b>REJECTED</b>\n"
                f"\u0410\u0434\u043c\u0438\u043d: <code>{callback.from_user.id}</code>\n"
                f"\u041a\u043e\u043d\u0442\u0435\u043d\u0442: <b>#{vid}</b>\n"
                f"\u041f\u0440\u0438\u0447\u0438\u043d\u0430: <b>{rt}</b>\n"
                f"\u0410\u0432\u0442\u043e\u0440: <code>{video.uploader_user_id}</code>"
            )

            await callback.answer("\u041e\u0442\u043a\u043b\u043e\u043d\u0435\u043d\u043e")
    except Exception:
        log_exception(
            logger,
            "Ошибка при отклонении контента",
            tg_id=callback.from_user.id if callback.from_user else None,
        )
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)


@router.callback_query(F.data == "admin_offers_menu")
async def offers_menu(callback: CallbackQuery):
    if not callback.from_user:
        return

    ok = await check_admin(callback.from_user.id)
    if not ok:
        await callback.answer("\u26d4", show_alert=True)
        return

    log_info(
        logger,
        "Открыто меню управления офферами",
        tg_id=callback.from_user.id,
    )

    await callback.message.answer(
        "\U0001f381 <b>\u041e\u0444\u0444\u0435\u0440\u044b</b>",
        parse_mode="HTML",
        reply_markup=admin_offers_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_offer_create")
async def offer_create(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return

    ok = await check_admin(callback.from_user.id)
    if not ok:
        await callback.answer("\u26d4", show_alert=True)
        return

    log_info(
        logger,
        "Начато создание оффера администратором",
        tg_id=callback.from_user.id,
    )

    await state.set_state(OfferCreateState.title)
    await callback.message.answer("\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 \u043e\u0444\u0444\u0435\u0440\u0430:")
    await callback.answer()


@router.message(OfferCreateState.title)
async def oc_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text or "")
    await state.set_state(OfferCreateState.description)
    await message.answer("\u041e\u043f\u0438\u0441\u0430\u043d\u0438\u0435:")


@router.message(OfferCreateState.description)
async def oc_desc(message: Message, state: FSMContext):
    await state.update_data(description=message.text or "")
    await state.set_state(OfferCreateState.channel_url)
    await message.answer("\u0421\u0441\u044b\u043b\u043a\u0430 \u043d\u0430 \u043a\u0430\u043d\u0430\u043b:")


@router.message(OfferCreateState.channel_url)
async def oc_url(message: Message, state: FSMContext):
    data = await state.get_data()

    try:
        async with async_session() as session:
            offer = await create_offer(
                session,
                data["title"],
                data["description"],
                message.text or "",
            )

        log_info(
            logger,
            "Оффер создан администратором",
            tg_id=message.from_user.id if message.from_user else None,
            offer_id=offer.id,
            title=offer.title,
        )

        await message.answer(
            f"\u2705 \u041e\u0444\u0444\u0435\u0440 #{offer.id} \u0441\u043e\u0437\u0434\u0430\u043d.",
            reply_markup=admin_offers_menu_keyboard(),
        )

        await send_admin_log(
            message.bot,
            f"\U0001f381 <b>NEW OFFER</b>\n"
            f"\u0410\u0434\u043c\u0438\u043d: <code>{message.from_user.id}</code>\n"
            f"ID: <b>{offer.id}</b>\n"
            f"\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435: {offer.title}"
        )
    except Exception:
        log_exception(
            logger,
            "Ошибка при создании оффера",
            tg_id=message.from_user.id if message.from_user else None,
        )
        await message.answer("\u041e\u0448\u0438\u0431\u043a\u0430.")
    finally:
        await state.clear()


@router.callback_query(F.data == "admin_offer_list")
async def offer_list(callback: CallbackQuery):
    if not callback.from_user:
        return

    ok = await check_admin(callback.from_user.id)
    if not ok:
        await callback.answer("\u26d4", show_alert=True)
        return

    try:
        async with async_session() as session:
            offers = await get_all_offers(session)

        log_info(
            logger,
            "Открыт список офферов в админке",
            tg_id=callback.from_user.id,
            offers_count=len(offers),
        )

        if not offers:
            await callback.message.answer(
                "\u041d\u0435\u0442 \u043e\u0444\u0444\u0435\u0440\u043e\u0432.",
                reply_markup=admin_offers_menu_keyboard(),
            )
        else:
            await callback.message.answer(
                "\U0001f4cb",
                reply_markup=admin_offer_list_keyboard(offers),
            )

        await callback.answer()
    except Exception:
        log_exception(
            logger,
            "Ошибка при открытии списка офферов",
            tg_id=callback.from_user.id if callback.from_user else None,
        )
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)


@router.callback_query(F.data.startswith("admin_offer_toggle:"))
async def offer_toggle(callback: CallbackQuery):
    if not callback.from_user:
        return

    ok = await check_admin(callback.from_user.id)
    if not ok:
        await callback.answer("\u26d4", show_alert=True)
        return

    try:
        oid = int(callback.data.split(":")[1])

        async with async_session() as session:
            offer = await toggle_offer_active(session, oid)

        if not offer:
            await callback.answer("\u041d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d", show_alert=True)
            return

        st = "\u0432\u043a\u043b" if offer.is_active else "\u0432\u044b\u043a\u043b"

        log_info(
            logger,
            "Переключено состояние оффера",
            tg_id=callback.from_user.id,
            offer_id=offer.id,
            is_active=offer.is_active,
        )

        await callback.message.answer(
            f"{offer.title} \u2014 {st}",
            reply_markup=admin_offers_menu_keyboard(),
        )

        await send_admin_log(
            callback.bot,
            f"\U0001f4cc <b>OFFER TOGGLE</b>\n"
            f"\u0410\u0434\u043c\u0438\u043d: <code>{callback.from_user.id}</code>\n"
            f"ID: <b>{offer.id}</b>\n"
            f"\u0421\u0442\u0430\u0442\u0443\u0441: <b>{st}</b>"
        )

        await callback.answer()
    except Exception:
        log_exception(
            logger,
            "Ошибка при переключении оффера",
            tg_id=callback.from_user.id if callback.from_user else None,
        )
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)


@router.callback_query(F.data == "admin_manage_admins")
async def cb_manage(callback: CallbackQuery):
    if not callback.from_user or not is_super_admin(callback.from_user.id):
        await callback.answer("\u26d4", show_alert=True)
        return

    log_info(
        logger,
        "Открыто управление администраторами",
        tg_id=callback.from_user.id,
    )

    await callback.message.edit_text(
        "\U0001f451 <b>\u0423\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435 \u0430\u0434\u043c\u0438\u043d\u0430\u043c\u0438</b>",
        parse_mode="HTML",
        reply_markup=admin_manage_keyboard(),
    )


@router.callback_query(F.data == "admm_list")
async def cb_list(callback: CallbackQuery):
    if not callback.from_user or not is_super_admin(callback.from_user.id):
        await callback.answer("\u26d4", show_alert=True)
        return

    try:
        async with async_session() as session:
            db_admins = await get_db_admins(session)

            lines = [
                "\U0001f451 <b>\u0410\u0434\u043c\u0438\u043d\u044b</b>\n",
                "<b>\U0001f534 \u0421\u0443\u043f\u0435\u0440 (env):</b>",
            ]

            for tid in ADMINS:
                u = await get_user(session, tid)
                if u:
                    lines.append(f" \u2022 @{u.username or u.telegram_id} ({u.first_name or ''})")
                else:
                    lines.append(f" \u2022 {tid} (\u043d\u0435 \u0432 \u0411\u0414)")

            lines.append("\n<b>\U0001f7e2 \u041e\u0431\u044b\u0447\u043d\u044b\u0435 (\u0411\u0414):</b>")
            non = [a for a in db_admins if a.telegram_id not in ADMINS]

            if non:
                for a in non:
                    lines.append(f" \u2022 @{a.username or a.telegram_id} ({a.first_name or ''})")
            else:
                lines.append(" (\u043f\u0443\u0441\u0442\u043e)")

            log_info(
                logger,
                "Открыт список администраторов",
                tg_id=callback.from_user.id,
                env_admins=len(ADMINS),
                db_admins=len(db_admins),
            )

            await callback.message.edit_text(
                "\n".join(lines),
                parse_mode="HTML",
                reply_markup=back_to_admin_manage_keyboard(),
            )
    except Exception:
        log_exception(
            logger,
            "Ошибка при открытии списка администраторов",
            tg_id=callback.from_user.id if callback.from_user else None,
        )
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)


@router.callback_query(F.data == "admm_add")
async def cb_add(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user or not is_super_admin(callback.from_user.id):
        await callback.answer("\u26d4", show_alert=True)
        return

    log_info(
        logger,
        "Начато добавление администратора",
        tg_id=callback.from_user.id,
    )

    await state.set_state(AdminManageState.waiting_add_username)
    await callback.message.answer(
        "\u2795 Username \u0434\u043b\u044f \u0434\u043e\u0431\u0430\u0432\u043b\u0435\u043d\u0438\u044f (@user \u0438\u043b\u0438 user).\n/start \u0434\u043b\u044f \u043e\u0442\u043c\u0435\u043d\u044b."
    )
    await callback.answer()


@router.message(AdminManageState.waiting_add_username)
async def add_proc(message: Message, state: FSMContext):
    if not message.from_user or not is_super_admin(message.from_user.id):
        await state.clear()
        return

    inp = (message.text or "").strip()

    try:
        async with async_session() as session:
            user = await get_user_by_username(session, inp)
            if not user:
                await message.answer(f"\u274c {inp} \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d.")
                await state.clear()
                return

            if user.telegram_id in ADMINS:
                await message.answer("\u26a0\ufe0f \u0423\u0436\u0435 \u0441\u0443\u043f\u0435\u0440-\u0430\u0434\u043c\u0438\u043d.")
                await state.clear()
                return

            if user.is_admin:
                await message.answer("\u26a0\ufe0f \u0423\u0436\u0435 \u0430\u0434\u043c\u0438\u043d.")
                await state.clear()
                return

            await set_user_admin(session, user, True)

        log_info(
            logger,
            "Добавлен новый администратор",
            initiator_tg_id=message.from_user.id,
            added_admin_tg_id=user.telegram_id,
            username=user.username,
        )

        await message.answer(f"\u2705 @{user.username} \u0442\u0435\u043f\u0435\u0440\u044c \u0430\u0434\u043c\u0438\u043d!")

        await send_admin_log(
            message.bot,
            f"\U0001f7e2 <b>ADMIN ADDED</b>\n"
            f"\u0418\u043d\u0438\u0446\u0438\u0430\u0442\u043e\u0440: <code>{message.from_user.id}</code>\n"
            f"\u041d\u043e\u0432\u044b\u0439 \u0430\u0434\u043c\u0438\u043d: @{user.username or user.telegram_id}"
        )
    except Exception:
        log_exception(
            logger,
            "Ошибка при добавлении администратора",
            tg_id=message.from_user.id if message.from_user else None,
            input_username=inp,
        )
        await message.answer("\u041e\u0448\u0438\u0431\u043a\u0430.")
    finally:
        await state.clear()


@router.callback_query(F.data == "admm_remove")
async def cb_rem(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user or not is_super_admin(callback.from_user.id):
        await callback.answer("\u26d4", show_alert=True)
        return

    log_info(
        logger,
        "Начато удаление администратора",
        tg_id=callback.from_user.id,
    )

    await state.set_state(AdminManageState.waiting_remove_username)
    await callback.message.answer(
        "\u2796 Username \u0434\u043b\u044f \u0443\u0434\u0430\u043b\u0435\u043d\u0438\u044f.\n/start \u0434\u043b\u044f \u043e\u0442\u043c\u0435\u043d\u044b."
    )
    await callback.answer()


@router.message(AdminManageState.waiting_remove_username)
async def rem_proc(message: Message, state: FSMContext):
    if not message.from_user or not is_super_admin(message.from_user.id):
        await state.clear()
        return

    inp = (message.text or "").strip()

    try:
        async with async_session() as session:
            user = await get_user_by_username(session, inp)
            if not user:
                await message.answer(f"\u274c {inp} \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d.")
                await state.clear()
                return

            if user.telegram_id in ADMINS:
                await message.answer("\u26d4 \u0421\u0443\u043f\u0435\u0440-\u0430\u0434\u043c\u0438\u043d. \u041d\u0435\u043b\u044c\u0437\u044f.")
                await state.clear()
                return

            if not user.is_admin:
                await message.answer("\u26a0\ufe0f \u041d\u0435 \u0430\u0434\u043c\u0438\u043d.")
                await state.clear()
                return

            await set_user_admin(session, user, False)

        log_info(
            logger,
            "Удалён администратор",
            initiator_tg_id=message.from_user.id,
            removed_admin_tg_id=user.telegram_id,
            username=user.username,
        )

        await message.answer(f"\u2705 @{user.username} \u0443\u0434\u0430\u043b\u0451\u043d.")

        await send_admin_log(
            message.bot,
            f"\U0001f534 <b>ADMIN REMOVED</b>\n"
            f"\u0418\u043d\u0438\u0446\u0438\u0430\u0442\u043e\u0440: <code>{message.from_user.id}</code>\n"
            f"\u0423\u0434\u0430\u043b\u0451\u043d\u043d\u044b\u0439 \u0430\u0434\u043c\u0438\u043d: @{user.username or user.telegram_id}"
        )
    except Exception:
        log_exception(
            logger,
            "Ошибка при удалении администратора",
            tg_id=message.from_user.id if message.from_user else None,
            input_username=inp,
        )
        await message.answer("\u041e\u0448\u0438\u0431\u043a\u0430.")
    finally:
        await state.clear()