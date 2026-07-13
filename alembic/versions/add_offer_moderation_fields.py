"""add offer and rental moderation metadata

Revision ID: offer_moderation_001
Revises: add_katya_messages
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa


revision = "offer_moderation_001"
down_revision = "add_katya_messages"
branch_labels = None
depends_on = None


def _column_names(inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "offers" in tables:
        columns = _column_names(inspector, "offers")
        additions = (
            ("approved_at", sa.DateTime()),
            ("reviewed_at", sa.DateTime()),
            ("reviewed_by_telegram_id", sa.BigInteger()),
            ("rejection_reason", sa.Text()),
        )
        for name, column_type in additions:
            if name not in columns:
                op.add_column("offers", sa.Column(name, column_type, nullable=True))

        # Старые одобренные офферы начинают отсчёт от их исходной даты.
        op.execute(
            sa.text(
                "UPDATE offers SET approved_at = created_at "
                "WHERE status = 'approved' AND approved_at IS NULL"
            )
        )

    if "offer_rentals" in tables:
        columns = _column_names(inspector, "offer_rentals")
        additions = (
            ("reviewed_at", sa.DateTime()),
            ("reviewed_by_telegram_id", sa.BigInteger()),
            ("rejection_reason", sa.Text()),
        )
        for name, column_type in additions:
            if name not in columns:
                op.add_column("offer_rentals", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "offer_rentals" in tables:
        columns = _column_names(inspector, "offer_rentals")
        for name in ("rejection_reason", "reviewed_by_telegram_id", "reviewed_at"):
            if name in columns:
                op.drop_column("offer_rentals", name)

    if "offers" in tables:
        columns = _column_names(inspector, "offers")
        for name in ("rejection_reason", "reviewed_by_telegram_id", "reviewed_at", "approved_at"):
            if name in columns:
                op.drop_column("offers", name)
