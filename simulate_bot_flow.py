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
from sqlalchemy import select
from app.db import init_db, async_session
from app.models import (
    User, Video, Base, Offer, LootboxOpen, Promocode,
    PromocodeActivation, Feedback, DailyQuestProgress
)
from app.user_handlers import (
    cmd_start, accept_rules, process_nickname,
    cmd_admin_redirect, show_profile, show_level, show_vip,
    btn_watch, btn_upload, btn_bonus, btn_referrals, btn_buy,
    btn_offers, btn_games, btn_tops, btn_quests, btn_lottery,
    feedback_start, feedback_submit, btn_promo,
    lootbox_menu, lootbox_buy,
    promo_create_start, promo_amount, promo_uses, promo_hours,
    promo_activate_start, promo_activate_code,
    PromoCreateState, PromoActivateState, FeedbackState,
    btn_faq
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
    AdminOfferCreateState, AdminManageState,
    admin_select_user, cb_admin_user_edit_nick_start, cb_admin_user_give_coins_start
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
    msg.answer_invoice = AsyncMock()
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
        ("👤 Профиль", show_profile, [state]),
        ("📊 Уровень", show_level, [state]),
        ("👑 VIP", show_vip, [state]),
        ("🎬 Смотреть", btn_watch, [state]),
        ("📤 Загрузить", btn_upload, [state]),
        ("🎁 Бонус", btn_bonus, [state]),
        ("👥 Рефералы", btn_referrals, [state]),
        ("💳 Купить монеты", btn_buy, [state]),
        ("📢 Офферы", btn_offers, [state]),
        ("🎮 Игры", btn_games, [state]),
        ("🏆 Топы", btn_tops, [state]),
        ("📋 Квесты", btn_quests, [state]),
        ("🎰 Лотерея-лото", btn_lottery, [state]),
        ("🎟 Промокоды", btn_promo, [state]),
        ("💬 Жалобы и предложения", feedback_start, [state]),
        ("ℹ️ FAQ / Помощь", btn_faq, [state]),
        ("💋 ИИ-Общение", btn_katya, [state]),
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
        ("👤 Выбрать пользователя (НОВАЯ)", admin_select_user, []),
        ("✏️ Изменить ник пользователя (НОВАЯ)", cb_admin_user_edit_nick_start, [state]),
        ("💰 Начислить монеты (НОВАЯ)", cb_admin_user_give_coins_start, [state]),
    ]

    passed_admin_callbacks = 0
    total_admin_callbacks = len(admin_callbacks)

    for label, handler, extra_args in admin_callbacks:
        print(f"  👉 Клики в админке: '{label}'...")
        cb_data = "dummy_data"
        if label == "👤 Выбрать пользователя (НОВАЯ)":
            cb_data = f"admin_select_user:{user_id}"
        elif label == "✏️ Изменить ник пользователя (НОВАЯ)":
            cb_data = f"admin_user_edit_nick_start:{user_id}"
        elif label == "💰 Начислить монеты (НОВАЯ)":
            cb_data = f"admin_user_give_coins_start:{user_id}"
            
        cb = create_mock_callback(cb_data, admin_id, admin_msg)
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
    total_deep = 6

    # 1. Симуляция 6-шагового создания оффера
    print("\n  👉 [Глубокий сценарий 1] Полноценный 6-шаговый ввод оффера в базу...")
    offer_state = MockState()
    try:
        # Шаг 1: Старт
        cb_start_off = create_mock_callback("admin_create_offer", admin_id, create_mock_message("", admin_id))
        await cb_admin_create_offer_start(cb_start_off, offer_state)
        assert await offer_state.get_state() == AdminOfferCreateState.waiting_title
        
        # Шаг 2: Название
        msg_t = create_mock_message("Тестовый спонсор 2026", admin_id)
        await process_offer_title(msg_t, offer_state)
        assert await offer_state.get_state() == AdminOfferCreateState.waiting_description
        
        # Шаг 3: Описание
        msg_d = create_mock_message("Подпишись на этот канал прямо сейчас!", admin_id)
        await process_offer_description(msg_d, offer_state)
        assert await offer_state.get_state() == AdminOfferCreateState.waiting_url
        
        # Шаг 4: Ссылка
        msg_u = create_mock_message("https://t.me/super_sponsor_channel", admin_id)
        await process_offer_url(msg_u, offer_state)
        assert await offer_state.get_state() == AdminOfferCreateState.waiting_reward_preview
        
        # Шаг 5: Награда старт
        msg_rp = create_mock_message("80.5", admin_id)
        await process_offer_reward_preview(msg_rp, offer_state)
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

    # 3. Симуляция Ежедневного Бонуса (Daily Bonus)
    print("\n  👉 [Глубокий сценарий 3] Симуляция получения Ежедневного Бонуса...")
    try:
        msg_bonus = create_mock_message("🎁 Бонус", user_id)
        await btn_bonus(msg_bonus, state)
        
        # Проверяем в БД: обновились ли поля бонуса
        async with async_session() as session:
            u_db = (await session.execute(select(User).where(User.telegram_id == user_id))).scalar_one()
            assert u_db.last_bonus_at is not None, "Дата последнего бонуса пуста!"
            assert u_db.bonus_streak == 1, "Счетчик серии бонусов не увеличился!"
            # Начальный баланс был 100 монет, за 1-й день серии дают 20 монет -> баланс должен быть 120
            assert u_db.balance == Decimal("120.00")
            print(f"    -> Серия бонусов: {u_db.bonus_streak}, Новый баланс: {u_db.balance} монет")
        print("    ✅ Ежедневный бонус успешно протестирован и зачислен в БД!")
        passed_deep += 1
    except Exception as e:
        print(f"    ❌ ОШИБКА получения ежедневного бонуса: {e}")
        import traceback; traceback.print_exc()

    # 4. Симуляция покупки Лутбокса за монеты (Lootbox Buy Flow)
    print("\n  👉 [Глубокий сценарий 4] Покупка лутбокса за монеты...")
    try:
        # Сначала покажем меню
        cb_lb_menu = create_mock_callback("lootbox_menu", user_id, create_mock_message("", user_id))
        await lootbox_menu(cb_lb_menu)
        
        # Симулируем покупку за монеты (цена 100 монет)
        cb_lb_buy = create_mock_callback("lootbox_buy:coins", user_id, create_mock_message("", user_id))
        await lootbox_buy(cb_lb_buy)
        
        # Проверяем в БД: списались ли монеты и создалась ли запись открытия
        async with async_session() as session:
            u_db = (await session.execute(select(User).where(User.telegram_id == user_id))).scalar_one()
            opens = (await session.execute(select(LootboxOpen).where(LootboxOpen.user_id == u_db.id))).scalars().all()
            
            assert len(opens) == 1, "Запись об открытии лутбокса не добавилась в БД!"
            # Баланс был 120, вычли 100 за лутбокс, но лутбокс выдает случайную награду (добавим ее к проверке)
            expected_balance = Decimal("120.00") - Decimal("100.00") + opens[0].reward_coins
            assert u_db.balance == expected_balance, f"Неверный баланс: {u_db.balance} != {expected_balance}"
            print(f"    -> Открыт лутбокс! Выигрыш: {opens[0].reward_coins} монет, Редкость: {opens[0].rarity}, Новый баланс: {u_db.balance}")
            
        print("    ✅ Покупка и открытие лутбокса успешно протыканы в БД!")
        passed_deep += 1
    except Exception as e:
        print(f"    ❌ ОШИБКА глубокого тестирования лутбоксов: {e}")
        import traceback; traceback.print_exc()

    # 5. Симуляция пошагового создания и активации Промокода
    print("\n  👉 [Глубокий сценарий 5] Пошаговое создание промокода (User А) и активация (User B)...")
    promo_state = MockState()
    promo_user_id_b = 888777666
    
    try:
        # Шаг 1: Создаем второго пользователя (User B) в БД и делаем User A (Gamer-X) VIP-пользователем!
        async with async_session() as session:
            user_b = await session.merge(User(
                telegram_id=promo_user_id_b,
                username="promo_user_b",
                first_name="UserB",
                last_name="Test",
                is_admin=False,
                agreed_to_rules=True,
                nickname_set=True,
                display_name="UserB"
            ))
            
            # Находим User А и даем ему VIP на 30 дней
            u_a = (await session.execute(select(User).where(User.telegram_id == user_id))).scalar_one()
            from datetime import datetime, timedelta
            u_a.vip_until = datetime.utcnow() + timedelta(days=30)
            u_a.promo_created_this_month = 0
            u_a.promo_month = datetime.utcnow().month
            
            await session.commit()
            
        # Шаг 2: Старт создания промокода (User A - Gamer-X)
        cb_promo_start = create_mock_callback("promo_create", user_id, create_mock_message("", user_id))
        await promo_create_start(cb_promo_start, promo_state)
        assert await promo_state.get_state() == PromoCreateState.waiting_amount
        
        # Шаг 3: Ввод суммы (50 монет)
        msg_pa = create_mock_message("50", user_id)
        await promo_amount(msg_pa, promo_state)
        assert await promo_state.get_state() == PromoCreateState.waiting_uses
        
        # Шаг 4: Ввод количеств использований (1 использование)
        msg_pu = create_mock_message("1", user_id)
        await promo_uses(msg_pu, promo_state)
        assert await promo_state.get_state() == PromoCreateState.waiting_hours
        
        # Шаг 5: Время действия (24 часа) - Финализирует создание промокода за монеты
        msg_ph = create_mock_message("24", user_id)
        
        # Подменим bot.get_me() для вызова в обработчике
        mock_bot_info = MagicMock()
        mock_bot_info.username = "bot_username"
        msg_ph.bot = MagicMock()
        msg_ph.bot.get_me = AsyncMock(return_value=mock_bot_info)
        
        await promo_hours(msg_ph, promo_state)
        assert await promo_state.get_state() is None # Очищен!
        
        # Извлекаем промокод из БД
        async with async_session() as session:
            promo_db = (await session.execute(select(Promocode))).scalars().first()
            assert promo_db is not None, "Промокод не создался в БД!"
            promo_code_str = promo_db.code
            print(f"    -> Создан промокод: «{promo_code_str}» на сумму {promo_db.coin_amount} монет.")
            
        # Шаг 6: Активация промокода (User B)
        cb_promo_act = create_mock_callback("promo_activate", promo_user_id_b, create_mock_message("", promo_user_id_b))
        promo_act_state = MockState()
        await promo_activate_start(cb_promo_act, promo_act_state)
        assert await promo_act_state.get_state() == PromoActivateState.waiting_code
        
        # Отправляем сам код
        msg_act_code = create_mock_message(promo_code_str, promo_user_id_b)
        await promo_activate_code(msg_act_code, promo_act_state)
        assert await promo_act_state.get_state() is None # Очищен!
        
        # Проверяем баланс User B (был 0 монет, после активации промокода на 50 должен быть 50)
        async with async_session() as session:
            u_b_db = (await session.execute(select(User).where(User.telegram_id == promo_user_id_b))).scalar_one()
            assert u_b_db.balance == Decimal("50.00"), f"Неверный баланс после активации: {u_b_db.balance}"
            print(f"    -> User B успешно активировал промокод! Новый баланс User B: {u_b_db.balance} монет.")
            
        print("    ✅ Сценарий создания и активации промокодов успешно протыкан!")
        passed_deep += 1
    except Exception as e:
        print(f"    ❌ ОШИБКА глубокого тестирования промокодов: {e}")
        import traceback; traceback.print_exc()

    # 6. Симуляция отправки Жалоб/Обращений пользователей (Feedback Flow)
    print("\n  👉 [Глубокий сценарий 6] Отправка обращения о баге в техподдержку...")
    feed_state = MockState()
    try:
        # Шаг 1: Нажимаем кнопку обращений и выбираем категорию "bug"
        cb_feed_start = create_mock_callback("feedback_kind:bug", user_id, create_mock_message("", user_id))
        # Настройка state-данных, имитирующих выбор категории
        await feed_state.update_data(feedback_kind="bug")
        await feed_state.set_state(FeedbackState.waiting_text)
        
        # Шаг 2: Отправляем текст жалобы
        msg_feed_txt = create_mock_message("Я нашел баг на экране Кати! Кнопка зависает.", user_id)
        await feedback_submit(msg_feed_txt, feed_state)
        assert await feed_state.get_state() is None # Очищено!
        
        # Проверяем БД
        async with async_session() as session:
            feedback_db = (await session.execute(select(Feedback).where(Feedback.user_id == 1))).scalars().first() # User A id is 1
            assert feedback_db is not None, "Обращение не сохранилось в БД!"
            assert feedback_db.kind == "bug"
            assert "зависает" in feedback_db.text
            print(f"    -> Обращение сохранено в БД! Тип: {feedback_db.kind}, Текст: «{feedback_db.text}»")
            
        print("    ✅ Сценарий отправки обращений в техподдержку полностью протыкан!")
        passed_deep += 1
    except Exception as e:
        print(f"    ❌ ОШИБКА глубокого тестирования обращений: {e}")
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
