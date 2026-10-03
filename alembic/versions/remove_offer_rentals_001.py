"""drop offer rentals: mechanic removed from the bot

Механика аренды рекламных слотов обычными пользователями удалена из кода:
модель `OfferRental` и поля `offers.is_rentable` / `offers.rent_cost_per_day` /
`offers.max_simultaneous_rentals` больше не существуют, поэтому схема приводится
в соответствие.

⚠️ Миграция удаляет ИСТОРИЧЕСКИЕ ДАННЫЕ таблицы `offer_rentals`.
Если на проде остались заявки в статусе `pending` (монеты списаны, слот ещё не
одобрен) — верните пользователям оплату до применения миграции.

Revision ID: remove_offer_rentals_001
Revises: add_admin_polls
Create Date: 2026-10-03

"""
from alembic import op
import sqlalchemy as sa


revision = "remove_offer_rentals_001"
down_revision = "add_admin_polls"
branch_labels = None
depends_on = None

_RENTAL_COLUMNS = ("is_rentable", "rent_cost_per_day", "max_simultaneous_rentals")
_RENTAL_INDEXES = ("ix_offer_rentals_offer_id", "ix_offer_rentals_renter_user_id")


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    inspector = _inspector()
    tables = inspector.get_table_names()

    if "offer_rentals" in tables:
        pending = op.get_bind().execute(
            sa.text("SELECT count(*) FROM offer_rentals WHERE status = 'pending'")
        ).scalar() or 0
        if pending:
            print(
                f"==> remove_offer_rentals_001: dropping offer_rentals with "
                f"{pending} pending request(s) — refunds must be handled manually."
            )
        existing_indexes = {index["name"] for index in inspector.get_indexes("offer_rentals")}
        for index_name in _RENTAL_INDEXES:
            if index_name in existing_indexes:
                op.drop_index(index_name, table_name="offer_rentals")
        op.drop_table("offer_rentals")

    if "offers" in tables:
        columns = {column["name"] for column in inspector.get_columns("offers")}
        for column_name in _RENTAL_COLUMNS:
            if column_name in columns:
                op.drop_column("offers", column_name)


def downgrade() -> None:
    """Восстанавливает структуру (данные аренд не восстанавливаются)."""
    inspector = _inspector()
    tables = inspector.get_table_names()

    if "offers" in tables:
        columns = {column["name"] for column in inspector.get_columns("offers")}
        if "is_rentable" not in columns:
            op.add_column(
                "offers",
                sa.Column("is_rentable", sa.Boolean(), nullable=False, server_default=sa.false()),
            )
        if "rent_cost_per_day" not in columns:
            op.add_column(
                "offers",
                sa.Column(
                    "rent_cost_per_day",
                    sa.Numeric(precision=10, scale=2),
                    nullable=False,
                    server_default="0",
                ),
            )
        if "max_simultaneous_rentals" not in columns:
            op.add_column(
                "offers",
                sa.Column(
                    "max_simultaneous_rentals",
                    sa.Integer(),
                    nullable=False,
                    server_default="1",
                ),
            )

    if "offer_rentals" not in inspector.get_table_names():
        op.create_table(
            "offer_rentals",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("offer_id", sa.Integer(), nullable=False),
            sa.Column("renter_user_id", sa.Integer(), nullable=False),
            sa.Column("renter_channel_title", sa.String(length=255), nullable=False),
            sa.Column("renter_channel_url", sa.Text(), nullable=False),
            sa.Column("rent_days", sa.Integer(), nullable=False),
            sa.Column("cost_paid", sa.Numeric(precision=10, scale=2), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("reviewed_by_telegram_id", sa.BigInteger(), nullable=True),
            sa.Column("rejection_reason", sa.Text(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["offer_id"], ["offers.id"]),
            sa.ForeignKeyConstraint(["renter_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_offer_rentals_offer_id"), "offer_rentals", ["offer_id"], unique=False
        )
        op.create_index(
            op.f("ix_offer_rentals_renter_user_id"),
            "offer_rentals",
            ["renter_user_id"],
            unique=False,
        )
