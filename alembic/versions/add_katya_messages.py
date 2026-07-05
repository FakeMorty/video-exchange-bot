"""add katya_messages table and character column

Revision ID: add_katya_messages
Revises: add_lottery_bets
Create Date: 2026-07-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "add_katya_messages"
down_revision = "add_lottery_bets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    if "katya_messages" not in tables:
        op.create_table(
            "katya_messages",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("chat_id", sa.Integer(), sa.ForeignKey("katya_chats.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("role", sa.String(length=20), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    if "katya_chats" in tables:
        columns = [c["name"] for c in inspector.get_columns("katya_chats")]
        if "character" not in columns:
            op.add_column(
                "katya_chats",
                sa.Column("character", sa.String(length=20), nullable=False, server_default="katya"),
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    if "katya_chats" in tables:
        columns = [c["name"] for c in inspector.get_columns("katya_chats")]
        if "character" in columns:
            op.drop_column("katya_chats", "character")

    if "katya_messages" in tables:
        op.drop_table("katya_messages")
