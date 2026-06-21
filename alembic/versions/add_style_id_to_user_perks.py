"""add style_id to user_perks

Revision ID: add_style_id_to_user_perks
Revises: add_user_perks_and_ad_counter
Create Date: 2026-06-20

"""
from alembic import op
import sqlalchemy as sa

revision = 'add_style_id_to_user_perks'
down_revision = 'add_user_perks_and_ad_counter'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'user_perks',
        sa.Column('style_id', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('user_perks', 'style_id')
