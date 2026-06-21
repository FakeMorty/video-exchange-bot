<div align="center">

# 🎬 Video Exchange Bot

> **Профессиональный Telegram-бот для обмена контентом**  
> **Professional Telegram Bot for Content Exchange**

[![Python](https://img.shields.io/badge/Python-3.11+-8b5cf6?style=for-the-badge&logo=python&logoColor=white)]()
[![aiogram](https://img.shields.io/badge/aiogram-3.x-7c3aed?style=for-the-badge&logo=telegram&logoColor=white)]()
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-6d28d9?style=for-the-badge&logo=sqlite&logoColor=white)]()
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-5b21b6?style=for-the-badge&logo=postgresql&logoColor=white)]()
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
  <b>Мощный Telegram-бот на aiogram 3</b> для обмена видео и фото, с социальной экономикой,  
  автоматизированной модерацией, ИИ-ассистентом, лотереями, квестами и полной монетизацией через Telegram Stars.
</p>

<br/>

## 🌟 Возможности

<table>
<tr>
<td width="50%">

### 🎬 Обмен контентом
Пользователи загружают фото и видео — бот показывает их другим участникам в автоматической очереди.

### 🤖 ИИ-ассистент «Neo»
Работает на **DeepSeek V4 Flash** через OpenModel. Без цензуры, с историей диалога, анти-спамом и дневными лимитами.

### 💰 Социальная экономика
Виртуальные монеты, VIP-статус через Telegram Stars, **донатный магазин** с перками (цветной/золотой ник, бустеры XP, эксклюзивные реакции), промокоды и лутбоксы.

### 🎯 Лотереи и квесты
Регулярные розыгрыши с WebApp-трансляцией, ежедневные задания, напоминания о розыгрыше за 1 час.

</td>
<td width="50%">

### 🛡️ Автоматическая модерация
Доверенные загрузчики, очередь ручной проверки, жалобы на контент, массовое одобрение, полноценная **панель администратора**.

### 🔗 Реферальная система
Многоуровневые награды за приглашение новых пользователей. Полная интеграция с экономикой бота.

### 📢 Умная реклама
Контекстный показ предложений, аудит подписок, праздничные баннеры (Новый год, 8 Марта, 9 Мая и др.).

### ⚡ Telegram Stars
Полная поддержка: VIP, промокоды, платные предложения пользователей — всё через Telegram Stars.

</td>
</tr>
</table>

## 🛠 Технологический стек

<p align="center">
  <img src="https://img.shields.io/badge/aiogram_3.x-Async_Framework-8b5cf6?style=flat-square&logo=telegram" />
  <img src="https://img.shields.io/badge/SQLAlchemy_2.0-ORM_AsyncPG-7c3aed?style=flat-square&logo=sqlite" />
  <img src="https://img.shields.io/badge/PostgreSQL-16-6d28d9?style=flat-square&logo=postgresql" />
  <img src="https://img.shields.io/badge/Alembic-Migrations-5b21b6?style=flat-square" />
  <img src="https://img.shields.io/badge/aiohttp-Webhooks_&_WebApp-4c1d95?style=flat-square&logo=aiohttp" />
  <img src="https://img.shields.io/badge/Docker_&_Compose-Deployment-3b0764?style=flat-square&logo=docker" />
  <img src="https://img.shields.io/badge/DeepSeek_V4-AI_Neo-2e1065?style=flat-square" />
  <img src="https://img.shields.io/badge/Python_3.11+-Native_Async-1a0533?style=flat-square&logo=python" />
</p>

## 🚀 Быстрый старт

### Предварительные требования
- Python 3.11+
- PostgreSQL 14+
- Токен бота от [@BotFather](https://t.me/BotFather)

### Установка

```bash
# 1. Клонируйте репозиторий
git clone https://github.com/FakeMorty/video-exchange-bot.git
cd video-exchange-bot

# 2. Настройте окружение
cp .env.example .env
# Отредактируйте .env — укажите токен бота и данные БД

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

## 📁 Структура проекта

```
video-exchange-bot/
├── app/                    # Основной код бота
│   ├── handlers/          # Обработчики команд Telegram
│   ├── models/            # SQLAlchemy модели
│   ├── services/          # Бизнес-логика и работа с БД
│   ├── utils/             # Вспомогательные функции
│   ├── admin_handlers.py  # Панель администратора
│   ├── ai_assistant.py    # ИИ-ассистент Neo
│   └── main.py            # Точка входа
├── alembic/               # Миграции базы данных
├── banners/               # Праздничные баннеры
├── scripts/               # Вспомогательные скрипты
├── .env.example           # Пример конфигурации
├── Dockerfile             # Docker-образ
├── docker-compose.yml     # Docker Compose
└── requirements.txt       # Зависимости
```

## 🤝 Как помочь проекту

1. ⭐ **Поставьте звезду** — это motivates!
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
  <b>A powerful Telegram bot built with aiogram 3</b> for video & photo exchange, featuring social economy,  
  automated moderation, AI assistant, lotteries, quests, and full monetization via Telegram Stars.
</p>

<br/>

## 🌟 Features

<table>
<tr>
<td width="50%">

### 🎬 Content Exchange
Users upload photos/videos — the bot displays them to other participants in an automatic queue.

### 🤖 AI Assistant "Neo"
Powered by **DeepSeek V4 Flash** via OpenModel. Uncensored, with dialogue history, anti-spam, and daily limits.

### 💰 Social Economy
Virtual coins, VIP status via Telegram Stars, **donation shop** with perks (colored/golden nickname, XP boosters, exclusive reactions), promo codes, and lootboxes.

### 🎯 Lotteries & Quests
Regular draws with WebApp live viewer, daily tasks for bonus rewards, 1-hour draw reminders.

</td>
<td width="50%">

### 🛡️ Automated Moderation
Trusted uploaders, manual review queue, content reports, batch approval, full-featured **admin panel**.

### 🔗 Referral System
Multi-tier rewards for bringing new users. Fully integrated with the bot economy.

### 📢 Smart Advertising
Contextual offer delivery, subscription audit, holiday banners (New Year, Mar 8, May 9, etc.).

### ⚡ Telegram Stars
Full support: VIP, promo codes, paid user offers — all via Telegram Stars.

</td>
</tr>
</table>

## 🛠 Tech Stack

<p align="center">
  <img src="https://img.shields.io/badge/aiogram_3.x-Async_Framework-8b5cf6?style=flat-square&logo=telegram" />
  <img src="https://img.shields.io/badge/SQLAlchemy_2.0-ORM_AsyncPG-7c3aed?style=flat-square&logo=sqlite" />
  <img src="https://img.shields.io/badge/PostgreSQL-16-6d28d9?style=flat-square&logo=postgresql" />
  <img src="https://img.shields.io/badge/Alembic-Migrations-5b21b6?style=flat-square" />
  <img src="https://img.shields.io/badge/aiohttp-Webhooks_&_WebApp-4c1d95?style=flat-square&logo=aiohttp" />
  <img src="https://img.shields.io/badge/Docker_&_Compose-Deployment-3b0764?style=flat-square&logo=docker" />
  <img src="https://img.shields.io/badge/DeepSeek_V4-AI_Neo-2e1065?style=flat-square" />
  <img src="https://img.shields.io/badge/Python_3.11+-Native_Async-1a0533?style=flat-square&logo=python" />
</p>

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL 14+
- Bot token from [@BotFather](https://t.me/BotFather)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/FakeMorty/video-exchange-bot.git
cd video-exchange-bot

# 2. Configure environment
cp .env.example .env
# Edit .env with your bot token and DB credentials

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

## 📁 Project Structure

```
video-exchange-bot/
├── app/                    # Core bot code
│   ├── handlers/          # Telegram command handlers
│   ├── models/            # SQLAlchemy models
│   ├── services/          # Business logic & DB layer
│   ├── utils/             # Helper functions
│   ├── admin_handlers.py  # Admin panel
│   ├── ai_assistant.py    # Neo AI Assistant
│   └── main.py            # Entry point
├── alembic/               # Database migrations
├── banners/               # Holiday banners
├── scripts/               # Utility scripts
├── .env.example           # Sample config
├── Dockerfile             # Docker image
├── docker-compose.yml     # Docker Compose
└── requirements.txt       # Dependencies
```

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
