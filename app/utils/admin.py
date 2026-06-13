from aiogram.types import CallbackQuery
from app.config import ADMINS
from app.db import async_session
from app.services import get_user

def is_super_admin(tid: int) -> bool:
    return tid in ADMINS


async def _safe_edit(callback: CallbackQuery, text: str, **kwargs):
    try:
        await callback.message.edit_text(text, **kwargs)
    except Exception:
        await callback.message.answer(text, **kwargs)

async def check_admin(tid: int) -> bool:
    if tid in ADMINS:
        return True
    async with async_session() as session:
        user = await get_user(session, tid)
        if user and user.is_admin:
            return True
    return False
