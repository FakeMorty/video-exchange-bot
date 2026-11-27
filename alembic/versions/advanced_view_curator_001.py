"""Add private curator roles and advanced video categories.

Revision ID: advanced_view_curator_001
Revises: remove_donationalerts_001
Create Date: 2026-11-26
"""
from alembic import op
import sqlalchemy as sa

revision = "advanced_view_curator_001"
down_revision = "remove_donationalerts_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("curator_status", sa.String(length=20), server_default="none", nullable=False))
    op.add_column("users", sa.Column("advanced_view_enabled", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("users", sa.Column("advanced_video_categories", sa.String(length=64), server_default="", nullable=False))
    op.add_column("videos", sa.Column("viewing_category", sa.String(length=24), nullable=True))


def downgrade() -> None:
    op.drop_column("videos", "viewing_category")
    op.drop_column("users", "advanced_video_categories")
    op.drop_column("users", "advanced_view_enabled")
    op.drop_column("users", "curator_status")
