from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

BTN_WATCH = "🎥 Смотреть"
BTN_UPLOAD = "📤 Загрузить"
BTN_PROFILE = "👤 Профиль"
BTN_BUY = "💎 Купить монеты"
BTN_OFFERS = "🎁 Офферы"
BTN_REFERRALS = "👥 Рефералы"
BTN_BONUS = "🏆 Ежедневный бонус"
BTN_ADMIN = "🛠 Админ-центр"


def rules_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Принимаю правила", callback_data="accept_rules")]
        ]
    )


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text=BTN_WATCH), KeyboardButton(text=BTN_UPLOAD)],
        [KeyboardButton(text=BTN_PROFILE), KeyboardButton(text=BTN_BONUS)],
        [KeyboardButton(text=BTN_BUY), KeyboardButton(text=BTN_OFFERS)],
        [KeyboardButton(text=BTN_REFERRALS)],
    ]

    if is_admin:
        keyboard.append([KeyboardButton(text=BTN_ADMIN)])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


def video_rating_keyboard(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👍", callback_data=f"rate:{video_id}:1"),
                InlineKeyboardButton(text="👎", callback_data=f"rate:{video_id}:-1"),
                InlineKeyboardButton(text="▶ Следующее", callback_data="watch_next"),
            ]
        ]
    )


def admin_center_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Взять видео на модерацию", callback_data="admin_get_pending")],
            [InlineKeyboardButton(text="📊 Статус очереди", callback_data="admin_queue_info")],
        ]
    )


def moderation_keyboard(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"mod_approve:{video_id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"mod_reject:{video_id}"),
            ],
            [
                InlineKeyboardButton(text="📋 Следующее видео", callback_data="admin_get_pending"),
            ],
        ]
    )


def rejection_reason_keyboard(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Дубликат", callback_data=f"reject_reason:{video_id}:duplicate")],
            [InlineKeyboardButton(text="Не по тематике", callback_data=f"reject_reason:{video_id}:off_topic")],
            [InlineKeyboardButton(text="Другое", callback_data=f"reject_reason:{video_id}:other")],
        ]
    )


def admin_after_action_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Следующее видео", callback_data="admin_get_pending")],
            [InlineKeyboardButton(text="🏠 Админ-центр", callback_data="admin_center")],
        ]
    )