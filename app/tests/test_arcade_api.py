"""
Хендлер-level тесты API «Космической аркады»:
подписанный Telegram initData, полный раунд через HTTP, защита от чужих забегов.
"""
import hashlib
import hmac
import json
import time
import urllib.parse
from decimal import Decimal

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.arcade as arcade
from app.models import Base, User

TOKEN = "123456:API-TEST-TOKEN"


def _headers(user_id: int) -> dict:
    data = {
        "user": json.dumps({"id": user_id}, separators=(",", ":")),
        "auth_date": str(int(time.time())),
        "query_id": "test",
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urllib.parse.urlencode(data)}


@pytest.fixture
async def client(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as session:
        session.add(User(
            telegram_id=4242, balance=Decimal("500.00"),
            nickname_set=True, display_name="Pilot",
        ))
        await session.commit()

    monkeypatch.setattr("app.db.async_session", Session)
    monkeypatch.setattr("app.main.BOT_TOKEN", TOKEN)

    import app.main as m
    app = web.Application()
    app.router.add_get("/arcade", m.arcade_page_handler)
    app.router.add_get("/api/arcade/state", m.api_arcade_state)
    app.router.add_post("/api/arcade/start", m.api_arcade_start)
    app.router.add_post("/api/arcade/wave", m.api_arcade_wave)
    app.router.add_post("/api/arcade/cashout", m.api_arcade_cashout)
    app.router.add_get("/api/arcade/top", m.api_arcade_top)

    c = TestClient(TestServer(app))
    await c.start_server()
    yield c
    await c.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_page_served_and_auth_required(client):
    r = await client.get("/arcade")
    html = await r.text()
    assert r.status == 200
    assert "Космическая Аркада" in html
    assert "telegram-web-app.js" in html

    r = await client.get("/api/arcade/state")
    assert r.status == 401

    # левый initData не проходит проверку подписи
    r = await client.get(
        "/api/arcade/state",
        headers={"X-Telegram-Init-Data": "user=%7B%22id%22%3A4242%7D&hash=deadbeef"},
    )
    assert r.status == 401


@pytest.mark.asyncio
async def test_full_round_over_http(client, monkeypatch):
    # Детерминированный раунд: crash-волна далеко → всегда hit
    monkeypatch.setattr(arcade, "draw_crash_wave", lambda *a, **k: 99)
    h = _headers(4242)

    st = await (await client.get("/api/arcade/state", headers=h)).json()
    assert st["ok"] and st["balance"] == 500.0 and st["active_run"] is None

    # Старт
    r = await (await client.post("/api/arcade/start", headers=h, json={"bet": 25})).json()
    assert r["ok"] and r["balance"] == 475.0
    run_id = r["run"]["run_id"]
    assert r["run"]["multiplier"] == 1.0

    # Первая волна
    w = await (await client.post("/api/arcade/wave", headers=h, json={"run_id": run_id})).json()
    assert w["ok"] and w["outcome"] == "hit" and w["wave"] == 1
    assert w["multiplier"] == 1.35
    assert w["balance"] == 475.0  # выплата только при выводе

    # Вывод
    co = await (await client.post("/api/arcade/cashout", headers=h, json={"run_id": run_id})).json()
    assert co["ok"] and co["payout"] == 33.75 and co["profit"] == 8.75
    assert co["balance"] == pytest.approx(508.75)

    # Повторный вывод — 409, без двойного начисления
    r2 = await client.post("/api/arcade/cashout", headers=h, json={"run_id": run_id})
    assert r2.status == 409
    st2 = await (await client.get("/api/arcade/state", headers=h)).json()
    assert st2["balance"] == pytest.approx(508.75)
    assert st2["active_run"] is None


@pytest.mark.asyncio
async def test_foreign_run_is_404_not_500(client, monkeypatch):
    """
    Регрессия: чужой/несуществующий run_id должен отдавать 404,
    а не падать в 500 (aiohttp Response — falsy, err проверяется через is not None).
    """
    monkeypatch.setattr(arcade, "draw_crash_wave", lambda *a, **k: 99)
    owner = _headers(4242)
    r = await (await client.post("/api/arcade/start", headers=owner, json={"bet": 10})).json()
    run_id = r["run"]["run_id"]

    # Несуществующий пользователь
    stranger = _headers(9999)
    resp = await client.post("/api/arcade/wave", headers=stranger, json={"run_id": run_id})
    assert resp.status == 404
    resp = await client.post("/api/arcade/cashout", headers=stranger, json={"run_id": run_id})
    assert resp.status == 404

    # Несуществующий run_id у существующего пользователя
    resp = await client.post("/api/arcade/wave", headers=owner, json={"run_id": 999999})
    assert resp.status == 404


@pytest.mark.asyncio
async def test_start_validations_over_http(client):
    h = _headers(4242)
    r = await (await client.post("/api/arcade/start", headers=h, json={"bet": 5})).json()
    assert not r["ok"] and r["error"] == "bad_bet"
    r = await (await client.post("/api/arcade/start", headers=h, json={"bet": "мусор"})).json()
    assert not r["ok"] and r["error"] == "bad_bet"
    r = await (await client.post("/api/arcade/start", headers=h, json={"bet": 99999})).json()
    assert not r["ok"] and r["error"] in ("bad_bet", "no_funds")


@pytest.mark.asyncio
async def test_top_endpoint_public(client):
    r = await (await client.get("/api/arcade/top")).json()
    assert r["ok"] and r["rows"] == []
