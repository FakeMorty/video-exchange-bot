"""
Безопасные утилиты для работы с сообщениями Telegram.
Предотвращают зависания при невозможности редактирования сообщений.
"""
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest


async def safe_edit(
    event: CallbackQuery | Message,
    text: str = None,
    caption: str = None,
    reply_markup: InlineKeyboardMarkup = None,
    parse_mode: str = "HTML"
) -> bool:
    """
    Безопасное редактирование сообщения.
    Возвращает True, если редактирование удалось, иначе False.
    """
    try:
        if isinstance(event, CallbackQuery):
            msg = event.message
        else:
            msg = event

        if caption is not None:
            await msg.edit_caption(caption=caption, reply_markup=reply_markup, parse_mode=parse_mode)
        elif text is not None:
            await msg.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
        elif reply_markup is not None:
            await msg.edit_reply_markup(reply_markup=reply_markup)
        return True

    except TelegramBadRequest:
        # Не удалось отредактировать — отправляем новое сообщение
        if isinstance(event, CallbackQuery):
            if caption:
                await event.message.answer(caption, parse_mode=parse_mode, reply_markup=reply_markup)
            elif text:
                await event.message.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)
        else:
            if caption:
                await event.answer(caption, parse_mode=parse_mode, reply_markup=reply_markup)
            elif text:
                await event.answer(text, parse_mode=parse_mode, reply_markup=reply_markup)
        return False


async def safe_answer(callback: CallbackQuery, text: str = "", show_alert: bool = False):
    """Безопасный ответ на callback."""
    try:
        await callback.answer(text, show_alert=show_alert)
    except Exception:
        pass
