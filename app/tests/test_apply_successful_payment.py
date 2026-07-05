from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, User, Payment
from app.services import apply_successful_payment


@pytest.mark.asyncio
async def test_apply_successful_payment_returns_real_credited_amount():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        user = User(telegram_id=9501, balance=Decimal("0.00"))
        session.add(user)
        await session.flush()
        payment = Payment(
            user_id=user.id,
            payload="pack_test_1",
            stars_amount=10,
            coins_amount=Decimal("120.00"),
            status="pending",
        )
        session.add(payment)
        await session.commit()

        applied_payment, credited_total = await apply_successful_payment(session, "pack_test_1")
        await session.refresh(user)

        assert applied_payment is not None
        assert credited_total >= Decimal("120.00")
        assert user.balance == credited_total
        assert applied_payment.status == "paid"

    await engine.dispose()
