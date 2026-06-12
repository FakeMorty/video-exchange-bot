"""add_events_table

Revision ID: add_events_001
Revises: b861ad02334f
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa


revision = 'add_events_001'
down_revision = 'b861ad02334f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('discount_percent', sa.Integer(), nullable=False),
        sa.Column('duration_days', sa.Integer(), nullable=False),
        sa.Column('applies_vip', sa.Boolean(), nullable=False, default=False),
        sa.Column('applies_coins', sa.Boolean(), nullable=False, default=False),
        sa.Column('applies_lootbox', sa.Boolean(), nullable=False, default=False),
        sa.Column('applies_cases', sa.Boolean(), nullable=False, default=False),
        sa.Column('start_date', sa.DateTime(), nullable=False),
        sa.Column('end_date', sa.DateTime(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_events_start_date'), 'events', ['start_date'], unique=False)
    op.create_index(op.f('ix_events_end_date'), 'events', ['end_date'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_events_end_date'), table_name='events')
    op.drop_index(op.f('ix_events_start_date'), table_name='events')
    op.drop_table('events')
