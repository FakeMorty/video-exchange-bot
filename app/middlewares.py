import time

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

from app.db import async_session, is_db_unavailable_error
from app.services import get_user
from app.logger import get_logger, log_warning

logger = get_logger(__name__)

DB_DOWN_TEXT = (
    "⚠️ Бот временно недоступен (ведутся технические работы). "
    "Попробуйте, пожалуйста, позже."
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
            try:
                async with async_session() as session:
                    user = await get_user(session, user_id)
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

            if user and user.status == "banned":
                if isinstance(event, Message):
                    await event.answer("🚫 Вы заблокированы.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("🚫 Вы заблокированы.", show_alert=True)
                return
        return await handler(event, data)
