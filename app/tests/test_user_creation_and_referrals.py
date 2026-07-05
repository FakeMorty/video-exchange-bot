from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, User
from app.services import get_or_create_user


@pytest.mark.asyncio
async def test_new_user_gets_single_starting_balance_not_double_counted():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        user, created = await get_or_create_user(session, telegram_id=5001, username="newbie")
        assert created is True
        assert user.balance == Decimal("100.00")

    await engine.dispose()


@pytest.mark.asyncio
async def test_referred_user_gets_bonus_and_inviter_counter_increments():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        inviter = User(
            telegram_id=6001,
            balance=Decimal("0.00"),
            referral_code="REFCODE1",
            referrals_count=0,
        )
        session.add(inviter)
        await session.commit()

        referred, created = await get_or_create_user(
            session,
            telegram_id=6002,
            username="referred_user",
            referral_code="REFCODE1",
        )

        assert created is True
        assert referred.balance == Decimal("150.00")

        await session.refresh(inviter)
        assert inviter.referrals_count == 1

    await engine.dispose()
