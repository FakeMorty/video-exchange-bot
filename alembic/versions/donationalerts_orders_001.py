"""Add DonationAlerts order matching and exception queue.

Revision ID: donationalerts_orders_001
Revises: blocked_user_reason_001
"""
from alembic import op
import sqlalchemy as sa


revision = "donationalerts_orders_001"
down_revision = "blocked_user_reason_001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "donationalerts_orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("order_code", sa.String(length=32), nullable=False),
        sa.Column("expected_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("reward_type", sa.String(length=20), nullable=False, server_default="coins"),
        sa.Column("coins_amount", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("donation_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("matched_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("order_code", name="uq_da_orders_code"),
        sa.UniqueConstraint("donation_id", name="uq_da_orders_donation_id"),
    )
    op.create_index("ix_da_orders_user_id", "donationalerts_orders", ["user_id"])
    op.create_index("ix_da_orders_status", "donationalerts_orders", ["status"])

    op.create_table(
        "donationalerts_exceptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("donation_id", sa.String(length=128), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="RUB"),
        sa.Column("donor_name", sa.String(length=255), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("reason", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("suggested_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by_telegram_id", sa.BigInteger(), nullable=True),
        sa.UniqueConstraint("donation_id", name="uq_da_exceptions_donation_id"),
    )
    op.create_index("ix_da_exceptions_status", "donationalerts_exceptions", ["status"])


def downgrade():
    op.drop_index("ix_da_exceptions_status", table_name="donationalerts_exceptions")
    op.drop_table("donationalerts_exceptions")
    op.drop_index("ix_da_orders_status", table_name="donationalerts_orders")
    op.drop_index("ix_da_orders_user_id", table_name="donationalerts_orders")
    op.drop_table("donationalerts_orders")
