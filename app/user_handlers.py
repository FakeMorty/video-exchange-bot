import logging
import traceback
from decimal import Decimal

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery

from app.db import async_session
from app.services import (
    get_or_create_user, agree_to_rules, get_user,
    save_video, get_random_video_for_user, record_view_and_charge, rate_video,
)
from app.keyboards import (
    rules_keyboard, main_menu, video_rating_keyboard,
    BTN_WATCH, BTN_UPLOAD, BTN_PROFILE, BTN_BUY, BTN_OFFERS, BTN_REFERRALS,
)
from app.config import WATCH_COST

logger = logging.getLogger(__name__)
router = Router()

RULES_TEXT = (
    "\u26a0\ufe0f <b>\u041f\u0440\u0430\u0432\u0438\u043b\u0430 \u0438\u0441\u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u043d\u0438\u044f</b>\n\n"
    "1. \u0411\u043e\u0442 \u0441\u043e\u0434\u0435\u0440\u0436\u0438\u0442 \u043a\u043e\u043d\u0442\u0435\u043d\u0442 18+. \u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u044f \u0431\u043e\u0442, \u0432\u044b \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0430\u0435\u0442\u0435, \u0447\u0442\u043e \u0432\u0430\u043c \u0435\u0441\u0442\u044c 18 \u043b\u0435\u0442.\n"
    "2. \u0417\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u043e \u0437\u0430\u0433\u0440\u0443\u0436\u0430\u0442\u044c \u043a\u043e\u043d\u0442\u0435\u043d\u0442 \u0441 \u043d\u0435\u0441\u043e\u0432\u0435\u0440\u0448\u0435\u043d\u043d\u043e\u043b\u0435\u0442\u043d\u0438\u043c\u0438.\n"
    "3. \u0417\u0430\u043f\u0440\u0435\u0449\u0451\u043d \u043a\u043e\u043d\u0442\u0435\u043d\u0442 \u0441 \u043d\u0430\u0441\u0438\u043b\u0438\u0435\u043c.\n"
    "4. \u0410\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0446\u0438\u044f \u043e\u0441\u0442\u0430\u0432\u043b\u044f\u0435\u0442 \u0437\u0430 \u0441\u043e\u0431\u043e\u0439 \u043f\u0440\u0430\u0432\u043e \u0437\u0430\u0431\u043b\u043e\u043a\u0438\u0440\u043e\u0432\u0430\u0442\u044c \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044f.\n\n"
    "\u041d\u0430\u0436\u043c\u0438\u0442\u0435 \u043a\u043d\u043e\u043f\u043a\u0443 \u043d\u0438\u0436\u0435, \u0447\u0442\u043e\u0431\u044b \u043f\u0440\u0438\u043d\u044f\u0442\u044c \u043f\u0440\u0430\u0432\u0438\u043b\u0430."
)


@router.message(CommandStart())
async def cmd_start(message: Message):
    logger.info(f"[START] user={message.from_user.id if message.from_user else '?'}")
    if not message.from_user:
        return

    try:
        async with async_session() as session:
            user, created = await get_or_create_user(
                session,
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
            )
            logger.info(f"[START] user={message.from_user.id} created={created} agreed={user.agreed_to_rules}")

            if not user.agreed_to_rules:
                await message.answer(RULES_TEXT, parse_mode="HTML", reply_markup=rules_keyboard())
                logger.info(f"[START] sent rules to user={message.from_user.id}")
                return

            await message.answer(
                f"\u0421 \u0432\u043e\u0437\u0432\u0440\u0430\u0449\u0435\u043d\u0438\u0435\u043c! \u0411\u0430\u043b\u0430\u043d\u0441: <b>{user.balance}</b> \u043c\u043e\u043d\u0435\u0442 \U0001f4b0",
                parse_mode="HTML",
                reply_markup=main_menu(),
            )
            logger.info(f"[START] sent menu to user={message.from_user.id}")
    except Exception as e:
        logger.error(f"[START] ERROR: {e}")
        logger.error(traceback.format_exc())


@router.callback_query(F.data == "accept_rules")
async def cb_accept_rules(callback: CallbackQuery):
    logger.info(f"[ACCEPT_RULES] user={callback.from_user.id if callback.from_user else '?'}")
    if not callback.from_user:
        return

    try:
        async with async_session() as session:
            user = await agree_to_rules(session, callback.from_user.id)

        await callback.message.edit_text("\u2705 \u041f\u0440\u0430\u0432\u0438\u043b\u0430 \u043f\u0440\u0438\u043d\u044f\u0442\u044b!")
        await callback.message.answer(
            "\u0414\u043e\u0431\u0440\u043e \u043f\u043e\u0436\u0430\u043b\u043e\u0432\u0430\u0442\u044c! \u0412\u0430\u0448 \u0441\u0442\u0430\u0440\u0442\u043e\u0432\u044b\u0439 \u0431\u0430\u043b\u0430\u043d\u0441: <b>2</b> \u043c\u043e\u043d\u0435\u0442\u044b \U0001f4b0",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )
        await callback.answer()
        logger.info(f"[ACCEPT_RULES] OK user={callback.from_user.id}")
    except Exception as e:
        logger.error(f"[ACCEPT_RULES] ERROR: {e}")
        logger.error(traceback.format_exc())


@router.message(F.text == BTN_PROFILE)
async def show_profile(message: Message):
    logger.info(f"[PROFILE] user={message.from_user.id if message.from_user else '?'}")
    if not message.from_user:
        return

    try:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)

        if not user:
            await message.answer("\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d. \u041d\u0430\u0436\u043c\u0438\u0442\u0435 /start")
            return

        text = (
            f"\U0001f464 <b>\u041f\u0440\u043e\u0444\u0438\u043b\u044c</b>\n\n"
            f"\U0001f194 Telegram ID: <code>{user.telegram_id}</code>\n"
            f"\U0001f4b0 \u0411\u0430\u043b\u0430\u043d\u0441: <b>{user.balance}</b> \u043c\u043e\u043d\u0435\u0442\n"
            f"\U0001f517 \u0420\u0435\u0444\u0435\u0440\u0430\u043b\u044c\u043d\u044b\u0439 \u043a\u043e\u0434: <code>{user.referral_code}</code>\n"
            f"\U0001f4ca \u0421\u0442\u0430\u0442\u0443\u0441: {user.status}"
        )
        await message.answer(text, parse_mode="HTML")
        logger.info(f"[PROFILE] OK user={message.from_user.id} balance={user.balance}")
    except Exception as e:
        logger.error(f"[PROFILE] ERROR: {e}")
        logger.error(traceback.format_exc())


@router.message(F.text == BTN_UPLOAD)
async def upload_prompt(message: Message):
    logger.info(f"[UPLOAD_PROMPT] user={message.from_user.id if message.from_user else '?'}")
    await message.answer("\u041e\u0442\u043f\u0440\u0430\u0432\u044c\u0442\u0435 \u0432\u0438\u0434\u0435\u043e, \u043a\u043e\u0442\u043e\u0440\u043e\u0435 \u0445\u043e\u0442\u0438\u0442\u0435 \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \U0001f3ac")


@router.message(F.video)
async def handle_video_upload(message: Message):
    logger.info(f"[VIDEO_UPLOAD] user={message.from_user.id if message.from_user else '?'}")
    if not message.from_user or not message.video:
        return

    try:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                await message.answer("\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d. \u041d\u0430\u0436\u043c\u0438\u0442\u0435 /start")
                return

            if not user.agreed_to_rules:
                await message.answer("\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u043f\u0440\u0438\u043c\u0438\u0442\u0435 \u043f\u0440\u0430\u0432\u0438\u043b\u0430: /start")
                return

            video = await save_video(
                session,
                uploader=user,
                file_id=message.video.file_id,
                file_unique_id=message.video.file_unique_id,
                duration=message.video.duration,
                file_size=message.video.file_size,
            )

        if video is None:
            await message.answer("\u26a0\ufe0f \u042d\u0442\u043e \u0432\u0438\u0434\u0435\u043e \u0443\u0436\u0435 \u0431\u044b\u043b\u043e \u0437\u0430\u0433\u0440\u0443\u0436\u0435\u043d\u043e \u0440\u0430\u043d\u0435\u0435 (\u0434\u0443\u0431\u043b\u0438\u043a\u0430\u0442).")
            logger.info(f"[VIDEO_UPLOAD] duplicate user={message.from_user.id}")
        else:
            await message.answer(
                "\u2705 \u0412\u0438\u0434\u0435\u043e \u0437\u0430\u0433\u0440\u0443\u0436\u0435\u043d\u043e \u0438 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u043e \u043d\u0430 \u043c\u043e\u0434\u0435\u0440\u0430\u0446\u0438\u044e!\n"
                "\u0412\u044b \u043f\u043e\u043b\u0443\u0447\u0438\u0442\u0435 <b>0.5 \u043c\u043e\u043d\u0435\u0442\u044b</b> \u043f\u043e\u0441\u043b\u0435 \u043e\u0434\u043e\u0431\u0440\u0435\u043d\u0438\u044f.",
                parse_mode="HTML",
            )
            logger.info(f"[VIDEO_UPLOAD] saved video_id={video.id} user={message.from_user.id}")
    except Exception as e:
        logger.error(f"[VIDEO_UPLOAD] ERROR: {e}")
        logger.error(traceback.format_exc())


@router.message(F.text == BTN_WATCH)
async def watch_video(message: Message):
    logger.info(f"[WATCH] user={message.from_user.id if message.from_user else '?'}")
    if not message.from_user:
        return
    await _send_next_video(message, message.from_user.id)


@router.callback_query(F.data == "watch_next")
async def cb_watch_next(callback: CallbackQuery):
    logger.info(f"[WATCH_NEXT] user={callback.from_user.id if callback.from_user else '?'}")
    if not callback.from_user:
        return
    await _send_next_video(callback.message, callback.from_user.id)
    await callback.answer()


async def _send_next_video(message: Message, telegram_id: int):
    try:
        async with async_session() as session:
            user = await get_user(session, telegram_id)
            if not user:
                await message.answer("\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d. \u041d\u0430\u0436\u043c\u0438\u0442\u0435 /start")
                return

            logger.info(f"[SEND_VIDEO] user={telegram_id} balance={user.balance}")

            if user.balance < Decimal(str(WATCH_COST)):
                await message.answer(
                    "\u274c \u041d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e \u043c\u043e\u043d\u0435\u0442 \u0434\u043b\u044f \u043f\u0440\u043e\u0441\u043c\u043e\u0442\u0440\u0430.\n"
                    "\u0417\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u0435 \u0432\u0438\u0434\u0435\u043e \u0438\u043b\u0438 \u043a\u0443\u043f\u0438\u0442\u0435 \u043c\u043e\u043d\u0435\u0442\u044b!",
                )
                logger.info(f"[SEND_VIDEO] not enough coins user={telegram_id}")
                return

            video = await get_random_video_for_user(session, user)
            if not video:
                await message.answer("\U0001f4ed \u0412 \u0431\u0430\u0437\u0435 \u0431\u043e\u043b\u044c\u0448\u0435 \u043d\u0435\u0442 \u043d\u043e\u0432\u044b\u0445 \u0432\u0438\u0434\u0435\u043e \u0434\u043b\u044f \u0432\u0430\u0441.")
                logger.info(f"[SEND_VIDEO] no videos for user={telegram_id}")
                return

            charged = await record_view_and_charge(session, user, video)
            if not charged:
                await message.answer("\u274c \u041d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e \u043c\u043e\u043d\u0435\u0442.")
                return

            new_balance = user.balance
            logger.info(f"[SEND_VIDEO] sending video_id={video.id} to user={telegram_id} new_balance={new_balance}")

        await message.answer_video(
            video=video.telegram_file_id,
            caption=f"\U0001f4b0 \u0421\u043f\u0438\u0441\u0430\u043d\u0430 1 \u043c\u043e\u043d\u0435\u0442\u0430. \u0411\u0430\u043b\u0430\u043d\u0441: <b>{new_balance}</b>",
            parse_mode="HTML",
            reply_markup=video_rating_keyboard(video.id),
        )
        logger.info(f"[SEND_VIDEO] OK video sent to user={telegram_id}")
    except Exception as e:
        logger.error(f"[SEND_VIDEO] ERROR: {e}")
        logger.error(traceback.format_exc())


@router.callback_query(F.data.startswith("rate:"))
async def cb_rate_video(callback: CallbackQuery):
    logger.info(f"[RATE] user={callback.from_user.id if callback.from_user else '?'} data={callback.data}")
    if not callback.from_user:
        return

    try:
        parts = callback.data.split(":")
        if len(parts) != 3:
            await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430")
            return

        video_id = int(parts[1])
        rating = int(parts[2])

        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not user:
                await callback.answer("\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d")
                return

            await rate_video(session, user.id, video_id, rating)

        emoji = "\U0001f44d" if rating == 1 else "\U0001f44e"
        await callback.answer(f"\u0412\u044b \u043e\u0446\u0435\u043d\u0438\u043b\u0438: {emoji}")
        logger.info(f"[RATE] OK user={callback.from_user.id} video={video_id} rating={rating}")
    except Exception as e:
        logger.error(f"[RATE] ERROR: {e}")
        logger.error(traceback.format_exc())


@router.message(F.text == BTN_BUY)
async def buy_coins_stub(message: Message):
    logger.info(f"[BUY] user={message.from_user.id if message.from_user else '?'}")
    await message.answer("\U0001f51c \u041f\u043e\u043a\u0443\u043f\u043a\u0430 \u043c\u043e\u043d\u0435\u0442 \u0441\u043a\u043e\u0440\u043e \u0431\u0443\u0434\u0435\u0442 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430.")


@router.message(F.text == BTN_OFFERS)
async def offers_stub(message: Message):
    logger.info(f"[OFFERS] user={message.from_user.id if message.from_user else '?'}")
    await message.answer("\U0001f51c \u0420\u0435\u043a\u043b\u0430\u043c\u043d\u044b\u0435 \u043e\u0444\u0444\u0435\u0440\u044b \u0441\u043a\u043e\u0440\u043e \u043f\u043e\u044f\u0432\u044f\u0442\u0441\u044f.")


@router.message(F.text == BTN_REFERRALS)
async def referrals_stub(message: Message):
    logger.info(f"[REFERRALS] user={message.from_user.id if message.from_user else '?'}")
    await message.answer("\U0001f51c \u0420\u0435\u0444\u0435\u0440\u0430\u043b\u044c\u043d\u0430\u044f \u0441\u0438\u0441\u0442\u0435\u043c\u0430 \u0431\u0443\u0434\u0435\u0442 \u0440\u0430\u0441\u0448\u0438\u0440\u0435\u043d\u0430 \u0432 \u0441\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0445 \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u044f\u0445.")
