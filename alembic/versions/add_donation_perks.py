"""add_donation_perks

Revision ID: add_donation_perks
Revises: final_migration
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa


revision = 'add_donation_perks'
down_revision = 'final_migration'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'user_perks',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('perk_type', sa.String(length=50), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_user_perks_user_id', 'user_perks', ['user_id'])
    op.create_index('ix_user_perks_expires_at', 'user_perks', ['expires_at'])


def downgrade() -> None:
    op.drop_table('user_perks')
