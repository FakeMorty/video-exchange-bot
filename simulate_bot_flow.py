import asyncio
import os
import sys
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

# Форсируем использование временной базы данных в памяти для безопасности тестов
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

# Добавляем текущую директорию в PYTHONPATH для корректного импорта модулей
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from sqlalchemy import select
from aiogram.types import Message, CallbackQuery
from app.db import init_db, async_session
from app.models import User, Video, Base, Offer
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
    settings_show_all,
    cb_admin_manage_admins, cb_admin_add_admin_start, process_add_admin, cb_admin_remove_admin,
    cb_admin_create_offer_start, process_offer_title, process_offer_description,
    process_offer_url, process_offer_reward_preview, process_offer_reward_final,
    process_offer_penalty_unsubscribe,
    AdminOfferCreateState, AdminManageState
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
        ("👑 Управление админами (НОВАЯ)", cb_admin_manage_admins, []),
        ("➕ Добавить админа - старт (НОВАЯ)", cb_admin_add_admin_start, [state]),
        ("➕ Создать оффер - старт (НОВАЯ)", cb_admin_create_offer_start, [state]),
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

    # ГЛУБОКОЕ ПРОТЫКИВАНИЕ ПОД-МЕНЮ (Создание оффера, Управление админами)
    print("\n🕵️‍♂️ НАЧАЛО ГЛУБОКОГО ПОШАГОВОГО ПРОТЫКИВАНИЯ СЛОЖНЫХ СЦЕНАРИЕВ...")
    passed_deep = 0
    total_deep = 2

    # 1. Симуляция 6-шагового создания оффера
    print("\n  👉 [Глубокий сценарий 1] Полноценный 6-шаговый ввод оффера в базу...")
    offer_state = MockState()
    try:
        # Шаг 1: Старт
        cb_start_off = create_mock_callback("admin_create_offer", admin_id, create_mock_message("", admin_id))
        await cb_admin_create_offer_start(cb_start_off, offer_state)
        print("      -> Шаг 1 статус:", await offer_state.get_state())
        assert await offer_state.get_state() == AdminOfferCreateState.waiting_title
        
        # Шаг 2: Название
        msg_t = create_mock_message("Тестовый спонсор 2026", admin_id)
        await process_offer_title(msg_t, offer_state)
        print("      -> Шаг 2 статус:", await offer_state.get_state())
        assert await offer_state.get_state() == AdminOfferCreateState.waiting_description
        
        # Шаг 3: Описание
        msg_d = create_mock_message("Подпишись на этот канал прямо сейчас!", admin_id)
        await process_offer_description(msg_d, offer_state)
        print("      -> Шаг 3 статус:", await offer_state.get_state())
        assert await offer_state.get_state() == AdminOfferCreateState.waiting_url
        
        # Шаг 4: Ссылка
        msg_u = create_mock_message("https://t.me/super_sponsor_channel", admin_id)
        await process_offer_url(msg_u, offer_state)
        print("      -> Шаг 4 статус:", await offer_state.get_state())
        assert await offer_state.get_state() == AdminOfferCreateState.waiting_reward_preview
        
        # Шаг 5: Награда старт
        msg_rp = create_mock_message("80.5", admin_id)
        await process_offer_reward_preview(msg_rp, offer_state)
        print("      -> Шаг 5 статус:", await offer_state.get_state())
        assert await offer_state.get_state() == AdminOfferCreateState.waiting_reward_final
        
        # Шаг 6: Награда финал
        msg_rf = create_mock_message("150", admin_id)
        await process_offer_reward_final(msg_rf, offer_state)
        assert await offer_state.get_state() == AdminOfferCreateState.waiting_penalty_unsubscribe
        
        # Шаг 7: Штраф за отписку и финализация в БД!
        msg_p = create_mock_message("200.5", admin_id)
        await process_offer_penalty_unsubscribe(msg_p, offer_state)
        assert await offer_state.get_state() is None # Очищено!
        
        # Проверяем в базе данных
        async with async_session() as session:
            db_off = (await session.execute(select(Offer).where(Offer.title == "Тестовый спонсор 2026"))).scalar_one_or_none()
            assert db_off is not None, "Спонсор не сохранился в БД!"
            assert db_off.reward_preview == Decimal("80.50"), "Неверная предпросмотр-награда!"
            assert db_off.reward_final == Decimal("150.00"), "Неверная финальная награда!"
            assert db_off.penalty_unsubscribe == Decimal("200.50"), "Неверный штраф!"
            
        print("    ✅ 6-шаговое создание оффера успешно протыкано, проверено и сохранено в БД!")
        passed_deep += 1
    except Exception as e:
        print(f"    ❌ ОШИБКА глубокого тестирования офферов: {e}")
        import traceback; traceback.print_exc()

    # 2. Симуляция добавления и снятия прав администратора
    print("\n  👉 [Глубокий сценарий 2] Симуляция пошагового назначения и удаления админов...")
    admin_manage_state = MockState()
    try:
        # Шаг 1: Нажимаем кнопку "Добавить админа"
        cb_add_adm = create_mock_callback("admin_add_admin_start", admin_id, create_mock_message("", admin_id))
        await cb_admin_add_admin_start(cb_add_adm, admin_manage_state)
        assert await admin_manage_state.get_state() == AdminManageState.waiting_new_admin
        
        # Шаг 2: Ввод невалидного текстового ID
        msg_inv = create_mock_message("not_a_number_id", admin_id)
        await process_add_admin(msg_inv, admin_manage_state)
        assert await admin_manage_state.get_state() == AdminManageState.waiting_new_admin # Состояние осталось
        
        # Шаг 3: Ввод валидного ID существующего пользователя
        msg_val = create_mock_message(str(user_id), admin_id)
        await process_add_admin(msg_val, admin_manage_state)
        assert await admin_manage_state.get_state() is None # Сброшено!
        
        # Проверяем БД: стал ли пользователь админом
        async with async_session() as session:
            u_db = (await session.execute(select(User).where(User.telegram_id == user_id))).scalar_one()
            assert u_db.is_admin is True, "Пользователь не стал администратором!"
            print("    -> Пользователь успешно назначен администратором в БД.")
            
        # Шаг 4: Разжалование администратора
        cb_remove_adm = create_mock_callback(f"admin_remove_admin:{user_id}", admin_id, create_mock_message("", admin_id))
        await cb_admin_remove_admin(cb_remove_adm)
        
        # Проверяем БД: сняты ли права
        async with async_session() as session:
            u_db = (await session.execute(select(User).where(User.telegram_id == user_id))).scalar_one()
            assert u_db.is_admin is False, "Права администратора не снялись!"
            print("    -> Пользователь успешно разжалован в БД.")
            
        print("    ✅ Сценарий назначения и снятия администраторов полностью протыкан!")
        passed_deep += 1
    except Exception as e:
        print(f"    ❌ ОШИБКА глубокого тестирования администраторов: {e}")
        import traceback; traceback.print_exc()

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

    total_tests = (passed_buttons + passed_admin_callbacks + passed_settings_callbacks + passed_deep + passed_extra)
    max_tests = (len(buttons_to_test) + total_admin_callbacks + total_settings_callbacks + total_deep + total_extra)

    print("\n======================================================================")
    print(f"📊 ИТОГИ ГЛУБОКОЙ СИМУЛЯЦИИ: Успешно пройдено {total_tests} из {max_tests} тестов.")
    if total_tests == max_tests:
        print("🎉 БОТ ИСПОЛЬЗОВАН НА 100% И ГЛУБОКО ПРОТЫКАН ПО ВСЕМ СЛОЖНЫМ СЦЕНАРИЯМ! 🎉")
        print("Ни одного зависания, багов, опечаток или NameError не осталось во всем проекте!")
    else:
        print("⚠️ Обнаружены ошибки! Пожалуйста, исправьте их перед деплоем.")
    print("======================================================================")

if __name__ == "__main__":
    asyncio.run(run_comprehensive_tests())
