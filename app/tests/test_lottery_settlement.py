from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, User, LotteryRound, LotteryTicket, LotteryBet
from app.services import settle_lottery_round, draw_next_lottery_number


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
        # paid_total считает только выплаты по билетам:
        # 5 (6 совпадений, джекпот) + 10 (5 совпадений) + 25 (4 совпадения) = 40
        # (выигрыш по ставке bettor не входит в paid_total, начисляется отдельно)
        # Остаток 60 монет остаётся в пуле (нет победителей с 3/2 совпадениями)
        assert stats["paid_total"] == 40.0

        await session.refresh(u6)
        await session.refresh(u5)
        await session.refresh(u4)
        await session.refresh(bettor)

        # Распределение призового фонда 100 монет:
        # 6 совпадений (джекпот) = 5% / 1 победитель = 5 монет
        # 5 совпадений = 10% / 1 победитель = 10 монет
        # 4 совпадения = 25% / 1 победитель = 25 монет
        # 3 совпадения = 60% (без победителей, не выплачивается)
        assert u6.balance == Decimal("5.00")
        assert u5.balance == Decimal("10.00")
        assert u4.balance == Decimal("25.00")
        # Ставка на нечётный первый бочонок: выпал 1 (нечётный) — ставка удваивается
        assert bettor.balance == Decimal("20.00")

    await engine.dispose()


@pytest.mark.asyncio
async def test_draw_next_lottery_number_preserves_draw_order_for_side_bets():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        round_obj = LotteryRound(
            week_key="test_round_2",
            status="drawing",
            ticket_price=Decimal("10.00"),
            numbers_pool=6,
            numbers_per_ticket=3,
            drawn_numbers="5,1",
            prize_pool=Decimal("0.00"),
            starts_at=None,
            draw_starts_at=None,
            draw_ends_at=None,
        )
        # SQLite model requires datetimes, so use a real timestamp
        from app.models import utc_now
        now = utc_now()
        round_obj.starts_at = now
        round_obj.draw_starts_at = now
        round_obj.draw_ends_at = now
        session.add(round_obj)
        await session.commit()

        next_num = await draw_next_lottery_number(session, round_obj)
        assert next_num in {2, 3, 4, 6}
        assert round_obj.drawn_numbers.startswith("5,1,")

    await engine.dispose()
