"""final_migration - Полная миграция схемы БД

Revision ID: final_migration
Revises: b861ad02334f
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa


revision = 'final_migration'
down_revision = 'b861ad02334f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # === ТАБЛИЦА EVENTS ===
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
    
    # === ОБНОВЛЕНИЕ ТАБЛИЦЫ OFFERS ===
    # Добавляем новые колонки
    op.add_column('offers', sa.Column('duration_days', sa.Integer(), nullable=False, server_default='30'))
    op.add_column('offers', sa.Column('placement_cost', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0'))
    
    # Удаляем колонки аренды (если существуют)
    try:
        op.drop_column('offers', 'is_rentable')
    except:
        pass
    try:
        op.drop_column('offers', 'rent_cost_per_day')
    except:
        pass
    try:
        op.drop_column('offers', 'max_simultaneous_rentals')
    except:
        pass
    
    # === УДАЛЕНИЕ ТАБЛИЦЫ OFFER_RENTALS ===
    try:
        op.drop_table('offer_rentals')
    except:
        pass


def downgrade() -> None:
    pass
