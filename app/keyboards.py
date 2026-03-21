from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

BTN_WATCH = "\U0001f3a5 \u0421\u043c\u043e\u0442\u0440\u0435\u0442\u044c"
BTN_UPLOAD = "\U0001f4e4 \u0417\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c"
BTN_PROFILE = "\U0001f464 \u041f\u0440\u043e\u0444\u0438\u043b\u044c"
BTN_BUY = "\U0001f48e \u041a\u0443\u043f\u0438\u0442\u044c \u043c\u043e\u043d\u0435\u0442\u044b"
BTN_OFFERS = "\U0001f381 \u041e\u0444\u0444\u0435\u0440\u044b"
BTN_REFERRALS = "\U0001f465 \u0420\u0435\u0444\u0435\u0440\u0430\u043b\u044b"
BTN_BONUS = "\U0001f3c6 \u0415\u0436\u0435\u0434\u043d\u0435\u0432\u043d\u044b\u0439 \u0431\u043e\u043d\u0443\u0441"
BTN_ADMIN = "\U0001f6e0 \u0410\u0434\u043c\u0438\u043d-\u0446\u0435\u043d\u0442\u0440"


def rules_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u2705 \u041f\u0440\u0438\u043d\u0438\u043c\u0430\u044e \u043f\u0440\u0430\u0432\u0438\u043b\u0430", callback_data="accept_rules")]
    ])


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
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="\U0001f44d", callback_data=f"rate:{video_id}:1"),
            InlineKeyboardButton(text="\U0001f44e", callback_data=f"rate:{video_id}:-1"),
            InlineKeyboardButton(text="\u25b6 \u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0435\u0435", callback_data="watch_next"),
        ]
    ])


def buy_coins_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="50 монет — 50 ⭐", callback_data="buy:stars_50")],
        [InlineKeyboardButton(text="120 монет — 100 ⭐", callback_data="buy:stars_120")],
        [InlineKeyboardButton(text="350 монет — 250 ⭐", callback_data="buy:stars_350")],
    ])


def admin_center_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001f4cb \u0412\u0437\u044f\u0442\u044c \u0432\u0438\u0434\u0435\u043e \u043d\u0430 \u043c\u043e\u0434\u0435\u0440\u0430\u0446\u0438\u044e", callback_data="admin_get_pending")],
        [InlineKeyboardButton(text="\U0001f4ca \u0421\u0442\u0430\u0442\u0443\u0441 \u043e\u0447\u0435\u0440\u0435\u0434\u0438", callback_data="admin_queue_info")],
    ])


def moderation_keyboard(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="\u2705 \u041e\u0434\u043e\u0431\u0440\u0438\u0442\u044c", callback_data=f"mod_approve:{video_id}"),
            InlineKeyboardButton(text="\u274c \u041e\u0442\u043a\u043b\u043e\u043d\u0438\u0442\u044c", callback_data=f"mod_reject:{video_id}"),
        ],
        [
            InlineKeyboardButton(text="\U0001f4cb \u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0435\u0435 \u0432\u0438\u0434\u0435\u043e", callback_data="admin_get_pending"),
        ]
    ])


def rejection_reason_keyboard(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u0414\u0443\u0431\u043b\u0438\u043a\u0430\u0442", callback_data=f"reject_reason:{video_id}:duplicate")],
        [InlineKeyboardButton(text="\u041d\u0435 \u043f\u043e \u0442\u0435\u043c\u0430\u0442\u0438\u043a\u0435", callback_data=f"reject_reason:{video_id}:off_topic")],
        [InlineKeyboardButton(text="\u0414\u0440\u0443\u0433\u043e\u0435", callback_data=f"reject_reason:{video_id}:other")],
    ])


def admin_after_action_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001f4cb \u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0435\u0435 \u0432\u0438\u0434\u0435\u043e", callback_data="admin_get_pending")],
        [InlineKeyboardButton(text="\U0001f3e0 \u0410\u0434\u043c\u0438\u043d-\u0446\u0435\u043d\u0442\u0440", callback_data="admin_center")],
    ])
