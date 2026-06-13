async def btn_watch(message: Message):
    from app.services import is_admin_or_super
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if user.status == "banned":
            await message.answer("🚫 Вы заблокированы.")
            return
        if not await require_nickname(message, user):
            return
        admin_flag = is_admin_or_super(message.from_user.id, user)
    await message.answer("👀 Что смотреть?", reply_markup=watch_choice_keyboard(is_admin=admin_flag))


@router.callback_query(F.data == "watch_video_content")
async def watch_video_content(callback: CallbackQuery):
    # Stop Telegram "loading" ASAP
    await _safe_callback_answer(callback)
    try:
        async with async_session() as session:
            user = await get_user(session, callback.from_user.id)
            if not user:
                return

            cost = to_decimal(WATCH_COST)
            if is_vip(user):
                cost = round(cost * to_decimal(0.5), 2)

            if user.balance < cost:
                if await should_show_low_balance_hint(session, user):
                    await mark_low_balance_hint_shown(session, user.id)
                    await callback.message.answer(
                        f"💸 <b>Монеток маловато!</b>\n\n"
                        f"На счету: <b>{user.balance}</b> монет, "
                        f"а нужно <b>{cost}</b> для просмотра.\n\n"
                        f"💡 <i>Знаешь ли ты, что можно бесплатно заработать монеты, "
                        f"подписываясь на каналы в разделе «Офферы»? "
                        f"Это быстро и просто!</i>",
                        parse_mode="HTML",
                        reply_markup=low_balance_offer_keyboard()
                    )
                else:
                    await callback.message.answer(
                        f"❌ Недостаточно монет!\n"
                        f"Нужно: {cost}, у вас: {user.balance}\n"
                        f"Пополните баланс или заработайте через офферы"
                    )
                return

            # Умная реклама: 35% шанс принудительного оффера
            if should_inject_ad_in_video() and await can_show_offer_to_user(session, user.id):
                offer = await get_random_active_offer(session)
                if offer:
                    await mark_offer_shown(session, user.id, offer.id, forced=True)
                    await callback.message.answer(
                        f"📢 <b>Небольшая реклама</b>\n\n"
                        f"<b>{offer.title}</b>\n"
                        f"{offer.description}\n\n"
                        f"⏳ Посмотрите {SMART_AD_FORCED_WATCH_SECONDS} секунд, "
                        f"затем сможете продолжить просмотр видео.\n"
                        f"💰 За подписку получите <b>{offer.reward_preview} монет</b>!",
                        parse_mode="HTML",
                        reply_markup=forced_offer_keyboard(
                            offer.id,
                            offer.channel_url,
                            SMART_AD_FORCED_WATCH_SECONDS
                        )
                    )
                    async def send_continue_button(chat_id: int, o_id: int, bot):
                        await asyncio.sleep(SMART_AD_FORCED_WATCH_SECONDS)
                        try:
                            await bot.send_message(
                                chat_id,
                                "✅ Спасибо за просмотр! Теперь можно продолжить.",
                                reply_markup=forced_offer_done_keyboard(o_id)
                            )
                        except Exception:
                            pass

                    asyncio.create_task(
                        send_continue_button(
                            callback.message.chat.id,
                            offer.id,
                            callback.bot
                        )
                    )
                    return

            # Обычный показ видео (с безопасной отправкой и возвратом при ошибке)
            last_send_error: str | None = None
            for _ in range(3):
                video = await get_random_video_for_user(session, user.id)
                if not video:
                    break

                ok = await record_view_and_charge_with_cost(session, user.id, video.id, cost)
                if not ok:
                    await callback.message.answer("❌ Ошибка списания монет.")
                    return

                try:
                    await callback.message.answer_video(
                        video.telegram_file_id,
                        caption=(
                            f"🎬 Видео #{video.id}\n"
                            f"💰 Списано: {cost} монет"
                        ),
                        reply_markup=video_rating_keyboard(video.id)
                    )
                except Exception as e:
                    last_send_error = str(e)
                    await mark_content_broken(session, video.id, f"send_failed: {e}")
                    await refund_watch_and_unview(
                        session,
                        user.id,
                        video.id,
                        cost,
                        reason=f"send_failed: {e}",
                    )
                    continue

                user = await get_user(session, callback.from_user.id)
                await _level_up_check(session, user, callback)
                await _update_quest_progress(session, user.id, "watch", 1)
                return

            await callback.message.answer(
                "😔 Нет доступных видео.\n"
                "Загрузите своё видео, чтобы другие смотрели!"
                + (f"\n\n⚠️ Ошибка отправки: {last_send_error}" if last_send_error else "")
            )
    except Exception:
        logger.exception("watch_video_content failed")
        try:
            await callback.message.answer("⚠️ Ошибка при показе видео. Попробуйте ещё раз через пару секунд.")
        except Exception:
            pass


