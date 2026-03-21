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
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принимаю правила", callback_data="accept_rules")]
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
            InlineKeyboardButton(text="👍", callback_data=f"rate:{video_id}:1"),
            InlineKeyboardButton(text="👎", callback_data=f"rate:{video_id}:-1"),
            InlineKeyboardButton(text="▶ Следующее", callback_data="watch_next"),
        ]
    ])


def buy_coins_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="50 монет — 50 ⭐", callback_data="buy:stars_50")],
        [InlineKeyboardButton(text="120 монет — 100 ⭐", callback_data="buy:stars_120")],
        [InlineKeyboardButton(text="350 монет — 250 ⭐", callback_data="buy:stars_350")],
    ])


def offers_list_keyboard(offers: list) -> InlineKeyboardMarkup:
    keyboard = []
    for offer in offers:
        keyboard.append([
            InlineKeyboardButton(
                text=f"🎁 {offer.title}",
                callback_data=f"offer_open:{offer.id}"
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def offer_view_keyboard(offer_id: int, channel_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Перейти в канал", url=channel_url)],
        [InlineKeyboardButton(text="✅ Участвовать", callback_data=f"offer_start:{offer_id}")],
        [InlineKeyboardButton(text="🔄 Проверить подписку", callback_data=f"offer_check:{offer_id}")],
    ])


def admin_center_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Взять видео на модерацию", callback_data="admin_get_pending")],
        [InlineKeyboardButton(text="📊 Статус очереди", callback_data="admin_queue_info")],
        [InlineKeyboardButton(text="🎁 Управление офферами", callback_data="admin_offers_menu")],
    ])


def admin_offers_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать оффер", callback_data="admin_offer_create")],
        [InlineKeyboardButton(text="📋 Список офферов", callback_data="admin_offer_list")],
        [InlineKeyboardButton(text="🏠 Назад в админ-центр", callback_data="admin_center")],
    ])


def admin_offer_list_keyboard(offers: list) -> InlineKeyboardMarkup:
    keyboard = []
    for offer in offers:
        status = "🟢" if offer.is_active else "🔴"
        keyboard.append([
            InlineKeyboardButton(
                text=f"{status} {offer.title}",
                callback_data=f"admin_offer_toggle:{offer.id}"
            )
        ])

    keyboard.append([InlineKeyboardButton(text="🏠 Назад", callback_data="admin_offers_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def moderation_keyboard(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"mod_approve:{video_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"mod_reject:{video_id}"),
        ],
        [
            InlineKeyboardButton(text="📋 Следующее видео", callback_data="admin_get_pending"),
        ]
    ])


def rejection_reason_keyboard(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Дубликат", callback_data=f"reject_reason:{video_id}:duplicate")],
        [InlineKeyboardButton(text="Не по тематике", callback_data=f"reject_reason:{video_id}:off_topic")],
        [InlineKeyboardButton(text="Другое", callback_data=f"reject_reason:{video_id}:other")],
    ])


def admin_after_action_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Следующее видео", callback_data="admin_get_pending")],
        [InlineKeyboardButton(text="🏠 Админ-центр", callback_data="admin_center")],
    ])