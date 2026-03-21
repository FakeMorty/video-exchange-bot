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
    get_user, get_next_pending_video, approve_video, reject_video,
    approve_all_pending,
    count_pending_videos, count_approved_videos, count_rejected_videos,
    format_duration, format_file_size, get_user_by_id,
    create_offer, get_all_offers, toggle_offer_active,
    get_user_by_username, set_user_admin, get_db_admins,
)
from app.keyboards import (
    moderation_keyboard, rejection_reason_keyboard,
    admin_center_keyboard, admin_after_action_keyboard,
    admin_offers_menu_keyboard, admin_offer_list_keyboard,
    admin_manage_keyboard, back_to_admin_manage_keyboard,
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


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not message.from_user:
        return
    ok = await check_admin(message.from_user.id)
    if not ok:
        await message.answer("\u26d4")
        return
    sa = is_super_admin(message.from_user.id)
    await message.answer("\U0001f6e0 <b>\u0410\u0434\u043c\u0438\u043d</b>", parse_mode="HTML", reply_markup=admin_center_keyboard(is_super_admin=sa))


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
        await callback.message.answer(
            f"\U0001f4ca <b>\u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430</b>\n\n"
            f"\u23f3 \u041d\u0430 \u043c\u043e\u0434\u0435\u0440\u0430\u0446\u0438\u0438: <b>{p}</b>\n"
            f"\u2705 \u041e\u0434\u043e\u0431\u0440\u0435\u043d\u043e: <b>{a}</b>\n"
            f"\u274c \u041e\u0442\u043a\u043b\u043e\u043d\u0435\u043d\u043e: <b>{r}</b>",
            parse_mode="HTML", reply_markup=admin_center_keyboard(is_super_admin=sa),
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"[QUEUE] {e}")
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)


# ===== APPROVE ALL =====

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
        await callback.message.answer(
            f"\u2705 \u041e\u0434\u043e\u0431\u0440\u0435\u043d\u043e \u0432\u0441\u0451: <b>{count}</b> \u0435\u0434.",
            parse_mode="HTML", reply_markup=admin_center_keyboard(is_super_admin=sa),
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"[APPROVE_ALL] {e}")
        logger.error(traceback.format_exc())
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)


# ===== MODERATION =====

@router.callback_query(F.data == "admin_get_pending")
async def cb_pending(callback: CallbackQuery):
    if not callback.from_user:
        return
    ok = await check_admin(callback.from_user.id)
    if not ok:
        await callback.answer("\u26d4", show_alert=True)
        return
    await callback.answer()
    await _send_pending(callback.message)


async def _send_pending(message):
    try:
        async with async_session() as session:
            pc = await count_pending_videos(session)
            video = await get_next_pending_video(session)
            if not video:
                await message.answer("\u2705 \u041f\u0443\u0441\u0442\u043e.", reply_markup=admin_center_keyboard())
                return
            fid = video.telegram_file_id
            vid = video.id
            uid = video.uploader_user_id
            ct = video.content_type
            dur = format_duration(video.duration_seconds) if ct == "video" else "\u2014"
            sz = format_file_size(video.file_size)
        label = "\U0001f5bc \u0424\u043e\u0442\u043e" if ct == "photo" else "\U0001f3ac \u0412\u0438\u0434\u0435\u043e"
        cap = f"\U0001f4cb <b>\u041c\u043e\u0434\u0435\u0440\u0430\u0446\u0438\u044f</b>\n\n{label} #{vid}\n\u0410\u0432\u0442\u043e\u0440: {uid}\n\u0414\u043b\u0438\u0442.: {dur}\n\u0420\u0430\u0437\u043c.: {sz}\n\u041e\u0447\u0435\u0440\u0435\u0434\u044c: {pc}"
        if ct == "photo":
            await message.answer_photo(photo=fid, caption=cap, parse_mode="HTML", reply_markup=moderation_keyboard(vid))
        else:
            await message.answer_video(video=fid, caption=cap, parse_mode="HTML", reply_markup=moderation_keyboard(vid))
    except Exception as e:
        logger.error(f"[PENDING] {e}")
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
            await callback.message.edit_caption(caption=f"#{vid} \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d.", reply_markup=admin_after_action_keyboard())
            await callback.answer()
            return
        rw = "0.1" if video.content_type == "photo" else "0.5"
        await callback.message.edit_caption(caption=f"\u2705 #{vid} +{rw}", reply_markup=admin_after_action_keyboard())
        if uploader:
            try:
                await callback.bot.send_message(uploader.telegram_id, f"\u2705 #{vid} \u043e\u0434\u043e\u0431\u0440\u0435\u043d. +<b>{rw}</b>", parse_mode="HTML")
            except Exception:
                pass
        await callback.answer("\u041e\u0434\u043e\u0431\u0440\u0435\u043d\u043e")
    except Exception as e:
        logger.error(f"[APPROVE] {e}")
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
            await callback.message.edit_caption(caption=f"#{vid} \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d.", reply_markup=admin_after_action_keyboard())
            await callback.answer()
            return
        await callback.message.edit_caption(caption=f"\u274c #{vid}: {rt}", reply_markup=admin_after_action_keyboard())
        if uploader:
            try:
                await callback.bot.send_message(uploader.telegram_id, f"\u274c #{vid}: <b>{rt}</b>", parse_mode="HTML")
            except Exception:
                pass
        await callback.answer("\u041e\u0442\u043a\u043b\u043e\u043d\u0435\u043d\u043e")
    except Exception as e:
        logger.error(f"[REJECT] {e}")
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)


# ===== OFFERS ADMIN =====

@router.callback_query(F.data == "admin_offers_menu")
async def offers_menu(callback: CallbackQuery):
    if not callback.from_user:
        return
    ok = await check_admin(callback.from_user.id)
    if not ok:
        await callback.answer("\u26d4", show_alert=True)
        return
    await callback.message.answer("\U0001f381 <b>\u041e\u0444\u0444\u0435\u0440\u044b</b>", parse_mode="HTML", reply_markup=admin_offers_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin_offer_create")
async def offer_create(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    ok = await check_admin(callback.from_user.id)
    if not ok:
        await callback.answer("\u26d4", show_alert=True)
        return
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
            offer = await create_offer(session, data["title"], data["description"], message.text or "")
        await message.answer(f"\u2705 \u041e\u0444\u0444\u0435\u0440 #{offer.id} \u0441\u043e\u0437\u0434\u0430\u043d.", reply_markup=admin_offers_menu_keyboard())
    except Exception as e:
        logger.error(f"[OC] {e}")
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
        if not offers:
            await callback.message.answer("\u041d\u0435\u0442 \u043e\u0444\u0444\u0435\u0440\u043e\u0432.", reply_markup=admin_offers_menu_keyboard())
        else:
            await callback.message.answer("\U0001f4cb", reply_markup=admin_offer_list_keyboard(offers))
        await callback.answer()
    except Exception as e:
        logger.error(f"[OL] {e}")
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
        await callback.message.answer(f"{offer.title} \u2014 {st}", reply_markup=admin_offers_menu_keyboard())
        await callback.answer()
    except Exception as e:
        logger.error(f"[OT] {e}")
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)


# ===== ADMIN MANAGE =====

@router.callback_query(F.data == "admin_manage_admins")
async def cb_manage(callback: CallbackQuery):
    if not callback.from_user or not is_super_admin(callback.from_user.id):
        await callback.answer("\u26d4", show_alert=True)
        return
    await callback.message.edit_text(
        "\U0001f451 <b>\u0423\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435 \u0430\u0434\u043c\u0438\u043d\u0430\u043c\u0438</b>",
        parse_mode="HTML", reply_markup=admin_manage_keyboard(),
    )


@router.callback_query(F.data == "admm_list")
async def cb_list(callback: CallbackQuery):
    if not callback.from_user or not is_super_admin(callback.from_user.id):
        await callback.answer("\u26d4", show_alert=True)
        return
    try:
        async with async_session() as session:
            db_admins = await get_db_admins(session)
            lines = ["\U0001f451 <b>\u0410\u0434\u043c\u0438\u043d\u044b</b>\n", "<b>\U0001f534 \u0421\u0443\u043f\u0435\u0440 (env):</b>"]
            for tid in ADMINS:
                u = await get_user(session, tid)
                if u:
                    lines.append(f"  \u2022 @{u.username or u.telegram_id} ({u.first_name or ''})")
                else:
                    lines.append(f"  \u2022 {tid} (\u043d\u0435 \u0432 \u0411\u0414)")
            lines.append("\n<b>\U0001f7e2 \u041e\u0431\u044b\u0447\u043d\u044b\u0435 (\u0411\u0414):</b>")
            non = [a for a in db_admins if a.telegram_id not in ADMINS]
            if non:
                for a in non:
                    lines.append(f"  \u2022 @{a.username or a.telegram_id} ({a.first_name or ''})")
            else:
                lines.append("  (\u043f\u0443\u0441\u0442\u043e)")
        await callback.message.edit_text("\n".join(lines), parse_mode="HTML", reply_markup=back_to_admin_manage_keyboard())
    except Exception as e:
        logger.error(f"[AL] {e}")
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)


@router.callback_query(F.data == "admm_add")
async def cb_add(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user or not is_super_admin(callback.from_user.id):
        await callback.answer("\u26d4", show_alert=True)
        return
    await state.set_state(AdminManageState.waiting_add_username)
    await callback.message.answer("\u2795 Username \u0434\u043b\u044f \u0434\u043e\u0431\u0430\u0432\u043b\u0435\u043d\u0438\u044f (@user \u0438\u043b\u0438 user).\n/start \u0434\u043b\u044f \u043e\u0442\u043c\u0435\u043d\u044b.")
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
                await message.answer(f"\u26a0\ufe0f \u0423\u0436\u0435 \u0441\u0443\u043f\u0435\u0440-\u0430\u0434\u043c\u0438\u043d.")
                await state.clear()
                return
            if user.is_admin:
                await message.answer(f"\u26a0\ufe0f \u0423\u0436\u0435 \u0430\u0434\u043c\u0438\u043d.")
                await state.clear()
                return
            await set_user_admin(session, user, True)
            await message.answer(f"\u2705 @{user.username} \u0442\u0435\u043f\u0435\u0440\u044c \u0430\u0434\u043c\u0438\u043d!")
    except Exception as e:
        logger.error(f"[AA] {e}")
        await message.answer("\u041e\u0448\u0438\u0431\u043a\u0430.")
    finally:
        await state.clear()


@router.callback_query(F.data == "admm_remove")
async def cb_rem(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user or not is_super_admin(callback.from_user.id):
        await callback.answer("\u26d4", show_alert=True)
        return
    await state.set_state(AdminManageState.waiting_remove_username)
    await callback.message.answer("\u2796 Username \u0434\u043b\u044f \u0443\u0434\u0430\u043b\u0435\u043d\u0438\u044f.\n/start \u0434\u043b\u044f \u043e\u0442\u043c\u0435\u043d\u044b.")
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
                await message.answer(f"\u26d4 \u0421\u0443\u043f\u0435\u0440-\u0430\u0434\u043c\u0438\u043d. \u041d\u0435\u043b\u044c\u0437\u044f.")
                await state.clear()
                return
            if not user.is_admin:
                await message.answer(f"\u26a0\ufe0f \u041d\u0435 \u0430\u0434\u043c\u0438\u043d.")
                await state.clear()
                return
            await set_user_admin(session, user, False)
            await message.answer(f"\u2705 @{user.username} \u0443\u0434\u0430\u043b\u0451\u043d.")
    except Exception as e:
        logger.error(f"[AR] {e}")
        await message.answer("\u041e\u0448\u0438\u0431\u043a\u0430.")
    finally:
        await state.clear()
