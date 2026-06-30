import re

file_path = 'app/admin_handlers.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Remove Privacy Mode warning
# The string is multi-line in the file.
warning_part1 = ' "⚠️ <b>ВАЖНО:</b> Если вы находитесь в группе, обязательно отвечайте (REPLY) на это сообщение числом, "'
warning_part2 = ' "иначе бот из-за Privacy Mode его не увидит!",'
# We find the range from part1 to part2
start_warn = content.find(warning_part1)
if start_warn != -1:
    end_warn = content.find(warning_part2, start_warn) + len(warning_part2)
    content = content[:start_warn] + content[end_warn:]

# 2. Fix admin_select_user and add show_user_profile
# We find the start of the function and replace it until the next handler.
start_marker = '@router.callback_query(F.data.startswith("admin_select_user:"))'
start_idx = content.find(start_marker)

if start_idx != -1:
    # Find the end of the function: look for the next handler starting with @router.
    # We skip the current handler and find the next @router.callback_query or @router.message
    next_marker_idx = -1
    
    # Look for @router.callback_query or @router.message that is NOT indented
    for i in range(start_idx + len(start_marker), len(content)):
        if content[i] == '\n' and (i+1 < len(content)) and content[i+1] == '@':
            # Check if it's a handler
            if content[i+1:].startswith('@router.callback_query') or content[i+1:].startswith('@router.message'):
                next_marker_idx = i
                break
    
    if next_marker_idx == -1:
        next_marker_idx = len(content)
        
    # The content to replace
    old_func_content = content[start_idx:next_marker_idx]
    
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
    # Fix double backslashes for the f-string in the replacement
    helper = helper.replace('\\n', '\n')
    
    handler = """
@router.callback_query(F.data.startswith("admin_select_user:"))
async def admin_select_user(callback: CallbackQuery):
    user_id = int(callback.data.split(":", 1)[1])
    await show_user_profile(callback, user_id)
    await callback.answer()
"""
    content = content[:start_idx] + helper + handler + content[next_marker_idx:]

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
