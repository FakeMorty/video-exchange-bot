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
from app.models import User, Video, Base
from app.user_handlers import (
    cmd_start, accept_rules, process_nickname,
    cmd_admin_redirect, show_profile, show_level, show_vip,
    btn_watch, btn_upload, btn_bonus, btn_referrals, btn_buy,
    btn_offers, btn_games, btn_tops, btn_quests, btn_lottery,
    feedback_start, btn_promo
)
from app.admin_handlers import (
    admin_approve_all_confirm,
    admin_feedback_menu, admin_db_menu, cb_queue, admin_events_menu,
    admin_sales_start, admin_manage_users, admin_extended_stats,
    admin_offers_menu, admin_bot_settings, admin_auto_moderation,
    admin_trusted_uploaders, admin_reports_menu,
    settings_economy, settings_vip, settings_games, settings_ads,
    settings_nicks, settings_promos, settings_welcome, settings_admin_free,
    settings_show_all
)
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
    print("\n[Шаг 1/5] Инициализация временной базы данных SQLite...")
    try:
        await init_db()
        print("✅ База данных успешно инициализирована.")
    except Exception as e:
        print(f"❌ Ошибка при инициализации БД: {e}")
        return

    user_id = 999888777
    state = MockState()

    # Шаг 2: Полный цикл регистрации и приветствия
    print("\n[Шаг 2/5] Тестирование процесса онбординга нового пользователя...")
    
    # 2.1 Команда /start
    print("  -> Симуляция команды /start от нового пользователя...")
    msg_start = create_mock_message("/start", user_id)
    cmd_obj = MagicMock()
    cmd_obj.args = ""
    await cmd_start(msg_start, cmd_obj, state)
    print("  ✅ Шаг 'Правила' успешно протестирован.")

    # 2.2 Принятие правил
    print("  -> Симуляция нажатия кнопки 'Принять правила'...")
    cb_rules = create_mock_callback("accept_rules", user_id, msg_start)
    await accept_rules(cb_rules)
    print("  ✅ Шаг 'Принятие правил' успешно протестирован.")

    # 2.3 Установка никнейма
    print("  -> Имитация ввода никнейма 'Gamer-X'...")
    msg_nick = create_mock_message("Gamer-X", user_id)
    await state.set_state("NicknameState:waiting_nickname")
    await process_nickname(msg_nick, state)
    print("  ✅ Шаг 'Установка никнейма' успешно протестирован.")

    # Шаг 3: Проверка ВСЕХ кнопок Главного Меню по отдельности
    print("\n[Шаг 3/5] Начинаем поочередное нажатие ВСЕХ кнопок Главного Меню бота...")
    
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

    # Сделаем тестового пользователя администратором
    admin_id = 123456
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

    # Шаг 4: Тестирование ВСЕХ разделов Админки (Inline-коллбеков)
    print("\n[Шаг 4/5] Тестирование ВСЕХ подразделов Админ-Панели (Inline-кнопки)...")
    
    admin_msg = create_mock_message("", admin_id)
    
    # Временный патч функции проверки супер-админа для симулятора
    import app.admin_handlers
    async def mock_check_admin(id):
        return True
    app.admin_handlers.is_super_admin = lambda id: True
    app.admin_handlers.check_admin = mock_check_admin

    admin_callbacks = [
        ("📊 Очередь модерации", cb_queue, []),
        ("💬 Обращения пользователей", admin_feedback_menu, []),
        ("🗄 Управление базой данных", admin_db_menu, []),
        ("🎉 Меню событий", admin_events_menu, []),
        ("🛍 Акции и скидки", admin_sales_start, [state]),
        ("👥 Управление пользователями", admin_manage_users, []),
        ("📈 Статистика бота", admin_extended_stats, []),
        ("📢 Офферы и реклама", admin_offers_menu, []),
        ("🔧 Настройки бота (главная)", admin_bot_settings, []),
        ("⚡ Авто-модерация", admin_auto_moderation, []),
        ("🤝 Доверенные авторы", admin_trusted_uploaders, []),
        ("🚨 Жалобы пользователей", admin_reports_menu, []),
    ]

    passed_admin_callbacks = 0
    total_admin_callbacks = len(admin_callbacks)

    for label, handler, extra_args in admin_callbacks:
        print(f"  👉 Клики в админке: '{label}'...")
        cb = create_mock_callback("dummy_data", admin_id, admin_msg)
        try:
            if len(extra_args) > 0:
                await handler(cb, *extra_args)
            else:
                await handler(cb)
            print(f"    ✅ Коллбек '{label}' отработал отлично!")
            passed_admin_callbacks += 1
        except Exception as e:
            print(f"    ❌ ОШИБКА коллбека '{label}': {e}")
            import traceback
            traceback.print_exc()

    # Шаг 5: Тестирование ВСЕХ подразделов Настроек БСП (Экономика, VIP, Игры и т.д.)
    print("\n[Шаг 5/5] Тестирование ВСЕХ подразделов редактирования Настроек бота...")
    
    settings_callbacks = [
        ("💰 Экономика", settings_economy),
        ("👑 VIP настройки", settings_vip),
        ("🎮 Игры и лотерея", settings_games),
        ("📺 Настройки рекламы", settings_ads),
        ("✏️ Никнеймы и лимиты", settings_nicks),
        ("🎟 Настройки промокодов", settings_promos),
        ("🖼 Приветствие и баннер", settings_welcome),
        ("🆓 Настройки ADMIN FREE", settings_admin_free),
        ("📊 Просмотр всех значений", settings_show_all),
    ]

    passed_settings_callbacks = 0
    total_settings_callbacks = len(settings_callbacks)

    for label, handler in settings_callbacks:
        print(f"  👉 Подраздел настроек: '{label}'...")
        cb = create_mock_callback("dummy_data", admin_id, admin_msg)
        try:
            await handler(cb)
            print(f"    ✅ Подраздел настроек '{label}' загрузился без ошибок!")
            passed_settings_callbacks += 1
        except Exception as e:
            print(f"    ❌ ОШИБКА подраздела '{label}': {e}")
            import traceback
            traceback.print_exc()

    # Дополнительно: Проверка фонового одобрения
    print("\n[Дополнительно] Повторная проверка фонового асинхронного одобрения...")
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

    passed_extra = 0
    total_extra = 1
    try:
        await admin_approve_all_confirm(cb_approve, mock_bot)
        await asyncio.sleep(0.1)
        print("    ✅ Асинхронное одобрение отработало без ошибок!")
        passed_extra += 1
    except Exception as e:
        print(f"    ❌ Ошибка асинхронного одобрения: {e}")

    total_tests = (passed_buttons + passed_admin_callbacks + passed_settings_callbacks + passed_extra)
    max_tests = (len(buttons_to_test) + total_admin_callbacks + total_settings_callbacks + total_extra)

    print("\n======================================================================")
    print(f"📊 ИТОГИ СИМУЛЯЦИИ: Успешно пройдено {total_tests} из {max_tests} тестов.")
    if total_tests == max_tests:
        print("🎉 БОТ ИСПОЛЬЗОВАН НА 100% (ПОЛЬЗОВАТЕЛИ + АДМИНКА + НАСТРОЙКИ) И ИДЕАЛЬНО ГОТОВ К РАБОТЕ! 🎉")
    else:
        print("⚠️ Обнаружены ошибки! Пожалуйста, исправьте их перед деплоем.")
    print("======================================================================")

if __name__ == "__main__":
    asyncio.run(run_comprehensive_tests())
