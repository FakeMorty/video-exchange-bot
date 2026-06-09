import random
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    KeyboardButton, ReplyKeyboardMarkup
)

# =========================
# ТЕКСТОВЫЕ КНОПКИ ГЛАВНОГО МЕНЮ
# =========================
BTN_WATCH      = "🎬 Смотреть"
BTN_UPLOAD     = "📤 Загрузить"
BTN_PROFILE    = "👤 Профиль"
BTN_BUY        = "💳 Купить монеты"
BTN_OFFERS     = "📢 Офферы"
BTN_REFERRALS  = "👥 Рефералы"
BTN_BONUS      = "🎁 Бонус"
BTN_ADMIN      = "🔧 Админка"
BTN_GAMES      = "🎮 Игры"
BTN_TOPS       = "🏆 Топы"
BTN_QUESTS     = "📋 Квесты"
BTN_VIP        = "👑 VIP"
BTN_LEVEL      = "📊 Уровень"
BTN_PROMO      = "🎟 Промокоды"
BTN_FEEDBACK   = "💬 Жалобы и предложения"
BTN_LOTTERY    = "🎰 Лотерея-лото"
BTN_LOOTBOXES  = "🎁 Лутбоксы"


# =========================
# ГЛАВНОЕ МЕНЮ (ReplyKeyboard)
# =========================
def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text=BTN_WATCH)],
        [KeyboardButton(text=BTN_UPLOAD), KeyboardButton(text=BTN_PROFILE)],
        [KeyboardButton(text=BTN_BUY), KeyboardButton(text=BTN_PROMO)],
        [KeyboardButton(text=BTN_OFFERS), KeyboardButton(text=BTN_REFERRALS)],
        [KeyboardButton(text=BTN_GAMES), KeyboardButton(text=BTN_BONUS)],
        [KeyboardButton(text=BTN_QUESTS), KeyboardButton(text=BTN_TOPS)],
        [KeyboardButton(text=BTN_VIP), KeyboardButton(text=BTN_LEVEL)],
        [KeyboardButton(text=BTN_FEEDBACK)],
    ]
    if is_admin:
        kb.append([KeyboardButton(text=BTN_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


# =========================
# АДМИН-КЛАВИАТУРЫ (Inline)
# =========================
def admin_main_keyboard(is_super: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📊 Очередь модерации", callback_data="admin_queue_info")],
        [InlineKeyboardButton(text="📈 Статистика бота", callback_data="admin_extended_stats")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_manage_users")],
        [InlineKeyboardButton(text="📝 Модерация контента", callback_data="admin_get_pending")],
        [InlineKeyboardButton(text="⚡ Авто-модерация (доверенные)", callback_data="admin_auto_moderation")],
        [InlineKeyboardButton(text="🤝 Доверенные авторы", callback_data="admin_trusted_uploaders")],
        [InlineKeyboardButton(text="📢 Офферы и реклама", callback_data="admin_offers_menu")],
        [InlineKeyboardButton(text="💬 Обращения пользователей", callback_data="admin_feedback_menu")],
        [InlineKeyboardButton(text="🕵️ Расследование", callback_data="admin_investigation")],
    ]
    if is_super:
        buttons.append([
            InlineKeyboardButton(
                text="🗄 База данных",
                callback_data="admin_db_menu"
            )
        ])
        buttons.append([
            InlineKeyboardButton(
                text="👑 Управление админами",
                callback_data="admin_manage_admins"
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_after_action_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Следующее", callback_data="admin_get_pending")],
        [InlineKeyboardButton(text="🔙 Админ-центр", callback_data="admin_center")],
    ])


# =========================
# КЛАВИАТУРЫ МОДЕРАЦИИ
# =========================
def moderation_keyboard(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"mod_approve:{video_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"mod_reject:{video_id}"),
        ],
        [InlineKeyboardButton(text="📝 Следующее", callback_data="admin_get_pending")],
    ])


def rejection_reason_keyboard(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Дубликат", callback_data=f"reject_reason:{video_id}:duplicate")],
        [InlineKeyboardButton(text="🚫 Не по теме", callback_data=f"reject_reason:{video_id}:off_topic")],
        [InlineKeyboardButton(text="🔞 Запрещёнка", callback_data=f"reject_reason:{video_id}:forbidden")],
        [InlineKeyboardButton(text="❓ Другое", callback_data=f"reject_reason:{video_id}:other")],
    ])


# =========================
# ПОЛЬЗОВАТЕЛЬСКИЕ КЛАВИАТУРЫ (Inline)
# =========================
def rules_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принимаю правила", callback_data="accept_rules")],
    ])


def watch_choice_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Видео", callback_data="watch_video_content")],
        [InlineKeyboardButton(text="🖼 Фото", callback_data="watch_photo_content")],
    ])


def video_rating_keyboard(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1", callback_data=f"rate:{video_id}:1"),
            InlineKeyboardButton(text="2", callback_data=f"rate:{video_id}:2"),
            InlineKeyboardButton(text="3", callback_data=f"rate:{video_id}:3"),
            InlineKeyboardButton(text="4", callback_data=f"rate:{video_id}:4"),
            InlineKeyboardButton(text="5", callback_data=f"rate:{video_id}:5"),
        ],
        [InlineKeyboardButton(text="💬 Комментарии", callback_data=f"comments:{video_id}")],
        [InlineKeyboardButton(text="😀 Реакции", callback_data=f"reactions:{video_id}")],
        [InlineKeyboardButton(text="📝 Следующее", callback_data="watch_next")],
    ])


def photo_actions_keyboard(photo_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="😀 Реакции", callback_data=f"reactions:{photo_id}")],
        [InlineKeyboardButton(text="📝 Следующее фото", callback_data="watch_next_photo")],
    ])





def offer_view_keyboard(offer_id: int, channel_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Перейти в канал", url=channel_url)],
        [InlineKeyboardButton(text="▶️ Начать", callback_data=f"offer_start:{offer_id}")],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data=f"offer_check:{offer_id}")],
        [InlineKeyboardButton(text="📣 Арендовать слот", callback_data=f"rent_offer:{offer_id}")],
    ])


def offer_rent_keyboard(offer_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📣 Арендовать слот", callback_data=f"rent_offer:{offer_id}")],
        [InlineKeyboardButton(text="🔙 К офферам", callback_data="back_to_offers")],
    ])


def rent_days_keyboard(offer_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1 день", callback_data=f"rent_days:{offer_id}:1"),
            InlineKeyboardButton(text="3 дня", callback_data=f"rent_days:{offer_id}:3"),
        ],
        [
            InlineKeyboardButton(text="7 дней", callback_data=f"rent_days:{offer_id}:7"),
            InlineKeyboardButton(text="14 дней", callback_data=f"rent_days:{offer_id}:14"),
        ],
        [InlineKeyboardButton(text="30 дней", callback_data=f"rent_days:{offer_id}:30")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"offer_open:{offer_id}")],
    ])


# =========================
# ИГРЫ
# =========================
def games_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Кости (PvP)", callback_data="dice_menu")],
        [InlineKeyboardButton(text="🎰 Угадай число", callback_data="guess_menu")],
        [InlineKeyboardButton(text=BTN_LOOTBOXES, callback_data="lootbox_menu")],
        [InlineKeyboardButton(text=BTN_LOTTERY, callback_data="open_lottery")],
    ])






# =========================
# ТОПЫ
# =========================
def tops_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Топ загрузчиков", callback_data="top_uploaders")],
        [InlineKeyboardButton(text="👁 Топ зрителей", callback_data="top_viewers")],
        [InlineKeyboardButton(text="⭐ Топ по XP", callback_data="top_levels")],
        [InlineKeyboardButton(text="💰 Топ богатых", callback_data="top_richest")],
    ])


# =========================
# КВЕСТЫ
# =========================
def quests_keyboard(quests: list) -> InlineKeyboardMarkup:
    buttons = []
    for q in quests:
        if q.completed and not q.reward_claimed:
            buttons.append([InlineKeyboardButton(
                text=f"🎁 Получить награду: {q.quest_type} ({q.reward} монет)",
                callback_data=f"quest_claim:{q.id}"
            )])
        elif q.completed:
            buttons.append([InlineKeyboardButton(
                text=f"✅ {q.quest_type}: {q.progress}/{q.target} — Выполнено",
                callback_data=f"quest_done:{q.id}"
            )])
        else:
            buttons.append([InlineKeyboardButton(
                text=f"⏳ {q.quest_type}: {q.progress}/{q.target}",
                callback_data=f"quest_info:{q.id}"
            )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def reaction_menu_keyboard(video_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👍", callback_data=f"react:{video_id}:👍"),
            InlineKeyboardButton(text="❤", callback_data=f"react:{video_id}:❤"),
            InlineKeyboardButton(text="🔥", callback_data=f"react:{video_id}:🔥"),
            InlineKeyboardButton(text="😁", callback_data=f"react:{video_id}:😁"),
            InlineKeyboardButton(text="😢", callback_data=f"react:{video_id}:😢"),
        ]
    ])


# =========================
# УМНАЯ РЕКЛАМА (forced offer / low balance)
# =========================
def forced_offer_keyboard(offer_id: int, channel_url: str, seconds: int = 5) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="📢 Перейти в канал (реклама)",
            url=channel_url
        )],
        [InlineKeyboardButton(
            text=f"⏳ Ждём {seconds} сек...",
            callback_data="forced_offer_wait"
        )],
    ])


def forced_offer_done_keyboard(offer_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Продолжить",
            callback_data=f"forced_offer_continue:{offer_id}"
        )],
    ])


def low_balance_offer_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💰 Перейти к офферам",
            callback_data="offers_participation"
        )],
        [InlineKeyboardButton(
            text="❌ Закрыть",
            callback_data="dismiss_low_balance_hint"
        )],
    ])


# =========================
# АДМИНСКАЯ БД (только для super-admin)
# =========================
def admin_db_keyboard(tables) -> InlineKeyboardMarkup:
    """
    tables can be:
      - list[str]
      - list[tuple[str, str]] where (table_name, label)
    """
    kb = []
    for t in tables:
        if isinstance(t, (tuple, list)) and len(t) == 2:
            table_name, label = t[0], t[1]
        else:
            table_name, label = t, str(t)
        kb.append([InlineKeyboardButton(text=f"📋 {label}", callback_data=f"db_open:{table_name}:0")])
    kb.append([InlineKeyboardButton(text="🔙 Админ-центр", callback_data="admin_center")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def captcha_keyboard(target_emoji: str) -> InlineKeyboardMarkup:
    emojis = ["🍎", "🍐", "🍊", "🍋", "🍌", "🍉", "🍇", "🍓", "🫐", "🍈", "🍒", "🍑", "🥭", "🍍", "🥥", "🥝", "🍅", "🍆", "🥑"]
    options = random.sample([e for e in emojis if e != target_emoji], 5)
    options.append(target_emoji)
    random.shuffle(options)
    
    buttons = []
    for em in options:
        cb_data = "captcha_pass" if em == target_emoji else f"captcha_fail:{em}"
        buttons.append(InlineKeyboardButton(text=em, callback_data=cb_data))
        
    return InlineKeyboardMarkup(inline_keyboard=[buttons[:3], buttons[3:]])


def buy_coins_keyboard(packs: dict) -> InlineKeyboardMarkup:
    buttons = []
    for p_id, p_data in packs.items():
        buttons.append([InlineKeyboardButton(text=f"💎 {p_data['coins']} монет ({p_data['stars']} Stars)", callback_data=f"buy_{p_id}")])
    buttons.append([InlineKeyboardButton(text="⚡ Своя сумма Stars", callback_data="buy_custom")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def vip_buy_keyboard(price: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⭐️ Купить за {price} Stars", callback_data="buy_vip")]
    ])
