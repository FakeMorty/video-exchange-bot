# Video Exchange Bot 🎬

A professional Telegram bot built with **aiogram 3** for content exchange, social economy, and automated moderation.

## Features 🚀

- **Content Exchange**: Users upload photos/videos, which are then shown to other users.
- **Automated Moderation**: Integration with admin-defined trusted uploaders and manual review queues.
- **Social Economy**:
  - Virtual coins earned through uploads and activities.
  - **VIP Status**: Purchased via Telegram Stars, granting bonuses and discounts.
  - **Lootboxes**: Chance-based rewards for engagement.
  - **Promocodes**: User-created codes backed by Telegram Stars.
- **Engagement Tools**:
  - **Lottery**: Regular draws with a Telegram WebApp live viewer.
  - **Quests**: Daily tasks to earn extra rewards.
  - **Referral System**: Multi-tier rewards for bringing new users.
- **Smart Advertising**: Contextual offer delivery and subscription audit.

## Tech Stack 🛠

- **Framework**: [aiogram 3.x](https://github.com/aiogram/aiogram) (Asynchronous Telegram Bots)
- **Database**: [SQLAlchemy 2.0](https://www.sqlalchemy.org/) with [PostgreSQL](https://www.postgresql.org/) (AsyncPG)
- **Migrations**: [Alembic](https://alembic.sqlalchemy.org/)
- **Web**: [aiohttp](https://docs.aiohttp.org/) (Webhooks and WebApp backend)
- **Deployment**: Docker & Docker Compose

## Getting Started 💻

### Prerequisites
- Python 3.11+
- PostgreSQL
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/FakeMorty/video-exchange-bot.git
   cd video-exchange-bot
   ```
2. Create and configure `.env`:
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run migrations:
   ```bash
   alembic upgrade head
   ```
5. Start the bot:
   ```bash
   python -m app.main
   ```

## Project Structure 📁

- `app/handlers/`: Modular Telegram update handlers.
- `app/models/`: SQLAlchemy database models.
- `app/services/`: Core business logic and DB abstractions.
- `app/utils/`: Helper functions and internal tools.
- `alembic/`: Database migration history.

## Contributing 🤝
Contributions are welcome! Please open an issue or submit a pull request for any improvements.

## License 📄
This project is licensed under the MIT License.
