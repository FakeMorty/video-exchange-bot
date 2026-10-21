"""Regional holidays — region-aware calendar per user.

Revision ID: regional_holidays_001
Revises: vip_playlists_001
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "regional_holidays_001"
down_revision = "vip_playlists_001"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = _tables()

    # users.region + tz + source + lock timestamps
    if "users" in tables:
        cols = _columns("users")
        if "region" not in cols:
            op.add_column("users", sa.Column("region", sa.String(length=8), nullable=True))
        if "region_tz" not in cols:
            op.add_column("users", sa.Column("region_tz", sa.String(length=64), nullable=True))
        if "region_source" not in cols:
            op.add_column("users", sa.Column("region_source", sa.String(length=20), nullable=True))
        if "region_locked_at" not in cols:
            op.add_column("users", sa.Column("region_locked_at", sa.DateTime(), nullable=True))
        if "region_changed_at" not in cols:
            op.add_column("users", sa.Column("region_changed_at", sa.DateTime(), nullable=True))

    # events.region
    if "events" in tables:
        cols = _columns("events")
        if "region" not in cols:
            op.add_column("events", sa.Column("region", sa.String(length=8), nullable=True))
        # ensure image_file_id already exists via prior migrations; if not, handled by ensure_model_columns
        # Add index on region for broadcast filtering
        try:
            op.create_index("ix_events_region", "events", ["region"])
        except Exception:
            pass

    # HolidayReward — idempotency (user_id, slug, year)
    if "holiday_rewards" not in tables:
        op.create_table(
            "holiday_rewards",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("holiday_slug", sa.String(length=64), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("claimed_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "holiday_slug", "year", name="uq_holiday_reward_user_slug_year"),
        )
        op.create_index("ix_holiday_rewards_user_id", "holiday_rewards", ["user_id"])
        op.create_index("ix_holiday_rewards_slug_year", "holiday_rewards", ["holiday_slug", "year"])


def downgrade() -> None:
    try:
        op.drop_index("ix_holiday_rewards_slug_year", table_name="holiday_rewards")
    except Exception:
        pass
    try:
        op.drop_index("ix_holiday_rewards_user_id", table_name="holiday_rewards")
    except Exception:
        pass
    try:
        op.drop_table("holiday_rewards")
    except Exception:
        pass
    # columns are kept on downgrade (safe)
