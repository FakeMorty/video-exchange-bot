"""add video_reports and mod_notifications tables

Revision ID: add_video_reports_mod_notifications
Revises: add_style_id_to_user_perks
Create Date: 2026-06-20

"""
from alembic import op
import sqlalchemy as sa

revision = 'add_video_reports_mod_notifications'
down_revision = 'add_style_id_to_user_perks'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'video_reports',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('video_id', sa.Integer(), sa.ForeignKey('videos.id'), nullable=False, index=True),
        sa.Column('reporter_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('reason', sa.String(50), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), server_default='pending'),
        sa.Column('reviewed_by', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        'mod_notifications',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('kind', sa.String(30), nullable=False),
        sa.Column('count', sa.Integer(), server_default='1'),
        sa.Column('is_sent', sa.Boolean(), server_default='false'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('mod_notifications')
    op.drop_table('video_reports')
