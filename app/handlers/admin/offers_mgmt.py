"""
Offers management (review, approve, reject, toggle, delete).
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select

from app.db import async_session
from app.models import Offer
from app.utils.admin import check_admin
from app.keyboards import admin_after_action_keyboard

router = Router()

@router.callback_query(F.data == "admin_offers_pending")
async def admin_offers_pending(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        offers = (await session.execute(
            select(Offer).where(Offer.status == "pending")
            .order_by(Offer.created_at)
        )).scalars().all()

    if not offers:
        await callback.message.answer(
            "✅ Нет офферов на проверку.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀ Назад", callback_data="admin_offers_menu")]
            ])
        )
        await callback.answer()
        return

    kb_buttons = []
    for offer in offers:
        kb_buttons.append([InlineKeyboardButton(
            text=f"📢 {offer.title[:35]}",
            callback_data=f"admin_review_offer:{offer.id}"
        )])
    kb_buttons.append([InlineKeyboardButton(text="◀ Назад", callback_data="admin_offers_menu")])
    await callback.message.answer(
        f"⏳ <b>Офферы на проверку ({len(offers)})</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    )
    await callback.answer()


@router.callback_query(F.data == "admin_offers_all")
async def admin_offers_all(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        offers = (await session.execute(
            select(Offer).order_by(desc(Offer.created_at)).limit(25)
        )).scalars().all()

    if not offers:
        await callback.message.answer("Офферов нет.")
        await callback.answer()
        return

    text = "📋 <b>Все офферы (последние 25)</b>\n\n"
    for o in offers:
        icon = "✅" if o.is_active else ("⏳" if o.status == "pending" else "❌")
        rent_icon = "🔑" if getattr(o, "is_rentable", False) else ""
        text += (
            f"{icon}{rent_icon} #{o.id} <b>{o.title[:30]}</b>\n"
            f"  Статус: {o.status} | "
            f"Награда: {o.reward_preview}+{o.reward_final}\n"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_offers_menu")]
    ])
    if len(text) > 4000:
        text = text[:4000] + "\n..."
    await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "admin_offers_active")
async def admin_offers_active(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        offers = (await session.execute(
            select(Offer).where(
                Offer.is_active,
                Offer.status == "approved"
            ).order_by(desc(Offer.created_at))
        )).scalars().all()

    if not offers:
        await callback.message.answer(
            "Нет активных офферов.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀ Назад", callback_data="admin_offers_menu")]
            ])
        )
        await callback.answer()
        return

    kb_buttons = []
    for o in offers:
        rent_icon = "🔑" if getattr(o, "is_rentable", False) else ""
        kb_buttons.append([InlineKeyboardButton(
            text=f"✅{rent_icon} #{o.id} {o.title[:30]}",
            callback_data=f"admin_review_offer:{o.id}"
        )])
    kb_buttons.append([InlineKeyboardButton(text="◀ Назад", callback_data="admin_offers_menu")])
    await callback.message.answer(
        f"✅ <b>Активные офферы ({len(offers)})</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_review_offer:"))
async def admin_review_offer(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    offer_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        offer = (await session.execute(
            select(Offer).where(Offer.id == offer_id)
        )).scalar_one_or_none()
        if not offer:
            await callback.answer("Не найдено.", show_alert=True)
            return

        participants = (await session.execute(
            select(func.count(OfferParticipation.id)).where(
                OfferParticipation.offer_id == offer_id
            )
        )).scalar_one()

        completed = (await session.execute(
            select(func.count(OfferParticipation.id)).where(
                OfferParticipation.offer_id == offer_id,
                OfferParticipation.status == "completed"
            )
        )).scalar_one()

        active_rentals_count = 0
        # Rentals system is disabled, so skip count
        # try:
        #     active_rentals_count = (await session.execute(...)).scalar_one()
        # except Exception:
        #     pass

    is_rentable = getattr(offer, "is_rentable", False)
    rent_cost = getattr(offer, "rent_cost_per_day", 0)
    max_rentals = getattr(offer, "max_simultaneous_rentals", 0)

    text = (
        f"📢 <b>Оффер #{offer.id}</b>\n\n"
        f"Название: <b>{offer.title}</b>\n"
        f"Описание: {offer.description}\n"
        f"URL: {offer.channel_url}\n"
        f"Статус: <b>{offer.status}</b> | "
        f"Активен: {'✅' if offer.is_active else '❌'}\n"
        f"💰 Награда: {offer.reward_preview} + {offer.reward_final}\n"
        f"Участников: {participants} | Завершили: {completed}\n"
        f"🔑 Аренда: {'✅' if is_rentable else '❌'}"
    )
    if is_rentable:
        text += (
            f"\n  Цена: {rent_cost} монет/день\n"
            f"  Макс. арендаторов: {max_rentals}\n"
            f"  Активных аренд: {active_rentals_count}"
        )
    text += f"\n📅 Создан: {offer.created_at.strftime('%d.%m.%Y %H:%M')}"

    action_buttons = []
    if offer.status == "pending":
        action_buttons.append([
            InlineKeyboardButton(
                text="✅ Одобрить",
                callback_data=f"approve_offer:{offer_id}"
            ),
            InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data=f"reject_offer:{offer_id}"
            ),
        ])
    else:
        toggle_text = "🔴 Деактивировать" if offer.is_active else "🟢 Активировать"
        action_buttons.append([
            InlineKeyboardButton(
                text=toggle_text,
                callback_data=f"toggle_offer:{offer_id}"
            ),
        ])

    action_buttons.append([
        InlineKeyboardButton(
            text="🗑 Удалить",
            callback_data=f"delete_offer:{offer_id}"
        ),
    ])
    action_buttons.append([
        InlineKeyboardButton(text="◀ Назад", callback_data="admin_offers_menu")
    ])

    await callback.message.answer(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=action_buttons)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("approve_offer:"))
async def approve_offer_cb(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    offer_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        offer = (await session.execute(
            select(Offer).where(Offer.id == offer_id)
        )).scalar_one_or_none()
        if not offer:
            await callback.answer("Не найдено.", show_alert=True)
            return
        offer.status = "approved"
        offer.is_active = True
        await session.commit()

        if offer.creator_user_id:
            creator = await get_user_by_id(session, offer.creator_user_id)
            if creator:
                try:
                    await callback.bot.send_message(
                        creator.telegram_id,
                        f"✅ Ваш оффер «{offer.title}» одобрен и опубликован!"
                    )
                except Exception:
                    pass
    await callback.answer("✅ Оффер одобрен!", show_alert=True)


@router.callback_query(F.data.startswith("reject_offer:"))
async def reject_offer_cb(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    offer_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        offer = (await session.execute(
            select(Offer).where(Offer.id == offer_id)
        )).scalar_one_or_none()
        if not offer:
            await callback.answer("Не найдено.", show_alert=True)
            return
        offer.status = "rejected"
        offer.is_active = False
        await session.commit()

        if offer.creator_user_id:
            creator = await get_user_by_id(session, offer.creator_user_id)
            if creator:
                try:
                    await callback.bot.send_message(
                        creator.telegram_id,
                        f"❌ Ваш оффер «{offer.title}» отклонён."
                    )
                except Exception:
                    pass
    await callback.answer("❌ Оффер отклонён!", show_alert=True)


@router.callback_query(F.data.startswith("toggle_offer:"))
async def toggle_offer_cb(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    offer_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        offer = (await session.execute(
            select(Offer).where(Offer.id == offer_id)
        )).scalar_one_or_none()
        if not offer:
            await callback.answer("Не найдено.", show_alert=True)
            return
        offer.is_active = not offer.is_active
        await session.commit()
    status = "активирован ✅" if offer.is_active else "деактивирован 🔴"
    await callback.answer(f"Оффер {status}!", show_alert=True)


@router.callback_query(F.data.startswith("delete_offer:"))
async def delete_offer_cb(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    offer_id = int(callback.data.split(":")[1])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Да, удалить",
                callback_data=f"confirm_delete_offer:{offer_id}"
            ),
            InlineKeyboardButton(
                text="❌ Отмена",
                callback_data=f"admin_review_offer:{offer_id}"
            ),
        ]
    ])
    await callback.message.answer(
        f"⚠️ Удалить оффер #{offer_id}?\n"
        f"Это действие скроет оффер от пользователей.",
        reply_markup=kb
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_delete_offer:"))
async def confirm_delete_offer_cb(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    offer_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        offer = (await session.execute(
            select(Offer).where(Offer.id == offer_id)
        )).scalar_one_or_none()
        if not offer:
            await callback.answer("Не найдено.", show_alert=True)
            return
        offer.is_active = False
        offer.status = "deleted"
        await session.commit()
    await callback.answer(f"🗑 Оффер #{offer_id} удалён.", show_alert=True)


# =========================
# RENTALS MANAGEMENT
# =========================
@router.callback_query(F.data == "admin_rentals_menu")
async def admin_rentals_menu(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id):
        await callback.answer()
        return
    async with async_session() as session:
        active_count = 0
        recent_rentals = []  # Rentals disabled

    text = f"🔑 <b>Управление арендой</b>\n\nАктивных аренд: {active_count}\n\n"

    kb_buttons = []
    if recent_rentals:
        text += "<b>Последние аренды:</b>\n"
        for rental, user, offer in recent_rentals:
            expires = rental.expires_at.strftime('%d.%m') if rental.expires_at else "???"
            text += (
                f"• {get_display_name(user)} → {offer.title[:20]}\n"
                f"  {rental.renter_channel_title[:25]} | "
                f"до {expires} | {rental.status}\n"
            )
            if rental.status == "pending":
                kb_buttons.append([InlineKeyboardButton(
                    text=f"⏳ Рассмотреть: {rental.renter_channel_title[:25]}",
                    callback_data=f"admin_review_rental:{rental.id}"
                )])

    kb_buttons.extend([
        [InlineKeyboardButton(
            text="⏰ Завершить просроченные",
            callback_data="admin_expire_rentals"
        )],
        [InlineKeyboardButton(text="◀ Назад", callback_data="admin_offers_menu")],
    ])
