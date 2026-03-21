import logging
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
    "\u26a0\ufe0f <b>Rules</b>\n\n"
    "1. This bot contains 18+ content. By using it you confirm you are 18+.\n"
    "2. Uploading content with minors is strictly forbidden.\n"
    "3. Violence content is forbidden.\n"
    "4. Administration reserves the right to block users.\n\n"
    "Press the button below to accept the rules."
)


@router.message(CommandStart())
async def cmd_start(message: Message):
    if not message.from_user:
        return

    async with async_session() as session:
        user, created = await get_or_create_user(
            session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )

        if not user.agreed_to_rules:
            await message.answer(RULES_TEXT, parse_mode="HTML", reply_markup=rules_keyboard())
            return

        await message.answer(
            f"Welcome back! Balance: <b>{user.balance}</b> coins \U0001f4b0",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )


@router.callback_query(F.data == "accept_rules")
async def cb_accept_rules(callback: CallbackQuery):
    if not callback.from_user:
        return

    async with async_session() as session:
        user = await agree_to_rules(session, callback.from_user.id)

    await callback.message.edit_text("\u2705 Rules accepted!")
    await callback.message.answer(
        "Welcome! Your starting balance: <b>2</b> coins \U0001f4b0",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )
    await callback.answer()


@router.message(F.text == BTN_PROFILE)
async def show_profile(message: Message):
    if not message.from_user:
        return

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)

    if not user:
        await message.answer("User not found. Press /start")
        return

    text = (
        f"\U0001f464 <b>Profile</b>\n\n"
        f"ID: <code>{user.telegram_id}</code>\n"
        f"\U0001f4b0 Balance: <b>{user.balance}</b> coins\n"
        f"Referral code: <code>{user.referral_code}</code>\n"
        f"Status: {user.status}"
    )
    await message.answer(text, parse_mode="HTML")


@router.message(F.text == BTN_UPLOAD)
async def upload_prompt(message: Message):
    await message.answer("Send a video you want to upload \U0001f3ac")


@router.message(F.video)
async def handle_video_upload(message: Message):
    if not message.from_user or not message.video:
        return

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await message.answer("User not found. Press /start")
            return

        if not user.agreed_to_rules:
            await message.answer("Accept the rules first: /start")
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
        await message.answer("\u26a0\ufe0f This video was already uploaded (duplicate).")
    else:
        await message.answer(
            "\u2705 Video uploaded and sent for moderation!\n"
            "You will receive <b>0.5 coins</b> after approval.",
            parse_mode="HTML",
        )


@router.message(F.text == BTN_WATCH)
async def watch_video(message: Message):
    if not message.from_user:
        return
    await _send_next_video(message, message.from_user.id)


@router.callback_query(F.data == "watch_next")
async def cb_watch_next(callback: CallbackQuery):
    if not callback.from_user:
        return
    await _send_next_video(callback.message, callback.from_user.id)
    await callback.answer()


async def _send_next_video(message: Message, telegram_id: int):
    async with async_session() as session:
        user = await get_user(session, telegram_id)
        if not user:
            await message.answer("User not found. Press /start")
            return

        if user.balance < Decimal(str(WATCH_COST)):
            await message.answer(
                "\u274c Not enough coins.\n"
                "Upload videos or buy coins!",
            )
            return

        video = await get_random_video_for_user(session, user)
        if not video:
            await message.answer("\U0001f4ed No more new videos for you.")
            return

        charged = await record_view_and_charge(session, user, video)
        if not charged:
            await message.answer("\u274c Not enough coins.")
            return

        new_balance = user.balance

    await message.answer_video(
        video=video.telegram_file_id,
        caption=f"\U0001f4b0 1 coin charged. Balance: <b>{new_balance}</b>",
        parse_mode="HTML",
        reply_markup=video_rating_keyboard(video.id),
    )


@router.callback_query(F.data.startswith("rate:"))
async def cb_rate_video(callback: CallbackQuery):
    if not callback.from_user:
        return

    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Error")
        return

    video_id = int(parts[1])
    rating = int(parts[2])

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer("User not found")
            return

        await rate_video(session, user.id, video_id, rating)

    emoji = "\U0001f44d" if rating == 1 else "\U0001f44e"
    await callback.answer(f"You rated: {emoji}")


@router.message(F.text == BTN_BUY)
async def buy_coins_stub(message: Message):
    await message.answer("\U0001f51c Coin purchase coming soon.")


@router.message(F.text == BTN_OFFERS)
async def offers_stub(message: Message):
    await message.answer("\U0001f51c Ad offers coming soon.")


@router.message(F.text == BTN_REFERRALS)
async def referrals_stub(message: Message):
    await message.answer("\U0001f51c Referral system will be expanded in future updates.")
