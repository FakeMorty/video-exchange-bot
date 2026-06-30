import re

with open('app/admin_handlers.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Remove Privacy Mode warning
warning_text = ' "⚠️ <b>ВАЖНО:</b> Если вы находитесь в группе, обязательно отвечайте (REPLY) на это сообщение числом, " "иначе бот из-за Privacy Mode его не увидит!,"'
# The text in the file is split across lines in the source
content = content.replace(
    ' "⚠️ <b>ВАЖНО:</b> Если вы находитесь в группе, обязательно отвечайте (REPLY) на это сообщение числом, "\n        "иначе бот из-за Privacy Mode его не увидит!",',
    ''
)

# 2. Add show_user_profile helper and update handlers
# We'll look for the start of admin_select_user and replace it.
# The original admin_select_user is:
# @router.callback_query(F.data.startswith("admin_select_user:"))
# async def admin_select_user(callback: CallbackQuery):
# ...

# First, let's implement the helper before the handler.
# Find the line where admin_select_user starts.
pattern = r'(@router\.callback_query\(F\.data\.startswith\("admin_select_user:"\)\)\nasync def admin_select_user\(callback: CallbackQuery\):.*?\n    await callback\.answer\(\))'
# This regex is tricky because of the multi-line nature.

# Let's try a simpler approach:
# 1. Replace the specific warning text.
# 2. Replace the admin_select_user handler.
# 3. Insert show_user_profile before it.

# We already did the warning removal. Now the handler.

# Search for the whole admin_select_user function
# Since I have the file content, I can just use a specific enough marker.

# I will define the helper and the new handler.
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

# Find the start of the old admin_select_user and the end (before the next handler)
# The old function starts with @router.callback_query(F.data.startswith("admin_select_user:"))
# and ends with await callback.answer()

# Since we are in Python, we can use a safer replacement.
# I'll use a marker for the replacement.

# a simple way to find the function:
# look for @router.callback_query(F.data.startswith("admin_select_user:"))
# then find the next @router.callback_query or @router.message

import re

# Find the whole admin_select_user function
# It starts at @router.callback_query(F.data.startswith("admin_select_user:"))
# and ends before the next @router.callback_query or @router.message or @router.callback_query
# and is followed by another handler.

start_marker = '@router.callback_query(F.data.startswith("admin_select_user:"))'
end_marker_regex = r'\n\n@router\.callback_query'

# This is getting complex. I will just use the provided la-file content.
