import logging
import traceback
from decimal import Decimal

from aiogram import Router, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.config import ADMINS, WATCH_COST, STARS_PACKAGES, STARS_TO_COINS_RATE
from app.db import async_session
from app.services import (
    get_or_create_user, agree_to_rules, get_user,
    save_video, save_photo,
    get_random_video_for_user, get_random_photo_for_user,
    record_view_and_charge, record_photo_view,
    count_photo_views_last_4h, rate_video,
    claim_daily_bonus, get_video_stats_for_user, count_referrals,
    create_payment, create_custom_payment, apply_successful_payment,
    get_active_offers, get_offer_by_id,
    start_offer_participation, verify_offer_subscription,
    FREE_PHOTO_LIMIT_PER_4H,
)
from app.keyboards import (
    rules_keyboard, main_menu, video_rating_keyboard,
    photo_actions_keyboard, watch_choice_keyboard,
    admin_center_keyboard, buy_coins_keyboard,
    offers_list_keyboard, offer_view_keyboard,
    BTN_WATCH, BTN_UPLOAD, BTN_PROFILE, BTN_BUY,
    BTN_OFFERS, BTN_REFERRALS, BTN_BONUS, BTN_ADMIN,
)

logger = logging.getLogger(__name__)
router = Router()

RULES_TEXT = (
    "\u26a0\ufe0f <b>\u041f\u0440\u0430\u0432\u0438\u043b\u0430</b>\n\n"
    "1. \u0411\u043e\u0442 \u0441\u043e\u0434\u0435\u0440\u0436\u0438\u0442 \u043a\u043e\u043d\u0442\u0435\u043d\u0442 18+.\n"
    "2. \u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u044f \u0431\u043e\u0442, \u0432\u044b \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0430\u0435\u0442\u0435 18+.\n"
    "3. \u0417\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u043e CP.\n"
    "4. \u0417\u0430\u043f\u0440\u0435\u0449\u0451\u043d \u043a\u043e\u043d\u0442\u0435\u043d\u0442 \u0441 \u043d\u0430\u0441\u0438\u043b\u0438\u0435\u043c.\n"
    "5. \u0410\u0434\u043c\u0438\u043d\u0438\u0441\u0442\u0440\u0430\u0446\u0438\u044f \u043c\u043e\u0436\u0435\u0442 \u043e\u0433\u0440\u0430\u043d\u0438\u0447\u0438\u0442\u044c \u0434\u043e\u0441\u0442\u0443\u043f.\n\n"
    "\u041d\u0430\u0436\u043c\u0438\u0442\u0435 \u043a\u043d\u043e\u043f\u043a\u0443 \u043d\u0438\u0436\u0435."
)


class CustomPayState(StatesGroup):
    waiting_amount = State()


def is_any_admin(telegram_id: int, user_obj=None) -> bool:
    if telegram_id in ADMINS:
        return True
    if user_obj and user_obj.is_admin:
        return True
    return False


def is_super_admin(telegram_id: int) -> bool:
    return telegram_id in ADMINS


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext):
    if not message.from_user:
        return
    await state.clear()

    referral_code = None
    if command and command.args:
        arg = command.args.strip()
        referral_code = arg

    try:
        async with async_session() as session:
            user, created = await get_or_create_user(
                session, message.from_user.id, message.from_user.username,
                message.from_user.first_name, message.from_user.last_name,
                referral_code,
            )
            if not user.agreed_to_rules:
                await message.answer(RULES_TEXT, parse_mode="HTML", reply_markup=rules_keyboard())
                return
            admin_flag = is_any_admin(message.from_user.id, user)
            await message.answer(
                f"\u0421 \u0432\u043e\u0437\u0432\u0440\u0430\u0449\u0435\u043d\u0438\u0435\u043c!\n\U0001f4b0 \u0411\u0430\u043b\u0430\u043d\u0441: <b>{user.balance}</b>",
                parse_mode="HTML", reply_markup=main_menu(is_admin=admin_flag),
            )
    except Exception as e:
        logger.error(f"[START] {e}")
        logger.error(traceback.format_exc())
        await message.answer("\u041e\u0448\u0438\u0431\u043a\u0430.")


@router.callback_query(F.data == "accept_rules")
async def cb_accept_rules(callback: CallbackQuery):
    if not callback.from_user:
        return
    try:
        async with async_session() as session:
            await agree_to_rules(session, callback.from_user.id)
            user = await get_user(session, callback.from_user.id)
            admin_flag = is_any_admin(callback.from_user.id, user)
        await callback.message.edit_text("\u2705 \u041f\u0440\u0430\u0432\u0438\u043b\u0430 \u043f\u0440\u0438\u043d\u044f\u0442\u044b.")
        await callback.message.answer("\u0414\u043e\u0431\u0440\u043e \u043f\u043e\u0436\u0430\u043b\u043e\u0432\u0430\u0442\u044c! \u0421\u0442\u0430\u0440\u0442\u043e\u0432\u044b\u0439 \u0431\u0430\u043b\u0430\u043d\u0441: <b>2</b>", parse_mode="HTML", reply_markup=main_menu(is_admin=admin_flag))
        await callback.answer()
    except Exception as e:
        logger.error(f"[ACCEPT] {e}")
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)


@router.message(F.text == BTN_BONUS)
async def daily_bonus(message: Message):
    if not message.from_user:
        return
    try:
        async with async_session() as session:
            success, msg = await claim_daily_bonus(session, message.from_user.id)
        await message.answer(f"\U0001f3c6 {msg}" if success else f"\u23f3 {msg}")
    except Exception as e:
        logger.error(f"[BONUS] {e}")
        await message.answer("\u041e\u0448\u0438\u0431\u043a\u0430.")


@router.message(F.text == BTN_PROFILE)
async def show_profile(message: Message):
    if not message.from_user:
        return
    try:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
        if not user:
            await message.answer("/start")
            return
        admin_flag = is_any_admin(message.from_user.id, user)
        role = "\u0410\u0434\u043c\u0438\u043d" if admin_flag else "\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c"
        text = (
            f"\U0001f464 <b>\u041f\u0440\u043e\u0444\u0438\u043b\u044c</b>\n\n"
            f"ID: <code>{user.telegram_id}</code>\n"
            f"\U0001f4b0 \u0411\u0430\u043b\u0430\u043d\u0441: <b>{user.balance}</b>\n"
            f"\u0420\u043e\u043b\u044c: {role}"
        )
        await message.answer(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"[PROFILE] {e}")
        await message.answer("\u041e\u0448\u0438\u0431\u043a\u0430.")


@router.message(F.text == BTN_REFERRALS)
async def referrals_info(message: Message):
    if not message.from_user:
        return
    try:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                await message.answer("/start")
                return
            referrals_count = await count_referrals(session, user.id)
        bot_username = (await message.bot.get_me()).username
        referral_link = f"https://t.me/{bot_username}?start={user.referral_code}"
        text = (
            f"\U0001f465 <b>\u041f\u0440\u0438\u0433\u043b\u0430\u0441\u0438 \u0434\u0440\u0443\u0433\u0430!</b>\n\n"
            f"\U0001f517 \u0422\u0432\u043e\u044f \u0441\u0441\u044b\u043b\u043a\u0430:\n<code>{referral_link}</code>\n\n"
            f"\u041e\u0442\u043f\u0440\u0430\u0432\u044c \u0435\u0451 \u0434\u0440\u0443\u0433\u0443 \u0438 \u043f\u043e\u043b\u0443\u0447\u0438\u0442\u0435 \u0431\u043e\u043d\u0443\u0441\u044b!\n\n"
            f"\U0001f464 \u041f\u0440\u0438\u0441\u043e\u0435\u0434\u0438\u043d\u0438\u043b\u043e\u0441\u044c: <b>{referrals_count}</b>\n"
            f"\U0001f4b0 \u0417\u0430\u0440\u0430\u0431\u043e\u0442\u0430\u043d\u043e: <b>{user.referral_earnings}</b>\n\n"
            f"\u2022 \u0442\u0435\u0431\u0435: <b>+2</b>\n\u2022 \u0434\u0440\u0443\u0433\u0443: <b>+1</b>"
        )
        await message.answer(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"[REFERRALS] {e}")
        await message.answer("\u041e\u0448\u0438\u0431\u043a\u0430.")


# ===== PAYMENTS =====

@router.message(F.text == BTN_BUY)
async def buy_coins(message: Message):
    await message.answer(
        "\U0001f48e <b>\u041f\u043e\u043a\u0443\u043f\u043a\u0430 \u043c\u043e\u043d\u0435\u0442</b>\n\n"
        f"\u041a\u0443\u0440\u0441: 1 Star = {STARS_TO_COINS_RATE} \u043c\u043e\u043d\u0435\u0442\n\n"
        "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043f\u0430\u043a\u0435\u0442 \u0438\u043b\u0438 \u0432\u0432\u0435\u0434\u0438\u0442\u0435 \u0441\u0432\u043e\u044e \u0441\u0443\u043c\u043c\u0443:",
        parse_mode="HTML",
        reply_markup=buy_coins_keyboard(),
    )


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy_package(callback: CallbackQuery):
    if not callback.from_user:
        return
    package_key = callback.data.split(":", 1)[1]
    package = STARS_PACKAGES.get(package_key)
    if not package:
        await callback.answer("\u041d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d", show_alert=True)
        return
    try:
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not user:
                await callback.answer("/start", show_alert=True)
                return
            payment = await create_payment(session, user, package_key)
            if not payment:
                await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)
                return
        await callback.message.answer_invoice(
            title=f"{package['coins']} \u043c\u043e\u043d\u0435\u0442",
            description=f"\u041f\u043e\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u0435 \u043d\u0430 {package['coins']} \u043c\u043e\u043d\u0435\u0442",
            payload=payment.payload,
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=f"{package['coins']} \u043c\u043e\u043d\u0435\u0442", amount=package["stars"])],
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"[BUY] {e}")
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)


@router.callback_query(F.data == "buy_custom")
async def cb_buy_custom(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    await state.set_state(CustomPayState.waiting_amount)
    await callback.message.answer(
        f"\U0001f4dd \u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043a\u043e\u043b\u0438\u0447\u0435\u0441\u0442\u0432\u043e \u0437\u0432\u0451\u0437\u0434 (Stars).\n"
        f"\u041a\u0443\u0440\u0441: 1 Star = {STARS_TO_COINS_RATE} \u043c\u043e\u043d\u0435\u0442\n\n"
        f"\u041c\u0438\u043d\u0438\u043c\u0443\u043c: 1 Star\n"
        f"\u0414\u043b\u044f \u043e\u0442\u043c\u0435\u043d\u044b: /start",
    )
    await callback.answer()


@router.message(CustomPayState.waiting_amount)
async def custom_pay_amount(message: Message, state: FSMContext):
    if not message.from_user:
        return
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) < 1:
        await message.answer("\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0447\u0438\u0441\u043b\u043e \u043e\u0442 1.")
        return
    stars = int(text)
    coins = Decimal(str(stars)) * Decimal(str(STARS_TO_COINS_RATE))
    try:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                await message.answer("/start")
                await state.clear()
                return
            payment = await create_custom_payment(session, user, stars)
        await message.answer_invoice(
            title=f"{coins} \u043c\u043e\u043d\u0435\u0442",
            description=f"{stars} Stars \u2192 {coins} \u043c\u043e\u043d\u0435\u0442",
            payload=payment.payload,
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=f"{coins} \u043c\u043e\u043d\u0435\u0442", amount=stars)],
        )
    except Exception as e:
        logger.error(f"[CUSTOM_PAY] {e}")
        logger.error(traceback.format_exc())
        await message.answer("\u041e\u0448\u0438\u0431\u043a\u0430.")
    finally:
        await state.clear()


@router.pre_checkout_query()
async def pre_checkout(pq: PreCheckoutQuery):
    await pq.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message):
    if not message.from_user or not message.successful_payment:
        return
    try:
        payload = message.successful_payment.invoice_payload
        async with async_session() as session:
            success, msg = await apply_successful_payment(session, payload)
        await message.answer(f"\u2705 {msg}" if success else f"\u26a0\ufe0f {msg}")
    except Exception as e:
        logger.error(f"[PAYMENT] {e}")
        await message.answer("\u041e\u0448\u0438\u0431\u043a\u0430 \u043d\u0430\u0447\u0438\u0441\u043b\u0435\u043d\u0438\u044f.")


# ===== OFFERS =====

@router.message(F.text == BTN_OFFERS)
async def show_offers(message: Message):
    if not message.from_user:
        return
    try:
        async with async_session() as session:
            offers = await get_active_offers(session)
        if not offers:
            await message.answer("\u041e\u0444\u0444\u0435\u0440\u043e\u0432 \u043d\u0435\u0442.")
            return
        await message.answer("\U0001f381 <b>\u041e\u0444\u0444\u0435\u0440\u044b</b>", parse_mode="HTML", reply_markup=offers_list_keyboard(offers))
    except Exception as e:
        logger.error(f"[OFFERS] {e}")
        await message.answer("\u041e\u0448\u0438\u0431\u043a\u0430.")


@router.callback_query(F.data.startswith("offer_open:"))
async def offer_open(callback: CallbackQuery):
    if not callback.from_user:
        return
    try:
        offer_id = int(callback.data.split(":")[1])
        async with async_session() as session:
            offer = await get_offer_by_id(session, offer_id)
        if not offer or not offer.is_active:
            await callback.answer("\u041d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d", show_alert=True)
            return
        text = (
            f"\U0001f381 <b>{offer.title}</b>\n\n{offer.description}\n\n"
            f"\U0001f517 {offer.channel_url}\n"
            f"\U0001f4b0 \u0412\u0441\u0435\u0433\u043e: <b>40</b>\n\u26a0\ufe0f \u0428\u0442\u0440\u0430\u0444: <b>40</b>"
        )
        await callback.message.answer(text, parse_mode="HTML", reply_markup=offer_view_keyboard(offer.id, offer.channel_url))
        await callback.answer()
    except Exception as e:
        logger.error(f"[OFFER_OPEN] {e}")
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)


@router.callback_query(F.data.startswith("offer_start:"))
async def offer_start(callback: CallbackQuery):
    if not callback.from_user:
        return
    try:
        offer_id = int(callback.data.split(":")[1])
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            offer = await get_offer_by_id(session, offer_id)
            if not user or not offer:
                await callback.answer("\u041d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e", show_alert=True)
                return
            success, msg = await start_offer_participation(session, user, offer)
        await callback.message.answer(f"\u2705 {msg}" if success else f"\u2139\ufe0f {msg}")
        await callback.answer()
    except Exception as e:
        logger.error(f"[OFFER_START] {e}")
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)


@router.callback_query(F.data.startswith("offer_check:"))
async def offer_check(callback: CallbackQuery):
    if not callback.from_user:
        return
    try:
        offer_id = int(callback.data.split(":")[1])
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            offer = await get_offer_by_id(session, offer_id)
            if not user or not offer:
                await callback.answer("\u041d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e", show_alert=True)
                return
        subscribed = False
        try:
            cm = await callback.bot.get_chat_member(chat_id=offer.channel_url, user_id=callback.from_user.id)
            subscribed = cm.status in ("member", "administrator", "creator")
        except Exception:
            pass
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            offer = await get_offer_by_id(session, offer_id)
            if not user or not offer:
                await callback.answer("\u041d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e", show_alert=True)
                return
            success, msg = await verify_offer_subscription(session, user, offer, subscribed)
        await callback.message.answer(f"\u2705 {msg}" if success else f"\u2139\ufe0f {msg}")
        await callback.answer()
    except Exception as e:
        logger.error(f"[OFFER_CHECK] {e}")
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)


# ===== UPLOAD =====

@router.message(F.text == BTN_UPLOAD)
async def upload_prompt(message: Message):
    await message.answer(
        "\u041e\u0442\u043f\u0440\u0430\u0432\u044c\u0442\u0435 \u0432\u0438\u0434\u0435\u043e, \u043a\u0440\u0443\u0436\u043e\u043a \u0438\u043b\u0438 \u0444\u043e\u0442\u043e.\n\n"
        "\u041d\u0430\u0433\u0440\u0430\u0434\u0430: \u0432\u0438\u0434\u0435\u043e/\u043a\u0440\u0443\u0436\u043e\u043a <b>0.5</b>, \u0444\u043e\u0442\u043e <b>0.1</b>",
        parse_mode="HTML",
    )


@router.message(F.video)
async def handle_video(message: Message):
    if not message.from_user or not message.video:
        return
    await _upload_video(message, message.video.file_id, message.video.file_unique_id, message.video.duration, message.video.file_size)


@router.message(F.video_note)
async def handle_vnote(message: Message):
    if not message.from_user or not message.video_note:
        return
    await _upload_video(message, message.video_note.file_id, message.video_note.file_unique_id, message.video_note.duration, message.video_note.file_size)


async def _upload_video(message, file_id, file_unique_id, duration, file_size):
    try:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user or not user.agreed_to_rules:
                await message.answer("/start")
                return
            video = await save_video(session, user, file_id, file_unique_id, duration, file_size)
        if video is None:
            await message.answer("\u26a0\ufe0f \u0414\u0443\u0431\u043b\u0438\u043a\u0430\u0442.")
        else:
            await message.answer("\u2705 \u041d\u0430 \u043c\u043e\u0434\u0435\u0440\u0430\u0446\u0438\u0438. \u041d\u0430\u0433\u0440\u0430\u0434\u0430: <b>0.5</b>", parse_mode="HTML")
    except Exception as e:
        logger.error(f"[UPLOAD_V] {e}")
        await message.answer("\u041e\u0448\u0438\u0431\u043a\u0430.")


@router.message(F.photo)
async def handle_photo(message: Message):
    if not message.from_user or not message.photo:
        return
    try:
        largest = message.photo[-1]
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user or not user.agreed_to_rules:
                await message.answer("/start")
                return
            photo = await save_photo(session, user, largest.file_id, largest.file_unique_id, largest.file_size)
        if photo is None:
            await message.answer("\u26a0\ufe0f \u0414\u0443\u0431\u043b\u0438\u043a\u0430\u0442.")
        else:
            await message.answer("\u2705 \u041d\u0430 \u043c\u043e\u0434\u0435\u0440\u0430\u0446\u0438\u0438. \u041d\u0430\u0433\u0440\u0430\u0434\u0430: <b>0.1</b>", parse_mode="HTML")
    except Exception as e:
        logger.error(f"[UPLOAD_P] {e}")
        await message.answer("\u041e\u0448\u0438\u0431\u043a\u0430.")


# ===== WATCH =====

@router.message(F.text == BTN_WATCH)
async def watch_menu(message: Message):
    await message.answer("\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435:", reply_markup=watch_choice_keyboard())


@router.callback_query(F.data == "watch_video_content")
async def cb_wv(callback: CallbackQuery):
    if callback.from_user:
        await _send_video(callback.message, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "watch_next")
async def cb_wn(callback: CallbackQuery):
    if callback.from_user:
        await _send_video(callback.message, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "watch_photo_content")
async def cb_wp(callback: CallbackQuery):
    if callback.from_user:
        await _send_photo(callback.message, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "watch_next_photo")
async def cb_wnp(callback: CallbackQuery):
    if callback.from_user:
        await _send_photo(callback.message, callback.from_user.id)
    await callback.answer()


async def _send_video(message, telegram_id):
    try:
        async with async_session() as session:
            user = await get_user(session, telegram_id)
            if not user:
                await message.answer("/start")
                return
            if user.balance < Decimal(str(WATCH_COST)):
                await message.answer("\u274c \u041d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e \u043c\u043e\u043d\u0435\u0442.")
                return
            video = await get_random_video_for_user(session, user)
            if not video:
                await message.answer("\U0001f4ed \u041d\u0435\u0442 \u0432\u0438\u0434\u0435\u043e.")
                return
            charged = await record_view_and_charge(session, user, video)
            if not charged:
                await message.answer("\u274c \u041e\u0448\u0438\u0431\u043a\u0430.")
                return
            bal = user.balance
            fid = video.telegram_file_id
            vid = video.id
        await message.answer_video(video=fid, caption=f"\U0001f4b0 -1. \u0411\u0430\u043b\u0430\u043d\u0441: <b>{bal}</b>", parse_mode="HTML", reply_markup=video_rating_keyboard(vid))
    except Exception as e:
        logger.error(f"[SEND_V] {e}")
        await message.answer("\u041e\u0448\u0438\u0431\u043a\u0430.")


async def _send_photo(message, telegram_id):
    try:
        async with async_session() as session:
            user = await get_user(session, telegram_id)
            if not user:
                await message.answer("/start")
                return
            vc = await count_photo_views_last_4h(session, user.id)
            if vc >= FREE_PHOTO_LIMIT_PER_4H:
                await message.answer(f"\u26d4 \u041b\u0438\u043c\u0438\u0442 {FREE_PHOTO_LIMIT_PER_4H} \u0444\u043e\u0442\u043e/4\u0447.")
                return
            photo = await get_random_photo_for_user(session, user)
            if not photo:
                await message.answer("\U0001f4ed \u041d\u0435\u0442 \u0444\u043e\u0442\u043e.")
                return
            await record_photo_view(session, user, photo)
            rem = FREE_PHOTO_LIMIT_PER_4H - (vc + 1)
            fid = photo.telegram_file_id
        await message.answer_photo(photo=fid, caption=f"\U0001f5bc \u041e\u0441\u0442\u0430\u043b\u043e\u0441\u044c: <b>{rem}</b>", parse_mode="HTML", reply_markup=photo_actions_keyboard())
    except Exception as e:
        logger.error(f"[SEND_P] {e}")
        await message.answer("\u041e\u0448\u0438\u0431\u043a\u0430.")


@router.callback_query(F.data.startswith("rate:"))
async def cb_rate(callback: CallbackQuery):
    if not callback.from_user:
        return
    try:
        parts = callback.data.split(":")
        vid = int(parts[1])
        r = int(parts[2])
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if user:
                await rate_video(session, user.id, vid, r)
        await callback.answer("\u041e\u0446\u0435\u043d\u043a\u0430 \u0441\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u0430")
    except Exception as e:
        logger.error(f"[RATE] {e}")
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)


# ===== ADMIN BTN =====

@router.message(F.text == BTN_ADMIN)
async def open_admin(message: Message):
    if not message.from_user:
        return
    try:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
        if not is_any_admin(message.from_user.id, user):
            await message.answer("\u26d4")
            return
        sa = is_super_admin(message.from_user.id)
        await message.answer("\U0001f6e0 <b>\u0410\u0434\u043c\u0438\u043d</b>", parse_mode="HTML", reply_markup=admin_center_keyboard(is_super_admin=sa))
    except Exception as e:
        logger.error(f"[ADMIN_BTN] {e}")
        await message.answer("\u041e\u0448\u0438\u0431\u043a\u0430.")


@router.callback_query(F.data == "admin_center")
async def cb_admin_center(callback: CallbackQuery):
    if not callback.from_user:
        return
    try:
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
        if not is_any_admin(callback.from_user.id, user):
            await callback.answer("\u26d4", show_alert=True)
            return
        sa = is_super_admin(callback.from_user.id)
        await callback.message.answer("\U0001f6e0 <b>\u0410\u0434\u043c\u0438\u043d</b>", parse_mode="HTML", reply_markup=admin_center_keyboard(is_super_admin=sa))
        await callback.answer()
    except Exception as e:
        logger.error(f"[ADMIN_CB] {e}")
        await callback.answer("\u041e\u0448\u0438\u0431\u043a\u0430", show_alert=True)
