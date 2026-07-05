import hashlib
import hmac
import json
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, User, LotteryBet


def build_init_data(bot_token: str, user_id: int) -> str:
    payload = {
        "auth_date": str(int(datetime.now(timezone.utc).timestamp())),
        "query_id": "AAEAAAE",
        "user": json.dumps({"id": user_id, "first_name": "BetUser"}, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(payload.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    payload["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(payload)


class DummyRequest:
    def __init__(self, payload, headers=None, query=None):
        self._payload = payload
        self.headers = headers or {}
        self.query = query or {}

    async def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_api_lottery_place_bet_creates_bet_and_charges_user(monkeypatch):
    import app.db
    import app.main

    bot_token = "123456:BETTOKEN"
    monkeypatch.setattr(app.main, "BOT_TOKEN", bot_token)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(app.db, "async_session", Session)

    async with Session() as session:
        user = User(telegram_id=7001, balance=Decimal("100.00"))
        session.add(user)
        await session.commit()

    init_data = build_init_data(bot_token, 7001)
    response = await app.main.api_lottery_place_bet(
        DummyRequest({"bet_type": "first_odd"}, headers={"X-Telegram-Init-Data": init_data})
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
