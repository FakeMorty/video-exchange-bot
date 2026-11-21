"""Remove DonationAlerts tables (card transfer replaces DA).

Revision ID: remove_donationalerts_001
Revises: event_automation_001

DonationAlerts удалён: автоматической сверки больше нет, оплата — переводом
на карту с ручной сверкой админом через конвертер. Таблицы заказов и очереди
исключений больше не нужны.
"""
from alembic import op


revision = "remove_donationalerts_001"
down_revision = "event_automation_001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("donationalerts_exceptions", "donationalerts_orders"):
        try:
            op.drop_table(table)
            print(f"✅ Dropped table: {table}")
        except Exception as e:
            print(f"⚠️ Table {table} may already be absent: {e}")


def downgrade() -> None:
    # Таблицы не восстанавливаем: DonationAlerts удалён из кода.
    pass
