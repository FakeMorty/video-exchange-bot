from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
import os

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from sqlalchemy import select, func, desc, text


from app.config import ADMINS, OFFER_DEFAULT_RENT_COST_PER_DAY, ENABLE_ADMIN_BROADCAST
from app.db import async_session
from app.models import (
    Base,
    User, Video, Offer, BalanceLog, GameHistory,
    TrustedUploader
)
from app.services import (
    get_user, get_user_by_id, get_user_by_username,
    get_user_dossier, update_user_balance, set_user_ban_status,
    count_pending_videos, count_approved_videos, count_rejected_videos,
    get_next_pending_video, approve_video, reject_video,
    get_admin_extended_stats, get_display_name,
    get_user_by_display_name, admin_create_offer,
    count_active_rentals, expire_old_rentals, log_user_action,
    get_recent_feedback,
)
from app.keyboards import (
    admin_main_keyboard, moderation_keyboard,
    rejection_reason_keyboard, admin_after_action_keyboard,
    admin_db_keyboard,
)

router = Router()


# =========================
# STATES
# =========================
class AdminUserState(StatesGroup):
    waiting_user_id = State()
    waiting_coins_amount = State()
    waiting_message_text = State()
    waiting_dossier_id = State()


class AdminManageState(StatesGroup):
    waiting_new_admin = State()
    waiting_remove_admin = State()


class AdminBroadcastState(StatesGroup):
    waiting_text = State()


class AdminNicknameState(StatesGroup):
    waiting_user_id = State()
    waiting_new_nick = State()


class AdminOfferCreateState(StatesGroup):
    waiting_title = State()
    waiting_description = State()
    waiting_url = State()
    waiting_reward_preview = State()
    waiting_reward_final = State()
    waiting_penalty_unsubscribe = State()
    waiting_rentable = State()
    waiting_rent_cost = State()
    waiting_max_rentals = State()


class TrustedUploaderState(StatesGroup):
    waiting_add = State()


# =========================
# HELPERS
from app.utils.admin import check_admin, is_super_admin, _safe_edit







# =========================
# ADMIN PANEL
# =========================
@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not await check_admin(message.from_user.id):
        return
    sa = is_super_admin(message.from_user.id)
    await message.answer(
        "⚙️ <b>Панель администратора</b>\n\nВыберите нужный раздел:",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard(is_super=sa)
    )


@router.callback_query(F.data == "admin_center")
async def admin_center(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    sa = is_super_admin(callback.from_user.id)
    await _safe_edit(
        callback,
        "⚙️ <b>Панель администратора</b>\n\nВыберите нужный раздел:",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard(is_super=sa)
    )
    await callback.answer()


@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    sa = is_super_admin(callback.from_user.id)
    await _safe_edit(
        callback,
        "⚙️ <b>Панель администратора</b>\n\nВыберите нужный раздел:",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard(is_super=sa)
    )
    await callback.answer()


@router.callback_query(F.data == "admin_feedback_menu")
async def admin_feedback_menu(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    async with async_session() as session:
        feedback_items = await get_recent_feedback(session, limit=15)

    if not feedback_items:
        await callback.message.answer(
            "💬 Обращений пока нет.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")]
            ]),
        )
        await callback.answer()
        return

    kind_name = {
        "bug": "🐞 Баг",
        "suggestion": "💡 Идея",
        "praise": "❤️ Благодарность",
    }
    text_out = "💬 <b>Последние обращения пользователей</b>\n\n"
    for item in feedback_items:
        preview = (item.text or "").strip().replace("\n", " ")
        if len(preview) > 140:
            preview = preview[:140] + "..."
        text_out += (
            f"#{item.id} {kind_name.get(item.kind, item.kind)}\n"
            f"user_id={item.user_id} | {item.created_at.strftime('%d.%m %H:%M')}\n"
            f"{preview}\n\n"
        )

    if len(text_out) > 3900:
        text_out = text_out[:3900] + "\n..."

    await callback.message.answer(
        text_out,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_feedback_menu")],
            [InlineKeyboardButton(text="◀ К панели", callback_data="admin_center")],
        ]),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_db_menu")
async def admin_db_menu(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer()
        return

    table_labels: dict[str, str] = {
        "users": "Пользователи",
        "videos": "Контент (видео/фото)",
        "video_views": "Просмотры",
        "video_ratings": "Оценки",
        "comments": "Комментарии",
        "content_reactions": "Реакции",
        "balance_logs": "Лог баланса",
        "user_action_logs": "Лог действий",
        "offers": "Офферы",
        "offer_participations": "Участия в офферах",
        "offer_rentals": "Аренда офферов",
        "payments": "Платежи",
        "feedback": "Обращения",
        "games_history": "История игр",
        "game_sessions": "Игровые сессии",
        "daily_quest_progress": "Прогресс квестов",
        "promocodes": "Промокоды",
        "promocode_activations": "Активации промокодов",
        "lottery_rounds": "Лотерея: раунды",
        "lottery_tickets": "Лотерея: билеты",
    }

    all_tables = sorted(Base.metadata.tables.keys())
    tables = [(t, table_labels.get(t, t)) for t in all_tables]
    await _safe_edit(
        callback,
        "🗄 <b>База данных</b>\n\nВыберите таблицу для просмотра:",
        parse_mode="HTML",
        reply_markup=admin_db_keyboard(tables)
    )
    await callback.answer()


def _format_db_value(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "Да" if v else "Нет"
    if isinstance(v, datetime):
        return v.strftime("%d.%m.%Y %H:%M")
    if isinstance(v, Decimal):
        return f"{v:.2f}"
    s = str(v)
    s = s.replace("\n", " ").strip()
    if len(s) > 80:
        s = s[:80] + "…"
    return s


@router.callback_query(F.data.startswith("db_open:"))
async def db_open(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer()
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer()
        return
    table_name = parts[1]
    try:
        offset = max(0, int(parts[2]))
    except Exception:
        offset = 0
    if table_name not in Base.metadata.tables:
        await callback.answer("Таблица не найдена.", show_alert=True)
        return
    page_size = 8

    async with async_session() as session:
        try:
            total = (await session.execute(
                text(f'SELECT COUNT(*) FROM "{table_name}"')
            )).scalar_one()
            rows = (await session.execute(
                text(f'SELECT * FROM "{table_name}" ORDER BY 1 DESC LIMIT {page_size} OFFSET {offset}')
            )).mappings().all()
        except Exception as e:
            await callback.answer(f"Ошибка чтения таблицы: {e}", show_alert=True)
            return

    from html import escape

    if not rows:
        body = "Нет строк."
    else:
        lines = []
        for row in rows:
            # Try to infer a natural "title" for the record
            row_id = row.get("id", "?")
            title = ""
            
            if "telegram_id" in row and "username" in row:
                title = f"Юзер @{row.get('username') or '?'}"
            elif "telegram_file_id" in row:
                title = f"Видео/Фото от {row.get('uploader_user_id')}"
            elif "action" in row:
                title = f"Действие: {row.get('action')}"
            elif "amount" in row and "source" in row:
                title = f"Транзакция: {row.get('amount')}"
            elif "title" in row:
                title = f"Оффер: {row.get('title')}"
            
            lines.append(f"<b>#{row_id}</b> <i>{escape(title)}</i>")
            
            # Format attributes compactly
            attrs = []
            for key, value in row.items():
                if key == "id" or value is None:
                    continue
                attrs.append(f"<b>{escape(str(key))}</b>: {escape(_format_db_value(value))}")
            
            lines.append("  " + " | ".join(attrs))
            lines.append("")
            
        body = "\n".join(lines).rstrip()

    text_out = (
        f"🗄 <b>{escape(table_name)}</b>\n"
        f"Всего строк: <b>{total}</b>\n"
        f"Страница: <b>{(offset // page_size) + 1}</b>\n"
        f"Показано: <b>{len(rows)}</b>\n\n"
        f"{body}"
    )
    if len(text_out) > 3900:
        text_out = text_out[:3900] + "\n..."

    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"db_open:{table_name}:{max(0, offset - page_size)}"))
    if offset + page_size < total:
        nav.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"db_open:{table_name}:{offset + page_size}"))

    kb_rows = []
    if nav:
        kb_rows.append(nav)
    kb_rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data=f"db_open:{table_name}:{offset}")])
    kb_rows.append([InlineKeyboardButton(text="📋 К списку таблиц", callback_data="admin_db_menu")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    await _safe_edit(
        callback,
        text_out,
        parse_mode="HTML",
        reply_markup=kb,
    )
    await callback.answer()


# =========================
# QUEUE INFO
# =========================
@router.callback_query(F.data == "admin_queue_info")
async def cb_queue(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        p = await count_pending_videos(session)
        a = await count_approved_videos(session)
        r = await count_rejected_videos(session)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶ Модерировать", callback_data="admin_get_pending")],
        [InlineKeyboardButton(text="✅ Одобрить всё", callback_data="admin_approve_all")],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")],
    ])
    await _safe_edit(
        callback,
        f"📊 <b>Очередь</b>\n\n"
        f"⏳ На модерации: <b>{p}</b>\n"
        f"✅ Одобрено: <b>{a}</b>\n"
        f"❌ Отклонено: <b>{r}</b>",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


# =========================
# EXTENDED STATS
# =========================
@router.callback_query(F.data == "admin_extended_stats")
async def admin_extended_stats(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        stats = await get_admin_extended_stats(session)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")]
    ])
    text = (
        f"📊 <b>Расширенная статистика</b>\n\n"
        f"👥 Пользователей: <b>{stats['users']}</b>\n"
        f"⭐ VIP: <b>{stats['vip']}</b>\n"
        f"🏷 С ником: <b>{stats['with_nickname']}</b>\n"
        f"💬 Комментариев: <b>{stats['comments']}</b>\n"
        f"❤ Реакций: <b>{stats['reactions']}</b>\n"
        f"🎮 Игр: <b>{stats['games']}</b>\n"
        f"📢 Офферов: <b>{stats['offers']}</b>\n"
        f"🔑 Активных аренд: <b>{stats.get('active_rentals', 0)}</b>\n\n"
        f"💰 Монет в системе: <b>{stats['total_balance_in_system']:.2f}</b>\n"
        f"🎁 Выдано админами: <b>{stats['total_admin_given']:.2f}</b>\n"
        f"🎲 Прибыль казино: <b>{stats['total_game_profit']:.2f}</b>\n"
        f"🏠 Доход от аренды: <b>{abs(float(stats.get('total_rent_income', 0))):.2f}</b>"
    )
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# =========================
@router.callback_query(F.data == "admin_get_pending")


@router.message(AdminBroadcastState.waiting_text)
async def admin_create_offer_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminOfferCreateState.waiting_title)
    await callback.message.answer(
        "📢 <b>Создание оффера (шаг 1/9)</b>\n\n"
        "Введите название оффера (название канала/группы):",
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(AdminOfferCreateState.waiting_title)
async def admin_offer_title(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    if len(message.text) > 100:
        await message.answer("❌ Название слишком длинное. Макс. 100 символов.")
        return
    await state.update_data(title=message.text.strip())
    await state.set_state(AdminOfferCreateState.waiting_description)
    await message.answer(
        "📝 <b>Шаг 2/9</b>\n\nВведите описание оффера:",
        parse_mode="HTML"
    )


@router.message(AdminOfferCreateState.waiting_description)
async def admin_offer_description(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    await state.update_data(description=message.text.strip())
    await state.set_state(AdminOfferCreateState.waiting_url)
    await message.answer(
        "🔗 <b>Шаг 3/9</b>\n\nВведите ссылку на канал (https://t.me/...):",
        parse_mode="HTML"
    )


@router.message(AdminOfferCreateState.waiting_url)
async def admin_offer_url(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    url = message.text.strip()
    if not (url.startswith("https://t.me/") or url.startswith("t.me/")):
        await message.answer(
            "❌ Ссылка должна начинаться с https://t.me/ или t.me/"
        )
        return
    await state.update_data(url=url)
    await state.set_state(AdminOfferCreateState.waiting_reward_preview)
    await message.answer(
        "💰 <b>Шаг 4/9</b>\n\n"
        "Введите предварительную награду (монеты, выдаётся сразу при старте):\n"
        "Рекомендуется: 5",
        parse_mode="HTML"
    )


@router.message(AdminOfferCreateState.waiting_reward_preview)
async def admin_offer_reward_preview(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    try:
        val = Decimal(message.text.strip())
        if val < 0:
            raise ValueError
    except Exception:
        await message.answer("❌ Введите корректное число.")
        return
    await state.update_data(reward_preview=val)
    await state.set_state(AdminOfferCreateState.waiting_reward_final)
    await message.answer(
        "💎 <b>Шаг 5/9</b>\n\n"
        "Введите итоговую награду (монеты, выдаётся после проверки подписки):\n"
        "Рекомендуется: 35",
        parse_mode="HTML"
    )


@router.message(AdminOfferCreateState.waiting_reward_final)
async def admin_offer_reward_final(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    try:
        val = Decimal(message.text.strip())
        if val < 0:
            raise ValueError
    except Exception:
        await message.answer("❌ Введите корректное число.")
        return
    await state.update_data(reward_final=val)
    data = await state.get_data()
    reward_preview = Decimal(data.get("reward_preview", 0))
    max_penalty = (reward_preview + val) * Decimal("0.5")
    await state.set_state(AdminOfferCreateState.waiting_penalty_unsubscribe)
    await message.answer(
        "⚠️ <b>Шаг 6/9</b>\n\n"
        "Введите штраф за отписку (дополнительно к возврату всех бонусов).\n"
        f"Максимум: {max_penalty} монет (50% от суммы бонусов).",
        parse_mode="HTML"
    )


@router.message(AdminOfferCreateState.waiting_penalty_unsubscribe)
async def admin_offer_penalty_unsubscribe(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    try:
        penalty = Decimal(message.text.strip())
        if penalty < 0:
            raise ValueError
    except Exception:
        await message.answer("❌ Введите корректное число >= 0.")
        return
    data = await state.get_data()
    reward_preview = Decimal(data.get("reward_preview", 0))
    reward_final = Decimal(data.get("reward_final", 0))
    max_penalty = (reward_preview + reward_final) * Decimal("0.5")
    if penalty > max_penalty:
        await message.answer(
            f"❌ Слишком большой штраф. Максимум: {max_penalty} монет."
        )
        return
    await state.update_data(penalty_unsubscribe=penalty)
    await state.set_state(AdminOfferCreateState.waiting_rentable)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data="offer_rentable_yes"),
            InlineKeyboardButton(text="❌ Нет", callback_data="offer_rentable_no"),
        ]
    ])
    await message.answer(
        "🏠 <b>Шаг 7/9</b>\n\n"
        "Разрешить рекламодателям арендовать этот оффер\n"
        "(размещать рекламу своего канала вместе с этим)?",
        parse_mode="HTML",
        reply_markup=kb
    )


@router.callback_query(AdminOfferCreateState.waiting_rentable, F.data == "offer_rentable_yes")
async def admin_offer_rentable_yes(callback: CallbackQuery, state: FSMContext):
    await state.update_data(is_rentable=True)
    await state.set_state(AdminOfferCreateState.waiting_rent_cost)
    await callback.message.answer(
        f"💵 <b>Шаг 8/9</b>\n\n"
        f"Введите стоимость аренды за 1 день (монеты):\n"
        f"По умолчанию: {OFFER_DEFAULT_RENT_COST_PER_DAY}",
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(AdminOfferCreateState.waiting_rentable, F.data == "offer_rentable_no")
async def admin_offer_rentable_no(callback: CallbackQuery, state: FSMContext):
    await state.update_data(is_rentable=False, rent_cost_per_day=Decimal("0"), max_simultaneous_rentals=0)
    await state.set_state(AdminOfferCreateState.waiting_max_rentals)
    await _finish_offer_creation(callback.message, state, skip_rentals=True)
    await callback.answer()


@router.message(AdminOfferCreateState.waiting_rent_cost)
async def admin_offer_rent_cost(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    try:
        val = Decimal(message.text.strip())
        if val <= 0:
            raise ValueError
    except Exception:
        await message.answer("❌ Введите корректное число.")
        return
    await state.update_data(rent_cost_per_day=val)
    await state.set_state(AdminOfferCreateState.waiting_max_rentals)
    await message.answer(
        "🔢 <b>Шаг 9/9</b>\n\n"
        "Максимальное число одновременных арендаторов?\n"
        "Рекомендуется: 1-5",
        parse_mode="HTML"
    )


@router.message(AdminOfferCreateState.waiting_max_rentals)
async def admin_offer_max_rentals(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    try:
        val = int(message.text.strip())
        if val < 1:
            raise ValueError
    except Exception:
        await message.answer("❌ Введите целое число >= 1.")
        return
    await state.update_data(max_simultaneous_rentals=val)
    await _finish_offer_creation(message, state)


async def _finish_offer_creation(
        message: Message,
        state: FSMContext,
        skip_rentals: bool = False
):
    data = await state.get_data()
    async with async_session() as session:
        await admin_create_offer(
            session,
            title=data["title"],
            description=data["description"],
            channel_url=data["url"],
            reward_preview=data["reward_preview"],
            reward_final=data["reward_final"],
            penalty_unsubscribe=data.get("penalty_unsubscribe", Decimal("0")),
            is_rentable=data.get("is_rentable", False),
            rent_cost_per_day=data.get("rent_cost_per_day", Decimal("0")),
            max_simultaneous_rentals=data.get("max_simultaneous_rentals", 0),
        )

    rentable_text = ""
    if data.get("is_rentable"):
        rentable_text = (
            f"\n🔑 Аренда: {data.get('rent_cost_per_day')} монет/день\n"
            f"Макс. арендаторов: {data.get('max_simultaneous_rentals')}"
        )

    await message.answer(
        f"✅ <b>Оффер создан!</b>\n\n"
        f"📢 {data['title']}\n"
        f"💰 Старт. награда: {data['reward_preview']}\n"
        f"💎 Итог. награда: {data['reward_final']}"
        f"\n⚠️ Штраф за отписку: {data.get('penalty_unsubscribe', Decimal('0'))}"
        f"{rentable_text}\n\n"
        f"Оффер сразу активен и виден пользователям.",
        parse_mode="HTML"
    )
    await state.clear()



    if len(text) > 4000:
        text = text[:4000] + "\n..."

    await callback.message.answer(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_review_rental:"))
async def admin_review_rental(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    rental_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        try:
            rental = (await session.execute(
            )).scalar_one_or_none()
        except Exception:
            rental = None

        if not rental:
            await callback.answer("Аренда не найдена.", show_alert=True)
            return

        renter = await get_user_by_id(session, rental.renter_user_id)
        offer = (await session.execute(
            select(Offer).where(Offer.id == rental.offer_id)
        )).scalar_one_or_none()

    text = (
        f"🔑 <b>Аренда #{rental.id}</b>\n\n"
        f"Арендатор: {get_display_name(renter) if renter else '???'}\n"
        f"Канал: {rental.renter_channel_title}\n"
        f"Ссылка: {rental.renter_channel_url}\n"
        f"Оффер: #{rental.offer_id} {offer.title if offer else '???'}\n"
        f"Дней: {rental.rent_days}\n"
        f"Оплачено: {rental.cost_paid} монет\n"
        f"Статус: {rental.status}\n"
        f"Создана: {rental.created_at.strftime('%d.%m.%Y %H:%M')}\n"
        f"Истекает: {rental.expires_at.strftime('%d.%m.%Y') if rental.expires_at else '???'}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Одобрить",
                callback_data=f"approve_rental:{rental_id}"
            ),
            InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data=f"reject_rental:{rental_id}"
            ),
        ],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_rentals_menu")],
    ])
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("approve_rental:"))
async def approve_rental_cb(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    rental_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        try:
            rental = (await session.execute(
            )).scalar_one_or_none()
            if not rental:
                await callback.answer("Не найдено.", show_alert=True)
                return
            rental.status = "active"
            rental.expires_at = datetime.now(timezone.utc) + timedelta(days=rental.rent_days)
            await session.commit()

            renter = await get_user_by_id(session, rental.renter_user_id)
            if renter:
                try:
                    await callback.bot.send_message(
                        renter.telegram_id,
                        f"✅ Ваша аренда одобрена!\n"
                        f"Канал: {rental.renter_channel_title}\n"
                        f"Активна до: {rental.expires_at.strftime('%d.%m.%Y')}"
                    )
                except Exception:
                    pass
        except Exception as e:
            await callback.answer(f"Ошибка: {e}", show_alert=True)
            return
    await callback.answer("✅ Аренда одобрена!", show_alert=True)


@router.callback_query(F.data.startswith("reject_rental:"))
async def reject_rental_cb(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    rental_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        try:
            rental = (await session.execute(
            )).scalar_one_or_none()
            if not rental:
                await callback.answer("Не найдено.", show_alert=True)
                return

            rental.status = "rejected"
            renter = await get_user_by_id(session, rental.renter_user_id)
            if renter and rental.cost_paid > 0:
                from app.services import log_balance_change
                await log_balance_change(
                    session,
                    renter,
                    rental.cost_paid,
                    "rental_refund",
                    source_id=rental_id,
                    details="Возврат за отклонённую аренду",
                )
                renter.balance += rental.cost_paid
            await session.commit()

            if renter:
                try:
                    await callback.bot.send_message(
                        renter.telegram_id,
                        f"❌ Ваша аренда отклонена.\n"
                        f"Возврат: {rental.cost_paid} монет"
                    )
                except Exception:
                    pass
        except Exception as e:
            await callback.answer(f"Ошибка: {e}", show_alert=True)
            return
    await callback.answer("❌ Аренда отклонена, возврат выполнен.", show_alert=True)


@router.callback_query(F.data == "admin_expire_rentals")
async def admin_expire_rentals_cb(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        try:
            expired = await expire_old_rentals(session)
            await callback.answer(f"✅ Завершено просроченных аренд: {expired}", show_alert=True)
        except Exception as e:
            await callback.answer(f"❌ Ошибка: {e}", show_alert=True)


# =========================
# ADMIN MANAGEMENT
# =========================
@router.callback_query(F.data == "admin_manage_admins")
async def manage_admins_menu(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer()
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список", callback_data="admin_list_admins")],
        [InlineKeyboardButton(text="➕ Добавить", callback_data="admin_add_admin")],
        [InlineKeyboardButton(text="➖ Удалить", callback_data="admin_remove_admin")],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")],
    ])
    await _safe_edit(
        callback,
        "👮 <b>Управление администраторами</b>",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data == "admin_list_admins")
async def list_admins(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        admins = (await session.execute(
            select(User).where(User.is_admin)
        )).scalars().all()

    text = "👮 <b>Администраторы бота:</b>\n\n"
    if not admins:
        text += "Дополнительных администраторов нет."
    else:
        for a in admins:
            text += (
                f"• {get_display_name(a)} "
                f"(ID: <code>{a.telegram_id}</code>)\n"
            )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_manage_admins")]
    ])
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_add_admin")
async def add_admin_start(callback: CallbackQuery, state: FSMContext):
    if not is_super_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminManageState.waiting_new_admin)
    await callback.message.answer(
        "Введите Telegram ID пользователя для назначения администратором:"
    )
    await callback.answer()


@router.message(AdminManageState.waiting_new_admin)
async def process_add_admin(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        return
    if not message.text.isdigit():
        await message.answer("❌ Введите числовой Telegram ID.")
        return
    telegram_id = int(message.text)
    async with async_session() as session:
        user = await get_user(session, telegram_id)
        if not user:
            await message.answer(
                "❌ Пользователь не найден.\n"
                "Попросите его отправить боту /start."
            )
            await state.clear()
            return
        if user.is_admin:
            await message.answer("Этот пользователь уже является администратором.")
            await state.clear()
            return
        user.is_admin = True
        await session.commit()

    await message.answer(
        f"✅ Пользователь <code>{telegram_id}</code> назначен администратором.",
        parse_mode="HTML"
    )
    try:
        await message.bot.send_message(
            telegram_id,
            "🎉 Вам выдана роль администратора бота!"
        )
    except Exception:
        pass
    await state.clear()


@router.callback_query(F.data == "admin_remove_admin")
async def remove_admin_start(callback: CallbackQuery, state: FSMContext):
    if not is_super_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminManageState.waiting_remove_admin)
    await callback.message.answer(
        "Введите Telegram ID администратора для снятия прав:"
    )
    await callback.answer()


@router.message(AdminManageState.waiting_remove_admin)
async def process_remove_admin(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        return
    if not message.text.isdigit():
        await message.answer("❌ Введите числовой Telegram ID.")
        return
    telegram_id = int(message.text)
    if telegram_id in ADMINS:
        await message.answer(
            "❌ Нельзя снять права у супер-администратора."
        )
        await state.clear()
        return
    async with async_session() as session:
        user = await get_user(session, telegram_id)
        if not user or not user.is_admin:
            await message.answer("❌ Этот пользователь не является администратором.")
            await state.clear()
            return
        user.is_admin = False
        await session.commit()

    await message.answer(
        f"✅ Права администратора сняты у <code>{telegram_id}</code>.",
        parse_mode="HTML"
    )
    try:
        await message.bot.send_message(
            telegram_id,
            "Ваши права администратора были отозваны."
        )
    except Exception:
        pass
    await state.clear()


class SaleState(StatesGroup):
    waiting_percent = State()
    waiting_scope = State()
    waiting_duration = State()
    waiting_text = State()

@router.callback_query(F.data == "admin_sales")
async def admin_sales_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    from app.services import get_active_sale
    async with async_session() as session:
        sale = await get_active_sale(session)
    
    text = "🛍 <b>Управление акциями</b>\n\n"
    if sale:
        text += (
            f"🟢 <b>Текущая акция активна!</b>\n"
            f"Скидка: <b>{sale.discount_percent}%</b>\n"
            f"Действует на: <b>{sale.applies_to}</b>\n"
            f"Закончится: <b>{sale.end_date.strftime('%d.%m.%Y %H:%M')} UTC</b>\n"
            f"Текст:\n<i>{sale.announcement}</i>\n\n"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛑 Завершить акцию", callback_data="admin_sale_stop")],
            [InlineKeyboardButton(text="◀ В меню", callback_data="admin_center")]
        ])
    else:
        text += "🔴 В данный момент нет активных акций."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать акцию", callback_data="admin_sale_create")],
            [InlineKeyboardButton(text="◀ В меню", callback_data="admin_center")]
        ])

    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "admin_sale_stop")
async def admin_sale_stop(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        return
    
    from app.services import get_active_sale
    async with async_session() as session:
        sale = await get_active_sale(session)
        if sale:
            from datetime import datetime
            sale.end_date = datetime.utcnow()
            await session.commit()
            await callback.answer("✅ Акция досрочно завершена!", show_alert=True)
        else:
            await callback.answer("Акция уже неактивна.", show_alert=True)
    
    await admin_sales_start(callback, None)

@router.callback_query(F.data == "admin_sale_create")
async def admin_sale_create(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        return
    await state.set_state(SaleState.waiting_percent)
    await _safe_edit(callback, "Введите процент скидки (от 1 до 99):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="admin_center")]
    ]))

@router.message(SaleState.waiting_percent)
async def admin_sale_percent(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("Пожалуйста, введите число от 1 до 99.")
        return
    pct = int(message.text)
    if pct < 1 or pct > 99:
        await message.answer("Процент должен быть от 1 до 99.")
        return
    await state.update_data(discount_percent=pct)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="На всё", callback_data="sale_scope:all")],
        [InlineKeyboardButton(text="Только VIP", callback_data="sale_scope:vip")],
        [InlineKeyboardButton(text="Только Монеты", callback_data="sale_scope:coins")],
        [InlineKeyboardButton(text="Отмена", callback_data="admin_center")]
    ])
    await state.set_state(SaleState.waiting_scope)
    await message.answer("Выберите, на что действует скидка:", reply_markup=kb)

@router.callback_query(SaleState.waiting_scope, F.data.startswith("sale_scope:"))
async def admin_sale_scope(callback: CallbackQuery, state: FSMContext):
    scope = callback.data.split(":")[1]
    await state.update_data(applies_to=scope)
    await state.set_state(SaleState.waiting_duration)
    await _safe_edit(callback, "Введите длительность акции в часах (например, 24):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="admin_center")]
    ]))
    await callback.answer()

@router.message(SaleState.waiting_duration)
async def admin_sale_duration(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("Пожалуйста, введите количество часов числом.")
        return
    hours = int(message.text)
    if hours < 1:
        await message.answer("Минимум 1 час.")
        return
    await state.update_data(duration_hours=hours)
    
    await state.set_state(SaleState.waiting_text)
    await message.answer(
        "Напишите текст рекламного объявления (поддерживается HTML).\n"
        "Это сообщение будет разослано всем пользователям вместе с картинкой-флаером."
    )

@router.message(SaleState.waiting_text)
async def admin_sale_finish(message: Message, state: FSMContext):
    data = await state.get_data()
    from datetime import datetime, timedelta
    from app.models import ActiveSale
    import os
    from aiogram.types import FSInputFile
    
    end_date = datetime.utcnow() + timedelta(hours=data["duration_hours"])
    
    async with async_session() as session:
        sale = ActiveSale(
            discount_percent=data["discount_percent"],
            applies_to=data["applies_to"],
            end_date=end_date,
            announcement=message.text
        )
        session.add(sale)
        await session.commit()
    
    await state.clear()
    await message.answer(f"✅ Акция успешно создана и будет действовать до {end_date.strftime('%d.%m.%Y %H:%M')} UTC!")
    
    # Trigger broadcast to all users
    # In a real heavy app we'd use a background worker, but for MVP we loop here
    async with async_session() as session:
        from app.models import User
        from sqlalchemy import select
        users = (await session.execute(select(User))).scalars().all()
    
    import asyncio
    sent = 0
    await message.answer("⏳ Начинаю рассылку флаера всем пользователям...")
    for u in users:
        try:
            if os.path.exists("app/flyer_sale.jpg"):
                await message.bot.send_photo(u.telegram_id, photo=FSInputFile("app/flyer_sale.jpg"), caption=message.text, parse_mode="HTML")
            else:
                await message.bot.send_message(u.telegram_id, message.text, parse_mode="HTML")
            sent += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)
        
    await message.answer(f"✅ Рассылка завершена. Доставлено: {sent} пользователям.")

