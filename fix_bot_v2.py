import re

file_path = 'app/admin_handlers.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Remove Privacy Mode warning
# We use a regex to find the specific multiline string.
warning_pattern = r' "⚠️ <b>ВАЖНО:</b> Если вы находитесь в группе, обязательно отвечайте \(REPLY\) на это сообщение числом, "\n        "иначе бот из-за Privacy Mode его не увидит!",'
content = re.sub(warning_pattern, '', content)

# 2. Replace admin_select_user with helper + handler
# We search for the whole function block of admin_select_user.
# It starts with @router.callback_query(F.data.startswith("admin_select_user:"))
# and goes until the next function or handler.

start_marker = '@router.callback_query(F.data.startswith("admin_select_user:"))'
# Find start index
start_idx = content.find(start_marker)

if start_idx != -1:
    # Find the end of this function. It's the next @router or @router.message or a new top-level def.
    # We look for the next occurrence of @router.callback_query or @router.message or @router.message
    # starting from after the current function.
    
    # a more reliable way: find the last line of the function which is '    await callback.answer()'
    # but we must ensure it's the one for this function.
    
    # Let's search for the next handler marker
    next_markers = [
        '\n@router.callback_query', 
        '\n@router.message', 
        '\nasync def'
    ]
    
    # We want the first marker that appears after the start_marker.
    end_idx = len(content)
    for marker in next_markers:
        idx = content.find(marker, start_idx + len(start_marker))
        if idx != -1 and idx < end_idx:
            end_idx = idx

    old_func_content = content[start_idx:end_idx]
    
    helper_func = """
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
    # Remove the backslashes added for the python string
    helper_func = helper_func.replace('\\n', '\n')

    new_handler = """
@router.callback_query(F.data.startswith("admin_select_user:"))
async def admin_select_user(callback: CallbackQuery):
    user_id = int(callback.data.split(":", 1)[1])
    await show_user_profile(callback, user_id)
    await callback.answer()
"""
    content = content[:start_idx] + helper_func + new_handler + content[end_idx:]

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
