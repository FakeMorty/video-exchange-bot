"""add administrator polls and rewarded responses

Revision ID: add_admin_polls
Revises: donationalerts_orders_001
Create Date: 2026-08-20

"""
from alembic import op
import sqlalchemy as sa


revision = "add_admin_polls"
down_revision = "donationalerts_orders_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_polls",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("poll_type", sa.String(length=20), nullable=False),
        sa.Column("options_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("reward", sa.Numeric(10, 2), nullable=False, server_default="20.00"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "admin_poll_responses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("poll_id", sa.Integer(), sa.ForeignKey("admin_polls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("answer_options_json", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("rewarded_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("poll_id", "user_id", name="uq_admin_poll_response_user"),
    )
    op.create_index("ix_admin_poll_responses_poll_id", "admin_poll_responses", ["poll_id"])
    op.create_index("ix_admin_poll_responses_user_id", "admin_poll_responses", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_admin_poll_responses_user_id", table_name="admin_poll_responses")
    op.drop_index("ix_admin_poll_responses_poll_id", table_name="admin_poll_responses")
    op.drop_table("admin_poll_responses")
    op.drop_table("admin_polls")
