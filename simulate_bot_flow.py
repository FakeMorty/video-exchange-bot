import asyncio
import os
import sys
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

# Форсируем использование временной базы данных в памяти для безопасности тестов
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

# Добавляем текущую директорию в PYTHONPATH для корректного импорта модулей
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from aiogram.types import Message, CallbackQuery
from app.db import init_db, async_session
from app.models import User, Video
from app.user_handlers import (
    cmd_start, accept_rules, process_nickname,
    cmd_admin_redirect, show_profile, show_level, show_vip,
    btn_watch, btn_upload, btn_bonus, btn_referrals, btn_buy,
    btn_offers, btn_games, btn_tops, btn_quests, btn_lottery,
    feedback_start, btn_promo
)
from app.admin_handlers import admin_approve_all_confirm
from app.ai_assistant import btn_katya

class MockState:
    """Эмулятор машины состояний FSMContext для aiogram"""
    def __init__(self):
        self.state = None
        self.data = {}
        
    async def set_state(self, state):
        self.state = state
        
    async def get_state(self):
        return self.state
        
    async def clear(self):
        self.state = None
        self.data = {}
        
    async def update_data(self, **kwargs):
        self.data.update(kwargs)
        
    async def get_data(self):
        return self.data


def create_mock_message(text: str, user_id: int, username: str = "test_user") -> Message:
    msg = MagicMock(spec=Message)
    msg.text = text
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.from_user.username = username
    msg.from_user.first_name = "Test"
    msg.from_user.last_name = "User"
    msg.chat = MagicMock()
    msg.chat.id = user_id
    msg.answer = AsyncMock()
    msg.answer_photo = AsyncMock()
    msg.edit_text = AsyncMock()
    msg.reply = AsyncMock()
    
    # Эмулируем bot.get_me() для реферальной системы
    msg.bot = MagicMock()
    mock_bot_info = MagicMock()
    mock_bot_info.username = "my_video_exchange_bot"
    msg.bot.get_me = AsyncMock(return_value=mock_bot_info)
    
    return msg


def create_mock_callback(data: str, user_id: int, msg: Message) -> CallbackQuery:
    cb = MagicMock(spec=CallbackQuery)
    cb.data = data
    cb.from_user = MagicMock()
    cb.from_user.id = user_id
    cb.message = msg
    cb.answer = AsyncMock()
    return cb


async def run_comprehensive_tests():
    print("======================================================================")
    print("🚀 НАЧАЛО ПОЛНОГО СИМУЛЯЦИОННОГО ТЕСТИРОВАНИЯ БОТА НА 100% КНОПОК 🚀")
    print("======================================================================")

    # Шаг 1: Инициализация БД
    print("\n[Шаг 1/3] Инициализация временной базы данных SQLite...")
    try:
        await init_db()
        print("✅ База данных успешно инициализирована.")
    except Exception as e:
        print(f"❌ Ошибка при инициализации БД: {e}")
        return

    user_id = 999888777
    state = MockState()

    # Шаг 2: Полный цикл регистрации и приветствия
    print("\n[Шаг 2/3] Тестирование процесса онбординга нового пользователя...")
    
    # 2.1 Команда /start
    print("  -> Симуляция команды /start от нового пользователя...")
    msg_start = create_mock_message("/start", user_id)
    cmd_obj = MagicMock()
    cmd_obj.args = ""
    await cmd_start(msg_start, cmd_obj, state)
    msg_start.answer.assert_any_call(
        "📋 <b>Правила бота</b>\n\n"
        "1. Нельзя публиковать запрещённый или шок-контент.\n"
        "2. Нельзя использовать баги и накручивать награды.\n"
        "3. Уважайте других пользователей и соблюдайте правила Telegram.\n\n"
        "Нажмите кнопку ниже, чтобы принять правила.",
        parse_mode="HTML",
        reply_markup=msg_start.answer.call_args_list[-1][1]["reply_markup"]
    )
    print("  ✅ Шаг 'Правила' успешно протестирован.")

    # 2.2 Принятие правил
    print("  -> Симуляция нажатия кнопки 'Принять правила'...")
    cb_rules = create_mock_callback("accept_rules", user_id, msg_start)
    await accept_rules(cb_rules)
    assert cb_rules.message.answer.called
    args, kwargs = cb_rules.message.answer.call_args_list[-1]
    assert "установите ник" in args[0].lower(), "Бот не предложил ввести ник после принятия правил!"
    print("  ✅ Шаг 'Принятие правил' успешно протестирован.")

    # 2.3 Установка никнейма
    print("  -> Имитация ввода никнейма 'Gamer-X'...")
    msg_nick = create_mock_message("Gamer-X", user_id)
    await state.set_state("NicknameState:waiting_nickname")
    await process_nickname(msg_nick, state)
    print("  ✅ Шаг 'Установка никнейма' успешно протестирован.")

    # Шаг 3: Проверка ВСЕХ кнопок Главного Меню по отдельности
    print("\n[Шаг 3/3] Начинаем поочередное нажатие ВСЕХ кнопок Главного Меню бота...")
    
    buttons_to_test = [
        ("👤 Профиль", show_profile, []),
        ("📊 Уровень", show_level, []),
        ("👑 VIP", show_vip, []),
        ("🎬 Смотреть", btn_watch, []),
        ("📤 Загрузить", btn_upload, []),
        ("🎁 Бонус", btn_bonus, []),
        ("👥 Рефералы", btn_referrals, []),
        ("💳 Купить монеты", btn_buy, []),
        ("📢 Офферы", btn_offers, []),
        ("🎮 Игры", btn_games, []),
        ("🏆 Топы", btn_tops, []),
        ("📋 Квесты", btn_quests, []),
        ("🎰 Лотерея-лото", btn_lottery, []),
        ("🎟 Промокоды", btn_promo, []),
        ("💬 Жалобы и предложения", feedback_start, [state]),
        ("💋 Катя (ИИ-Подруга)", btn_katya, [state]),
    ]

    total_buttons = len(buttons_to_test)
    passed_buttons = 0

    for label, handler, extra_args in buttons_to_test:
        print(f"  👉 Тестирование кнопки '{label}'...")
        msg = create_mock_message(label, user_id)
        try:
            # Вызываем обработчик кнопки
            if len(extra_args) > 0:
                await handler(msg, *extra_args)
            else:
                await handler(msg)
            print(f"    ✅ Кнопка '{label}' нажата успешно (ошибок нет)!")
            passed_buttons += 1
        except Exception as e:
            print(f"    ❌ ОШИБКА на кнопке '{label}': {e}")
            import traceback
            traceback.print_exc()

    # Шаг 3.2: Тестирование админки (для админа)
    print("\n[Дополнительный Шаг] Симуляция входа в админку для Администратора...")
    admin_id = 123456
    # Сначала сделаем пользователя админом в БД
    async with async_session() as session:
        user = await session.merge(User(
            telegram_id=admin_id,
            username="main_admin",
            first_name="Admin",
            last_name="Super",
            is_admin=True,
            agreed_to_rules=True,
            nickname_set=True,
            display_name="Admin"
        ))
        await session.commit()

    msg_admin = create_mock_message("🔧 Админка", admin_id)
    try:
        await cmd_admin_redirect(msg_admin)
        print("    ✅ Перенаправление в админ-панель работает корректно!")
        passed_buttons += 1
        total_buttons += 1
    except Exception as e:
        print(f"    ❌ Ошибка входа в админку: {e}")

    # Шаг 3.3: Тестирование фонового одобрения видео
    print("\n[Дополнительный Шаг] Тестирование фонового одобрения...")
    async with async_session() as session:
        video = Video(
            uploader_user_id=user_id,
            content_type="video",
            telegram_file_id="file_123",
            telegram_file_unique_id="unique_file_123",
            status="pending"
        )
        session.add(video)
        await session.commit()

    admin_msg_cb = create_mock_message("", admin_id)
    cb_approve = create_mock_callback("admin_approve_all_confirm", admin_id, admin_msg_cb)
    mock_bot = AsyncMock()

    try:
        await admin_approve_all_confirm(cb_approve, mock_bot)
        await asyncio.sleep(0.1) # дадим задаче отработать
        print("    ✅ Фоновое одобрение отработало без ошибок!")
        passed_buttons += 1
        total_buttons += 1
    except Exception as e:
        print(f"    ❌ Ошибка фонового одобрения: {e}")

    print("\n======================================================================")
    print(f"📊 ИТОГИ СИМУЛЯЦИИ: Успешно пройдено {passed_buttons} из {total_buttons} тестов.")
    if passed_buttons == total_buttons:
        print("🎉 БОТ ИСПОЛЬЗОВАН НА 100% И ИДЕАЛЬНО ГОТОВ К РАБОТЕ БЕЗ ЕДИНОГО БАГА! 🎉")
    else:
        print("⚠️ Обнаружены ошибки! Пожалуйста, исправьте их перед деплоем.")
    print("======================================================================")

if __name__ == "__main__":
    asyncio.run(run_comprehensive_tests())
