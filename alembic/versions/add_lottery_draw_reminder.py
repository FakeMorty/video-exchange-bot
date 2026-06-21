"""add lottery draw_reminder_sent column

Revision ID: add_lottery_draw_reminder
Revises: add_video_reports_mod_notifications
Create Date: 2026-06-21
"""
from alembic import op
import sqlalchemy as sa

revision = "add_lottery_draw_reminder"
down_revision = "add_video_reports_mod_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add draw_reminder_sent to lottery_rounds
    try:
        op.add_column(
            "lottery_rounds",
            sa.Column("draw_reminder_sent", sa.Boolean(), server_default="0", nullable=False),
        )
        print("✅ Added column: lottery_rounds.draw_reminder_sent")
    except Exception as e:
        print(f"⚠️ Column lottery_rounds.draw_reminder_sent may already exist: {e}")


def downgrade() -> None:
    try:
        op.drop_column("lottery_rounds", "draw_reminder_sent")
    except Exception:
        pass
