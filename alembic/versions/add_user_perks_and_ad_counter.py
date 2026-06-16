"""add_user_perks_and_ad_counter

Revision ID: add_user_perks_and_ad_counter
Revises: final_schema_fix
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'add_user_perks_and_ad_counter'
down_revision = 'final_schema_fix'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    # 1. Создаём таблицу user_perks, если её нет
    if 'user_perks' not in tables:
        op.create_table(
            'user_perks',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
            sa.Column('perk_type', sa.String(50), nullable=False, index=True),
            sa.Column('active_until', sa.DateTime(), nullable=False),
            sa.Column('is_active', sa.Boolean(), default=True),
            sa.Column('purchased_at', sa.DateTime(), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_user_perks_user_id', 'user_perks', ['user_id'])
        op.create_index('ix_user_perks_perk_type', 'user_perks', ['perk_type'])
        print("✅ Created table: user_perks")
    else:
        print("ℹ️ Table user_perks already exists")

    # 2. Добавляем поле videos_watched_since_ad в user_ad_states
    if 'user_ad_states' in tables:
        columns = [col['name'] for col in inspector.get_columns('user_ad_states')]
        if 'videos_watched_since_ad' not in columns:
            op.add_column('user_ad_states', sa.Column('videos_watched_since_ad', sa.Integer(), server_default='0'))
            print("✅ Added column: user_ad_states.videos_watched_since_ad")
        else:
            print("ℹ️ Column videos_watched_since_ad already exists")

    # 3. Добавляем поля is_rentable, rent_cost_per_day, max_simultaneous_rentals в offers
    if 'offers' in tables:
        columns = [col['name'] for col in inspector.get_columns('offers')]
        for col_name, col_type, default in [
            ('is_rentable', sa.Boolean(), 'false'),
            ('rent_cost_per_day', sa.Numeric(10, 2), '0'),
            ('max_simultaneous_rentals', sa.Integer(), '1'),
        ]:
            if col_name not in columns:
                op.add_column('offers', sa.Column(col_name, col_type, server_default=default))
                print(f"✅ Added column: offers.{col_name}")
            else:
                print(f"ℹ️ Column offers.{col_name} already exists")

    print("✅ Migration complete!")


def downgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)

    if 'user_perks' in inspector.get_table_names():
        op.drop_table('user_perks')
        print("🗑 Dropped table: user_perks")

    if 'user_ad_states' in inspector.get_table_names():
        columns = [col['name'] for col in inspector.get_columns('user_ad_states')]
        if 'videos_watched_since_ad' in columns:
            op.drop_column('user_ad_states', 'videos_watched_since_ad')
            print("🗑 Dropped column: user_ad_states.videos_watched_since_ad")

    if 'offers' in inspector.get_table_names():
        columns = [col['name'] for col in inspector.get_columns('offers')]
        for col_name in ['is_rentable', 'rent_cost_per_day', 'max_simultaneous_rentals']:
            if col_name in columns:
                op.drop_column('offers', col_name)
                print(f"🗑 Dropped column: offers.{col_name}")

    print("✅ Downgrade complete!")
