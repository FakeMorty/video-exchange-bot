"""Allow historical Telegram admin IDs in balance audit logs.

Revision ID: widen_balance_admin_id
Revises: offer_moderation_001
"""
from alembic import op
import sqlalchemy as sa

revision = "widen_balance_admin_id"
down_revision = "offer_moderation_001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("balance_logs") as batch_op:
        batch_op.alter_column(
            "admin_id",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=True,
        )


def downgrade():
    with op.batch_alter_table("balance_logs") as batch_op:
        batch_op.alter_column(
            "admin_id",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=True,
        )
