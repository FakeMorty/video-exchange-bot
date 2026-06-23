"""add_events_table

Revision ID: add_events_001
Revises: 0c4bad721113
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa


revision = 'add_events_001'
down_revision = '0c4bad721113'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    # final_migration in this chain can already create events, so keep this
    # migration idempotent for both fresh and existing databases.
    if 'events' not in tables:
        op.create_table(
            'events',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('discount_percent', sa.Integer(), nullable=False),
            sa.Column('duration_days', sa.Integer(), nullable=False),
            sa.Column('applies_vip', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('applies_coins', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('applies_lootbox', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('applies_cases', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('start_date', sa.DateTime(), nullable=False),
            sa.Column('end_date', sa.DateTime(), nullable=False),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('created_by', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
            sa.PrimaryKeyConstraint('id')
        )

    inspector = sa.inspect(conn)
    indexes = {idx['name'] for idx in inspector.get_indexes('events')} if 'events' in inspector.get_table_names() else set()
    if 'ix_events_start_date' not in indexes:
        op.create_index(op.f('ix_events_start_date'), 'events', ['start_date'], unique=False)
    if 'ix_events_end_date' not in indexes:
        op.create_index(op.f('ix_events_end_date'), 'events', ['end_date'], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'events' in inspector.get_table_names():
        indexes = {idx['name'] for idx in inspector.get_indexes('events')}
        if 'ix_events_end_date' in indexes:
            op.drop_index(op.f('ix_events_end_date'), table_name='events')
        if 'ix_events_start_date' in indexes:
            op.drop_index(op.f('ix_events_start_date'), table_name='events')
        op.drop_table('events')
