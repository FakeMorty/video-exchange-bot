from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)


def rules_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принимаю правила", callback_data="accept_rules")]
    ])


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎥 Смотреть"), KeyboardButton(text="📤 Загрузить")],
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="💎 Купить монеты")],
            [KeyboardButton(text="🎁 Офферы"), KeyboardButton(text="👥 Рефералы")],
        ],
        resize_keyboard=True,
    )


def video_rating_keyboard(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👍", callback_data=f"rate:{video_id}:1"),
            InlineKeyboardButton(text="👎", callback_data=f"rate:{video_id}:-1"),
            InlineKeyboardButton(text="▶ Следующее", callback_data="watch_next"),
        ]
    ])


def moderation_keyboard(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"mod_approve:{video_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"mod_reject:{video_id}"),
        ]
    ])


def rejection_reason_keyboard(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Дубликат", callback_data=f"reject_reason:{video_id}:дубликат")],
        [InlineKeyboardButton(text="Не по тематике", callback_data=f"reject_reason:{video_id}:не по тематике")],
        [InlineKeyboardButton(text="Другое", callback_data=f"reject_reason:{video_id}:другое")],
    ])
