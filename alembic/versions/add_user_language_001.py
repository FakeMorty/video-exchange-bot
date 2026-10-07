"""Add users.language column (bot interface language, i18n)

Язык интерфейса бота, который пользователь выбирает кнопкой «🌐 Язык»
в главном меню (см. `app/i18n.py`). По умолчанию всем существующим
пользователям проставляется русский ("ru").

Revision ID: add_user_language_001
Revises: remove_offer_rentals_001
Create Date: 2026-10-07
"""
from alembic import op
import sqlalchemy as sa


revision = "add_user_language_001"
down_revision = "remove_offer_rentals_001"
branch_labels = None
depends_on = None


def _user_columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if "users" not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns("users")}


def upgrade() -> None:
    if "language" not in _user_columns():
        op.add_column(
            "users",
            sa.Column(
                "language",
                sa.String(length=8),
                nullable=False,
                server_default="ru",
            ),
        )


def downgrade() -> None:
    if "language" in _user_columns():
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_column("language")
