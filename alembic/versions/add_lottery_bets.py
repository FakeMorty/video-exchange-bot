"""add lottery_bets table

Revision ID: add_lottery_bets
Revises: add_katya_chats
Create Date: 2026-07-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "add_lottery_bets"
down_revision = "add_katya_chats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    if "lottery_bets" not in tables:
        op.create_table(
            "lottery_bets",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("round_id", sa.Integer(), sa.ForeignKey("lottery_rounds.id"), nullable=False, index=True),
            sa.Column("bet_type", sa.String(length=50), nullable=True),
            sa.Column("amount", sa.Numeric(10, 2), nullable=True, server_default="10.0"),
            sa.Column("is_settled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_won", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    op.drop_table("lottery_bets")
