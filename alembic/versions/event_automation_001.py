"""add events.slug and events.poster_path for holiday auto-events

Revision ID: event_automation_001
Revises: vip_playlists_001
Create Date: 2026-10-19

Колонки для автоматических праздничных событий (каталог app/holidays.py):
- slug — стабильный ключ праздника (дедупликация создания, переводы);
- poster_path — имя файла постера в папке «постеры/» или banners/.

На проде дублируется self-heal'ом `ensure_model_columns()` (app/db.py),
который добавляет недостающие колонки моделей на каждом старте бота.
"""
from alembic import op
import sqlalchemy as sa

revision = "event_automation_001"
down_revision = "vip_playlists_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    try:
        op.add_column("events", sa.Column("slug", sa.String(length=64), nullable=True))
        print("✅ Added column: events.slug")
    except Exception as e:
        print(f"⚠️ Column events.slug may already exist: {e}")
    try:
        op.add_column("events", sa.Column("poster_path", sa.Text(), nullable=True))
        print("✅ Added column: events.poster_path")
    except Exception as e:
        print(f"⚠️ Column events.poster_path may already exist: {e}")


def downgrade() -> None:
    try:
        op.drop_column("events", "poster_path")
    except Exception:
        pass
    try:
        op.drop_column("events", "slug")
    except Exception:
        pass
