async def lootbox_menu(callback: CallbackQuery):
    if not ENABLE_LOOTBOXES:
        await callback.message.answer("⛔ Лутбоксы временно отключены.")
        await callback.answer()
        return
    coin_price = to_decimal(LOOTBOX_COIN_PRICE)
    star_price = int(LOOTBOX_STAR_PRICE)
    await callback.message.answer(
        "🎁 <b>Лутбоксы</b>\n\n"
        f"Цена: <b>{coin_price:.0f}</b> монет или <b>{star_price}</b> Stars.\n"
        "Внутри — случайный выигрыш монет.\n"
        "Редкие крупные выигрыши возможны, но не гарантированы.",
        parse_mode="HTML",
        reply_markup=_lootbox_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("lootbox_buy:"))
async def lootbox_buy(callback: CallbackQuery):
    if not ENABLE_LOOTBOXES:
        await callback.answer("Лутбоксы отключены.", show_alert=True)
        return
    kind = callback.data.split(":", 1)[1]
    if kind == "coins":
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not user:
                await callback.answer()
                return
            reward, rarity_or_err = await open_lootbox_for_coins(session, user.id)
        if reward is None:
            await callback.answer(rarity_or_err, show_alert=True)
            return
        rarity = rarity_or_err
        icon = {"common": "⚪", "rare": "🔵", "epic": "🟣", "jackpot": "🟡"}.get(rarity, "🎁")
        await callback.message.answer(
            f"{icon} <b>Лутбокс открыт!</b>\n\n"
            f"Выигрыш: <b>+{reward:.2f}</b> монет",
            parse_mode="HTML",
            reply_markup=_lootbox_kb(),
        )
        await callback.answer()
        return

    if kind == "stars":
        star_price = int(LOOTBOX_STAR_PRICE)
        payload = f"lootbox_{callback.from_user.id}_{uuid.uuid4().hex[:8]}"
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not user:
                await callback.answer()
                return
            await ensure_payment_pending(
                session,
                user_id=user.id,
                payload=payload,
                stars_amount=star_price,
            )
            await session.commit()
        await callback.message.answer_invoice(
            title="Лутбокс",
            description=f"Открытие лутбокса за {star_price} Stars",
            payload=payload,
            currency="XTR",
            prices=[LabeledPrice(label="Лутбокс", amount=star_price)],
        )
        await callback.answer()
        return

    await callback.answer()


# =========================
# OFFERS
# =========================
@router.message(F.text == BTN_OFFERS)
async def btn_offers(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
