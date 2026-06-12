"""final_schema_fix - Приводит схему к финальному состоянию

Revision ID: final_schema_fix
Revises: update_offer_v2
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'final_schema_fix'
down_revision = 'update_offer_v2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()
    
    # 1. Создаём таблицу events, если её нет
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
        op.create_index('ix_events_start_date', 'events', ['start_date'])
        op.create_index('ix_events_end_date', 'events', ['end_date'])
    
    # 2. Обновляем таблицу offers
    columns = [c['name'] for c in inspector.get_columns('offers')]
    
    # Добавляем duration_days если нет
    if 'duration_days' not in columns:
        op.add_column('offers', sa.Column('duration_days', sa.Integer(), nullable=False, server_default='30'))
    
    # Добавляем placement_cost если нет
    if 'placement_cost' not in columns:
        op.add_column('offers', sa.Column('placement_cost', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0'))
    
    # Удаляем старые колонки аренды если они есть
    if 'is_rentable' in columns:
        op.drop_column('offers', 'is_rentable')
    if 'rent_cost_per_day' in columns:
        op.drop_column('offers', 'rent_cost_per_day')
    if 'max_simultaneous_rentals' in columns:
        op.drop_column('offers', 'max_simultaneous_rentals')
    
    # 3. Удаляем таблицу offer_rentals если существует
    if 'offer_rentals' in tables:
        op.drop_table('offer_rentals')


def downgrade() -> None:
    pass
