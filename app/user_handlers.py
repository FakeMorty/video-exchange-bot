from decimal import Decimal
import uuid
import asyncio
from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton,
)
from sqlalchemy import select, func, desc

from app.config import (
    ADMINS, LEVEL_XP_BASE, LEVEL_XP_MULTIPLIER,
    DAILY_QUESTS, PREMIUM_DAILY_QUESTS,
    NICKNAME_CHANGE_COST, NICKNAME_MIN_LENGTH, NICKNAME_MAX_LENGTH,
    PROMOCODE_CREATION_STAR_RATE,
    PROMOCODE_MAX_AMOUNT, PROMOCODE_MAX_USES, PROMOCODE_MAX_HOURS,
    VIP_FREE_PROMO_PER_MONTH,
    ENABLE_PROMOCODES,
    PROMO_ACTIVATE_COOLDOWN_SECONDS,
    ENABLE_LOTTERY,
    WEBHOOK_BASE,
)
from app.db import async_session

class CaptchaState(StatesGroup):
    waiting_for_text = State()

from app.models import (
    User, Video, VideoView, DailyQuestProgress, Offer, Promocode,
)
from app.services import (
    get_or_create_user, get_user, get_user_by_id,
    ensure_payment_pending, get_offer_by_id,
    to_decimal,
    set_display_name, get_display_name, log_balance_change,
    create_promocode, activate_promocode,
    calculate_promocode_star_cost,
    create_feedback,
    ensure_current_lottery_round, buy_lottery_ticket,
    get_latest_lottery_round, get_user_lottery_tickets, get_lottery_state_dict,
    is_admin_or_super,
)
from app.selfcheck import run_selfcheck, format_selfcheck_report
from app.keyboards import (
    main_menu,
    tops_menu_keyboard,
    quests_keyboard, BTN_TOPS, BTN_QUESTS, BTN_PROMO, BTN_FEEDBACK, BTN_LOTTERY,
)
from app.logger import get_logger

logger = get_logger(__name__)
router = Router()
_offer_action_last_ts: dict[tuple[int, str], datetime] = {}
_promo_activate_last_ts: dict[int, datetime] = {}

async def _safe_callback_answer(callback: CallbackQuery) -> None:
    try:
        pass
    except Exception:
        pass


def _chat_id_from_offer_url(channel_url: str) -> str | None:
    if not channel_url:
        return None
    url = channel_url.strip()
    if "t.me/" in url:
        url = url.split("t.me/", 1)[1]
    if url.startswith("@"):
        return url
    url = url.strip("/").split("?")[0]
    if not url:
        return None
    return f"@{url}"


async def _check_user_offer_subscription(callback: CallbackQuery, offer: Offer) -> bool:
    chat_id = _chat_id_from_offer_url(offer.channel_url)
    if not chat_id:
        return False
    try:
        member = await callback.bot.get_chat_member(chat_id=chat_id, user_id=callback.from_user.id)
        return member.status in {"member", "administrator", "creator"}
    except TelegramBadRequest:
        return False
    except Exception:
        return False


def _cooldown_ok(
    cache: dict,
    key,
    cooldown_seconds: int,
) -> bool:
    now = datetime.utcnow()
    last = cache.get(key)
    if last and (now - last).total_seconds() < cooldown_seconds:
        return False
    cache[key] = now
    return True


# =========================
# STATES
# =========================
class NicknameState(StatesGroup):
    waiting_nickname = State()


class CommentState(StatesGroup):
    waiting_text = State()


class CustomBuyState(StatesGroup):
    waiting_stars = State()


class RentOfferState(StatesGroup):
    waiting_channel_title = State()
    waiting_channel_url = State()
    waiting_days = State()


class PromoCreateState(StatesGroup):
    waiting_amount = State()
    waiting_uses = State()
    waiting_hours = State()


class PromoActivateState(StatesGroup):
    waiting_code = State()


class FeedbackState(StatesGroup):
    waiting_text = State()


# =========================
# HELPERS
# =========================
def is_any_admin(telegram_id: int, user_obj=None) -> bool:
    if telegram_id in ADMINS:
        return True
    if user_obj and user_obj.is_admin:
        return True
    return False


def calc_level_xp_required(level: int) -> int:
    return int(LEVEL_XP_BASE * (LEVEL_XP_MULTIPLIER ** (level - 1)))


def calc_level_from_xp(xp: int) -> int:
    level = 1
    remaining = xp
    while True:
        required = calc_level_xp_required(level)
        if remaining < required:
            break
        remaining -= required
        level += 1
    return level


def is_vip(user) -> bool:
    return bool(user.vip_until and user.vip_until > datetime.utcnow())


async def require_nickname(message: Message, user) -> bool:
    """Проверяет наличие ника. False = ник не задан, показано предупреждение."""
    if user.nickname_set and user.display_name:
        return True
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✏️ Установить ник",
            callback_data="set_nickname_start"
        )]
    ])
    await message.answer(
        f"⚠️ <b>Необходимо установить ник!</b>\n\n"
        f"• От {NICKNAME_MIN_LENGTH} до {NICKNAME_MAX_LENGTH} символов\n"
        f"• Только буквы (рус/лат), цифры, _ и -\n"
        f"• Уникальный\n\n"
        f"Первая установка — бесплатно!\n"
        f"Смена ника стоит {NICKNAME_CHANGE_COST} монет.",
        parse_mode="HTML",
        reply_markup=kb
    )
    return False


async def _level_up_check(session, user, message_or_callback):
    """Проверяет апгрейд уровня и отправляет поздравление."""
    new_level = calc_level_from_xp(user.xp)
    if new_level > user.level:
        user.level = new_level
        await session.commit()
        if hasattr(message_or_callback, "answer"):
            await message_or_callback.answer(
                f"🎉 Поздравляем! Вы достигли уровня <b>{new_level}</b>!",
                parse_mode="HTML"
            )
        else:
            await message_or_callback.message.answer(
                f"🎉 Поздравляем! Вы достигли уровня <b>{new_level}</b>!",
                parse_mode="HTML"
            )


# =========================
# NICKNAME FLOW
# =========================
@router.callback_query(F.data == "set_nickname_start")
async def set_nickname_start(callback: CallbackQuery, state: FSMContext):
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            pass
            return
        is_first = not user.nickname_set
        cost_text = "бесплатно" if is_first else f"{NICKNAME_CHANGE_COST} монет"

    await state.set_state(NicknameState.waiting_nickname)
    await callback.message.answer(
        f"✏️ Введите ник ({cost_text}):\n\n"
        f"• От {NICKNAME_MIN_LENGTH} до {NICKNAME_MAX_LENGTH} символов\n"
        f"• Буквы (рус/лат), цифры, _ или -\n"
        f"• Без точек, пробелов, спецсимволов"
    )
    pass


@router.message(NicknameState.waiting_nickname)
async def process_nickname(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await state.clear()
            return
        ok, msg = await set_display_name(session, user, name)

    await message.answer(msg, parse_mode="HTML")
    if ok:
        await state.clear()
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            admin_flag = is_any_admin(message.from_user.id, user)
        await message.answer(
            "Теперь вы можете пользоваться ботом!",
            reply_markup=main_menu(is_admin=admin_flag)
        )


# =========================
# START / RULES
# =========================
@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext):
    user, created = await get_or_create_user(
        async_session(),
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
        referral_code=command.args
    )

    if not user.agreed_to_rules:
        from captcha.image import ImageCaptcha
        import string
        import random
        from aiogram.types import BufferedInputFile
        
        image = ImageCaptcha(width=280, height=90)
        captcha_text = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
        data = image.generate(captcha_text)
        
        await state.update_data(captcha_text=captcha_text)
        await state.set_state(CaptchaState.waiting_for_text)
        
        photo = BufferedInputFile(data.getvalue(), filename="captcha.png")
        await message.answer_photo(
            photo=photo,
            caption="🤖 <b>Проверка на робота!</b>\n\nПожалуйста, введите код с картинки, чтобы продолжить:"
        )
        return

    await message.answer(
        f"Добро пожаловать обратно, {get_display_name(user)}!",
        reply_markup=main_menu(is_admin=is_admin_or_super(message.from_user.id, user))
    )

@router.message(CaptchaState.waiting_for_text)
async def process_captcha(message: Message, state: FSMContext):
    data = await state.get_data()
    correct_text = data.get("captcha_text", "")
    
    if message.text and message.text.strip().upper() == correct_text.upper():
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if user:
                user.agreed_to_rules = True
                await session.commit()
        
        await state.clear()
        await message.answer("✅ Вы успешно прошли проверку! Добро пожаловать!")
        await message.answer(
            "🚀 Используйте меню ниже для навигации.",
            reply_markup=main_menu(is_admin=is_admin_or_super(message.from_user.id, user))
        )
    else:
        from captcha.image import ImageCaptcha
        import string
        import random
        from aiogram.types import BufferedInputFile
        
        image = ImageCaptcha(width=280, height=90)
        new_text = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
        new_data = image.generate(new_text)
        
        await state.update_data(captcha_text=new_text)
        photo = BufferedInputFile(new_data.getvalue(), filename="captcha.png")
        
        await message.answer_photo(
            photo=photo,
            caption="❌ <b>Неверный код.</b>\n\nПопробуйте еще раз. Введите код с новой картинки:"
        )
    pass


# =========================
# TOPS
# =========================
@router.message(F.text == BTN_TOPS)
async def btn_tops(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if not await require_nickname(message, user):
            return
    await message.answer(
        "🏆 <b>Топы</b>",
        parse_mode="HTML",
        reply_markup=tops_menu_keyboard()
    )


@router.callback_query(F.data == "top_uploaders")
async def top_uploaders(callback: CallbackQuery):
    async with async_session() as session:
        rows = (await session.execute(
            select(User, func.count(Video.id).label("cnt"))
            .join(Video, Video.uploader_user_id == User.id)
            .where(Video.status == "approved")
            .group_by(User.id)
            .order_by(desc("cnt"))
            .limit(10)
        )).all()

    text = "🎬 <b>Топ загрузчиков</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    seen, rank = set(), 0
    for u, cnt in rows:
        if u.id in seen:
            continue
        seen.add(u.id)
        rank += 1
        icon = medals[rank - 1] if rank <= 3 else f"{rank}."
        text += f"{icon} {get_display_name(u)} — {cnt} видео\n"
    if not rows:
        text += "Пусто"
    await callback.message.answer(text, parse_mode="HTML")
    pass


@router.callback_query(F.data == "top_viewers")
async def top_viewers(callback: CallbackQuery):
    async with async_session() as session:
        rows = (await session.execute(
            select(User, func.count(VideoView.id).label("cnt"))
            .join(VideoView, VideoView.user_id == User.id)
            .group_by(User.id)
            .order_by(desc("cnt"))
            .limit(10)
        )).all()

    text = "👁 <b>Топ зрителей</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    seen, rank = set(), 0
    for u, cnt in rows:
        if u.id in seen:
            continue
        seen.add(u.id)
        rank += 1
        icon = medals[rank - 1] if rank <= 3 else f"{rank}."
        text += f"{icon} {get_display_name(u)} — {cnt} просмотров\n"
    if not rows:
        text += "Пусто"
    await callback.message.answer(text, parse_mode="HTML")
    pass


@router.callback_query(F.data == "top_levels")
async def top_levels(callback: CallbackQuery):
    async with async_session() as session:
        users = (await session.execute(
            select(User).order_by(desc(User.xp)).limit(10)
        )).scalars().all()

    text = "⭐ <b>Топ по XP</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    seen, rank = set(), 0
    for u in users:
        if u.id in seen:
            continue
        seen.add(u.id)
        rank += 1
        icon = medals[rank - 1] if rank <= 3 else f"{rank}."
        text += f"{icon} {get_display_name(u)} — Ур.{u.level} ({u.xp} XP)\n"
    if not users:
        text += "Пусто"
    await callback.message.answer(text, parse_mode="HTML")
    pass


@router.callback_query(F.data == "top_richest")
async def top_richest(callback: CallbackQuery):
    async with async_session() as session:
        users = (await session.execute(
            select(User).order_by(desc(User.balance)).limit(10)
        )).scalars().all()

    text = "💰 <b>Топ богатых</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    seen, rank = set(), 0
    for u in users:
        if u.id in seen:
            continue
        seen.add(u.id)
        rank += 1
        icon = medals[rank - 1] if rank <= 3 else f"{rank}."
        text += f"{icon} {get_display_name(u)} — {u.balance:.2f} монет\n"
    if not users:
        text += "Пусто"
    await callback.message.answer(text, parse_mode="HTML")
    pass


# =========================
# QUESTS
# =========================
@router.message(F.text == BTN_QUESTS)
async def btn_quests(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if not await require_nickname(message, user):
            return

        today = datetime.utcnow().date()
        quests = (await session.execute(
            select(DailyQuestProgress).where(
                DailyQuestProgress.user_id == user.id,
                DailyQuestProgress.quest_date == today
            )
        )).scalars().all()

        if not quests:
            quest_list = DAILY_QUESTS.copy()
            if is_vip(user):
                quest_list += PREMIUM_DAILY_QUESTS
            for q in quest_list:
                session.add(DailyQuestProgress(
                    user_id=user.id,
                    quest_type=q["type"],
                    quest_date=today,
                    progress=0,
                    target=q["target"],
                    reward=to_decimal(q["reward"]),
                ))
            await session.commit()
            quests = (await session.execute(
                select(DailyQuestProgress).where(
                    DailyQuestProgress.user_id == user.id,
                    DailyQuestProgress.quest_date == today
                )
            )).scalars().all()

        text = "📋 <b>Ежедневные квесты</b>\n\n"
        for q in quests:
            status = "✅" if q.completed else "⏳"
            claimed = " ✔ получено" if q.reward_claimed else ""
            text += (
                f"{status} {q.quest_type}: "
                f"{q.progress}/{q.target} — "
                f"{q.reward} монет{claimed}\n"
            )

        await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=quests_keyboard(quests)
        )


@router.callback_query(F.data.startswith("quest_claim:"))
async def quest_claim(callback: CallbackQuery):
    quest_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        quest = (await session.execute(
            select(DailyQuestProgress).where(DailyQuestProgress.id == quest_id)
        )).scalar_one_or_none()
        if not quest:
            await callback.answer("Квест не найден.", show_alert=True)
            return
        if not quest.completed:
            await callback.answer("Квест ещё не выполнен!", show_alert=True)
            return
        if quest.reward_claimed:
            await callback.answer("Награда уже получена!", show_alert=True)
            return

        user = await get_user_by_id(session, quest.user_id)
        if not user:
            pass
            return

        quest.reward_claimed = True
        await log_balance_change(
            session, user, quest.reward,
            "quest_reward", source_id=quest.id
        )
        user.balance += quest.reward
        await session.commit()

    await callback.answer(f"🎁 Получено {quest.reward} монет!", show_alert=True)


@router.callback_query(F.data.startswith("quest_done:"))
async def quest_done(callback: CallbackQuery):
    await callback.answer("✅ Квест выполнен, награда уже получена.", show_alert=True)


@router.callback_query(F.data.startswith("quest_info:"))
async def quest_info(callback: CallbackQuery):
    await callback.answer("⏳ Квест ещё не выполнен. Продолжайте!", show_alert=True)


# =========================
# HELPER: обновление квестов
# =========================
async def _update_quest_progress(
    session,
    user_id: int,
    quest_type: str,
    amount: int = 1
):
    today = datetime.utcnow().date()
    quests = (await session.execute(
        select(DailyQuestProgress).where(
            DailyQuestProgress.user_id == user_id,
            DailyQuestProgress.quest_type == quest_type,
            DailyQuestProgress.quest_date == today,
            not DailyQuestProgress.completed
        )
    )).scalars().all()

    for quest in quests:
        quest.progress = min(quest.progress + amount, quest.target)
        if quest.progress >= quest.target:
            quest.completed = True

    try:
        await session.commit()
    except Exception:
        await session.rollback()


# =========================
# УМНАЯ РЕКЛАМА — FORCED OFFER
# =========================

@router.callback_query(F.data == "forced_offer_wait")
async def forced_offer_wait(callback: CallbackQuery):
    await callback.answer(
        "⏳ Подождите ещё немного...",
        show_alert=False
    )


@router.callback_query(F.data.startswith("forced_offer_continue:"))
async def forced_offer_continue(callback: CallbackQuery):
    offer_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        offer = await get_offer_by_id(session, offer_id)
        if offer:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="✅ Я подписался — получить монеты",
                    callback_data=f"offer_start:{offer_id}"
                )],
                [InlineKeyboardButton(
                    text="▶️ Смотреть видео",
                    callback_data="watch_video_content"
                )],
            ])
            await callback.message.answer(
                f"💡 Кстати, за подписку на <b>{offer.title}</b> "
                f"можно получить <b>{offer.reward_preview} монет</b>!\n"
                f"Хотите заработать?",
                parse_mode="HTML",
                reply_markup=kb
            )
        else:
            pass
            return

    pass


@router.callback_query(F.data == "dismiss_low_balance_hint")
async def dismiss_low_balance_hint(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("Хорошо! Офферы всегда доступны в меню 💰")


# =========================
# ЛОТЕРЕЯ-ЛОТО
# =========================
def _lottery_menu_kb() -> InlineKeyboardMarkup:
    base = (WEBHOOK_BASE or "").rstrip("/")
    live_url = f"{base}/lottery/live" if base else ""

    buttons = []
    if live_url:
        from aiogram.types.web_app_info import WebAppInfo
        buttons.append([InlineKeyboardButton(text="🔴 Открыть Live (Mini App)", web_app=WebAppInfo(url=live_url))])
    else:
        buttons.append([InlineKeyboardButton(text="🔴 Как открыть Live", callback_data="lottery_live_info")])

    buttons.extend([
        [InlineKeyboardButton(text="🎫 Купить билет", callback_data="lottery_buy")],
        [InlineKeyboardButton(text="📋 Мои билеты", callback_data="lottery_my_tickets")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="lottery_menu")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _send_lottery_menu(message_or_callback_message: Message) -> None:
    if not ENABLE_LOTTERY:
        await message_or_callback_message.answer("⛔ Лотерея временно отключена.")
        return
    async with async_session() as session:
        round_obj = await ensure_current_lottery_round(session)
        state_data = get_lottery_state_dict(round_obj)
    base = (WEBHOOK_BASE or "").rstrip("/")
    live_url = f"{base}/lottery/live" if base else ""
    # UX: show both UTC and MSK (UTC+3) without timezone guessing
    try:
        start_utc = round_obj.draw_starts_at.strftime("%H:%M")
        end_utc = round_obj.draw_ends_at.strftime("%H:%M")
        start_msk = (round_obj.draw_starts_at + timedelta(hours=3)).strftime("%H:%M")
        end_msk = (round_obj.draw_ends_at + timedelta(hours=3)).strftime("%H:%M")
        draw_line = f"Розыгрыш: <b>воскресенье</b> {start_utc}–{end_utc} UTC ( {start_msk}–{end_msk} МСК )"
    except Exception:
        draw_line = "Розыгрыш: <b>воскресенье</b> (в live-режиме)"
    await message_or_callback_message.answer(
        "🎰 <b>Лотерея-лото</b>\n\n"
        f"Раунд: <b>{state_data.get('week_key')}</b>\n"
        f"Статус: <b>{state_data.get('status')}</b>\n"
        f"Цена билета: <b>{state_data.get('ticket_price')}</b> монет\n"
        f"Призовой фонд: <b>{state_data.get('prize_pool')}</b> монет\n"
        f"Уже выпало: {', '.join(map(str, state_data.get('drawn_numbers', []))) or '—'}\n\n"
        + (f"🔴 Live-ссылка: <a href=\"{live_url}\">{live_url}</a>\n" if live_url else "")
        + f"{draw_line}\n\n"
        "Нажмите «🔴 Открыть Live», чтобы посмотреть колесо/розыгрыш.",
        parse_mode="HTML",
        reply_markup=_lottery_menu_kb(),
    )


@router.message(F.text == BTN_LOTTERY)
async def btn_lottery(message: Message):
    await _send_lottery_menu(message)


@router.callback_query(F.data == "open_lottery")
async def open_lottery_from_games(callback: CallbackQuery):
    await _send_lottery_menu(callback.message)
    pass


@router.callback_query(F.data == "lottery_menu")
async def lottery_menu(callback: CallbackQuery):
    if not ENABLE_LOTTERY:
        await callback.answer("Лотерея отключена.", show_alert=True)
        return
    await _send_lottery_menu(callback.message)
    pass


@router.callback_query(F.data == "lottery_buy")
async def lottery_buy(callback: CallbackQuery):
    if not ENABLE_LOTTERY:
        await callback.answer("Лотерея отключена.", show_alert=True)
        return
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            pass
            return
        ticket, error = await buy_lottery_ticket(session, user)
        if error:
            await callback.answer(error, show_alert=True)
            return
        await callback.answer("Билет куплен!", show_alert=True)
        await callback.message.answer(
            f"🎫 Билет #{ticket.id} куплен\n"
            f"Ваши числа: <b>{ticket.numbers}</b>",
            parse_mode="HTML",
        )


@router.callback_query(F.data == "lottery_my_tickets")
async def lottery_my_tickets(callback: CallbackQuery):
    if not ENABLE_LOTTERY:
        await callback.answer("Лотерея отключена.", show_alert=True)
        return
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            pass
            return
        round_obj = await get_latest_lottery_round(session)
        tickets = await get_user_lottery_tickets(session, user.id, round_obj.id if round_obj else None, limit=20)
    if not tickets:
        await callback.message.answer("У вас пока нет билетов в текущем раунде.")
        pass
        return
    text = "📋 <b>Ваши билеты</b>\n\n"
    for t in tickets:
        text += f"#{t.id}: {t.numbers} | совпадений: {t.matched_count}\n"
    await callback.message.answer(text, parse_mode="HTML")
    pass


@router.callback_query(F.data == "lottery_live_info")
async def lottery_live_info(callback: CallbackQuery):
    base = (WEBHOOK_BASE or "").rstrip("/")
    live_url = f"{base}/lottery/live" if base else "/lottery/live"
    await callback.message.answer(
        "🔴 <b>Live-розыгрыш</b>\n\n"
        f"Ссылка: {live_url}",
        parse_mode="HTML",
    )
    pass


# =========================
# ЖАЛОБЫ И ПРЕДЛОЖЕНИЯ
# =========================
@router.message(F.text == BTN_FEEDBACK)
async def feedback_start(message: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐞 Сообщить о баге", callback_data="feedback_kind:bug")],
        [InlineKeyboardButton(text="💡 Предложить идею", callback_data="feedback_kind:suggestion")],
        [InlineKeyboardButton(text="❤️ Поблагодарить команду", callback_data="feedback_kind:praise")],
    ])
    await message.answer(
        "💬 <b>Жалобы и предложения</b>\n\n"
        "Напишите нам бесплатно: о баге, идее или просто поддержке.\n"
        "Мы читаем все обращения.",
        parse_mode="HTML",
        reply_markup=kb,
    )
    await state.clear()


@router.callback_query(F.data.startswith("feedback_kind:"))
async def feedback_pick_kind(callback: CallbackQuery, state: FSMContext):
    kind = callback.data.split(":", 1)[1]
    kind_title = {
        "bug": "Баг",
        "suggestion": "Идея",
        "praise": "Благодарность",
    }.get(kind)
    if not kind_title:
        await callback.answer("Неизвестный тип обращения.", show_alert=True)
        return
    await state.set_state(FeedbackState.waiting_text)
    await state.update_data(feedback_kind=kind)
    await callback.message.answer(
        f"✍️ Тип: <b>{kind_title}</b>\n\n"
        "Опишите ваше сообщение одним текстом (5-2000 символов).",
        parse_mode="HTML",
    )
    pass


@router.message(FeedbackState.waiting_text)
async def feedback_submit(message: Message, state: FSMContext):
    text_value = (message.text or "").strip()
    if len(text_value) < 5:
        await message.answer("Сообщение слишком короткое. Минимум 5 символов.")
        return
    if len(text_value) > 2000:
        await message.answer("Сообщение слишком длинное. Максимум 2000 символов.")
        return

    data = await state.get_data()
    kind = data.get("feedback_kind", "suggestion")
    kind_title = {
        "bug": "Баг",
        "suggestion": "Идея",
        "praise": "Благодарность",
    }.get(kind, kind)

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await state.clear()
            return
        feedback = await create_feedback(session, user.id, kind, text_value)
        author_name = get_display_name(user)

    for admin_tg in ADMINS:
        try:
            await message.bot.send_message(
                admin_tg,
                (
                    "💬 <b>Новое обращение пользователя</b>\n\n"
                    f"Тип: <b>{kind_title}</b>\n"
                    f"Обращение: <code>#{feedback.id}</code>\n"
                    f"Пользователь: {author_name}\n"
                    f"TG ID: <code>{message.from_user.id}</code>\n\n"
                    f"{text_value}"
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    await message.answer(
        "✅ Спасибо! Ваше обращение отправлено команде.\n"
        "Если нужно, мы свяжемся с вами в Telegram."
    )
    await state.clear()


# =========================
# ПРОМОКОДЫ (НОВЫЙ РАЗДЕЛ)
# =========================
@router.message(F.text == BTN_PROMO)
async def btn_promo(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if not await require_nickname(message, user):
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎟 Создать промокод", callback_data="promo_create")],
            [InlineKeyboardButton(text="🔑 Активировать промокод", callback_data="promo_activate")],
            [InlineKeyboardButton(text="📋 Мои промокоды", callback_data="promo_my")],
        ])
        await message.answer(
            "🎟 <b>Промокоды</b>\n\n"
            "Создайте код на монеты и поделитесь с друзьями!\n"
            f"Стоимость создания: {PROMOCODE_CREATION_STAR_RATE} Stars за 1 монету × использования.\n"
            f"VIP: {VIP_FREE_PROMO_PER_MONTH} бесплатный код в месяц.",
            parse_mode="HTML",
            reply_markup=kb
        )


@router.callback_query(F.data == "promo_create")
async def promo_create_start(callback: CallbackQuery, state: FSMContext):
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            pass
            return
        await state.set_state(PromoCreateState.waiting_amount)
        await callback.message.answer(
            f"Введите сумму монет (1–{PROMOCODE_MAX_AMOUNT}):"
        )
    pass


@router.message(PromoCreateState.waiting_amount)
async def promo_amount(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("Введите число.")
        return
    amount = int(message.text)
    if amount < 1 or amount > PROMOCODE_MAX_AMOUNT:
        await message.answer(f"От 1 до {PROMOCODE_MAX_AMOUNT}.")
        return
    await state.update_data(promo_amount=amount)
    await state.set_state(PromoCreateState.waiting_uses)
    await message.answer(f"Количество использований (1–{PROMOCODE_MAX_USES}):")


@router.message(PromoCreateState.waiting_uses)
async def promo_uses(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("Введите число.")
        return
    uses = int(message.text)
    if uses < 1 or uses > PROMOCODE_MAX_USES:
        await message.answer(f"От 1 до {PROMOCODE_MAX_USES}.")
        return
    await state.update_data(promo_uses=uses)
    await state.set_state(PromoCreateState.waiting_hours)
    await message.answer(f"Срок действия в часах (1–{PROMOCODE_MAX_HOURS}):")


@router.message(PromoCreateState.waiting_hours)
async def promo_hours(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("Введите число.")
        return
    hours = int(message.text)
    if hours < 1 or hours > PROMOCODE_MAX_HOURS:
        await message.answer(f"От 1 до {PROMOCODE_MAX_HOURS}.")
        return
    data = await state.get_data()
    amount = data["promo_amount"]
    uses = data["promo_uses"]
    star_cost = calculate_promocode_star_cost(to_decimal(amount), uses)

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await state.clear()
            return
        admin_free = is_admin_or_super(message.from_user.id, user)
        if admin_free:
            promo, _, error = await create_promocode(session, message.from_user.id,
                                                      to_decimal(amount), uses, hours,
                                                      admin_free=True)
            if error:
                await message.answer(error)
            else:
                await message.answer(
                    f"✅ Промокод создан (админ-режим):\n"
                    f"<code>{promo.code}</code>\n"
                    f"Сумма: {amount} монет, использований: {uses}/{promo.max_uses}\n"
                    f"Ссылка: t.me/{(await message.bot.get_me()).username}?start=promo_{promo.code}",
                    parse_mode="HTML"
                )
            await state.clear()
            return

        # VIP бесплатный
        if is_vip(user) and user.promo_created_this_month < VIP_FREE_PROMO_PER_MONTH:
            promo, cost, error = await create_promocode(session, message.from_user.id,
                                                         to_decimal(amount), uses, hours)
            if error:
                await message.answer(error)
            else:
                await message.answer(
                    f"✅ Бесплатный VIP-промокод:\n"
                    f"<code>{promo.code}</code>\n"
                    f"Сумма: {amount} монет, использований: {uses}\n"
                    f"Осталось бесплатных в этом месяце: {VIP_FREE_PROMO_PER_MONTH - user.promo_created_this_month}",
                    parse_mode="HTML"
                )
            await state.clear()
            return

        # Платный – выставляем инвойс
        payload = f"promo_{message.from_user.id}_{amount}_{uses}_{hours}_{uuid.uuid4().hex[:4]}"
        await ensure_payment_pending(
            session,
            user_id=user.id,
            payload=payload,
            stars_amount=star_cost,
        )
        await session.commit()
        await message.answer_invoice(
            title="Создание промокода",
            description=f"{amount} монет × {uses} исп. на {hours}ч",
            payload=payload,
            currency="XTR",
            prices=[LabeledPrice(label="Промокод", amount=star_cost)]
        )
    await state.clear()


@router.callback_query(F.data == "promo_activate")
async def promo_activate_start(callback: CallbackQuery, state: FSMContext):
    if not ENABLE_PROMOCODES:
        await callback.answer("⛔ Промокоды временно отключены.", show_alert=True)
        return
    await state.set_state(PromoActivateState.waiting_code)
    await callback.message.answer("Введите промокод:")
    pass


@router.message(PromoActivateState.waiting_code)
async def promo_activate_code(message: Message, state: FSMContext):
    if not ENABLE_PROMOCODES:
        await message.answer("⛔ Промокоды временно отключены.")
        await state.clear()
        return
    if not _cooldown_ok(
        _promo_activate_last_ts,
        message.from_user.id,
        PROMO_ACTIVATE_COOLDOWN_SECONDS,
    ):
        await message.answer("⏳ Слишком часто. Попробуйте чуть позже.")
        return
    code = (message.text or "").strip()
    if not code:
        await message.answer("Введите промокод.")
        return
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await state.clear()
            return
        result = await activate_promocode(session, user.id, code)
        await message.answer(result)
    await state.clear()


@router.callback_query(F.data == "promo_my")
async def promo_my(callback: CallbackQuery):
    if not ENABLE_PROMOCODES:
        await callback.answer("⛔ Промокоды временно отключены.", show_alert=True)
        return
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            pass
            return
        promos = (await session.execute(
            select(Promocode).where(Promocode.creator_user_id == user.id)
            .order_by(desc(Promocode.created_at)).limit(10)
        )).scalars().all()
        if not promos:
            await callback.message.answer("У вас пока нет промокодов.")
            pass
            return
        text = "🎟 <b>Ваши промокоды:</b>\n\n"
        for p in promos:
            status = "✅" if p.is_active else "❌"
            text += (
                f"{status} <code>{p.code}</code>\n"
                f"Сумма: {p.coin_amount} | Исп: {p.used_count}/{p.max_uses}\n"
                f"До: {p.expires_at.strftime('%d.%m %H:%M') if p.expires_at else '∞'}\n\n"
            )
        await callback.message.answer(text, parse_mode="HTML")
    pass


@router.message(Command("health"))
async def cmd_health(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        admin_flag = is_admin_or_super(message.from_user.id, user)
    if not admin_flag:
        return
    await message.answer(
        "✅ Health OK\n"
        f"• time_utc: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}\n"
        "• db: connected\n"
        "• bot: running",
    )


@router.message(Command("selfcheck"))
async def cmd_selfcheck(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        admin_flag = is_admin_or_super(message.from_user.id, user)
        if not admin_flag:
            return
        items = await run_selfcheck(session)
    await message.answer(format_selfcheck_report(items))


@router.message(F.text == "🎰 Игровые автоматы")
async def play_slots(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        bet = Decimal("10.0")
        if user.balance < bet:
            await message.answer("Недостаточно монет для игры (нужно 10 🪙).")
            return
        
        user.balance -= bet
        await session.commit()
        
        msg = await message.answer_dice(emoji="🎰")
        val = msg.dice.value
        
        # 1 - bar, 22 - grape, 43 - lemon, 64 - seven
        reward = Decimal("0")
        if val == 64:
            reward = Decimal("500.0")
        elif val == 43:
            reward = Decimal("100.0")
        elif val == 22:
            reward = Decimal("50.0")
        elif val == 1:
            reward = Decimal("30.0")
        
        if reward > 0:
            user.balance += reward
            await log_balance_change(session, user, reward, "slots_win")
            await session.commit()
            await asyncio.sleep(2)
            await message.answer(f"🎉 ДЖЕКПОТ! Вы выиграли {reward} 🪙!")
        else:
            await log_balance_change(session, user, -bet, "slots_loss")
            await session.commit()

@router.message(F.text == "🏀 Баскетбол")
async def play_basketball(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        bet = Decimal("10.0")
        if user.balance < bet:
            await message.answer("Недостаточно монет для игры (нужно 10 🪙).")
            return
        
        user.balance -= bet
        msg = await message.answer_dice(emoji="🏀")
        val = msg.dice.value
        
        reward = Decimal("0")
        if val >= 4:
            reward = Decimal("25.0")
        
        if reward > 0:
            user.balance += reward
            await log_balance_change(session, user, reward, "basketball_win")
            await session.commit()
            await asyncio.sleep(2)
            await message.answer(f"🏀 ГОООЛ! Вы выиграли {reward} 🪙!")
        else:
            await log_balance_change(session, user, -bet, "basketball_loss")
            await session.commit()

@router.message(F.text == "🎯 Дартс")
async def play_darts(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        bet = Decimal("10.0")
        if user.balance < bet:
            await message.answer("Недостаточно монет для игры (нужно 10 🪙).")
            return
        
        user.balance -= bet
        msg = await message.answer_dice(emoji="🎯")
        val = msg.dice.value
        
        reward = Decimal("0")
        if val == 6:
            reward = Decimal("50.0")
        elif val == 5:
            reward = Decimal("20.0")
        
        if reward > 0:
            user.balance += reward
            await log_balance_change(session, user, reward, "darts_win")
            await session.commit()
            await asyncio.sleep(2)
            await message.answer(f"🎯 Точно в цель! Вы выиграли {reward} 🪙!")
        else:
            await log_balance_change(session, user, -bet, "darts_loss")
            await session.commit()
