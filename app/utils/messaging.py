"""
Безопасные утилиты для работы с сообщениями.
"""
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramBadRequest


async def safe_edit_text(
    callback: CallbackQuery,
    text: str,
    parse_mode: str = "HTML",
    reply_markup=None
):
    """Безопасное редактирование сообщения."""
    try:
        await callback.message.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
    except TelegramBadRequest:
        # Если не получилось отредактировать — отправляем новое
        await callback.message.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)
    await callback.answer()
