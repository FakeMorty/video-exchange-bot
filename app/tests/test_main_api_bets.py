import json
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, User, LotteryBet


class DummyRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_api_lottery_place_bet_creates_bet_and_charges_user(monkeypatch):
    import app.db
    import app.main

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(app.db, "async_session", Session)

    async with Session() as session:
        user = User(telegram_id=7001, balance=Decimal("100.00"))
        session.add(user)
        await session.commit()

    response = await app.main.api_lottery_place_bet(
        DummyRequest({"user_id": 7001, "bet_type": "first_odd"})
    )
    payload = json.loads(response.text)

    assert payload["ok"] is True
    assert payload["balance"] == 90.0

    async with Session() as session:
        db_user = (await session.execute(select(User).where(User.telegram_id == 7001))).scalar_one()
        bets = (await session.execute(select(LotteryBet).where(LotteryBet.user_id == db_user.id))).scalars().all()

        assert db_user.balance == Decimal("90.00")
        assert len(bets) == 1
        assert bets[0].bet_type == "first_odd"
        assert bets[0].amount == Decimal("10.00")

    await engine.dispose()
