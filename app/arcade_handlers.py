"""
🚀 Космическая Аркада — хендлеры bot-стороны (меню, топ, «как открыть»).

Сама игра — HTML5 Mini App (страница `/arcade` и API `/api/arcade/*`
в app/main.py). Все игровые исходы считает сервер (crash-модель), клиент
не может влиять на экономику.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_DOWN
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, select

from app.arcade import GAME_TYPE, _fmt, load_arcade_config
from app.db import async_session
from app.logger import get_logger
from app.models import GameHistory, utc_now
from app.services import get_user, has_valid_nickname

logger = get_logger(__name__)

router = Router(name="arcade")


def arcade_webapp_url() -> str:
    """Публичный URL Mini App (как у Live-трансляции Секслото)."""
    from app.config import WEBHOOK_BASE
    base = (WEBHOOK_BASE or "").rstrip("/")
    return f"{base}/arcade" if base else ""


def _menu_text(cfg) -> str:
    return (
        "🚀 <b>Космическая Аркада</b>\n\n"
        "Отбивай волны инопланетного флота 👾 в настоящей аркаде (Mini App) "
        "и наращивай множитель ставки!\n\n"
        "🔫 Каждая уничтоженная волна — множитель растёт.\n"
        "☠️ Рано или поздно флот прорвётся — ставка сгорит.\n"
        "💰 Забирай выигрыш, пока не поздно!\n\n"
        f"💵 Ставка: от <b>{_fmt(cfg.min_bet)}</b> до <b>{_fmt(cfg.max_bet)}</b> монет\n"
        f"📈 Макс. множитель: <b>x{_fmt(cfg.max_multiplier)}</b>\n"
        f"🛡 Дневной кап чистой прибыли: <b>{_fmt(cfg.daily_profit_cap)}</b> монет"
    )


def _menu_keyboard(cfg) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    url = arcade_webapp_url()
    if url:
        from aiogram.types.web_app_info import WebAppInfo
        buttons.append([InlineKeyboardButton(text="🎮 Играть (Mini App)", web_app=WebAppInfo(url=url))])
    else:
        buttons.append([InlineKeyboardButton(text="🎮 Как открыть игру", callback_data="arcade_howto")])
    buttons.extend([
        [InlineKeyboardButton(text="🏆 Топ аркады", callback_data="arcade_top")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="arcade_menu")],
        [InlineKeyboardButton(text="◀️ Игровой центр", callback_data="arcade_to_games")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ============================
# МЕНЮ
# ============================

@router.callback_query(F.data == "arcade_menu")
async def arcade_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    async with async_session() as session:
        cfg = await load_arcade_config(session)
        if not cfg.enabled:
            await callback.answer("⛔ Аркада временно отключена.", show_alert=True)
            return
        user = await get_user(session, callback.from_user.id)
        if user and not has_valid_nickname(user):
            await callback.answer("⚠️ Сначала установи нормальный ник в Профиле!", show_alert=True)
            return
    try:
        await callback.message.edit_text(
            _menu_text(cfg), parse_mode="HTML", reply_markup=_menu_keyboard(cfg)
        )
    except Exception:
        await callback.message.answer(
            _menu_text(cfg), parse_mode="HTML", reply_markup=_menu_keyboard(cfg)
        )
    await callback.answer()


@router.callback_query(F.data == "arcade_howto")
async def arcade_howto(callback: CallbackQuery):
    text = (
        "🎮 <b>Как открыть Космическую аркаду</b>\n\n"
        "Игра открывается как Telegram Mini App по прямой ссылке:\n"
        f"<code>/arcade</code> на сервере бота.\n\n"
        "⚠️ Сейчас публичный адрес не настроен: задайте переменную окружения "
        "<code>WEBHOOK_BASE</code> (например <code>https://mybot.example.com</code>), "
        "и кнопка «Играть» появится автоматически."
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "arcade_to_games")
async def arcade_to_games(callback: CallbackQuery):
    from app.keyboards import games_menu_keyboard
    await callback.message.answer(
        "🎮 <b>Игровой центр</b>\n\nВыберите раздел:",
        parse_mode="HTML",
        reply_markup=games_menu_keyboard(),
    )
    await callback.answer()


# ============================
# ТОП НЕДЕЛИ
# ============================

@router.callback_query(F.data == "arcade_top")
async def arcade_top(callback: CallbackQuery):
    from app.models import User

    week_ago = utc_now() - timedelta(days=7)
    async with async_session() as session:
        rows = (await session.execute(
            select(
                User.display_name,
                func.sum(GameHistory.result).label("net"),
                func.count(GameHistory.id).label("games"),
            )
            .join(User, User.id == GameHistory.user_id)
            .where(
                GameHistory.game_type == GAME_TYPE,
                GameHistory.created_at >= week_ago,
            )
            .group_by(GameHistory.user_id, User.display_name)
            .having(func.sum(GameHistory.result) > 0)
            .order_by(func.sum(GameHistory.result).desc())
            .limit(10)
        )).all()

    if not rows:
        text = "🏆 <b>Топ аркады (7 дней)</b>\n\nПока никто не вышел в плюс — будь первым! 🚀"
    else:
        medals = {0: "🥇", 1: "🥈", 2: "🥉"}
        lines = ["🏆 <b>Топ аркады (7 дней)</b>\n"]
        for i, (name, net, games) in enumerate(rows):
            medal = medals.get(i, f"{i + 1}.")
            lines.append(
                f"{medal} <b>{escape(name or 'Игрок')}</b> — +{_fmt(Decimal(net))} монет ({games} заб.)"
            )
        text = "\n".join(lines)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Меню аркады", callback_data="arcade_menu")],
    ])
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()
