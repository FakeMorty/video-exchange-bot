"""update_offer_model_v2 - add user offer fields without breaking rental fields

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
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if 'offers' in tables:
        columns = [c['name'] for c in inspector.get_columns('offers')]

        if 'duration_days' not in columns:
            op.add_column('offers', sa.Column('duration_days', sa.Integer(), nullable=False, server_default='30'))
        if 'placement_cost' not in columns:
            op.add_column('offers', sa.Column('placement_cost', sa.Numeric(precision=10, scale=2), nullable=False, server_default='0'))

        # Код приложения всё ещё использует эти поля. Не удаляем их из БД.
        rental_columns = [
            ('is_rentable', sa.Boolean(), 'false'),
            ('rent_cost_per_day', sa.Numeric(10, 2), '0'),
            ('max_simultaneous_rentals', sa.Integer(), '1'),
        ]
        for col_name, col_type, default in rental_columns:
            if col_name not in columns:
                op.add_column('offers', sa.Column(col_name, col_type, nullable=False, server_default=default))

    if 'offer_rentals' not in tables:
        op.create_table(
            'offer_rentals',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('offer_id', sa.Integer(), nullable=False),
            sa.Column('renter_user_id', sa.Integer(), nullable=False),
            sa.Column('renter_channel_title', sa.String(length=255), nullable=False),
            sa.Column('renter_channel_url', sa.Text(), nullable=False),
            sa.Column('rent_days', sa.Integer(), nullable=False),
            sa.Column('cost_paid', sa.Numeric(precision=10, scale=2), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('expires_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['offer_id'], ['offers.id']),
            sa.ForeignKeyConstraint(['renter_user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_offer_rentals_offer_id'), 'offer_rentals', ['offer_id'], unique=False)
        op.create_index(op.f('ix_offer_rentals_renter_user_id'), 'offer_rentals', ['renter_user_id'], unique=False)


def downgrade() -> None:
    pass
