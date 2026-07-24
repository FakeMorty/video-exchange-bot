"""Add arcade_runs table for the Space Arcade mini-game.

Revision ID: arcade_runs_001
Revises: widen_balance_admin_id
"""
from alembic import op
import sqlalchemy as sa

revision = "arcade_runs_001"
down_revision = "widen_balance_admin_id"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "arcade_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("bet", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("wave", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("multiplier", sa.Numeric(8, 2), nullable=False, server_default="1"),
        # Скрытая crash-волна (серверная crash-модель, клиенту не отдаётся).
        sa.Column("crash_wave", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active", index=True),
        sa.Column("payout", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table("arcade_runs")
