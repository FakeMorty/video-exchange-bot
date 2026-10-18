"""Add VIP-only personal playlists.

Revision ID: vip_playlists_001
Revises: schema_drift_2026_10_13
Create Date: 2026-10-18
"""
from alembic import op
import sqlalchemy as sa


revision = "vip_playlists_001"
down_revision = "schema_drift_2026_10_13"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    tables = _tables()
    if "user_playlists" not in tables:
        op.create_table(
            "user_playlists",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=50), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("user_id", "name", name="uq_user_playlist_user_name"),
        )

    if "user_playlist_items" not in tables:
        op.create_table(
            "user_playlist_items",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("playlist_id", sa.Integer(), nullable=False),
            sa.Column("video_id", sa.Integer(), nullable=False),
            sa.Column("added_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["playlist_id"], ["user_playlists.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("playlist_id", "video_id", name="uq_user_playlist_video"),
        )

    if "ix_user_playlists_user_created_at" not in _indexes("user_playlists"):
        op.create_index(
            "ix_user_playlists_user_created_at",
            "user_playlists",
            ["user_id", "created_at"],
        )
    if "ix_user_playlist_items_playlist_added" not in _indexes("user_playlist_items"):
        op.create_index(
            "ix_user_playlist_items_playlist_added",
            "user_playlist_items",
            ["playlist_id", "added_at"],
        )
    if "ix_user_playlist_items_video_id" not in _indexes("user_playlist_items"):
        op.create_index(
            "ix_user_playlist_items_video_id",
            "user_playlist_items",
            ["video_id"],
        )


def downgrade() -> None:
    tables = _tables()
    if "user_playlist_items" in tables:
        op.drop_table("user_playlist_items")
    if "user_playlists" in _tables():
        op.drop_table("user_playlists")
