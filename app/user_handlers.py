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
from app.keyboards import rules_keyboard, main_menu, video_rating_keyboard
from app.config import WATCH_COST

logger = logging.getLogger(__name__)
router = Router()

RULES_TEXT = (
    "⚠️ <b>Правила использования</b>\n\n"
    "1. Бот содержит контент 18+. Используя бот, вы подтверждаете, что вам есть 18 лет.\n"
    "2. Запрещено загружать контент с несовершеннолетними.\n"
    "3. Запрещён контент с насилием.\n"
    "4. Администрация оставляет за собой право заблокировать пользователя.\n\n"
    "Нажмите кнопку ниже, чтобы принять правила."
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
            f"С возвращением! Баланс: <b>{user.balance}</b> монет ���",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )


@router.callback_query(F.data == "accept_rules")
async def cb_accept_rules(callback: CallbackQuery):
    if not callback.from_user:
        return

    async with async_session() as session:
        user = await agree_to_rules(session, callback.from_user.id)

    await callback.message.edit_text("✅ Правила приняты!")
    await callback.message.answer(
        "Добро пожаловать! Ваш стартовый баланс: <b>2</b> монеты ���",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )
    await callback.answer()


@router.message(F.text == "��� Профиль")
async def show_profile(message: Message):
    if not message.from_user:
        return

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)

    if not user:
        await message.answer("Пользователь не найден. Нажмите /start")
        return

    text = (
        f"��� <b>Профиль</b>\n\n"
        f"��� Telegram ID: <code>{user.telegram_id}</code>\n"
        f"��� Баланс: <b>{user.balance}</b> монет\n"
        f"��� Реферальный код: <code>{user.referral_code}</code>\n"
        f"��� Статус: {user.status}"
    )
    await message.answer(text, parse_mode="HTML")


@router.message(F.text == "��� Загрузить")
async def upload_prompt(message: Message):
    await message.answer("Отправьте видео, которое хотите загрузить. ���")


@router.message(F.video)
async def handle_video_upload(message: Message):
    if not message.from_user or not message.video:
        return

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await message.answer("Пользователь не найден. Нажмите /start")
            return

        if not user.agreed_to_rules:
            await message.answer("Сначала примите правила: /start")
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
        await message.answer("⚠️ Это видео уже было загружено ранее (дубликат).")
    else:
        await message.answer(
            "✅ Видео загружено и отправлено на модерацию!\n"
            "Вы получите <b>0.5 монеты</b> после одобрения.",
            parse_mode="HTML",
        )


@router.message(F.text == "��� Смотреть")
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
            await message.answer("Пользователь не найден. Нажмите /start")
            return

        if user.balance < Decimal(str(WATCH_COST)):
            await message.answer(
                "❌ Недостаточно монет для просмотра.\n"
                "Загрузите видео или купите монеты!",
            )
            return

        video = await get_random_video_for_user(session, user)
        if not video:
            await message.answer("��� В базе больше нет новых видео для вас.")
            return

        charged = await record_view_and_charge(session, user, video)
        if not charged:
            await message.answer("❌ Недостаточно монет.")
            return

        new_balance = user.balance

    await message.answer_video(
        video=video.telegram_file_id,
        caption=f"��� Списана 1 монета. Баланс: <b>{new_balance}</b>",
        parse_mode="HTML",
        reply_markup=video_rating_keyboard(video.id),
    )


@router.callback_query(F.data.startswith("rate:"))
async def cb_rate_video(callback: CallbackQuery):
    if not callback.from_user:
        return

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

    emoji = "���" if rating == 1 else "���"
    await callback.answer(f"Вы оценили: {emoji}")


@router.message(F.text == "��� Купить монеты")
async def buy_coins_stub(message: Message):
    await message.answer("��� Покупка монет скоро будет доступна.")


@router.message(F.text == "��� Офферы")
async def offers_stub(message: Message):
    await message.answer("��� Рекламные офферы скоро появятся.")


@router.message(F.text == "��� Рефералы")
async def referrals_stub(message: Message):
    await message.answer("��� Реферальная система будет расширена в следующих обновлениях.")
