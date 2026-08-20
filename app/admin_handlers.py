from app.models import utc_now
import os
import asyncio
import json
from datetime import datetime, timezone, timedelta
from html import escape
from decimal import Decimal

from aiogram import Router, F
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
)
from sqlalchemy import select, func, text


from app.config import ENABLE_AUTO_MODERATION
from app.db import async_session
from app.models import (
    Base,
    User, Video, TrustedUploader, Event, ActiveSale,
    VideoReport, ModNotification, Offer, OfferRental,
    DonationAlertException,
    AdminPoll, AdminPollResponse, utc_now,
)
from app.services import (
    get_user, get_user_by_id, get_user_by_username,
    get_user_dossier, count_pending_videos, count_approved_videos, count_rejected_videos,
    get_next_pending_video, get_video_by_id, get_rejected_video, restore_rejected_video,
    approve_video, reject_video,
    get_admin_extended_stats, get_display_name, get_styled_display_name,
    get_user_by_display_name, get_recent_feedback, get_active_sale,
    get_active_events, approve_all_pending,
    get_pending_reports, dismiss_report, REPORT_REASONS,
    get_offer_moderation_counts, get_offers_for_admin, get_offer_by_id,
    moderate_offer, set_offer_active, get_offer_expires_at,
    get_pending_rentals, moderate_offer_rental, normalize_telegram_url,
    adjust_balance_by_admin, AdminBalanceError,
)
from app.keyboards import (
    admin_main_keyboard, moderation_keyboard,
    rejection_reason_keyboard, admin_after_action_keyboard,
    admin_db_keyboard,
)
from app.logger import get_logger
from app.reports import build_all_users_report_pdf, build_bot_report_pdf, build_user_report_pdf
from app.utils.admin import check_admin, is_super_admin, _safe_edit

logger = get_logger(__name__)

router = Router()

@router.message(Command("cancel"))
async def cmd_cancel_admin(message: Message, state: FSMContext):
    await state.clear()
    from app.keyboards import main_menu
    from app.services import get_user
    from app.user_handlers import is_any_admin
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        admin_flag = is_any_admin(message.from_user.id, user)
    await message.answer("❌ Действие отменено.", reply_markup=main_menu(is_admin=admin_flag))


@router.message(CommandStart())
async def cmd_start_admin(message: Message, command: CommandObject, state: FSMContext):
    await state.clear()
    from app.user_handlers import cmd_start
    await cmd_start(message, command, state)


# =========================
# STATES
# =========================
class AdminUserState(StatesGroup):
    waiting_user_id = State()
    waiting_coins_amount = State()
    waiting_message_text = State()
    waiting_dossier_id = State()
    waiting_new_nickname = State()
    waiting_user_search = State()


class ModerationRejectState(StatesGroup):
    waiting_comment = State()


class AdminVideoSearchState(StatesGroup):
    waiting_video_id = State()


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
    waiting_penalty = State()
    waiting_duration = State()
    waiting_rentable = State()
    waiting_rent_cost = State()
    waiting_max_rentals = State()


class TrustedUploaderState(StatesGroup):
    waiting_add = State()
    waiting_remove = State()


class SaleState(StatesGroup):
    waiting_percent = State()
    waiting_scope = State()
    waiting_duration = State()
    waiting_text = State()


class EventCreationState(StatesGroup):
    waiting_name = State()
    waiting_description = State()
    waiting_discount = State()
    waiting_duration = State()
    waiting_applies = State()
    waiting_image = State()      # опциональная картинка
    confirm = State()


class PromoRotationState(StatesGroup):
    """Редактирование пула авто-ротации промо-рассылок («📋 Авто-рассылки»)."""
    waiting_add_title = State()
    waiting_add_text = State()
    waiting_edit_title = State()
    waiting_edit_text = State()


class DAManualState(StatesGroup):
    """Ручное зачисление платежа DonationAlerts."""
    waiting_user = State()
    waiting_amount = State()


class AdminPollCreationState(StatesGroup):
    """Пошаговое создание опроса с фиксированной наградой."""
    waiting_question = State()
    waiting_options = State()


# =========================
# ADMIN PANEL
# =========================
@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext | None = None):
    if state:
        await state.clear()
    if not await check_admin(message.from_user.id):
        return
    sa = is_super_admin(message.from_user.id)
    await message.answer(
        "⚙️ <b>Панель администратора</b>\n\nВыбери нужный раздел:",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard(is_super=sa)
    )


@router.callback_query(F.data == "admin_center")
async def admin_center(callback: CallbackQuery, state: FSMContext | None = None):
    if state:
        await state.clear()
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    sa = is_super_admin(callback.from_user.id)
    await _safe_edit(
        callback,
        "⚙️ <b>Панель администратора</b>\n\nВыбери нужный раздел:",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard(is_super=sa)
    )
    await callback.answer()


@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    await admin_center(callback)


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

    kind_name = {"bug": "🐞 Баг", "suggestion": "💡 Идея", "praise": "❤️ Благодарность"}
    text_out = "💬 <b>Последние обращения</b>\n\n"
    for item in feedback_items:
        preview = (item.text or "").strip().replace("\n", " ")[:140]
        text_out += f"#{item.id} {kind_name.get(item.kind, item.kind)}\nuser_id={item.user_id} | {item.created_at.strftime('%d.%m %H:%M')}\n{preview}\n\n"

    await callback.message.answer(text_out, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_feedback_menu")],
        [InlineKeyboardButton(text="◀ К панели", callback_data="admin_center")],
    ]))
    await callback.answer()


@router.callback_query(F.data == "admin_db_menu")
async def admin_db_menu(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer()
        return
    table_labels = {"users": "Пользователи", "videos": "Контент", "offers": "Офферы", "events": "События", "balance_logs": "Лог баланса"}
    all_tables = sorted(Base.metadata.tables.keys())
    tables = [(t, table_labels.get(t, t)) for t in all_tables]
    await _safe_edit(callback, "🗄 <b>База данных</b>", parse_mode="HTML", reply_markup=admin_db_keyboard(tables))
    await callback.answer()


@router.callback_query(F.data.startswith("db_open:"))
async def db_open(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id): return
    parts = callback.data.split(":")
    table_name = parts[1]
    offset = int(parts[2]) if len(parts) > 2 else 0
    page_size = 8

    # SQL injection protection: whitelist table names
    from app.models import Base
    allowed_tables = [mapper.class_.__tablename__ for mapper in Base.registry.mappers]
    if table_name not in allowed_tables:
        await callback.answer("Недопустимая таблица", show_alert=True)
        return

    async with async_session() as session:
        try:
            total = (await session.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))).scalar_one()
            rows = (await session.execute(text(f'SELECT * FROM "{table_name}" ORDER BY 1 DESC LIMIT {page_size} OFFSET {offset}'))).mappings().all()
        except Exception as e:
            await callback.answer(f"Ошибка: {e}", show_alert=True)
            return

    body = ""
    for r in rows:
        body += f"<b>#{r.get('id','?')}</b> | {escape(str(dict(r))[:120])}\n\n"
    
    text_out = f"🗄 <b>{escape(table_name)}</b>\nВсего: {total}\n\n{body or 'Нет строк.'}"
    
    nav = []
    if offset > 0: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"db_open:{table_name}:{max(0, offset-page_size)}"))
    if offset + page_size < total: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"db_open:{table_name}:{offset+page_size}"))
    
    kb = InlineKeyboardMarkup(inline_keyboard=[nav, [InlineKeyboardButton(text="📋 Список", callback_data="admin_db_menu")]])
    await _safe_edit(callback, text_out, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# =========================
# MODERATION
# =========================
@router.callback_query(F.data == "admin_queue_info")
async def cb_queue(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    async with async_session() as session:
        p, a, r = await count_pending_videos(session), await count_approved_videos(session), await count_rejected_videos(session)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶ Модерировать", callback_data="admin_get_pending")],
        [InlineKeyboardButton(text=f"🗄 Отклонённые ({r})", callback_data="admin_rejected:0")],
        [InlineKeyboardButton(text="🔎 Найти публикацию по #ID", callback_data="admin_video_search")],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")],
    ])
    await _safe_edit(callback, f"📊 <b>Очередь</b>\n\n⏳ Ожидает: {p}\n✅ Одобрено: {a}\n❌ Отклонено: {r}", parse_mode="HTML", reply_markup=kb)
    await callback.answer()


def _parse_video_number(raw: str | None) -> int | None:
    value = (raw or "").strip()
    if value.startswith("#"):
        value = value[1:]
    if not value.isdigit():
        return None
    video_id = int(value)
    return video_id if video_id > 0 else None


def _video_admin_keyboard(video: Video, *, back_callback: str = "admin_queue_info") -> InlineKeyboardMarkup:
    rows = []
    if video.status == "pending":
        rows.append([
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"mod_approve:{video.id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"mod_reject:{video.id}"),
        ])
    elif video.status == "approved":
        rows.append([InlineKeyboardButton(text="❌ Снять с публикации", callback_data=f"mod_reject:{video.id}")])
    elif video.status == "rejected":
        rows.append([InlineKeyboardButton(text="↩️ Вернуть на модерацию", callback_data=f"admin_video_restore:{video.id}")])
    rows.append([InlineKeyboardButton(text="◀ Назад", callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_admin_video_card(message: Message, video: Video, uploader: User | None, reply_markup) -> None:
    name = escape(get_display_name(uploader)) if uploader else "???"
    status_labels = {"pending": "⏳ ожидает", "approved": "✅ одобрено", "rejected": "❌ отклонено"}
    reason = f"\n📝 Причина: {escape(video.rejection_reason)}" if video.rejection_reason else ""
    caption = (
        f"🎬 <b>Публикация #{video.id}</b>\n"
        f"Статус: {status_labels.get(video.status, escape(video.status))}\n"
        f"Тип: {escape(video.content_type)}\n"
        f"Автор: {name}\n"
        f"Дата: {video.created_at.strftime('%d.%m.%Y %H:%M')}"
        f"{reason}"
    )
    try:
        if video.content_type == "photo":
            await message.answer_photo(video.telegram_file_id, caption=caption, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await message.answer_video(video.telegram_file_id, caption=caption, parse_mode="HTML", reply_markup=reply_markup)
    except Exception:
        await message.answer(
            f"⚠️ Медиа Telegram недоступно.\n\n{caption}",
            parse_mode="HTML",
            reply_markup=reply_markup,
        )


@router.callback_query(F.data.startswith("admin_rejected:"))
async def admin_rejected_archive(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    offset = max(0, int(callback.data.split(":", 1)[1]))
    async with async_session() as session:
        total = await count_rejected_videos(session)
        if not total:
            await _safe_edit(callback, "🗄 Хранилище отклонённых публикаций пусто.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀ Назад", callback_data="admin_queue_info")]
            ]))
            await callback.answer()
            return
        if offset >= total:
            offset = total - 1
        video = await get_rejected_video(session, offset)
        uploader = await get_user_by_id(session, video.uploader_user_id) if video else None

    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"admin_rejected:{offset - 1}"))
    nav.append(InlineKeyboardButton(text=f"{offset + 1}/{total}", callback_data="admin_rejected_noop"))
    if offset + 1 < total:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"admin_rejected:{offset + 1}"))
    rows = [nav]
    if video:
        rows.append([InlineKeyboardButton(text="↩️ Вернуть на модерацию", callback_data=f"admin_video_restore:{video.id}")])
    rows.extend([
        [InlineKeyboardButton(text="🔎 Найти по #ID", callback_data="admin_video_search")],
        [InlineKeyboardButton(text="◀ К очереди", callback_data="admin_queue_info")],
    ])
    try:
        await callback.message.delete()
    except Exception:
        pass
    if video:
        await _send_admin_video_card(callback.message, video, uploader, InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data == "admin_rejected_noop")
async def admin_rejected_noop(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data == "admin_video_search")
async def admin_video_search_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    await state.set_state(AdminVideoSearchState.waiting_video_id)
    await _safe_edit(
        callback,
        "🔎 Отправь номер публикации в формате <code>#1234</code> или <code>1234</code>.\n\nТакже поиск всегда доступен командой <code>/video 1234</code>.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_queue_info")]]),
    )
    await callback.answer()


async def _show_video_search_result(message: Message, raw_id: str | None) -> bool:
    video_id = _parse_video_number(raw_id)
    if not video_id:
        await message.answer("❌ Нужен корректный номер, например <code>#1234</code>.", parse_mode="HTML")
        return False
    async with async_session() as session:
        video = await get_video_by_id(session, video_id)
        uploader = await get_user_by_id(session, video.uploader_user_id) if video else None
    if not video:
        await message.answer(f"❌ Публикация <b>#{video_id}</b> не найдена.", parse_mode="HTML")
        return False
    await _send_admin_video_card(message, video, uploader, _video_admin_keyboard(video))
    return True


@router.message(Command("video"))
async def admin_video_search_command(message: Message):
    if not await check_admin(message.from_user.id): return
    parts = (message.text or "").split(maxsplit=1)
    await _show_video_search_result(message, parts[1] if len(parts) > 1 else None)


@router.message(AdminVideoSearchState.waiting_video_id)
async def admin_video_search_input(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    if await _show_video_search_result(message, message.text):
        await state.clear()


@router.callback_query(F.data.startswith("admin_video_restore:"))
async def admin_video_restore(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    video_id = int(callback.data.split(":", 1)[1])
    async with async_session() as session:
        video = await restore_rejected_video(session, video_id)
    if not video:
        await callback.answer("Публикация уже не отклонена.", show_alert=True)
        return
    await _safe_edit(
        callback,
        f"↩️ Публикация #{video_id} возвращена в очередь модерации.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶ Модерировать", callback_data="admin_get_pending")],
            [InlineKeyboardButton(text="🗄 К отклонённым", callback_data="admin_rejected:0")],
        ]),
    )
    await callback.answer("Возвращено в очередь")


@router.callback_query(F.data == "admin_get_pending")
async def admin_get_pending(callback: CallbackQuery, state: FSMContext | None = None):
    if state:
        await state.clear()
    if not await check_admin(callback.from_user.id): return
    async with async_session() as session:
        video = await get_next_pending_video(session)
        if not video:
            await _safe_edit(callback, "✅ Очередь пуста!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")]]))
            await callback.answer()
            return
        uploader = await get_user_by_id(session, video.uploader_user_id)
        name = await get_styled_display_name(session, uploader) if uploader else "???"
        caption = f"📹 #{video.id} | {video.content_type}\n👤 {name}\n📅 {video.created_at.strftime('%d.%m %H:%M')}"
        try:
            if video.content_type == "photo":
                await callback.message.answer_photo(video.telegram_file_id, caption=caption, reply_markup=moderation_keyboard(video.id))
            else:
                await callback.message.answer_video(video.telegram_file_id, caption=caption, reply_markup=moderation_keyboard(video.id))
        except Exception:
            await callback.message.answer(f"⚠️ Ошибка медиа #{video.id}\n{caption}", reply_markup=moderation_keyboard(video.id))
    await callback.answer()


@router.callback_query(F.data.startswith("mod_approve:"))
async def mod_approve(callback: CallbackQuery, state: FSMContext | None = None):
    if state:
        await state.clear()
    if not await check_admin(callback.from_user.id): return
    video_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        video = await approve_video(session, video_id)
        if video:
            uploader = await get_user_by_id(session, video.uploader_user_id)
            if uploader:
                try: await callback.bot.send_message(uploader.telegram_id, f"✅ Публикация #{video_id} одобрена!")
                except Exception: pass
    await _safe_edit(callback, f"✅ #{video_id} ОДОБРЕНО", reply_markup=admin_after_action_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("mod_reject:"))
async def mod_reject(callback: CallbackQuery, state: FSMContext | None = None):
    if state:
        await state.clear()
    if not await check_admin(callback.from_user.id): return
    video_id = int(callback.data.split(":")[1])
    await _safe_edit(callback, f"Причина отклонения #{video_id}:", reply_markup=rejection_reason_keyboard(video_id))
    await callback.answer()


@router.callback_query(F.data.startswith("reject_reason:"))
async def reject_reason(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    parts = callback.data.split(":")
    video_id, reason_key = int(parts[1]), parts[2]
    reasons = {
        "duplicate": "Дубликат",
        "off_topic": "Не по теме",
        "forbidden": "Запрещёнка",
        "rules_violation": "Не соответствует правилам",
        "shock_content": "Шок-контент",
        "other": "Другое",
    }
    reason_text = reasons.get(reason_key, reason_key)
    
    if reason_key == "other":
        await state.set_state(ModerationRejectState.waiting_comment)
        await state.update_data(reject_video_id=video_id, reject_reason_text=reason_text)
        await _safe_edit(
            callback,
            f"❌ <b>Отклонение #{video_id}</b>\n\n"
            f"Базовая причина: <b>{reason_text}</b>\n\n"
            f"Теперь отправь <b>комментарий для пользователя</b>, где объясни, что именно не так с публикацией.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_get_pending")]
            ])
        )
        await callback.answer()
    else:
        await state.clear()
        async with async_session() as session:
            video = await reject_video(session, video_id, reason_text)
            if video:
                uploader = await get_user_by_id(session, video.uploader_user_id)
                if uploader:
                    try:
                        await callback.bot.send_message(
                            uploader.telegram_id,
                            f"❌ Публикация #{video_id} отклонена.\nПричина: {reason_text}",
                        )
                    except Exception:
                        pass
        await _safe_edit(
            callback,
            f"❌ #{video_id} отклонено\nПричина: {reason_text}",
            reply_markup=admin_after_action_keyboard(),
        )
        await callback.answer()


@router.message(ModerationRejectState.waiting_comment)
async def reject_reason_comment(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    comment = (message.text or "").strip()

    # Если пользователь нажал кнопку меню или команду вместо ввода комментария
    NAV_BUTTONS = {
        "🔧 Админка", "◀️ Админ-центр", "◀ Назад", "🎬 Смотреть", "👤 Профиль",
        "📤 Загрузить", "👑 VIP", "📊 Уровень", "🏆 Топы", "💬 Поддержка",
        "🎰 Секслото", "🎟 Промокоды", "🎁 Лутбоксы"
    }
    if comment.startswith("/") or comment in NAV_BUTTONS:
        await state.clear()
        if comment in ("🔧 Админка", "/admin"):
            await cmd_admin(message, state)
        else:
            await message.answer("❌ Ввод комментария отменён.")
        return

    if len(comment) < 3:
        await message.answer("❌ Комментарий слишком короткий. Напиши понятное объяснение для пользователя.")
        return

    data = await state.get_data()
    video_id = data.get("reject_video_id")
    reason_text = data.get("reject_reason_text")
    if not video_id or not reason_text:
        await state.clear()
        await message.answer("❌ Сессия отклонения потеряна. Начните заново.")
        return

    async with async_session() as session:
        video = await reject_video(session, int(video_id), str(reason_text), comment)
        if video:
            uploader = await get_user_by_id(session, video.uploader_user_id)
            if uploader:
                try:
                    await message.bot.send_message(
                        uploader.telegram_id,
                        f"❌ Публикация #{video_id} отклонена.\n"
                        f"Причина: {reason_text}\n"
                        f"Комментарий модератора: {comment}",
                    )
                except Exception:
                    pass
    await state.clear()
    await message.answer(
        f"❌ #{video_id} отклонено\n"
        f"Причина: {reason_text}\n"
        f"Комментарий: {comment}",
        reply_markup=admin_after_action_keyboard(),
    )


# =========================
# EVENTS
# =========================
def event_applies_keyboard(selected: dict) -> InlineKeyboardMarkup:
    def icon(k): return "✅" if selected.get(k) else "❌"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{icon('vip')} VIP", callback_data="event_toggle:vip")],
        [InlineKeyboardButton(text=f"{icon('coins')} Монеты", callback_data="event_toggle:coins")],
        [InlineKeyboardButton(text=f"{icon('lootbox')} Лутбоксы", callback_data="event_toggle:lootbox")],
        [InlineKeyboardButton(text="✅ Готово", callback_data="event_applies_done"), InlineKeyboardButton(text="❌ Отмена", callback_data="admin_events_menu")]
    ])


@router.callback_query(F.data == "admin_events_menu")
async def admin_events_menu(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    try:
        async with async_session() as session:
            active = (await session.execute(select(Event).where(Event.is_active.is_(True), Event.end_date > utc_now()).order_by(Event.start_date.desc()))).scalars().all()
        text = "🎉 <b>События</b>\n\n" + ("\n".join([f"• {escape(ev.name)} ({ev.discount_percent}%)" for ev in active[:5]]) if active else "Нет активных событий.")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать", callback_data="event_create_start")],
            [InlineKeyboardButton(text="📋 Все", callback_data="event_list_all")],
            [InlineKeyboardButton(text="🛍 Акции (Sale)", callback_data="admin_sales")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_center")]
        ])
        await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)
    finally:
        await callback.answer()


@router.callback_query(F.data == "event_create_start")
async def event_create_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    await state.set_state(EventCreationState.waiting_name)
    await callback.message.answer("🎉 Шаг 1: Введи название:")
    await callback.answer()


@router.message(EventCreationState.waiting_name)
async def event_name(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    await state.update_data(name=message.text.strip()[:255])
    await state.set_state(EventCreationState.waiting_description)
    await message.answer("Шаг 2: Описание:")


@router.message(EventCreationState.waiting_description)
async def event_description(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    await state.update_data(description=message.text.strip()[:2000])
    await state.set_state(EventCreationState.waiting_discount)
    await message.answer("Шаг 3: Скидка (1-99%):")


@router.message(EventCreationState.waiting_discount)
async def event_discount(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    if not message.text.isdigit(): return
    await state.update_data(discount_percent=int(message.text))
    await state.set_state(EventCreationState.waiting_duration)
    await message.answer("Шаг 4: Длительность (дней):")


@router.message(EventCreationState.waiting_duration)
async def event_duration(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    if not message.text.isdigit(): return
    await state.update_data(duration_days=int(message.text), applies={"vip": False, "coins": False, "lootbox": False})
    await state.set_state(EventCreationState.waiting_applies)
    await message.answer("Шаг 5: На что?", reply_markup=event_applies_keyboard({"vip": False, "coins": False, "lootbox": False}))


@router.callback_query(EventCreationState.waiting_applies, F.data.startswith("event_toggle:"))
async def event_toggle_applies(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(":")[1]
    data = await state.get_data()
    applies = data.get("applies", {})
    applies[key] = not applies.get(key, False)
    await state.update_data(applies=applies)
    await callback.message.edit_reply_markup(reply_markup=event_applies_keyboard(applies))
    await callback.answer()


@router.callback_query(EventCreationState.waiting_applies, F.data == "event_applies_done")
async def event_applies_done(callback: CallbackQuery, state: FSMContext):
    await state.set_state(EventCreationState.waiting_image)
    await callback.message.answer("Шаг 6: Фото или 'пропустить':")
    await callback.answer()


@router.message(EventCreationState.waiting_image)
async def event_image(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    file_id = message.photo[-1].file_id if message.photo else None
    await state.update_data(image_file_id=file_id)
    data = await state.get_data()
    await state.set_state(EventCreationState.confirm)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Создать", callback_data="event_confirm_yes"), InlineKeyboardButton(text="❌ Отмена", callback_data="admin_events_menu")]])
    await message.answer(f"Создать событие {escape(data['name'])}?", reply_markup=kb)


@router.callback_query(EventCreationState.confirm, F.data == "event_confirm_yes")
async def event_confirm_yes(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    data = await state.get_data()
    applies = data.get("applies", {})
    start = utc_now()
    end = start + timedelta(days=data["duration_days"])
    async with async_session() as session:
        admin = await get_user(session, callback.from_user.id)
        ev = Event(name=data["name"], description=data["description"], discount_percent=data["discount_percent"], duration_days=data["duration_days"], applies_vip=applies.get("vip", False), applies_coins=applies.get("coins", False), applies_lootbox=applies.get("lootbox", False), image_file_id=data.get("image_file_id"), start_date=start, end_date=end, is_active=True, created_by=admin.id if admin else None)
        session.add(ev)
        await session.commit()
    await state.clear()
    
    # Рассылаем уведомление всем пользователям
    from app.services import broadcast_event_to_users
    try:
        sent = await broadcast_event_to_users(callback.bot, ev)
        await callback.message.answer(f"✅ Событие создано!\n📢 Рассылка: {sent} пользователей.")
    except Exception as e:
        logger.error(f"Ошибка рассылки события: {e}")
        await callback.message.answer(f"✅ Событие создано!\n⚠️ Рассылка не удалась: {e}")
    await callback.answer()


@router.callback_query(F.data == "event_list_all")
async def event_list_all(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    async with async_session() as session:
        events = (await session.execute(select(Event).order_by(Event.created_at.desc()).limit(20))).scalars().all()
    if not events:
        await callback.message.answer("Нет событий.")
        await callback.answer()
        return
    for ev in events:
        status = "🟢 Активно" if ev.is_active and ev.end_date > utc_now() else "🔴 Завершено"
        text = (
            f"🎉 <b>{escape(ev.name)}</b>\n"
            f"Скидка: {ev.discount_percent}% | {status}\n"
            f"До: {ev.end_date.strftime('%d.%m.%Y %H:%M')}"
        )
        kb_rows = []
        if ev.is_active and ev.end_date > utc_now():
            kb_rows.append([InlineKeyboardButton(text="🛑 Остановить", callback_data=f"event_stop:{ev.id}")])
        kb_rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_events_menu")])
        await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await callback.answer()


# =========================
# SALES
# =========================
@router.callback_query(F.data == "admin_sales")
async def admin_sales_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    async with async_session() as session:
        sale = await get_active_sale(session)
    text = "🛍 <b>Глобальные акции</b>\n\n" + (f"🟢 Активна: {sale.discount_percent}%" if sale else "🔴 Нет активных акций.")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🛑 Остановить", callback_data="admin_sale_stop")] if sale else [InlineKeyboardButton(text="➕ Создать", callback_data="admin_sale_create")], [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")]])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_sale_stop")
async def admin_sale_stop(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    async with async_session() as session:
        sale = await get_active_sale(session)
        if sale:
            sale.end_date = utc_now()
            await session.commit()
    await admin_sales_start(callback, None)


@router.callback_query(F.data == "admin_sale_create")
async def admin_sale_create(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    await state.set_state(SaleState.waiting_percent)
    await _safe_edit(callback, "Введи % (1-99):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="admin_center")]]))


@router.message(SaleState.waiting_percent)
async def admin_sale_percent(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    if not message.text.isdigit(): return
    await state.update_data(discount_percent=int(message.text))
    await state.set_state(SaleState.waiting_scope)
    await message.answer("Сфера применения:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Все", callback_data="sale_scope:all")]]))


@router.callback_query(SaleState.waiting_scope, F.data.startswith("sale_scope:"))
async def admin_sale_scope(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    await state.update_data(applies_to=callback.data.split(":")[1])
    await state.set_state(SaleState.waiting_duration)
    await _safe_edit(callback, "Длительность (часов):")
    await callback.answer()


@router.message(SaleState.waiting_duration)
async def admin_sale_duration(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    if not message.text.isdigit(): return
    await state.update_data(duration_hours=int(message.text))
    await state.set_state(SaleState.waiting_text)
    await message.answer("Текст рассылки:")


@router.message(SaleState.waiting_text)
async def admin_sale_finish(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    data = await state.get_data()
    end_date = utc_now() + timedelta(hours=data["duration_hours"])
    async with async_session() as session:
        sale = ActiveSale(discount_percent=data["discount_percent"], applies_to=data["applies_to"], end_date=end_date, announcement=message.text)
        session.add(sale)
        await session.commit()
    await state.clear()
    
    # Рассылаем уведомление всем пользователям
    from app.services import broadcast_sale_to_users
    try:
        sent = await broadcast_sale_to_users(message.bot, sale)
        await message.answer(f"✅ Акция запущена!\n📢 Рассылка: {sent} пользователей.")
    except Exception as e:
        logger.error(f"Ошибка рассылки акции: {e}")
        await message.answer(f"✅ Акция запущена!\n⚠️ Рассылка не удалась: {e}")


# =========================
# BROADCAST
# =========================
@router.callback_query(F.data == "admin_direct_message_all")
async def admin_direct_message_all(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        return
    await state.clear()
    await state.set_state(AdminBroadcastState.waiting_text)
    await state.update_data(broadcast_mode="admin_direct")
    await _safe_edit(
        callback,
        "📨 <b>Сообщение всем от админа</b>\n\n"
        "Напиши текст, который бот отправит всем активным пользователям.\n\n"
        "Пользователь увидит это в формате:\n"
        "<code>📢 Тебе сообщение от админа: ...</code>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_center")]
        ])
    )
    await callback.answer()


@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Еженедельная халява", callback_data="admin_broadcast_tpl:bonus")],
        [InlineKeyboardButton(text="🎰 Реклама Секслото", callback_data="admin_broadcast_tpl:lottery")],
        [InlineKeyboardButton(text="💋 Призыв поболтать с Катей", callback_data="admin_broadcast_tpl:katya")],
        [InlineKeyboardButton(text="🎟 Создание промокодов", callback_data="admin_broadcast_tpl:promo")],
        [InlineKeyboardButton(text="🎁 Лутбоксы", callback_data="admin_broadcast_tpl:games")],
        [InlineKeyboardButton(text="👥 Рефералка", callback_data="admin_broadcast_tpl:quests")],
        [InlineKeyboardButton(text="👑 Привилегии VIP-подписки", callback_data="admin_broadcast_tpl:vip")],
        [InlineKeyboardButton(text="🎯 Сегмент: ник есть, покупок 0", callback_data="admin_broadcast_tpl:segment_nopay")],
        [InlineKeyboardButton(text="✍️ Написать свой текст (HTML)", callback_data="admin_broadcast_custom")],
        [InlineKeyboardButton(text="📋 Авто-рассылки (ротация)", callback_data="admin_promo_rot")],
        [InlineKeyboardButton(text="◀️ Назад в админку", callback_data="admin_center")]
    ])

    await _safe_edit(
        callback,
        "📢 <b>Управление рассылками и пуш-уведомлениями</b>\n\n"
        "Выбери готовый шаблон для напоминания пользователям о функциях бота, или напиши свой собственный текст.\n\n"
        "📋 <b>Авто-рассылки (ротация)</b> — сообщения, которые бот сам рассылает всем "
        "каждые 20 мин – 6 ч. Там же можно добавлять свои, редактировать и удалять.",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


# =========================
# АВТО-РАССЫЛКИ (РОТАЦИЯ): список / добавить / править / удалить
# =========================
PROMO_ROT_PAGE_SIZE = 6


def _promo_preview(text: str, n: int = 46) -> str:
    t = " ".join((text or "").split())
    return t[:n] + ("…" if len(t) > n else "")


async def _render_promo_rot_list(callback: CallbackQuery, offset: int = 0):
    """Экран со списком сообщений ротации + кнопки ✏️/🗑 у каждого."""
    from app.services import (
        count_promo_messages, list_promo_messages, get_active_events,
        seed_default_promo_messages,
    )
    async with async_session() as session:
        await seed_default_promo_messages(session)  # первый заход: засеять дефолт
        total = await count_promo_messages(session)
        items = await list_promo_messages(session, offset=offset, limit=PROMO_ROT_PAGE_SIZE)
        events = await get_active_events(session)

    lines = [f"📋 <b>Авто-рассылки (ротация)</b> — {total} шт.\n"]
    lines.append("Бот случайно выбирает одно сообщение и рассылает всем каждые 20 мин – 6 ч.")
    if events:
        lines.append(f"➕ Плюс {len(events)} активное событие — карточки событий крутятся в ротации автоматически.")
    lines.append("")

    kb_rows = []
    for i, m in enumerate(items):
        num = offset + i + 1
        icon = "⚙️" if m.kind == "builtin" else "✍️"
        title_str = escape(m.title) if m.title else "Без названия"
        lines.append(f"{num}. {icon} <b>{title_str}</b>\n   <code>{escape(_promo_preview(m.text))}</code>")
        kb_rows.append([
            InlineKeyboardButton(text=f"✏️ Редактировать {num}", callback_data=f"admin_promo_rot_edit:{m.id}"),
            InlineKeyboardButton(text=f"🗑 Удалить {num}", callback_data=f"admin_promo_rot_del:{m.id}"),
        ])

    if not items and total == 0:
        lines.append("<i>Список пуст — добавь первое сообщение кнопкой ниже.</i>")

    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_promo_rot_pg:{max(0, offset - PROMO_ROT_PAGE_SIZE)}"))
    if offset + PROMO_ROT_PAGE_SIZE < total:
        nav.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"admin_promo_rot_pg:{offset + PROMO_ROT_PAGE_SIZE}"))
    if nav:
        kb_rows.append(nav)

    kb_rows.append([InlineKeyboardButton(text="➕ Добавить своё сообщение", callback_data="admin_promo_rot_add")])
    kb_rows.append([InlineKeyboardButton(text="◀️ К рассылкам", callback_data="admin_broadcast")])

    await _safe_edit(
        callback,
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_promo_rot")
async def admin_promo_rot(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    await _render_promo_rot_list(callback, 0)


@router.callback_query(F.data.startswith("admin_promo_rot_pg:"))
async def admin_promo_rot_page(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    offset = int(callback.data.split(":", 1)[1])
    await _render_promo_rot_list(callback, offset)


@router.callback_query(F.data == "admin_promo_rot_add")
async def admin_promo_rot_add(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(PromoRotationState.waiting_add_title)
    await callback.message.answer(
        "➕ <b>Новая постоянная промо-рассылка</b>\n\n"
        "<b>Шаг 1 из 2:</b> Введи название рассылки (например, <code>Отзыв</code>):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_promo_rot")
        ]]),
    )
    await callback.answer()


@router.message(PromoRotationState.waiting_add_title)
async def promo_rot_add_title_process(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    title_val = (message.text or "").strip()
    if not title_val:
        await message.answer("❌ Название не может быть пустым.")
        return
    if len(title_val) > 100:
        await message.answer("❌ Слишком длинное название (макс. 100 символов).")
        return
    await state.update_data(add_promo_title=title_val)
    await state.set_state(PromoRotationState.waiting_add_text)
    await message.answer(
        f"➕ <b>Новая постоянная промо-рассылка («{escape(title_val)}»)</b>\n\n"
        "<b>Шаг 2 из 2:</b> Отправь текст рассылки (поддерживается HTML-разметка):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_promo_rot")
        ]]),
    )


@router.message(PromoRotationState.waiting_add_text)
async def promo_rot_add_process(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    text_val = (message.text or "").strip()
    if not text_val:
        await message.answer("❌ Текст не может быть пустым.")
        return
    if len(text_val) > 3500:
        await message.answer("❌ Слишком длинно (макс. 3500 символов).")
        return
    data = await state.get_data()
    title_val = data.get("add_promo_title")
    from app.services import add_promo_message
    async with async_session() as session:
        msg = await add_promo_message(session, text_val, title=title_val, kind="custom")
    await state.clear()
    title_disp = f"«{escape(title_val)}» " if title_val else ""
    await message.answer(
        f"✅ <b>Рассылка {title_disp}добавлена в ротацию (№{msg.id}).</b>\n\n"
        f"----------------------------------\n"
        f"{text_val}\n"
        f"----------------------------------\n\n"
        f"Теперь она будет регулярно приходить пользователям наравне с остальными промо-рассылками.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📋 К списку ротации", callback_data="admin_promo_rot")
        ]]),
    )


@router.callback_query(F.data.startswith("admin_promo_rot_edit:"))
async def admin_promo_rot_edit(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    msg_id = int(callback.data.split(":", 1)[1])
    from app.services import get_promo_message
    async with async_session() as session:
        msg = await get_promo_message(session, msg_id)
    if not msg:
        await callback.answer("Сообщение не найдено (уже удалено?)", show_alert=True)
        return
    
    title_str = escape(msg.title) if msg.title else "<i>Без названия</i>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить название", callback_data=f"admin_promo_rot_edittitle:{msg.id}")],
        [InlineKeyboardButton(text="📝 Изменить текст", callback_data=f"admin_promo_rot_edittext:{msg.id}")],
        [InlineKeyboardButton(text="◀️ К списку ротации", callback_data="admin_promo_rot")],
    ])
    await _safe_edit(
        callback,
        f"✏️ <b>Редактирование рассылки №{msg.id}</b>\n\n"
        f"<b>Название:</b> {title_str}\n\n"
        f"<b>Текст:</b>\n<pre>{escape(msg.text)}</pre>",
        parse_mode="HTML",
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_promo_rot_edittitle:"))
async def admin_promo_rot_edit_title_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    msg_id = int(callback.data.split(":", 1)[1])
    await state.set_state(PromoRotationState.waiting_edit_title)
    await state.update_data(promo_edit_id=msg_id)
    await callback.message.answer(
        f"✏️ <b>Редактирование названия рассылки №{msg_id}</b>\n\n"
        f"Отправь новое название (например, <code>Отзыв</code>):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_promo_rot")
        ]]),
    )
    await callback.answer()


@router.message(PromoRotationState.waiting_edit_title)
async def promo_rot_edit_title_process(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    title_val = (message.text or "").strip()
    if not title_val:
        await message.answer("❌ Название не может быть пустым.")
        return
    if len(title_val) > 100:
        await message.answer("❌ Слишком длинное название (макс. 100 символов).")
        return
    data = await state.get_data()
    msg_id = int(data.get("promo_edit_id") or 0)
    from app.services import update_promo_message
    async with async_session() as session:
        ok = await update_promo_message(session, msg_id, title=title_val)
    await state.clear()
    await message.answer(
        f"✅ <b>Название рассылки №{msg_id} изменено на «{escape(title_val)}».</b>" if ok
        else "⚠️ Сообщение не найдено — возможно, его уже удалили.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📋 К списку ротации", callback_data="admin_promo_rot")
        ]]),
    )


@router.callback_query(F.data.startswith("admin_promo_rot_edittext:"))
async def admin_promo_rot_edit_text_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    msg_id = int(callback.data.split(":", 1)[1])
    from app.services import get_promo_message
    async with async_session() as session:
        msg = await get_promo_message(session, msg_id)
        text_val = msg.text if msg else None
    if text_val is None:
        await callback.answer("Сообщение не найдено (уже удалено?)", show_alert=True)
        return
    await state.set_state(PromoRotationState.waiting_edit_text)
    await state.update_data(promo_edit_id=msg_id)
    await callback.message.answer(
        f"📝 <b>Редактирование текста рассылки №{msg_id}</b>\n\n"
        f"Текущий текст:\n<pre>{escape(text_val)}</pre>\n\n"
        f"Отправь новый текст (HTML-разметка поддерживается):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_promo_rot")
        ]]),
    )
    await callback.answer()


@router.message(PromoRotationState.waiting_edit_text)
async def promo_rot_edit_process(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    text_val = (message.text or "").strip()
    if not text_val:
        await message.answer("❌ Текст не может быть пустым.")
        return
    if len(text_val) > 3500:
        await message.answer("❌ Слишком длинно (макс. 3500 символов).")
        return
    data = await state.get_data()
    msg_id = int(data.get("promo_edit_id") or 0)
    from app.services import update_promo_message
    async with async_session() as session:
        ok = await update_promo_message(session, msg_id, text=text_val)
    await state.clear()
    await message.answer(
        ("✅ <b>Текст рассылки обновлён.</b>\n\n----------------------------------\n" + text_val) if ok
        else "⚠️ Сообщение не найдено — возможно, его уже удалили.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📋 К списку ротации", callback_data="admin_promo_rot")
        ]]),
    )


@router.callback_query(F.data.startswith("admin_promo_rot_del:"))
async def admin_promo_rot_delete_ask(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    msg_id = int(callback.data.split(":", 1)[1])
    from app.services import get_promo_message
    async with async_session() as session:
        msg = await get_promo_message(session, msg_id)
    if not msg:
        await callback.answer("Сообщение не найдено (уже удалено?)", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Да, удалить", callback_data=f"admin_promo_rot_delok:{msg_id}")],
        [InlineKeyboardButton(text="◀️ Назад к списку", callback_data="admin_promo_rot")],
    ])
    title_disp = f"«{escape(msg.title)}» " if msg.title else ""
    await _safe_edit(
        callback,
        f"🗑 <b>Удалить рассылку {title_disp}(№{msg_id}) из ротации?</b>\n\n"
        f"----------------------------------\n"
        f"<code>{escape(_promo_preview(msg.text, 300))}</code>\n"
        f"----------------------------------\n\n"
        f"Она больше не будет приходить пользователям автоматически.",
        parse_mode="HTML",
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_promo_rot_delok:"))
async def admin_promo_rot_delete_do(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    msg_id = int(callback.data.split(":", 1)[1])
    from app.services import delete_promo_message
    async with async_session() as session:
        await delete_promo_message(session, msg_id)
    # Обновлённый список сам подтверждает удаление (двойной answer не нужен).
    await _render_promo_rot_list(callback, 0)


@router.callback_query(F.data.startswith("admin_broadcast_tpl:"))
async def cb_admin_broadcast_tpl(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    tpl_name = callback.data.split(":", 1)[1]
    
    templates = {
        "bonus": (
            "🎁 <b>Еженедельная халява уже близко!</b>\n\n"
            "Раз в неделю мы рассылаем секретный промокод на бесплатные монеты. Следи за сообщениями бота и не пропусти раздачу! 💰\n\n"
            "👉 Перейди в меню <b>🎟 Промокоды</b>"
        ),
        "lottery": (
            "🎰 <b>Секслото — розыгрыш монет</b>\n\n"
            "Новый раунд уже открыт! Купи билет за монеты и следи за розыгрышем в Live. Размер призового фонда зависит от количества купленных билетов. 🎡\n\n"
            "👉 Зайди в меню <b>🎮 Игры ➔ 🎰 Секслото</b>"
        ),
        "promo": (
            "🎟 <b>Создавай свои промокоды за Stars!</b>\n\n"
            "Хочешь порадовать подписчиков своего канала или друзей? Создай свой уникальный промокод на любую сумму монет и подари его им! 🎁\n\n"
            "👉 Перейди в меню <b>🎟 Промокоды</b>"
        ),
        "games": (
            "🎁 <b>Открой лутбокс!</b>\n\n"
            "Иногда один лутбокс — это быстрый способ вернуться в игру и сорвать красивый дроп монет. Проверь удачу!\n\n"
            "👉 Перейди в меню <b>🎮 Игры</b>"
        ),
        "quests": (
            "👥 <b>Монеты закончились? Позови друзей!</b>\n\n"
            "Разошли свою реферальную ссылку друзьям и получай награды за новых активных пользователей. Это самый быстрый способ снова пополнить баланс.\n\n"
            "👉 Перейди в меню <b>👥 Рефералы</b>"
        ),
        "vip": (
            "👑 <b>Получи статус VIP-пользователя!</b>\n\n"
            "VIP даёт множитель начисления монет ×2, скидку на просмотр видео, просмотр фото без дневного лимита и дополнительные бонусы в экономике. ⭐\n\n"
            "👉 Открой <b>🛍 Магазин</b> в главном меню!"
        )
    }

    segment_mode = (tpl_name == "segment_nopay")
    seg_count = 0
    if segment_mode:
        from app.config import STARTER_PACK_STARS, STARTER_PACK_COINS
        from app.services import get_never_payer_nicknamed_targets
        async with async_session() as session:
            seg_count = len(await get_never_payer_nicknamed_targets(session))
        templates["segment_nopay"] = (
            "🎁 <b>Специальное предложение — только для тебя!</b>\n\n"
            "Ты уже освоился в боте, но ещё ни разу не пополнял баланс. "
            f"Для первого платежа мы собрали старт-пак: <b>{STARTER_PACK_COINS} монет всего за {STARTER_PACK_STARS} Stars</b> — "
            "выгоднее любого другого пакета. Доступен строго один раз!\n\n"
            "👉 Жми <b>💰 Пополнить</b> в главном меню — пакет уже ждёт тебя первым в списке!"
        )
    
    tpl_text = templates.get(tpl_name)
    if not tpl_text:
        await callback.answer("Ошибка шаблона", show_alert=True)
        return
        
    await state.update_data(
        broadcast_text=tpl_text,
        broadcast_mode="promo",
        broadcast_segment=("nopay" if segment_mode else ""),
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Запустить рассылку", callback_data="admin_broadcast_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_broadcast")]
    ])
    
    confirm_tail = (
        f"Отправить это <b>{seg_count}</b> пользователям из сегмента «все с ником, 0 покупок»?"
        if segment_mode else
        "Ты действительно хочешь отправить это сообщение всем активным пользователям?"
    )
    await _safe_edit(
        callback,
        f"📢 <b>Предпросмотр рассылки:</b>\n\n"
        f"----------------------------------\n"
        f"{tpl_text}\n"
        f"----------------------------------\n\n"
        f"{confirm_tail}",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data == "admin_broadcast_custom")
async def cb_admin_broadcast_custom(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    await state.set_state(AdminBroadcastState.waiting_text)
    await state.update_data(broadcast_mode="promo")
    await callback.message.answer("📢 Введи твой пользовательский текст для промо-рассылки (поддерживается HTML-разметка):")
    await callback.answer()


@router.message(AdminBroadcastState.waiting_text)
async def process_broadcast(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    text_val = (message.text or "").strip()
    if not text_val:
        await message.answer("❌ Текст не может быть пустым.")
        return

    data = await state.get_data()
    mode = data.get("broadcast_mode", "promo")
    await state.update_data(broadcast_text=text_val)

    if mode == "admin_direct":
        preview_text = (
            "📢 <b>Тебе сообщение от админа:</b>\n\n"
            f"{text_val}"
        )
        cancel_target = "admin_center"
        header = "📨 <b>Предпросмотр сообщения от админа:</b>"
    else:
        preview_text = text_val
        cancel_target = "admin_broadcast"
        header = "📢 <b>Предпросмотр твоей рассылки:</b>"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Запустить рассылку", callback_data="admin_broadcast_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=cancel_target)]
    ])

    await message.answer(
        f"{header}\n\n"
        f"----------------------------------\n"
        f"{preview_text}\n"
        f"----------------------------------\n\n"
        f"Ты действительно хочешь отправить это сообщение всем активным пользователям?",
        parse_mode="HTML",
        reply_markup=kb
    )


@router.callback_query(F.data == "admin_broadcast_confirm")
async def cb_admin_broadcast_confirm(callback: CallbackQuery, state: FSMContext, bot):
    if not await check_admin(callback.from_user.id):
        return

    data = await state.get_data()
    text_val = data.get("broadcast_text")
    mode = data.get("broadcast_mode", "promo")
    segment = data.get("broadcast_segment", "") or ""
    await state.clear()

    if not text_val:
        await callback.answer("Ошибка: Текст пуст.", show_alert=True)
        return

    if mode == "admin_direct":
        outgoing_text = f"📢 <b>Тебе сообщение от админа:</b>\n\n{text_val}"
        start_text = "⏳ <b>Сообщение от админа отправляется всем активным пользователям...</b>"
        done_text = "✅ <b>Сообщение от админа успешно отправлено!</b>"
    else:
        outgoing_text = text_val
        start_text = "⏳ <b>Рассылка запущена в фоновом режиме...</b>"
        done_text = "✅ <b>Рассылка успешно завершена!</b>"

    await callback.message.edit_text(start_text, parse_mode="HTML")
    await callback.answer()

    async def run_broadcast_task():
        async with async_session() as session:
            if segment == "nopay":
                from app.services import get_never_payer_nicknamed_targets
                users = await get_never_payer_nicknamed_targets(session)
            else:
                users = (await session.execute(select(User.telegram_id).where(User.status == "active"))).scalars().all()

        sent = 0
        for tid in users:
            try:
                await bot.send_message(tid, outgoing_text, parse_mode="HTML")
                sent += 1
                if sent % 30 == 0:
                    await asyncio.sleep(0.5)
            except Exception:
                pass

        try:
            await bot.send_message(
                callback.from_user.id,
                f"{done_text}\n\n"
                f"Сообщение доставлено <b>{sent}</b> активным пользователям.",
                parse_mode="HTML"
            )
        except Exception:
            pass

    asyncio.create_task(run_broadcast_task())


# =========================
# USER MGMT
# =========================
@router.callback_query(F.data.startswith("admin_manage_users"))
async def admin_manage_users(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    await state.clear()
    
    parts = callback.data.split(":")
    offset = int(parts[1]) if len(parts) > 1 else 0
    limit = 8
    
    async with async_session() as session:
        total = (await session.execute(select(func.count(User.id)))).scalar_one()
        users = (await session.execute(select(User).order_by(User.id.desc()).offset(offset).limit(limit))).scalars().all()
        
    text = f"👥 <b>Управление пользователями ({offset + 1}-{min(offset + limit, total)} из {total})</b>\n\nВыбери пользователя для управления:"
    
    kb_rows = []
    for u in users:
        name = u.display_name or u.username or f"User {u.telegram_id}"
        status_icon = "🚫" if u.status == "banned" else "👤"
        kb_rows.append([InlineKeyboardButton(
            text=f"{status_icon} {name[:18]} (ID: {u.telegram_id})",
            callback_data=f"admin_select_user:{u.id}"
        )])
        
    # Navigation row
    nav_row = []
    if offset > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"admin_manage_users:{max(0, offset - limit)}"))
    if offset + limit < total:
        nav_row.append(InlineKeyboardButton(text="Вперед ▶️", callback_data=f"admin_manage_users:{offset + limit}"))
        
    if nav_row:
        kb_rows.append(nav_row)
        
    kb_rows.append([InlineKeyboardButton(text="🔎 Поиск по нику/ID", callback_data="admin_user_search")])
    kb_rows.append([InlineKeyboardButton(text="◀ Назад в админку", callback_data="admin_center")])
    
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await callback.answer()


@router.callback_query(F.data == "admin_user_search")
async def admin_user_search_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AdminUserState.waiting_user_search)
    await callback.message.answer(
        "🔎 <b>Поиск пользователя</b>\n\n"
        "Введи ник (можно частично, регистр не важен) или Telegram ID.\n"
        "Покажу до 8 совпадений:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_manage_users:0")
        ]]),
    )
    await callback.answer()


@router.message(AdminUserState.waiting_user_search)
async def admin_user_search_process(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    from app.services import search_users_admin
    query_text = (message.text or "").strip()
    await state.clear()

    async with async_session() as session:
        found = await search_users_admin(session, query_text)

    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀ Назад к списку", callback_data="admin_manage_users:0")]
    ])
    if not found:
        await message.answer(
            f"🔎 По запросу «{escape(query_text)}» никого не нашлось.",
            parse_mode="HTML",
            reply_markup=back_kb,
        )
        return

    kb_rows = []
    for u in found:
        name = u.display_name or u.username or f"User {u.telegram_id}"
        status_icon = "🚫" if u.status == "banned" else "👤"
        kb_rows.append([InlineKeyboardButton(
            text=f"{status_icon} {name[:24]} (ID: {u.telegram_id})",
            callback_data=f"admin_select_user:{u.id}"
        )])
    kb_rows.append([InlineKeyboardButton(text="◀ Назад к списку", callback_data="admin_manage_users:0")])
    await message.answer(
        f"🔎 <b>Найдено: {len(found)}</b> (показано до 8). Выбери пользователя:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
    )


async def show_user_profile(callback: CallbackQuery, user_id: int):
    async with async_session() as session:
        user = await get_user_by_id(session, user_id)
        if not user:
            return False
            
    from app.user_handlers import is_vip
    status_text = "🚫 Забанен" if user.status == "banned" else "✅ Активен"
    vip_text = "👑 Да" if is_vip(user) else "❌ Нет"
    
    text = (

        f"👤 <b>Управление пользователем:</b> <a href='tg://user?id={user.telegram_id}'>{user.display_name or user.username or user_id}</a>\n\n"

        f"• <b>Telegram ID:</b> <code>{user.telegram_id}</code>\n"

        f"• <b>Username:</b> {('@' + user.username) if user.username else 'отсутствует'}\n"

        f"• <b>Никнейм в БД:</b> {user.display_name or 'отсутствует'}\n"

        f"• <b>Баланс:</b> <b>{user.balance}</b> монет\n"

        f"• <b>Серия бонусов:</b> {user.bonus_streak} дней\n"

        f"• <b>Уровень/XP:</b> Lvl {user.level} ({user.xp} XP)\n"

        f"• <b>Статус:</b> {status_text}\n"

        f"• <b>VIP статус:</b> {vip_text}\n"

    )
    
    ban_label = "✅ Разбанить" if user.status == "banned" else "🚫 Забанить"
    
    kb_rows = [
        [
            InlineKeyboardButton(text="✏️ Поменять ник", callback_data=f"admin_user_edit_nick_start:{user_id}"),
            InlineKeyboardButton(text="💰 Выдать монеты", callback_data=f"admin_user_give_coins_start:{user_id}"),
        ],
        [
            InlineKeyboardButton(text=ban_label, callback_data=f"admin_user_toggle_ban:{user_id}"),
            InlineKeyboardButton(text="✉️ Личное сообщение", callback_data=f"admin_user_send_msg_start:{user_id}"),
        ],
        [InlineKeyboardButton(text="🔎 Всеобъемлющее досье", callback_data=f"admin_user_dossier_detailed:{user_id}")],
    ]
    if is_super_admin(callback.from_user.id):
        kb_rows.append([InlineKeyboardButton(text="📄 Экспорт PDF", callback_data=f"admin_user_export_pdf:{user_id}")])
    kb_rows.append([InlineKeyboardButton(text="◀️ Назад к списку", callback_data="admin_manage_users:0")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    return True


@router.callback_query(F.data.startswith("admin_select_user:"))
async def admin_select_user(callback: CallbackQuery):

    if not await check_admin(callback.from_user.id): return
    
    user_id = int(callback.data.split(":", 1)[1])
    async with async_session() as session:
        user = await get_user_by_id(session, user_id)
        if not user:
            await callback.answer("Пользователь не найден в базе.", show_alert=True)
            return
            
    from app.user_handlers import is_vip
    status_text = "🚫 Забанен" if user.status == "banned" else "✅ Активен"
    vip_text = "👑 Да" if is_vip(user) else "❌ Нет"
    
    text = (

        f"👤 <b>Управление пользователем:</b> <a href='tg://user?id={user.telegram_id}'>{user.display_name or user.username or user_id}</a>\n\n"

        f"• <b>Telegram ID:</b> <code>{user.telegram_id}</code>\n"

        f"• <b>Username:</b> {('@' + user.username) if user.username else 'отсутствует'}\n"

        f"• <b>Никнейм в БД:</b> {user.display_name or 'отсутствует'}\n"

        f"• <b>Баланс:</b> <b>{user.balance}</b> монет\n"

        f"• <b>Серия бонусов:</b> {user.bonus_streak} дней\n"

        f"• <b>Уровень/XP:</b> Lvl {user.level} ({user.xp} XP)\n"

        f"• <b>Статус:</b> {status_text}\n"

        f"• <b>VIP статус:</b> {vip_text}\n"

    )
    
    ban_label = "✅ Разбанить" if user.status == "banned" else "🚫 Забанить"
    
    kb_rows = [
        [
            InlineKeyboardButton(text="✏️ Поменять ник", callback_data=f"admin_user_edit_nick_start:{user_id}"),
            InlineKeyboardButton(text="💰 Выдать монеты", callback_data=f"admin_user_give_coins_start:{user_id}"),
        ],
        [
            InlineKeyboardButton(text=ban_label, callback_data=f"admin_user_toggle_ban:{user_id}"),
            InlineKeyboardButton(text="✉️ Личное сообщение", callback_data=f"admin_user_send_msg_start:{user_id}"),
        ],
        [InlineKeyboardButton(text="🔎 Всеобъемлющее досье", callback_data=f"admin_user_dossier_detailed:{user_id}")],
    ]
    if is_super_admin(callback.from_user.id):
        kb_rows.append([InlineKeyboardButton(text="📄 Экспорт PDF", callback_data=f"admin_user_export_pdf:{user_id}")])
    kb_rows.append([InlineKeyboardButton(text="◀️ Назад к списку", callback_data="admin_manage_users:0")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_user_export_pdf:"))
async def admin_user_export_pdf(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Только супер-админ.", show_alert=True)
        return

    user_id = int(callback.data.split(":", 1)[1])
    await callback.answer()
    await callback.message.answer("⏳ Готовлю подробный PDF-отчёт по пользователю...")

    async def _runner() -> None:
        pdf_path = None
        try:
            async with async_session() as session:
                user = await get_user_by_id(session, user_id)
                if not user:
                    await callback.bot.send_message(callback.from_user.id, "❌ Пользователь не найден.")
                    return
                telegram_id = user.telegram_id

            pdf_path, filename = await build_user_report_pdf(telegram_id)
            await callback.bot.send_document(
                callback.from_user.id,
                FSInputFile(str(pdf_path), filename=filename),
                caption=f"📄 PDF-отчёт по пользователю <code>{telegram_id}</code> готов.",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.exception("Failed to build admin user PDF report")
            await callback.bot.send_message(
                callback.from_user.id,
                f"❌ Не удалось собрать PDF по пользователю. Ошибка: {escape(str(e))}",
                parse_mode="HTML",
            )
        finally:
            if pdf_path:
                try:
                    os.remove(pdf_path)
                except Exception:
                    pass

    asyncio.create_task(_runner())


@router.callback_query(F.data.startswith("admin_user_edit_nick_start:"))
async def cb_admin_user_edit_nick_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    user_id = int(callback.data.split(":", 1)[1])
    await state.update_data(target_user_id=user_id)
    await state.set_state(AdminUserState.waiting_new_nickname)
    await _safe_edit(
        callback,
        "✏️ <b>Изменение никнейма пользователя</b>\n\n"
        "Отправь мне <b>новый никнейм</b> для этого пользователя:\n"
        "• От 4 до 20 символов\n"
        "• Буквы, цифры, _ и -\n"
        "• Без точек, ? и User&lt;id&gt;",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin_select_user:{user_id}")]
        ])
    )
    await callback.answer()


@router.message(AdminUserState.waiting_new_nickname)
async def process_admin_user_edit_nick(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    new_nick = (message.text or "").strip()
    
    data = await state.get_data()
    user_id = data.get("target_user_id")
    if not user_id:
        await state.clear()
        return
        
    from app.services import validate_nickname_format, is_placeholder_nickname
    ok, err = validate_nickname_format(new_nick)
    if not ok:
        await message.answer(f"❌ {err}\nВведи снова:")
        return

    async with async_session() as session:
        user = await get_user_by_id(session, user_id)
        if not user:
            await message.answer("Пользователь не найден.")
            await state.clear()
            return

        if is_placeholder_nickname(new_nick, user.telegram_id):
            await message.answer("❌ Ник вида User&lt;id&gt; запрещён. Введи нормальный ник:")
            return

        exists = (await session.execute(
            select(User).where(User.display_name == new_nick, User.id != user.id)
        )).scalars().first()
        if exists:
            await message.answer("❌ Этот ник уже занят другим пользователем. Введи другой ник:")
            return

        old_nick = user.display_name
        user.display_name = new_nick
        user.nickname_set = True
        await session.commit()
        
    await message.answer(
        f"✅ Никнейм пользователя успешно изменен!\n\n"
        f"• Старый ник: <b>{old_nick or 'не задан'}</b>\n"
        f"• Новый ник: <b>{new_nick}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад к пользователю", callback_data=f"admin_select_user:{user_id}")]
        ])
    )
    await state.clear()


@router.callback_query(F.data.startswith("admin_user_give_coins_start:"))
async def cb_admin_user_give_coins_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    user_id = int(callback.data.split(":", 1)[1])
    await state.update_data(target_user_id=user_id)
    await state.set_state(AdminUserState.waiting_coins_amount)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="+10 🪙", callback_data=f"admin_user_give_coins_exec:{user_id}:10"),
            InlineKeyboardButton(text="+50 🪙", callback_data=f"admin_user_give_coins_exec:{user_id}:50"),
            InlineKeyboardButton(text="+100 🪙", callback_data=f"admin_user_give_coins_exec:{user_id}:100"),
            InlineKeyboardButton(text="+500 🪙", callback_data=f"admin_user_give_coins_exec:{user_id}:500"),
        ],
        [
            InlineKeyboardButton(text="-10 🪙", callback_data=f"admin_user_give_coins_exec:{user_id}:-10"),
            InlineKeyboardButton(text="-50 🪙", callback_data=f"admin_user_give_coins_exec:{user_id}:-50"),
            InlineKeyboardButton(text="-100 🪙", callback_data=f"admin_user_give_coins_exec:{user_id}:-100"),
            InlineKeyboardButton(text="-500 🪙", callback_data=f"admin_user_give_coins_exec:{user_id}:-500"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin_select_user:{user_id}")]
    ])
    
    await _safe_edit(
        callback,
        "💰 <b>Начисление или списание монет</b>\n\n"
        "Используй быстрые кнопки ниже для начисления/списания монет в один клик,\n"
        "либо отправь число сообщением (например, <code>150</code> или <code>-50</code>).",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


async def _apply_admin_balance_change(bot, admin_telegram_id: int, user_id: int, amount: Decimal, details: str) -> User:
    async with async_session() as session:
        admin = await get_user(session, admin_telegram_id)
        try:
            user = await adjust_balance_by_admin(
                session,
                user_id,
                amount,
                admin.id if admin else None,
                details=f"{details}; admin_telegram_id={admin_telegram_id}",
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        telegram_id = user.telegram_id
        new_balance = user.balance

    action = "начислил" if amount > 0 else "списал"
    try:
        await bot.send_message(
            telegram_id,
            f"💰 Администратор {action} <b>{abs(amount)}</b> монет.\n"
            f"Твой баланс: <b>{new_balance}</b> монет.",
            parse_mode="HTML",
        )
    except Exception:
        pass
    return user


@router.callback_query(F.data.startswith("admin_user_give_coins_exec:"))
async def cb_admin_user_give_coins_exec(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    parts = callback.data.split(":")
    user_id = int(parts[1])
    amount = Decimal(parts[2])
    try:
        user = await _apply_admin_balance_change(
            callback.bot, callback.from_user.id, user_id, amount, "Быстрые кнопки баланса"
        )
    except AdminBalanceError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    except Exception:
        logger.exception("Admin balance change failed")
        await callback.answer("Не удалось изменить баланс. Попробуй ещё раз.", show_alert=True)
        return

    await callback.answer(
        f"✅ {'Начислено' if amount > 0 else 'Списано'} {abs(amount)}. Баланс: {user.balance}",
        show_alert=True,
    )
    await state.clear()
    await show_user_profile(callback, user_id)


@router.message(AdminUserState.waiting_coins_amount)
async def process_admin_user_give_coins(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    val = (message.text or "").strip().replace(",", ".")
    try:
        amount = Decimal(val)
    except Exception:
        await message.answer("❌ Некорректная сумма. Отправь число, например <code>100</code> или <code>-50</code>.", parse_mode="HTML")
        return

    data = await state.get_data()
    user_id = data.get("target_user_id")
    if not user_id:
        await state.clear()
        await message.answer("❌ Сессия устарела. Открой пользователя в админке заново.")
        return

    try:
        user = await _apply_admin_balance_change(
            message.bot, message.from_user.id, user_id, amount, "Ручное изменение баланса"
        )
    except AdminBalanceError as exc:
        await message.answer(f"❌ {escape(str(exc))}", parse_mode="HTML")
        return
    except Exception:
        logger.exception("Admin balance change failed")
        await message.answer("❌ Не удалось изменить баланс. Попробуй ещё раз.")
        return

    status_msg = "начислено" if amount > 0 else "списано"
    await message.answer(
        f"✅ Пользователю {status_msg} <b>{abs(amount)}</b> монет.\n\n"
        f"• Новый баланс: <b>{user.balance}</b> монет.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад к пользователю", callback_data=f"admin_select_user:{user_id}")]
        ]),
    )
    await state.clear()


@router.callback_query(F.data.startswith("admin_user_toggle_ban:"))
async def cb_admin_user_toggle_ban(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    
    user_id = int(callback.data.split(":", 1)[1])
    async with async_session() as session:
        user = await get_user_by_id(session, user_id)
        if not user:
            await callback.answer("Пользователь не найден.")
            return
            
        if user.status == "banned":
            user.status = "active"
            action = "unbanned"
            msg = f"Пользователь {user.display_name or user_id} разбанен."
        else:
            user.status = "banned"
            action = "banned"
            msg = f"Пользователь {user.display_name or user_id} заблокирован!"
            
        await session.commit()
        await callback.answer(msg, show_alert=True)
        
    await show_user_profile(callback, user_id)


@router.callback_query(F.data.startswith("admin_user_send_msg_start:"))
async def cb_admin_user_send_msg_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    user_id = int(callback.data.split(":", 1)[1])
    await state.update_data(target_user_id=user_id)
    await state.set_state(AdminUserState.waiting_message_text)
    await _safe_edit(
        callback,
        "✉️ <b>Личное сообщение от бота</b>\n\n"
        "Отправь мне текст сообщения, которое хочешь доставить этому пользователю лично от имени бота:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin_select_user:{user_id}")]
        ])
    )
    await callback.answer()


@router.message(AdminUserState.waiting_message_text)
async def process_admin_user_send_msg(message: Message, state: FSMContext, bot):
    if not await check_admin(message.from_user.id):
        return
    text_val = (message.text or "").strip()
    if not text_val:
        await message.answer("❌ Сообщение не может быть пустым. Введи текст:")
        return

    data = await state.get_data()
    user_id = data.get("target_user_id")
    if not user_id:
        await state.clear()
        return

    async with async_session() as session:
        user = await get_user_by_id(session, user_id)
        if not user:
            await message.answer("❌ Пользователь не найден.")
            await state.clear()
            return
        telegram_id = user.telegram_id

    try:
        await bot.send_message(
            telegram_id,
            f"✉️ <b>Сообщение от администрации бота:</b>\n\n{text_val}",
            parse_mode="HTML",
        )
        await message.answer(
            "✅ Сообщение успешно отправлено в личные сообщения пользователю!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ К админам", callback_data="admin_manage_users:0")]
            ])
        )
    except Exception as e:
        await message.answer(
            f"❌ Не удалось отправить сообщение в Telegram. Ошибка: {e}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ К админам", callback_data="admin_manage_users:0")]
            ])
        )
    await state.clear()


@router.callback_query(F.data.startswith("admin_user_dossier_detailed:"))
async def cb_admin_user_dossier_detailed(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    
    user_id = int(callback.data.split(":", 1)[1])
    async with async_session() as session:
        d = await get_user_dossier(session, user_id)
        if not d:
            await callback.answer("Пользователь не найден.", show_alert=True)
            return
            
    from app.user_handlers import is_vip
    user = d["user"]
    styled_name = await get_styled_display_name(session, user, card=True)
    
    text = (
        f"🔍 <b>ПОЛНОЕ СЛЕДСТВЕННОЕ ДОСЬЕ ПОЛЬЗОВАТЕЛЯ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Профиль:</b> <a href='tg://user?id={user.telegram_id}'>{styled_name}</a>\n"
        f"• <b>Telegram ID:</b> <code>{user.telegram_id}</code>\n"
        f"• <b>Username:</b> {('@' + user.username) if user.username else 'нет'}\n"
        f"• <b>Никнейм в БД:</b> {user.display_name or 'не установлен'}\n"
        f"• <b>Роль доступа:</b> {d['role_label']}\n"
        f"• <b>Баланс:</b> <b>{user.balance}</b> монет\n"
        f"• <b>VIP статус:</b> {'👑 Активен до ' + user.vip_until.strftime('%d.%m.%Y') if is_vip(user) else '❌ Нет'}\n"
        f"• <b>Рефералы:</b> пригласил <b>{user.referrals_count}</b> юзеров (заработал {user.referral_earnings} монет)\n"
        f"• <b>Дата регистрации:</b> {user.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
        f"📈 <b>Активность и контент:</b>\n"
        f"• <b>Загружено файлов:</b> {d['videos_uploaded']} шт. (Средний рейтинг: ★ {d['avg_rating']})\n"
        f"• <b>Просмотрено файлов:</b> {d['videos_watched']} шт.\n"
        f"• <b>Оставлено комментариев:</b> {d['comments_count']} шт.\n"
        f"• <b>Поставлено реакций:</b> {d['reactions_count']} шт.\n\n"
        f"💰 <b>Финансовый аудит:</b>\n"
        f"• <b>Заработано (за всё время):</b> +{d['total_earned']} монет\n"
        f"• <b>Потрачено (за всё время):</b> {d['total_spent']} монет\n"
        f"• <b>Заработано за неделю:</b> +{d['weekly_earned']} монет\n"
        f"• <b>Потрачено за неделю:</b> {d['weekly_spent']} монет\n"
        f"• <b>Выдано администратором:</b> +{d['admin_given']} монет\n\n"
        f"🎮 <b>Игровая статистика:</b>\n"
        f"• <b>Сыграно игр:</b> {d['games_count']} раз (Чистая прибыль: {d['game_profit']} монет)\n"
        f"• <b>Крупные выигрыши (>50):</b> {len(d['suspicious_games'])} раз\n"
    )
    
    if d["action_logs"]:
        text += "\n📝 <b>Последние действия в системе:</b>\n"
        for log in d["action_logs"][:5]:
            text += f" • <code>{log.created_at.strftime('%H:%M')}</code> | {log.action}: {log.details or ''}\n"
            
    if d["balance_logs"]:
        text += "\n💸 <b>Последние изменения баланса:</b>\n"
        for log in d["balance_logs"][:5]:
            sign = "+" if log.amount >= 0 else ""
            text += f" • <code>{log.created_at.strftime('%d.%m %H:%M')}</code> | <b>{sign}{log.amount}</b> ({log.source})\n"
            
    buttons = []
    if d['videos_uploaded'] > 0:
        buttons.append([InlineKeyboardButton(text="🎬 Загруженные видео", callback_data=f"admin_view_user_videos:{user_id}:0")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад к управлению", callback_data=f"admin_select_user:{user_id}")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    if len(text) > 4000:
        text = text[:4000] + "\n..."
        
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_view_user_videos:"))
async def cb_admin_view_user_videos(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    
    parts = callback.data.split(":")
    user_id = int(parts[1])
    offset = int(parts[2])
    
    async with async_session() as session:
        user = await get_user_by_id(session, user_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
            
        total = (await session.execute(
            select(func.count(Video.id)).where(Video.uploader_user_id == user.id)
        )).scalar_one()
        
        if total == 0:
            await callback.answer("Нет загруженных видео", show_alert=True)
            return
            
        video = (await session.execute(
            select(Video).where(Video.uploader_user_id == user.id).order_by(Video.id.desc()).offset(offset).limit(1)
        )).scalar_one_or_none()
        
        if not video:
            await callback.answer("Видео не найдено", show_alert=True)
            return

    nav_row = []
    if offset > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ Пред.", callback_data=f"admin_view_user_videos:{user_id}:{offset-1}"))
    if offset < total - 1:
        nav_row.append(InlineKeyboardButton(text="След. ▶️", callback_data=f"admin_view_user_videos:{user_id}:{offset+1}"))
        
    kb_rows = []
    if nav_row:
        kb_rows.append(nav_row)
    kb_rows.append([InlineKeyboardButton(text="🔎 Назад к досье", callback_data=f"admin_user_dossier_detailed:{user_id}")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    
    caption = f"🎬 <b>Загруженное видео пользователя</b> ({offset+1}/{total})\nID: {video.id} | Статус: {video.status}\nОпубликовано: {video.created_at.strftime('%d.%m.%Y %H:%M')}"
    
    try:
        await callback.message.delete()
    except Exception:
        pass

    try:

        if video.content_type == "photo":

            await callback.message.answer_photo(

                video.telegram_file_id,

                caption=caption,

                parse_mode="HTML",

                reply_markup=kb

            )

        else:

            await callback.message.answer_video(

                video.telegram_file_id,

                caption=caption,

                parse_mode="HTML",

                reply_markup=kb

            )

    except Exception as e:
        await callback.message.answer(f"⚠️ Ошибка при отправке видео: {e}")

    await callback.answer()


def _format_admin_extended_stats(stats: dict) -> str:
    """Собирает короткую, читаемую без прокрутки сводку для Telegram."""
    audience = stats["audience"]
    content = stats["content"]
    economy = stats["economy"]
    moderation = stats["moderation"]
    engagement = stats["engagement"]

    change = audience["registration_change_pct"]
    if change is None:
        growth = "недостаточно данных для сравнения"
    elif change > 0:
        growth = f"↗️ +{change:.0f}% к предыдущим 7 дням"
    elif change < 0:
        growth = f"↘️ {change:.0f}% к предыдущим 7 дням"
    else:
        growth = "→ без изменений к предыдущим 7 дням"

    pending_content_age = (
        f", старейшая {content_pending_age:.0f} ч"
        if (content_pending_age := moderation["oldest_pending_content_age_hours"]) >= 1 else ""
    )
    pending_report_age = (
        f", старейшая {report_pending_age:.0f} ч"
        if (report_pending_age := moderation["oldest_report_age_hours"]) >= 1 else ""
    )

    return (
        "📊 <b>Оперативная статистика</b>\n"
        "<i>Периодные показатели — за последние 7 дней.</i>\n\n"
        "<b>👥 Аудитория</b>\n"
        f"Всего: <b>{stats['users']}</b> · активных аккаунтов: <b>{audience['active_accounts']}</b> · VIP: <b>{stats['vip']}</b>\n"
        f"Прирост: <b>+{audience['new_users_1d']}</b> за 24 ч · <b>+{audience['new_users_7d']}</b> за 7 дн. ({growth})\n"
        f"Активность: DAU <b>{audience['dau']}</b> · WAU <b>{audience['wau']}</b> · MAU <b>{audience['mau']}</b> · липкость <b>{audience['sticky_pct']:.1f}%</b>\n"
        f"Онбординг: правила <b>{audience['rules_accept_rate_pct']:.1f}%</b> · ник <b>{audience['nickname_rate_pct']:.1f}%</b> · платят <b>{audience['payer_conversion_pct']:.1f}%</b>\n\n"
        "<b>🎬 Контент и вовлечение</b>\n"
        f"За 7 дн.: <b>{content['uploads_7d']}</b> загрузок от <b>{content['creators_7d']}</b> авторов · <b>{content['views_7d']}</b> просмотров от <b>{content['viewers_7d']}</b> зрителей\n"
        f"Обсуждение: <b>{content['comments_7d']}</b> комментариев · <b>{content['reactions_7d']}</b> реакций · средняя оценка <b>{content['average_rating']:.2f}/5</b>\n"
        f"Модерация контента: ожидает <b>{content['pending']}</b>{pending_content_age} · одобрено <b>{content['approval_rate_pct']:.1f}%</b>\n\n"
        "<b>💰 Экономика</b>\n"
        f"Баланс в системе: <b>{stats['total_balance_in_system']:.2f}</b> монет\n"
        f"За 7 дн.: начислено <b>+{economy['coins_in_7d']:.2f}</b> · списано <b>−{economy['coins_out_7d']:.2f}</b> · чистый поток <b>{economy['net_coins_7d']:+.2f}</b>\n"
        f"Оплаты: <b>{economy['payments_7d']}</b> на <b>{economy['paid_stars_7d']}</b> Stars от <b>{economy['payers_7d']}</b> пользователей\n\n"
        "<b>🛡 Очереди и обратная связь</b>\n"
        f"Жалобы: ожидает <b>{moderation['reports_pending']}</b>{pending_report_age} · новых за 7 дн. <b>{moderation['reports_7d']}</b>\n"
        f"Опросы: активных <b>{engagement['polls_active']}</b> · ответов за 7 дн. <b>{engagement['poll_responses_7d']}</b>"
    )


@router.callback_query(F.data == "admin_extended_stats")
async def admin_extended_stats(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        return
    async with async_session() as session:
        stats = await get_admin_extended_stats(session)

    rows = [[InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_extended_stats")]]
    if is_super_admin(callback.from_user.id):
        rows.append([InlineKeyboardButton(text="📊 Экспорт PDF по боту", callback_data="admin_export_bot_pdf")])
        rows.append([InlineKeyboardButton(text="👥 Экспорт PDF по всем пользователям", callback_data="admin_export_all_users_pdf")])
    rows.append([InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")])

    await _safe_edit(
        callback,
        _format_admin_extended_stats(stats),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_export_bot_pdf")
async def admin_export_bot_pdf(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Только супер-админ.", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer("⏳ Готовлю большой отчёт по всему боту: собираю данные и строю диаграммы...")

    async def _runner() -> None:
        pdf_path = None
        try:
            pdf_path, filename = await build_bot_report_pdf()
            await callback.bot.send_document(
                callback.from_user.id,
                FSInputFile(str(pdf_path), filename=filename),
                caption="📊 Подробный PDF-отчёт по боту готов.",
            )
        except Exception as e:
            logger.exception("Failed to build bot PDF report")
            await callback.bot.send_message(
                callback.from_user.id,
                f"❌ Не удалось собрать PDF по боту. Ошибка: {escape(str(e))}",
                parse_mode="HTML",
            )
        finally:
            if pdf_path:
                try:
                    os.remove(pdf_path)
                except Exception:
                    pass

    asyncio.create_task(_runner())


@router.callback_query(F.data == "admin_export_all_users_pdf")
async def admin_export_all_users_pdf(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Только супер-админ.", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer("⏳ Готовлю единый PDF-отчёт по всем пользователям бота. Это может занять время...")

    async def _runner() -> None:
        pdf_path = None
        try:
            pdf_path, filename = await build_all_users_report_pdf()
            await callback.bot.send_document(
                callback.from_user.id,
                FSInputFile(str(pdf_path), filename=filename),
                caption="👥 PDF-отчёт по всем пользователям готов.",
            )
        except Exception as e:
            logger.exception("Failed to build all users PDF report")
            await callback.bot.send_message(
                callback.from_user.id,
                f"❌ Не удалось собрать PDF по всем пользователям. Ошибка: {escape(str(e))}",
                parse_mode="HTML",
            )
        finally:
            if pdf_path:
                try:
                    os.remove(pdf_path)
                except Exception:
                    pass

    asyncio.create_task(_runner())


@router.callback_query(F.data == "admin_offers_menu")
async def admin_offers_menu(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        counts = await get_offer_moderation_counts(session)

    pending = counts.get("pending", 0)
    approved = counts.get("approved", 0)
    rejected = counts.get("rejected", 0)
    pending_rentals = counts.get("pending_rentals", 0)
    total_offers = sum(value for key, value in counts.items() if key != "pending_rentals")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"⏳ Офферы на модерации ({pending})",
            callback_data="admin_offers_list:pending:0",
        )],
        [InlineKeyboardButton(
            text=f"🧾 Аренды на модерации ({pending_rentals})",
            callback_data="admin_rentals_list:0",
        )],
        [InlineKeyboardButton(
            text=f"📋 Все офферы ({total_offers})",
            callback_data="admin_offers_list:all:0",
        )],
        [InlineKeyboardButton(text="➕ Создать оффер", callback_data="admin_create_offer")],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")],
    ])
    text_value = (
        "📢 <b>Офферы и реклама</b>\n\n"
        f"⏳ Ожидают модерации: <b>{pending}</b>\n"
        f"✅ Одобрено: <b>{approved}</b>\n"
        f"❌ Отклонено: <b>{rejected}</b>\n"
        f"🧾 Аренды на проверке: <b>{pending_rentals}</b>\n\n"
        "Здесь можно открыть заявку, проверить ссылку и одобрить или отклонить её."
    )
    await _safe_edit(callback, text_value, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


_OFFER_PAGE_SIZE = 8
_OFFER_REJECTION_REASONS = {
    "forbidden": "Запрещённый или сомнительный проект",
    "link": "Ссылка не работает или ведёт не на заявленный проект",
    "description": "Недостаточно информации или вводящее в заблуждение описание",
    "other": "Не соответствует требованиям размещения",
}
_RENTAL_REJECTION_REASONS = {
    "forbidden": "Запрещённый или сомнительный проект",
    "link": "Ссылка не работает",
    "content": "Название или содержание рекламы не соответствует требованиям",
    "other": "Не соответствует требованиям размещения",
}


def _offer_status_text(offer: Offer) -> str:
    labels = {
        "payment_pending": "💳 ожидает оплаты",
        "pending": "⏳ на модерации",
        "approved": "✅ одобрен",
        "rejected": "❌ отклонён",
    }
    label = labels.get(offer.status, escape(offer.status))
    if offer.status == "approved" and not offer.is_active:
        return f"{label}, ⏸ выключен"
    expires_at = get_offer_expires_at(offer)
    if offer.status == "approved" and expires_at and expires_at <= utc_now():
        return f"{label}, ⌛ срок истёк"
    return label


async def _send_offer_review_notification(bot, offer: Offer) -> None:
    if not offer.creator_user_id:
        return
    async with async_session() as session:
        creator = await get_user_by_id(session, offer.creator_user_id)
    if not creator:
        return
    try:
        if offer.status == "approved":
            await bot.send_message(
                creator.telegram_id,
                f"✅ Твой оффер <b>{escape(offer.title)}</b> одобрен и опубликован.",
                parse_mode="HTML",
            )
        elif offer.status == "rejected":
            await bot.send_message(
                creator.telegram_id,
                f"❌ Твой оффер <b>{escape(offer.title)}</b> отклонён.\n"
                f"Причина: {escape(offer.rejection_reason or 'Не прошёл модерацию')}",
                parse_mode="HTML",
            )
    except Exception:
        logger.warning("Failed to notify offer creator for offer_id=%s", offer.id)


@router.callback_query(F.data.startswith("admin_offers_list:"))
async def admin_offers_list(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    try:
        _, status, page_raw = callback.data.split(":", 2)
        page = max(0, int(page_raw))
    except (ValueError, AttributeError):
        await callback.answer("Некорректная страница.", show_alert=True)
        return

    async with async_session() as session:
        offers = await get_offers_for_admin(
            session,
            status=status,
            offset=page * _OFFER_PAGE_SIZE,
            limit=_OFFER_PAGE_SIZE + 1,
        )
    has_next_page = len(offers) > _OFFER_PAGE_SIZE
    offers = offers[:_OFFER_PAGE_SIZE]

    title = "Офферы на модерации" if status == "pending" else "Все офферы"
    rows = []
    for offer in offers:
        icon = {"pending": "⏳", "approved": "✅", "rejected": "❌", "payment_pending": "💳"}.get(offer.status, "•")
        rows.append([InlineKeyboardButton(
            text=f"{icon} #{offer.id} {offer.title[:38]}",
            callback_data=f"admin_offer_view:{offer.id}",
        )])

    navigation = []
    if page > 0:
        navigation.append(InlineKeyboardButton(
            text="◀️",
            callback_data=f"admin_offers_list:{status}:{page - 1}",
        ))
    if has_next_page:
        navigation.append(InlineKeyboardButton(
            text="▶️",
            callback_data=f"admin_offers_list:{status}:{page + 1}",
        ))
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton(text="◀ К офферам", callback_data="admin_offers_menu")])

    body = f"📋 <b>{title}</b>\n\n"
    body += "Выбери заявку:" if offers else "На этой странице заявок нет."
    await _safe_edit(
        callback,
        body,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_offer_view:"))
async def admin_offer_view(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    try:
        offer_id = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, AttributeError):
        await callback.answer("Некорректный ID.", show_alert=True)
        return

    async with async_session() as session:
        offer = await get_offer_by_id(session, offer_id)
        creator = await get_user_by_id(session, offer.creator_user_id) if offer and offer.creator_user_id else None
        participants = 0
        if offer:
            from app.models import OfferParticipation
            participants = (await session.execute(
                select(func.count(OfferParticipation.id)).where(OfferParticipation.offer_id == offer.id)
            )).scalar_one() or 0
    if not offer:
        await callback.answer("Оффер не найден.", show_alert=True)
        return

    creator_text = "Администратор"
    if creator:
        creator_text = f"{escape(get_display_name(creator))} (<code>{creator.telegram_id}</code>)"
    expires_at = get_offer_expires_at(offer)
    expires_text = expires_at.strftime("%d.%m.%Y %H:%M UTC") if expires_at else "—"
    text_value = (
        f"📢 <b>Оффер #{offer.id}</b>\n\n"
        f"<b>{escape(offer.title)}</b>\n"
        f"{escape(offer.description)}\n\n"
        f"Статус: {_offer_status_text(offer)}\n"
        f"Автор: {creator_text}\n"
        f"Ссылка: {escape(offer.channel_url)}\n"
        f"Награды: <b>{offer.reward_preview} + {offer.reward_final}</b> монет\n"
        f"Штраф: <b>{offer.penalty_unsubscribe}</b> монет\n"
        f"Размещение: <b>{offer.placement_cost}</b> монет\n"
        f"Срок: <b>{offer.duration_days}</b> дней, до {expires_text}\n"
        f"Участников: <b>{participants}</b>\n"
        f"Аренда: {'да' if offer.is_rentable else 'нет'}"
    )
    if offer.rejection_reason:
        text_value += f"\nПричина отказа: {escape(offer.rejection_reason)}"

    rows = []
    button_url = normalize_telegram_url(offer.channel_url)
    if button_url:
        rows.append([InlineKeyboardButton(text="🔗 Открыть проект", url=button_url)])
    if offer.status == "pending":
        rows.append([
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"admin_offer_approve:{offer.id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admin_offer_reject:{offer.id}"),
        ])
    elif offer.status == "approved":
        rows.append([InlineKeyboardButton(
            text="⏸ Выключить" if offer.is_active else "▶️ Включить",
            callback_data=f"admin_offer_toggle:{offer.id}",
        )])
    rows.extend([
        [InlineKeyboardButton(text="⏳ К очереди", callback_data="admin_offers_list:pending:0")],
        [InlineKeyboardButton(text="◀ К офферам", callback_data="admin_offers_menu")],
    ])
    await _safe_edit(
        callback,
        text_value,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_offer_approve:"))
async def admin_offer_approve(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    offer_id = int(callback.data.rsplit(":", 1)[1])
    async with async_session() as session:
        offer = await moderate_offer(
            session,
            offer_id,
            approve=True,
            admin_telegram_id=callback.from_user.id,
        )
    if not offer:
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return
    await _send_offer_review_notification(callback.bot, offer)
    await admin_offer_view(callback)


@router.callback_query(F.data.startswith("admin_offer_reject:"))
async def admin_offer_reject(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    offer_id = int(callback.data.rsplit(":", 1)[1])
    rows = [[InlineKeyboardButton(
        text=label,
        callback_data=f"admin_offer_reject_reason:{offer_id}:{code}",
    )] for code, label in _OFFER_REJECTION_REASONS.items()]
    rows.append([InlineKeyboardButton(text="◀ Назад", callback_data=f"admin_offer_view:{offer_id}")])
    await _safe_edit(
        callback,
        "❌ <b>Причина отклонения оффера</b>\n\nОна будет отправлена автору.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_offer_reject_reason:"))
async def admin_offer_reject_reason(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    try:
        _, offer_raw, code = callback.data.split(":", 2)
        offer_id = int(offer_raw)
        reason = _OFFER_REJECTION_REASONS[code]
    except (ValueError, KeyError, AttributeError):
        await callback.answer("Некорректная причина.", show_alert=True)
        return
    async with async_session() as session:
        offer = await moderate_offer(
            session,
            offer_id,
            approve=False,
            admin_telegram_id=callback.from_user.id,
            reason=reason,
        )
    if not offer:
        await callback.answer("Заявка уже обработана.", show_alert=True)
        return
    await _send_offer_review_notification(callback.bot, offer)
    await admin_offer_view(callback)


@router.callback_query(F.data.startswith("admin_offer_toggle:"))
async def admin_offer_toggle(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    offer_id = int(callback.data.rsplit(":", 1)[1])
    async with async_session() as session:
        current = await get_offer_by_id(session, offer_id)
        offer = await set_offer_active(
            session,
            offer_id,
            active=not bool(current.is_active) if current else False,
            admin_telegram_id=callback.from_user.id,
        )
    if not offer:
        await callback.answer("Оффер не найден или не одобрен.", show_alert=True)
        return
    await admin_offer_view(callback)


@router.callback_query(F.data.startswith("admin_rentals_list:"))
async def admin_rentals_list(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    try:
        page = max(0, int(callback.data.rsplit(":", 1)[1]))
    except (ValueError, AttributeError):
        await callback.answer("Некорректная страница.", show_alert=True)
        return
    async with async_session() as session:
        rentals = await get_pending_rentals(
            session,
            offset=page * _OFFER_PAGE_SIZE,
            limit=_OFFER_PAGE_SIZE + 1,
        )
    has_next_page = len(rentals) > _OFFER_PAGE_SIZE
    rentals = rentals[:_OFFER_PAGE_SIZE]
    rows = [[InlineKeyboardButton(
        text=f"⏳ #{rental.id} {rental.renter_channel_title[:38]}",
        callback_data=f"admin_rental_view:{rental.id}",
    )] for rental in rentals]
    navigation = []
    if page > 0:
        navigation.append(InlineKeyboardButton(text="◀️", callback_data=f"admin_rentals_list:{page - 1}"))
    if has_next_page:
        navigation.append(InlineKeyboardButton(text="▶️", callback_data=f"admin_rentals_list:{page + 1}"))
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton(text="◀ К офферам", callback_data="admin_offers_menu")])
    text_value = "🧾 <b>Аренды на модерации</b>\n\n"
    text_value += "Выбери заявку:" if rentals else "Очередь пуста."
    await _safe_edit(
        callback,
        text_value,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_rental_view:"))
async def admin_rental_view(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    rental_id = int(callback.data.rsplit(":", 1)[1])
    async with async_session() as session:
        rental = await session.get(OfferRental, rental_id)
        offer = await get_offer_by_id(session, rental.offer_id) if rental else None
        renter = await get_user_by_id(session, rental.renter_user_id) if rental else None
    if not rental:
        await callback.answer("Аренда не найдена.", show_alert=True)
        return
    text_value = (
        f"🧾 <b>Аренда #{rental.id}</b>\n\n"
        f"Канал: <b>{escape(rental.renter_channel_title)}</b>\n"
        f"Ссылка: {escape(rental.renter_channel_url)}\n"
        f"Автор: {escape(get_display_name(renter)) if renter else '—'}"
        f"{f' (<code>{renter.telegram_id}</code>)' if renter else ''}\n"
        f"Родительский оффер: {escape(offer.title) if offer else f'#{rental.offer_id}'}\n"
        f"Срок: <b>{rental.rent_days}</b> дней\n"
        f"Оплачено: <b>{rental.cost_paid}</b> монет\n"
        f"Статус: <b>{escape(rental.status)}</b>"
    )
    if rental.rejection_reason:
        text_value += f"\nПричина: {escape(rental.rejection_reason)}"
    rows = []
    button_url = normalize_telegram_url(rental.renter_channel_url)
    if button_url:
        rows.append([InlineKeyboardButton(text="🔗 Открыть канал", url=button_url)])
    if rental.status == "pending":
        rows.append([
            InlineKeyboardButton(text="✅ Одобрить", callback_data=f"admin_rental_approve:{rental.id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admin_rental_reject:{rental.id}"),
        ])
    rows.extend([
        [InlineKeyboardButton(text="⏳ К очереди", callback_data="admin_rentals_list:0")],
        [InlineKeyboardButton(text="◀ К офферам", callback_data="admin_offers_menu")],
    ])
    await _safe_edit(
        callback,
        text_value,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


async def _notify_rental_review(bot, rental: OfferRental) -> None:
    async with async_session() as session:
        renter = await get_user_by_id(session, rental.renter_user_id)
    if not renter:
        return
    try:
        if rental.status == "active":
            await bot.send_message(
                renter.telegram_id,
                f"✅ Аренда рекламы <b>{escape(rental.renter_channel_title)}</b> одобрена. "
                f"Срок показа: {rental.rent_days} дней.",
                parse_mode="HTML",
            )
        elif rental.status == "rejected":
            await bot.send_message(
                renter.telegram_id,
                f"❌ Аренда рекламы <b>{escape(rental.renter_channel_title)}</b> отклонена.\n"
                f"Причина: {escape(rental.rejection_reason or 'Не прошла модерацию')}\n"
                f"Возвращено: <b>{rental.cost_paid}</b> монет.",
                parse_mode="HTML",
            )
    except Exception:
        logger.warning("Failed to notify renter for rental_id=%s", rental.id)


@router.callback_query(F.data.startswith("admin_rental_approve:"))
async def admin_rental_approve(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    rental_id = int(callback.data.rsplit(":", 1)[1])
    async with async_session() as session:
        rental, error = await moderate_offer_rental(
            session,
            rental_id,
            approve=True,
            admin_telegram_id=callback.from_user.id,
        )
    if error or not rental:
        await callback.answer(error or "Не удалось обработать заявку.", show_alert=True)
        return
    await _notify_rental_review(callback.bot, rental)
    await admin_rental_view(callback)


@router.callback_query(F.data.startswith("admin_rental_reject:"))
async def admin_rental_reject(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    rental_id = int(callback.data.rsplit(":", 1)[1])
    rows = [[InlineKeyboardButton(
        text=label,
        callback_data=f"admin_rental_reject_reason:{rental_id}:{code}",
    )] for code, label in _RENTAL_REJECTION_REASONS.items()]
    rows.append([InlineKeyboardButton(text="◀ Назад", callback_data=f"admin_rental_view:{rental_id}")])
    await _safe_edit(
        callback,
        "❌ <b>Причина отклонения аренды</b>\n\n"
        "Оплата будет автоматически возвращена пользователю.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_rental_reject_reason:"))
async def admin_rental_reject_reason(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    try:
        _, rental_raw, code = callback.data.split(":", 2)
        rental_id = int(rental_raw)
        reason = _RENTAL_REJECTION_REASONS[code]
    except (ValueError, KeyError, AttributeError):
        await callback.answer("Некорректная причина.", show_alert=True)
        return
    async with async_session() as session:
        rental, error = await moderate_offer_rental(
            session,
            rental_id,
            approve=False,
            admin_telegram_id=callback.from_user.id,
            reason=reason,
        )
    if error or not rental:
        await callback.answer(error or "Не удалось обработать заявку.", show_alert=True)
        return
    await _notify_rental_review(callback.bot, rental)
    await admin_rental_view(callback)

# ============================
# НАСТРОЙКИ БОТА
# ============================

class BotSettingsState(StatesGroup):
    waiting_value = State()
    waiting_welcome_text = State()
    waiting_welcome_banner = State()


# ---------- Главное меню настроек ----------
@router.callback_query(F.data == "admin_bot_settings")
async def admin_bot_settings(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Экономика", callback_data="settings_economy")],
        [InlineKeyboardButton(text="👑 VIP", callback_data="settings_vip")],
        [InlineKeyboardButton(text="🎁 Лутбоксы", callback_data="settings_games")],
        [InlineKeyboardButton(text="🚀 Аркада", callback_data="settings_arcade")],
        [InlineKeyboardButton(text="🎁 Еженедельная халява", callback_data="settings_weekly_promo")],
        [InlineKeyboardButton(text="📺 Реклама", callback_data="settings_ads")],
        [InlineKeyboardButton(text="✏️ Никнеймы", callback_data="settings_nicks")],
        [InlineKeyboardButton(text="🎟 Промокоды", callback_data="settings_promos")],
        [InlineKeyboardButton(text="🖼 Приветствие и баннер", callback_data="settings_welcome")],
        [InlineKeyboardButton(text="🆓 ADMIN FREE", callback_data="settings_admin_free")],
        [InlineKeyboardButton(text="📊 Текущие значения", callback_data="settings_show_all")],
        [InlineKeyboardButton(text="🗑 Сбросить все настройки", callback_data="settings_reset_all")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_center")],
    ])
    await _safe_edit(callback, "🔧 <b>Настройки бота</b>\n\nВыбери категорию:", parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------- ЭКОНОМИКА ----------
@router.callback_query(F.data == "settings_economy")
async def settings_economy(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        from app.services import get_setting
        sb = await get_setting(session, "starting_balance", "")
        wc = await get_setting(session, "watch_cost", "")
        ur = await get_setting(session, "upload_reward", "")
        pr = await get_setting(session, "photo_upload_reward", "")
        str_c = await get_setting(session, "stars_to_coins_rate", "")
        ri = await get_setting(session, "referral_reward_inviter", "")
        rn = await get_setting(session, "referral_reward_new_user", "")
        fp = await get_setting(session, "first_purchase_daily_bonus", "")
    from app.config import (
        STARTING_BALANCE, WATCH_COST, UPLOAD_REWARD, PHOTO_UPLOAD_REWARD,
        STARS_TO_COINS_RATE, REFERRAL_REWARD_INVITER, REFERRAL_REWARD_NEW_USER,
        FIRST_PURCHASE_DAILY_BONUS,
    )
    def v(db_val, default):
        return f"{db_val or default}"
    text = (
        f"💰 <b>Экономика</b>\n\n"
        f"Стартовый баланс: {v(sb, STARTING_BALANCE)}\n"
        f"Просмотр видео: {v(wc, WATCH_COST)}\n"
        f"Награда за видео: {v(ur, UPLOAD_REWARD)}\n"
        f"Награда за фото: {v(pr, PHOTO_UPLOAD_REWARD)}\n"
        f"Курс Stars→Coins: {v(str_c, STARS_TO_COINS_RATE)}\n"
        f"Реферал (пригласивший): {v(ri, REFERRAL_REWARD_INVITER)}\n"
        f"Реферал (новый): {v(rn, REFERRAL_REWARD_NEW_USER)}\n"
        f"Бонус 1-й покупки: {v(fp, FIRST_PURCHASE_DAILY_BONUS)}\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Стартовый баланс", callback_data="settings_edit:starting_balance")],
        [InlineKeyboardButton(text="✏️ Цена просмотра", callback_data="settings_edit:watch_cost")],
        [InlineKeyboardButton(text="✏️ Награда за видео", callback_data="settings_edit:upload_reward")],
        [InlineKeyboardButton(text="✏️ Награда за фото", callback_data="settings_edit:photo_upload_reward")],
        [InlineKeyboardButton(text="✏️ Курс Stars→Coins", callback_data="settings_edit:stars_to_coins_rate")],
        [InlineKeyboardButton(text="✏️ Реферал (пригл.)", callback_data="settings_edit:referral_reward_inviter")],
        [InlineKeyboardButton(text="✏️ Реферал (новый)", callback_data="settings_edit:referral_reward_new_user")],
        [InlineKeyboardButton(text="✏️ Бонус 1-й покупки", callback_data="settings_edit:first_purchase_daily_bonus")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_bot_settings")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------- VIP ----------
@router.callback_query(F.data == "settings_vip")
async def settings_vip(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        from app.services import get_setting
        vp = await get_setting(session, "vip_price_stars", "")
        vd = await get_setting(session, "vip_duration_days", "")
        vb = await get_setting(session, "vip_bonus_multiplier", "")
        vw = await get_setting(session, "vip_watch_discount", "")
    from app.config import VIP_PRICE_STARS, VIP_DURATION_DAYS, VIP_BONUS_MULTIPLIER, VIP_WATCH_DISCOUNT
    def v(db_val, default):
        return f"{db_val or default}"
    text = (
        f"👑 <b>VIP</b>\n\n"
        f"Цена (Stars): {v(vp, VIP_PRICE_STARS)}\n"
        f"Длительность (дней): {v(vd, VIP_DURATION_DAYS)}\n"
        f"Множитель монет: {v(vb, VIP_BONUS_MULTIPLIER)}\n"
        f"Скидка на просмотр: {v(vw, VIP_WATCH_DISCOUNT)}\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Цена VIP (Stars)", callback_data="settings_edit:vip_price_stars")],
        [InlineKeyboardButton(text="✏️ Длительность VIP", callback_data="settings_edit:vip_duration_days")],
        [InlineKeyboardButton(text="✏️ Множитель монет", callback_data="settings_edit:vip_bonus_multiplier")],
        [InlineKeyboardButton(text="✏️ Скидка на просмотр", callback_data="settings_edit:vip_watch_discount")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_bot_settings")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------- ЛУТБОКСЫ ----------
@router.callback_query(F.data == "settings_games")
async def settings_games(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        from app.services import get_setting
        lc = await get_setting(session, "lootbox_coin_price", "")
        ls = await get_setting(session, "lootbox_star_price", "")
        eb = await get_setting(session, "enable_lootboxes", "")
    from app.config import LOOTBOX_COIN_PRICE, LOOTBOX_STAR_PRICE, ENABLE_LOOTBOXES
    def v(db_val, default):
        return f"{db_val or default}"
    text = (
        f"🎁 <b>Лутбоксы</b>\n\n"
        f"Цена лутбокса (монеты): {v(lc, LOOTBOX_COIN_PRICE)}\n"
        f"Цена лутбокса (Stars): {v(ls, LOOTBOX_STAR_PRICE)}\n"
        f"Лутбоксы: {v(eb, 'on' if ENABLE_LOOTBOXES else 'off')}\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Цена лутбокса (монеты)", callback_data="settings_edit:lootbox_coin_price")],
        [InlineKeyboardButton(text="✏️ Цена лутбокса (Stars)", callback_data="settings_edit:lootbox_star_price")],
        [InlineKeyboardButton(text="🔘 Лутбоксы " + ("выкл" if eb == "off" else "вкл"), callback_data="settings_toggle:enable_lootboxes")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_bot_settings")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------- АРКАДА ----------
@router.callback_query(F.data == "settings_arcade")
async def settings_arcade(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        from app.arcade import load_arcade_config
        cfg = await load_arcade_config(session)
        from app.services import get_setting
        enabled_raw = await get_setting(session, "arcade_enabled", "")
    status_label = "включена ✅" if cfg.enabled else "отключена ⛔"
    toggle_label = "выкл ⛔" if cfg.enabled else "вкл ✅"
    text = (
        f"🚀 <b>Космическая аркада</b> (Mini App)\n\n"
        f"Статус: {status_label}\n"
        f"Мин. ставка: <b>{cfg.min_bet}</b> монет\n"
        f"Макс. ставка: <b>{cfg.max_bet}</b> монет\n"
        f"Макс. множитель: <b>x{cfg.max_multiplier}</b>\n"
        f"Дневной кап чистой прибыли: <b>{cfg.daily_profit_cap}</b> монет\n"
        f"TTL забега (возврат ставки): <b>{cfg.run_ttl_minutes}</b> мин\n\n"
        f"<i>Математика волн (шансы/множители) зашита в коде — см. app/arcade.py.</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔘 Аркада: {toggle_label}", callback_data="settings_toggle:arcade_enabled")],
        [InlineKeyboardButton(text="✏️ Мин. ставка", callback_data="settings_edit:arcade_min_bet")],
        [InlineKeyboardButton(text="✏️ Макс. ставка", callback_data="settings_edit:arcade_max_bet")],
        [InlineKeyboardButton(text="✏️ Макс. множитель", callback_data="settings_edit:arcade_max_multiplier")],
        [InlineKeyboardButton(text="✏️ Дневной кап прибыли", callback_data="settings_edit:arcade_daily_profit_cap")],
        [InlineKeyboardButton(text="✏️ TTL забега (мин)", callback_data="settings_edit:arcade_run_ttl_minutes")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_bot_settings")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------- РЕКЛАМА ----------
@router.callback_query(F.data == "settings_ads")
async def settings_ads(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        from app.services import get_setting
        vc = await get_setting(session, "smart_ad_video_chance", "")
        fs = await get_setting(session, "smart_ad_forced_watch_seconds", "")
        mi = await get_setting(session, "smart_ad_min_interval_minutes", "")
        lb = await get_setting(session, "smart_ad_low_balance_threshold", "")
        li = await get_setting(session, "smart_ad_low_balance_hint_interval", "")
        od = await get_setting(session, "offer_daily_reward_cap", "")
        vi = await get_setting(session, "videos_per_ad_interval", "")
    from app.config import (
        SMART_AD_VIDEO_CHANCE, SMART_AD_FORCED_WATCH_SECONDS,
        SMART_AD_MIN_INTERVAL_MINUTES, SMART_AD_LOW_BALANCE_THRESHOLD,
        SMART_AD_LOW_BALANCE_HINT_INTERVAL_MINUTES, OFFER_DAILY_REWARD_CAP,
    )
    def v(db_val, default):
        return f"{db_val or default}"
    text = (
        f"📺 <b>Реклама и офферы</b>\n\n"
        f"Шанс рекламы в видео: {v(vc, SMART_AD_VIDEO_CHANCE)}\n"
        f"Секунды ожидания: {v(fs, SMART_AD_FORCED_WATCH_SECONDS)}\n"
        f"Мин. интервал (мин): {v(mi, SMART_AD_MIN_INTERVAL_MINUTES)}\n"
        f"Порог низкого баланса: {v(lb, SMART_AD_LOW_BALANCE_THRESHOLD)}\n"
        f"Интервал подсказки (мин): {v(li, SMART_AD_LOW_BALANCE_HINT_INTERVAL_MINUTES)}\n"
        f"Лимит наград за офферы/день: {v(od, OFFER_DAILY_REWARD_CAP)}\n"
        f"Реклама каждые N видео: {v(vi, '10')}\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Шанс рекламы", callback_data="settings_edit:smart_ad_video_chance")],
        [InlineKeyboardButton(text="✏️ Секунды ожидания", callback_data="settings_edit:smart_ad_forced_watch_seconds")],
        [InlineKeyboardButton(text="✏️ Мин. интервал", callback_data="settings_edit:smart_ad_min_interval_minutes")],
        [InlineKeyboardButton(text="✏️ Порог низкого баланса", callback_data="settings_edit:smart_ad_low_balance_threshold")],
        [InlineKeyboardButton(text="✏️ Интервал подсказки", callback_data="settings_edit:smart_ad_low_balance_hint_interval")],
        [InlineKeyboardButton(text="✏️ Лимит наград за офферы", callback_data="settings_edit:offer_daily_reward_cap")],
        [InlineKeyboardButton(text="✏️ Реклама каждые N видео", callback_data="settings_edit:videos_per_ad_interval")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_bot_settings")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------- НИКНЕЙМЫ ----------
@router.callback_query(F.data == "settings_nicks")
async def settings_nicks(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        from app.services import get_setting
        nc = await get_setting(session, "nickname_change_cost", "")
        nm = await get_setting(session, "nickname_min_length", "")
        nx = await get_setting(session, "nickname_max_length", "")
        dl = await get_setting(session, "daily_photo_limit", "")
    from app.config import NICKNAME_CHANGE_COST, NICKNAME_MIN_LENGTH, NICKNAME_MAX_LENGTH, DAILY_PHOTO_LIMIT
    def v(db_val, default):
        return f"{db_val or default}"
    text = (
        f"✏️ <b>Никнеймы</b>\n\n"
        f"Цена смены ника: {v(nc, NICKNAME_CHANGE_COST)}\n"
        f"Мин. длина ника: {v(nm, NICKNAME_MIN_LENGTH)}\n"
        f"Макс. длина ника: {v(nx, NICKNAME_MAX_LENGTH)}\n"
        f"Лимит фото в день: {v(dl, DAILY_PHOTO_LIMIT)}\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Цена смены ника", callback_data="settings_edit:nickname_change_cost")],
        [InlineKeyboardButton(text="✏️ Мин. длина ника", callback_data="settings_edit:nickname_min_length")],
        [InlineKeyboardButton(text="✏️ Макс. длина ника", callback_data="settings_edit:nickname_max_length")],
        [InlineKeyboardButton(text="✏️ Лимит фото в день", callback_data="settings_edit:daily_photo_limit")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_bot_settings")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------- ПРОМОКОДЫ ----------
@router.callback_query(F.data == "settings_promos")
async def settings_promos(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        from app.services import get_setting
        sr = await get_setting(session, "promocode_creation_star_rate", "")
        bt = await get_setting(session, "promocode_bulk_discount_threshold", "")
        br = await get_setting(session, "promocode_bulk_discount_rate", "")
        cb = await get_setting(session, "promocode_creator_bonus_percent", "")
        mx = await get_setting(session, "promocode_max_amount", "")
        mu = await get_setting(session, "promocode_max_uses", "")
        mh = await get_setting(session, "promocode_max_hours", "")
        vp = await get_setting(session, "vip_free_promo_per_month", "")
    from app.config import (
        PROMOCODE_CREATION_STAR_RATE, PROMOCODE_BULK_DISCOUNT_THRESHOLD,
        PROMOCODE_BULK_DISCOUNT_RATE, PROMOCODE_CREATOR_BONUS_PERCENT,
        PROMOCODE_MAX_AMOUNT, PROMOCODE_MAX_USES, PROMOCODE_MAX_HOURS,
        VIP_FREE_PROMO_PER_MONTH,
    )
    def v(db_val, default):
        return f"{db_val or default}"
    text = (
        f"🎟 <b>Промокоды</b>\n\n"
        f"Цена (Stars за 1 монету): {v(sr, PROMOCODE_CREATION_STAR_RATE)}\n"
        f"Порог bulk скидки: {v(bt, PROMOCODE_BULK_DISCOUNT_THRESHOLD)}\n"
        f"Rate bulk скидки: {v(br, PROMOCODE_BULK_DISCOUNT_RATE)}\n"
        f"Бонус создателю (%): {v(cb, PROMOCODE_CREATOR_BONUS_PERCENT)}\n"
        f"Макс. сумма: {v(mx, PROMOCODE_MAX_AMOUNT)}\n"
        f"Макс. использований: {v(mu, PROMOCODE_MAX_USES)}\n"
        f"Макс. часов: {v(mh, PROMOCODE_MAX_HOURS)}\n"
        f"Бесплатных промо VIP/мес: {v(vp, VIP_FREE_PROMO_PER_MONTH)}\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Цена Stars за 1 монету", callback_data="settings_edit:promocode_creation_star_rate")],
        [InlineKeyboardButton(text="✏️ Порог bulk скидки", callback_data="settings_edit:promocode_bulk_discount_threshold")],
        [InlineKeyboardButton(text="✏️ Rate bulk скидки", callback_data="settings_edit:promocode_bulk_discount_rate")],
        [InlineKeyboardButton(text="✏️ Бонус создателю", callback_data="settings_edit:promocode_creator_bonus_percent")],
        [InlineKeyboardButton(text="✏️ Макс. сумма", callback_data="settings_edit:promocode_max_amount")],
        [InlineKeyboardButton(text="✏️ Макс. использований", callback_data="settings_edit:promocode_max_uses")],
        [InlineKeyboardButton(text="✏️ Макс. часов", callback_data="settings_edit:promocode_max_hours")],
        [InlineKeyboardButton(text="✏️ Бесплатных промо VIP", callback_data="settings_edit:vip_free_promo_per_month")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_bot_settings")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------- ЛОТЕРЕЯ (СЕКРЕТНЫЕ НАСТРОЙКИ СЕКЛОТО) ----------
@router.callback_query(F.data == "settings_lottery")
async def settings_lottery(callback: CallbackQuery):
    await callback.answer(
        "Настройки Секслото убраны из админки: расписание и длительность теперь зафиксированы в коде.",
        show_alert=True,
    )
    await admin_bot_settings(callback)


# ---------- ЕЖЕНЕДЕЛЬНЫЙ ПРОМОКОД ----------
@router.callback_query(F.data == "settings_weekly_promo")
async def settings_weekly_promo(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        from app.services import get_setting
        wd = await get_setting(session, "weekly_promo_day", "")
        wh = await get_setting(session, "weekly_promo_hour", "")
    from app.config import WEEKLY_PROMO_DAY, WEEKLY_PROMO_HOUR
    def v(db_val, default):
        return f"{db_val or default}"
    day_names = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]
    current_day = int(wd) if str(wd).isdigit() else WEEKLY_PROMO_DAY

    text = (
        "🎁 <b>Настройки Еженедельной Халявы</b>\n\n"
        "Раз в неделю бот рассылает всем пользователям <b>секретное слово недели</b>. "
        "За ввод слова: случайно <b>200–1500 монет</b> (один раз на человека за неделю).\n\n"
        f"<b>День недели рассылки:</b> {day_names[current_day] if 0 <= current_day < 7 else current_day}\n"
        f"<b>Час по UTC (0-23):</b> {v(wh, WEEKLY_PROMO_HOUR)}\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Выбрать день недели", callback_data="settings_edit:weekly_promo_day")],
        [InlineKeyboardButton(text="✏️ Час по UTC", callback_data="settings_edit:weekly_promo_hour")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_bot_settings")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------- ПРИВЕТСТВИЕ И БАННЕР ----------
@router.callback_query(F.data == "settings_welcome")
async def settings_welcome(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        from app.services import get_setting
        welcome_text = await get_setting(session, "welcome_text", "")
        welcome_banner_id = await get_setting(session, "welcome_banner_id", "")
    text = (
        "🖼 <b>Приветствие и баннер</b>\n\n"
        f"<b>Текст:</b>\n{escape(welcome_text) if welcome_text else '<i>(Не задан, используется стандартный)</i>'}\n\n"
        f"<b>Баннер установлен:</b> {'✅ Да' if welcome_banner_id else '❌ Нет (или локальный app/banner.jpg)'}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить текст приветствия", callback_data="admin_set_welcome_text")],
        [InlineKeyboardButton(text="🖼 Изменить картинку (баннер)", callback_data="admin_set_welcome_banner")],
        [InlineKeyboardButton(text="🗑 Сбросить баннер", callback_data="admin_reset_welcome_banner")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_bot_settings")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------- ADMIN FREE ----------
@router.callback_query(F.data == "settings_admin_free")
async def settings_admin_free(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        from app.services import get_setting
        val = await get_setting(session, "admin_free_enabled", "false")
    status = "🟢 ВКЛЮЧЕНО (админы покупают всё бесплатно)" if val.lower() == "true" else "🔴 ВЫКЛЮЧЕНО"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔘 " + ("Отключить" if val.lower() == "true" else "Включить"), callback_data="toggle_admin_free")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_bot_settings")],
    ])
    await _safe_edit(callback, f"🆓 <b>ADMIN FREE</b>\n\n{status}", parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------- DONATIONALERTS ----------
@router.callback_query(F.data == "admin_da_menu")
async def admin_da_menu(callback: CallbackQuery, state: FSMContext | None = None):
    if state:
        await state.clear()
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    from app.config import (
        DONATION_ALERTS_URL, RUB_TO_COINS_RATE, VIP_PRICE_RUB,
        DONATION_ALERTS_ACCESS_TOKEN, DONATION_ALERTS_CLIENT_ID,
        DONATION_ALERTS_REFRESH_TOKEN,
    )
    async with async_session() as session:
        pending_exceptions = (await session.execute(
            select(func.count(DonationAlertException.id)).where(DonationAlertException.status == "pending")
        )).scalar() or 0

    oauth_ready = bool(DONATION_ALERTS_ACCESS_TOKEN or (
        DONATION_ALERTS_CLIENT_ID and DONATION_ALERTS_REFRESH_TOKEN
    ))
    automation_status = "🟢 OAuth-синхронизация включена" if oauth_ready else "🟡 Нужны OAuth-реквизиты"
    text = (
        f"💳 <b>Управление DonationAlerts</b>\n\n"
        f"🔗 <b>Ссылка для оплаты:</b> <code>{DONATION_ALERTS_URL}</code>\n"
        f"🤖 <b>Автоматизация:</b> {automation_status}\n"
        f"⚠️ <b>Очередь сверки:</b> {pending_exceptions}\n\n"
        f"📊 <b>Текущие настройки:</b>\n"
        f"• 1 RUB ➔ <b>{int(RUB_TO_COINS_RATE)} монет</b>\n"
        f"• VIP-подписка ➔ <b>{int(VIP_PRICE_RUB)} RUB / 30 дней</b>\n\n"
        "Автоматически зачисляются только платежи с действующим одноразовым кодом "
        "заказа и точной суммой. Всё остальное попадает в очередь сверки."
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⚠️ Очередь сверки ({pending_exceptions})", callback_data="admin_da_exceptions")],
        [InlineKeyboardButton(text="➕ Начислить донат вручную", callback_data="admin_da_manual_start")],
        [InlineKeyboardButton(text="◀️ Назад в панель", callback_data="admin_center")],
    ])

    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_da_manual_start")
async def admin_da_manual_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(DAManualState.waiting_user)
    await callback.message.answer(
        "💳 <b>Ручное зачисление платежа DonationAlerts</b>\n\n"
        "<b>Шаг 1 из 2:</b> Введите Telegram ID пользователя (например, <code>123456789</code>):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_da_menu")
        ]])
    )
    await callback.answer()


@router.message(DAManualState.waiting_user)
async def admin_da_manual_user(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("❌ Telegram ID должен состоять только из цифр. Попробуйте еще раз:")
        return

    tid = int(raw)
    async with async_session() as session:
        user = await get_user(session, tid)
        if not user:
            await message.answer(f"❌ Пользователь с Telegram ID <code>{tid}</code> не найден в базе данных. Проверьте ID:")
            return
        disp_name = get_display_name(user)

    await state.update_data(da_manual_user_id=tid)
    await state.set_state(DAManualState.waiting_amount)
    await message.answer(
        f"👤 Пользователь найден: <b>{escape(disp_name)}</b> (ID: <code>{tid}</code>)\n\n"
        f"<b>Шаг 2 из 2:</b> Введите сумму доната в рублях (например, <code>100</code> или <code>150</code> для VIP, или напишите <code>vip</code>):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_da_menu")
        ]])
    )


@router.message(DAManualState.waiting_amount)
async def admin_da_manual_amount(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    raw = (message.text or "").strip().lower()
    data = await state.get_data()
    tid = int(data.get("da_manual_user_id") or 0)

    if not tid:
        await state.clear()
        await message.answer("❌ Сессия сброшена.")
        return

    if raw == "vip":
        amount_rub = 150
        comment = "vip"
    else:
        try:
            amount_rub = float(raw)
            comment = f"manual_by_admin_{message.from_user.id}"
        except ValueError:
            await message.answer("❌ Введите числовое значение суммы в рублях (или `vip`):")
            return

    import uuid
    manual_da_id = f"manual_{uuid.uuid4().hex[:8]}"

    async with async_session() as session:
        from app.services import process_donationalerts_donation
        ok, res_msg = await process_donationalerts_donation(
            session=session,
            donation_id=manual_da_id,
            amount_rub=amount_rub,
            telegram_user_id=tid,
            comment=comment,
            bot=message.bot
        )

    await state.clear()
    if ok:
        await message.answer(
            f"✅ <b>Донат успешно проведен!</b>\n\n"
            f"Пользователь: ID <code>{tid}</code>\n"
            f"Сумма: <b>{amount_rub} руб.</b>\n"
            f"Результат: <b>{res_msg}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="💳 В меню DonationAlerts", callback_data="admin_da_menu")
            ]])
        )
    else:
        await message.answer(f"❌ Ошибка проведения доната: {res_msg}")


# ---------- ПОКАЗАТЬ ВСЕ НАСТРОЙКИ ----------
@router.callback_query(F.data == "settings_show_all")
async def settings_show_all(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        from app.models import BotSetting
        result = await session.execute(select(BotSetting).order_by(BotSetting.key))
        settings = result.scalars().all()
    if not settings:
        text = "📊 <b>Все настройки</b>\n\nНет пользовательских настроек. Используются значения из config.py."
    else:
        text = "📊 <b>Все пользовательские настройки</b>\n\n"
        for s in settings:
            text += f"• <code>{s.key}</code> = <b>{s.value}</b>\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Сбросить все", callback_data="settings_reset_all")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_bot_settings")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


# ---------- СБРОСИТЬ ВСЕ НАСТРОЙКИ ----------
@router.callback_query(F.data == "settings_reset_all")
async def settings_reset_all(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, сбросить", callback_data="settings_reset_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_bot_settings")],
    ])
    await _safe_edit(callback, "⚠️ <b>Ты точно хочешь продолжить?</b>\n\nЭто удалит все пользовательские настройки бота. Значения вернутся к дефолтным из config.py.", parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "settings_reset_confirm")
async def settings_reset_confirm(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        from sqlalchemy import delete
        from app.models import BotSetting
        await session.execute(delete(BotSetting))
        await session.commit()
    await callback.answer("✅ Все настройки сброшены!", show_alert=True)
    await admin_bot_settings(callback)


# ---------- РЕДАКТИРОВАНИЕ НАСТРОЕК ----------
@router.callback_query(F.data.startswith("settings_edit:"))
async def settings_edit_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    key = callback.data.split(":", 1)[1]
    await state.update_data(settings_key=key)
    
    if key == "weekly_promo_day":
        days = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]
        kb_rows = [
            [
                InlineKeyboardButton(text=days[0], callback_data="settings_set_day:0"),
                InlineKeyboardButton(text=days[1], callback_data="settings_set_day:1"),
                InlineKeyboardButton(text=days[2], callback_data="settings_set_day:2"),
                InlineKeyboardButton(text=days[3], callback_data="settings_set_day:3"),
            ],
            [
                InlineKeyboardButton(text=days[4], callback_data="settings_set_day:4"),
                InlineKeyboardButton(text=days[5], callback_data="settings_set_day:5"),
                InlineKeyboardButton(text=days[6], callback_data="settings_set_day:6"),
            ],
            [InlineKeyboardButton(text="Отмена", callback_data="admin_bot_settings")],
        ]
        await callback.message.answer("📅 <b>Выбери день недели для рассылки промокода:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
        await callback.answer()
        return

    await state.set_state(BotSettingsState.waiting_value)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="admin_bot_settings")]])
    await callback.message.answer(
        f"✏️ Введи новое значение для <code>{key}</code>:\n\n"
        f"Для сброса к дефолту отправь <code>-</code> (дефис).",
        parse_mode="HTML",
        reply_markup=kb,
    )
    await callback.answer()

@router.callback_query(F.data.startswith("settings_set_day:"))
async def settings_set_day(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    day_val = callback.data.split(":")[1]
    day_names = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]

    data = await state.get_data()
    key = data.get("settings_key", "weekly_promo_day")

    async with async_session() as session:
        from app.services import set_setting
        await set_setting(session, key, day_val)
        await session.commit()

    label = day_names[int(day_val)] if day_val.isdigit() and 0 <= int(day_val) < 7 else day_val
    await callback.message.answer(f"✅ Настройка {key} успешно изменена: {label}!")
    await callback.answer()



@router.message(BotSettingsState.waiting_value)
async def settings_edit_save(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    data = await state.get_data()
    key = data.get("settings_key", "")
    value = message.text.strip()
    
    async with async_session() as session:
        from app.services import set_setting
        if value == "-":
            # Удаляем настройку — вернётся к дефолту
            from sqlalchemy import delete
            from app.models import BotSetting
            await session.execute(delete(BotSetting).where(BotSetting.key == key))
            await session.commit()
            await message.answer(f"✅ Настройка <code>{key}</code> сброшена к дефолтному значению.", parse_mode="HTML")
        else:
            await set_setting(session, key, value)
            await message.answer(f"✅ Настройка <code>{key}</code> = <b>{value}</b>", parse_mode="HTML")
    await state.clear()


# ---------- ПЕРЕКЛЮЧАТЕЛИ ----------
@router.callback_query(F.data.startswith("settings_toggle:"))
async def settings_toggle(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    key = callback.data.split(":", 1)[1]
    async with async_session() as session:
        from app.services import get_setting, set_setting
        current = await get_setting(session, key, "on")
        new_val = "off" if current.lower() == "on" else "on"
        await set_setting(session, key, new_val)
    status = "включён" if new_val == "on" else "отключён"
    await callback.answer(f"✅ {key} {status}!", show_alert=True)
    # Перезапускаем текущее меню
    if key in ("enable_lottery", "enable_lootboxes"):
        await settings_games(callback)
    elif key == "arcade_enabled":
        await settings_arcade(callback)
    else:
        await admin_bot_settings(callback)


# ---------- СТАРЫЕ ОБРАБОТЧИКИ БАННЕРА ----------
@router.callback_query(F.data == "admin_set_welcome_text")
async def admin_set_welcome_text_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(BotSettingsState.waiting_welcome_text)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="settings_welcome")]])
    await _safe_edit(
        callback,
        "Введи новый текст приветствия.\n"
        "Можно использовать HTML теги.\n"
        "Для сброса текста отправь <code>-</code> (дефис).",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


@router.message(BotSettingsState.waiting_welcome_text)
async def admin_set_welcome_text_finish(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    text = message.html_text.strip()
    if text == "-":
        text = ""
    
    async with async_session() as session:
        from app.services import set_setting
        await set_setting(session, "welcome_text", text)
    
    await message.answer("✅ Текст приветствия успешно обновлен!")
    await state.clear()


@router.callback_query(F.data == "admin_set_welcome_banner")
async def admin_set_welcome_banner_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(BotSettingsState.waiting_welcome_banner)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="settings_welcome")]])
    await _safe_edit(
        callback,
        "Отправь новую картинку (фото), которая будет использоваться как приветственный баннер.",
        reply_markup=kb
    )
    await callback.answer()


@router.message(BotSettingsState.waiting_welcome_banner, F.photo)
async def admin_set_welcome_banner_finish(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    photo_id = message.photo[-1].file_id
    
    async with async_session() as session:
        from app.services import set_setting
        await set_setting(session, "welcome_banner_id", photo_id)
        
    await message.answer("✅ Приветственный баннер успешно обновлен!")
    await state.clear()


@router.callback_query(F.data == "admin_reset_welcome_banner")
async def admin_reset_welcome_banner(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    
    async with async_session() as session:
        from app.services import set_setting
        await set_setting(session, "welcome_banner_id", "")
        
    await callback.answer("✅ Баннер сброшен! Теперь используется стандартный app/banner.jpg", show_alert=True)
    await settings_welcome(callback)


# ============================
# АВТО-МОДЕРАЦИЯ И ДОВЕРЕННЫЕ АВТОРЫ
# ============================
@router.callback_query(F.data == "admin_auto_moderation")
async def admin_auto_moderation(callback: CallbackQuery):
    """Показать статистику авто-модерации и переключатель"""
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    async with async_session() as session:
        from app.services import get_setting
        db_val = await get_setting(session, "auto_moderation_enabled", "")
        if db_val:
            is_enabled = db_val.lower() == "true"
        else:
            is_enabled = ENABLE_AUTO_MODERATION

        trusted_count = (await session.execute(
            select(func.count(TrustedUploader.id))
        )).scalar_one()
        # Auto-approved is no longer marked by rejection_reason; use 0 or join via UserActionLog if needed
        auto_approved_count = 0

    status_icon = "🟢" if is_enabled else "🔴"
    status_text = "включена" if is_enabled else "отключена"

    text = (
        f"⚡ <b>Авто-модерация</b>\n\n"
        f"Статус: {status_icon} {status_text}\n"
        f"Доверенных авторов: {trusted_count}\n"
        f"Авто-одобрено видео: {auto_approved_count}\n\n"
        f"Доверенные авторы загружают контент без премодерации.\n"
        f"Управляйте списком в разделе «🤝 Доверенные авторы»."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🔘 " + ("Отключить" if is_enabled else "Включить"),
            callback_data="toggle_auto_mod"
        )],
        [InlineKeyboardButton(text="🤝 Доверенные авторы", callback_data="admin_trusted_uploaders")],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "toggle_auto_mod")
async def toggle_auto_moderation(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    async with async_session() as session:
        from app.services import get_setting, set_setting
        current = await get_setting(session, "auto_moderation_enabled", "")
        # Если пусто — берём из ENV
        if current:
            new_val = "false" if current.lower() == "true" else "true"
        else:
            new_val = "false" if ENABLE_AUTO_MODERATION else "true"
        await set_setting(session, "auto_moderation_enabled", new_val)

    status = "включена" if new_val == "true" else "отключена"
    await callback.answer(f"⚡ Авто-модерация {status}!", show_alert=True)
    await admin_auto_moderation(callback)


@router.callback_query(F.data == "toggle_admin_free")
async def toggle_admin_free(callback: CallbackQuery):
    """Переключить ADMIN FREE — админы покупают всё бесплатно"""
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    async with async_session() as session:
        from app.services import get_setting, set_setting
        current = await get_setting(session, "admin_free_enabled", "false")
        new_val = "true" if current.lower() != "true" else "false"
        await set_setting(session, "admin_free_enabled", new_val)

    status = "включён" if new_val == "true" else "отключён"
    await callback.answer(f"🆓 ADMIN FREE {status}!", show_alert=True)
    await admin_bot_settings(callback)


@router.callback_query(F.data == "admin_trusted_uploaders")
async def admin_trusted_uploaders(callback: CallbackQuery):
    """Список доверенных авторов + возможность добавить/удалить"""
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    async with async_session() as session:
        trusted_rows = (await session.execute(
            select(TrustedUploader, User)
            .join(User, TrustedUploader.trusted_user_id == User.id)
            .order_by(TrustedUploader.created_at.desc())
        )).all()

        admin_ids = {tu.admin_user_id for tu, _ in trusted_rows}
        admin_map = {}
        if admin_ids:
            admins = (await session.execute(
                select(User).where(User.id.in_(admin_ids))
            )).scalars().all()
            admin_map = {admin.id: admin for admin in admins}

    if not trusted_rows:
        text = "🤝 <b>Доверенные авторы</b>\n\nНет доверенных авторов.\n\nДобавьте автора по ID или @username:"
    else:
        text = "🤝 <b>Доверенные авторы</b>\n\n"
        for tu, user_obj in trusted_rows:
            admin_obj = admin_map.get(tu.admin_user_id)
            admin_name = get_display_name(admin_obj) if admin_obj else "?"
            text += f"• {get_display_name(user_obj)} (добавил {admin_name})\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить автора", callback_data="trusted_add_start")],
        [InlineKeyboardButton(text="➖ Удалить автора", callback_data="trusted_remove_start")],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_center")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "trusted_add_start")
async def trusted_add_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(TrustedUploaderState.waiting_add)
    await callback.message.answer(
        "🤝 <b>Добавить доверенного автора</b>\n\n"
        "Введи ID пользователя или @username:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="admin_trusted_uploaders")]
        ])
    )
    await callback.answer()


@router.message(TrustedUploaderState.waiting_add)
async def trusted_add_process(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return

    query = message.text.strip()
    async with async_session() as session:
        if query.isdigit():
            # Здесь ожидается Telegram ID, а не внутренний users.id.
            user = await get_user(session, int(query))
        else:
            if query.startswith("@"):
                query = query[1:]
            user = await get_user_by_username(session, query)

        if not user:
            await message.answer("❌ Пользователь не найден.")
            await state.clear()
            return

        # Проверяем, не добавлен ли уже
        existing = (await session.execute(
            select(TrustedUploader).where(
                TrustedUploader.trusted_user_id == user.id
            )
        )).scalar_one_or_none()

        if existing:
            await message.answer(f"⚠️ {get_display_name(user)} уже в списке доверенных.")
            await state.clear()
            return

        admin_user = await get_user(session, message.from_user.id)
        session.add(TrustedUploader(
            admin_user_id=admin_user.id,
            trusted_user_id=user.id,
        ))
        await session.commit()

    await message.answer(f"✅ {get_display_name(user)} добавлен как доверенный автор!\nТеперь его видео одобряются автоматически.")
    await state.clear()


@router.callback_query(F.data == "trusted_remove_start")
async def trusted_remove_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(TrustedUploaderState.waiting_remove)
    await callback.message.answer(
        "➖ <b>Удалить доверенного автора</b>\n\n"
        "Введи ID пользователя или @username:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="admin_trusted_uploaders")]
        ])
    )
    await callback.answer()


@router.message(TrustedUploaderState.waiting_remove)
async def trusted_remove_process(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return

    query = message.text.strip()
    async with async_session() as session:
        if query.isdigit():
            # Здесь ожидается Telegram ID, а не внутренний users.id.
            user = await get_user(session, int(query))
        else:
            if query.startswith("@"):
                query = query[1:]
            user = await get_user_by_username(session, query)

        if not user:
            await message.answer("❌ Пользователь не найден.")
            await state.clear()
            return

        result = await session.execute(
            select(TrustedUploader).where(
                TrustedUploader.trusted_user_id == user.id
            )
        )
        trusted = result.scalar_one_or_none()

        if not trusted:
            await message.answer(f"⚠️ {get_display_name(user)} не в списке доверенных.")
            await state.clear()
            return

        await session.delete(trusted)
        await session.commit()

    await message.answer(f"✅ {get_display_name(user)} удалён из списка доверенных авторов.")
    await state.clear()


# ============================
# ДОСРОЧНАЯ ОСТАНОВКА СОБЫТИЙ
# ============================
@router.callback_query(F.data == "admin_events_list_full")
async def admin_events_list_full(callback: CallbackQuery):
    """Полный список событий с кнопками остановки."""
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        events = (await session.execute(
            select(Event).order_by(Event.created_at.desc()).limit(20)
        )).scalars().all()

    if not events:
        await callback.message.answer("Нет событий.")
        await callback.answer()
        return

    for ev in events:
        status = "🟢 Активно" if ev.is_active and ev.end_date > utc_now() else "🔴 Завершено"
        text = (
            f"🎉 <b>{escape(ev.name)}</b>\n"
            f"Скидка: {ev.discount_percent}% | {status}\n"
            f"До: {ev.end_date.strftime('%d.%m.%Y %H:%M')}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[])
        if ev.is_active and ev.end_date > utc_now():
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🛑 Остановить", callback_data=f"event_stop:{ev.id}")],
            ])
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("event_stop:"))
async def event_stop(callback: CallbackQuery):
    """Досрочно остановить событие."""
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    event_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        ev = (await session.execute(
            select(Event).where(Event.id == event_id)
        )).scalar_one_or_none()
        if not ev:
            await callback.answer("Событие не найдено.", show_alert=True)
            return
        ev.is_active = False
        ev.end_date = utc_now()
        await session.commit()
    await callback.message.edit_text(
        f"🛑 Событие «{escape(ev.name)}» остановлено.",
        parse_mode="HTML",
    )
    await callback.answer("Остановлено!")


# ============================
# ДОСРОЧНАЯ ОСТАНОВКА АКЦИЙ
# ============================
@router.callback_query(F.data == "admin_sales_list_full")
async def admin_sales_list_full(callback: CallbackQuery):
    """Полный список акций с кнопками остановки."""
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        sales = (await session.execute(
            select(ActiveSale).order_by(ActiveSale.id.desc()).limit(20)
        )).scalars().all()

    if not sales:
        await callback.message.answer("Нет акций.")
        await callback.answer()
        return

    for sale in sales:
        status = "🟢 Активна" if sale.end_date > utc_now() else "🔴 Завершена"
        text = (
            f"🛍 <b>Акция #{sale.id}</b>\n"
            f"Скидка: {sale.discount_percent}% на {sale.applies_to} | {status}\n"
            f"До: {sale.end_date.strftime('%d.%m.%Y %H:%M')}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[])
        if sale.end_date > utc_now():
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🛑 Остановить", callback_data=f"sale_stop:{sale.id}")],
            ])
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("sale_stop:"))
async def sale_stop_force(callback: CallbackQuery):
    """Досрочно остановить акцию."""
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    sale_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        sale = (await session.execute(
            select(ActiveSale).where(ActiveSale.id == sale_id)
        )).scalar_one_or_none()
        if not sale:
            await callback.answer("Акция не найдена.", show_alert=True)
            return
        sale.end_date = utc_now()
        await session.commit()
    await callback.message.edit_text(
        f"🛑 Акция #{sale_id} остановлена.",
        parse_mode="HTML",
    )
    await callback.answer("Остановлена!")


# ============================
# ОДОБРИТЬ ВСЁ (APPROVE ALL)
# ============================
@router.callback_query(F.data == "admin_approve_all")
async def admin_approve_all(callback: CallbackQuery):
    """Показать подтверждение одобрения всех pending-видео."""
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Только супер-админ.", show_alert=True)
        return
    async with async_session() as session:
        pending_count = await count_pending_videos(session)

    if pending_count == 0:
        await callback.message.answer("✅ Очередь пуста — нечего одобрять.")
        await callback.answer()
        return

    await callback.message.answer(
        f"⚠️ <b>Одобрить ВСЕ видео?</b>\n\n"
        f"В очереди: <b>{pending_count}</b> файлов.\n"
        f"Все будут одобрены, загрузчики получат награды.\n"
        f"Действие необратимо.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, одобрить всё", callback_data="admin_approve_all_confirm"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="admin_center"),
            ],
        ]),
    )
    await callback.answer()


async def approve_all_pending_background_task(admin_chat_id: int, admin_user_id: int, bot):
    import asyncio
    from app.db import async_session
    
    total_approved = 0
    BATCH_SIZE = 50
    
    while True:
        try:
            async with async_session() as session:
                count = await approve_all_pending(session, admin_user_id, limit=BATCH_SIZE)
                total_approved += count
                if count < BATCH_SIZE:
                    break
            await asyncio.sleep(0.5)
        except Exception as e:
            try:
                await bot.send_message(
                    admin_chat_id,
                    f"⚠️ <b>Произошла ошибка во время фонового одобрения:</b> {e}\n"
                    f"Одобрено файлов на момент сбоя: <b>{total_approved}</b>",
                    parse_mode="HTML"
                )
            except Exception:
                pass
            return
            
    try:
        await bot.send_message(
            admin_chat_id,
            f"🎉 <b>Фоновое одобрение успешно завершено!</b>\n\n"
            f"Всего одобрено файлов: <b>{total_approved}</b>.\n"
            f"Награды начислены всем загрузчикам.",
            parse_mode="HTML"
        )
    except Exception:
        pass


@router.callback_query(F.data == "admin_approve_all_confirm")
async def admin_approve_all_confirm(callback: CallbackQuery, bot):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Только супер-админ.", show_alert=True)
        return
    
    async with async_session() as session:
        admin = await get_user(session, callback.from_user.id)
        admin_id = admin.id if admin else 0
        total_pending = await count_pending_videos(session)
        
    if total_pending == 0:
        await callback.message.edit_text("Очередь модерации пуста!")
        await callback.answer("Очередь пуста!")
        return
        
    await callback.message.edit_text(
        f"⏳ <b>Запущено фоновое одобрение!</b>\n\n"
        f"Бот начал обрабатывать <b>{total_pending}</b> файлов в фоновом режиме.\n"
        f"Ты можешь закрыть бота и заниматься своими делами. По завершении ты получишь личное сообщение от бота! 🚀",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В админку", callback_data="admin_center")]
        ])
    )
    await callback.answer("Фоновое одобрение запущено!")
    
    asyncio.create_task(
        approve_all_pending_background_task(
            admin_chat_id=callback.message.chat.id,
            admin_user_id=admin_id,
            bot=bot
        )
    )


# ============================
# ЖАЛОБЫ НА ВИДЕО
# ============================
@router.callback_query(F.data == "admin_reports")
async def admin_reports_menu(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        reports = await get_pending_reports(session, limit=20)

    if not reports:
        await callback.message.answer(
            "✅ Нет жалоб на рассмотрении.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_center")],
            ]),
        )
        await callback.answer()
        return

    text = "🚨 <b>Жалобы на контент</b>\n\n"
    for r in reports[:10]:
        reason_label = REPORT_REASONS.get(r.reason, r.reason)
        text += (
            f"#{r.id} | {reason_label}\n"
            f"  Видео #{r.video_id} | От user_id={r.reporter_user_id}\n"
        )
        if r.comment:
            text += f"  💬 {escape(r.comment[:80])}\n"
        text += "\n"

    # Кнопки для каждой жалобы
    kb_rows = []
    for r in reports[:10]:
        reason_label = REPORT_REASONS.get(r.reason, r.reason)
        kb_rows.append([
            InlineKeyboardButton(
                text=f"✅ Отклонить #{r.id}",
                callback_data=f"report_dismiss:{r.id}",
            ),
            InlineKeyboardButton(
                text=f"🗑 Удалить видео #{r.video_id}",
                callback_data=f"report_remove_video:{r.id}:{r.video_id}",
            ),
        ])
        kb_rows.append([
            InlineKeyboardButton(
                text=f"👀 Посмотреть видео #{r.video_id}",
                callback_data=f"report_view_video:{r.id}:{r.video_id}",
            ),
        ])
    kb_rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_center")])

    await callback.message.answer(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("report_view_video:"))
async def report_view_video(callback: CallbackQuery):
    """Открыть публикацию из жалобы без ручного поиска по ID."""
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Неверный формат.", show_alert=True)
        return
    try:
        report_id = int(parts[1])
        video_id = int(parts[2])
    except ValueError:
        await callback.answer("Неверный формат.", show_alert=True)
        return

    async with async_session() as session:
        report = await session.get(VideoReport, report_id)
        video = await get_video_by_id(session, video_id)
        uploader = await get_user_by_id(session, video.uploader_user_id) if video else None
    if not report or report.video_id != video_id or not video:
        await callback.answer("Видео или жалоба больше недоступны.", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Оставить видео", callback_data=f"report_dismiss:{report.id}"),
            InlineKeyboardButton(text="🗑 Удалить видео", callback_data=f"report_remove_video:{report.id}:{video.id}"),
        ],
        [InlineKeyboardButton(text="◀️ К жалобам", callback_data="admin_reports")],
    ])
    await _send_admin_video_card(callback.message, video, uploader, keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("report_dismiss:"))
async def report_dismiss(callback: CallbackQuery):
    """Отклонить жалобу (оставить видео)."""
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    report_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        admin = await get_user(session, callback.from_user.id)
        rep = (await session.execute(
            select(VideoReport).where(VideoReport.id == report_id)
        )).scalar_one_or_none()
        
        ok = await dismiss_report(session, report_id, admin.id if admin else 0)
        
        if ok and rep:
            reporter = await get_user_by_id(session, rep.reporter_user_id)
            if reporter:
                try:
                    await callback.bot.send_message(
                        reporter.telegram_id,
                        f"📢 Админ рассмотрел вашу жалобу на видео #{rep.video_id} и принятое решение: Оставить видео",
                    )
                except Exception:
                    pass
    if ok:
        await callback.answer("Жалоба отклонена ✅")
    else:
        await callback.answer("Жалоба не найдена.", show_alert=True)


@router.callback_query(F.data.startswith("report_remove_video:"))
async def report_remove_video(callback: CallbackQuery):
    """Удалить видео по жалобе и закрыть жалобу."""
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Неверный формат.", show_alert=True)
        return
    report_id = int(parts[1])
    video_id = int(parts[2])
    async with async_session() as session:
        admin = await get_user(session, callback.from_user.id)
        # Удаляем видео (помечаем как rejected)
        v = (await session.execute(
            select(Video).where(Video.id == video_id)
        )).scalar_one_or_none()
        if v:
            v.status = "rejected"
            v.rejection_reason = "removed_by_report"
        # Закрываем ВСЕ pending-жалобы на это видео
        pending_reports = (await session.execute(
            select(VideoReport).where(
                VideoReport.video_id == video_id,
                VideoReport.status == "pending",
            )
        )).scalars().all()
        
        reporter_ids = set()
        for r in pending_reports:
            r.status = "reviewed"
            r.reviewed_by = admin.id if admin else 0
            reporter_ids.add(r.reporter_user_id)
            
        await session.commit()
        
        for r_user_id in reporter_ids:
            reporter = await get_user_by_id(session, r_user_id)
            if reporter:
                try:
                    await callback.bot.send_message(
                        reporter.telegram_id,
                        f"📢 Админ рассмотрел вашу жалобу на видео #{video_id} и принятое решение: Удалить видео",
                    )
                except Exception:
                    pass

    await callback.answer(f"Видео #{video_id} удалено, жалобы закрыты 🗑", show_alert=True)


# ====================================================
# УПРАВЛЕНИЕ АДМИНИСТРАТОРАМИ (👑 Только Super-Admin)
# ====================================================
@router.callback_query(F.data == "admin_manage_admins")
async def cb_admin_manage_admins(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Только для супер-админов.", show_alert=True)
        return
        
    async with async_session() as session:
        admins = (await session.execute(select(User).where(User.is_admin == True))).scalars().all()
        
    text = "👑 <b>Управление администраторами</b>\n\n"
    if not admins:
        text += "В базе данных нет администраторов. Только супер-админы из .env."
    else:
        text += "Список администраторов в базе данных:\n"
        for i, adm in enumerate(admins, 1):
            name = adm.display_name or adm.username or f"ID {adm.telegram_id}"
            text += f"{i}. {name} (ID: <code>{adm.telegram_id}</code>)\n"
            
    kb_rows = []
    kb_rows.append([InlineKeyboardButton(text="➕ Назначить админа", callback_data="admin_add_admin_start")])
    
    for adm in admins:
        name = adm.display_name or adm.username or f"ID {adm.telegram_id}"
        kb_rows.append([InlineKeyboardButton(text=f"❌ Снять: {name[:20]}", callback_data=f"admin_remove_admin:{adm.telegram_id}")])
        
    kb_rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_center")])
    
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await callback.answer()


@router.callback_query(F.data == "admin_add_admin_start")
async def cb_admin_add_admin_start(callback: CallbackQuery, state: FSMContext):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Только для супер-админов.", show_alert=True)
        return
        
    await state.set_state(AdminManageState.waiting_new_admin)
    await _safe_edit(
        callback,
        "✏️ <b>Назначение администратора</b>\n\n"
        "Отправь мне <b>Telegram ID</b> пользователя, которого хочешь назначить администратором в боте.\n\n"
        "<i>Пользователь должен хотя бы раз запустить бота перед этим, чтобы запись о нём была в базе данных.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_manage_admins")]
        ])
    )
    await callback.answer()


@router.message(AdminManageState.waiting_new_admin)
async def process_add_admin(message: Message, state: FSMContext):
    if not is_super_admin(message.from_user.id):
        return
        
    text_val = (message.text or "").strip()
    if not text_val.isdigit():
        await message.answer("❌ Telegram ID должен состоять только из цифр. Пожалуйста, попробуйте снова или отправь команду отмены.")
        return
        
    tid = int(text_val)
    async with async_session() as session:
        user = await get_user(session, tid)
        if not user:
            await message.answer(
                f"❌ Пользователь с Telegram ID <code>{tid}</code> не найден в базе данных.\n"
                f"Убедись, что он запустил бота и создал профиль.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ К админам", callback_data="admin_manage_admins")]
                ])
            )
            return
            
        if user.is_admin:
            await message.answer(
                f"ℹ️ Пользователь <b>{user.display_name or user.username or tid}</b> уже является администратором.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ К админам", callback_data="admin_manage_admins")]
                ])
            )
            await state.clear()
            return
            
        user.is_admin = True
        await session.commit()
        
    await message.answer(
        f"✅ Пользователь <b>{user.display_name or user.username or tid}</b> успешно назначен администратором!",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ К админам", callback_data="admin_manage_admins")]
        ])
    )
    await state.clear()


@router.callback_query(F.data.startswith("admin_remove_admin:"))
async def cb_admin_remove_admin(callback: CallbackQuery):
    if not is_super_admin(callback.from_user.id):
        await callback.answer("Только для супер-админов.", show_alert=True)
        return
        
    tid = int(callback.data.split(":", 1)[1])
    async with async_session() as session:
        user = await get_user(session, tid)
        if user:
            user.is_admin = False
            await session.commit()
            await callback.answer(f"Администратор {user.display_name or tid} удален.")
        else:
            await callback.answer("Пользователь не найден.")
            
    await cb_admin_manage_admins(callback)


# ====================================================
# СОЗДАНИЕ ОФФЕРОВ (FSM)
# ====================================================
@router.callback_query(F.data == "admin_create_offer")
async def cb_admin_create_offer_start(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
        
    await state.set_state(AdminOfferCreateState.waiting_title)
    
    text = (
        "📝 <b>Создание оффера (Шаг 1/10)</b>\n\n"
        "⚠️ <b>Важно:</b> можно рекламировать каналы, группы, чаты и ботов Telegram.\n"
        "• публичные каналы / группы / чаты с username бот может проверять автоматически\n"
        "• для ботов, приватных инвайтов и некоторых ссылок авто-проверка недоступна — там подтверждение будет ручным\n"
        "• серые, мутные и запрещённые проекты не допускаются\n\n"
        "Введи <b>название оффера</b> (например, <i>Подписка на игровой канал</i>):"
    )
    
    await _safe_edit(
        callback,
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_offers_menu")]
        ])
    )
    await callback.answer()


@router.message(AdminOfferCreateState.waiting_title)
async def process_offer_title(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    title = (message.text or "").strip()
    if not title or len(title) > 100:
        await message.answer("❌ Введи название длиной от 1 до 100 символов:")
        return
        
    await state.update_data(title=title)
    await state.set_state(AdminOfferCreateState.waiting_description)
    await message.answer(
        "📝 <b>Создание оффера (Шаг 2/10)</b>\n\n"
        "Введи <b>описание оффера</b> (что нужно сделать пользователю):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_offers_menu")]
        ])
    )


@router.message(AdminOfferCreateState.waiting_description)
async def process_offer_description(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    description = (message.text or "").strip()
    if not description or len(description) > 1500:
        await message.answer("❌ Введи описание длиной от 1 до 1500 символов:")
        return
        
    await state.update_data(description=description)
    await state.set_state(AdminOfferCreateState.waiting_url)
    await message.answer(
        "🔗 <b>Создание оффера (Шаг 3/10)</b>\n\n"
        "Введи <b>ссылку на Telegram-проект</b> — канал, группу, чат или бота\n"
        "(например, <code>https://t.me/my_channel</code>, <code>https://t.me/MyBot?start=promo</code>, <code>https://t.me/+invite</code>):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_offers_menu")]
        ])
    )


@router.message(AdminOfferCreateState.waiting_url)
async def process_offer_url(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    url = normalize_telegram_url(message.text or "")
    if not url:
        await message.answer("❌ Нужна корректная ссылка t.me/... или @username Telegram-проекта.")
        return

    await state.update_data(channel_url=url)
    await state.set_state(AdminOfferCreateState.waiting_reward_preview)
    await message.answer(
        "💰 <b>Создание оффера (Шаг 4/10)</b>\n\n"
        "Введи <b>награду за старт</b> (число монет, например, <code>50</code>):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_offers_menu")]
        ])
    )


@router.message(AdminOfferCreateState.waiting_reward_preview)
async def process_offer_reward_preview(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    val = (message.text or "").strip().replace(",", ".")
    try:
        reward = Decimal(val)
        if not reward.is_finite() or reward < 0: raise ValueError()
    except Exception:
        await message.answer("❌ Некорректное число монет. Введи положительное число:")
        return
        
    await state.update_data(reward_preview=str(reward))
    await state.set_state(AdminOfferCreateState.waiting_reward_final)
    await message.answer(
        "💰 <b>Создание оффера (Шаг 5/10)</b>\n\n"
        "Введи <b>награду за финальную подписку</b> (число монет, например, <code>350</code>):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_offers_menu")]
        ])
    )


@router.message(AdminOfferCreateState.waiting_reward_final)
async def process_offer_reward_final(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    val = (message.text or "").strip().replace(",", ".")
    try:
        reward = Decimal(val)
        if not reward.is_finite() or reward < 0: raise ValueError()
    except Exception:
        await message.answer("❌ Некорректное число монет. Введи положительное число:")
        return
        
    await state.update_data(reward_final=str(reward))
    await state.set_state(AdminOfferCreateState.waiting_penalty)
    await message.answer(
        "💰 <b>Создание оффера (Шаг 6/10)</b>\n\n"
        "Введи <b>штраф за отписку</b> (сколько монет спишется дополнительно, если пользователь отпишется):\n"
        "<i>Рекомендуется: сумма, превышающая награду, чтобы отписка была невыгодной.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_offers_menu")]
        ])
    )


@router.message(AdminOfferCreateState.waiting_penalty)
async def process_offer_penalty(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    val = (message.text or "").strip().replace(",", ".")
    try:
        penalty = Decimal(val)
        if not penalty.is_finite() or penalty < 0: raise ValueError()
    except Exception:
        await message.answer("❌ Некорректное число монет. Введи положительное число:")
        return
        
    await state.update_data(penalty_unsubscribe=str(penalty))
    await state.set_state(AdminOfferCreateState.waiting_duration)
    await message.answer(
        "📅 <b>Создание оффера (Шаг 7/10)</b>\n\n"
        "Сколько дней оффер должен быть активен после публикации? Введи число от 1 до 365:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_offers_menu")]
        ]),
    )


@router.message(AdminOfferCreateState.waiting_duration)
async def process_offer_duration(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    try:
        duration_days = int((message.text or "").strip())
        if not 1 <= duration_days <= 365:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи целое число дней от 1 до 365.")
        return

    await state.update_data(duration_days=duration_days)
    await state.set_state(AdminOfferCreateState.waiting_rentable)
    await message.answer(
        "📣 <b>Создание оффера (Шаг 8/10)</b>\n\n"
        "Будет ли этот оффер доступен для <b>аренды</b> обычными пользователями?\n"
        "Если да, любой пользователь сможет заплатить, чтобы рекламировать свой канал в этом оффере.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да", callback_data="offer_rent_yes")],
            [InlineKeyboardButton(text="❌ Нет", callback_data="offer_rent_no")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_offers_menu")]
        ])
    )


@router.callback_query(AdminOfferCreateState.waiting_rentable, F.data == "offer_rent_yes")
async def process_offer_rentable_yes(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    await state.update_data(is_rentable=True)
    await state.set_state(AdminOfferCreateState.waiting_rent_cost)
    await callback.message.answer(
        "💰 <b>Создание оффера (Шаг 9/10)</b>\n\n"
        "Введи <b>стоимость аренды одного слота в день</b> (монеты):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_offers_menu")]
        ])
    )
    await callback.answer()


@router.callback_query(AdminOfferCreateState.waiting_rentable, F.data == "offer_rent_no")
async def process_offer_rentable_no(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id): return
    await state.update_data(is_rentable=False, rent_cost=0, max_rentals=1)
    await finalize_admin_offer(callback, state)
    await callback.answer()


async def finalize_admin_offer(callback_or_message, state: FSMContext):
    data = await state.get_data()
    async with async_session() as session:
        from app.services import admin_create_offer
        offer = await admin_create_offer(
            session,
            title=data["title"],
            description=data["description"],
            channel_url=data["channel_url"],
            reward_preview=Decimal(data["reward_preview"]),
            reward_final=Decimal(data["reward_final"]),
            penalty_unsubscribe=Decimal(data.get("penalty_unsubscribe", 0)),
            is_rentable=data.get("is_rentable", False),
            rent_cost_per_day=Decimal(data.get("rent_cost", 0)),
            max_simultaneous_rentals=int(data.get("max_rentals", 1)),
            duration_days=int(data.get("duration_days", 30)),
            admin_telegram_id=callback_or_message.from_user.id,
        )

    text = (
        f"🎉 <b>Оффер успешно создан!</b>\n\n"
        f"• Название: <b>{escape(offer.title)}</b>\n"
        f"• Награды: {offer.reward_preview} + {offer.reward_final} монет\n"
        f"• Штраф отписки: {offer.penalty_unsubscribe} монет\n"
        f"• Срок: {offer.duration_days} дней\n"
        f"• Ссылка: {escape(offer.channel_url)}"
    )
    
    if isinstance(callback_or_message, CallbackQuery):
        await callback_or_message.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ К офферам", callback_data="admin_offers_menu")]
            ])
        )
    else:
        await callback_or_message.answer(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ К офферам", callback_data="admin_offers_menu")]
            ])
        )
    await state.clear()


@router.message(AdminOfferCreateState.waiting_rent_cost)
async def process_offer_rent_cost(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    val = (message.text or "").strip().replace(",", ".")
    try:
        cost = Decimal(val)
        if not cost.is_finite() or cost < 0: raise ValueError()
    except Exception:
        await message.answer("❌ Некорректное число монет. Введи положительное число:")
        return
        
    await state.update_data(rent_cost=str(cost))
    await state.set_state(AdminOfferCreateState.waiting_max_rentals)
    await message.answer(
        "🔢 <b>Создание оффера (Шаг 10/10)</b>\n\n"
        "Введи <b>максимальное количество рекламных слотов</b> (сколько каналов может рекламироваться одновременно):",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_offers_menu")]
        ])
    )


@router.message(AdminOfferCreateState.waiting_max_rentals)
async def process_offer_max_rentals(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id): return
    try:
        max_rentals = int((message.text or "").strip())
        if not 1 <= max_rentals <= 100:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи целое число слотов от 1 до 100:")
        return

    await state.update_data(max_rentals=max_rentals)
    await finalize_admin_offer(message, state)


# Remove the process_offer_penalty_unsubscribe function completely


# ---------- DONATIONALERTS: ОЧЕРЕДЬ ИСКЛЮЧЕНИЙ ----------
@router.callback_query(F.data == "admin_da_exceptions")
async def admin_da_exceptions(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return

    async with async_session() as session:
        exception = (await session.execute(
            select(DonationAlertException)
            .where(DonationAlertException.status == "pending")
            .order_by(DonationAlertException.created_at.asc())
            .limit(1)
        )).scalar_one_or_none()
        pending_count = (await session.execute(
            select(func.count(DonationAlertException.id))
            .where(DonationAlertException.status == "pending")
        )).scalar() or 0

    if not exception:
        await _safe_edit(
            callback,
            "✅ <b>Очередь сверки DonationAlerts пуста.</b>\n\n"
            "Все новые платежи либо автоматически сопоставлены с заказом, либо ещё не поступили.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="◀️ DonationAlerts", callback_data="admin_da_menu")
            ]]),
        )
        await callback.answer()
        return

    suggested = f"Пользователь БД: <code>{exception.suggested_user_id}</code>\n" if exception.suggested_user_id else "Пользователь: не определён\n"
    text = (
        f"⚠️ <b>Сверка DonationAlerts ({pending_count})</b>\n\n"
        f"Донат: <code>{exception.donation_id}</code>\n"
        f"Сумма: <b>{exception.amount} {escape(exception.currency)}</b>\n"
        f"Причина: <code>{escape(exception.reason)}</code>\n"
        f"{suggested}"
        f"Отправитель: <code>{escape(exception.donor_name or '—')}</code>\n"
        f"Сообщение: <code>{escape((exception.message or '—')[:500])}</code>\n\n"
        "Проверьте платёж в DonationAlerts. Ручное начисление используйте только после сверки; "
        "оно не происходит по этой карточке автоматически."
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Ручное зачисление после сверки", callback_data="admin_da_manual_start")],
        [InlineKeyboardButton(text="✅ Закрыть без начисления", callback_data=f"admin_da_exception_close:{exception.id}")],
        [InlineKeyboardButton(text="🔄 Следующее / обновить", callback_data="admin_da_exceptions")],
        [InlineKeyboardButton(text="◀️ DonationAlerts", callback_data="admin_da_menu")],
    ])
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_da_exception_close:"))
async def admin_da_exception_close(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    try:
        exception_id = int(callback.data.rsplit(":", 1)[1])
    except (TypeError, ValueError):
        await callback.answer("Некорректная запись.", show_alert=True)
        return

    async with async_session() as session:
        exception = await session.get(DonationAlertException, exception_id)
        if not exception or exception.status != "pending":
            await callback.answer("Запись уже закрыта или не найдена.", show_alert=True)
            return
        exception.status = "closed"
        exception.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
        exception.resolved_by_telegram_id = callback.from_user.id
        await session.commit()

    await callback.answer("Запись закрыта без начисления.")
    await admin_da_exceptions(callback)


# ====================================================
# ОПРОСЫ АДМИНИСТРАТОРА С НАГРАДОЙ
# ====================================================
_POLL_REWARD = Decimal("20.00")
_POLL_TYPE_LABELS = {
    "single": "один вариант",
    "multiple": "несколько вариантов",
    "text": "свободный ответ",
}


def _poll_admin_keyboard(polls: list[AdminPoll]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="➕ Создать опрос", callback_data="admin_poll_create")],
    ]
    for poll in polls[:8]:
        status = "🟢" if poll.is_active else "⚫"
        rows.append([
            InlineKeyboardButton(
                text=f"{status} #{poll.id} {poll.question[:34]}",
                callback_data=f"admin_poll_view:{poll.id}",
            )
        ])
    rows.append([InlineKeyboardButton(text="◀️ В админку", callback_data="admin_center")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render_admin_polls_menu(callback: CallbackQuery) -> None:
    async with async_session() as session:
        polls = (await session.execute(
            select(AdminPoll).order_by(AdminPoll.is_active.desc(), AdminPoll.id.desc()).limit(8)
        )).scalars().all()
        active_count = int((await session.execute(
            select(func.count(AdminPoll.id)).where(AdminPoll.is_active == True)
        )).scalar_one() or 0)

    text = (
        "📊 <b>Опросы с наградой</b>\n\n"
        "Создавайте опросы с одним вариантом, несколькими вариантами или свободным ответом. "
        "За одно успешное прохождение активного опроса пользователь получает <b>20 монет</b>.\n\n"
        f"Активных опросов: <b>{active_count}</b>"
    )
    await _safe_edit(
        callback,
        text,
        parse_mode="HTML",
        reply_markup=_poll_admin_keyboard(polls),
    )


@router.callback_query(F.data == "admin_polls")
async def admin_polls_menu(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    await _render_admin_polls_menu(callback)
    await callback.answer()


@router.callback_query(F.data == "admin_poll_create")
async def admin_poll_create(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔘 Один вариант", callback_data="admin_poll_type:single")],
        [InlineKeyboardButton(text="☑️ Несколько вариантов", callback_data="admin_poll_type:multiple")],
        [InlineKeyboardButton(text="✍️ Свободный ответ", callback_data="admin_poll_type:text")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_polls")],
    ])
    await _safe_edit(
        callback,
        "➕ <b>Новый опрос</b>\n\nВыбери формат ответа. Награда за прохождение всегда составляет <b>20 монет</b>.",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_poll_type:"))
async def admin_poll_select_type(callback: CallbackQuery, state: FSMContext):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    poll_type = callback.data.split(":", 1)[1]
    if poll_type not in _POLL_TYPE_LABELS:
        await callback.answer("Неизвестный формат.", show_alert=True)
        return
    await state.set_state(AdminPollCreationState.waiting_question)
    await state.update_data(poll_type=poll_type)
    await callback.message.answer(
        "✍️ Напиши вопрос опроса одним сообщением (от 1 до 1000 символов).",
    )
    await callback.answer()


async def _show_poll_preview(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    question = escape(data["poll_question"])
    poll_type = data["poll_type"]
    options = data.get("poll_options", [])
    details = ""
    if options:
        details = "\n\n<b>Варианты:</b>\n" + "\n".join(
            f"{idx + 1}. {escape(option)}" for idx, option in enumerate(options)
        )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Разослать опрос", callback_data="admin_poll_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_polls")],
    ])
    await message.answer(
        f"📋 <b>Предпросмотр опроса</b>\n\n"
        f"<b>Формат:</b> {_POLL_TYPE_LABELS[poll_type]}\n"
        f"<b>Вопрос:</b> {question}{details}\n\n"
        f"Награда каждому участнику: <b>20 монет</b>.\n\n"
        "Разослать опрос всем активным пользователям?",
        parse_mode="HTML",
        reply_markup=keyboard,
    )


@router.message(AdminPollCreationState.waiting_question)
async def admin_poll_receive_question(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    question = (message.text or "").strip()
    if not question:
        await message.answer("❌ Вопрос не может быть пустым.")
        return
    if len(question) > 1000:
        await message.answer("❌ Вопрос слишком длинный: максимум 1000 символов.")
        return
    await state.update_data(poll_question=question)
    data = await state.get_data()
    if data.get("poll_type") == "text":
        await state.update_data(poll_options=[])
        await _show_poll_preview(message, state)
        return
    await state.set_state(AdminPollCreationState.waiting_options)
    await message.answer(
        "📝 Отправь варианты ответов: по одному варианту в каждой строке.\n"
        "Нужно от 2 до 12 вариантов, каждый не длиннее 64 символов.",
    )


@router.message(AdminPollCreationState.waiting_options)
async def admin_poll_receive_options(message: Message, state: FSMContext):
    if not await check_admin(message.from_user.id):
        return
    options = [line.strip() for line in (message.text or "").splitlines() if line.strip()]
    if not 2 <= len(options) <= 12:
        await message.answer("❌ Нужно указать от 2 до 12 вариантов — каждый с новой строки.")
        return
    if len(set(option.casefold() for option in options)) != len(options):
        await message.answer("❌ Варианты не должны повторяться.")
        return
    if any(len(option) > 64 for option in options):
        await message.answer("❌ Каждый вариант должен быть не длиннее 64 символов.")
        return
    await state.update_data(poll_options=options)
    await _show_poll_preview(message, state)


async def _broadcast_admin_poll(bot, creator_telegram_id: int, poll_id: int) -> None:
    """Рассылает опрос фоном, не блокируя обработку обновлений бота."""
    async with async_session() as session:
        poll = await session.get(AdminPoll, poll_id)
        targets = (await session.execute(
            select(User.telegram_id).where(User.status == "active")
        )).scalars().all()
    if not poll or not poll.is_active:
        return

    try:
        options = json.loads(poll.options_json or "[]")
    except (TypeError, json.JSONDecodeError):
        options = []

    header = (
        "📊 <b>Опрос от администрации</b>\n\n"
        f"{escape(poll.question)}\n\n"
        "Пройди опрос один раз и получи <b>20 монет</b>."
    )
    if poll.poll_type == "text":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✍️ Написать ответ", callback_data=f"poll_text:{poll.id}")
        ]])
    elif poll.poll_type == "single":
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=option, callback_data=f"poll_single:{poll.id}:{index}")]
            for index, option in enumerate(options)
        ])
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="☑️ Выбрать варианты", callback_data=f"poll_multi_open:{poll.id}")
        ]])

    sent = 0
    for telegram_id in targets:
        try:
            await bot.send_message(telegram_id, header, parse_mode="HTML", reply_markup=keyboard)
            sent += 1
            if sent % 30 == 0:
                await asyncio.sleep(0.5)
        except Exception:
            continue

    try:
        await bot.send_message(
            creator_telegram_id,
            f"✅ <b>Опрос #{poll_id} разослан.</b>\n\nДоставлено: <b>{sent}</b> активным пользователям.",
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.callback_query(F.data == "admin_poll_confirm")
async def admin_poll_confirm(callback: CallbackQuery, state: FSMContext, bot):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    data = await state.get_data()
    question = (data.get("poll_question") or "").strip()
    poll_type = data.get("poll_type")
    options = data.get("poll_options", [])
    if not question or poll_type not in _POLL_TYPE_LABELS:
        await callback.answer("Черновик опроса не найден. Создай его заново.", show_alert=True)
        return
    if poll_type in {"single", "multiple"} and not options:
        await callback.answer("Укажи варианты ответов.", show_alert=True)
        return

    async with async_session() as session:
        admin = await get_user(session, callback.from_user.id)
        poll = AdminPoll(
            question=question,
            poll_type=poll_type,
            options_json=json.dumps(options, ensure_ascii=False),
            reward=_POLL_REWARD,
            created_by=admin.id if admin else None,
        )
        session.add(poll)
        await session.commit()
        poll_id = poll.id

    await state.clear()
    await _safe_edit(
        callback,
        f"⏳ <b>Опрос #{poll_id} создаётся и рассылается в фоновом режиме.</b>\n\n"
        "После завершения рассылки бот пришлёт количество доставленных сообщений.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 К опросам", callback_data="admin_polls")],
        ]),
    )
    await callback.answer("Рассылка запущена.")
    asyncio.create_task(_broadcast_admin_poll(bot, callback.from_user.id, poll_id))


@router.callback_query(F.data.startswith("admin_poll_view:"))
async def admin_poll_view(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    try:
        poll_id = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("Некорректный опрос.", show_alert=True)
        return

    async with async_session() as session:
        poll = await session.get(AdminPoll, poll_id)
        responses = (await session.execute(
            select(AdminPollResponse).where(AdminPollResponse.poll_id == poll_id).order_by(AdminPollResponse.id.asc())
        )).scalars().all() if poll else []
    if not poll:
        await callback.answer("Опрос не найден.", show_alert=True)
        return

    try:
        options = json.loads(poll.options_json or "[]")
    except (TypeError, json.JSONDecodeError):
        options = []
    status = "🟢 активен" if poll.is_active else "⚫ завершён"
    text = (
        f"📊 <b>Опрос #{poll.id}</b> — {status}\n\n"
        f"<b>Вопрос:</b> {escape(poll.question)}\n"
        f"<b>Формат:</b> {_POLL_TYPE_LABELS.get(poll.poll_type, poll.poll_type)}\n"
        f"<b>Ответов:</b> {len(responses)}\n"
        f"<b>Выдано наград:</b> {len([response for response in responses if response.rewarded_at]) * 20} монет\n\n"
    )
    if poll.poll_type in {"single", "multiple"}:
        counts = [0 for _ in options]
        for response in responses:
            try:
                for index in json.loads(response.answer_options_json or "[]"):
                    if isinstance(index, int) and 0 <= index < len(counts):
                        counts[index] += 1
            except (TypeError, json.JSONDecodeError):
                continue
        text += "<b>Распределение ответов:</b>\n" + "\n".join(
            f"{index + 1}. {escape(option)} — <b>{counts[index]}</b>"
            for index, option in enumerate(options)
        )
    else:
        text += "<b>Последние ответы:</b>\n"
        if responses:
            text += "\n".join(
                f"• {escape((response.answer_text or '—')[:180])}"
                for response in responses[-8:]
            )
        else:
            text += "Пока нет."

    rows = []
    if poll.is_active:
        rows.append([InlineKeyboardButton(text="⏹ Завершить опрос", callback_data=f"admin_poll_close:{poll.id}")])
    rows.append([InlineKeyboardButton(text="◀️ К опросам", callback_data="admin_polls")])
    await _safe_edit(
        callback,
        text[:4000],
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_poll_close:"))
async def admin_poll_close(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    try:
        poll_id = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("Некорректный опрос.", show_alert=True)
        return
    async with async_session() as session:
        poll = await session.get(AdminPoll, poll_id)
        if not poll or not poll.is_active:
            await callback.answer("Опрос уже завершён или не найден.", show_alert=True)
            return
        poll.is_active = False
        poll.closed_at = utc_now()
        await session.commit()
    await callback.answer("Опрос завершён.")
    await admin_poll_view(callback)
