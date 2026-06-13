async def btn_buy(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if not await require_nickname(message, user):
            return

    # Динамический курс
    bonus_text = ""
    if DYNAMIC_STAR_DISCOUNT_ENABLED:
        try:
            start_h, end_h = map(int, DYNAMIC_STAR_DISCOUNT_HOURS.split("-"))
            now_h = datetime.utcnow().hour
            if start_h <= now_h < end_h:
                bonus_text = f"\n🔥 <b>Сейчас действует бонус +{int((DYNAMIC_STAR_DISCOUNT_MULTIPLIER - 1) * 100)}% монет!</b>"
            else:
                bonus_text = f"\n💡 Часы бонуса: {start_h}:00–{end_h}:00 UTC (+{int((DYNAMIC_STAR_DISCOUNT_MULTIPLIER - 1) * 100)}%)"
        except Exception:
            pass
    bonus_text += f"\n🎁 Первая покупка дня: +{FIRST_PURCHASE_DAILY_BONUS} монет бонусом."

    await message.answer(
        f"💳 <b>Пополнение баланса</b>{bonus_text}\n\nВыберите пакет:",
        parse_mode="HTML",
        reply_markup=buy_coins_keyboard()
    )


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy_pack(callback: CallbackQuery):
    pack_key = callback.data.split(":")[1]
    pack = STARS_PACKAGES.get(pack_key)
    if not pack:
        await callback.answer("Пакет не найден.", show_alert=True)
        return

    async with async_session() as session:
        user = await get_user(session, callback.from_user.id)
        if not user:
            await callback.answer()
            return
        payment = await create_payment(session, user.id, pack_key)

    await callback.message.answer_invoice(
        title=f"Покупка {pack['title']}",
        description=f"{pack['coins']} монет за {pack['stars']} Stars",
        payload=payment.payload,
        currency="XTR",
        prices=[LabeledPrice(label=pack['title'], amount=pack['stars'])]
    )
    await callback.answer()


@router.callback_query(F.data == "buy_custom")
async def cb_buy_custom(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CustomBuyState.waiting_stars)
    await callback.message.answer("💫 Введите количество Stars (мин. 1):")
    await callback.answer()


@router.message(CustomBuyState.waiting_stars)
async def process_custom_stars(message: Message, state: FSMContext):
    if not message.text or not message.text.isdigit():
        await message.answer("❌ Введите целое число.")
        return
    stars = int(message.text)
    if stars < 1:
        await message.answer("❌ Минимум 1 Star.")
        return

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await state.clear()
            return
        payment = await create_custom_payment(session, user.id, stars)
        coins = int(stars * STARS_TO_COINS_RATE)

    await message.answer_invoice(
        title=f"Покупка {coins} монет",
        description=f"{coins} монет за {stars} Stars",
        payload=payment.payload,
        currency="XTR",
        prices=[LabeledPrice(label=f"{coins} монет", amount=stars)]
    )
    await state.clear()


@router.pre_checkout_query()
