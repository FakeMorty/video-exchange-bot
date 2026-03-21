import logging
import traceback
from decimal import Decimal

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery

from app.config import ADMINS, WATCH_COST
from app.db import async_session
from app.keyboards import (
    rules_keyboard, main_menu, video_rating_keyboard,
    BTN_WATCH, BTN_UPLOAD, BTN_PROFILE, BTN_BUY,
    BTN_OFFERS, BTN_REFERRALS, BTN_BONUS, BTN_ADMIN,
    admin_center_keyboard,
)
from app.services import (
    get_or_create_user, agree_to_rules, get_user,
    save_video, get_random_video_for_user, record_view_and_charge,
    rate_video, claim_daily_bonus,
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

            if not user.agreed_to_rules:
                await message.answer(RULES_TEXT, parse_mode="HTML", reply_markup=rules_keyboard())
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

        user_type = "Администратор" if is_admin(message.from_user.id) else "Пользователь"

        text = (
            f"👤 <b>Профиль</b>\n\n"
            f"🆔 Telegram ID: <code>{user.telegram_id}</code>\n"
            f"💰 Баланс: <b>{user.balance}</b> монет\n"
            f"🔗 Реферальный код: <code>{user.referral_code}</code>\n"
            f"📊 Статус: {user.status}\n"
            f"🛡 Роль: {user_type}"
        )
        await message.answer(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"[PROFILE] ERROR: {e}")
        logger.error(traceback.format_exc())
        await message.answer("Не удалось открыть профиль.")


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
                    "Загрузите видео, получите бонус или купите монеты."
                )
                return

            video = await get_random_video_for_user(session, user)
            if not video:
                await message.answer("📭 Для вас пока нет новых одобренных видео.")
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


@router.message(F.text == BTN_BUY)
async def buy_coins_stub(message: Message):
    await message.answer("💎 Покупка монет скоро будет доступна.")


@router.message(F.text == BTN_OFFERS)
async def offers_stub(message: Message):
    await message.answer("🎁 Рекламные офферы скоро появятся.")


@router.message(F.text == BTN_REFERRALS)
async def referrals_stub(message: Message):
    await message.answer("👥 Реферальная система будет расширена в следующих обновлениях.") 