from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

BTN_WATCH = "\U0001f3a5 Watch"
BTN_UPLOAD = "\U0001f4e4 Upload"
BTN_PROFILE = "\U0001f464 Profile"
BTN_BUY = "\U0001f48e Buy coins"
BTN_OFFERS = "\U0001f381 Offers"
BTN_REFERRALS = "\U0001f465 Referrals"


def rules_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u2705 Accept rules", callback_data="accept_rules")]
    ])


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_WATCH), KeyboardButton(text=BTN_UPLOAD)],
            [KeyboardButton(text=BTN_PROFILE), KeyboardButton(text=BTN_BUY)],
            [KeyboardButton(text=BTN_OFFERS), KeyboardButton(text=BTN_REFERRALS)],
        ],
        resize_keyboard=True,
    )


def video_rating_keyboard(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="\U0001f44d", callback_data=f"rate:{video_id}:1"),
            InlineKeyboardButton(text="\U0001f44e", callback_data=f"rate:{video_id}:-1"),
            InlineKeyboardButton(text="\u25b6 Next", callback_data="watch_next"),
        ]
    ])


def moderation_keyboard(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="\u2705 Approve", callback_data=f"mod_approve:{video_id}"),
            InlineKeyboardButton(text="\u274c Reject", callback_data=f"mod_reject:{video_id}"),
        ]
    ])


def rejection_reason_keyboard(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Duplicate", callback_data=f"reject_reason:{video_id}:duplicate")],
        [InlineKeyboardButton(text="Off topic", callback_data=f"reject_reason:{video_id}:off_topic")],
        [InlineKeyboardButton(text="Other", callback_data=f"reject_reason:{video_id}:other")],
    ])
