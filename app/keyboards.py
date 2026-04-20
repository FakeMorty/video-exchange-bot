from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# Buttons
BTN_WATCH = "📺 Смотреть"
BTN_UPLOAD = "📤 Загрузить"
BTN_PROFILE = "👤 Профиль"
BTN_BUY = "💰 Купить"
BTN_OFFERS = "🎁 Офферы"
BTN_REFERRALS = "👥 Рефералы"
BTN_BONUS = "🎁 Бонус"
BTN_ADMIN = "🛠 Админ"
BTN_GAMES = "🎮 Игры"
BTN_TOPS = "🏆 Топы"
BTN_QUESTS = "📜 Квесты"
BTN_VIP = "💎 VIP"
BTN_LEVEL = "📈 Уровень"

def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text=BTN_WATCH), KeyboardButton(text=BTN_UPLOAD)],
        [KeyboardButton(text=BTN_PROFILE), KeyboardButton(text=BTN_GAMES)],
        [KeyboardButton(text=BTN_OFFERS), KeyboardButton(text=BTN_BUY)],
        [KeyboardButton(text=BTN_REFERRALS), KeyboardButton(text=BTN_BONUS)],
        [KeyboardButton(text=BTN_QUESTS), KeyboardButton(text=BTN_TOPS)],
        [KeyboardButton(text=BTN_LEVEL), KeyboardButton(text=BTN_VIP)],
    ]
    if is_admin:
        kb.append([KeyboardButton(text=BTN_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def admin_center_keyboard(is_super_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📊 Очередь", callback_data="admin_queue_info")],
        [InlineKeyboardButton(text="📊 Статистика+", callback_data="admin_extended_stats")],
        [InlineKeyboardButton(text="👤 Управление пользователями", callback_data="admin_manage_users")],
        [InlineKeyboardButton(text="📋 Модерация", callback_data="admin_get_pending")],
        [InlineKeyboardButton(text="✅ Одобрить всё", callback_data="admin_approve_all")],
        [InlineKeyboardButton(text="🎁 Офферы", callback_data="admin_offers_menu")],
    ]
    if is_super_admin:
        buttons.append([InlineKeyboardButton(text="👑 Управление админами", callback_data="admin_manage_admins")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def moderation_keyboard(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"mod_approve:{video_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"mod_reject:{video_id}"),
        ],
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data="admin_get_pending")],
    ])

def rejection_reason_keyboard(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Дубликат", callback_data=f"reject_reason:{video_id}:duplicate")],
        [InlineKeyboardButton(text="🚫 Не по тематике", callback_data=f"reject_reason:{video_id}:off_topic")],
        [InlineKeyboardButton(text="❓ Другое", callback_data=f"reject_reason:{video_id}:other")],
    ])

def admin_after_action_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Следующий", callback_data="admin_get_pending")],
        [InlineKeyboardButton(text="🔙 Админ-центр", callback_data="admin_center")],
    ])

def offer_view_keyboard(offer_id: int, channel_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Перейти в канал", url=channel_url)],
        [InlineKeyboardButton(text="✅ Начать", callback_data=f"offer_start:{offer_id}")],
        [InlineKeyboardButton(text="🔍 Проверить", callback_data=f"offer_check:{offer_id}")],
    ])

def games_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Кости", callback_data="game_dice")],
        [InlineKeyboardButton(text="🪙 Монетка", callback_data="game_coinflip")],
        [InlineKeyboardButton(text="🔢 Угадай число", callback_data="game_guess")],
    ])

def tops_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Топ загрузчиков", callback_data="top_uploaders")],
        [InlineKeyboardButton(text="👀 Топ зрителей", callback_data="top_viewers")],
        [InlineKeyboardButton(text="📈 Топ по XP", callback_data="top_levels")],
        [InlineKeyboardButton(text="💰 Топ богачей", callback_data="top_richest")],
    ])

def watch_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Видео", callback_data="watch_video_content")],
        [InlineKeyboardButton(text="🖼 Фото", callback_data="watch_photo_content")],
    ])

def video_rating_keyboard(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐ 1", callback_data=f"rate:{video_id}:1"),
            InlineKeyboardButton(text="⭐ 2", callback_data=f"rate:{video_id}:2"),
            InlineKeyboardButton(text="⭐ 3", callback_data=f"rate:{video_id}:3"),
            InlineKeyboardButton(text="⭐ 4", callback_data=f"rate:{video_id}:4"),
            InlineKeyboardButton(text="⭐ 5", callback_data=f"rate:{video_id}:5"),
        ],
        [InlineKeyboardButton(text="💬 Комменты", callback_data=f"comments:{video_id}")],
        [InlineKeyboardButton(text="⏭ Следующее", callback_data="watch_next")],
    ])

def photo_actions_keyboard(photo_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Следующее фото", callback_data="watch_next_photo")],
    ])

def rules_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принимаю правила", callback_data="accept_rules")],
    ])

def buy_coins_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐️ 10 монет (5 Stars)", callback_data="buy:pack_5")],
        [InlineKeyboardButton(text="⭐️ 20 монет (10 Stars)", callback_data="buy:pack_10")],
        [InlineKeyboardButton(text="⭐️ 50 монет (25 Stars)", callback_data="buy:pack_25")],
        [InlineKeyboardButton(text="⭐️ 100 монет (50 Stars)", callback_data="buy:pack_50")],
        [InlineKeyboardButton(text="📝 Своя сумма", callback_data="buy_custom")],
    ])

def vip_buy_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Купить VIP", callback_data="buy_vip")],
    ])

def offers_list_keyboard(offers) -> InlineKeyboardMarkup:
    buttons = []
    for o in offers:
        icon = "🟢" if o.is_active else "🔴"
        buttons.append([InlineKeyboardButton(text=f"{icon} {o.title}", callback_data=f"offer_open:{o.id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def quests_keyboard(quests) -> InlineKeyboardMarkup:
    buttons = []
    for q in quests:
        status = "✅" if q.completed else "⏳"
        buttons.append([InlineKeyboardButton(text=f"{status} {q.quest_type}: {q.progress}/{q.target}", callback_data=f"quest_claim:{q.id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def reaction_menu_keyboard(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔥", callback_data=f"react:{video_id}:🔥"),
            InlineKeyboardButton(text="❤️", callback_data=f"react:{video_id}:❤️"),
            InlineKeyboardButton(text="😂", callback_data=f"react:{video_id}:😂"),
            InlineKeyboardButton(text="👍", callback_data=f"react:{video_id}:👍"),
            InlineKeyboardButton(text="💯", callback_data=f"react:{video_id}:💯"),
        ]
    ])
