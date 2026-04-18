from decimal import Decimal
from aiogram import Router, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import (
    Message,
    CallbackQuery,
    LabeledPrice,
    PreCheckoutQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from app.config import (
    ADMINS,
    WATCH_COST,
    STARS_PACKAGES,
    STARS_TO_COINS_RATE,
    REACTION_TYPES,
    XP_PER_WATCH,
    XP_PER_UPLOAD,
    XP_PER_RATING,
    XP_PER_COMMENT,
    XP_PER_REACTION,
    XP_PER_GAME,
)
from app.db import async_session
from app.services import (
    get_or_create_user,
    agree_to_rules,
    get_user,
    save_video,
    save_photo,
    get_random_video_for_user,
    get_random_photo_for_user,
    record_view_and_charge,
    record_photo_view,
    count_photo_views_last_4h,
    rate_video,
    claim_daily_bonus,
    count_referrals,
    create_payment,
    create_custom_payment,
    create_vip_payment,
    apply_successful_payment,
    get_active_offers,
    get_offer_by_id,
    start_offer_participation,
    verify_offer_subscription,
    FREE_PHOTO_LIMIT_PER_4H,
    add_xp,
    calc_level_info,
    is_vip,
    ensure_daily_quests,
    increment_quest,
    claim_quest_reward,
    get_top_uploaders,
    get_top_viewers,
    get_top_by_level,
    get_top_richest,
    play_lootbox,
    play_dice,
    play_coinflip,
    play_guess,
    add_comment,
    get_video_comments,
    add_reaction,
    get_reaction_counts,
    check_game_limit,
    pay_for_game_session,
    increment_game_session,
    GAME_SESSION_COST,
    GAME_SESSION_LIMIT,
)
from app.keyboards import (
    rules_keyboard,
    main_menu,
    video_rating_keyboard,
    photo_actions_keyboard,
    watch_choice_keyboard,
    admin_center_keyboard,
    buy_coins_keyboard,
    vip_buy_keyboard,
    offers_list_keyboard,
    offer_view_keyboard,
    games_menu_keyboard,
    tops_menu_keyboard,
    quests_keyboard,
    reaction_menu_keyboard,
    BTN_WATCH,
    BTN_UPLOAD,
    BTN_PROFILE,
    BTN_BUY,
    BTN_OFFERS,
    BTN_REFERRALS,
    BTN_BONUS,
    BTN_ADMIN,
    BTN_GAMES,
    BTN_TOPS,
    BTN_QUESTS,
    BTN_VIP,
    BTN_LEVEL,
)
from app.logger import get_logger, log_info, log_warning, log_exception

logger = get_logger(__name__)
router = Router()

RULES_TEXT = (
    "⚠️ <b>Правила</b>\n\n"
    "1. Бот содержит контент 18+.\n"
    "2. Используя бот, вы подтверждаете 18+.\n"
    "3. Запрещено CP.\n"
    "4. Запрещён контент с насилием.\n"
    "5. Администрация может ограничить доступ.\n\n"
    "Нажмите кнопку ниже."
)


def _game_limit_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"💰 Купить ещё {GAME_SESSION_LIMIT} игр за {GAME_SESSION_COST} монет",
                    callback_data="pay_game_session",
                )
            ]
        ]
    )


class CustomPayState(StatesGroup):
    waiting_amount = State()


class GameState(StatesGroup):
    waiting_dice_bet = State()
    waiting_coin_bet = State()
    waiting_guess_number = State()
    waiting_guess_bet = State()


class CommentState(StatesGroup):
    waiting_comment_text = State()


def is_any_admin(telegram_id: int, user_obj=None) -> bool:
    if telegram_id in ADMINS:
        return True
    if user_obj and user_obj.is_admin:
        return True
    return False


def is_super_admin(telegram_id: int) -> bool:
    return telegram_id in ADMINS


def extract_channel_id(channel_url: str) -> str:
    url = channel_url.strip().rstrip("/")
    if url.startswith("https://t.me/"):
        return f"@{url.replace('https://t.me/', '', 1)}"
    if url.startswith("http://t.me/"):
        return f"@{url.replace('http://t.me/', '', 1)}"
    if url.startswith("t.me/"):
        return f"@{url.replace('t.me/', '', 1)}"
    if url.startswith("@"):
        return url
    return f"@{url}"


async def safe_edit_or_answer(callback: CallbackQuery, text: str, reply_markup=None):
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=reply_markup)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=reply_markup)


async def get_user_or_reply(
    event: Message | CallbackQuery,
    telegram_id: int,
    require_rules: bool = True,
):
    async with async_session() as session:
        user = await get_user(session, telegram_id)
        if not user:
            if isinstance(event, CallbackQuery):
                await event.answer("/start", show_alert=True)
            else:
                await event.answer("/start")
            return None
        if require_rules and not user.agreed_to_rules:
            if isinstance(event, CallbackQuery):
                await event.answer("Сначала примите правила", show_alert=True)
            else:
                await event.answer("Сначала примите правила через /start")
            return None
        return user


def format_level_text(user) -> str:
    lvl, current_xp, need_xp = calc_level_info(user.xp)
    vip_text = "\n💎 VIP: активен" if is_vip(user) else ""
    return (
        f"📈 <b>Уровень</b>\n\n"
        f"🏅 Уровень: <b>{lvl}</b>\n"
        f"XP: <b>{user.xp}</b>\n"
        f"Прогресс: <b>{current_xp}/{need_xp}</b>{vip_text}"
    )


async def _maybe_send_offers(message, telegram_id):
    """Автоматически показывает офферы если монет не хватает."""
    try:
        async with async_session() as session:
            offers = await get_active_offers(session)
            if not offers:
                return
            log_info(
                logger,
                "Авто-показ офферов при нехватке монет",
                tg_id=telegram_id,
                offers_count=len(offers),
            )
            await message.answer(
                "💡 <b>Заработайте монеты — выполните офферы!</b>",
                parse_mode="HTML",
                reply_markup=offers_list_keyboard(offers),
            )
    except Exception:
        pass


# ========== START ==========
@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext):
    if not message.from_user:
        return
    await state.clear()
    referral_code = command.args.strip() if command and command.args else None
    try:
        async with async_session() as session:
            user, is_new = await get_or_create_user(
                session,
                message.from_user.id,
                message.from_user.username,
                message.from_user.first_name,
                message.from_user.last_name,
                referral_code,
            )
            if not user.agreed_to_rules:
                log_info(
                    logger,
                    "Новый пользователь, показываем правила",
                    tg_id=message.from_user.id,
                    is_new=is_new,
                    referral_code=referral_code,
                )
                await message.answer(
                    RULES_TEXT,
                    parse_mode="HTML",
                    reply_markup=rules_keyboard(),
                )
                return
            await ensure_daily_quests(session, user.id, user)
            admin_flag = is_any_admin(message.from_user.id, user)
            log_info(
                logger,
                "Пользователь вернулся в бот",
                tg_id=message.from_user.id,
                username=message.from_user.username,
                is_new=is_new,
                balance=str(user.balance),
                is_admin=admin_flag,
            )
            await message.answer(
                f"👋 С возвращением!\n"
                f"💰 Баланс: <b>{user.balance}</b>",
                parse_mode="HTML",
                reply_markup=main_menu(is_admin=admin_flag),
            )
    except Exception:
        log_exception(
            logger,
            "Ошибка в /start",
            tg_id=message.from_user.id if message.from_user else None,
        )
        await message.answer("Ошибка.")


@router.callback_query(F.data == "accept_rules")
async def cb_accept_rules(callback: CallbackQuery):
    if not callback.from_user:
        return
    try:
        async with async_session() as session:
            await agree_to_rules(session, callback.from_user.id)
            user = await get_user(session, callback.from_user.id)
            if not user:
                await callback.answer("/start", show_alert=True)
                return
            await ensure_daily_quests(session, user.id, user)
            admin_flag = is_any_admin(callback.from_user.id, user)
            log_info(
                logger,
                "Пользователь принял правила",
                tg_id=callback.from_user.id,
            )
            await callback.message.edit_text("✅ Правила приняты.")
            await callback.message.answer(
                "Добро пожаловать! Стартовый баланс: <b>2</b>",
                parse_mode="HTML",
                reply_markup=main_menu(is_admin=admin_flag),
            )
            await callback.answer()
    except Exception:
        log_exception(
            logger,
            "Ошибка при принятии правил",
            tg_id=callback.from_user.id if callback.from_user else None,
        )
        await callback.answer("Ошибка", show_alert=True)


# ========== BONUS ==========
@router.message(F.text == BTN_BONUS)
async def daily_bonus(message: Message):
    if not message.from_user:
        return
    try:
        user = await get_user_or_reply(message, message.from_user.id)
        if not user:
            return
        async with async_session() as session:
            success, msg = await claim_daily_bonus(session, message.from_user.id)
        log_info(
            logger,
            "Запрос ежедневного бонуса",
            tg_id=message.from_user.id,
            success=success,
            result=msg,
        )
        await message.answer(f"🏆 {msg}" if success else f"⏳ {msg}")
    except Exception:
        log_exception(
            logger,
            "Ошибка при запросе бонуса",
            tg_id=message.from_user.id if message.from_user else None,
        )
        await message.answer("Ошибка.")


# ========== PROFILE ==========
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
            role = "Админ" if admin_flag else "Пользователь"
            vip_text = ""
            if is_vip(user) and user.vip_until:
                vip_text = "\n💎 VIP до: <b>" + user.vip_until.strftime("%d.%m.%Y") + "</b>"
            text = (
                f"👤 <b>Профиль</b>\n\n"
                f"ID: <code>{user.telegram_id}</code>\n"
                f"💰 Баланс: <b>{user.balance}</b>\n"
                f"📈 XP: <b>{user.xp}</b>\n"
                f"🏅 Уровень: <b>{user.level}</b>\n"
                f"Роль: {role}{vip_text}"
            )
            log_info(
                logger,
                "Запрос профиля",
                tg_id=message.from_user.id,
                balance=str(user.balance),
                xp=user.xp,
                level=user.level,
            )
            await message.answer(text, parse_mode="HTML")
    except Exception:
        log_exception(
            logger,
            "Ошибка при запросе профиля",
            tg_id=message.from_user.id if message.from_user else None,
        )
        await message.answer("Ошибка.")


# ========== LEVEL ==========
@router.message(F.text == BTN_LEVEL)
async def level_info(message: Message):
    if not message.from_user:
        return
    try:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                await message.answer("/start")
                return
            log_info(
                logger,
                "Запрос информации об уровне",
                tg_id=message.from_user.id,
                xp=user.xp,
                level=user.level,
            )
            await message.answer(format_level_text(user), parse_mode="HTML")
    except Exception:
        log_exception(
            logger,
            "Ошибка при запросе уровня",
            tg_id=message.from_user.id if message.from_user else None,
        )
        await message.answer("Ошибка.")


# ========== REFERRALS ==========
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
                f"👥 <b>Пригласи друга!</b>\n\n"
                f"🔗 Твоя ссылка:\n<code>{referral_link}</code>\n\n"
                f"👤 Присоединилось: <b>{referrals_count}</b>\n"
                f"💰 Заработано: <b>{user.referral_earnings}</b>"
            )
            log_info(
                logger,
                "Запрос реферальной ссылки",
                tg_id=message.from_user.id,
                referrals_count=referrals_count,
                referral_earnings=str(user.referral_earnings),
            )
            await message.answer(text, parse_mode="HTML")
    except Exception:
        log_exception(
            logger,
            "Ошибка при запросе рефералов",
            tg_id=message.from_user.id if message.from_user else None,
        )
        await message.answer("Ошибка.")


# ========== BUY ==========
@router.message(F.text == BTN_BUY)
async def buy_coins(message: Message):
    log_info(
        logger,
        "Запрос меню покупки монет",
        tg_id=message.from_user.id if message.from_user else None,
    )
    await message.answer(
        f"💎 <b>Покупка монет</b>\n\n"
        f"Курс: 1 Star = {STARS_TO_COINS_RATE} монет\n\n"
        "Выберите пакет или введите свою сумму:",
        parse_mode="HTML",
        reply_markup=buy_coins_keyboard(),
    )


@router.message(F.text == BTN_VIP)
async def vip_info(message: Message):
    if not message.from_user:
        return
    try:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                await message.answer("/start")
                return
            status = "✅ Активен" if is_vip(user) else "❌ Нет"
            text = (
                "💎 <b>VIP</b>\n\n"
                f"Статус: {status}\n"
                "Бонусы:\n"
                "• x2 к ежедневному бонусу\n"
                "• VIP в профиле\n"
                "• безлимит фото\n\n"
                "Цена: 50 Stars / 30 дней"
            )
            log_info(
                logger,
                "Запрос меню VIP",
                tg_id=message.from_user.id,
                vip_active=is_vip(user),
            )
            await message.answer(text, parse_mode="HTML", reply_markup=vip_buy_keyboard())
    except Exception:
        log_exception(
            logger,
            "Ошибка при запросе VIP",
            tg_id=message.from_user.id if message.from_user else None,
        )
        await message.answer("Ошибка.")


@router.callback_query(F.data == "buy_vip")
async def buy_vip(callback: CallbackQuery):
    if not callback.from_user:
        return
    try:
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not user:
                await callback.answer("/start", show_alert=True)
                return
            payment = await create_vip_payment(session, user)
            log_info(
                logger,
                "Создан VIP-инвойс",
                tg_id=callback.from_user.id,
                payload=payment.payload,
                stars_amount=payment.stars_amount,
            )
            await callback.message.answer_invoice(
                title="VIP 30 дней",
                description="Активация VIP на 30 дней",
                payload=payment.payload,
                provider_token="",
                currency="XTR",
                prices=[LabeledPrice(label="VIP 30 дней", amount=50)],
            )
            await callback.answer()
    except Exception:
        log_exception(
            logger,
            "Ошибка при создании VIP-инвойса",
            tg_id=callback.from_user.id if callback.from_user else None,
        )
        await callback.answer("Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy_package(callback: CallbackQuery):
    if not callback.from_user:
        return
    package_key = callback.data.split(":", 1)[1]
    package = STARS_PACKAGES.get(package_key)
    if not package:
        await callback.answer("Не найден", show_alert=True)
        return
    try:
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not user:
                await callback.answer("/start", show_alert=True)
                return
            payment = await create_payment(session, user, package_key)
            if not payment:
                await callback.answer("Ошибка", show_alert=True)
                return
            log_info(
                logger,
                "Создан инвойс пакета монет",
                tg_id=callback.from_user.id,
                package_key=package_key,
                payload=payment.payload,
                stars_amount=payment.stars_amount,
                coins_amount=str(payment.coins_amount),
            )
            await callback.message.answer_invoice(
                title=f"{package['coins']} монет",
                description=f"Пополнение на {package['coins']} монет",
                payload=payment.payload,
                provider_token="",
                currency="XTR",
                prices=[LabeledPrice(label=f"{package['coins']} монет", amount=package["stars"])],
            )
            await callback.answer()
    except Exception:
        log_exception(
            logger,
            "Ошибка при создании инвойса пакета монет",
            tg_id=callback.from_user.id if callback.from_user else None,
            package_key=package_key,
        )
        await callback.answer("Ошибка", show_alert=True)


@router.callback_query(F.data == "buy_custom")
async def cb_buy_custom(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user:
        return
    await state.set_state(CustomPayState.waiting_amount)
    log_info(
        logger,
        "Начат ввод кастомной суммы Stars",
        tg_id=callback.from_user.id,
    )
    await callback.message.answer(
        f"📝 Введите кол-во звёзд (Stars).\n"
        f"Курс: 1 Star = {STARS_TO_COINS_RATE} монет\n\n"
        "Мин: 1 Star\n/start для отмены"
    )
    await callback.answer()


@router.message(CustomPayState.waiting_amount)
async def custom_pay_amount(message: Message, state: FSMContext):
    if not message.from_user:
        return
    text = (message.text or "").strip()
    if not text.isdigit() or int(text) < 1:
        await message.answer("Введите число от 1.")
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
            log_info(
                logger,
                "Создан кастомный инвойс",
                tg_id=message.from_user.id,
                payload=payment.payload,
                stars_amount=stars,
                coins_amount=str(coins),
            )
            await message.answer_invoice(
                title=f"{coins} монет",
                description=f"{stars} Stars → {coins} монет",
                payload=payment.payload,
                provider_token="",
                currency="XTR",
                prices=[LabeledPrice(label=f"{coins} монет", amount=stars)],
            )
    except Exception:
        log_exception(
            logger,
            "Ошибка при создании кастомного инвойса",
            tg_id=message.from_user.id if message.from_user else None,
            stars=stars,
        )
        await message.answer("Ошибка.")
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
        log_info(
            logger,
            "Обработан успешный платёж",
            tg_id=message.from_user.id,
            payload=payload,
            success=success,
            result=msg,
        )
        await message.answer(f"✅ {msg}" if success else f"⚠️ {msg}")
    except Exception:
        log_exception(
            logger,
            "Ошибка обработки successful_payment",
            tg_id=message.from_user.id if message.from_user else None,
        )
        await message.answer("Ошибка начисления.")


# ========== OFFERS ==========
@router.message(F.text == BTN_OFFERS)
async def show_offers(message: Message):
    if not message.from_user:
        return
    try:
        async with async_session() as session:
            offers = await get_active_offers(session)
            if not offers:
                await message.answer("Офферов нет.")
                return
            log_info(
                logger,
                "Запрос меню офферов",
                tg_id=message.from_user.id,
                offers_count=len(offers),
            )
            await message.answer(
                "🎁 <b>Офферы</b>",
                parse_mode="HTML",
                reply_markup=offers_list_keyboard(offers),
            )
    except Exception:
        log_exception(
            logger,
            "Ошибка при запросе меню офферов",
            tg_id=message.from_user.id if message.from_user else None,
        )
        await message.answer("Ошибка.")


@router.callback_query(F.data.startswith("offer_open:"))
async def offer_open(callback: CallbackQuery):
    if not callback.from_user:
        return
    try:
        offer_id = int(callback.data.split(":")[1])
        async with async_session() as session:
            offer = await get_offer_by_id(session, offer_id)
            if not offer or not offer.is_active:
                await callback.answer("Недоступен", show_alert=True)
                return
            text = (
                f"🎁 <b>{offer.title}</b>\n\n{offer.description}\n\n"
                f"🔗 {offer.channel_url}\n"
                f"💰 Всего: <b>40</b>\n"
                f"⚠️ Штраф: <b>40</b>"
            )
            log_info(
                logger,
                "Просмотр деталей оффера",
                tg_id=callback.from_user.id,
                offer_id=offer.id,
                title=offer.title,
            )
            await safe_edit_or_answer(callback, text, offer_view_keyboard(offer.id, offer.channel_url))
            await callback.answer()
    except Exception:
        log_exception(
            logger,
            "Ошибка при просмотре оффера",
            tg_id=callback.from_user.id if callback.from_user else None,
        )
        await callback.answer("Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("offer_start:"))
async def offer_start(callback: CallbackQuery):
    if not callback.from_user:
        return
    offer_id = None
    try:
        offer_id = int(callback.data.split(":")[1])
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            offer = await get_offer_by_id(session, offer_id)
            if not user or not offer:
                await callback.answer("Не найдено", show_alert=True)
                return
            success, msg = await start_offer_participation(session, user, offer)
            log_info(
                logger,
                "Начало участия в оффере",
                tg_id=callback.from_user.id,
                offer_id=offer_id,
                success=success,
                result=msg,
            )
            text = f"✅ {msg}" if success else f"ℹ️ {msg}"
            if success:
                text += "\n\nПодпишитесь на канал и нажмите проверить."
            await safe_edit_or_answer(callback, text, offer_view_keyboard(offer_id, offer.channel_url))
            await callback.answer()
    except Exception:
        log_exception(
            logger,
            "Ошибка при начале оффера",
            tg_id=callback.from_user.id if callback.from_user else None,
            offer_id=offer_id,
        )
        await callback.answer("Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("offer_check:"))
async def offer_check(callback: CallbackQuery):
    if not callback.from_user:
        return
    offer_id = None
    try:
        offer_id = int(callback.data.split(":")[1])
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            offer = await get_offer_by_id(session, offer_id)
            if not user or not offer:
                await callback.answer("Не найдено", show_alert=True)
                return
            chat_id = extract_channel_id(offer.channel_url)
            subscribed = False
            try:
                cm = await callback.bot.get_chat_member(chat_id=chat_id, user_id=callback.from_user.id)
                subscribed = cm.status in ("member", "administrator", "creator")
            except Exception as e:
                log_warning(
                    logger,
                    "Не удалось проверить подписку через get_chat_member",
                    tg_id=callback.from_user.id,
                    chat_id=chat_id,
                    error=str(e),
                )
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            offer = await get_offer_by_id(session, offer_id)
            success, msg = await verify_offer_subscription(session, user, offer, subscribed)
            log_info(
                logger,
                "Проверка подписки оффера",
                tg_id=callback.from_user.id,
                offer_id=offer_id,
                subscribed=subscribed,
                success=success,
                result=msg,
            )
            await safe_edit_or_answer(
                callback,
                f"✅ {msg}" if success else f"ℹ️ {msg}",
                offer_view_keyboard(offer.id, offer.channel_url),
            )
            await callback.answer()
    except Exception:
        log_exception(
            logger,
            "Ошибка при проверке оффера",
            tg_id=callback.from_user.id if callback.from_user else None,
            offer_id=offer_id,
        )
        await callback.answer("Ошибка", show_alert=True)


# ========== GAMES ==========
@router.message(F.text == BTN_GAMES)
async def games_menu(message: Message):
    log_info(
        logger,
        "Открыто меню игр",
        tg_id=message.from_user.id if message.from_user else None,
    )
    await message.answer(
        f"🎮 <b>Игры</b>\n\n"
        f"Лимит: {GAME_SESSION_LIMIT} игр за 4 часа.\n"
        f"Продление: {GAME_SESSION_COST} монет.\n\n"
        "Выберите:",
        parse_mode="HTML",
        reply_markup=games_menu_keyboard(),
    )


@router.callback_query(F.data == "pay_game_session")
async def cb_pay_game_session(callback: CallbackQuery):
    if not callback.from_user:
        return
    try:
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not user:
                await callback.answer("/start", show_alert=True)
                return
            success, msg = await pay_for_game_session(session, user)
            log_info(
                logger,
                "Оплата игровой сессии",
                tg_id=callback.from_user.id,
                success=success,
                result=msg,
            )
            await callback.message.answer(msg, parse_mode="HTML", reply_markup=games_menu_keyboard())
            await callback.answer()
    except Exception:
        log_exception(
            logger,
            "Ошибка при оплате игровой сессии",
            tg_id=callback.from_user.id if callback.from_user else None,
        )
        await callback.answer("Ошибка", show_alert=True)


@router.callback_query(F.data == "game_lootbox")
async def game_lootbox(callback: CallbackQuery):
    if not callback.from_user:
        return
    try:
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not user:
                await callback.answer("/start", show_alert=True)
                return

            can_play, limit_msg, gs = await check_game_limit(session, user)
            if not can_play:
                await callback.message.answer(limit_msg, parse_mode="HTML", reply_markup=_game_limit_keyboard())
                await callback.answer()
                return

            success, reward, msg = await play_lootbox(session, user)
            if success:
                await increment_game_session(session, user)
                await add_xp(session, user, XP_PER_GAME)

            log_info(
                logger,
                "Игра lootbox сыграна",
                tg_id=callback.from_user.id,
                success=success,
                reward=reward,
                result=msg,
            )
            text = (
                f"📦 Вы открыли лутбокс и выиграли <b>{reward}</b> монет!"
                if success
                else f"⚠️ {msg}"
            )
            await safe_edit_or_answer(callback, text, games_menu_keyboard())
            await callback.answer()
    except Exception:
        log_exception(
            logger,
            "Ошибка в lootbox",
            tg_id=callback.from_user.id if callback.from_user else None,
        )
        await callback.answer("Ошибка", show_alert=True)


@router.callback_query(F.data == "game_dice")
async def game_dice_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameState.waiting_dice_bet)
    await safe_edit_or_answer(
        callback,
        "🎲 Введите ставку для костей (1-50):",
    )
    await callback.answer()


@router.message(GameState.waiting_dice_bet)
async def game_dice_process(message: Message, state: FSMContext):
    if not message.from_user:
        return
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("Введите число.")
        return
    bet = int(text)
    try:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                await message.answer("/start")
                await state.clear()
                return

            can_play, limit_msg, gs = await check_game_limit(session, user)
            if not can_play:
                await message.answer(limit_msg, parse_mode="HTML", reply_markup=_game_limit_keyboard())
                await state.clear()
                return

            success, roll, win, msg = await play_dice(session, user, bet)
            if success:
                await increment_game_session(session, user)
                await add_xp(session, user, XP_PER_GAME)

            log_info(
                logger,
                "Игра dice сыграна",
                tg_id=message.from_user.id,
                bet=bet,
                success=success,
                roll=roll,
                win=str(win),
                result=msg,
            )
            if success:
                await message.answer(
                    f"🎲 Выпало: <b>{roll}</b>\n"
                    f"💰 Выигрыш: <b>{win}</b>",
                    parse_mode="HTML",
                    reply_markup=games_menu_keyboard(),
                )
            else:
                await message.answer(f"⚠️ {msg}", reply_markup=games_menu_keyboard())
    except Exception:
        log_exception(
            logger,
            "Ошибка в dice",
            tg_id=message.from_user.id if message.from_user else None,
            bet=bet,
        )
        await message.answer("Ошибка.")
    finally:
        await state.clear()


@router.callback_query(F.data == "game_coinflip")
async def game_coinflip_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameState.waiting_coin_bet)
    await safe_edit_or_answer(
        callback,
        "🪙 Введите ставку для монетки (1-50):",
    )
    await callback.answer()


@router.message(GameState.waiting_coin_bet)
async def game_coinflip_process(message: Message, state: FSMContext):
    if not message.from_user:
        return
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("Введите число.")
        return
    bet = int(text)
    try:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                await message.answer("/start")
                await state.clear()
                return

            can_play, limit_msg, gs = await check_game_limit(session, user)
            if not can_play:
                await message.answer(limit_msg, parse_mode="HTML", reply_markup=_game_limit_keyboard())
                await state.clear()
                return

            success, side, win, msg = await play_coinflip(session, user, bet)
            if success:
                await increment_game_session(session, user)
                await add_xp(session, user, XP_PER_GAME)

            log_info(
                logger,
                "Игра coinflip сыграна",
                tg_id=message.from_user.id,
                bet=bet,
                success=success,
                side=side,
                win=str(win),
                result=msg,
            )
            if success:
                side_text = "Орёл" if side == "heads" else "Решка"
                await message.answer(
                    f"🪙 {side_text}\n💰 Выигрыш: <b>{win}</b>",
                    parse_mode="HTML",
                    reply_markup=games_menu_keyboard(),
                )
            else:
                await message.answer(f"⚠️ {msg}", reply_markup=games_menu_keyboard())
    except Exception:
        log_exception(
            logger,
            "Ошибка в coinflip",
            tg_id=message.from_user.id if message.from_user else None,
            bet=bet,
        )
        await message.answer("Ошибка.")
    finally:
        await state.clear()


@router.callback_query(F.data == "game_guess")
async def game_guess_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameState.waiting_guess_number)
    await safe_edit_or_answer(
        callback,
        "🔢 Введите число 1-10:",
    )
    await callback.answer()


@router.message(GameState.waiting_guess_number)
async def game_guess_number(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("Введите число.")
        return
    number = int(text)
    await state.update_data(guess=number)
    await state.set_state(GameState.waiting_guess_bet)
    await message.answer("💰 Теперь введите ставку (1-50):")


@router.message(GameState.waiting_guess_bet)
async def game_guess_bet(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("Введите число.")
        return
    bet = int(text)
    data = await state.get_data()
    guess = int(data.get("guess", 0))
    try:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                await message.answer("/start")
                await state.clear()
                return

            can_play, limit_msg, gs = await check_game_limit(session, user)
            if not can_play:
                await message.answer(limit_msg, parse_mode="HTML", reply_markup=_game_limit_keyboard())
                await state.clear()
                return

            success, answer, win, msg = await play_guess(session, user, guess, bet)
            if success:
                await increment_game_session(session, user)
                await add_xp(session, user, XP_PER_GAME)

            log_info(
                logger,
                "Игра guess сыграна",
                tg_id=message.from_user.id,
                bet=bet,
                guess=guess,
                success=success,
                answer=answer,
                win=str(win),
                result=msg,
            )
            if success:
                await message.answer(
                    f"🔢 Вы загадали: <b>{guess}</b>\n"
                    f"Ответ: <b>{answer}</b>\n"
                    f"💰 Выигрыш: <b>{win}</b>",
                    parse_mode="HTML",
                    reply_markup=games_menu_keyboard(),
                )
            else:
                await message.answer(f"⚠️ {msg}", reply_markup=games_menu_keyboard())
    except Exception:
        log_exception(
            logger,
            "Ошибка в guess",
            tg_id=message.from_user.id if message.from_user else None,
            bet=bet,
        )
        await message.answer("Ошибка.")
    finally:
        await state.clear()


# ========== TOPS ==========
@router.message(F.text == BTN_TOPS)
async def tops_menu(message: Message):
    log_info(
        logger,
        "Открыто меню топов",
        tg_id=message.from_user.id if message.from_user else None,
    )
    await message.answer(
        "🏆 <b>Топы</b>",
        parse_mode="HTML",
        reply_markup=tops_menu_keyboard(),
    )


@router.callback_query(F.data == "top_uploaders")
async def top_uploaders(callback: CallbackQuery):
    try:
        async with async_session() as session:
            rows = await get_top_uploaders(session)
            if not rows:
                text = "Пока нет данных."
            else:
                lines = ["🏆 <b>Топ загрузчиков</b>\n"]
                for i, row in enumerate(rows, start=1):
                    username, first_name, telegram_id, cnt = row
                    name = f"@{username}" if username else (first_name or str(telegram_id))
                    lines.append(f"{i}. {name} — {cnt}")
                text = "\n".join(lines)
        log_info(
            logger,
            "Запрос топа загрузчиков",
            tg_id=callback.from_user.id if callback.from_user else None,
            rows_count=len(rows),
        )
        await safe_edit_or_answer(callback, text, tops_menu_keyboard())
        await callback.answer()
    except Exception:
        log_exception(
            logger,
            "Ошибка при запросе топа загрузчиков",
            tg_id=callback.from_user.id if callback.from_user else None,
        )
        await callback.answer("Ошибка", show_alert=True)


@router.callback_query(F.data == "top_viewers")
async def top_viewers(callback: CallbackQuery):
    try:
        async with async_session() as session:
            rows = await get_top_viewers(session)
            if not rows:
                text = "Пока нет данных."
            else:
                lines = ["👀 <b>Топ зрителей</b>\n"]
                for i, row in enumerate(rows, start=1):
                    username, first_name, telegram_id, cnt = row
                    name = f"@{username}" if username else (first_name or str(telegram_id))
                    lines.append(f"{i}. {name} — {cnt}")
                text = "\n".join(lines)
        log_info(
            logger,
            "Запрос топа зрителей",
            tg_id=callback.from_user.id if callback.from_user else None,
            rows_count=len(rows),
        )
        await safe_edit_or_answer(callback, text, tops_menu_keyboard())
        await callback.answer()
    except Exception:
        log_exception(
            logger,
            "Ошибка при запросе топа зрителей",
            tg_id=callback.from_user.id if callback.from_user else None,
        )
        await callback.answer("Ошибка", show_alert=True)


@router.callback_query(F.data == "top_levels")
async def top_levels(callback: CallbackQuery):
    try:
        async with async_session() as session:
            users = await get_top_by_level(session)
            if not users:
                text = "Пока нет данных."
            else:
                lines = ["📈 <b>Топ по XP</b>\n"]
                for i, u in enumerate(users, start=1):
                    name = f"@{u.username}" if u.username else (u.first_name or str(u.telegram_id))
                    lines.append(f"{i}. {name} — lvl {u.level}, XP {u.xp}")
                text = "\n".join(lines)
        log_info(
            logger,
            "Запрос топа по XP",
            tg_id=callback.from_user.id if callback.from_user else None,
            users_count=len(users),
        )
        await safe_edit_or_answer(callback, text, tops_menu_keyboard())
        await callback.answer()
    except Exception:
        log_exception(
            logger,
            "Ошибка при запросе топа по XP",
            tg_id=callback.from_user.id if callback.from_user else None,
        )
        await callback.answer("Ошибка", show_alert=True)


@router.callback_query(F.data == "top_richest")
async def top_richest(callback: CallbackQuery):
    try:
        async with async_session() as session:
            users = await get_top_richest(session)
            if not users:
                text = "Пока нет данных."
            else:
                lines = ["💰 <b>Топ богачей</b>\n"]
                for i, u in enumerate(users, start=1):
                    name = f"@{u.username}" if u.username else (u.first_name or str(u.telegram_id))
                    lines.append(f"{i}. {name} — {u.balance}")
                text = "\n".join(lines)
        log_info(
            logger,
            "Запрос топа богачей",
            tg_id=callback.from_user.id if callback.from_user else None,
            users_count=len(users),
        )
        await safe_edit_or_answer(callback, text, tops_menu_keyboard())
        await callback.answer()
    except Exception:
        log_exception(
            logger,
            "Ошибка при запросе топа богачей",
            tg_id=callback.from_user.id if callback.from_user else None,
        )
        await callback.answer("Ошибка", show_alert=True)


# ========== QUESTS ==========
@router.message(F.text == BTN_QUESTS)
async def quests_menu(message: Message):
    if not message.from_user:
        return
    try:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                await message.answer("/start")
                return
            quests = await ensure_daily_quests(session, user.id, user)
            log_info(
                logger,
                "Открыто меню квестов",
                tg_id=message.from_user.id,
                quests_count=len(quests),
            )
            await message.answer(
                "🎯 <b>Ежедневные квесты</b>",
                parse_mode="HTML",
                reply_markup=quests_keyboard(quests),
            )
    except Exception:
        log_exception(
            logger,
            "Ошибка при запросе квестов",
            tg_id=message.from_user.id if message.from_user else None,
        )
        await message.answer("Ошибка.")


@router.callback_query(F.data.startswith("quest_claim:"))
async def quest_claim(callback: CallbackQuery):
    if not callback.from_user:
        return
    quest_id = None
    try:
        quest_id = int(callback.data.split(":")[1])
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not user:
                await callback.answer("/start", show_alert=True)
                return
            success, msg = await claim_quest_reward(session, user, quest_id)
            quests = await ensure_daily_quests(session, user.id, user)
            log_info(
                logger,
                "Получена награда квеста за кнопку",
                tg_id=callback.from_user.id,
                quest_id=quest_id,
                success=success,
                result=msg,
            )
            text = f"✅ {msg}" if success else f"ℹ️ {msg}"
            await safe_edit_or_answer(callback, text, quests_keyboard(quests))
            await callback.answer()
    except Exception:
        log_exception(
            logger,
            "Ошибка при получении награды квеста за кнопку",
            tg_id=callback.from_user.id if callback.from_user else None,
            quest_id=quest_id,
        )
        await callback.answer("Ошибка", show_alert=True)


@router.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery):
    await callback.answer()


# ========== COMMENTS ==========
@router.callback_query(F.data.startswith("comments:"))
async def show_comments(callback: CallbackQuery):
    try:
        video_id = int(callback.data.split(":")[1])
        async with async_session() as session:
            comments = await get_video_comments(session, video_id, limit=10)
            reactions = await get_reaction_counts(session, video_id)
        react_line = " ".join([f"{k}{v}" for k, v in reactions.items()]) if reactions else "нет"
        if not comments:
            text = (
                f"💬 <b>Комментарии к #{video_id}</b>\n\n"
                f"Реакции: {react_line}\n\n"
                "Пока пусто."
            )
        else:
            lines = [
                f"💬 <b>Комментарии к #{video_id}</b>\n",
                f"Реакции: {react_line}\n"
            ]
            for c in comments:
                lines.append(f"<b>{c['author']}</b>: {c['text']}")
            text = "\n".join(lines)
        log_info(
            logger,
            "Просмотр комментариев",
            tg_id=callback.from_user.id if callback.from_user else None,
            video_id=video_id,
            comments_count=len(comments),
            reactions_count=len(reactions),
        )
        await callback.message.answer(text, parse_mode="HTML")
        await callback.answer()
    except Exception:
        log_exception(
            logger,
            "Ошибка при просмотре комментариев",
            tg_id=callback.from_user.id if callback.from_user else None,
        )
        await callback.answer("Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("comment_add:"))
async def add_comment_start(callback: CallbackQuery, state: FSMContext):
    video_id = None
    try:
        video_id = int(callback.data.split(":")[1])
        await state.update_data(comment_video_id=video_id)
        await state.set_state(CommentState.waiting_comment_text)
        log_info(
            logger,
            "Начало ввода комментария",
            tg_id=callback.from_user.id if callback.from_user else None,
            video_id=video_id,
        )
        await callback.message.answer(
            f"✍️ Напишите комментарий для #{video_id}\n/start — отмена"
        )
        await callback.answer()
    except Exception:
        log_exception(
            logger,
            "Ошибка при начале комментария",
            tg_id=callback.from_user.id if callback.from_user else None,
        )
        await callback.answer("Ошибка", show_alert=True)


@router.message(CommentState.waiting_comment_text)
async def add_comment_process(message: Message, state: FSMContext):
    if not message.from_user:
        return
    text = (message.text or "").strip()
    if len(text) < 1:
        await message.answer("Пустой комментарий.")
        return
    try:
        data = await state.get_data()
        video_id = int(data["comment_video_id"])
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                await message.answer("/start")
                await state.clear()
                return
            await add_comment(session, user.id, video_id, text)
            await add_xp(session, user, XP_PER_COMMENT)
            await increment_quest(session, user.id, "comment")
        log_info(
            logger,
            "Комментарий добавлен",
            tg_id=message.from_user.id,
            video_id=video_id,
            text_length=len(text),
        )
        await message.answer("✅ Комментарий добавлен.")
    except Exception:
        log_exception(
            logger,
            "Ошибка при добавлении комментария",
            tg_id=message.from_user.id if message.from_user else None,
        )
        await message.answer("Ошибка.")
    finally:
        await state.clear()


# ========== REACTIONS ==========
@router.callback_query(F.data.startswith("react_menu:"))
async def react_menu(callback: CallbackQuery):
    try:
        video_id = int(callback.data.split(":")[1])
        log_info(
            logger,
            "Открыто меню реакций",
            tg_id=callback.from_user.id if callback.from_user else None,
            video_id=video_id,
        )
        await callback.message.answer(
            "❤️ <b>Реакции</b>",
            parse_mode="HTML",
            reply_markup=reaction_menu_keyboard(video_id),
        )
        await callback.answer()
    except Exception:
        log_exception(
            logger,
            "Ошибка при открытии меню реакций",
            tg_id=callback.from_user.id if callback.from_user else None,
        )
        await callback.answer("Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("react:"))
async def react_process(callback: CallbackQuery):
    if not callback.from_user:
        return
    try:
        _, video_id, reaction = callback.data.split(":", 2)
        if reaction not in REACTION_TYPES:
            await callback.answer("Нельзя", show_alert=True)
            return
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not user:
                await callback.answer("/start", show_alert=True)
                return
            await add_reaction(session, user.id, int(video_id), reaction)
            await add_xp(session, user, XP_PER_REACTION)
            await increment_quest(session, user.id, "react")
        log_info(
            logger,
            "Добавлена реакция",
            tg_id=callback.from_user.id,
            video_id=int(video_id),
            reaction=reaction,
        )
        await callback.answer(f"{reaction} сохранено")
    except Exception:
        log_exception(
            logger,
            "Ошибка при добавлении реакции",
            tg_id=callback.from_user.id if callback.from_user else None,
        )
        await callback.answer("Ошибка", show_alert=True)


# ========== UPLOAD ==========
@router.message(F.text == BTN_UPLOAD)
async def upload_prompt(message: Message):
    log_info(
        logger,
        "Запрос меню загрузки контента",
        tg_id=message.from_user.id if message.from_user else None,
    )
    await message.answer(
        "Отправьте видео, кружок или фото.\n\n"
        "Награда: видео/кружок <b>0.5</b>, фото <b>0.1</b>",
        parse_mode="HTML",
    )


@router.message(F.video)
async def handle_video(message: Message):
    if not message.from_user or not message.video:
        return
    await _upload_video(
        message,
        message.video.file_id,
        message.video.file_unique_id,
        message.video.duration,
        message.video.file_size,
    )


@router.message(F.video_note)
async def handle_vnote(message: Message):
    if not message.from_user or not message.video_note:
        return
    await _upload_video(
        message,
        message.video_note.file_id,
        message.video_note.file_unique_id,
        message.video_note.duration,
        message.video_note.file_size,
    )


async def _upload_video(message, file_id, file_unique_id, duration, file_size):
    try:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user or not user.agreed_to_rules:
                await message.answer("/start")
                return
            video = await save_video(session, user, file_id, file_unique_id, duration, file_size)
            if video is None:
                log_warning(
                    logger,
                    "Попытка загрузить дубликат видео",
                    tg_id=message.from_user.id,
                    file_unique_id=file_unique_id,
                )
                await message.answer("⚠️ Дубликат.")
                return
            await add_xp(session, user, XP_PER_UPLOAD)
            await increment_quest(session, user.id, "upload")
            log_info(
                logger,
                "Видео отправлено на модерацию",
                tg_id=message.from_user.id,
                video_id=video.id,
                duration=duration,
                file_size=file_size,
            )
            await message.answer(
                "✅ На модерации. Награда: <b>0.5</b>",
                parse_mode="HTML",
            )
    except Exception:
        log_exception(
            logger,
            "Ошибка при загрузке видео",
            tg_id=message.from_user.id if message.from_user else None,
        )
        await message.answer("Ошибка.")


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
                log_warning(
                    logger,
                    "Попытка загрузить дубликат фото",
                    tg_id=message.from_user.id,
                    file_unique_id=largest.file_unique_id,
                )
                await message.answer("⚠️ Дубликат.")
                return
            await add_xp(session, user, XP_PER_UPLOAD)
            await increment_quest(session, user.id, "upload")
            log_info(
                logger,
                "Фото отправлено на модерацию",
                tg_id=message.from_user.id,
                photo_id=photo.id,
                file_size=largest.file_size,
            )
            await message.answer(
                "✅ На модерации. Награда: <b>0.1</b>",
                parse_mode="HTML",
            )
    except Exception:
        log_exception(
            logger,
            "Ошибка при загрузке фото",
            tg_id=message.from_user.id if message.from_user else None,
        )
        await message.answer("Ошибка.")


# ========== WATCH ==========
@router.message(F.text == BTN_WATCH)
async def watch_menu(message: Message):
    log_info(
        logger,
        "Открыто меню просмотра",
        tg_id=message.from_user.id if message.from_user else None,
    )
    await message.answer("Выберите:", reply_markup=watch_choice_keyboard())


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
                await message.answer("❌ Недостаточно монет.")
                await _maybe_send_offers(message, telegram_id)
                return
            video = await get_random_video_for_user(session, user)
            if not video:
                await message.answer("📭 Нет видео.")
                return
            charged = await record_view_and_charge(session, user, video)
            if not charged:
                await message.answer("❌ Ошибка.")
                return
            await add_xp(session, user, XP_PER_WATCH)
            await increment_quest(session, user.id, "watch")
            await session.refresh(user)
            fid = video.telegram_file_id
            vid = video.id
            bal = user.balance
            log_info(
                logger,
                "Видео отправлено пользователю",
                tg_id=telegram_id,
                video_id=vid,
                balance_after=str(bal),
            )
            await message.answer_video(
                video=fid,
                caption=f"💰 -1. Баланс: <b>{bal}</b>",
                parse_mode="HTML",
                reply_markup=video_rating_keyboard(vid),
            )
    except Exception:
        log_exception(
            logger,
            "Ошибка при отправке видео пользователю",
            tg_id=telegram_id,
        )
        await message.answer("Ошибка.")


async def _send_photo(message, telegram_id):
    try:
        async with async_session() as session:
            user = await get_user(session, telegram_id)
            if not user:
                await message.answer("/start")
                return
            if not is_vip(user):
                vc = await count_photo_views_last_4h(session, user.id)
                if vc >= FREE_PHOTO_LIMIT_PER_4H:
                    await message.answer(f"⛔ Лимит {FREE_PHOTO_LIMIT_PER_4H} фото/4ч.")
                    await _maybe_send_offers(message, telegram_id)
                    return
            else:
                vc = 0
            photo = await get_random_photo_for_user(session, user)
            if not photo:
                await message.answer("📭 Нет фото.")
                return
            await record_photo_view(session, user, photo)
            rem = "∞" if is_vip(user) else str(FREE_PHOTO_LIMIT_PER_4H - (vc + 1))
            fid = photo.telegram_file_id
            pid = photo.id
            log_info(
                logger,
                "Фото отправлено пользователю",
                tg_id=telegram_id,
                photo_id=pid,
                remaining=rem,
            )
            await message.answer_photo(
                photo=fid,
                caption=f"🖼 Осталось: <b>{rem}</b>",
                parse_mode="HTML",
                reply_markup=photo_actions_keyboard(),
            )
    except Exception:
        log_exception(
            logger,
            "Ошибка при отправке фото пользователю",
            tg_id=telegram_id,
        )
        await message.answer("Ошибка.")


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
                await add_xp(session, user, XP_PER_RATING)
                await increment_quest(session, user.id, "rate")
        log_info(
            logger,
            "Поставлена оценка видео",
            tg_id=callback.from_user.id,
            video_id=vid,
            rating=r,
        )
        await callback.answer("Оценка сохранена")
    except Exception:
        log_exception(
            logger,
            "Ошибка при оценке видео",
            tg_id=callback.from_user.id if callback.from_user else None,
        )
        await callback.answer("Ошибка", show_alert=True)


# ========== ADMIN ==========
@router.message(F.text == BTN_ADMIN)
async def open_admin(message: Message):
    if not message.from_user:
        return
    try:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not is_any_admin(message.from_user.id, user):
                await message.answer("⛔")
                return
            sa = is_super_admin(message.from_user.id)
            log_info(
                logger,
                "Открыта панель администратора",
                tg_id=message.from_user.id,
                is_super_admin=sa,
            )
            await message.answer(
                "🛠 <b>Админ</b>",
                parse_mode="HTML",
                reply_markup=admin_center_keyboard(is_super_admin=sa),
            )
    except Exception:
        log_exception(
            logger,
            "Ошибка при открытии панели админа",
            tg_id=message.from_user.id if message.from_user else None,
        )
        await message.answer("Ошибка.")


@router.callback_query(F.data == "admin_center")
async def cb_admin_center(callback: CallbackQuery):
    if not callback.from_user:
        return
    try:
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not is_any_admin(callback.from_user.id, user):
                await callback.answer("⛔", show_alert=True)
                return
            sa = is_super_admin(callback.from_user.id)
            log_info(
                logger,
                "Возврат в admin_center callback",
                tg_id=callback.from_user.id,
                is_super_admin=sa,
            )
            await safe_edit_or_answer(
                callback,
                "🛠 <b>Админ</b>",
                admin_center_keyboard(is_super_admin=sa),
            )
            await callback.answer()
    except Exception:
        log_exception(
            logger,
            "Ошибка при возврате в admin_center",
            tg_id=callback.from_user.id if callback.from_user else None,
        )
        await callback.answer("Ошибка", show_alert=True)


# ========== FALLBACK ==========
@router.message()
async def fallback_unknown_message(message: Message):
    if not message.from_user:
        return
    log_warning(
        logger,
        "Неизвестное сообщение от пользователя",
        tg_id=message.from_user.id,
        text=message.text,
    )
    await message.answer(
        "ℹ️ Я не понял эту команду.\n"
        "Используйте /start или кнопки меню."
    )
