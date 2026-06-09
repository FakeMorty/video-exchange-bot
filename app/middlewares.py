from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from app.db import async_session
from app.services import get_user

class BanCheckMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user_id = None
        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id
            
        if user_id:
            async with async_session() as session:
                user = await get_user(session, user_id)
                if user and user.status == "banned":
                    if isinstance(event, Message):
                        await event.answer("🚫 Вы заблокированы.")
                    elif isinstance(event, CallbackQuery):
                        await event.answer("🚫 Вы заблокированы.", show_alert=True)
                    return
        return await handler(event, data)