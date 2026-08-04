import time

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

from app.db import async_session, is_db_unavailable_error
from app.services import get_user
from app.logger import get_logger, log_warning, log_error

logger = get_logger(__name__)

DB_DOWN_TEXT = (
    "⚠️ Бот временно недоступен (ведутся технические работы). "
    "Попробуй, пожалуйста, позже."
)

# Троттлинг, чтобы при падении БД не спамить:
# в лог — не чаще раза в минуту, пользователю — не чаще раза в 5 минут.
_LOG_INTERVAL_SECONDS = 60
_NOTICE_INTERVAL_SECONDS = 300
_last_log_ts = 0.0
_last_notice_ts = 0.0


class BanCheckMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        global _last_log_ts, _last_notice_ts

        user_id = None
        if isinstance(event, (Message, CallbackQuery)):
            user_id = event.from_user.id

        if user_id:
            user_banned = False
            daily_bonus_granted = None
            try:
                async with async_session() as session:
                    user = await get_user(session, user_id)
                    if user:
                        user_banned = (user.status == "banned")
                        # Авто-бонус за ежедневный возврат: строго внутри открытой
                        # сессии, чтобы пометка (last_bonus_at) реально писалась в БД.
                        if not user_banned:
                            try:
                                from app.services import auto_daily_return_bonus
                                daily_bonus_granted = await auto_daily_return_bonus(session, user)
                            except Exception as e:
                                log_error(logger, f"Daily return bonus error: {e}")
            except Exception as e:
                if not is_db_unavailable_error(e):
                    raise
                # БД недоступна (например, исчерпана compute-квота Neon):
                # дальше всё равно всё упадёт — коротко логируем и вежливо
                # отвечаем пользователю вместо трейсбека на каждый апдейт.
                now = time.monotonic()
                if now - _last_log_ts >= _LOG_INTERVAL_SECONDS:
                    _last_log_ts = now
                    log_warning(
                        logger,
                        f"DB unavailable, update skipped: {type(e).__name__}: {e}",
                    )
                if now - _last_notice_ts >= _NOTICE_INTERVAL_SECONDS:
                    _last_notice_ts = now
                    try:
                        if isinstance(event, Message):
                            await event.answer(DB_DOWN_TEXT)
                        else:
                            await event.answer(DB_DOWN_TEXT, show_alert=True)
                    except Exception:
                        pass
                return

            if user_banned:
                if isinstance(event, Message):
                    await event.answer("🚫 Доступ к боту для тебя заблокирован.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("🚫 Доступ к боту для тебя заблокирован.", show_alert=True)
                return

            # Сообщение о бонусе шлём уже после закрытия сессии (начисление зафиксировано).
            if daily_bonus_granted:
                reward, streak = daily_bonus_granted
                try:
                    await data["bot"].send_message(
                        user_id,
                        "🔥 <b>Ежедневный бонус за возвращение!</b>\n\n"
                        f"Начислено: <b>+{reward:.0f}</b> монет\n"
                        f"Дней подряд: <b>{streak}</b>\n\n"
                        "Заходи каждый день — бонус растёт с серией!",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
        return await handler(event, data)
