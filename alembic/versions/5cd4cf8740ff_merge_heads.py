"""merge heads

Revision ID: 5cd4cf8740ff
Revises: add_donation_perks, final_schema_fix
Create Date: 2026-06-13 14:59:13.520324
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5cd4cf8740ff'
down_revision = ('add_donation_perks', 'final_schema_fix')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

