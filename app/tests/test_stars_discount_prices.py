from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, User, UserPerk
from app.services import get_current_prices, get_stars_discount
from app.models import utc_now


@pytest.mark.asyncio
async def test_stars_discount_affects_displayed_vip_and_pack_prices():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        user = User(telegram_id=9401, balance=Decimal("0.00"), nickname_set=True, display_name="Buyer")
        session.add(user)
        await session.flush()
        session.add(UserPerk(
            user_id=user.id,
            perk_type="stars_discount",
            active_until=utc_now() + timedelta(days=7),
            is_active=True,
        ))
        await session.commit()

        discount = await get_stars_discount(session, user.id)
        vip_price, packs, _ = await get_current_prices(session, user.id)

        assert discount == 0.25
        assert vip_price == 75
        assert packs["pack_50"]["stars"] == 38
        assert packs["pack_100"]["stars"] == 75

    await engine.dispose()
