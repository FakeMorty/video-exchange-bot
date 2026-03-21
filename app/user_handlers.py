import logging
import traceback
from decimal import Decimal

from aiogram import Router, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import Message, CallbackQuery, LabeledPrice, PreCheckoutQuery

from app.config import ADMINS, WATCH_COST, STARS_PACKAGES
from app.db import async_session
from app.services import (
    get_or_create_user,
    agree_to_rules,
    get_user,
    save_video,
    get_random_video_for_user,
    record_view_and_charge,
    rate_video,
    claim_daily_bonus,
    get_video_stats_for_user,
    count_referrals,
    create_payment,
    apply_successful_payment,
    get_active_offers,
    get_offer_by_id,
    start_offer_participation,
    verify_offer_subscription,
)
from app.keyboards import (
    rules_keyboard,
    main_menu,
    video_rating_keyboard,
    admin_center_keyboard,
    buy_coins_keyboard,
    offers_list_keyboard,
    offer_view_keyboard,
    BTN_WATCH,
    BTN_UPLOAD,
    BTN_PROFILE,
    BTN_BUY,
    BTN_OFFERS,
    BTN_REFERRALS,
    BTN_BONUS,
    BTN_ADMIN,
)

logger = logging.getLogger(__name__)
router = Router()

RULES_TEXT = (
    "⚠️ <b>Правила использования</b>\n\n"
    "1. Бот содержит контент 18+.\n"
    "2. Используя бота, вы подтверждаете, что вам есть 18 лет.\n"
    "3. Запрещено загружать контент с несовершеннолетними.\n"
    "4. Запрещён контент с насилием.\n"
    "5. Администрация имеет право ограничить доступ при нарушениях.\n\n"
    "Нажмите кнопку ниже, чтобы принять правила."
)


def is_admin(telegram_id: int) -> bool:
    return telegram_id in ADMINS


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    if not message.from_user:
        return

    referral_code = None
    if command and command.args:
        arg = command.args.strip()
        if arg.startswith("ref_"):
            referral_code = arg.replace("ref_", "", 1)

    try:
        async with async_session() as session:
            user, created = await get_or_create_user(
                session,
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
                referral_code=referral_code,
            )

            if not user.agreed_to_rules:
                await message.answer(
                    RULES_TEXT,
                    parse_mode="HTML",
                    reply_markup=rules_keyboard(),
                )
                return

            await message.answer(
                f"С возвращением!\n\n"
                f"💰 Баланс: <b>{user.balance}</b> монет",
                parse_mode="HTML",
                reply_markup=main_menu(is_admin=is_admin(message.from_user.id)),
            )
    except Exception as e:
        logger.error(f"[START] ERROR: {e}")
        logger.error(traceback.format_exc())
        await message.answer("Произошла ошибка при запуске.")


@router.callback_query(F.data == "accept_rules")
async def cb_accept_rules(callback: CallbackQuery):
    if not callback.from_user:
        return

    try:
        async with async_session() as session:
            await agree_to_rules(session, callback.from_user.id)

        await callback.message.edit_text("✅ Правила приняты.")
        await callback.message.answer(
            "Добро пожаловать!\n\n"
            "🎁 Вам начислен стартовый баланс: <b>2</b> монеты",
            parse_mode="HTML",
            reply_markup=main_menu(is_admin=is_admin(callback.from_user.id)),
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"[ACCEPT_RULES] ERROR: {e}")
        logger.error(traceback.format_exc())
        await callback.answer("Ошибка", show_alert=True)


@router.message(F.text == BTN_BONUS)
async def daily_bonus(message: Message):
    if not message.from_user:
        return

    try:
        async with async_session() as session:
            success, msg = await claim_daily_bonus(session, message.from_user.id)

        if success:
            await message.answer(f"🏆 {msg}")
        else:
            await message.answer(f"⏳ {msg}")
    except Exception as e:
        logger.error(f"[BONUS] ERROR: {e}")
        logger.error(traceback.format_exc())
        await message.answer("Не удалось получить бонус.")


@router.message(F.text == BTN_PROFILE)
async def show_profile(message: Message):
    if not message.from_user:
        return

    try:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)

        if not user:
            await message.answer("Пользователь не найден. Нажмите /start")
            return

        role = "Администратор" if is_admin(message.from_user.id) else "Пользователь"

        text = (
            f"👤 <b>Профиль</b>\n\n"
            f"🆔 Telegram ID: <code>{user.telegram_id}</code>\n"
            f"💰 Баланс: <b>{user.balance}</b> монет\n"
            f"🔗 Реферальный код: <code>{user.referral_code}</code>\n"
            f"📊 Статус: {user.status}\n"
            f"🛡 Роль: {role}"
        )
        await message.answer(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"[PROFILE] ERROR: {e}")
        logger.error(traceback.format_exc())
        await message.answer("Не удалось открыть профиль.")


@router.message(F.text == BTN_REFERRALS)
async def referrals_info(message: Message):
    if not message.from_user:
        return

    try:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                await message.answer("Пользователь не найден. Нажмите /start")
                return

            referrals_count = await count_referrals(session, user.id)

        bot_username = (await message.bot.get_me()).username
        referral_link = f"https://t.me/{bot_username}?start=ref_{user.referral_code}"

        text = (
            f"👥 <b>Рефералы</b>\n\n"
            f"🔗 Ваша ссылка:\n<code>{referral_link}</code>\n\n"
            f"🧩 Ваш код: <code>{user.referral_code}</code>\n"
            f"👤 Приглашено пользователей: <b>{referrals_count}</b>\n"
            f"💰 Заработано по рефералам: <b>{user.referral_earnings}</b> монет\n\n"
            f"За каждого приглашённого:\n"
            f"• вам: <b>+2</b> монеты\n"
            f"• ему: <b>+1</b> монета"
        )
        await message.answer(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"[REFERRALS] ERROR: {e}")
        logger.error(traceback.format_exc())
        await message.answer("Не удалось открыть раздел рефералов.")


@router.message(F.text == BTN_BUY)
async def buy_coins(message: Message):
    await message.answer(
        "💎 <b>Покупка монет через Telegram Stars</b>\n\n"
        "Выберите пакет:",
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
        await callback.answer("Пакет не найден", show_alert=True)
        return

    try:
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not user:
                await callback.answer("Пользователь не найден", show_alert=True)
                return

            payment = await create_payment(session, user, package_key)
            if not payment:
                await callback.answer("Не удалось создать платёж", show_alert=True)
                return

        await callback.message.answer_invoice(
            title=f"Покупка: {package['title']}",
            description=f"Пополнение баланса на {package['coins']} монет",
            payload=payment.payload,
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=package["title"], amount=package["stars"])],
        )

        await callback.answer()
    except Exception as e:
        logger.error(f"[BUY] ERROR: {e}")
        logger.error(traceback.format_exc())
        await callback.answer("Ошибка оплаты", show_alert=True)


@router.pre_checkout_query()
async def pre_checkout_query(pre_checkout_query: PreCheckoutQuery):
    try:
        await pre_checkout_query.answer(ok=True)
    except Exception as e:
        logger.error(f"[PRE_CHECKOUT] ERROR: {e}")
        logger.error(traceback.format_exc())


@router.message(F.successful_payment)
async def successful_payment(message: Message):
    if not message.from_user or not message.successful_payment:
        return

    try:
        payload = message.successful_payment.invoice_payload

        async with async_session() as session:
            success, msg = await apply_successful_payment(session, payload)

        if success:
            await message.answer(f"✅ Оплата прошла успешно.\n{msg}")
        else:
            await message.answer(f"⚠️ Оплата прошла, но возникла проблема: {msg}")
    except Exception as e:
        logger.error(f"[SUCCESS_PAYMENT] ERROR: {e}")
        logger.error(traceback.format_exc())
        await message.answer(
            "Оплата прошла, но произошла ошибка при начислении монет. Напишите администратору."
        )


@router.message(F.text == BTN_OFFERS)
async def show_offers(message: Message):
    if not message.from_user:
        return

    try:
        async with async_session() as session:
            offers = await get_active_offers(session)

        if not offers:
            await message.answer(
                "🎁 <b>Офферы</b>\n\n"
                "Сейчас активных офферов нет.",
                parse_mode="HTML",
            )
            return

        await message.answer(
            "🎁 <b>Доступные офферы</b>\n\nВыберите оффер:",
            parse_mode="HTML",
            reply_markup=offers_list_keyboard(offers),
        )
    except Exception as e:
        logger.error(f"[OFFERS] ERROR: {e}")
        logger.error(traceback.format_exc())
        await message.answer("Не удалось загрузить офферы.")


@router.callback_query(F.data.startswith("offer_open:"))
async def offer_open(callback: CallbackQuery):
    if not callback.from_user:
        return

    try:
        offer_id = int(callback.data.split(":")[1])

        async with async_session() as session:
            offer = await get_offer_by_id(session, offer_id)

        if not offer or not offer.is_active:
            await callback.answer("Оффер недоступен", show_alert=True)
            return

        text = (
            f"🎁 <b>{offer.title}</b>\n\n"
            f"{offer.description}\n\n"
            f"🔗 Канал: {offer.channel_url}\n"
            f"💰 Награда за старт: <b>{offer.reward_preview}</b>\n"
            f"💰 Награда за подтверждение: <b>{offer.reward_final}</b>\n"
            f"⚠️ Штраф за отписку: <b>{offer.penalty_unsubscribe}</b>"
        )

        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=offer_view_keyboard(offer.id, offer.channel_url),
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"[OFFER_OPEN] ERROR: {e}")
        logger.error(traceback.format_exc())
        await callback.answer("Ошибка", show_alert=True)


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
                await callback.answer("Оффер не найден", show_alert=True)
                return

            success, msg = await start_offer_participation(session, user, offer)

        if success:
            await callback.message.answer(f"✅ {msg}")
        else:
            await callback.message.answer(f"ℹ️ {msg}")

        await callback.answer()
    except Exception as e:
        logger.error(f"[OFFER_START] ERROR: {e}")
        logger.error(traceback.format_exc())
        await callback.answer("Ошибка", show_alert=True)


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
                await callback.answer("Оффер не найден", show_alert=True)
                return

        # Проверка подписки через Telegram API
        subscribed = False
        error_text = None

        try:
            chat_member = await callback.bot.get_chat_member(chat_id=offer.channel_url, user_id=callback.from_user.id)
            subscribed = chat_member.status in ("member", "administrator", "creator")
        except Exception as e:
            error_text = str(e)

        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            offer = await get_offer_by_id(session, offer_id)

            if not user or not offer:
                await callback.answer("Оффер не найден", show_alert=True)
                return

            success, msg = await verify_offer_subscription(session, user, offer, subscribed)

        if error_text:
            await callback.message.answer(
                "⚠️ Бот не смог надёжно проверить подписку.\n"
                "Убедитесь, что бот имеет доступ к каналу.\n\n"
                f"Технически: <code>{error_text}</code>",
                parse_mode="HTML",
            )

        if success:
            await callback.message.answer(f"✅ {msg}")
        else:
            await callback.message.answer(f"ℹ️ {msg}")

        await callback.answer()
    except Exception as e:
        logger.error(f"[OFFER_CHECK] ERROR: {e}")
        logger.error(traceback.format_exc())
        await callback.answer("Ошибка проверки", show_alert=True)


@router.message(F.text == BTN_UPLOAD)
async def upload_prompt(message: Message):
    await message.answer("Отправьте видео, которое хотите загрузить.")


@router.message(F.video)
async def handle_video_upload(message: Message):
    if not message.from_user or not message.video:
        return

    try:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                await message.answer("Пользователь не найден. Нажмите /start")
                return

            if not user.agreed_to_rules:
                await message.answer("Сначала примите правила через /start")
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
            await message.answer("⚠️ Это видео уже загружалось ранее. Дубликат.")
        else:
            await message.answer(
                "✅ Видео загружено и сразу отправлено на модерацию.\n"
                "После одобрения вы получите <b>0.5 монеты</b>.",
                parse_mode="HTML",
            )
    except Exception as e:
        logger.error(f"[VIDEO_UPLOAD] ERROR: {e}")
        logger.error(traceback.format_exc())
        await message.answer("Ошибка при загрузке видео.")


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
    try:
        async with async_session() as session:
            user = await get_user(session, telegram_id)
            if not user:
                await message.answer("Пользователь не найден. Нажмите /start")
                return

            if user.balance < Decimal(str(WATCH_COST)):
                await message.answer(
                    "❌ Недостаточно монет для просмотра.\n"
                    "Получите бонус, пригласите друзей, выполните оффер или купите монеты."
                )
                return

            stats = await get_video_stats_for_user(session, user)

            video = await get_random_video_for_user(session, user)
            if not video:
                if stats["total_approved"] == 0:
                    await message.answer("📭 В базе пока нет одобренных видео.")
                elif stats["approved_not_own"] == 0:
                    await message.answer(
                        "📭 Нет доступных видео для просмотра.\n"
                        "Ваши собственные видео пользователю не показываются."
                    )
                elif stats["available"] == 0:
                    await message.answer("📭 Вы уже просмотрели все доступные вам видео.")
                else:
                    await message.answer("📭 Для вас пока нет новых видео.")
                return

            charged = await record_view_and_charge(session, user, video)
            if not charged:
                await message.answer("❌ Не удалось списать монету за просмотр.")
                return

            new_balance = user.balance
            video_file_id = video.telegram_file_id
            video_db_id = video.id

        await message.answer_video(
            video=video_file_id,
            caption=f"💰 Списана 1 монета.\nТекущий баланс: <b>{new_balance}</b>",
            parse_mode="HTML",
            reply_markup=video_rating_keyboard(video_db_id),
        )
    except Exception as e:
        logger.error(f"[SEND_VIDEO] ERROR: {e}")
        logger.error(traceback.format_exc())
        await message.answer("Ошибка при показе видео.")


@router.callback_query(F.data.startswith("rate:"))
async def cb_rate_video(callback: CallbackQuery):
    if not callback.from_user:
        return

    try:
        parts = callback.data.split(":")
        if len(parts) != 3:
            await callback.answer("Ошибка")
            return

        video_id = int(parts[1])
        rating = int(parts[2])

        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not user:
                await callback.answer("Пользователь не найден")
                return

            await rate_video(session, user.id, video_id, rating)

        await callback.answer("Оценка сохранена")
    except Exception as e:
        logger.error(f"[RATE] ERROR: {e}")
        logger.error(traceback.format_exc())
        await callback.answer("Ошибка оценки", show_alert=True)


@router.message(F.text == BTN_ADMIN)
async def open_admin_center(message: Message):
    if not message.from_user:
        return

    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа к админ-центру.")
        return

    await message.answer(
        "🛠 <b>Админ-центр</b>\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=admin_center_keyboard(),
    )


@router.callback_query(F.data == "admin_center")
async def cb_admin_center(callback: CallbackQuery):
    if not callback.from_user:
        return

    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await callback.message.answer(
        "🛠 <b>Админ-центр</b>\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=admin_center_keyboard(),
    )
    await callback.answer()