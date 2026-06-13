async def btn_upload(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            return
        if user.status == "banned":
            await message.answer("🚫 Вы заблокированы.")
            return
        if not await require_nickname(message, user):
            return
    await message.answer(
        "📤 Отправьте видео или фото.\n\n"
        "После проверки модератором вы получите монеты!"
    )


@router.message(F.video)
async def handle_video_upload(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user or user.status == "banned":
            return
        if not user.agreed_to_rules:
            await message.answer("Примите правила командой /start")
            return
        if not user.nickname_set:
            await require_nickname(message, user)
            return

        v = message.video
        saved, is_duplicate = await save_video(
            session, user.id,
            v.file_id, v.file_unique_id,
            v.duration, v.file_size
        )

        if is_duplicate:
            data = _upload_notifications[user.id]
            if "dup_count" not in data:
                data["dup_count"] = 0
            data["dup_count"] += 1
            if data["task"] is None or data["task"].done():
                data["task"] = asyncio.create_task(_send_upload_notification(message.bot, message.chat.id, user.id))
            return

        user.xp += 20
        await _level_up_check(session, user, message)
        await _update_quest_progress(session, user.id, "upload", 1)
        data = _upload_notifications[user.id]
        if "count" not in data:
            data["count"] = 0
        data["count"] += 1
        if data["task"] is None or data["task"].done():
            data["task"] = asyncio.create_task(_send_upload_notification(message.bot, message.chat.id, user.id))


@router.message(F.photo)
async def handle_photo_upload(message: Message):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user or user.status == "banned":
            return
        if not user.agreed_to_rules:
            await message.answer("Примите правила командой /start")
            return
        if not user.nickname_set:
            await require_nickname(message, user)
            return

        p = message.photo[-1]
        saved, is_duplicate = await save_photo(
            session, user.id,
            p.file_id, p.file_unique_id,
            p.file_size
        )

        if is_duplicate:
            data = _upload_notifications[user.id]
            # Initialize safely
            if "dup_count" not in data:
                data["dup_count"] = 0
            data["dup_count"] += 1
            if data["task"] is None or data["task"].done():
                data["task"] = asyncio.create_task(_send_upload_notification(message.bot, message.chat.id, user.id))
            return

        user.xp += XP_PER_UPLOAD
        await _level_up_check(session, user, message)
        await _update_quest_progress(session, user.id, "upload", 1)
        data = _upload_notifications[user.id]
        if "count" not in data:
            data["count"] = 0
        data["count"] += 1
        if data["task"] is None or data["task"].done():
            data["task"] = asyncio.create_task(_send_upload_notification(message.bot, message.chat.id, user.id))


# =========================
# BONUS
# =========================
@router.message(F.text == BTN_BONUS)
