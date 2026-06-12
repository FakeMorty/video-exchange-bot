"""update_offer_model_v2 - remove rental system, add user offer fields

Revision ID: update_offer_v2
Revises: add_events_001
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa


revision = 'update_offer_v2'
down_revision = 'add_events_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Удаляем таблицу аренды (если существует)
    try:
        op.drop_table('offer_rentals')
    except:
        pass
    
    # Добавляем новые колонки в offers
    op.add_column('offers', sa.Column('duration_days', sa.Integer(), nullable=False, server_default='30'))
    op.add_column('offers', sa.Column('placement_cost', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0'))
    
    # Удаляем старые колонки аренды
    try:
        op.drop_column('offers', 'is_rentable')
        op.drop_column('offers', 'rent_cost_per_day')
        op.drop_column('offers', 'max_simultaneous_rentals')
    except:
        pass


def downgrade() -> None:
    pass
