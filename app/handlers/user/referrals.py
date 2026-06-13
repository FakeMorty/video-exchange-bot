async def btn_referrals(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if not await require_nickname(message, user):
            return
        refs = await count_referrals(session, user.id)

    bot_info = await message.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start={user.referral_code}"
    await message.answer(
        f"👥 <b>Рефералы</b>\n\n"
        f"Ваша ссылка:\n<code>{ref_link}</code>\n\n"
        f"Приглашено: <b>{refs}</b>\n"
        f"Заработано: <b>{user.referral_earnings}</b> монет\n\n"
        f"За каждого приглашённого:\n"
        f"• Вы получаете: +{REFERRAL_REWARD_INVITER} монет\n"
        f"• Новый пользователь: +{REFERRAL_REWARD_NEW_USER} монет",
        parse_mode="HTML"
    )


# =========================
# BUY COINS
# =========================
@router.message(F.text == BTN_BUY)
