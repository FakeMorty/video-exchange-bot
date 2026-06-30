from app.models import utc_now
"""
Донатный магазин — покупка привилегий за монеты.
Включает FSM-флоу для выбора кастомного стиля ника из 50 вариантов.
"""

from datetime import datetime, timezone
from decimal import Decimal
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.db import async_session
from app.services import (
    get_user, log_balance_change, log_user_action,
    activate_perk, has_active_perk, get_active_perks, deactivate_perk,
    get_display_name,
    is_admin_free_eligible,
)
from app.nick_styles import (
    CATEGORIES, STYLES, STYLES_BY_CAT,
    format_nick_inline, format_nick_card,
    validate_style_id, style_label,
)

router = Router()


# ════════════════════════════════════════════════
#  FSM
# ════════════════════════════════════════════════

class CustomNickState(StatesGroup):
    picking_category = State()
    browsing_styles  = State()
    confirming       = State()


# Пагинация стилей внутри категории
_STYLES_PER_PAGE = 10


# ════════════════════════════════════════════════
#  Товары магазина (custom_nick заменяет color/gold)
# ════════════════════════════════════════════════

DONATION_ITEMS = [
    {
        "id": "custom_nick",
        "name": "🎨 Кастомный ник",
        "price": 500,
        "description": "Выбери из 50 уникальных стилей оформления ника — он будет выделяться везде в боте",
        "duration_days": 30,
    },
    {
        "id": "coin_multiplier",
        "name": "💰 Бустер монет x1.5",
        "price": 600,
        "description": "Получаешь на 50% больше монет за просмотры и квесты",
        "duration_days": 7,
    },
    {
        "id": "xp_multiplier",
        "name": "📈 Бустер XP x2",
        "price": 500,
        "description": "Получаешь в 2 раза больше XP за все действия",
        "duration_days": 7,
    },
    {
        "id": "stars_discount",
        "name": "⭐ Скидка 25% на Stars",
        "price": 1000,
        "description": "Все покупки за Stars стоят на 25% дешевле",
        "duration_days": 30,
    },
    {
        "id": "priority_moderation",
        "name": "⚡ Приоритетная модерация",
        "price": 300,
        "description": "Твои видео проверяют в первую очередь",
        "duration_days": 14,
    },
    {
        "id": "exclusive_reactions",
        "name": "✨ Эксклюзивные реакции",
        "price": 400,
        "description": "Доступ к уникальным реакциям (💎, 🔥, 👑 и др.)",
        "duration_days": 30,
    },
]


# ════════════════════════════════════════════════
#  Клавиатуры
# ════════════════════════════════════════════════

def donation_shop_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for item in DONATION_ITEMS:
        label = f"{item['name']} — {item['price']:,} 🪙".replace(',', ' ')
        buttons.append([
            InlineKeyboardButton(text=label, callback_data=f"donate_buy:{item['id']}")
        ])
    buttons.append([InlineKeyboardButton(text="📋 Мои привилегии", callback_data="donate_my_perks")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="btn_profile")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _category_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for cat_id, (icon, name) in CATEGORIES.items():
        rows.append([InlineKeyboardButton(
            text=f"{icon} {name}",
            callback_data=f"cn_cat:{cat_id}",
        )])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="donation_shop")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _styles_keyboard(cat_id: int, user_name: str, page: int = 0) -> InlineKeyboardMarkup:
    """Клавиатура со стилями одной категории (пагинация по 10)."""
    rows = []
    styles = STYLES_BY_CAT.get(cat_id, [])
    start = page * _STYLES_PER_PAGE
    end = start + _STYLES_PER_PAGE
    page_styles = styles[start:end]

    for s in page_styles:
        preview = format_nick_inline(user_name, s.id)
        rows.append([InlineKeyboardButton(
            text=preview,
            callback_data=f"cn_style:{s.id}",
        )])

    # Навигация
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"cn_page:{cat_id}:{page-1}"))
    if end < len(styles):
        nav.append(InlineKeyboardButton(text="➡️ Ещё", callback_data=f"cn_page:{cat_id}:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="◀️ К категориям", callback_data="cn_back_cats")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="donation_shop")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _confirm_keyboard(style_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Выбрать", callback_data=f"cn_confirm:{style_id}"),
            InlineKeyboardButton(text="❌ Назад", callback_data=f"cn_back_styles:{STYLES[style_id].cat_id}"),
        ],
    ])


# ════════════════════════════════════════════════
#  Главный магазин
# ════════════════════════════════════════════════

@router.callback_query(F.data == "donation_shop")
async def show_donation_shop(callback: CallbackQuery):
    text = (
        "🛍 <b>Магазин привилегий</b>\n\n"
        "Здесь ты можешь приобрести крутые привилегии за монеты.\n"
        "Все цены указаны в монетах.\n\n"
        "Выбери, что хочешь купить:"
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=donation_shop_keyboard())
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=donation_shop_keyboard())
    await callback.answer()


# ════════════════════════════════════════════════
#  Покупка НЕ-никовых перков (бустеры и т.п.)
# ════════════════════════════════════════════════

@router.callback_query(F.data.startswith("donate_buy:"))
async def donate_buy(callback: CallbackQuery, state: FSMContext):
    item_id = callback.data.split(":")[1]

    # custom_nick — отдельный флоу
    if item_id == "custom_nick":
        await _start_custom_nick_flow(callback, state)
        return

    item = next((i for i in DONATION_ITEMS if i["id"] == item_id), None)
    if not item:
        await callback.answer("Товар не найден", show_alert=True)
        return

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return

        admin_free = await is_admin_free_eligible(session, callback.from_user.id, user)
        has_perk = await has_active_perk(session, user.id, item["id"])
        extra_info = ""
        if has_perk:
            extra_info = "\n⚠️ У тебя уже активна эта привилегия!\nПокупка <b>продлит</b> действие."

        if not admin_free and user.balance < item["price"]:
            await callback.answer(
                f"❌ Недостаточно монет. Нужно: {item['price']:,}".replace(',', ' '),
                show_alert=True,
            )
            return

        if admin_free:
            price_line = f"💰 Цена: <b>{item['price']:,} монет</b> <i>(🆓 бесплатно для админа)</i>\n".replace(',', ' ')
            balance_line = f"💳 Твой баланс: {user.balance:,.0f}".replace(',', ' ')
        else:
            price_line = f"💰 Цена: <b>{item['price']:,} монет</b>\n".replace(',', ' ')
            balance_line = f"💳 Твой баланс: {user.balance:,.0f} → {user.balance - item['price']:,.0f}".replace(',', ' ')

        text = (
            f"🛍 <b>Покупка: {item['name']}</b>\n\n"
            f"{item['description']}\n\n"
            f"{price_line}"
            f"⏳ Длительность: <b>{item['duration_days']} дней</b>\n"
            f"{balance_line}" +
            extra_info
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Купить", callback_data=f"donate_confirm:{item_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="donation_shop"),
            ]
        ])

        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await state.update_data(selected_item=item_id)
        await callback.answer()


@router.callback_query(F.data.startswith("donate_confirm:"))
async def donate_confirm(callback: CallbackQuery, state: FSMContext):
    item_id = callback.data.split(":")[1]

    # custom_nick — подтверждение через свой флоу
    if item_id == "custom_nick":
        return

    item = next((i for i in DONATION_ITEMS if i["id"] == item_id), None)
    if not item:
        await callback.answer("Ошибка", show_alert=True)
        return

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return

        admin_free = await is_admin_free_eligible(session, callback.from_user.id, user)
        if not admin_free and user.balance < item["price"]:
            await callback.answer("Недостаточно монет", show_alert=True)
            return

        if admin_free:
            await change_balance_atomic(session, user.id, Decimal("0"), "donation_purchase_admin_free",
                                         details=f"{item['name']} (ADMIN_FREE)")
        else:
            await change_balance_atomic(session, user.id, -item["price"], "donation_purchase",
                                         details=item["name"])
            # user.balance -= item["price"] # Handled by change_balance_atomic

        perk = await activate_perk(session, user.id, item["id"], item["duration_days"])
        expires = perk.active_until

        await log_user_action(session, user.id, "perk_activated",
                              f"{item['name']} до {expires.strftime('%d.%m')}")
        await session.commit()

        await state.clear()

        free_badge = "\n🆓 <b>(Бесплатно для админа)</b>" if admin_free else ""
        await callback.message.edit_text(
            f"✅ <b>Покупка успешна!</b>{free_badge}\n\n"
            f"Вы приобрели: <b>{item['name']}</b>\n"
            f"Действует до: <b>{expires.strftime('%d.%m.%Y %H:%M')}</b>\n\n"
            f"Спасибо за поддержку! 💙",
            parse_mode="HTML",
        )
        await callback.answer("Привилегия активирована!", show_alert=True)


# ════════════════════════════════════════════════
#  КАСТОМНЫЙ НИК — FSM ФЛОУ
# ════════════════════════════════════════════════

async def _start_custom_nick_flow(callback: CallbackQuery, state: FSMContext):
    """Шаг 1: показать выбор категории."""
    await state.set_state(CustomNickState.picking_category)

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return

        has_existing = await has_active_perk(session, user.id, "custom_nick")
        renew_note = ""
        if has_existing:
            renew_note = (
                "\n⚠️ У тебя уже есть кастомный ник. "
                "Покупка <b>продлит</b> его и даст возможность <b>выбрать новый стиль</b>.\n"
            )

        admin_free = await is_admin_free_eligible(session, callback.from_user.id, user)

    price_note = "🆓 Бесплатно для админа" if admin_free else "💰 Цена: <b>500 монет</b>"

    text = (
        "🎨 <b>Кастомный ник</b>\n\n"
        f"{price_note}\n"
        f"⏳ Длительность: <b>30 дней</b>\n\n"
        "Выбери категорию стиля:\n"
        "Каждый стиль уникален и виден в профиле, топах и комментариях.\n"
        f"{renew_note}"
    )

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_category_keyboard())
    await callback.answer()


@router.callback_query(CustomNickState.picking_category, F.data.startswith("cn_cat:"))
async def _show_styles_in_category(callback: CallbackQuery, state: FSMContext):
    """Шаг 2: показать стили выбранной категории (первая страница)."""
    cat_id = int(callback.data.split(":")[1])
    if cat_id not in CATEGORIES:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    await state.set_state(CustomNickState.browsing_styles)
    await state.update_data(cat_id=cat_id)

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        user_name = get_display_name(user) if user else "Ник"

    icon, cat_name = CATEGORIES[cat_id]
    text = f"{icon} <b>{cat_name}</b>\n\nВыбери стиль (твой ник для предпросмотра):\n"

    await callback.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=_styles_keyboard(cat_id, user_name, page=0),
    )
    await callback.answer()


@router.callback_query(CustomNickState.browsing_styles, F.data.startswith("cn_page:"))
async def _styles_page(callback: CallbackQuery, state: FSMContext):
    """Пагинация внутри категории."""
    parts = callback.data.split(":")
    cat_id = int(parts[1])
    page = int(parts[2])

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        user_name = get_display_name(user) if user else "Ник"

    icon, cat_name = CATEGORIES[cat_id]
    total_pages = (len(STYLES_BY_CAT.get(cat_id, [])) + _STYLES_PER_PAGE - 1) // _STYLES_PER_PAGE
    text = f"{icon} <b>{cat_name}</b> (стр. {page+1}/{total_pages})\n\nВыбери стиль:\n"

    await callback.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=_styles_keyboard(cat_id, user_name, page=page),
    )
    await callback.answer()


@router.callback_query(CustomNickState.browsing_styles, F.data.startswith("cn_style:"))
async def _show_style_preview(callback: CallbackQuery, state: FSMContext):
    """Шаг 3: показать карточку-превью выбранного стиля."""
    style_id = int(callback.data.split(":")[1])
    if not validate_style_id(style_id):
        await callback.answer("Стиль не найден", show_alert=True)
        return

    await state.set_state(CustomNickState.confirming)
    await state.update_data(style_id=style_id)

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        user_name = get_display_name(user) if user else "Ник"

    s = STYLES[style_id]
    icon, cat_name = CATEGORIES[s.cat_id]

    inline_preview = format_nick_inline(user_name, style_id)
    card_preview = format_nick_card(user_name, style_id)

    text = (
        f"🎨 <b>Превью стиля «{s.label}»</b>\n"
        f"📂 {icon} {cat_name}\n\n"
        f"<b>В строке:</b>\n{inline_preview}\n\n"
        f"<b>В профиле:</b>\n{card_preview}\n\n"
        f"⚠️ После подтверждения стиль <b>нельзя изменить</b> без новой покупки.\n"
        f"Подтверждаешь выбор?"
    )

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_confirm_keyboard(style_id))
    await callback.answer()


@router.callback_query(CustomNickState.confirming, F.data.startswith("cn_confirm:"))
async def _confirm_custom_nick(callback: CallbackQuery, state: FSMContext):
    """Шаг 4: списать монеты, активировать перк со style_id."""
    style_id = int(callback.data.split(":")[1])
    if not validate_style_id(style_id):
        await callback.answer("Стиль не найден", show_alert=True)
        return

    PRICE = 500
    DURATION = 30

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return

        admin_free = await is_admin_free_eligible(session, callback.from_user.id, user)

        if not admin_free and user.balance < PRICE:
            await callback.answer(
                f"❌ Недостаточно монет. Нужно: {PRICE}",
                show_alert=True,
            )
            return

        # Деактивируем легаси-перки ника если есть
        for legacy_type in ("color_nick", "gold_nick"):
            if await has_active_perk(session, user.id, legacy_type):
                await deactivate_perk(session, user.id, legacy_type)

        # Списываем монеты
        if admin_free:
            await log_balance_change(session, user, Decimal("0"), "donation_purchase_admin_free",
                                     details=f"custom_nick style={style_id} (ADMIN_FREE)",
            )
        else:
            await change_balance_atomic(
                session, user.id, -PRICE, "donation_purchase",
                details=f"custom_nick style={style_id}",
            )

        # Активируем перк со style_id
        perk = await activate_perk(
            session, user.id, "custom_nick", DURATION, style_id=style_id,
        )
        expires = perk.active_until

        await log_user_action(
            session, user.id, "perk_activated",
            f"custom_nick style={style_id} ({STYLES[style_id].label}) до {expires.strftime('%d.%m')}",
        )
        await session.commit()

    await state.clear()

    # Финальное сообщение с рендером
    user_name = get_display_name(user)
    inline = format_nick_inline(user_name, style_id)
    card = format_nick_card(user_name, style_id)

    free_badge = "\n🆓 <b>(Бесплатно для админа)</b>" if admin_free else ""
    await callback.message.edit_text(
        f"✅ <b>Кастомный ник активирован!</b>{free_badge}\n\n"
        f"Стиль: <b>{STYLES[style_id].label}</b>\n"
        f"Действует до: <b>{expires.strftime('%d.%m.%Y %H:%M')}</b>\n\n"
        f"Твой ник теперь выглядит так:\n\n"
        f"В строке: {inline}\n\n"
        f"В профиле:\n{card}\n\n"
        f"Спасибо за поддержку! 💙",
        parse_mode="HTML",
    )
    await callback.answer("Стиль активирован!", show_alert=True)


# ── Навигация ──────────────────────────────────

@router.callback_query(CustomNickState.picking_category, F.data == "cn_back_cats")
async def _back_to_categories(callback: CallbackQuery, state: FSMContext):
    await _start_custom_nick_flow(callback, state)


@router.callback_query(CustomNickState.browsing_styles, F.data == "cn_back_cats")
async def _back_to_categories_from_styles(callback: CallbackQuery, state: FSMContext):
    await _start_custom_nick_flow(callback, state)


@router.callback_query(CustomNickState.confirming, F.data.startswith("cn_back_styles:"))
async def _back_to_styles(callback: CallbackQuery, state: FSMContext):
    cat_id = int(callback.data.split(":")[1])
    await state.set_state(CustomNickState.browsing_styles)
    await state.update_data(cat_id=cat_id)

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        user_name = get_display_name(user) if user else "Ник"

    icon, cat_name = CATEGORIES[cat_id]
    text = f"{icon} <b>{cat_name}</b>\n\nВыбери стиль (твой ник для предпросмотра):\n"

    await callback.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=_styles_keyboard(cat_id, user_name),
    )
    await callback.answer()


@router.callback_query(CustomNickState.picking_category, F.data == "donation_shop")
async def _cancel_from_cats(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_donation_shop(callback)


@router.callback_query(CustomNickState.browsing_styles, F.data == "donation_shop")
async def _cancel_from_styles(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_donation_shop(callback)


@router.callback_query(CustomNickState.confirming, F.data == "donation_shop")
async def _cancel_from_confirm(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_donation_shop(callback)


# ════════════════════════════════════════════════
#  МОИ ПЕРКИ
# ════════════════════════════════════════════════

@router.callback_query(F.data == "donate_my_perks")
async def donate_my_perks(callback: CallbackQuery):
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return

        perks = await get_active_perks(session, user.id)

        if not perks:
            text = "🎖 <b>Мои привилегии</b>\n\nУ тебя пока нет активных привилегий.\nЗагляни в магазин!"
        else:
            text = "🎖 <b>Мои привилегии</b>\n\n"
            for perk in perks:
                # Название перка
                if perk.perk_type == "custom_nick" and perk.style_id:
                    s = STYLES.get(perk.style_id)
                    name = f"🎨 Кастомный ник — «{s.label}»" if s else "🎨 Кастомный ник"
                else:
                    from app.services import PERK_ICONS, PERK_NAMES
                    icon = PERK_ICONS.get(perk.perk_type, "🔹")
                    name = PERK_NAMES.get(perk.perk_type, perk.perk_type)

                days_left = (perk.active_until - utc_now()).days
                text += f"{name}\n"
                text += f"   ⏰ Осталось: <b>{days_left} дн.</b> (до {perk.active_until.strftime('%d.%m')})\n\n"

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛍 В магазин", callback_data="donation_shop")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="btn_profile")],
        ])
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
        await callback.answer()

# =========================
# BACK BUTTON HANDLER
# =========================
@router.callback_query(F.data == "btn_profile")
async def back_to_profile(callback: CallbackQuery):
    # Simple back: show profile hint
    try:
        await callback.message.edit_text(
            "👤 Нажмите кнопку 👤 Профиль в главном меню, чтобы вернуться.",
            reply_markup=None
        )
    except Exception:
        await callback.message.answer("👤 Нажмите кнопку 👤 Профиль в главном меню.")
    await callback.answer()

