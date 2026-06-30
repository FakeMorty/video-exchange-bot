import re

file_path = 'app/admin_handlers.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Remove Privacy Mode warning
# We use a regex to handle the multi-line string
pattern_warning = r' "⚠️ <b>ВАЖНО:</b> Если вы находитесь в группе, обязательно отвечайте \(REPLY\) на это сообщение числом, "\n        "иначе бот из-за Privacy Mode его не увидит!",'
content = re.sub(pattern_warning, '', content)

# 2. Update admin_select_user and introduce show_user_profile
# We find the function admin_select_user and replace it.
# Since it's a large block, we'll search for the start and end.

start_marker = '@router.callback_query(F.data.startswith("admin_select_user:"))'
end_marker = 'await callback.answer()' # The last line of that function

# This is still a bit risky. Let's find the function by its signature.
# I'll use a simpler approach: I'll search for the function's start and then find the next function's start.

# I'll just use a very specific replacement for the function.
# I'll use the content I saw in read_file.

old_func = """@router.callback_query(F.data.startswith("admin_select_user:"))
async def admin_select_user(callback: CallbackQuery):
    if not await check_admin(callback.from_user.id): return
    
    user_id = int(callback.data.split(":", 1)[1])
    async with async_session() as session:
        user = await get_user(session, user_id)
        if not user:
            await callback.answer("Пользователь не найден в базе.", show_alert=True)
            return
            
    from app.user_handlers import is_vip
    status_text = "🚫 Забанен" if user.status == "banned" else "✅ Активен"
    vip_text = "👑 Да" if is_vip(user) else "❌ Нет"
    
    text = (
        f"👤 <b>Управление пользователем:</b> {user.display_name or user.username or user_id}\\n\\n"
        f"• <b>Telegram ID:</b> <code>{user.telegram_id}</code>\\n"
        f"• <b>Никнейм в БД:</b> {user.username or 'отсутствует'}\\n"
        f"• <b>Баланс:</b> <b>{user.balance}</b> монет\\n"
        f"• <b>Серия бонусов:</b> {user.bonus_streak} дней\\n"
        f"• <b>Уровень/XP:</b> Lvl {user.level} ({user.xp} XP)\\n"
        f"• <b>Статус:</b> {status_text}\\n"
        f"• <b>VIP статус:</b> {vip_text}\\n"
    )
    
    ban_label = "✅ Разбанить" if user.status == "banned" else "🚫 Забанить"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Поменять ник", callback_data=f"admin_user_edit_nick_start:{user_id}"),
            InlineKeyboardButton(text="💰 Выдать монеты", callback_data=f"admin_user_give_coins_start:{user_id}"),
        ],
        [
            InlineKeyboardButton(text=ban_label, callback_data=f"admin_user_toggle_ban:{user_id}"),
            InlineKeyboardButton(text="✉️ Личное сообщение", callback_data=f"admin_user_send_msg_start:{user_id}"),
        ],
        [InlineKeyboardButton(text="🔎 Всеобъемлющее досье", callback_data=f"admin_user_dossier_detailed:{user_id}")],
        [InlineKeyboardButton(text="◀️ Назад к списку", callback_data="admin_manage_users:0")]
    ])
    
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()"""

# In reality, the file content has \n and not \\n.
# Let's just use a regex to replace the function.

# Find the start of the function
# @router.callback_query(F.data.startswith("admin_select_user:"))
# async def admin_select_user(callback: CallbackQuery):

# I'll use a more robust way: read the file, split into lines, and replace the range.
lines = content.splitlines()
start_line = -1
end_line = -1

for i, line in enumerate(lines):
    if '@router.callback_query(F.data.startswith("admin_select_user:"))' in line:
        start_line = i
        break

if start_line != -1:
    # Find the end of the function (the last line that's indented)
    for i in range(start_line + 1, len(lines)):
        if lines[i] and not lines[i].startswith(' ') and not lines[i].startswith('\t'):
            end_line = i - 1
            break
    if end_line == -1:
        end_line = len(lines) - 1
    
    # The replacement
    helper = """
async def show_user_profile(callback: CallbackQuery, user_id: int):
    if not await check_admin(callback.from_user.id): return
    
    async with async_session() as session:
        user = await get_user(session, user_id)
        if not user:
            await callback.answer("Пользователь не найден в базе.", show_alert=True)
            return
            
    from app.user_handlers import is_vip
    status_text = "🚫 Забанен" if user.status == "banned" else "✅ Активен"
    vip_text = "👑 Да" if is_vip(user) else "❌ Нет"
    
    text = (
        f"👤 <b>Управление пользователем:</b> {user.display_name or user.username or user_id}\\n\\n"
        f"• <b>Telegram ID:</b> <code>{user.telegram_id}</code>\\n"
        f"• <b>Никнейм в БД:</b> {user.username or 'отсутствует'}\\n"
        f"• <b>Баланс:</b> <b>{user.balance}</b> монет\\n"
        f"• <b>Серия бонусов:</b> {user.bonus_streak} дней\\n"
        f"• <b>Уровень/XP:</b> Lvl {user.level} ({user.xp} XP)\\n"
        f"• <b>Статус:</b> {status_text}\\n"
        f"• <b>VIP статус:</b> {vip_text}\\n"
    )
    
    ban_label = "✅ Разбанить" if user.status == "banned" else "🚫 Забанить"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Поменять ник", callback_data=f"admin_user_edit_nick_start:{user_id}"),
            InlineKeyboardButton(text="💰 Выдать монеты", callback_data=f"admin_user_give_coins_start:{user_id}"),
        ],
        [
            InlineKeyboardButton(text=ban_label, callback_data=f"admin_user_toggle_ban:{user_id}"),
            InlineKeyboardButton(text="✉️ Личное сообщение", callback_data=f"admin_user_send_msg_start:{user_id}"),
        ],
        [InlineKeyboardButton(text="🔎 Всеобъемлющее досье", callback_data=f"admin_user_dossier_detailed:{user_id}")],
        [InlineKeyboardButton(text="◀️ Назад к списку", callback_data="admin_manage_users:0")]
    ])
    
    await _safe_edit(callback, text, parse_mode="HTML", reply_markup=kb)
"""
    handler = """
@router.callback_query(F.data.startswith("admin_select_user:"))
async def admin_select_user(callback: CallbackQuery):
    user_id = int(callback.data.split(":", 1)[1])
    await show_user_profile(callback, user_id)
    await callback.answer()
"""
    # Replace the range
    lines[start_line:end_line+1] = helper.strip().splitlines() + [handler.strip()]
    content = "\\n".join(lines) # Wait, this is wrong. Use \n.

# Let's just do it correctly.
