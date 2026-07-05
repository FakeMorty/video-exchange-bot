from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, User, LotteryRound, LotteryTicket, LotteryBet
from app.services import settle_lottery_round


@pytest.mark.asyncio
async def test_settle_lottery_round_pays_all_winner_tiers_and_bets():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        u6 = User(telegram_id=1001, balance=Decimal("0.00"))
        u5 = User(telegram_id=1002, balance=Decimal("0.00"))
        u4 = User(telegram_id=1003, balance=Decimal("0.00"))
        bettor = User(telegram_id=1004, balance=Decimal("0.00"))
        session.add_all([u6, u5, u4, bettor])
        await session.flush()

        round_obj = LotteryRound(
            week_key="test_round_1",
            status="drawing",
            ticket_price=Decimal("10.00"),
            numbers_pool=36,
            numbers_per_ticket=6,
            drawn_numbers="1,2,3,4,5,6",
            prize_pool=Decimal("100.00"),
            starts_at=u6.created_at,
            draw_starts_at=u6.created_at,
            draw_ends_at=u6.created_at,
        )
        session.add(round_obj)
        await session.flush()

        session.add_all([
            LotteryTicket(round_id=round_obj.id, user_id=u6.id, numbers="1,2,3,4,5,6"),
            LotteryTicket(round_id=round_obj.id, user_id=u5.id, numbers="1,2,3,4,5,7"),
            LotteryTicket(round_id=round_obj.id, user_id=u4.id, numbers="1,2,3,4,7,8"),
            LotteryBet(round_id=round_obj.id, user_id=bettor.id, bet_type="first_odd", amount=Decimal("10.00")),
        ])
        await session.commit()

        stats = await settle_lottery_round(session, round_obj)

        assert stats["tickets"] == 3
        assert stats["winners"] == 3
        assert stats["paid_total"] == 100.0

        await session.refresh(u6)
        await session.refresh(u5)
        await session.refresh(u4)
        await session.refresh(bettor)

        assert u6.balance == Decimal("70.00")
        assert u5.balance == Decimal("20.00")
        assert u4.balance == Decimal("10.00")
        assert bettor.balance == Decimal("20.00")

    await engine.dispose()
