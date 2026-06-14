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
    except Exception:
        pass
    
    # Добавляем новые колонки в offers
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('offers')]
    
    if 'duration_days' not in columns:
        op.add_column('offers', sa.Column('duration_days', sa.Integer(), nullable=False, server_default='30'))
    if 'placement_cost' not in columns:
        op.add_column('offers', sa.Column('placement_cost', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0'))
    
    # Удаляем старые колонки аренды
    try:
        if 'is_rentable' in columns:
            op.drop_column('offers', 'is_rentable')
        if 'rent_cost_per_day' in columns:
            op.drop_column('offers', 'rent_cost_per_day')
        if 'max_simultaneous_rentals' in columns:
            op.drop_column('offers', 'max_simultaneous_rentals')
    except Exception:
        pass


def downgrade() -> None:
    pass
