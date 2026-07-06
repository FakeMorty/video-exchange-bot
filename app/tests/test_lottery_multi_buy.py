import hashlib
import hmac
import json
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, User, LotteryTicket
from app.services import buy_lottery_tickets


def build_init_data(bot_token: str, user_id: int) -> str:
    payload = {
        "auth_date": str(int(datetime.now(timezone.utc).timestamp())),
        "query_id": "AAEAAAE",
        "user": json.dumps({"id": user_id, "first_name": "Buyer"}, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(payload.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    payload["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(payload)


class DummyRequest:
    def __init__(self, payload, headers=None):
        self._payload = payload
        self.headers = headers or {}
        self.query = {}

    async def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_buy_lottery_tickets_charges_total_and_creates_batch():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        user = User(telegram_id=9901, balance=Decimal("150.00"))
        session.add(user)
        await session.commit()

        tickets, total_cost, error = await buy_lottery_tickets(session, user, 3)
        await session.refresh(user)

        assert error is None
        assert len(tickets) == 3
        assert total_cost == Decimal("90.00")
        assert user.balance == Decimal("60.00")

        db_tickets = (await session.execute(select(LotteryTicket).where(LotteryTicket.user_id == user.id))).scalars().all()
        assert len(db_tickets) == 3

    await engine.dispose()


@pytest.mark.asyncio
async def test_api_lottery_buy_accepts_quantity(monkeypatch):
    import app.db
    import app.main as main

    bot_token = "123456:BUYTOKEN"
    monkeypatch.setattr(main, "BOT_TOKEN", bot_token)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(app.db, "async_session", Session)

    async with Session() as session:
        user = User(telegram_id=9902, balance=Decimal("200.00"))
        session.add(user)
        await session.commit()

    init_data = build_init_data(bot_token, 9902)
    response = await main.api_lottery_buy(
        DummyRequest({"quantity": 4}, headers={"X-Telegram-Init-Data": init_data})
    )
    payload = json.loads(response.text)

    assert payload["ok"] is True
    assert payload["quantity"] == 4
    assert payload["balance"] == 80.0

    await engine.dispose()
