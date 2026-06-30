import re

file_path = 'app/admin_handlers.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Remove Privacy Mode warning
# We find the specific text and remove it.
warning_text = ' "⚠️ <b>ВАЖНО:</b> Если вы находитесь в группе, обязательно отвечайте (REPLY) на это сообщение числом, "\n        "иначе бот из-за Privacy Mode его не увидит!",'
content = content.replace(warning_text, '')

# 2. Replace admin_select_user with helper + handler
# We'll find the function and replace it.
# The function starts with @router.callback_query(F.data.startswith("admin_select_user:"))
# and ends with await callback.answer() before the next handler.

# I'll find the start and the end of the function.
start_pattern = '@router.callback_query(F.data.startswith("admin_select_user:"))'
start_idx = content.find(start_pattern)

if start_idx != -1:
    # Find the end of the function by looking for the next handler marker
    # @router.callback_query, @router.message, or @router.callback_query
    # We search for the first occurrence of @router. after the function start.
    
    # A simpler way: search for the next @router. handler.
    # The function admin_select_user is followed by @router.callback_query(F.data.startswith("admin_user_edit_nick_start:"))
    end_marker = '@router.callback_query(F.data.startswith("admin_user_edit_nick_start:"))'
    end_idx = content.find(end_marker, start_idx)
    
    if end_idx != -1:
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
    # Fix the \n in helper string since it's a raw string replacement
    helper = helper.replace('\\n', '\n')

    handler = """
@router.callback_query(F.data.startswith("admin_select_user:"))
async def admin_select_user(callback: CallbackQuery):
    user_id = int(callback.data.split(":", 1)[1])
    await show_user_profile(callback, user_id)
    await callback.answer()
"""
    content = content[:start_idx] + helper + handler + content[end_idx:]

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
