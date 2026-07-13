from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, BalanceLog, Offer, OfferRental, User, utc_now
from app.services import (
    create_offer_rental,
    get_active_offers,
    get_active_rentals_for_offer,
    is_offer_available,
    moderate_offer,
    moderate_offer_rental,
    normalize_telegram_url,
    start_offer_participation,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("@ExampleBot", "https://t.me/ExampleBot"),
        ("t.me/example_channel", "https://t.me/example_channel"),
        ("https://t.me/+InviteHash", "https://t.me/+InviteHash"),
        ("https://evil.example/?next=t.me/channel", None),
        ("https://t.me/", None),
    ],
)
def test_normalize_telegram_url(raw, expected):
    assert normalize_telegram_url(raw) == expected


@pytest.mark.asyncio
async def test_offer_moderation_starts_duration_on_approval_and_is_idempotent():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        creator = User(telegram_id=7001, balance=Decimal("100"))
        session.add(creator)
        await session.flush()
        submitted_at = utc_now() - timedelta(days=20)
        offer = Offer(
            creator_user_id=creator.id,
            title="Test",
            description="Description",
            channel_url="https://t.me/example_channel",
            reward_preview=Decimal("10"),
            reward_final=Decimal("50"),
            duration_days=7,
            status="pending",
            is_active=False,
            created_at=submitted_at,
        )
        session.add(offer)
        await session.commit()

        reviewed = await moderate_offer(
            session,
            offer.id,
            approve=True,
            admin_telegram_id=999,
        )
        assert reviewed is not None
        assert reviewed.status == "approved"
        assert reviewed.is_active is True
        assert reviewed.approved_at is not None
        assert reviewed.approved_at > submitted_at
        assert is_offer_available(reviewed)

        offer_id = reviewed.id
        repeated = await moderate_offer(
            session,
            offer_id,
            approve=False,
            admin_telegram_id=999,
            reason="second click",
        )
        assert repeated is None
        current = await session.get(Offer, offer_id)
        await session.refresh(current)
        assert current.status == "approved"

    await engine.dispose()


@pytest.mark.asyncio
async def test_expired_offer_is_hidden_and_rejects_stale_participation_button():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        user = User(telegram_id=7002, balance=Decimal("100"))
        offer = Offer(
            title="Expired",
            description="Expired",
            channel_url="https://t.me/example_channel",
            reward_preview=Decimal("10"),
            reward_final=Decimal("50"),
            duration_days=1,
            status="approved",
            is_active=True,
            approved_at=utc_now() - timedelta(days=2),
        )
        session.add_all([user, offer])
        await session.commit()

        assert await get_active_offers(session) == []
        participation, is_new = await start_offer_participation(session, user.id, offer.id)
        assert participation is None
        assert is_new is False
        await session.refresh(user)
        assert user.balance == Decimal("100")

    await engine.dispose()


@pytest.mark.asyncio
async def test_rental_rejection_refunds_once_and_approval_publishes_ad():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        renter = User(telegram_id=7003, balance=Decimal("100"))
        offer = Offer(
            title="Parent",
            description="Parent offer",
            channel_url="https://t.me/parent_channel",
            reward_preview=Decimal("10"),
            reward_final=Decimal("50"),
            duration_days=30,
            status="approved",
            is_active=True,
            is_rentable=True,
            rent_cost_per_day=Decimal("10"),
            max_simultaneous_rentals=1,
            approved_at=utc_now(),
        )
        session.add_all([renter, offer])
        await session.commit()

        rental, error = await create_offer_rental(
            session,
            offer.id,
            renter.id,
            "Renter channel",
            "@renter_channel",
            3,
        )
        assert error is None
        assert rental.status == "pending"
        await session.refresh(renter)
        assert renter.balance == Decimal("70")

        rejected, error = await moderate_offer_rental(
            session,
            rental.id,
            approve=False,
            admin_telegram_id=999,
            reason="bad ad",
        )
        assert error is None
        assert rejected.status == "rejected"
        await session.refresh(renter)
        assert renter.balance == Decimal("100")

        repeated, error = await moderate_offer_rental(
            session,
            rental.id,
            approve=False,
            admin_telegram_id=999,
            reason="second click",
        )
        assert repeated is None
        assert error
        refunds = (await session.execute(
            select(BalanceLog).where(
                BalanceLog.source == "offer_rental_refund",
                BalanceLog.source_id == rental.id,
            )
        )).scalars().all()
        assert len(refunds) == 1

        second, error = await create_offer_rental(
            session,
            offer.id,
            renter.id,
            "Approved ad",
            "https://t.me/approved_ad",
            2,
        )
        assert error is None
        active, error = await moderate_offer_rental(
            session,
            second.id,
            approve=True,
            admin_telegram_id=999,
        )
        assert error is None
        assert active.status == "active"
        assert active.expires_at > utc_now()

        ads = await get_active_rentals_for_offer(session, offer.id)
        assert [ad.id for ad in ads] == [second.id]

    await engine.dispose()
