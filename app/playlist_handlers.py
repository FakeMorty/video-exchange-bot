"""VIP-only personal video playlist flows for the Telegram bot."""
from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.db import async_session
from app.i18n import t
from app.keyboards import menu_button_variants, video_rating_keyboard
from app.models import User
from app.playlists import (
    MAX_PLAYLIST_ITEMS,
    MAX_PLAYLIST_NAME_LENGTH,
    MAX_PLAYLISTS_PER_USER,
    PLAYLIST_PAGE_SIZE,
    PlaylistError,
    add_video_to_playlist,
    create_user_playlist,
    delete_user_playlist,
    get_playlist_page,
    get_playlist_video,
    get_user_playlists,
    remove_video_from_playlist,
)
from app.services import get_user, is_admin_or_super, is_vip

router = Router()


class PlaylistCreateState(StatesGroup):
    waiting_name = State()


def _locked_message(user: User | None) -> str:
    if user and user.vip_until:
        return t(
            "⏸ <b>VIP закончился {until}.</b>\n\n"
            "Плейлист не удалён: он сохранится и снова станет доступен после продления подписки.",
            until=user.vip_until.strftime("%d.%m.%Y %H:%M"),
        )
    return t(
        "🔒 <b>Плейлисты доступны только с активным VIP.</b>\n\n"
        "Если подписка закончится, созданные плейлисты не удалятся — они будут скрыты до продления."
    )


def _vip_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t("🛍 Продлить VIP"), callback_data="store_menu")]
    ])


def _error_text(error: PlaylistError) -> str:
    messages = {
        "user_not_found": t("Пользователь не найден. Открой бота командой /start."),
        "vip_required": t("🔒 Действие доступно только с активным VIP. Плейлисты сохраняются до продления."),
        "invalid_name": t(
            "Название должно содержать от 1 до {max_len} символов.",
            max_len=MAX_PLAYLIST_NAME_LENGTH,
        ),
        "duplicate_name": t("Плейлист с таким названием уже есть. Выбери другое."),
        "playlist_limit": t(
            "Можно создать не больше {max_playlists} плейлистов.",
            max_playlists=MAX_PLAYLISTS_PER_USER,
        ),
        "playlist_full": t(
            "В одном плейлисте может быть не больше {max_items} видео.",
            max_items=MAX_PLAYLIST_ITEMS,
        ),
        "playlist_not_found": t("Плейлист не найден или не принадлежит тебе."),
        "video_unavailable": t("Видео больше недоступно: сохранять можно только одобренные ролики."),
        "author_blocked": t("Ты заблокировал автора этого видео, поэтому открыть его нельзя."),
        "video_not_watched": t("Сначала посмотри видео в ленте — добавлять можно уже просмотренные ролики."),
        "already_added": t("Это видео уже есть в плейлисте."),
        "item_not_found": t("Этого видео нет в выбранном плейлисте."),
    }
    return messages.get(error.code, t("Не удалось выполнить действие с плейлистом. Попробуй ещё раз."))


async def _send_locked(message: Message, user: User | None) -> None:
    await message.answer(
        _locked_message(user),
        parse_mode="HTML",
        reply_markup=_vip_keyboard(),
    )


async def _lock_callback(callback: CallbackQuery, user: User | None) -> None:
    try:
        await callback.answer(t("🔒 Нужен активный VIP. Плейлист сохранён до продления."), show_alert=True)
    except Exception:
        pass
    if callback.message:
        await _send_locked(callback.message, user)


def _playlist_home_markup(playlists: list[tuple[object, int]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for playlist, item_count in playlists:
        name = playlist.name
        if len(name) > 32:
            name = name[:31].rstrip() + "…"
        rows.append([
            InlineKeyboardButton(
                text=t("🎵 {name} · {count} видео", name=name, count=item_count),
                callback_data=f"playlist_open:{playlist.id}:0",
            )
        ])
    if len(playlists) < MAX_PLAYLISTS_PER_USER:
        rows.append([InlineKeyboardButton(text=t("➕ Создать плейлист"), callback_data="playlist_create")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_playlist_home(message: Message, telegram_id: int) -> None:
    async with async_session() as session:
        user = await get_user(session, telegram_id)
        if not user:
            return
        if not is_vip(user):
            await _send_locked(message, user)
            return
        try:
            playlists = await get_user_playlists(session, user.id)
        except PlaylistError as error:
            if error.code == "vip_required":
                await _send_locked(message, user)
                return
            raise

    text = t(
        "🎵 <b>Мои плейлисты</b>\n\n"
        "Создавай личные подборки из уже просмотренных видео. Сохранённые ролики можно открыть повторно без нового списания.\n\n"
        "Когда VIP закончится, подборки временно скроются, но останутся сохранёнными и снова откроются после продления."
    )
    if not playlists:
        text += "\n\n" + t(
            "🗂 Создай первый плейлист, а затем добавляй просмотренные ролики кнопкой «➕ В плейлист» под видео."
        )
    elif len(playlists) >= MAX_PLAYLISTS_PER_USER:
        text += "\n\n" + t(
            "Достигнут лимит: {max_playlists} плейлистов.",
            max_playlists=MAX_PLAYLISTS_PER_USER,
        )

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=_playlist_home_markup(playlists),
    )


async def _start_create(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    pending_video_id: int | None = None,
) -> None:
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        if not is_vip(user):
            await _lock_callback(callback, user)
            return
        playlists = await get_user_playlists(session, user.id)
        if len(playlists) >= MAX_PLAYLISTS_PER_USER:
            await callback.answer()
            if callback.message:
                await callback.message.answer(_error_text(PlaylistError("playlist_limit")))
            return

    await state.clear()
    await state.set_state(PlaylistCreateState.waiting_name)
    await state.update_data(pending_video_id=pending_video_id)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            t(
                "✏️ Отправь название плейлиста одним сообщением (от 1 до {max_len} символов).",
                max_len=MAX_PLAYLIST_NAME_LENGTH,
            ),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t("❌ Отмена"), callback_data="playlist_cancel_create")]
            ]),
        )


@router.message(F.text.in_(menu_button_variants("playlists")))
async def open_my_playlists(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _show_playlist_home(message, message.from_user.id)


@router.callback_query(F.data == "playlist_home")
async def callback_playlist_home(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await _show_playlist_home(callback.message, callback.from_user.id)


@router.callback_query(F.data == "playlist_create")
async def callback_playlist_create(callback: CallbackQuery, state: FSMContext) -> None:
    await _start_create(callback, state)


@router.callback_query(F.data.startswith("playlist_create_from:"))
async def callback_playlist_create_from_video(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        video_id = int(callback.data.rsplit(":", 1)[1])
    except (TypeError, ValueError, IndexError):
        await callback.answer(t("Видео не найдено."), show_alert=True)
        return
    await _start_create(callback, state, pending_video_id=video_id)


@router.callback_query(F.data == "playlist_cancel_create")
async def callback_cancel_playlist_create(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer(t("Создание плейлиста отменено."))
    if callback.message:
        await callback.message.answer(t("Создание плейлиста отменено."))


@router.message(PlaylistCreateState.waiting_name)
async def receive_playlist_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name or len(name) > MAX_PLAYLIST_NAME_LENGTH:
        await message.answer(_error_text(PlaylistError("invalid_name")))
        return

    data = await state.get_data()
    pending_video_id = data.get("pending_video_id")
    try:
        pending_video_id = int(pending_video_id) if pending_video_id is not None else None
    except (TypeError, ValueError):
        pending_video_id = None

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await state.clear()
            return
        if not is_vip(user):
            await state.clear()
            await _send_locked(message, user)
            return
        try:
            playlist = await create_user_playlist(session, user.id, name)
            playlist_name = playlist.name
            playlist_id = playlist.id
            await session.commit()
        except PlaylistError as error:
            if error.code not in {"invalid_name", "duplicate_name"}:
                await state.clear()
            await message.answer(_error_text(error))
            return

        added_video = False
        add_error: PlaylistError | None = None
        if pending_video_id is not None:
            try:
                await add_video_to_playlist(session, user.id, playlist_id, pending_video_id)
                await session.commit()
                added_video = True
            except PlaylistError as error:
                await session.rollback()
                add_error = error

    await state.clear()
    if added_video:
        notice = t("✅ Создан плейлист «{name}», видео добавлено.", name=escape(playlist_name, quote=False))
    elif add_error:
        notice = t(
            "✅ Плейлист «{name}» создан. Видео не добавлено: {reason}",
            name=escape(playlist_name, quote=False),
            reason=_error_text(add_error),
        )
    else:
        notice = t("✅ Плейлист «{name}» создан.", name=escape(playlist_name, quote=False))
    await message.answer(notice, parse_mode="HTML")
    await _show_playlist_home(message, message.from_user.id)


@router.callback_query(F.data.startswith("playlist_add:"))
async def callback_playlist_add(callback: CallbackQuery) -> None:
    try:
        video_id = int(callback.data.split(":", 1)[1])
    except (TypeError, ValueError, IndexError):
        await callback.answer(t("Видео не найдено."), show_alert=True)
        return

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        if not is_vip(user):
            await _lock_callback(callback, user)
            return
        playlists = await get_user_playlists(session, user.id)

    rows = [
        [InlineKeyboardButton(
            text=t("🎵 {name}", name=playlist.name[:40]),
            callback_data=f"playlist_add_to:{playlist.id}:{video_id}",
        )]
        for playlist, _count in playlists
    ]
    create_callback = "playlist_create_from:" + str(video_id)
    if len(playlists) < MAX_PLAYLISTS_PER_USER:
        rows.append([InlineKeyboardButton(
            text=t("➕ Создать новый плейлист"),
            callback_data=create_callback,
        )])
    if not rows:
        rows.append([InlineKeyboardButton(
            text=t("➕ Создать плейлист"),
            callback_data=create_callback,
        )])

    await callback.answer()
    if callback.message:
        prompt = t("Выбери плейлист, куда добавить видео:") if playlists else t(
            "Пока нет плейлистов. Создай первый — это видео добавится сразу после ввода названия."
        )
        await callback.message.answer(
            prompt,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )


@router.callback_query(F.data.startswith("playlist_add_to:"))
async def callback_playlist_add_to(callback: CallbackQuery) -> None:
    try:
        _prefix, playlist_id, video_id = callback.data.split(":", 2)
        playlist_id, video_id = int(playlist_id), int(video_id)
    except (TypeError, ValueError):
        await callback.answer(t("Не удалось выполнить действие с плейлистом."), show_alert=True)
        return

    user: User | None = None
    try:
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not user:
                await callback.answer()
                return
            if not is_vip(user):
                await _lock_callback(callback, user)
                return
            playlist = await add_video_to_playlist(session, user.id, playlist_id, video_id)
            await session.commit()
    except PlaylistError as error:
        if error.code == "vip_required":
            await _lock_callback(callback, user)
            return
        await callback.answer(_error_text(error), show_alert=True)
        return

    await callback.answer(t("✅ Добавлено в плейлист."))
    if callback.message:
        await callback.message.answer(
            t("✅ Видео добавлено в «{name}».", name=escape(playlist.name, quote=False)),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t("🎵 Открыть плейлисты"), callback_data="playlist_home")]
            ]),
        )


@router.callback_query(F.data.startswith("playlist_open:"))
async def callback_playlist_open(callback: CallbackQuery) -> None:
    try:
        _prefix, playlist_id, offset = callback.data.split(":", 2)
        playlist_id, offset = int(playlist_id), max(0, int(offset))
    except (TypeError, ValueError):
        await callback.answer(t("Плейлист не найден."), show_alert=True)
        return

    await callback.answer()
    if callback.message:
        await _show_playlist_page(callback.message, callback.from_user.id, playlist_id, offset)


@router.callback_query(F.data.startswith("playlist_watch:"))
async def callback_playlist_watch(callback: CallbackQuery) -> None:
    try:
        _prefix, playlist_id, video_id = callback.data.split(":", 2)
        playlist_id, video_id = int(playlist_id), int(video_id)
    except (TypeError, ValueError):
        await callback.answer(t("Видео не найдено."), show_alert=True)
        return

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        if not is_vip(user):
            await _lock_callback(callback, user)
            return
        if not isinstance(callback.message, Message):
            await callback.answer()
            return
        from app.user_handlers import require_view_access
        if not await require_view_access(callback.message, user, session):
            await callback.answer()
            return
        try:
            playlist, video = await get_playlist_video(session, user.id, playlist_id, video_id)
        except PlaylistError as error:
            if error.code == "vip_required":
                await _lock_callback(callback, user)
                return
            await callback.answer(_error_text(error), show_alert=True)
            return

        if video.status != "approved" or video.content_type != "video":
            await callback.answer(t("⛔ Это видео сейчас нельзя посмотреть."), show_alert=True)
            return

        await callback.answer()
        await callback.message.answer_video(
            video.telegram_file_id,
            caption=t(
                "🎵 Плейлист «{name}» · видео #{video_id}",
                name=escape(playlist.name, quote=False),
                video_id=video.id,
            ),
            parse_mode="HTML",
            reply_markup=video_rating_keyboard(
                video.id,
                is_admin=is_admin_or_super(callback.from_user.id, user),
            ),
        )


@router.callback_query(F.data.startswith("playlist_remove:"))
async def callback_playlist_remove(callback: CallbackQuery) -> None:
    try:
        _prefix, playlist_id, video_id, offset = callback.data.split(":", 3)
        playlist_id, video_id, offset = int(playlist_id), int(video_id), max(0, int(offset))
    except (TypeError, ValueError):
        await callback.answer(t("Не удалось выполнить действие с плейлистом."), show_alert=True)
        return

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        if not is_vip(user):
            await _lock_callback(callback, user)
            return
        try:
            removed = await remove_video_from_playlist(session, user.id, playlist_id, video_id)
            await session.commit()
        except PlaylistError as error:
            if error.code == "vip_required":
                await _lock_callback(callback, user)
                return
            await callback.answer(_error_text(error), show_alert=True)
            return

    await callback.answer(t("✅ Видео удалено из плейлиста.") if removed else t("Видео уже удалено из плейлиста."))
    if callback.message:
        await _show_playlist_page(callback.message, callback.from_user.id, playlist_id, offset)


async def _show_playlist_page(message: Message, telegram_id: int, playlist_id: int, offset: int) -> None:
    """Render a playlist page without relying on a callback message payload."""
    async with async_session() as session:
        user = await get_user(session, telegram_id)
        if not user:
            return
        if not is_vip(user):
            await _send_locked(message, user)
            return
        try:
            playlist, total, entries = await get_playlist_page(
                session,
                user.id,
                playlist_id,
                offset=offset,
                limit=PLAYLIST_PAGE_SIZE,
            )
            if total == 0:
                offset = 0
            elif offset >= total:
                offset = ((total - 1) // PLAYLIST_PAGE_SIZE) * PLAYLIST_PAGE_SIZE
                playlist, total, entries = await get_playlist_page(
                    session,
                    user.id,
                    playlist_id,
                    offset=offset,
                    limit=PLAYLIST_PAGE_SIZE,
                )
        except PlaylistError as error:
            if error.code == "vip_required":
                await _send_locked(message, user)
            else:
                await message.answer(_error_text(error))
            return

    page_count = max(1, (total + PLAYLIST_PAGE_SIZE - 1) // PLAYLIST_PAGE_SIZE)
    current_page = min(page_count, offset // PLAYLIST_PAGE_SIZE + 1)
    text = t(
        "🎵 <b>{name}</b>\n\nВидео в подборке: <b>{total}</b>\nСтраница {page} из {pages}.",
        name=escape(playlist.name, quote=False), total=total, page=current_page, pages=page_count,
    )
    if not entries:
        text += "\n\n" + t("Пока здесь пусто. Добавляй просмотренные ролики кнопкой «➕ В плейлист».")
    rows: list[list[InlineKeyboardButton]] = []
    for index, (_item, video) in enumerate(entries, start=offset + 1):
        if video.status == "approved" and video.content_type == "video":
            label, callback_data = t("▶️ Видео #{video_id}", video_id=video.id), f"playlist_watch:{playlist.id}:{video.id}"
        else:
            label, callback_data = t("⛔ Видео #{video_id} недоступно", video_id=video.id), "playlist_unavailable"
        rows.append([
            InlineKeyboardButton(text=f"{index}. {label}", callback_data=callback_data),
            InlineKeyboardButton(text=t("✖️"), callback_data=f"playlist_remove:{playlist.id}:{video.id}:{offset}"),
        ])
    nav: list[InlineKeyboardButton] = []
    if offset > 0:
        nav.append(InlineKeyboardButton(text=t("◀️ Назад"), callback_data=f"playlist_open:{playlist.id}:{max(0, offset - PLAYLIST_PAGE_SIZE)}"))
    if offset + PLAYLIST_PAGE_SIZE < total:
        nav.append(InlineKeyboardButton(text=t("Дальше ▶️"), callback_data=f"playlist_open:{playlist.id}:{offset + PLAYLIST_PAGE_SIZE}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text=t("🗑 Удалить плейлист"), callback_data=f"playlist_delete_confirm:{playlist.id}")])
    rows.append([InlineKeyboardButton(text=t("◀️ К моим плейлистам"), callback_data="playlist_home")])
    await message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "playlist_unavailable")
async def callback_playlist_unavailable(callback: CallbackQuery) -> None:
    await callback.answer(t("⛔ Видео скрыто или отклонено модерацией."), show_alert=True)


@router.callback_query(F.data.startswith("playlist_delete_confirm:"))
async def callback_playlist_delete_confirm(callback: CallbackQuery) -> None:
    try:
        playlist_id = int(callback.data.rsplit(":", 1)[1])
    except (TypeError, ValueError, IndexError):
        await callback.answer(t("Плейлист не найден."), show_alert=True)
        return
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        if not is_vip(user):
            await _lock_callback(callback, user)
            return
        try:
            playlist, _total, _entries = await get_playlist_page(
                session, user.id, playlist_id, offset=0, limit=1
            )
        except PlaylistError as error:
            await callback.answer(_error_text(error), show_alert=True)
            return

    await callback.answer()
    if callback.message:
        await callback.message.answer(
            t(
                "⚠️ <b>Удалить плейлист «{name}»?</b>\n\nВсе видео будут убраны из подборки. Это действие нельзя отменить.",
                name=escape(playlist.name, quote=False),
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=t("✅ Да, удалить"), callback_data=f"playlist_delete:{playlist_id}")],
                [InlineKeyboardButton(text=t("↩️ Отмена"), callback_data=f"playlist_open:{playlist_id}:0")],
            ]),
        )


@router.callback_query(F.data.startswith("playlist_delete:"))
async def callback_playlist_delete(callback: CallbackQuery) -> None:
    try:
        playlist_id = int(callback.data.rsplit(":", 1)[1])
    except (TypeError, ValueError, IndexError):
        await callback.answer(t("Плейлист не найден."), show_alert=True)
        return
    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        if not is_vip(user):
            await _lock_callback(callback, user)
            return
        try:
            deleted = await delete_user_playlist(session, user.id, playlist_id)
            await session.commit()
        except PlaylistError as error:
            if error.code == "vip_required":
                await _lock_callback(callback, user)
                return
            await callback.answer(_error_text(error), show_alert=True)
            return

    await callback.answer(t("✅ Плейлист удалён.") if deleted else t("Плейлист не найден."))
    if callback.message and deleted:
        await _show_playlist_home(callback.message, callback.from_user.id)
