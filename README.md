<div align="center">

# 🎬 Video Exchange Bot

> **Telegram-бот для обмена видео и фото с социальной экономикой**  
> **Telegram Bot for Video & Photo Exchange with Social Economy**

[![Python](https://img.shields.io/badge/Python-3.13-8b5cf6?style=for-the-badge&logo=python&logoColor=white)]()
[![aiogram](https://img.shields.io/badge/aiogram-3.x-7c3aed?style=for-the-badge&logo=telegram&logoColor=white)]()
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-6d28d9?style=for-the-badge&logo=sqlite&logoColor=white)]()
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-5b21b6?style=for-the-badge&logo=postgresql&logoColor=white)]()
[![Docker](https://img.shields.io/badge/Docker-ready-4c1d95?style=for-the-badge&logo=docker&logoColor=white)]()
[![License](https://img.shields.io/badge/License-MIT-3b0764?style=for-the-badge&logo=open-source-initiative&logoColor=white)]()

<br/>

[![GitHub stars](https://img.shields.io/github/stars/FakeMorty/video-exchange-bot?style=social&label=⭐%20Stars)]()
[![GitHub forks](https://img.shields.io/github/forks/FakeMorty/video-exchange-bot?style=social&label=🍴%20Forks)]()
[![GitHub commit activity](https://img.shields.io/github/commit-activity/m/FakeMorty/video-exchange-bot?style=social&label=🔥%20Commits)]()

---

<!-- Language Tabs -->
<details open>
<summary><b>🇷🇺 Русский</b></summary>
<br/>

<p align="center">
  <b>Telegram-бот на aiogram 3</b> для обмена видео и фото, с социальной экономикой,  
  модерацией, виртуальной подругой Катей, Секслото, лутбоксами и монетизацией через Telegram Stars.
</p>

<br/>

## 🌟 Возможности

<table>
<tr>
<td width="50%">

### 🎬 Обмен контентом
Пользователи загружают фото и видео — бот показывает их другим в автоматической очереди. Оценки, комментарии, реакции.

### 💋 Виртуальная подруга Катя
ИИ-компаньон на **DeepSeek V4 Flash** через OpenModel. Ролевой диалог с историей, анти-спамом, дневным лимитом. 5 монет за сообщение, админы — бесплатно.

### 💰 Социальная экономика
Виртуальные монеты, VIP через Telegram Stars, **донатный магазин** со 100 стилями никнейма (5 категорий), бустерами XP, эксклюзивными реакциями, промокодами и лутбоксами.

### 🎯 Секслото и Mini App
Регулярные розыгрыши с WebApp-трансляцией, live-интерфейсом, покупкой билетов внутри Mini App и напоминаниями о розыгрыше.

</td>
<td width="50%">

### 🛡️ Модерация и жалобы
Доверенные загрузчики, очередь ручной проверки, **жалобы на контент** (спам/шок/авторское право), массовое одобрение, агрегированные уведомления для админов, полная **панель администратора**.

### 🔗 Реферальная система
Прогрессивные награды за приглашение (монеты, лутбоксы, VIP). Полная интеграция с экономикой.

### 📢 Офферы и реклама
Умный показ предложений, аудит подписок, платные офферы от пользователей, праздничные баннеры (Новый год, 8 Марта, 9 Мая и др.).

### ⚡ Telegram Stars
Полная поддержка: VIP, промокоды, платные предложения пользователей, лутбоксы — всё через Telegram Stars.

</td>
</tr>
</table>

## 🛠 Технологический стек

<p align="center">
  <img src="https://img.shields.io/badge/aiogram_3.x-Async_Framework-8b5cf6?style=flat-square&logo=telegram" />
  <img src="https://img.shields.io/badge/SQLAlchemy_2.0-ORM_AsyncPG-7c3aed?style=flat-square&logo=sqlite" />
  <img src="https://img.shields.io/badge/PostgreSQL-15-6d28d9?style=flat-square&logo=postgresql" />
  <img src="https://img.shields.io/badge/Alembic-Migrations-5b21b6?style=flat-square" />
  <img src="https://img.shields.io/badge/aiohttp-Webhooks_&_WebApp-4c1d95?style=flat-square&logo=aiohttp" />
  <img src="https://img.shields.io/badge/Docker_&_Compose-Deployment-3b0764?style=flat-square&logo=docker" />
  <img src="https://img.shields.io/badge/DeepSeek_V4-Katya_AI-2e1065?style=flat-square" />
  <img src="https://img.shields.io/badge/Python_3.13-Native_Async-1a0533?style=flat-square&logo=python" />
</p>

## 🚀 Быстрый старт

### Предварительные требования
- Python 3.13+
- PostgreSQL 15+
- Токен бота от [@BotFather](https://t.me/BotFather)

### Установка

```bash
# 1. Клонируйте репозиторий
git clone https://github.com/FakeMorty/video-exchange-bot.git
cd video-exchange-bot

# 2. Настройте окружение
cp .env.example .env
# Отредактируйте .env — укажите токен бота, данные БД, API-ключ OpenModel

# 3. Установите зависимости
pip install -r requirements.txt

# 4. Запустите миграции
alembic upgrade head

# 5. Запустите бота
python -m app.main
```

### Запуск через Docker

```bash
docker compose up -d --build
```

### Где модерировать офферы

1. Откройте бота аккаунтом, чей Telegram ID указан в `ADMINS`.
2. Отправьте `/admin` или нажмите **🔧 Админка**.
3. Перейдите в **📢 Офферы и реклама**.
4. Используйте **⏳ Офферы на модерации** для пользовательских офферов и **🧾 Аренды на модерации** для рекламных слотов.

В карточке заявки доступны ссылка на проект, данные автора, одобрение и отказ с причиной. При отклонении аренды её стоимость автоматически возвращается пользователю.

## ⚙️ Переменные окружения

| Переменная | Обязательно | Описание |
|---|---|---|
| `BOT_TOKEN` | ✅ | Токен бота от BotFather |
| `DATABASE_URL` | ✅ | PostgreSQL async URL (`postgresql+asyncpg://...`) |
| `ADMINS` | ✅ | ID администраторов через запятую |
| `WEBHOOK_BASE` | ✅ | Публичный URL для вебхуков |
| `WEBHOOK_PATH` | ❌ | Путь вебхука (по умолчанию `/webhook`) |
| `PROVIDER_TOKEN` | ✅ | Токен провайдера Telegram Stars |
| `BOT_USERNAME` | ❌ | Username бота (без @) |
| `LOG_CHAT_ID` | ❌ | ID чата для логов |
| `AI_ASSISTANT_API_KEY` | ❌ | API-ключ OpenModel (для Кати) |
| `AI_ASSISTANT_BASE_URL` | ❌ | URL API (по умолч. `https://api.openmodel.ai`) |
| `AI_ASSISTANT_MODEL` | ❌ | Модель (по умолч. `deepseek-v4-flash`) |
| `AI_ASSISTANT_PRICE` | ❌ | Цена сообщения в монетах (по умолч. `5`) |
| `ENABLE_AI_ASSISTANT` | ❌ | Включить Катю (по умолч. `true`) |

Полный список переменных — в `app/config.py`.

## 📁 Структура проекта

```
video-exchange-bot/
├── app/                        # Основной код бота
│   ├── main.py                # Точка входа: диспетчер, вебхуки, фоновые таски
│   ├── config.py              # Конфигурация из .env
│   ├── models.py              # SQLAlchemy модели (User, Video, Lottery, Report…)
│   ├── db.py                  # Async engine, сессии, init_db
│   ├── services.py            # Бизнес-логика и запросы к БД
│   ├── user_handlers.py       # Обработчики пользователя (смотреть, загрузить, профиль…)
│   ├── admin_handlers.py      # Панель администратора (модерация, статистика, жалобы…)
│   ├── user_offer_handlers.py # Офферы пользователей
│   ├── donation_shop.py       # Донатный магазин (стили ника, перки, лутбоксы)
│   ├── ai_assistant.py        # Виртуальная подруга Катя (DeepSeek V4 Flash)
│   ├── nick_styles.py         # 100 стилей никнейма в 5 категориях
│   ├── sticker_prompts.py     # Промпты для стикерпака Кати (28 стикеров)
│   ├── keyboards.py           # Клавиатуры (inline и reply)
│   ├── middlewares.py         # Middleware бота
│   ├── logger.py              # Логирование
│   ├── selfcheck.py           # Самопроверка бота
│   ├── make_project_pdf.py    # Генерация PDF-документации
│   └── utils/                 # Утилиты
│       ├── admin.py           # Проверка прав админа
│       ├── db_fix.py          # Исправления БД
│       └── messaging.py       # Помощники отправки сообщений
├── alembic/                   # Миграции базы данных
│   └── versions/              # 12 миграций (от чистовой схемы до последней)
├── banners/                   # Праздничные баннеры (НГ, 8 Марта, 9 Мая…)
├── scripts/                   # Скрипты обслуживания
│   ├── backup_db.py           # Бэкап БД
│   ├── release_smoke_check.py # Проверка перед релизом
│   └── selfcheck_cli.py       # CLI самопроверки
├── .env.example               # Пример конфигурации
├── Dockerfile                 # Docker-образ (Python 3.13-slim)
├── docker-compose.yml         # Docker Compose (bot + PostgreSQL 15)
└── requirements.txt           # Зависимости
```

## 🎨 100 стилей никнейма

Стили разбиты на 5 категорий по 20 штук:

| Категория | Эмодзи | Примеры |
|---|---|---|
| Элегантные | 🔮 | Алмаз `◈ Nick ◈`, Корона `♛ Nick ♛`, Призма `⟡ Nick ⟡` |
| Древние | ⚔️ | Руна `ᚱ Nick ᚱ`, Сагитта `➴ Nick ➴`, Клинок `⟝ Nick ⟞` |
| Нежные | 🌸 | Роза `❀ Nick ❀`, Лепесток `✿ Nick ✿`, Жемчуг `◯ Nick ◯` |
| Строгие | 💎 | Секция `§ Nick §`, Параграф `¶ Nick ¶`, Юстиция `⚖ Nick ⚖` |
| Космические | ✦ | Звезда `★ Nick ★`, Сверхновая `✴ Nick ✴`, Туманность `≋ Nick ≋` |

Стиль привязан к перку `custom_nick` в донатном магазине. Сменить стиль — купить заново.

## 💋 Катя — виртуальная подруга

Катя — 18-летняя гимнастка, заканчивает 11 класс. Устала от ЕГЭ и рада отвлечься. Работает на DeepSeek V4 Flash через OpenModel API.

- **Стоимость**: 5 монет за сообщение (с возвратом при ошибке API)
- **Анти-спам**: кулдаун 5 сек, дневной лимит 50 сообщений
- **История**: 10 пар сообщений в контексте
- **Админы**: общаются бесплатно
- **Безопасность**: автоматическая фильтрация утечек API-ключей

## 🤝 Как помочь проекту

1. ⭐ **Поставьте звезду** — это мотивирует!
2. 🐛 **Сообщайте о багах** в [Issues](https://github.com/FakeMorty/video-exchange-bot/issues)
3. 🔀 **Делайте пул-реквесты** с улучшениями
4. 💬 **Предлагайте идеи** — мы открыты к обсуждению

## 📄 Лицензия

Проект распространяется под лицензией **MIT**.

---

</details>

<details>
<summary><b>🇬🇧 English</b></summary>
<br/>

<p align="center">
  <b>A Telegram bot built with aiogram 3</b> for video & photo exchange, featuring social economy,  
  moderation, virtual girlfriend Katya, Sexlotto, lootboxes, and monetization via Telegram Stars.
</p>

<br/>

## 🌟 Features

<table>
<tr>
<td width="50%">

### 🎬 Content Exchange
Users upload photos/videos — the bot displays them to others in an automatic queue. Ratings, comments, reactions.

### 💋 Virtual Girlfriend Katya
AI companion powered by **DeepSeek V4 Flash** via OpenModel. Roleplay dialogue with history, anti-spam, and daily limits. 5 coins per message, admins chat free.

### 💰 Social Economy
Virtual coins, VIP via Telegram Stars, **donation shop** with 100 nickname styles (5 categories), XP boosters, exclusive reactions, promo codes, and lootboxes.

### 🎯 Sexlotto & Mini App
Regular draws with a WebApp live viewer, in-app ticket purchases, and 1-hour draw reminders.

</td>
<td width="50%">

### 🛡️ Moderation & Reports
Trusted uploaders, manual review queue, **content reports** (spam/shock/copyright), batch approval, aggregated admin notifications, full-featured **admin panel**.

### 🔗 Referral System
Progressive rewards for bringing new users (coins, lootboxes, VIP). Fully integrated with the bot economy.

### 📢 Offers & Advertising
Smart offer delivery, subscription audit, paid user offers, holiday banners (New Year, Mar 8, May 9, etc.).

### ⚡ Telegram Stars
Full support: VIP, promo codes, paid user offers, lootboxes — all via Telegram Stars.

</td>
</tr>
</table>

## 🛠 Tech Stack

<p align="center">
  <img src="https://img.shields.io/badge/aiogram_3.x-Async_Framework-8b5cf6?style=flat-square&logo=telegram" />
  <img src="https://img.shields.io/badge/SQLAlchemy_2.0-ORM_AsyncPG-7c3aed?style=flat-square&logo=sqlite" />
  <img src="https://img.shields.io/badge/PostgreSQL-15-6d28d9?style=flat-square&logo=postgresql" />
  <img src="https://img.shields.io/badge/Alembic-Migrations-5b21b6?style=flat-square" />
  <img src="https://img.shields.io/badge/aiohttp-Webhooks_&_WebApp-4c1d95?style=flat-square&logo=aiohttp" />
  <img src="https://img.shields.io/badge/Docker_&_Compose-Deployment-3b0764?style=flat-square&logo=docker" />
  <img src="https://img.shields.io/badge/DeepSeek_V4-Katya_AI-2e1065?style=flat-square" />
  <img src="https://img.shields.io/badge/Python_3.13-Native_Async-1a0533?style=flat-square&logo=python" />
</p>

## 🚀 Quick Start

### Prerequisites
- Python 3.13+
- PostgreSQL 15+
- Bot token from [@BotFather](https://t.me/BotFather)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/FakeMorty/video-exchange-bot.git
cd video-exchange-bot

# 2. Configure environment
cp .env.example .env
# Edit .env with your bot token, DB credentials, and OpenModel API key

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run migrations
alembic upgrade head

# 5. Start the bot
python -m app.main
```

### Launch with Docker

```bash
docker compose up -d --build
```

## ⚙️ Environment Variables

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | ✅ | Bot token from BotFather |
| `DATABASE_URL` | ✅ | PostgreSQL async URL (`postgresql+asyncpg://...`) |
| `ADMINS` | ✅ | Admin IDs, comma-separated |
| `WEBHOOK_BASE` | ✅ | Public URL for webhooks |
| `WEBHOOK_PATH` | ❌ | Webhook path (default `/webhook`) |
| `PROVIDER_TOKEN` | ✅ | Telegram Stars provider token |
| `BOT_USERNAME` | ❌ | Bot username (without @) |
| `LOG_CHAT_ID` | ❌ | Chat ID for logs |
| `AI_ASSISTANT_API_KEY` | ❌ | OpenModel API key (for Katya) |
| `AI_ASSISTANT_BASE_URL` | ❌ | API URL (default `https://api.openmodel.ai`) |
| `AI_ASSISTANT_MODEL` | ❌ | Model (default `deepseek-v4-flash`) |
| `AI_ASSISTANT_PRICE` | ❌ | Message price in coins (default `5`) |
| `ENABLE_AI_ASSISTANT` | ❌ | Enable Katya (default `true`) |

Full list of variables — in `app/config.py`.

## 📁 Project Structure

```
video-exchange-bot/
├── app/                        # Core bot code
│   ├── main.py                # Entry point: dispatcher, webhooks, background tasks
│   ├── config.py              # Configuration from .env
│   ├── models.py              # SQLAlchemy models (User, Video, Lottery, Report…)
│   ├── db.py                  # Async engine, sessions, init_db
│   ├── services.py            # Business logic & DB queries
│   ├── user_handlers.py       # User handlers (watch, upload, profile…)
│   ├── admin_handlers.py      # Admin panel (moderation, stats, reports…)
│   ├── user_offer_handlers.py # User offers
│   ├── donation_shop.py       # Donation shop (nick styles, perks, lootboxes)
│   ├── ai_assistant.py        # Virtual girlfriend Katya (DeepSeek V4 Flash)
│   ├── nick_styles.py         # 100 nickname styles in 5 categories
│   ├── sticker_prompts.py     # Katya sticker pack prompts (28 stickers)
│   ├── keyboards.py           # Keyboards (inline and reply)
│   ├── middlewares.py         # Bot middleware
│   ├── logger.py              # Logging
│   ├── selfcheck.py           # Bot self-check
│   ├── make_project_pdf.py    # PDF documentation generator
│   └── utils/                 # Utilities
│       ├── admin.py           # Admin permission checks
│       ├── db_fix.py          # DB fixes
│       └── messaging.py       # Message sending helpers
├── alembic/                   # Database migrations
│   └── versions/              # 12 migrations (from clean schema to latest)
├── banners/                   # Holiday banners (NY, Mar 8, May 9…)
├── scripts/                   # Maintenance scripts
│   ├── backup_db.py           # DB backup
│   ├── release_smoke_check.py # Pre-release smoke test
│   └── selfcheck_cli.py       # CLI self-check
├── .env.example               # Sample configuration
├── Dockerfile                 # Docker image (Python 3.13-slim)
├── docker-compose.yml         # Docker Compose (bot + PostgreSQL 15)
└── requirements.txt           # Dependencies
```

## 🎨 100 Nickname Styles

Styles are split into 5 categories, 20 each:

| Category | Emoji | Examples |
|---|---|---|
| Elegant | 🔮 | Diamond `◈ Nick ◈`, Crown `♛ Nick ♛`, Prism `⟡ Nick ⟡` |
| Ancient | ⚔️ | Rune `ᚱ Nick ᚱ`, Sagitta `➴ Nick ➴`, Blade `⟝ Nick ⟞` |
| Gentle | 🌸 | Rose `❀ Nick ❀`, Petal `✿ Nick ✿`, Pearl `◯ Nick ◯` |
| Strict | 💎 | Section `§ Nick §`, Paragraph `¶ Nick ¶`, Justice `⚖ Nick ⚖` |
| Cosmic | ✦ | Star `★ Nick ★`, Supernova `✴ Nick ✴`, Nebula `≋ Nick ≋` |

Style is tied to the `custom_nick` perk in the donation shop. To change style — purchase again.

## 💋 Katya — Virtual Girlfriend

Katya is an 18-year-old gymnast finishing 11th grade. Tired from exams and happy to chat. Powered by DeepSeek V4 Flash via OpenModel API.

- **Price**: 5 coins per message (refunded on API error)
- **Anti-spam**: 5-sec cooldown, 50 messages/day limit
- **History**: 10 message pairs in context
- **Admins**: chat for free
- **Security**: automatic API key leak filtering

## 🤝 Contributing

1. ⭐ **Star the repo** — it really helps!
2. 🐛 **Report bugs** via [Issues](https://github.com/FakeMorty/video-exchange-bot/issues)
3. 🔀 **Submit pull requests** with improvements
4. 💬 **Share your ideas** — we're open to discussion

## 📄 License

This project is licensed under the **MIT License**.

---

</details>

<br/>

<div align="center">

---

### ⚡ Статистика | Statistics

<br/>

[![GitHub repo size](https://img.shields.io/github/repo-size/FakeMorty/video-exchange-bot?style=flat-square&label=Размер%20репозитория%20%7C%20Repo%20Size&color=8b5cf6)]()
[![GitHub last commit](https://img.shields.io/github/last-commit/FakeMorty/video-exchange-bot?style=flat-square&label=Последний%20коммит%20%7C%20Last%20Commit&color=7c3aed)]()
[![GitHub language count](https://img.shields.io/github/languages/count/FakeMorty/video-exchange-bot?style=flat-square&label=Языки%20%7C%20Languages&color=6d28d9)]()
[![Python](https://img.shields.io/github/languages/top/FakeMorty/video-exchange-bot?style=flat-square&label=Python&color=5b21b6)]()

<br/>

---

<p>
  <sub>
    Сделано с ❤️ командой FakeMorty &nbsp;|&nbsp; 
    Made with ❤️ by FakeMorty team
  </sub>
</p>

<p>
  <a href="https://github.com/FakeMorty/video-exchange-bot">
    <img src="https://img.shields.io/badge/🔗_GitHub-video--exchange--bot-8b5cf6?style=for-the-badge" />
  </a>
</p>

</div>
