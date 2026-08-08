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
BTN_ADMIN      = "🔧 Админка"
BTN_GAMES      = "🎮 Игры"
BTN_TOPS       = "🏆 Топы"
BTN_VIP        = "👑 VIP"
BTN_LEVEL      = "📊 Уровень"
BTN_PROMO      = "🎟 Промокоды"
BTN_FEEDBACK   = "💬 Жалобы и предложения"
BTN_LOTTERY    = "🎰 Секслото"
BTN_LOOTBOXES  = "🎁 Лутбоксы"
BTN_ARCADE     = "🚀 Космическая аркада"
BTN_AI         = "💋 ИИ-Общение"
BTN_RULES      = "📜 Правила"
BTN_FAQ        = "ℹ️ FAQ / Помощь"


# =========================
# ГЛАВНОЕ МЕНЮ (ReplyKeyboard)
# =========================
def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text=BTN_WATCH), KeyboardButton(text=BTN_AI)],
        [KeyboardButton(text=BTN_UPLOAD), KeyboardButton(text=BTN_PROFILE)],
        [KeyboardButton(text=BTN_BUY), KeyboardButton(text=BTN_PROMO)],
        [KeyboardButton(text=BTN_OFFERS), KeyboardButton(text=BTN_REFERRALS)],
        [KeyboardButton(text=BTN_GAMES), KeyboardButton(text=BTN_TOPS)],
        [KeyboardButton(text=BTN_FEEDBACK)],
        [KeyboardButton(text=BTN_VIP), KeyboardButton(text=BTN_LEVEL)],
        [KeyboardButton(text=BTN_RULES), KeyboardButton(text=BTN_FAQ)],
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
        [InlineKeyboardButton(text="✅ Одобрить всё", callback_data="admin_approve_all")],
        [InlineKeyboardButton(text="📈 Статистика бота", callback_data="admin_extended_stats")],
        [InlineKeyboardButton(text="💳 Управление DonationAlerts", callback_data="admin_da_menu")],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_manage_users")],
        [InlineKeyboardButton(text="⚡ Авто-модерация (доверенные)", callback_data="admin_auto_moderation")],
        [InlineKeyboardButton(text="🤝 Доверенные авторы", callback_data="admin_trusted_uploaders")],
        [InlineKeyboardButton(text="📢 Офферы и реклама", callback_data="admin_offers_menu")],
        [InlineKeyboardButton(text="📨 Сообщение всем от админа", callback_data="admin_direct_message_all")],
        [InlineKeyboardButton(text="📣 Промо-рассылки", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="🎉 События", callback_data="admin_events_menu")],
        [InlineKeyboardButton(text="🛍 Акции и скидки", callback_data="admin_sales")],
        [InlineKeyboardButton(text="🚨 Жалобы", callback_data="admin_reports")],
        [InlineKeyboardButton(text="💬 Обращения пользователей", callback_data="admin_feedback_menu")],
        [InlineKeyboardButton(text="🔧 Настройки бота", callback_data="admin_bot_settings")],
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
        [InlineKeyboardButton(text="📜 Не соответствует правилам", callback_data=f"reject_reason:{video_id}:rules_violation")],
        [InlineKeyboardButton(text="⚠️ Шок-контент", callback_data=f"reject_reason:{video_id}:shock_content")],
        [InlineKeyboardButton(text="❓ Другое", callback_data=f"reject_reason:{video_id}:other")],
    ])


# =========================
# ПОЛЬЗОВАТЕЛЬСКИЕ КЛАВИАТУРЫ (Inline)
# =========================
def rules_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Полные правила", callback_data="show_full_rules")],
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
        [
            InlineKeyboardButton(text="😀 Реакции", callback_data=f"reactions:{video_id}"),
            InlineKeyboardButton(text="🚨 Жалоба", callback_data=f"report_video:{video_id}"),
        ],
        [InlineKeyboardButton(text="🚫 Заблокировать автора", callback_data=f"block_author:{video_id}")],
        [InlineKeyboardButton(text="📝 Следующее", callback_data="watch_next")],
    ])


def photo_actions_keyboard(photo_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="😀 Реакции", callback_data=f"reactions:{photo_id}")],
        [
            InlineKeyboardButton(text="🚨 Жалоба", callback_data=f"report_video:{photo_id}"),
            InlineKeyboardButton(text="🚫 Блок автора", callback_data=f"block_author:{photo_id}"),
        ],
        [InlineKeyboardButton(text="📝 Следующее фото", callback_data="watch_next_photo")],
    ])


# =========================
# КЛАВИАТУРЫ-ВЫХОД ДЛЯ ОШИБОК ПОКАЗА КОНТЕНТА
# (всегда дают возможность продолжить: бракованное видео ≠ следующее бракованное)
# =========================
def video_error_keyboard() -> InlineKeyboardMarkup:
    """Выход при ошибке показа видео.

    Одно нерабочее видео не означает, что следующих нет — поэтому всегда
    даём кнопку «Смотреть дальше», плюс запасной переход к фото.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Смотреть дальше", callback_data="watch_next")],
        [InlineKeyboardButton(text="🖼 Перейти к фото", callback_data="watch_photo_content")],
    ])


def photo_error_keyboard() -> InlineKeyboardMarkup:
    """Выход при ошибке показа фото: всегда можно попробовать следующее или уйти к видео."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Смотреть дальше", callback_data="watch_next_photo")],
        [InlineKeyboardButton(text="🎬 Перейти к видео", callback_data="watch_video_content")],
    ])


def photo_limit_reached_keyboard() -> InlineKeyboardMarkup:
    """Выход при достижении дневного лимита фото: показываем альтернативу (видео без лимита)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Смотреть видео", callback_data="watch_video_content")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="dismiss_low_balance_hint")],
    ])


def offers_list_keyboard(offers) -> InlineKeyboardMarkup:
    """Создаёт клавиатуру со списком офферов"""
    buttons = []
    for offer in offers[:10]:  # Ограничиваем 10 офферами
        buttons.append([
            InlineKeyboardButton(
                text=f"📢 {offer.title[:40]}",
                callback_data=f"offer_open:{offer.id}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="btn_offers_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def offer_view_keyboard(offer_id: int, channel_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Перейти в канал", url=channel_url)],
        [InlineKeyboardButton(text="▶️ Начать", callback_data=f"offer_start:{offer_id}")],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data=f"offer_check:{offer_id}")],
        [InlineKeyboardButton(text="📣 Арендовать слот", callback_data=f"rent_offer:{offer_id}")],
    ])


def rent_days_keyboard(offer_id: int) -> InlineKeyboardMarkup:
    """Быстрый выбор срока аренды рекламного слота."""
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
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"rent_offer:{offer_id}")],
    ])


def games_menu_keyboard() -> InlineKeyboardMarkup:
    from app.config import WEBHOOK_BASE
    base = (WEBHOOK_BASE or "").rstrip("/")
    cases_url = f"{base}/cases" if base else ""
    
    kb = []
    if cases_url:
        from aiogram.types.web_app_info import WebAppInfo
        kb.append([InlineKeyboardButton(text="🎁 Кейсы (Mini App)", web_app=WebAppInfo(url=cases_url))])
        
    kb.extend([
        [InlineKeyboardButton(text=BTN_ARCADE, callback_data="arcade_menu")],
        [InlineKeyboardButton(text=BTN_LOOTBOXES, callback_data="lootbox_menu")],
        [InlineKeyboardButton(text=BTN_LOTTERY, callback_data="open_lottery")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def tops_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Топ загрузчиков", callback_data="top_uploaders")],
        [InlineKeyboardButton(text="👁 Топ зрителей", callback_data="top_viewers")],
        [InlineKeyboardButton(text="⭐ Топ по XP", callback_data="top_levels")],
        [InlineKeyboardButton(text="💰 Топ богатых", callback_data="top_richest")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="btn_main_menu")],
    ])


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
        [InlineKeyboardButton(text="⚡ Пополнить и смотреть дальше", callback_data="btn_buy")],
        [InlineKeyboardButton(text="💰 Перейти к офферам", callback_data="offers_participation")],
        [InlineKeyboardButton(text="👥 Открыть рефералку", callback_data="low_balance_referrals")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="dismiss_low_balance_hint")],
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


def buy_coins_keyboard(packs: dict = None, user_id: int | None = None) -> InlineKeyboardMarkup:
    from app.config import DONATION_ALERTS_URL
    buttons = [
        [InlineKeyboardButton(text="💳 Перейти к оплате (DonationAlerts)", url=DONATION_ALERTS_URL)],
    ]
    if user_id:
        buttons.append([InlineKeyboardButton(text=f"📋 Скопировать мой ID: {user_id}", callback_data=f"copy_id:{user_id}")])
    buttons.append([InlineKeyboardButton(text="🔄 Проверить зачисление", callback_data="da_check_payment")])
    buttons.append([InlineKeyboardButton(text="🌐 Другие способы / Telegram Stars (дороже)", callback_data="show_stars_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def vip_buy_keyboard(price: int = 450, user_id: int | None = None) -> InlineKeyboardMarkup:
    from app.config import DONATION_ALERTS_URL
    buttons = [
        [InlineKeyboardButton(text="💳 Купить VIP за 150 руб. (DonationAlerts)", url=DONATION_ALERTS_URL)],
    ]
    if user_id:
        buttons.append([InlineKeyboardButton(text=f"📋 Скопировать: {user_id} vip", callback_data=f"copy_id:{user_id}_vip")])
    buttons.append([InlineKeyboardButton(text="🔄 Проверить зачисление", callback_data="da_check_payment")])
    buttons.append([InlineKeyboardButton(text=f"🌐 Резерв: Оформить за {price} Stars", callback_data="buy_vip_stars")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)