import hashlib
import hmac
import json
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, User


def build_init_data(bot_token: str, user_id: int) -> str:
    payload = {
        "auth_date": str(int(datetime.now(timezone.utc).timestamp())),
        "query_id": "AAEAAAE",
        "user": json.dumps({"id": user_id, "first_name": "Test"}, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(payload.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    payload["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(payload)


class DummyRequest:
    def __init__(self, headers=None, query=None, payload=None):
        self.headers = headers or {}
        self.query = query or {}
        self._payload = payload or {}

    async def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_webapp_auth_validation_and_balance_endpoint(monkeypatch):
    import app.db
    import app.main as main

    bot_token = "123456:TESTTOKEN"
    monkeypatch.setattr(main, "BOT_TOKEN", bot_token)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(app.db, "async_session", Session)

    async with Session() as session:
        session.add_all([
            User(telegram_id=1111, balance=Decimal("55.00")),
            User(telegram_id=2222, balance=Decimal("99.00")),
        ])
        await session.commit()

    init_data = build_init_data(bot_token, 1111)
    assert main._validate_telegram_webapp_init_data(init_data) == 1111
    assert main._validate_telegram_webapp_init_data(init_data + "tamper") is None

    unauthorized = await main.api_user_balance(DummyRequest())
    assert unauthorized.status == 401

    # Even if attacker spoofs another user_id in query/body, endpoint must trust initData only.
    authorized = await main.api_user_balance(
        DummyRequest(headers={"X-Telegram-Init-Data": init_data}, query={"user_id": "2222"})
    )
    data = json.loads(authorized.text)
    assert data["ok"] is True
    assert data["balance"] == 55.0

    await engine.dispose()
