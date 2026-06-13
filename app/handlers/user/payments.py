"""
Payment handlers.
"""
from aiogram import Router, F
from aiogram.types import PreCheckoutQuery, Message

from app.db import async_session
from app.services import update_user_balance, get_user

router = Router()

async def pre_checkout(query: PreCheckoutQuery):
    payload = query.invoice_payload or ""
    allowed = (
        payload.startswith("pack_")
        or payload.startswith("custom_")
        or payload.startswith("vip_")
        or payload.startswith("promo_")
        or payload.startswith("lootbox_")
    )
    if not allowed:
        await query.answer(ok=False, error_message="Неверный платёжный payload.")
        return
    async with async_session() as session:
        user = await get_user(session, query.from_user.id)
        if not user:
            await query.answer(ok=False, error_message="Пользователь не найден.")
            return
        payment = await get_payment_by_payload(session, payload)
        if not payment:
            await query.answer(ok=False, error_message="Платёж не найден.")
            return
        if payment.user_id != user.id:
            await query.answer(ok=False, error_message="Платёж принадлежит другому пользователю.")
            return
        if payment.status != "pending":
            await query.answer(ok=False, error_message="Платёж уже обработан.")
            return
        if int(payment.stars_amount) != int(query.total_amount):
            await query.answer(ok=False, error_message="Сумма платежа не совпадает.")
            return
    await query.answer(ok=True)


@router.message(F.successful_payment)
