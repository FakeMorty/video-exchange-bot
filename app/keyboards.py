from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)
from app.config import STARS_PACKAGES

BTN_WATCH = "\U0001f3a5 \u0421\u043c\u043e\u0442\u0440\u0435\u0442\u044c"
BTN_UPLOAD = "\U0001f4e4 \u0417\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c"
BTN_PROFILE = "\U0001f464 \u041f\u0440\u043e\u0444\u0438\u043b\u044c"
BTN_BUY = "\U0001f4b3 \u041a\u0443\u043f\u0438\u0442\u044c \u043c\u043e\u043d\u0435\u0442\u044b"
BTN_OFFERS = "\U0001f381 \u041e\u0444\u0444\u0435\u0440\u044b"
BTN_REFERRALS = "\U0001f465 \u041f\u0440\u0438\u0433\u043b\u0430\u0441\u0438\u0442\u044c \u0434\u0440\u0443\u0433\u0430"
BTN_BONUS = "\U0001f3c6 \u0411\u043e\u043d\u0443\u0441"
BTN_ADMIN = "\U0001f6e0 \u0410\u0434\u043c\u0438\u043d"


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=BTN_WATCH), KeyboardButton(text=BTN_UPLOAD)],
        [KeyboardButton(text=BTN_PROFILE), KeyboardButton(text=BTN_BONUS)],
        [KeyboardButton(text=BTN_BUY), KeyboardButton(text=BTN_OFFERS)],
        [KeyboardButton(text=BTN_REFERRALS)],
    ]
    if is_admin:
        rows.append([KeyboardButton(text=BTN_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def rules_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u2705 \u041f\u0440\u0438\u043d\u0438\u043c\u0430\u044e", callback_data="accept_rules")],
    ])


def watch_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001f3ac \u0412\u0438\u0434\u0435\u043e", callback_data="watch_video_content")],
        [InlineKeyboardButton(text="\U0001f5bc \u0424\u043e\u0442\u043e", callback_data="watch_photo_content")],
    ])


def video_rating_keyboard(video_id: int) -> InlineKeyboardMarkup:
    stars = []
    for i in range(1, 6):
        stars.append(InlineKeyboardButton(text=f"{i}\u2b50", callback_data=f"rate:{video_id}:{i}"))
    return InlineKeyboardMarkup(inline_keyboard=[
        stars,
        [InlineKeyboardButton(text="\u25b6\ufe0f \u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0435\u0435", callback_data="watch_next")],
    ])


def photo_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001f5bc \u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0435\u0435 \u0444\u043e\u0442\u043e", callback_data="watch_next_photo")],
    ])


def buy_coins_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for key, pkg in STARS_PACKAGES.items():
        buttons.append([InlineKeyboardButton(
            text=f"\u2b50 {pkg['stars']} Stars \u2192 {pkg['coins']} \u043c\u043e\u043d\u0435\u0442",
            callback_data=f"buy:{key}",
        )])
    buttons.append([InlineKeyboardButton(text="\U0001f4dd \u0421\u0432\u043e\u044f \u0441\u0443\u043c\u043c\u0430", callback_data="buy_custom")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def offers_list_keyboard(offers) -> InlineKeyboardMarkup:
    buttons = []
    for o in offers:
        icon = "\U0001f7e2" if o.is_active else "\U0001f534"
        buttons.append([InlineKeyboardButton(text=f"{icon} {o.title}", callback_data=f"offer_open:{o.id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def offer_view_keyboard(offer_id: int, channel_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001f517 \u041f\u0435\u0440\u0435\u0439\u0442\u0438 \u0432 \u043a\u0430\u043d\u0430\u043b", url=channel_url)],
        [InlineKeyboardButton(text="\u2705 \u041d\u0430\u0447\u0430\u0442\u044c", callback_data=f"offer_start:{offer_id}")],
        [InlineKeyboardButton(text="\U0001f50d \u041f\u0440\u043e\u0432\u0435\u0440\u0438\u0442\u044c", callback_data=f"offer_check:{offer_id}")],
    ])


# ===== ADMIN =====

def admin_center_keyboard(is_super_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="\U0001f4ca \u041e\u0447\u0435\u0440\u0435\u0434\u044c", callback_data="admin_queue_info")],
        [InlineKeyboardButton(text="\U0001f4cb \u041c\u043e\u0434\u0435\u0440\u0430\u0446\u0438\u044f", callback_data="admin_get_pending")],
        [InlineKeyboardButton(text="\u2705 \u041e\u0434\u043e\u0431\u0440\u0438\u0442\u044c \u0432\u0441\u0451", callback_data="admin_approve_all")],
        [InlineKeyboardButton(text="\U0001f381 \u041e\u0444\u0444\u0435\u0440\u044b", callback_data="admin_offers_menu")],
    ]
    if is_super_admin:
        buttons.append([InlineKeyboardButton(text="\U0001f451 \u0423\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435 \u0430\u0434\u043c\u0438\u043d\u0430\u043c\u0438", callback_data="admin_manage_admins")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def moderation_keyboard(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="\u2705 \u041e\u0434\u043e\u0431\u0440\u0438\u0442\u044c", callback_data=f"mod_approve:{video_id}"),
            InlineKeyboardButton(text="\u274c \u041e\u0442\u043a\u043b\u043e\u043d\u0438\u0442\u044c", callback_data=f"mod_reject:{video_id}"),
        ],
        [InlineKeyboardButton(text="\u23ed \u041f\u0440\u043e\u043f\u0443\u0441\u0442\u0438\u0442\u044c", callback_data="admin_get_pending")],
    ])


def rejection_reason_keyboard(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001f503 \u0414\u0443\u0431\u043b\u0438\u043a\u0430\u0442", callback_data=f"reject_reason:{video_id}:duplicate")],
        [InlineKeyboardButton(text="\U0001f6ab \u041d\u0435 \u043f\u043e \u0442\u0435\u043c\u0430\u0442\u0438\u043a\u0435", callback_data=f"reject_reason:{video_id}:off_topic")],
        [InlineKeyboardButton(text="\u2753 \u0414\u0440\u0443\u0433\u043e\u0435", callback_data=f"reject_reason:{video_id}:other")],
    ])


def admin_after_action_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u25b6\ufe0f \u0421\u043b\u0435\u0434\u0443\u044e\u0449\u0438\u0439", callback_data="admin_get_pending")],
        [InlineKeyboardButton(text="\U0001f519 \u0410\u0434\u043c\u0438\u043d-\u0446\u0435\u043d\u0442\u0440", callback_data="admin_center")],
    ])


def admin_offers_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\u2795 \u0421\u043e\u0437\u0434\u0430\u0442\u044c", callback_data="admin_offer_create")],
        [InlineKeyboardButton(text="\U0001f4cb \u0421\u043f\u0438\u0441\u043e\u043a", callback_data="admin_offer_list")],
        [InlineKeyboardButton(text="\U0001f519 \u041d\u0430\u0437\u0430\u0434", callback_data="admin_center")],
    ])


def admin_offer_list_keyboard(offers) -> InlineKeyboardMarkup:
    buttons = []
    for o in offers:
        icon = "\U0001f7e2" if o.is_active else "\U0001f534"
        buttons.append([InlineKeyboardButton(text=f"{icon} {o.title}", callback_data=f"admin_offer_toggle:{o.id}")])
    buttons.append([InlineKeyboardButton(text="\U0001f519 \u041d\u0430\u0437\u0430\u0434", callback_data="admin_offers_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_manage_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001f4cb \u0421\u043f\u0438\u0441\u043e\u043a", callback_data="admm_list")],
        [InlineKeyboardButton(text="\u2795 \u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c", callback_data="admm_add")],
        [InlineKeyboardButton(text="\u2796 \u0423\u0434\u0430\u043b\u0438\u0442\u044c", callback_data="admm_remove")],
        [InlineKeyboardButton(text="\U0001f519 \u041d\u0430\u0437\u0430\u0434", callback_data="admin_center")],
    ])


def back_to_admin_manage_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="\U0001f519 \u041d\u0430\u0437\u0430\u0434", callback_data="admin_manage_admins")],
    ])
