"""Догоняем схему до моделей: дрейф, не покрытый ни одной миграцией

До этой ревизии `alembic upgrade head` на БД «из миграций» давал схему,
отличную от `Base.metadata` (аудит 2026-10-13, пункт B-13):

* таблицы `promo_messages` не было вовсе;
* в `users` не хватало `lootbox_pity_counter`, `promo_month`,
  `last_freebie_week`, `last_freebie_year`, `timezone`;
* в `events` — `image_file_id`;
* в `offers` — эскроу-бюджет пользовательских офферов
  (`budget_total`, `budget_spent`, `max_participants`, `budget_refunded_at`);
* в `arcade_runs` — частичный уникальный индекс «один активный забег на игрока».

Все шаги идемпотентны (проверяют наличие через inspector), поэтому миграция
безопасна и для БД, где колонки уже догнал `ensure_model_columns`.

Revision ID: schema_drift_2026_10_13
Revises: add_user_language_001
Create Date: 2026-10-13
"""
from alembic import op
import sqlalchemy as sa


revision = "schema_drift_2026_10_13"
down_revision = "add_user_language_001"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _tables() -> set[str]:
    return set(_inspector().get_table_names())


def _columns(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {c["name"] for c in _inspector().get_columns(table)}


def _indexes(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {i["name"] for i in _inspector().get_indexes(table)}


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    if table in _tables() and column.name not in _columns(table):
        op.add_column(table, column)


def upgrade() -> None:
    # 1. promo_messages
    if "promo_messages" not in _tables():
        op.create_table(
            "promo_messages",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("title", sa.String(length=100), nullable=True),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("kind", sa.String(length=20), nullable=True, server_default="custom"),
            sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    # 2. users
    _add_column_if_missing("users", sa.Column("lootbox_pity_counter", sa.Integer(), nullable=True, server_default="0"))
    _add_column_if_missing("users", sa.Column("promo_month", sa.Integer(), nullable=True, server_default="0"))
    _add_column_if_missing("users", sa.Column("last_freebie_week", sa.Integer(), nullable=True, server_default="0"))
    _add_column_if_missing("users", sa.Column("last_freebie_year", sa.Integer(), nullable=True, server_default="0"))
    _add_column_if_missing("users", sa.Column("timezone", sa.String(length=50), nullable=True))

    # 3. events
    _add_column_if_missing("events", sa.Column("image_file_id", sa.Text(), nullable=True))

    # 4. offers — эскроу-бюджет пользовательских офферов
    _add_column_if_missing("offers", sa.Column("budget_total", sa.Numeric(12, 2), nullable=True, server_default="0"))
    _add_column_if_missing("offers", sa.Column("budget_spent", sa.Numeric(12, 2), nullable=True, server_default="0"))
    _add_column_if_missing("offers", sa.Column("max_participants", sa.Integer(), nullable=True))
    _add_column_if_missing("offers", sa.Column("budget_refunded_at", sa.DateTime(), nullable=True))

    # 5. donationalerts_* — индексы из моделей, которых не создала миграция
    #    donationalerts_orders_001 (unique по order_code/donation_id там уже есть).
    for table, index_name, column, unique in (
        ("donationalerts_orders", "ix_donationalerts_orders_user_id", "user_id", False),
        ("donationalerts_orders", "ix_donationalerts_orders_order_code", "order_code", True),
        ("donationalerts_orders", "ix_donationalerts_orders_status", "status", False),
        ("donationalerts_exceptions", "ix_donationalerts_exceptions_donation_id", "donation_id", True),
        ("donationalerts_exceptions", "ix_donationalerts_exceptions_status", "status", False),
    ):
        if table in _tables() and column in _columns(table) and index_name not in _indexes(table):
            op.create_index(index_name, table, [column], unique=unique)

    # 6. arcade_runs — один активный забег на игрока
    if "arcade_runs" in _tables() and "uq_arcade_runs_active_user" not in _indexes("arcade_runs"):
        # На живой БД могли накопиться дубли активных забегов (гонка старта до
        # этого фикса) — иначе CREATE UNIQUE INDEX упадёт. Оставляем самый новый,
        # остальные помечаем expired (ставка по ним уже вернётся/учтена отдельно).
        op.execute(sa.text(
            "UPDATE arcade_runs SET status = 'expired' "
            "WHERE status = 'active' AND id NOT IN ("
            "  SELECT max_id FROM (SELECT MAX(id) AS max_id FROM arcade_runs "
            "  WHERE status = 'active' GROUP BY user_id) AS keep"
            ")"
        ))
        op.create_index(
            "uq_arcade_runs_active_user",
            "arcade_runs",
            ["user_id"],
            unique=True,
            postgresql_where=sa.text("status = 'active'"),
            sqlite_where=sa.text("status = 'active'"),
        )


def downgrade() -> None:
    if "arcade_runs" in _tables() and "uq_arcade_runs_active_user" in _indexes("arcade_runs"):
        op.drop_index("uq_arcade_runs_active_user", table_name="arcade_runs")
    for table, index_name in (
        ("donationalerts_orders", "ix_donationalerts_orders_user_id"),
        ("donationalerts_orders", "ix_donationalerts_orders_order_code"),
        ("donationalerts_orders", "ix_donationalerts_orders_status"),
        ("donationalerts_exceptions", "ix_donationalerts_exceptions_donation_id"),
        ("donationalerts_exceptions", "ix_donationalerts_exceptions_status"),
    ):
        if index_name in _indexes(table):
            op.drop_index(index_name, table_name=table)
    for table, cols in (
        ("offers", ("budget_refunded_at", "max_participants", "budget_spent", "budget_total")),
        ("events", ("image_file_id",)),
        ("users", ("timezone", "last_freebie_year", "last_freebie_week", "promo_month", "lootbox_pity_counter")),
    ):
        existing = _columns(table)
        to_drop = [c for c in cols if c in existing]
        if to_drop:
            with op.batch_alter_table(table) as batch_op:
                for c in to_drop:
                    batch_op.drop_column(c)
    if "promo_messages" in _tables():
        op.drop_table("promo_messages")
