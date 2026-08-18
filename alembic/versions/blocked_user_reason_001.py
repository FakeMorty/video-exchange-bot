"""Store the user-selected reason for hiding an author.

Revision ID: blocked_user_reason_001
Revises: arcade_runs_001
"""
from alembic import op
import sqlalchemy as sa


revision = "blocked_user_reason_001"
down_revision = "arcade_runs_001"
branch_labels = None
depends_on = None


def upgrade():
    """Support both historic databases and clean deployments.

    `blocked_users` originally came from runtime schema initialization rather
    than the Alembic chain. Existing installations only need the `reason`
    column; a clean database needs the whole table before that column can be
    referenced.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("blocked_users"):
        op.create_table(
            "blocked_users",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("blocked_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("reason", sa.String(length=32), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("user_id", "blocked_user_id", name="uq_user_blocked_user"),
        )
        op.create_index("ix_blocked_users_user_id", "blocked_users", ["user_id"])
        op.create_index("ix_blocked_users_blocked_user_id", "blocked_users", ["blocked_user_id"])
        return

    columns = {column["name"] for column in inspector.get_columns("blocked_users")}
    if "reason" not in columns:
        op.add_column("blocked_users", sa.Column("reason", sa.String(length=32), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("blocked_users"):
        columns = {column["name"] for column in inspector.get_columns("blocked_users")}
        if "reason" in columns:
            op.drop_column("blocked_users", "reason")
