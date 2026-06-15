"""Add bot_settings table

Revision ID: add_bot_settings
Revises: final_schema_fix
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = 'add_bot_settings'
down_revision = 'final_migration'
branch_labels = None
depends_on = None

def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()
    
    if 'bot_settings' not in tables:
        op.create_table(
            'bot_settings',
            sa.Column('key', sa.String(length=50), nullable=False),
            sa.Column('value', sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint('key')
        )

def downgrade() -> None:
    op.drop_table('bot_settings')
