"""add_katya_chats

Revision ID: add_katya_chats
Revises: add_lottery_draw_reminder
Create Date: 2024-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "add_katya_chats"
down_revision = "add_lottery_draw_reminder"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "katya_chats",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(50), nullable=False, server_default="Болтовня"),
        sa.Column("message_count", sa.Integer(), server_default="0", nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_katya_chats_user_id", "katya_chats", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_katya_chats_user_id")
    op.drop_table("katya_chats")
