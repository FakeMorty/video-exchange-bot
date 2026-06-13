async def successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    paid_stars = int(message.successful_payment.total_amount)

    if payload.startswith("vip_"):
        parts = payload.split("_")
        if len(parts) < 3 or not parts[1].isdigit() or int(parts[1]) != message.from_user.id:
            await message.answer("Ошибка платежа: некорректный payload.")
            return
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if user:
                payment = await get_payment_by_payload(session, payload)
                if not payment:
                    await ensure_payment_pending(
                        session,
                        user_id=user.id,
                        payload=payload,
                        stars_amount=paid_stars,
                    )
                    payment = await get_payment_by_payload(session, payload)
                if not payment or payment.user_id != user.id:
                    await session.rollback()
                    await message.answer("Ошибка платежа: пользователь не совпадает.")
                    return
                if int(payment.stars_amount) != paid_stars:
                    await session.rollback()
                    await message.answer("Ошибка платежа: сумма не совпадает.")
                    return
                if not await mark_payment_paid_once(session, payload):
                    await session.rollback()
                    await message.answer("✅ Платёж уже был обработан ранее.")
                    return
                now = datetime.utcnow()
                user.vip_until = (
                    user.vip_until + timedelta(days=VIP_DURATION_DAYS)
                    if user.vip_until and user.vip_until > now
                    else now + timedelta(days=VIP_DURATION_DAYS)
                )
                await log_user_action(
                    session, user.id,
                    "buy_vip",
                    f"payload={payload};until={user.vip_until}",
                    auto_commit=False,
                )
                await session.commit()
        await message.answer(
            f"👑 VIP активирован на {VIP_DURATION_DAYS} дней!"
        )
    elif payload.startswith("promo_"):
        # Инвойс на создание промокода (платный)
        parts = payload.split("_")
        if len(parts) >= 5:
            try:
                creator_tg_id = int(parts[1])
                amount = int(parts[2])
                uses = int(parts[3])
                hours = int(parts[4])
            except Exception:
                await message.answer("Ошибка платежа: некорректный payload.")
                return
            async with async_session() as session:
                user = await get_user(session, creator_tg_id)
                if not user or user.telegram_id != message.from_user.id:
                    await message.answer("Ошибка платежа: пользователь не найден.")
                    return
                payment = await get_payment_by_payload(session, payload)
                if not payment:
                    await ensure_payment_pending(
                        session,
                        user_id=user.id,
                        payload=payload,
                        stars_amount=paid_stars,
                    )
                    payment = await get_payment_by_payload(session, payload)
                if not payment or payment.user_id != user.id:
                    await session.rollback()
                    await message.answer("Ошибка платежа: пользователь не совпадает.")
                    return
                if int(payment.stars_amount) != paid_stars:
                    await session.rollback()
                    await message.answer("Ошибка платежа: сумма не совпадает.")
                    return
                if not await mark_payment_paid_once(session, payload):
                    await session.rollback()
                    await message.answer("✅ Платёж уже был обработан ранее.")
                    return
                promo, cost, error = await create_promocode(
                    session, creator_tg_id,
                    to_decimal(amount), uses, hours,
                    auto_commit=False,
                )
                if error:
                    await session.rollback()
                    await message.answer(f"❌ Ошибка создания промокода: {error}")
                else:
                    await session.commit()
                    bot = await message.bot.get_me()
                    await message.answer(
                        f"✅ Промокод создан:\n"
                        f"<code>{promo.code}</code>\n"
                        f"Сумма: {amount} монет, использований: {uses}/{promo.max_uses}\n"
                        f"Ссылка: t.me/{bot.username}?start=promo_{promo.code}",
                        parse_mode="HTML"
                    )
        else:
            await message.answer("Ошибка платежа.")
    elif payload.startswith("lootbox_"):
        parts = payload.split("_")
        if len(parts) < 3 or not parts[1].isdigit() or int(parts[1]) != message.from_user.id:
            await message.answer("Ошибка платежа: некорректный payload.")
            return
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                await message.answer("⚠️ Пользователь не найден.")
                return
            payment = await get_payment_by_payload(session, payload)
            if not payment:
                await ensure_payment_pending(
                    session,
                    user_id=user.id,
                    payload=payload,
                    stars_amount=paid_stars,
                )
                payment = await get_payment_by_payload(session, payload)
            if not payment or payment.user_id != user.id:
                await session.rollback()
                await message.answer("Ошибка платежа: пользователь не совпадает.")
                return
            if int(payment.stars_amount) != paid_stars:
                await session.rollback()
                await message.answer("Ошибка платежа: сумма не совпадает.")
                return
            reward, rarity_or_err = await open_lootbox_for_stars(
                session,
                telegram_user_id=message.from_user.id,
                payment_payload=payload,
            )
            # Keep Payment status aligned with idempotent lootbox processing.
            if await mark_payment_paid_once(session, payload):
                await session.commit()
        if reward is None:
            await message.answer(f"⚠️ {rarity_or_err}")
        else:
            rarity = rarity_or_err
            icon = {"common": "⚪", "rare": "🔵", "epic": "🟣", "jackpot": "🟡"}.get(rarity, "🎁")
            await message.answer(
                f"{icon} <b>Лутбокс открыт!</b>\n\n"
                f"Выигрыш: <b>+{reward:.2f}</b> монет",
                parse_mode="HTML",
            )
    else:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                await message.answer("⚠️ Пользователь не найден.")
                return
            payment_row = await get_payment_by_payload(session, payload)
            if not payment_row or payment_row.user_id != user.id:
                await message.answer("Ошибка платежа: не найден в системе.")
                return
            if int(payment_row.stars_amount) != paid_stars:
                await message.answer("Ошибка платежа: сумма не совпадает.")
                return
            payment = await apply_successful_payment(session, payload)
        if payment:
            await message.answer(
                f"✅ Оплата успешна!\n"
                f"💰 Начислено: <b>{payment.coins_amount}</b> монет",
                parse_mode="HTML"
            )
        else:
            await message.answer("✅ Оплата получена!")


def _lootbox_kb() -> InlineKeyboardMarkup:
    coin_price = to_decimal(LOOTBOX_COIN_PRICE)
    star_price = int(LOOTBOX_STAR_PRICE)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"🪙 Купить за {coin_price:.0f} монет",
            callback_data="lootbox_buy:coins"
        )],
        [InlineKeyboardButton(
            text=f"⭐ Купить за {star_price} Stars",
            callback_data="lootbox_buy:stars"
        )],
    ])


@router.callback_query(F.data == "lootbox_menu")
