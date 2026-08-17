"""Store the user-selected reason for hiding an author.

Revision ID: blocked_user_reason_001
Revises: arcade_runs_001
"""
from alembic import op
import sqlalchemy as sa


revision = "blocked_user_reason_001"
down_revision = "arcade_runs_001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "blocked_users",
        sa.Column("reason", sa.String(length=32), nullable=True),
    )


def downgrade():
    op.drop_column("blocked_users", "reason")
