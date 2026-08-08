"""БОЛЬШОЙ МАСТЕР-ТЕСТ БОТА (единый файл).

Сюда объединены все тесты из бывших отдельных файлов app/tests/test_*.py
(каждый раздел помечен именем исходного файла) + полные сценарии-сьюты
(архив роста, хотфиксы, халява, ротация промо и т.д.) — см. конец файла.

КАК ДОПИСЫВАТЬ: просто добавь в конец файла новую `async def test_...` (или
обычную `def test_...`) в тематический раздел. Для тестов с БД в своей
песочнице вызови `await reset_bot_db()` в начале теста.
"""

from decimal import Decimal
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.admin_handlers import _parse_video_number
from app.models import BalanceLog, Base, User, UserActionLog, Video
from app.services import (
    AdminBalanceError,
    adjust_balance_by_admin,
    get_rejected_video,
    get_video_by_id,
    restore_rejected_video,
)
from types import SimpleNamespace
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.models import Base, User, KatyaChat
import time
from app.models import Base, User
from app.models import Base, User, Payment
from app.services import apply_successful_payment
import hashlib
import hmac
import json
import urllib.parse
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import app.arcade as arcade
from datetime import timedelta
from app.arcade import (
    ArcadeConfig,
    advance_wave,
    cashout_run,
    expire_stale_runs,
    get_active_run,
    start_run,
)
from app.models import ArcadeRun, Base, GameHistory, User, utc_now
from app.services import get_user
import random
from app.arcade import (
    BASE_HIT_CHANCE,
    MAX_MULT_STEP,
    MIN_HIT_CHANCE,
    draw_crash_wave,
    load_arcade_config,
    multiplier_after,
    next_multiplier,
    payout_for,
    wave_hit_chance,
    wave_mult_step,
)
from app.models import Base, BotSetting
from unittest.mock import AsyncMock
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine
from app.user_handlers import _best_event_badge
from datetime import datetime, timezone
from app.models import Base, User, LotteryTicket
from app.services import buy_lottery_tickets
from datetime import datetime
from app.services import _get_lottery_window
from app.models import Base, User, LotteryRound, LotteryTicket, LotteryBet
from app.services import settle_lottery_round, draw_next_lottery_number
from app.models import Base, User, LotteryBet
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone, timedelta
from app.models import User
from app.services import log_balance_change
from app.utils.messaging import format_time_for_user
from app.config import NICKNAME_MIN_LENGTH
from app.services import (
    has_valid_nickname,
    is_placeholder_nickname,
    validate_nickname_format,
)
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
from sqlalchemy import select, func
from app.models import Base, User, Video, VideoView, BalanceLog
from app.services import process_referral_reward
from app.models import Base, User, Video
from app.release_notes import build_version_text, get_recent_changelog_items, CURRENT_VERSION
from app.models import Base, BalanceLog, LotteryRound, LotteryTicket, Payment, User, UserActionLog, Video, VideoView, utc_now
from app.rules_text import FULL_RULES_TEXT, SHORT_RULES_TEXT
from app.services import reject_video
from app.services import to_decimal, round_coin
from app.models import Base, User, UserPerk
from app.services import get_current_prices, get_stars_discount
from app.models import utc_now
from app.models import Base, User, Video, TrustedUploader, UserPerk, BotSetting, utc_now
from app.services import auto_approve_if_trusted
from app.services import get_or_create_user
from app.user_offer_handlers import _calc_offer_stars_price
from app.models import Base, User, Video, VideoView


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_admin_content_and_balance.py
# ══════════════════════════════════════════════════════════════

@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as session:
        yield session
    await engine.dispose()


def test_parse_video_number_accepts_hash_and_plain_id():
    assert _parse_video_number("#1234") == 1234
    assert _parse_video_number(" 1234 ") == 1234
    assert _parse_video_number("#0") is None
    assert _parse_video_number("video 1234") is None


@pytest.mark.asyncio
async def test_rejected_archive_lookup_and_restore(db_session):
    user = User(telegram_id=700001, display_name="Author", balance=Decimal("0"))
    db_session.add(user)
    await db_session.flush()
    first = Video(
        uploader_user_id=user.id,
        telegram_file_id="file-1",
        telegram_file_unique_id="unique-1",
        status="rejected",
        rejection_reason="duplicate",
    )
    second = Video(
        uploader_user_id=user.id,
        telegram_file_id="file-2",
        telegram_file_unique_id="unique-2",
        status="rejected",
        rejection_reason="off topic",
    )
    db_session.add_all([first, second])
    await db_session.commit()

    found = await get_video_by_id(db_session, first.id)
    newest = await get_rejected_video(db_session, 0)
    assert found.id == first.id
    assert newest.id == second.id

    restored = await restore_rejected_video(db_session, second.id)
    assert restored.status == "pending"
    assert restored.rejection_reason is None
    assert (await get_rejected_video(db_session, 0)).id == first.id


@pytest.mark.asyncio
async def test_admin_balance_change_is_logged_once(db_session):
    admin = User(telegram_id=800001, display_name="Admin", balance=Decimal("0"), is_admin=True)
    target = User(telegram_id=800002, display_name="Target", balance=Decimal("100"))
    db_session.add_all([admin, target])
    await db_session.commit()

    changed = await adjust_balance_by_admin(db_session, target.id, Decimal("25.129"), admin.id)
    await db_session.commit()
    assert changed.balance == Decimal("125.13")

    logs = (await db_session.execute(select(BalanceLog))).scalars().all()
    assert len(logs) == 1
    assert logs[0].amount == Decimal("25.13")
    assert logs[0].balance_before == Decimal("100")
    assert logs[0].balance_after == Decimal("125.13")
    assert logs[0].admin_id == admin.id
    actions = (await db_session.execute(select(UserActionLog))).scalars().all()
    assert len(actions) == 1


@pytest.mark.asyncio
async def test_admin_cannot_create_negative_balance_or_zero_change(db_session):
    admin = User(telegram_id=900001, display_name="Admin", balance=Decimal("0"), is_admin=True)
    target = User(telegram_id=900002, display_name="Target", balance=Decimal("10"))
    db_session.add_all([admin, target])
    await db_session.commit()

    with pytest.raises(AdminBalanceError, match="Нельзя списать"):
        await adjust_balance_by_admin(db_session, target.id, Decimal("-11"), admin.id)
    with pytest.raises(AdminBalanceError, match="ненулевым"):
        await adjust_balance_by_admin(db_session, target.id, Decimal("0"), admin.id)

    await db_session.refresh(target)
    assert target.balance == Decimal("10")
    assert (await db_session.execute(select(BalanceLog))).scalars().all() == []


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_ai_assistant_custom_chat.py
# ══════════════════════════════════════════════════════════════

class DummyState_ai_assistant_custom_chat:
    def __init__(self, data=None):
        self.data = data or {}
        self.state = None

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def set_state(self, value):
        self.state = value


class DummyMessage_ai_assistant_custom_chat:
    def __init__(self, text, user_id):
        self.text = text
        self.from_user = SimpleNamespace(id=user_id)
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


@pytest.mark.asyncio
async def test_custom_named_chat_keeps_selected_character(monkeypatch):
    import app.ai_assistant as ai_assistant

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(ai_assistant, "async_session", Session)

    async with Session() as session:
        user = User(telegram_id=8001, balance=Decimal("100.00"), nickname_set=True)
        session.add(user)
        await session.commit()

    state = DummyState_ai_assistant_custom_chat({"waiting_chat_name": True, "selected_char": "sofa"})
    message = DummyMessage_ai_assistant_custom_chat("Мой кастомный чат", 8001)

    await ai_assistant.katya_menu_message(message, state)

    async with Session() as session:
        created_chat = (await session.execute(select(KatyaChat))).scalar_one()
        assert created_chat.character == "sofa"
        assert created_chat.title == "Мой кастомный чат"

    assert state.data["selected_char"] == "sofa"
    assert any("Чат «Мой кастомный чат»" in text for text, _ in message.answers)

    await engine.dispose()


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_ai_daily_limit_refund.py
# ══════════════════════════════════════════════════════════════

class DummyState_ai_daily_limit_refund:
    def __init__(self):
        self.data = {}

    async def get_data(self):
        return dict(self.data)


class DummyBot:
    async def send_chat_action(self, *args, **kwargs):
        return None


class DummyMessage_ai_daily_limit_refund:
    def __init__(self, user_id, text):
        self.from_user = SimpleNamespace(id=user_id)
        self.text = text
        self.bot = DummyBot()
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


@pytest.mark.asyncio
async def test_ai_api_failure_refunds_balance_and_releases_daily_limit(monkeypatch):
    import app.ai_assistant as ai

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(ai, "async_session", Session)
    monkeypatch.setattr(ai, "call_katya", lambda *args, **kwargs: __import__('asyncio').sleep(0, result=None))
    monkeypatch.setattr(ai, "_append_history", lambda *args, **kwargs: __import__('asyncio').sleep(0))
    monkeypatch.setattr(ai, "_get_history", lambda *args, **kwargs: __import__('asyncio').sleep(0, result=[]))

    user_id = 9201
    ai._user_daily_count[user_id] = ai.AI_ASSISTANT_DAILY_LIMIT - 1
    ai._user_daily_reset[user_id] = time.monotonic()
    ai._user_last_ts.pop(user_id, None)

    async with Session() as session:
        user = User(telegram_id=user_id, balance=Decimal("100.00"), nickname_set=True, display_name="Tester")
        session.add(user)
        await session.commit()

    message = DummyMessage_ai_daily_limit_refund(user_id, "Привет")
    state = DummyState_ai_daily_limit_refund()

    await ai.katya_chat_message(message, state)

    async with Session() as session:
        db_user = (await session.execute(select(User).where(User.telegram_id == user_id))).scalar_one()
        assert db_user.balance == Decimal("100.00")

    assert ai._user_daily_count[user_id] == ai.AI_ASSISTANT_DAILY_LIMIT - 1
    assert message.answers
    assert "связь барахлит" in message.answers[-1][0]

    await engine.dispose()


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_apply_successful_payment.py
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_apply_successful_payment_returns_real_credited_amount():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        user = User(telegram_id=9501, balance=Decimal("0.00"))
        session.add(user)
        await session.flush()
        payment = Payment(
            user_id=user.id,
            payload="pack_test_1",
            stars_amount=10,
            coins_amount=Decimal("120.00"),
            status="pending",
        )
        session.add(payment)
        await session.commit()

        applied_payment, credited_total = await apply_successful_payment(session, "pack_test_1")
        await session.refresh(user)

        assert applied_payment is not None
        assert credited_total >= Decimal("120.00")
        assert user.balance == credited_total
        assert applied_payment.status == "paid"

        second_payment, second_credit = await apply_successful_payment(session, "pack_test_1")
        await session.refresh(user)

        assert second_payment is None
        assert second_credit == Decimal("0")
        assert user.balance == credited_total

    await engine.dispose()


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_arcade_api.py
# ══════════════════════════════════════════════════════════════

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

    # ВНИМАНИЕ: patch монкипатча в ASYNC-фикстуре не гарантирует откат до
    # следующего теста (порядок финализации async-генераторов в auto-режиме),
    # из-за чего последующие тесты видели чужую пустую :memory:-БД
    # ("no such table"). Поэтому — ручной патч с гарантированным откатом.
    import app.db as _real_db
    import app.main as m
    _orig_session = _real_db.async_session
    _orig_token = m.BOT_TOKEN
    _real_db.async_session = Session
    m.BOT_TOKEN = TOKEN

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
    _real_db.async_session = _orig_session
    m.BOT_TOKEN = _orig_token
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


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_arcade_core_flow.py
# ══════════════════════════════════════════════════════════════

def _cfg(**kw):
    base = dict(
        enabled=True,
        min_bet=Decimal("10"),
        max_bet=Decimal("250"),
        max_multiplier=Decimal("50"),
        daily_profit_cap=Decimal("500"),
        run_ttl_minutes=30,
    )
    base.update(kw)
    return ArcadeConfig(**base)


@pytest.fixture
async def db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # arcade.py и arcade_handlers используют async_session из app.db —
    # подменяем на тестовую in-memory сессию.
    # (исправлено: ручной патч с гарантированным откатом вместо monkeypatch —
    # monkeypatch в async-фикстуре мог откатиться позже следующего теста)
    import app.arcade_handlers as ah
    _orig_ah_session = ah.async_session
    ah.async_session = Session

    async with Session() as session:
        user = User(
            telegram_id=777001,
            balance=Decimal("1000.00"),
            nickname_set=True,
            display_name="Pilot",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    yield Session
    ah.async_session = _orig_ah_session
    await engine.dispose()


# ============================
# СТАРТ ЗАБЕГА
# ============================

@pytest.mark.asyncio
async def test_start_run_deducts_bet_and_sets_crash_wave(db, monkeypatch):
    monkeypatch.setattr(arcade, "draw_crash_wave", lambda *a, **k: 5)
    async with db() as session:
        user = await get_user(session, 777001)
        run, err = await start_run(session, user, Decimal("50"), _cfg())
        assert err == ""
        assert run.status == "active"
        assert run.bet == Decimal("50.00")
        assert run.crash_wave == 5
        await session.refresh(user)
        assert user.balance == Decimal("950.00")


@pytest.mark.asyncio
async def test_start_run_validations(db):
    cfg = _cfg()
    async with db() as session:
        user = await get_user(session, 777001)
        _, err = await start_run(session, user, Decimal("5"), cfg)
        assert err == "bad_bet"  # ниже минимума
        _, err = await start_run(session, user, Decimal("9999"), cfg)
        assert err == "bad_bet"  # выше максимума
        _, err = await start_run(session, user, Decimal("10000"), cfg)
        assert err == "bad_bet"  # max_bet проверяется раньше баланса

        # Недостаточно средств
        user.balance = Decimal("5.00")
        await session.commit()
        _, err = await start_run(session, user, Decimal("100"), cfg)
        assert err == "no_funds"

        # Отключенная аркада
        _, err = await start_run(session, user, Decimal("10"), _cfg(enabled=False))
        assert err == "disabled"


@pytest.mark.asyncio
async def test_one_active_run_at_a_time(db, monkeypatch):
    monkeypatch.setattr(arcade, "draw_crash_wave", lambda *a, **k: 9)
    async with db() as session:
        user = await get_user(session, 777001)
        run1, err = await start_run(session, user, Decimal("25"), _cfg())
        assert err == ""
        _, err = await start_run(session, user, Decimal("25"), _cfg())
        assert err == "run_in_progress"
        assert (await get_active_run(session, user.id)).id == run1.id


# ============================
# ВОЛНЫ И ПРОРЫВ
# ============================

@pytest.mark.asyncio
async def test_advance_wave_hit_grows_multiplier(db, monkeypatch):
    monkeypatch.setattr(arcade, "draw_crash_wave", lambda *a, **k: 99)
    async with db() as session:
        user = await get_user(session, 777001)
        run, _ = await start_run(session, user, Decimal("100"), _cfg())

        r1 = await advance_wave(session, run, _cfg())
        assert r1["outcome"] == "hit"
        assert r1["wave"] == 1
        assert r1["multiplier"] == Decimal("1.35")

        r2 = await advance_wave(session, run, _cfg())
        assert r2["outcome"] == "hit"
        assert r2["wave"] == 2
        assert r2["multiplier"] == Decimal("1.89")

        # Баланс пока не менялся (ставка списана на старте)
        await session.refresh(user)
        assert user.balance == Decimal("900.00")


@pytest.mark.asyncio
async def test_advance_wave_breach_loses_bet(db, monkeypatch):
    # crash_wave = 0 → прорыв на первой же попытке
    monkeypatch.setattr(arcade, "draw_crash_wave", lambda *a, **k: 0)
    async with db() as session:
        user = await get_user(session, 777001)
        run, _ = await start_run(session, user, Decimal("40"), _cfg())
        result = await advance_wave(session, run, _cfg())
        assert result["outcome"] == "lost"
        assert run.status == "lost"

        hist = (await session.execute(
            select(GameHistory).where(GameHistory.user_id == user.id)
        )).scalar_one()
        assert hist.game_type == "arcade"
        assert hist.result == Decimal("-40.00")

        await session.refresh(user)
        assert user.balance == Decimal("960.00")  # ставка сгорела, возврата нет


@pytest.mark.asyncio
async def test_multiplier_cap_triggers_auto_cashout(db, monkeypatch):
    monkeypatch.setattr(arcade, "draw_crash_wave", lambda *a, **k: 999)
    cfg = _cfg(max_multiplier=Decimal("2"))
    async with db() as session:
        user = await get_user(session, 777001)
        run, _ = await start_run(session, user, Decimal("100"), _cfg())
        r1 = await advance_wave(session, run, cfg)
        assert r1["outcome"] == "hit"
        # Вторая волна: 1.35 * 1.40 = 1.89; третья: *1.45 = 2.74 >= cap=2 → авто-вывод
        r2 = await advance_wave(session, run, cfg)
        assert r2["outcome"] == "hit"
        r3 = await advance_wave(session, run, cfg)
        assert r3["outcome"] == "cashed_out"
        assert r3["capped"] is True
        assert run.status == "won"
        assert run.multiplier == Decimal("2.00")
        await session.refresh(user)
        assert user.balance == Decimal("900.00") + Decimal("200.00")


# ============================
# ВЫВОД И ДНЕВНОЙ КАП
# ============================

@pytest.mark.asyncio
async def test_cashout_pays_and_is_idempotent(db, monkeypatch):
    monkeypatch.setattr(arcade, "draw_crash_wave", lambda *a, **k: 99)
    cfg = _cfg()
    async with db() as session:
        user = await get_user(session, 777001)
        run, _ = await start_run(session, user, Decimal("100"), cfg)
        await advance_wave(session, run, cfg)  # волна 1 → x1.35

        result = await cashout_run(session, run, cfg)
        assert result["ok"] is True
        assert result["payout"] == Decimal("135.00")
        assert result["profit"] == Decimal("35.00")
        assert result["cap_applied"] is False
        assert run.status == "won"

        await session.refresh(user)
        assert user.balance == Decimal("900.00") + Decimal("135.00")

        # Повторный вывод — идемпотентно, без двойного начисления
        again = await cashout_run(session, run, cfg)
        assert again["ok"] is False
        assert again["error"] == "not_active"
        await session.refresh(user)
        assert user.balance == Decimal("1035.00")


@pytest.mark.asyncio
async def test_cashout_before_any_wave_rejected(db, monkeypatch):
    monkeypatch.setattr(arcade, "draw_crash_wave", lambda *a, **k: 99)
    async with db() as session:
        user = await get_user(session, 777001)
        run, _ = await start_run(session, user, Decimal("50"), _cfg())
        result = await cashout_run(session, run, _cfg())
        assert result["ok"] is False
        assert result["error"] == "no_waves"
        assert run.status == "active"


@pytest.mark.asyncio
async def test_daily_profit_cap_limits_payout(db, monkeypatch):
    monkeypatch.setattr(arcade, "draw_crash_wave", lambda *a, **k: 99)
    cfg = _cfg(daily_profit_cap=Decimal("50"))
    async with db() as session:
        user = await get_user(session, 777001)
        # Уже заработал сегодня 40 чистой прибыли
        session.add(GameHistory(
            user_id=user.id, game_type="arcade",
            bet=Decimal("100"), result=Decimal("40.00"),
            details="раньше сегодня",
        ))
        await session.commit()

        run, _ = await start_run(session, user, Decimal("100"), _cfg())
        await advance_wave(session, run, _cfg())  # x1.35 → сырой профит 35
        result = await cashout_run(session, run, cfg)
        # remaining = 50 - 40 = 10 → выплата = 100 + 10 = 110, а не 135
        assert result["ok"] is True
        assert result["payout"] == Decimal("110.00")
        assert result["cap_applied"] is True

        # Второй забег: кап уже исчерпан → выплата = только ставка
        run2, _ = await start_run(session, user, Decimal("100"), _cfg())
        await advance_wave(session, run2, _cfg())
        result2 = await cashout_run(session, run2, cfg)
        assert result2["payout"] == Decimal("100.00")
        assert result2["cap_applied"] is True
        assert result2["profit"] == Decimal("0.00")


# ============================
# ПРОТУХШИЕ ЗАБЕГИ
# ============================

@pytest.mark.asyncio
async def test_stale_run_refunded(db, monkeypatch):
    monkeypatch.setattr(arcade, "draw_crash_wave", lambda *a, **k: 50)
    cfg = _cfg(run_ttl_minutes=30)
    async with db() as session:
        user = await get_user(session, 777001)
        run, _ = await start_run(session, user, Decimal("75"), cfg)
        assert user.balance == Decimal("925.00")

        # «Проматываем время»: забег создан 2 часа назад
        run.created_at = utc_now() - timedelta(hours=2)
        await session.commit()

        await expire_stale_runs(session, user.id, cfg)
        await session.refresh(run)
        await session.refresh(user)
        assert run.status == "expired"
        assert user.balance == Decimal("1000.00")  # ставка возвращена

        # После возврата можно стартовать заново
        run2, err = await start_run(session, user, Decimal("75"), cfg)
        assert err == ""
        assert run2.status == "active"


# ============================
# BOT-МЕНЮ
# ============================

class _FakeMsg:
    def __init__(self):
        self.sent = []

    async def answer(self, text, **kw):
        self.sent.append((text, kw))
        return _FakeMsg()

    async def edit_text(self, text, **kw):
        self.sent.append((text, kw))
        return None


class _FakeCallback:
    def __init__(self, user_id, data="arcade_menu"):
        self.from_user = SimpleNamespace(id=user_id)
        self.data = data
        self.message = _FakeMsg()
        self.answers = []

    async def answer(self, text=None, **kw):
        self.answers.append(text)


class _DummyState:
    async def clear(self):
        return None


@pytest.mark.asyncio
async def test_arcade_menu_shows_miniapp_or_howto(db, monkeypatch):
    import app.arcade_handlers as ah

    monkeypatch.setattr(ah, "arcade_webapp_url", lambda: "")
    cb = _FakeCallback(777001)
    await ah.arcade_menu(cb, _DummyState())
    text, kw = cb.message.sent[0]
    assert "Космическая Аркада" in text
    buttons = [b.callback_data for row in kw["reply_markup"].inline_keyboard for b in row]
    assert "arcade_howto" in buttons  # WEBHOOK_BASE не задан → фолбэк
    assert "arcade_top" in buttons

    # С настроенным URL — кнопка WebApp
    monkeypatch.setattr(ah, "arcade_webapp_url", lambda: "https://bot.example.com/arcade")
    cb2 = _FakeCallback(777001)
    await ah.arcade_menu(cb2, _DummyState())
    _, kw2 = cb2.message.sent[0]
    webapp_buttons = [
        b for row in kw2["reply_markup"].inline_keyboard for b in row if b.web_app
    ]
    assert webapp_buttons and webapp_buttons[0].web_app.url == "https://bot.example.com/arcade"


@pytest.mark.asyncio
async def test_arcade_menu_blocks_when_disabled(db, monkeypatch):
    import app.arcade_handlers as ah
    from app.models import BotSetting

    async with db() as session:
        session.add(BotSetting(key="arcade_enabled", value="off"))
        await session.commit()

    cb = _FakeCallback(777001)
    await ah.arcade_menu(cb, _DummyState())
    assert cb.answers and "отключена" in (cb.answers[0] or "")
    assert not cb.message.sent  # меню не рисуется


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_arcade_engine.py
# ══════════════════════════════════════════════════════════════

def test_hit_chance_decays_and_floored():
    assert wave_hit_chance(0) == pytest.approx(BASE_HIT_CHANCE)
    assert wave_hit_chance(1) < wave_hit_chance(0)
    # Пол шанса
    assert wave_hit_chance(100) == pytest.approx(MIN_HIT_CHANCE)
    # Отрицательный индекс не ломает функцию
    assert wave_hit_chance(-3) == pytest.approx(BASE_HIT_CHANCE)


def test_mult_step_grows_and_capped():
    assert wave_mult_step(0) == Decimal("1.35")
    assert wave_mult_step(1) == Decimal("1.40")
    assert wave_mult_step(50) == Decimal(str(MAX_MULT_STEP))


def test_multiplier_after_monotonic_and_capped():
    cap = Decimal("50")
    prev = Decimal("1")
    for n in range(1, 15):
        m = multiplier_after(n, cap)
        assert m >= prev
        assert m <= cap
        prev = m
    assert multiplier_after(50, cap) == cap
    # Без капа множитель растёт дальше
    assert multiplier_after(15) > cap


def test_next_multiplier_cap_flag():
    m, capped = next_multiplier(Decimal("40"), 8, Decimal("50"))
    assert capped is True
    assert m == Decimal("50")
    m2, capped2 = next_multiplier(Decimal("1.00"), 0, Decimal("50"))
    assert capped2 is False
    assert m2 == Decimal("1.35")


def test_payout_rounds_down():
    assert payout_for(Decimal("10"), Decimal("1.35")) == Decimal("13.50")
    assert payout_for(Decimal("33.33"), Decimal("1.35")) == Decimal("44.99")


def test_draw_crash_wave_distribution():
    """P(crash == 0) = 1 - p0 ≈ 0.28; среднее по выборке разумное."""
    rng = random.Random(1234)
    n = 20000
    crashes = [draw_crash_wave(rng) for _ in range(n)]
    p0 = crashes.count(0) / n
    assert 0.24 < p0 < 0.32  # 1 - 0.72 = 0.28
    avg = sum(crashes) / n
    # E[crash] = sum prod(p_i) ≈ 2.2 — проверяем порядок величины
    assert 1.5 < avg < 3.2
    assert all(c >= 0 for c in crashes)


def test_house_edge_every_stage():
    """
    EV стратегии «всегда забирать после N волн» = prod(p_k * step_k).
    Должен быть < 1 на любой стадии (бот всегда в плюсе),
    но около 0.97 на первой волне (игроку не обидно).
    """
    ev = 1.0
    for n in range(1, 12):
        k = n - 1
        ev *= wave_hit_chance(k) * float(wave_mult_step(k))
        assert ev < 1.0, f"EV >= 1 на волне {n}: игрок в плюсе!"
    # Первая волна почти безубыточна (весело), поздние — сильный минус
    ev1 = wave_hit_chance(0) * float(wave_mult_step(0))
    assert 0.90 < ev1 < 0.99
    assert ev < 0.25  # до 11-й волны доживают единицы


def test_monte_carlo_expected_payout_below_one():
    """
    Симуляция «жадного» игрока (целится в 3 волны, иначе забирает после 1-й):
    средний возврат на монету ставки должен быть заметно меньше 1.
    """
    rng = random.Random(777)
    runs = 30000
    total = 0.0
    for _ in range(runs):
        crash = draw_crash_wave(rng)
        bet = 100.0
        mult = Decimal("1")
        cleared = 0
        target = 3
        lost = False
        for w in range(target):
            if w >= crash:
                lost = True
                break
            mult, _ = next_multiplier(mult, w, Decimal("50"))
            cleared += 1
        if lost:
            total += 0.0
        else:
            total += float(payout_for(Decimal(str(bet)), mult))
    ev = total / (runs * 100.0)
    assert 0.75 < ev < 0.98, f"EV вне здорового диапазона: {ev}"


@pytest.mark.asyncio
async def test_load_arcade_config_defaults_and_overrides():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        cfg = await load_arcade_config(session)
        assert cfg.enabled is True
        assert cfg.min_bet == Decimal("10.00")
        assert cfg.max_bet == Decimal("250.00")
        assert cfg.max_multiplier == Decimal("50.00")
        assert cfg.daily_profit_cap == Decimal("500.00")

        # Админские overrides из BotSetting
        session.add_all([
            BotSetting(key="arcade_min_bet", value="25"),
            BotSetting(key="arcade_max_multiplier", value="30"),
            BotSetting(key="arcade_enabled", value="off"),
            BotSetting(key="arcade_daily_profit_cap", value="не-число"),
        ])
        await session.commit()

        cfg2 = await load_arcade_config(session)
        assert cfg2.min_bet == Decimal("25.00")
        assert cfg2.max_multiplier == Decimal("30.00")
        assert cfg2.enabled is False
        # Мусорное значение → дефолт
        assert cfg2.daily_profit_cap == Decimal("500.00")
        # max_bet >= min_bet гарантировано
        assert cfg2.max_bet >= cfg2.min_bet

    await engine.dispose()


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_auto_approve_message_format.py
# ══════════════════════════════════════════════════════════════

class DummyVideo:
    def __init__(self):
        self.file_id = "file"
        self.file_unique_id = "uniq"
        self.duration = 10
        self.file_size = 123


class DummyMessage_auto_approve_message_format:
    def __init__(self, user_id):
        self.from_user = SimpleNamespace(id=user_id)
        self.video = DummyVideo()
        self.chat = SimpleNamespace(id=user_id)
        self.answers = []
        self.bot = SimpleNamespace()

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


@pytest.mark.asyncio
async def test_trusted_auto_approve_message_shows_fractional_reward(monkeypatch):
    import app.user_handlers as user_handlers

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(user_handlers, "async_session", Session)
    import app.services as services

    monkeypatch.setattr(user_handlers, "save_video", AsyncMock(return_value=(SimpleNamespace(id=1), False)))
    monkeypatch.setattr(user_handlers, "_update_quest_progress", AsyncMock())
    monkeypatch.setattr(user_handlers, "schedule_mod_notification", AsyncMock())
    monkeypatch.setattr(user_handlers, "_level_up_check", AsyncMock())
    monkeypatch.setattr(user_handlers, "get_xp_multiplier", AsyncMock(return_value=1.0))
    monkeypatch.setattr(services, "auto_approve_if_trusted", AsyncMock(return_value=(True, Decimal("0.50"))))

    async with Session() as session:
        user = User(telegram_id=9801, balance=Decimal("0.00"), nickname_set=True, agreed_to_rules=True, display_name="Trusted")
        session.add(user)
        await session.commit()

    message = DummyMessage_auto_approve_message_format(9801)
    await user_handlers.handle_video_upload(message)

    assert message.answers
    assert "+0.50 монет" in message.answers[-1][0]

    await engine.dispose()


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_db_fix_creates_lottery_bets.py
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_fix_database_creates_lottery_bets_table(monkeypatch):
    import app.utils.db_fix as db_fix

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    monkeypatch.setattr(db_fix, "engine", engine)

    await db_fix.fix_database()

    async with engine.begin() as conn:
        tables = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())

    assert "lottery_bets" in tables
    assert "katya_messages" in tables

    await engine.dispose()


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_event_badges.py
# ══════════════════════════════════════════════════════════════

def test_best_event_badge_filters_by_target_type():
    events = [
        SimpleNamespace(name="CoinsOnly", discount_percent=30, applies_vip=False, applies_coins=True),
        SimpleNamespace(name="VipOnly", discount_percent=20, applies_vip=True, applies_coins=False),
    ]

    vip_badge = _best_event_badge(events, "vip")
    coins_badge = _best_event_badge(events, "coins")

    assert "VipOnly" in vip_badge
    assert "CoinsOnly" not in vip_badge
    assert "CoinsOnly" in coins_badge
    assert "VipOnly" not in coins_badge


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_games_menu.py
# ══════════════════════════════════════════════════════════════

class DummyState_games_menu:
    async def clear(self):
        return None


class DummyMessage_games_menu:
    def __init__(self, user_id):
        self.from_user = SimpleNamespace(id=user_id)
        self.answers = []

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


@pytest.mark.asyncio
async def test_games_menu_is_not_blocked_by_legacy_game_session(monkeypatch):
    import app.user_handlers as user_handlers

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(user_handlers, "async_session", Session)
    monkeypatch.setattr(user_handlers, "require_nickname", lambda *args, **kwargs: __import__('asyncio').sleep(0, result=True))

    async with Session() as session:
        user = User(telegram_id=9001, balance=Decimal("0.00"), nickname_set=True, display_name="Player")
        session.add(user)
        await session.commit()

    message = DummyMessage_games_menu(9001)
    state = DummyState_games_menu()

    await user_handlers.btn_games(message, state)

    assert message.answers
    assert "Игровой центр" in message.answers[0][0]

    await engine.dispose()


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_lottery_menu_timezone.py
# ══════════════════════════════════════════════════════════════

class DummyMessage_lottery_menu_timezone:
    def __init__(self):
        self.answers = []
        self.from_user = SimpleNamespace(id=999999)  # simulate bot/non-user sender

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


@pytest.mark.asyncio
async def test_lottery_menu_uses_explicit_telegram_user_id_for_timezone(monkeypatch):
    import app.user_handlers as user_handlers

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(user_handlers, "async_session", Session)

    async with Session() as session:
        user = User(
            telegram_id=9601,
            balance=Decimal("0.00"),
            nickname_set=True,
            display_name="TimezoneUser",
            timezone="Europe/Moscow",
        )
        session.add(user)
        await session.commit()

    message = DummyMessage_lottery_menu_timezone()
    await user_handlers._send_lottery_menu(message, 9601)

    assert message.answers
    text = message.answers[0][0]
    assert "по твоему времени" in text or "МСК" in text

    await engine.dispose()


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_lottery_multi_buy.py
# ══════════════════════════════════════════════════════════════

def build_init_data_lottery_multi_buy(bot_token: str, user_id: int) -> str:
    payload = {
        "auth_date": str(int(datetime.now(timezone.utc).timestamp())),
        "query_id": "AAEAAAE",
        "user": json.dumps({"id": user_id, "first_name": "Buyer"}, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(payload.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    payload["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(payload)


class DummyRequest_lottery_multi_buy:
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

    init_data = build_init_data_lottery_multi_buy(bot_token, 9902)
    response = await main.api_lottery_buy(
        DummyRequest_lottery_multi_buy({"quantity": 4}, headers={"X-Telegram-Init-Data": init_data})
    )
    payload = json.loads(response.text)

    assert payload["ok"] is True
    assert payload["quantity"] == 4
    assert payload["balance"] == 80.0

    await engine.dispose()


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_lottery_schedule.py
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_lottery_window_is_daily_at_20_msk_before_draw():
    # 2026-07-05 15:00 UTC == 18:00 MSK, same-day draw should be at 20:00 MSK.
    key, start_utc, draw_start_utc, draw_end_utc = await _get_lottery_window(None, datetime(2026, 7, 5, 15, 0, 0))

    assert key == "lottery_20260705"
    assert draw_start_utc == datetime(2026, 7, 5, 17, 0, 0)  # 20:00 MSK
    assert draw_end_utc == datetime(2026, 7, 5, 17, 1, 30)  # 6 balls * 15 sec
    assert start_utc == datetime(2026, 7, 4, 17, 1, 30)


@pytest.mark.asyncio
async def test_lottery_window_rolls_to_next_day_after_draw_end():
    # 2026-07-05 17:05 UTC == 20:05 MSK, draw already ended (20:01:30 MSK).
    key, start_utc, draw_start_utc, draw_end_utc = await _get_lottery_window(None, datetime(2026, 7, 5, 17, 5, 0))

    assert key == "lottery_20260706"
    assert draw_start_utc == datetime(2026, 7, 6, 17, 0, 0)
    assert draw_end_utc == datetime(2026, 7, 6, 17, 1, 30)
    assert start_utc == datetime(2026, 7, 5, 17, 1, 30)


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_lottery_settlement.py
# ══════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_main_api_bets.py
# ══════════════════════════════════════════════════════════════

def build_init_data_main_api_bets(bot_token: str, user_id: int) -> str:
    payload = {
        "auth_date": str(int(datetime.now(timezone.utc).timestamp())),
        "query_id": "AAEAAAE",
        "user": json.dumps({"id": user_id, "first_name": "BetUser"}, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(payload.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    payload["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(payload)


class DummyRequest_main_api_bets:
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

    init_data = build_init_data_main_api_bets(bot_token, 7001)
    response = await app.main.api_lottery_place_bet(
        DummyRequest_main_api_bets({"bet_type": "first_odd"}, headers={"X-Telegram-Init-Data": init_data})
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


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_main_startup.py
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_on_startup_only_runs_initialization_steps_for_sqlite():
    import app.main as main

    app = {"bot": object()}

    with (
        patch("app.config.DATABASE_URL", "sqlite+aiosqlite:///:memory:"),
        patch.object(main, "init_db", AsyncMock()) as init_db,
        patch("app.utils.db_fix.fix_database", AsyncMock()) as fix_database,
        patch.object(main, "_notify_admins_started", AsyncMock()) as notify_admins,
        patch("app.ai_assistant.load_sticker_set", AsyncMock()) as load_sticker_set,
        patch.object(main.web, "AppRunner") as app_runner_cls,
        patch.object(main.asyncio, "create_task") as create_task,
    ):
        await main.on_startup(app)

    init_db.assert_awaited_once()
    fix_database.assert_awaited_once()
    notify_admins.assert_awaited_once_with(app["bot"])
    load_sticker_set.assert_awaited_once_with(app["bot"])
    app_runner_cls.assert_not_called()
    create_task.assert_not_called()


@pytest.mark.asyncio
async def test_on_startup_uses_alembic_for_postgres_without_init_db():
    import app.main as main

    app = {"bot": object()}

    with (
        patch("app.config.DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/db"),
        patch.object(main, "init_db", AsyncMock()) as init_db,
        patch("app.utils.db_fix.fix_database", AsyncMock()) as fix_database,
        patch.object(main, "_notify_admins_started", AsyncMock()) as notify_admins,
        patch("app.ai_assistant.load_sticker_set", AsyncMock()) as load_sticker_set,
        patch.object(main.asyncio, "to_thread", AsyncMock()) as to_thread,
    ):
        await main.on_startup(app)

    init_db.assert_not_awaited()
    to_thread.assert_awaited_once()
    fix_database.assert_awaited_once()
    notify_admins.assert_awaited_once_with(app["bot"])
    load_sticker_set.assert_awaited_once_with(app["bot"])


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_main_webapp_auth.py
# ══════════════════════════════════════════════════════════════

def build_init_data_main_webapp_auth(bot_token: str, user_id: int) -> str:
    payload = {
        "auth_date": str(int(datetime.now(timezone.utc).timestamp())),
        "query_id": "AAEAAAE",
        "user": json.dumps({"id": user_id, "first_name": "Test"}, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(payload.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    payload["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(payload)


class DummyRequest_main_webapp_auth:
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

    init_data = build_init_data_main_webapp_auth(bot_token, 1111)
    assert main._validate_telegram_webapp_init_data(init_data) == 1111
    assert main._validate_telegram_webapp_init_data(init_data + "tamper") is None

    unauthorized = await main.api_user_balance(DummyRequest_main_webapp_auth())
    assert unauthorized.status == 401

    # Even if attacker spoofs another user_id in query/body, endpoint must trust initData only.
    authorized = await main.api_user_balance(
        DummyRequest_main_webapp_auth(headers={"X-Telegram-Init-Data": init_data}, query={"user_id": "2222"})
    )
    data = json.loads(authorized.text)
    assert data["ok"] is True
    assert data["balance"] == 55.0

    await engine.dispose()


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_messaging_and_balance_log.py
# ══════════════════════════════════════════════════════════════

class DummySession:
    def __init__(self):
        self.items = []

    def add(self, item):
        self.items.append(item)


@pytest.mark.asyncio
async def test_log_balance_change_only_logs_without_mutating_balance():
    user = User(id=1, telegram_id=123, balance=Decimal("100.00"))
    session = DummySession()

    await log_balance_change(session, user, Decimal("25.00"), "test_source")

    assert user.balance == Decimal("100.00")
    assert len(session.items) == 1
    log = session.items[0]
    assert log.balance_before == Decimal("100.00")
    assert log.balance_after == Decimal("125.00")
    assert log.amount == Decimal("25.00")


def test_format_time_for_user_includes_local_and_msk_when_timezone_known():
    target = datetime.now(timezone.utc) + timedelta(hours=3)
    text = format_time_for_user(target, "Europe/Moscow")

    assert "через" in text
    assert "по твоему времени" in text
    assert "МСК" in text


def test_format_time_for_user_falls_back_to_msk_only():
    target = datetime.now(timezone.utc) + timedelta(minutes=45)
    text = format_time_for_user(target)

    assert "через" in text
    assert "МСК" in text


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_nickname_validation.py
# ══════════════════════════════════════════════════════════════

class _FakeUser:
    def __init__(self, display_name, telegram_id=1, nickname_set=True):
        self.display_name = display_name
        self.telegram_id = telegram_id
        self.nickname_set = nickname_set


def test_min_length_is_at_least_4():
    assert NICKNAME_MIN_LENGTH >= 4


def test_placeholder_user_id_patterns():
    tid = 8809168513
    assert is_placeholder_nickname(f"User {tid}", tid)
    assert is_placeholder_nickname(f"User{tid}", tid)
    assert is_placeholder_nickname(f"User#{tid}", tid)
    assert is_placeholder_nickname(f"User_{tid}", tid)
    assert is_placeholder_nickname(f"user-{tid}", tid)
    assert is_placeholder_nickname(str(tid), tid)
    assert is_placeholder_nickname(None)
    assert is_placeholder_nickname("")
    assert not is_placeholder_nickname("Полина", tid)
    assert not is_placeholder_nickname("Fast", tid)
    assert not is_placeholder_nickname("Mixaka86565", tid)


def test_validate_rejects_dots_questions_short_and_placeholder():
    assert validate_nickname_format(".")[0] is False
    assert validate_nickname_format("?")[0] is False
    assert validate_nickname_format("....")[0] is False
    assert validate_nickname_format("ab")[0] is False
    assert validate_nickname_format("abc")[0] is False
    assert validate_nickname_format("User1")[0] is False
    assert validate_nickname_format("1234")[0] is False
    assert validate_nickname_format("aaaa")[0] is False


def test_validate_accepts_normal_nicks():
    assert validate_nickname_format("Полина")[0] is True
    assert validate_nickname_format("Fast")[0] is True
    assert validate_nickname_format("wllmLvt")[0] is True
    assert validate_nickname_format("Cool_Nick")[0] is True
    assert validate_nickname_format("a_b1")[0] is True


def test_has_valid_nickname_forces_placeholder_users():
    bad = _FakeUser("User 8809168513", telegram_id=8809168513, nickname_set=True)
    assert has_valid_nickname(bad) is False

    good = _FakeUser("Полина", telegram_id=1, nickname_set=True)
    assert has_valid_nickname(good) is True

    unset = _FakeUser(None, telegram_id=1, nickname_set=False)
    assert has_valid_nickname(unset) is False

    short = _FakeUser("abc", telegram_id=1, nickname_set=True)
    assert has_valid_nickname(short) is False


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_offer_moderation.py
# ══════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_referral_reward_content_type.py
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_referral_reward_requires_video_views_not_photo_views():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        inviter = User(telegram_id=9301, balance=Decimal("0.00"), nickname_set=True, display_name="Inviter")
        referred = User(telegram_id=9302, balance=Decimal("0.00"), nickname_set=True, display_name="Referred")
        session.add_all([inviter, referred])
        await session.flush()
        referred.referred_by_user_id = inviter.id

        for idx in range(5):
            photo = Video(
                uploader_user_id=inviter.id,
                content_type="photo",
                telegram_file_id=f"photo_{idx}",
                telegram_file_unique_id=f"photo_unique_{idx}",
                status="approved",
            )
            session.add(photo)
            await session.flush()
            session.add(VideoView(user_id=referred.id, video_id=photo.id))
        await session.commit()

        await process_referral_reward(session, inviter.id)
        await session.refresh(inviter)
        assert inviter.balance == Decimal("0.00")

        videos = []
        for idx in range(5):
            video = Video(
                uploader_user_id=inviter.id,
                content_type="video",
                telegram_file_id=f"video_{idx}",
                telegram_file_unique_id=f"video_unique_{idx}",
                status="approved",
            )
            session.add(video)
            await session.flush()
            videos.append(video)
            session.add(VideoView(user_id=referred.id, video_id=video.id))
        await session.commit()

        await process_referral_reward(session, inviter.id)
        await session.refresh(inviter)
        reward_logs = (await session.execute(
            select(func.count(BalanceLog.id)).where(BalanceLog.source == "referral_reward")
        )).scalar_one()

        assert inviter.balance > Decimal("0.00")
        assert reward_logs == 1

    await engine.dispose()


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_referral_trigger_on_watch.py
# ══════════════════════════════════════════════════════════════

class DummyMessage_referral_trigger_on_watch:
    def __init__(self):
        self.video_answers = []
        self.answers = []

    async def answer_video(self, *args, **kwargs):
        self.video_answers.append((args, kwargs))

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


class DummyCallback_referral_trigger_on_watch:
    def __init__(self, user_id):
        self.from_user = SimpleNamespace(id=user_id)
        self.message = DummyMessage_referral_trigger_on_watch()

    async def answer(self, *args, **kwargs):
        return None


@pytest.mark.asyncio
async def test_watch_video_triggers_referral_reward_check_after_successful_send(monkeypatch):
    import app.user_handlers as user_handlers

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(user_handlers, "async_session", Session)
    referral_mock = AsyncMock()
    monkeypatch.setattr(user_handlers, "process_referral_reward", referral_mock)

    async with Session() as session:
        inviter = User(telegram_id=9101, balance=Decimal("0.00"), nickname_set=True, display_name="Inviter")
        viewer = User(
            telegram_id=9102,
            balance=Decimal("100.00"),
            nickname_set=True,
            display_name="Viewer",
            referred_by_user_id=1,
        )
        uploader = User(telegram_id=9103, balance=Decimal("0.00"), nickname_set=True, display_name="Uploader")
        session.add_all([inviter, viewer, uploader])
        await session.flush()
        viewer.referred_by_user_id = inviter.id

        video = Video(
            uploader_user_id=uploader.id,
            content_type="video",
            telegram_file_id="file_1",
            telegram_file_unique_id="uniq_1",
            status="approved",
        )
        session.add(video)
        await session.commit()

    callback = DummyCallback_referral_trigger_on_watch(9102)
    await user_handlers.watch_video_content(callback)

    referral_mock.assert_awaited_once()
    assert callback.message.video_answers

    await engine.dispose()


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_release_notes.py
# ══════════════════════════════════════════════════════════════

def test_release_notes_reads_recent_items_from_changelog():
    items = get_recent_changelog_items(limit=3)
    assert items
    assert all(item.strip() for item in items)
    assert all(not item.startswith("* ") for item in items)


def test_release_notes_text_contains_current_version_and_changelog_hint():
    text = build_version_text(admin=True, limit=2)
    assert CURRENT_VERSION in text
    assert "CHANGELOG.md" in text
    assert "Последние изменения" in text


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_reports_pdf.py
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_build_user_report_pdf_smoke(monkeypatch):
    import app.reports as reports

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(reports, "async_session", Session)

    async with Session() as session:
        user = User(telegram_id=1111001, balance=Decimal("123.45"), nickname_set=True, display_name="PdfUser")
        session.add(user)
        await session.commit()

    pdf_path, filename = await reports.build_user_report_pdf(1111001)
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
    assert filename.endswith(".pdf")
    pdf_path.unlink(missing_ok=True)
    await engine.dispose()


@pytest.mark.asyncio
async def test_build_bot_report_pdf_smoke(monkeypatch):
    import app.reports as reports

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(reports, "async_session", Session)

    async with Session() as session:
        user = User(telegram_id=1111002, balance=Decimal("50.00"), nickname_set=True, display_name="BotUser")
        session.add(user)
        await session.commit()

    pdf_path, filename = await reports.build_bot_report_pdf()
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
    assert filename.endswith(".pdf")
    pdf_path.unlink(missing_ok=True)
    await engine.dispose()


@pytest.mark.asyncio
async def test_build_all_users_report_pdf_smoke(monkeypatch):
    import app.reports as reports

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(reports, "async_session", Session)

    async with Session() as session:
        session.add_all([
            User(telegram_id=1111003, balance=Decimal("10.00"), nickname_set=True, display_name="UserA"),
            User(telegram_id=1111004, balance=Decimal("20.00"), nickname_set=True, display_name="UserB"),
        ])
        await session.commit()

    pdf_path, filename = await reports.build_all_users_report_pdf()
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
    assert filename.endswith(".pdf")
    pdf_path.unlink(missing_ok=True)
    await engine.dispose()


@pytest.mark.asyncio
async def test_collect_user_report_data_adds_profile_and_payment_metrics(monkeypatch):
    import app.reports as reports

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(reports, "async_session", Session)

    async with Session() as session:
        user = User(telegram_id=2222001, balance=Decimal("200.00"), nickname_set=True, display_name="MetricsUser")
        session.add(user)
        await session.flush()
        session.add(Payment(user_id=user.id, payload="pay_user_report", stars_amount=30, coins_amount=Decimal("300.00"), status="paid"))
        session.add(BalanceLog(user_id=user.id, amount=Decimal("50.00"), balance_before=Decimal("150.00"), balance_after=Decimal("200.00"), source="purchase"))
        session.add(UserActionLog(user_id=user.id, action="open_menu", details="test"))
        await session.commit()

    data = await reports.collect_user_report_data(2222001)
    assert data["payments"]["count"] == 1
    assert data["payments"]["stars_total"] == 30
    assert data["payments"]["types"]
    assert data["profile"]["active_days_30"] >= 1
    assert data["content"]["efficiency"]["uploads_total"] >= 0
    assert data["comparison"]["rows"]
    assert data["comparison"]["population"] >= 1
    assert data["insights"]["purchase_comment"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_collect_bot_report_data_adds_conversion_metrics(monkeypatch):
    import app.reports as reports

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(reports, "async_session", Session)

    now = utc_now()
    async with Session() as session:
        user1 = User(
            telegram_id=3333001,
            balance=Decimal("100.00"),
            nickname_set=True,
            display_name="Buyer",
            agreed_to_rules=True,
            created_at=now - timedelta(days=10),
        )
        session.add(user1)
        await session.flush()
        user2 = User(
            telegram_id=3333002,
            balance=Decimal("0.00"),
            nickname_set=True,
            display_name="Referral",
            agreed_to_rules=True,
            referred_by_user_id=user1.id,
            created_at=now - timedelta(days=10),
        )
        session.add(user2)
        await session.flush()

        video = Video(
            uploader_user_id=user1.id,
            telegram_file_id="file1",
            telegram_file_unique_id="uniq1",
            status="approved",
            created_at=now - timedelta(days=9),
        )
        session.add(video)
        await session.flush()
        session.add(VideoView(user_id=user1.id, video_id=video.id, created_at=now - timedelta(days=9), watched_at=now - timedelta(days=9)))

        lottery_round = LotteryRound(
            week_key="lottery_20260701",
            starts_at=now - timedelta(days=9),
            draw_starts_at=now - timedelta(days=9),
            draw_ends_at=now - timedelta(days=9) + timedelta(minutes=2),
        )
        session.add(lottery_round)
        await session.flush()
        session.add(LotteryTicket(round_id=lottery_round.id, user_id=user1.id, numbers="1,2,3,4,5,6", created_at=now - timedelta(days=8)))

        session.add(Payment(user_id=user1.id, payload="pay_bot_report", stars_amount=40, coins_amount=Decimal("400.00"), status="paid", created_at=now - timedelta(days=9)))
        session.add(UserActionLog(user_id=user1.id, action="returned_d1", details="test", created_at=now - timedelta(days=9)))
        session.add(UserActionLog(user_id=user1.id, action="returned_d7", details="test", created_at=now - timedelta(days=3)))
        await session.commit()

    data = await reports.collect_bot_report_data()
    assert data["summary"]["payer_count"] == 1
    assert data["summary"]["payment_conversion_pct"] == pytest.approx(50.0)
    assert data["economy"]["payment_type_counts"]
    assert data["payments_analytics"]["rows"]
    assert data["retention"]["referred_total"] == 1
    assert len(data["retention"]["active_users_daily_30"]) == 30
    assert data["segments"]["rows"]
    assert data["leaders"]["payments"]
    assert data["churn"]["rows"]
    assert data["activity_heatmap"]["hours"][0] == "00"
    assert len(data["activity_heatmap"]["matrix"]) == 7
    assert data["funnel"]["rows"][0]["label"] == "Регистрация"
    assert data["funnel"]["rows"][3]["count"] == 1
    assert data["cohorts"]["d1"]["eligible"] >= 2
    assert data["cohorts"]["d1"]["retained"] >= 1
    await engine.dispose()


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_rules_and_reject.py
# ══════════════════════════════════════════════════════════════

def test_rules_text_contains_key_sections():
    full = FULL_RULES_TEXT.lower()
    short = SHORT_RULES_TEXT.lower()
    assert "шок-контент" in short
    assert "чётко видно" in short
    assert "умников найдём и оштрафуем" in short
    assert "некрофилия" in full
    assert "зоофилия" in full
    assert "копрофилия" in full
    assert "эмодзи" in short
    assert "мультиакки" in full
    assert "каналы, группы, чаты и ботов" in full


@pytest.mark.asyncio
async def test_reject_video_stores_reason_and_admin_comment():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        user = User(telegram_id=991001, balance=Decimal("0.00"), nickname_set=True, display_name="Uploader")
        session.add(user)
        await session.flush()
        video = Video(
            uploader_user_id=user.id,
            telegram_file_id="vid1",
            telegram_file_unique_id="uniq_vid1",
            status="pending",
        )
        session.add(video)
        await session.commit()

        updated = await reject_video(session, video.id, "Не по теме", "Нужно показать контент открыто, без эмодзи и рук")
        assert updated is not None
        assert updated.status == "rejected"
        assert updated.rejection_reason == "Не по теме. Комментарий модератора: Нужно показать контент открыто, без эмодзи и рук"

    await engine.dispose()


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_services.py
# ══════════════════════════════════════════════════════════════

def test_to_decimal():
    assert to_decimal("10.5") == Decimal("10.5")
    assert to_decimal(5) == Decimal("5")

def test_round_coin():
    val = Decimal("10.556")
    assert round_coin(val) == Decimal("10.55")
    
    val2 = Decimal("10.5")
    assert round_coin(val2) == Decimal("10.50")


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_stars_discount_prices.py
# ══════════════════════════════════════════════════════════════

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
        assert vip_price == 338
        assert packs["pack_50"]["stars"] == 113
        assert packs["pack_100"]["stars"] == 225

    await engine.dispose()


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_trusted_auto_approve_reward.py
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_trusted_auto_approve_uses_runtime_reward_and_multiplier():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        admin = User(telegram_id=9701, balance=Decimal("0.00"), is_admin=True)
        uploader = User(telegram_id=9702, balance=Decimal("0.00"), nickname_set=True, display_name="TrustedUploader")
        session.add_all([admin, uploader])
        await session.flush()

        session.add(TrustedUploader(admin_user_id=admin.id, trusted_user_id=uploader.id))
        session.add(BotSetting(key="auto_moderation_enabled", value="true"))
        session.add(BotSetting(key="upload_reward", value="55"))
        session.add(UserPerk(
            user_id=uploader.id,
            perk_type="coin_multiplier",
            active_until=utc_now() + timedelta(days=7),
            is_active=True,
        ))

        video = Video(
            uploader_user_id=uploader.id,
            content_type="video",
            telegram_file_id="file_1",
            telegram_file_unique_id="uniq_1",
            status="pending",
        )
        session.add(video)
        await session.commit()

        approved, reward = await auto_approve_if_trusted(session, video.id, uploader.id)
        await session.refresh(uploader)
        await session.refresh(video)

        assert approved is True
        assert reward == Decimal("82.50")
        assert uploader.balance == Decimal("82.50")
        assert video.status == "approved"

    await engine.dispose()


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_user_creation_and_referrals.py
# ══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_new_user_gets_single_starting_balance_not_double_counted():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
            user, created = await get_or_create_user(session, telegram_id=5001, username="newbie")
            assert created is True
            assert user.balance == Decimal("150.00")

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
        assert referred.balance == Decimal("160.00")

        await session.refresh(inviter)
        assert inviter.referrals_count == 1

    await engine.dispose()


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_user_offer_pricing.py
# ══════════════════════════════════════════════════════════════

def test_offer_stars_price_rounds_up_instead_of_undercharging():
    assert _calc_offer_stars_price(Decimal("50")) == 2
    assert _calc_offer_stars_price(Decimal("55")) == 2
    assert _calc_offer_stars_price(Decimal("101")) == 4


def test_offer_stars_price_applies_user_discount_after_round_up():
    assert _calc_offer_stars_price(Decimal("55"), 0.25) == 2
    assert _calc_offer_stars_price(Decimal("101"), 0.25) == 3


# ══════════════════════════════════════════════════════════════
#  был файл: app/tests/test_watch_error_exit.py
# ══════════════════════════════════════════════════════════════

class DummyMessage_watch_error_exit:
    def __init__(self, *, video_raises=False, photo_raises=False):
        self.video_answers = []
        self.photo_answers = []
        self.answers = []
        self._video_raises = video_raises
        self._photo_raises = photo_raises

    async def answer_video(self, *args, **kwargs):
        if self._video_raises:
            raise RuntimeError("Bad Request: failed to get HTTP URL")
        self.video_answers.append((args, kwargs))

    async def answer_photo(self, *args, **kwargs):
        if self._photo_raises:
            raise RuntimeError("Bad Request: failed to get HTTP URL")
        self.photo_answers.append((args, kwargs))

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


class DummyCallback_watch_error_exit:
    def __init__(self, user_id, *, video_raises=False, photo_raises=False):
        self.from_user = SimpleNamespace(id=user_id)
        self.message = DummyMessage_watch_error_exit(video_raises=video_raises, photo_raises=photo_raises)

    async def answer(self, *args, **kwargs):
        return None


def _markup_callbacks(message):
    """Собирает все callback_data из последнего ответа (если есть клавиатура)."""
    cbs = set()
    if not message.answers:
        return cbs
    _text, kwargs = message.answers[-1]
    markup = kwargs.get("reply_markup")
    if markup is None:
        return cbs
    for row in markup.inline_keyboard:
        for btn in row:
            cbs.add(btn.callback_data)
    return cbs


def _last_text(message):
    assert message.answers, "Ожидалось текстовое сообщение об ошибке"
    return message.answers[-1][0]


async def _make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, Session


# ---------------------------------------------------------------------------
# ВИДЕО
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_watch_video_no_content_shows_clear_message_with_exit(monkeypatch):
    """Нет доступных видео → понятный текст + кнопки продолжения (не тупик)."""
    import app.user_handlers as user_handlers

    engine, Session = await _make_session()
    monkeypatch.setattr(user_handlers, "async_session", Session)

    async with Session() as session:
        viewer = User(
            telegram_id=2001,
            balance=Decimal("1000.00"),
            nickname_set=True,
            display_name="Viewer",
        )
        session.add(viewer)
        await session.commit()

    callback = DummyCallback_watch_error_exit(2001)
    await user_handlers.watch_video_content(callback)

    text = _last_text(callback.message)
    assert "Нет доступных видео" not in text, "Не должно быть сырой старой фразы без контекста"
    assert "нет новых видео" in text.lower()
    # Главный признак исправления — есть выход:
    cbs = _markup_callbacks(callback.message)
    assert "watch_next" in cbs, "Должна быть кнопка «Смотреть дальше»"
    assert "watch_photo_content" in cbs, "Должна быть кнопка перехода к фото"

    await engine.dispose()


@pytest.mark.asyncio
async def test_watch_video_broken_video_does_not_leak_raw_error_and_gives_exit(monkeypatch):
    """Видео не отправляется → пользователь НЕ видит сырую ошибку, но может продолжить."""
    import app.user_handlers as user_handlers

    engine, Session = await _make_session()
    monkeypatch.setattr(user_handlers, "async_session", Session)

    async with Session() as session:
        uploader = User(telegram_id=2002, balance=Decimal("0.00"),
                        nickname_set=True, display_name="Uploader")
        viewer = User(telegram_id=2003, balance=Decimal("1000.00"),
                      nickname_set=True, display_name="Viewer")
        session.add_all([uploader, viewer])
        await session.flush()
        video = Video(
            uploader_user_id=uploader.id,
            content_type="video",
            telegram_file_id="file_broken",
            telegram_file_unique_id="uniq_broken",
            status="approved",
        )
        session.add(video)
        await session.commit()

    callback = DummyCallback_watch_error_exit(2003, video_raises=True)
    await user_handlers.watch_video_content(callback)

    text = _last_text(callback.message)
    # Сырая телеграм-ошибка НЕ должна попасть пользователю:
    assert "Bad Request" not in text
    assert "HTTP URL" not in text
    assert "не удалось показать" in text.lower()
    # ...зато есть выход:
    cbs = _markup_callbacks(callback.message)
    assert "watch_next" in cbs
    # И деньги за неотправленное видео вернули:
    async with Session() as session:
        from sqlalchemy import select
        views = (await session.execute(
            select(VideoView).where(VideoView.user_id == 2)
        )).scalars().all()
        assert views == [], "Просмотр неотправленного видео не должен сохраниться"

    await engine.dispose()


# ---------------------------------------------------------------------------
# ФОТО
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_watch_photo_no_content_shows_clear_message_with_exit(monkeypatch):
    """Нет доступных фото → понятный текст + кнопки продолжения."""
    import app.user_handlers as user_handlers

    engine, Session = await _make_session()
    monkeypatch.setattr(user_handlers, "async_session", Session)

    async with Session() as session:
        viewer = User(
            telegram_id=2004,
            balance=Decimal("1000.00"),
            nickname_set=True,
            display_name="Viewer",
        )
        session.add(viewer)
        await session.commit()

    callback = DummyCallback_watch_error_exit(2004)
    await user_handlers.watch_photo_content(callback)

    text = _last_text(callback.message)
    assert "нет новых фото" in text.lower()
    cbs = _markup_callbacks(callback.message)
    assert "watch_next_photo" in cbs, "Должна быть кнопка «Смотреть дальше»"
    assert "watch_video_content" in cbs, "Должна быть кнопка перехода к видео"

    await engine.dispose()


@pytest.mark.asyncio
async def test_watch_photo_broken_photo_does_not_leak_raw_error_and_gives_exit(monkeypatch):
    """Фото не отправляется → без сырой ошибки, с кнопкой продолжения."""
    import app.user_handlers as user_handlers

    engine, Session = await _make_session()
    monkeypatch.setattr(user_handlers, "async_session", Session)

    async with Session() as session:
        uploader = User(telegram_id=2005, balance=Decimal("0.00"),
                        nickname_set=True, display_name="Uploader")
        viewer = User(telegram_id=2006, balance=Decimal("1000.00"),
                      nickname_set=True, display_name="Viewer")
        session.add_all([uploader, viewer])
        await session.flush()
        photo = Video(
            uploader_user_id=uploader.id,
            content_type="photo",
            telegram_file_id="photo_broken",
            telegram_file_unique_id="uniq_photo_broken",
            status="approved",
        )
        session.add(photo)
        await session.commit()

    callback = DummyCallback_watch_error_exit(2006, photo_raises=True)
    await user_handlers.watch_photo_content(callback)

    text = _last_text(callback.message)
    assert "Bad Request" not in text
    assert "HTTP URL" not in text
    assert "не удалось показать" in text.lower()
    cbs = _markup_callbacks(callback.message)
    assert "watch_next_photo" in cbs

    await engine.dispose()


@pytest.mark.asyncio
async def test_watch_photo_daily_limit_shows_exit_to_video(monkeypatch):
    """Дневной лимит фото исчерпан → есть выход к видео (не тупик)."""
    import app.user_handlers as user_handlers

    engine, Session = await _make_session()
    monkeypatch.setattr(user_handlers, "async_session", Session)

    async with Session() as session:
        viewer = User(
            telegram_id=2007,
            balance=Decimal("1000.00"),
            nickname_set=True,
            display_name="Viewer",
            # не VIP → попадает под дневной лимит
        )
        session.add(viewer)
        await session.flush()

        # Создаём достаточно фото-просмотров, чтобы лимит был исчерпан.
        uploader = User(telegram_id=2008, balance=Decimal("0.00"),
                        nickname_set=True, display_name="Uploader")
        session.add(uploader)
        await session.flush()
        for i in range(user_handlers.DAILY_PHOTO_LIMIT + 1):
            photo = Video(
                uploader_user_id=uploader.id,
                content_type="photo",
                telegram_file_id=f"file_{i}",
                telegram_file_unique_id=f"uniq_{i}",
                status="approved",
            )
            session.add(photo)
            await session.flush()
            session.add(VideoView(user_id=viewer.id, video_id=photo.id))
        await session.commit()

    callback = DummyCallback_watch_error_exit(2007)
    await user_handlers.watch_photo_content(callback)

    text = _last_text(callback.message)
    assert "лимит" in text.lower()
    cbs = _markup_callbacks(callback.message)
    assert "watch_video_content" in cbs, "Из лимита фото должен быть выход к видео"

    await engine.dispose()


# ══════════════════════════════════════════════════════════════
#  ПОЛНЫЕ СЦЕНАРИИ-СЬЮТЫ (портированы из старых отдельных скриптов)
#  Каждый сьют начинается с reset_bot_db() — полная очистка таблиц,
#  чтобы шаги сьюта видели чистую БД, а соседние тесты не мешали.
# ══════════════════════════════════════════════════════════════
from unittest.mock import AsyncMock as _AsyncMock


async def reset_bot_db():
    """Полная очистка всех таблиц бота (для изоляции сценарных сьютов)."""
    from app.db import engine
    from app.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for t in reversed(Base.metadata.sorted_tables):
            await conn.execute(t.delete())


def _mk_simple_bot(sent_list):
    """Минимальный фейк бота: send_message складывает в sent_list."""
    async def _fake_send(tid, text, **kw):
        sent_list.append((tid, text))
    return SimpleNamespace(send_message=_fake_send)


# ── Сьют: КЕЙСЫ Mini App API (бывший test_cases_api.py) ──────────────
async def test_suite_cases_miniapp_api(monkeypatch):
    import app.main as m
    from app.db import async_session
    from app.models import User, LootboxOpen, BalanceLog
    from aiohttp import web
    from aiohttp.test_utils import TestServer, TestClient
    import time, urllib.parse

    monkeypatch.setattr(m, "BOT_TOKEN", "testtoken123")
    await reset_bot_db()

    TG_ID = 123456789

    def make_init_data() -> str:
        user_json = json.dumps({"id": TG_ID, "first_name": "Test", "username": "tester"},
                               separators=(",", ":"))
        data = {"auth_date": str(int(time.time())), "query_id": "AATEST", "user": user_json}
        dcs = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret = hmac.new(b"WebAppData", b"testtoken123", hashlib.sha256).digest()
        hsh = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
        return urllib.parse.urlencode({**data, "hash": hsh})

    async with async_session() as s:
        s.add(User(telegram_id=TG_ID, username="tester", first_name="Test",
                   balance=Decimal("3877.00"), level=5))
        await s.commit()

    app = web.Application()
    app.router.add_get("/cases", m.cases_page_handler)
    app.router.add_get("/api/cases/state", m.api_cases_state)
    app.router.add_post("/api/cases/open", m.api_cases_open)
    client = TestClient(TestServer(app))
    await client.start_server()
    hdrs = {"X-Telegram-Init-Data": make_init_data(), "Content-Type": "application/json"}

    # 0) страница отдаётся
    r = await client.get("/cases")
    assert r.status == 200, f"cases page {r.status}"

    # 1) state
    r = await client.get("/api/cases/state", headers=hdrs)
    st = await r.json()
    assert r.status == 200 and st.get("ok") and abs(st["balance"] - 3877.0) < 1e-6 and st["pity"] == 10, \
        f"state: {r.status} {st}"

    # 2) open common
    r = await client.post("/api/cases/open", headers=hdrs, json={"case_id": "common"})
    body = await r.json()
    assert r.status == 200 and body.get("ok"), f"open common: {r.status} {body}"
    assert len(body["sequence"]) == 50 and body["sequence"][45] == body["win"], "sequence/win mismatch"

    # 3) open styles
    r = await client.post("/api/cases/open", headers=hdrs, json={"case_id": "styles"})
    body3 = await r.json()
    assert r.status == 200 and body3.get("ok"), f"open styles: {r.status} {body3}"
    assert body3["sequence"][45] == body3["win"], "styles sequence/win mismatch"

    # 4) ещё 9 common -> pity-цикл
    for i in range(9):
        r = await client.post("/api/cases/open", headers=hdrs, json={"case_id": "common"})
        body = await r.json()
        assert body.get("ok"), f"open common #{i+2}: {body}"

    # 5) elite на 5 уровне -> обработанная ошибка
    r = await client.post("/api/cases/open", headers=hdrs, json={"case_id": "elite"})
    b5 = await r.json()
    assert r.status == 200 and not b5.get("ok") and "уровень" in (b5.get("error") or ""), \
        f"elite low-level: {r.status} {b5}"

    # 6) невалидный json -> 400, а не 500
    r = await client.post("/api/cases/open", headers={"X-Telegram-Init-Data": make_init_data()},
                          data=b"not-json")
    b6 = await r.json()
    assert r.status == 400 and b6.get("error") == "bad_request", f"bad json: {r.status} {b6}"

    # 7) без initData -> 401
    r = await client.get("/api/cases/state")
    assert r.status == 401, f"no-initData state: {r.status}"

    # побочные эффекты в БД
    async with async_session() as s:
        user = (await s.execute(select(User).where(User.telegram_id == TG_ID))).scalar_one()
        opens = (await s.execute(select(func.count(LootboxOpen.id)))).scalar()
        logs = (await s.execute(select(func.count(BalanceLog.id)))).scalar()
        assert opens == 10, f"expected 10 lootbox_opens rows, got {opens}"
        assert logs >= 20, "balance_logs rows missing"
        assert user.balance >= 0, "negative balance!"

    await client.close()
    print("PASS  cases MiniApp API: page/state/open x10/elite-guard/400/401 + DB side effects")


# ── Сьют: ПАК РОСТА (бывший test_growth_pack.py) ─────────────────────
async def test_suite_growth_pack():
    from app.db import async_session
    from app.models import User, Payment, VideoView, Video, UserActionLog
    from sqlalchemy import delete  # noqa: F401  (на случай расширений)
    from app.services import (
        auto_daily_return_bonus, is_starter_pack_eligible, create_payment,
        apply_successful_payment, get_current_prices, count_views_today,
        maybe_send_zalip_upsell, get_never_payer_nicknamed_targets,
        check_daily_video_upload_possible, set_setting,
    )
    from app.main import onboarding_retention_pass
    from uuid import uuid4

    await reset_bot_db()
    sent: list = []

    class FakeBot:
        @staticmethod
        async def send_message(tid, text, **kw):
            sent.append((tid, text))
        async def get_me(self):
            return SimpleNamespace(username="wseksbot")

    BOT = FakeBot()

    def mk_user(tid, **kw):
        u = User(telegram_id=tid, first_name=f"U{tid}",
                 balance=kw.pop("balance", Decimal("0")), status=kw.pop("status", "active"), **kw)
        return u

    # ---------- A. Daily return streak ----------
    async with async_session() as s:
        s.add(mk_user(101)); await s.commit()
        uid = (await s.execute(select(User.id).where(User.telegram_id == 101))).scalar_one()
    async with async_session() as s:
        u = await s.get(User, uid)
        r = await auto_daily_return_bonus(s, u)
        assert r is not None and r[1] == 1 and float(u.balance) > 0, f"streak day1: {r}"
        r2 = await auto_daily_return_bonus(s, u)
        assert r2 is None, f"streak same day dup: {r2}"
    async with async_session() as s:  # вчерашний бонус -> streak 2
        u = await s.get(User, uid)
        u.last_bonus_at = u.last_bonus_at - timedelta(days=1)
        r3 = await auto_daily_return_bonus(s, u)
        assert r3 and r3[1] == 2, f"streak day2: {r3}"
    async with async_session() as s:  # разрыв -> сброс на 1
        u = await s.get(User, uid)
        u.last_bonus_at = u.last_bonus_at - timedelta(days=4)
        r4 = await auto_daily_return_bonus(s, u)
        assert r4 and r4[1] == 1, f"streak reset: {r4}"
    async with async_session() as s:  # кап 30
        u = await s.get(User, uid)
        u.last_bonus_at = u.last_bonus_at - timedelta(days=1)
        u.bonus_streak = 30
        r5 = await auto_daily_return_bonus(s, u)
        assert r5 and r5[1] == 30, f"streak cap: {r5}"
    print("PASS  growth A: streak 1->2->reset->cap30, без дублей в один день")

    # ---------- B. Starter pack ----------
    async with async_session() as s:
        s.add(mk_user(102)); await s.commit()
        uid2 = (await s.execute(select(User.id).where(User.telegram_id == 102))).scalar_one()
    async with async_session() as s:
        u = await s.get(User, uid2)
        assert await is_starter_pack_eligible(s, u), "starter: not eligible fresh"
        _, packs, _ = await get_current_prices(s, uid2)
        sp = packs.get("starterpack")
        assert sp and sp["stars"] == 27 and sp["coins"] == 500, f"starter price: {sp}"
        pay = await create_payment(s, uid2, "starterpack")
        paym, credited = await apply_successful_payment(s, pay.payload)
        assert paym and float(credited) >= 500, f"starter apply: {credited}"
        u = await s.get(User, uid2)
        assert not await is_starter_pack_eligible(s, u), "starter: still eligible after paid"
    print("PASS  growth B: starter pack 9 Stars/500, одноразовость")

    # ---------- C. Zalip upsell ----------
    async with async_session() as s:
        s.add(mk_user(103)); await s.commit()
        uid3 = (await s.execute(select(User.id).where(User.telegram_id == 103))).scalar_one()
        up = await s.get(User, uid3)
        vids = [Video(uploader_user_id=uid2, telegram_file_id=uuid4().hex,
                      telegram_file_unique_id=uuid4().hex) for _ in range(8)]
        s.add_all(vids); await s.flush()
        for v in vids:
            s.add(VideoView(user_id=uid3, video_id=v.id, watched_at=datetime.now()))
        await s.commit()
        assert await count_views_today(s, uid3) == 8
        n0 = len(sent)
        r = await maybe_send_zalip_upsell(s, BOT, up, views_today=8)
        assert r and len(sent) == n0 + 1, f"zalip first: r={r}"
        assert "старт-пак" in sent[-1][1], "zalip text lacks starter pack"
        r2 = await maybe_send_zalip_upsell(s, BOT, up, views_today=8)
        assert not r2, "zalip duplicate same day"
        r3 = await maybe_send_zalip_upsell(s, BOT, up, views_today=9)
        assert not r3, "zalip wrong threshold"
        s.add(Payment(user_id=uid3, payload="x1", stars_amount=1, coins_amount=1, status="paid"))
        await s.commit()
        r4 = await maybe_send_zalip_upsell(s, BOT, up, views_today=8)
        assert not r4, "zalip to payer"
    print("PASS  growth C: zalip на 8 просмотрах один раз, платившим нет")

    # ---------- D. Onboarding drip + comeback ----------
    now = datetime.now()
    async with async_session() as s:
        s.add(mk_user(201, created_at=now - timedelta(hours=2, minutes=30)))
        s.add(mk_user(202, created_at=now - timedelta(hours=30)))
        u_old = mk_user(203, created_at=now - timedelta(hours=100))
        s.add(u_old); await s.flush()
        s.add(UserActionLog(user_id=u_old.id, action="watch", details="", created_at=now - timedelta(hours=70)))
        s.add(mk_user(204, created_at=now - timedelta(minutes=30)))
        s.add(mk_user(205, created_at=now - timedelta(hours=200), last_bonus_at=now))
        await s.commit()
    n0 = len(sent)
    st = await onboarding_retention_pass(BOT)
    tgts = {tid for tid, _ in sent[n0:]}
    assert st["drip"] == 2 and 201 in tgts and 202 in tgts, f"drip: {st} tgts={tgts}"
    assert st["comeback"] == 1 and 203 in tgts, f"comeback: {st} tgts={tgts}"
    async with async_session() as s:
        bal = (await s.execute(select(User.balance).where(User.telegram_id == 203))).scalar_one()
        assert float(bal) == 100.0, f"comeback balance: {bal}"
    st2 = await onboarding_retention_pass(BOT)
    assert st2["drip"] == 0 and st2["comeback"] == 0, f"retention not idempotent: {st2}"
    print("PASS  growth D: drip1+drip2 по возрасту, comeback +100, идемпотентность")

    # ---------- E. Segment ----------
    async with async_session() as s:
        s.add(mk_user(301, nickname_set=True, display_name="A1"))
        s.add(mk_user(302, nickname_set=True, display_name="B1")); await s.flush()
        pid = (await s.execute(select(User.id).where(User.telegram_id == 302))).scalar_one()
        s.add(Payment(user_id=pid, payload="seg1", stars_amount=1, coins_amount=1, status="paid"))
        s.add(mk_user(303))
        s.add(mk_user(304, nickname_set=True, display_name="C1", status="banned"))
        await s.commit()
        targets = await get_never_payer_nicknamed_targets(s)
    assert targets == [301], f"segment: {targets}"
    print("PASS  growth E: сегмент 'ник + 0 платежей' = ровно один юзер")

    # ---------- F. Video upload daily limit ----------
    async with async_session() as s:
        await set_setting(s, "daily_video_upload_limit", "2")
        s.add(mk_user(401)); await s.commit()
        uidv = (await s.execute(select(User.id).where(User.telegram_id == 401))).scalar_one()
        ok, done, lim = await check_daily_video_upload_possible(s, uidv)
        assert ok and lim == 2
        for _ in range(2):
            s.add(Video(uploader_user_id=uidv, telegram_file_id=uuid4().hex,
                        telegram_file_unique_id=uuid4().hex))
        await s.commit()
        ok2, done2, lim2 = await check_daily_video_upload_possible(s, uidv)
        assert not ok2 and done2 == 2, f"upload limit: {ok2},{done2}"
    print("PASS  growth F: дневной лимит загрузок видео (2/2)")


# ── Сьют: ХОТФИКС middleware-бонус + поиск (бывший test_hotfix_search.py) ──
async def test_suite_hotfix_middleware_and_search():
    from app.db import async_session
    from app.models import User
    from app.services import auto_daily_return_bonus, get_user, search_users_admin

    await reset_bot_db()

    async with async_session() as s:
        s.add(User(telegram_id=11, first_name="Spammer", balance=Decimal("200"), status="active", display_name="Viperrr", nickname_set=True))
        s.add(User(telegram_id=12, first_name="Poor", balance=Decimal("15"), status="active", display_name="viperr", nickname_set=True))
        s.add(User(telegram_id=527207617, first_name="A", balance=Decimal("0"), status="active", display_name="Vip_ogurec", nickname_set=True))
        s.add(User(telegram_id=999, first_name="B", balance=Decimal("0"), status="active", display_name="Dasha", nickname_set=True))
        await s.commit()

    # Middleware-shape: бонус один раз в день, last_bonus_at персистится.
    # (Старый баг: пометка писалась в отсоединённый объект и не сохранялась,
    # бонус капал на КАЖДЫЙ апдейт.)
    async with async_session() as s:
        user = await get_user(s, 11)
        granted1 = await auto_daily_return_bonus(s, user)
    assert granted1 is not None, "first grant inside session returned None"

    async with async_session() as s:
        lb = (await s.execute(select(User.last_bonus_at).where(User.telegram_id == 11))).scalar_one()
        bal = (await s.execute(select(User.balance).where(User.telegram_id == 11))).scalar_one()
    assert lb is not None and lb.date() == datetime.now().date(), f"last_bonus_at NOT persisted: {lb}"
    assert float(bal) == 220.0, f"balance: {bal} != 220"

    async with async_session() as s:
        user = await get_user(s, 11)
        granted2 = await auto_daily_return_bonus(s, user)
    assert granted2 is None, f"daily bonus granted twice in one day: {granted2}"
    print("PASS  hotfix: бонус 1 раз/день, маркер персистится")

    # Админский поиск: частичный ник (регистр не важен), суффикс, tg-prefix, без ложных срабатываний
    async with async_session() as s:
        res = await search_users_admin(s, "Vip")
        names = sorted(u.display_name for u in res)
        assert names == ["Vip_ogurec", "Viperrr", "viperr"], f"search 'Vip': {names}"
        res2 = await search_users_admin(s, "ogure")
        assert [u.display_name for u in res2] == ["Vip_ogurec"], f"search 'ogure'"
        res3 = await search_users_admin(s, "527")
        assert res3 and res3[0].telegram_id == 527207617, f"search tg prefix 527"
        res4 = await search_users_admin(s, "zzz_nothing")
        assert not res4, f"search nothing: {res4}"
    print("PASS  hotfix: поиск по частичному нику/ID")

    # ВНИМАНИЕ: прогон migrate.repair_bonus_spam_step() здесь намеренно НЕ
    # вызывается — внутри него asyncio.run(), недопустимый из асинхронного теста
    # (это одноразовая починка, маркерbonus_spam_repaired_v1 уже стоит в проде).


# ── Сьют: УВЕДОМЛЕНИЕ О НОВОМ ПОЛЬЗОВАТЕЛЕ (бывший test_new_user_notify.py) ──
async def test_suite_new_user_notify(monkeypatch):
    from app.db import async_session
    from app.models import User
    from app.services import get_or_create_user, has_valid_nickname, change_balance_atomic  # noqa: F401
    import app.user_handlers as uh
    from app.user_handlers import cmd_start, process_nickname

    await reset_bot_db()
    # notify_admins живёт в services.py и читает ADMINS СВОЕГО модуля
    import app.services as _svc
    monkeypatch.setattr(_svc, "ADMINS", [999111])
    monkeypatch.setattr(uh, "ADMINS", [999111])

    sent_admin: list = []
    BOT = _mk_simple_bot(sent_admin)

    def make_msg(tg_id: int, text: str = "", username="oliver", first="Oliver"):
        return SimpleNamespace(
            text=text,
            from_user=SimpleNamespace(id=tg_id, username=username, first_name=first, last_name=None),
            answer=_AsyncMock(),
            bot=BOT,
        )

    def make_state():
        return SimpleNamespace(clear=_AsyncMock(), set_state=_AsyncMock(),
                               get_data=_AsyncMock(return_value={}), update_data=_AsyncMock())

    # 1) Первый /start -> админам ТИШИНА
    await cmd_start(make_msg(555000001), SimpleNamespace(args=None), make_state())
    assert not sent_admin, f"/start fired admin notify: {sent_admin}"
    async with async_session() as s:
        u = (await s.execute(select(User).where(User.telegram_id == 555000001))).scalar_one()
        assert u.id and not has_valid_nickname(u)
    # 2) Первый валидный ник -> ровно одно уведомление с ником
    await process_nickname(make_msg(555000001, text="Oliver"), make_state())
    assert len(sent_admin) == 1 and "Новый пользователь" in sent_admin[0][1] and "Oliver" in sent_admin[0][1], \
        f"first nick: {sent_admin}"
    async with async_session() as s:
        u = (await s.execute(select(User).where(User.telegram_id == 555000001))).scalar_one()
        assert has_valid_nickname(u) and u.display_name == "Oliver"
    # 3) Платная смена ника -> повторного уведомления нет
    async with async_session() as s:
        u = (await s.execute(select(User).where(User.telegram_id == 555000001))).scalar_one()
        await change_balance_atomic(s, u.id, 100000, "test_topup")
    await process_nickname(make_msg(555000001, text="NikTwo"), make_state())
    assert len(sent_admin) == 1, f"nick change fired again: {sent_admin}"
    # 4) Невалидный ник -> без уведомления, ник не сохраняется
    async with async_session() as s:
        s.add(User(telegram_id=555000002, first_name="Bob")); await s.commit()
    await process_nickname(make_msg(555000002, text="..", username=None, first="Bob"), make_state())
    assert len(sent_admin) == 1, f"invalid nick fired: {sent_admin}"
    async with async_session() as s:
        u2 = (await s.execute(select(User).where(User.telegram_id == 555000002))).scalar_one()
        assert not has_valid_nickname(u2), "invalid nick must not be stored"
    print("PASS  new-user-notify: /start тихо, 1-й ник -> уведомление, смена/невалид -> тихо")


# ── Сьют: РОТАЦИЯ ПРОМО-РАССЫЛОК (бывший test_promo_rotation.py) ─────────
async def test_suite_promo_rotation():
    from app.db import async_session
    from app.models import Event, utc_now
    from app.services import (
        seed_default_promo_messages, count_promo_messages, list_promo_messages,
        add_promo_message, update_promo_message, delete_promo_message,
        get_auto_broadcast_pool, build_event_promo_text,
    )
    from app.config import DEFAULT_PROMO_MESSAGES

    await reset_bot_db()

    # 1) сид дефолтов один раз
    async with async_session() as s:
        n1 = await seed_default_promo_messages(s)
    async with async_session() as s:
        n2 = await seed_default_promo_messages(s)
        total = await count_promo_messages(s)
        items = await list_promo_messages(s, offset=0, limit=100)
    assert n1 == len(DEFAULT_PROMO_MESSAGES) and n2 == 0 and total == len(DEFAULT_PROMO_MESSAGES), \
        f"seed: n1={n1} n2={n2} total={total}"
    assert all(m.kind == "builtin" for m in items)
    expected_texts = [d["text"] if isinstance(d, dict) else d for d in DEFAULT_PROMO_MESSAGES]
    assert sorted(m.text for m in items) == sorted(expected_texts)

    # 2-4) add/edit/delete custom сразу видны в пуле
    async with async_session() as s:
        msg = await add_promo_message(s, "🔥 <b>Моя акция выходного дня!</b> Жми скорее!", kind="custom")
        my_id = msg.id
    async with async_session() as s:
        pool = await get_auto_broadcast_pool(s)
        assert any(p["text"].startswith("🔥") for p in pool), "custom не в пуле"
        assert await update_promo_message(s, my_id, "✏️ Обновлённый текст ротации")
        pool2 = await get_auto_broadcast_pool(s)
        assert any("Обновлённый текст" in p["text"] for p in pool2), "update не в пуле"
        assert not any("Моя акция выходного" in p["text"] for p in pool2), "старый текст в пуле"
        assert await delete_promo_message(s, my_id)
        assert not await delete_promo_message(s, 999999), "нельзя удалять несуществующее"
        pool3 = await get_auto_broadcast_pool(s)
        assert not any("Обновлённый текст" in p["text"] for p in pool3), "delete не сработал"
    print("PASS  promo-rotation: сид 16 шт 1 раз; add/edit/delete видны в пуле")

    # 5) события в пуле: активное с фото и длинным описанием -> caption<=1000
    long_descr = "Описание акции. " * 100
    async with async_session() as s:
        s.add_all([
            Event(name="Викенд-скидки", description=long_descr, discount_percent=35,
                  duration_days=3, applies_vip=True, applies_coins=True,
                  image_file_id="PHOTO_FILE_ID_X",
                  start_date=utc_now(), end_date=utc_now() + timedelta(days=3), is_active=True),
            Event(name="Старая акция", description="была", discount_percent=10,
                  duration_days=1, applies_coins=True,
                  start_date=utc_now() - timedelta(days=5), end_date=utc_now() - timedelta(days=1),
                  is_active=True),
            Event(name="Выключенная", description="неактивна", discount_percent=20,
                  duration_days=2, applies_coins=True,
                  start_date=utc_now(), end_date=utc_now() + timedelta(days=2), is_active=False),
        ])
        await s.commit()
        pool4 = await get_auto_broadcast_pool(s)
    cards = [p for p in pool4 if "Викенд-скидки" in p["text"]]
    assert len(cards) == 1, f"event карточек: {len(cards)}"
    card = cards[0]
    assert card["image_file_id"] == "PHOTO_FILE_ID_X", "фото события не в пуле"
    assert len(card["text"]) <= 1000, f"caption {len(card['text'])} > 1000"
    assert "35%" in card["text"] and "VIP" in card["text"]
    assert not any("Старая акция" in p["text"] or "Выключенная" in p["text"] for p in pool4), \
        "просроченное/выключенное событие в пуле"

    # 6) формат карточки == прежнему формату рассылки (короткое описание)
    from app.models import Event as _E
    ev2 = _E(name="Тест", description="Короткое описание", discount_percent=50,
             duration_days=1, applies_coins=True,
             start_date=utc_now(), end_date=utc_now() + timedelta(days=1), is_active=True)
    txt = build_event_promo_text(ev2)
    assert txt.startswith("🎉 <b>Тест</b>\n\nКороткое описание\n\n🔥 Скидка <b>50%</b> на монеты!\n")
    assert "Не пропусти!" in txt
    assert build_event_promo_text(ev2, max_len=4000) == txt

    # 7) удаление ВСЕХ сообщений -> сид НЕ воскрешает, пул живёт на событиях
    async with async_session() as s:
        for m in await list_promo_messages(s, offset=0, limit=100):
            await delete_promo_message(s, m.id)
        reseed = await seed_default_promo_messages(s)
        total_after = await count_promo_messages(s)
        pool5 = await get_auto_broadcast_pool(s)
    assert reseed == 0 and total_after == 0, "удалённые шаблоны воскресли!"
    assert len(pool5) == 1 and "Викенд-скидки" in pool5[0]["text"], "пул должен быть из 1 карточки события"
    print("PASS  promo-rotation: события в ротации, caption-лимит, удалённые не воскресают")


# ── Сьют: ЕЖЕНЕДЕЛЬНАЯ ХАЛЯВА (бывший test_weekly_freebie.py) ────────────
async def test_suite_weekly_freebie():
    from app.db import async_session
    from app.models import User, BotSetting
    from app.services import set_setting
    from app.user_handlers import get_current_freebie_word
    from app.main import weekly_freebie_broadcast

    await reset_bot_db()
    sent: list = []
    BOT = _mk_simple_bot(sent)

    now = datetime.now(timezone.utc)
    iso = now.isocalendar()
    week_key = f"{iso[0]}-W{iso[1]:02d}"

    async with async_session() as s:
        for i in range(3):
            s.add(User(telegram_id=900001 + i, first_name=f"U{i}", balance=Decimal("100"), status="active"))
        s.add(User(telegram_id=900010, first_name="Ban", balance=Decimal("0"), status="banned"))
        await s.commit()

    # 1) день/час совпали -> рассылка только активным, со словом недели
    async with async_session() as s:
        await set_setting(s, "weekly_promo_day", str(now.weekday()))
        await set_setting(s, "weekly_promo_hour", str(now.hour))
    res = await weekly_freebie_broadcast(BOT)
    assert res == 3 and len(sent) == 3, f"broadcast: res={res} sent={len(sent)}"
    body = sent[0][1]
    word = get_current_freebie_word()
    assert word in body, "секретное слово отсутствует в сообщении"
    assert "ЕЖЕНЕДЕЛЬНАЯ ХАЛЯВА" in body and "200" in body and "1500" in body
    assert {tid for tid, _ in sent} == {900001, 900002, 900003}, "забаненный получил письмо!"

    async with async_session() as s:
        row = (await s.execute(select(BotSetting).where(BotSetting.key == "weekly_promo_last_sent_week"))).scalar_one_or_none()
        assert row and row.value == week_key, f"marker: {row and row.value} != {week_key}"

    # 2) повтор в ту же неделю -> не шлём (защита от редеплоя)
    res2 = await weekly_freebie_broadcast(BOT)
    assert res2 is None and len(sent) == 3, f"resend happened: {res2}"

    # 3) другой день недели -> пропуск
    async with async_session() as s:
        await set_setting(s, "weekly_promo_day", str((now.weekday() + 1) % 7))
        await set_setting(s, "weekly_promo_last_sent_week", "")
    res3 = await weekly_freebie_broadcast(BOT)
    assert res3 is None and len(sent) == 3, f"wrong day sent: {res3}"

    # 4) верный день, но час ещё не наступил -> ждём
    if now.hour < 23:
        async with async_session() as s:
            await set_setting(s, "weekly_promo_day", str(now.weekday()))
            await set_setting(s, "weekly_promo_hour", str(now.hour + 1))
        res4 = await weekly_freebie_broadcast(BOT)
        assert res4 is None and len(sent) == 3, f"future hour sent: {res4}"
    print(f"PASS  weekly-freebie: слово '{word}' активным, 1 раз/неделю, день/час соблюдены")


@pytest.mark.asyncio
async def test_new_rejection_reasons_and_immediate_reject():
    from app.keyboards import rejection_reason_keyboard
    from app.admin_handlers import reject_reason
    from app.models import User, Video, Base
    from unittest.mock import AsyncMock, patch
    from aiogram.fsm.context import FSMContext

    # 1. Keyboard tests
    kb = rejection_reason_keyboard(999)
    texts = [btn.text for row in kb.inline_keyboard for btn in row]
    cb_datas = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    
    assert any("Не соответствует правилам" in t for t in texts)
    assert any("Шок-контент" in t for t in texts)
    assert "reject_reason:999:rules_violation" in cb_datas
    assert "reject_reason:999:shock_content" in cb_datas

    # 2. Immediate reject logic
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        uploader = User(telegram_id=555111, balance=Decimal("10.00"), nickname_set=True, display_name="Uploader")
        session.add(uploader)
        await session.flush()
        v = Video(uploader_user_id=uploader.id, telegram_file_id="v_rules", telegram_file_unique_id="uniq_v_rules", status="pending")
        session.add(v)
        await session.commit()
        vid_id = v.id

    with patch("app.admin_handlers.async_session", Session), \
         patch("app.admin_handlers.check_admin", AsyncMock(return_value=True)):

        cb = AsyncMock()
        cb.from_user.id = 999999
        cb.data = f"reject_reason:{vid_id}:rules_violation"
        cb.bot = AsyncMock()
        cb.message = AsyncMock()
        state = AsyncMock(spec=FSMContext)

        await reject_reason(cb, state)

        # State should NOT be waiting_comment for rules_violation
        state.set_state.assert_not_called()

        async with Session() as session:
            updated_v = (await session.execute(select(Video).where(Video.id == vid_id))).scalar_one()
            assert updated_v.status == "rejected"
            assert updated_v.rejection_reason == "Не соответствует правилам"

        # Check uploader was notified
        cb.bot.send_message.assert_called_once_with(
            555111,
            f"❌ Публикация #{vid_id} отклонена.\nПричина: Не соответствует правилам"
        )

    await engine.dispose()


@pytest.mark.asyncio
async def test_report_decision_notifications():
    from app.admin_handlers import report_dismiss, report_remove_video
    from app.models import User, Video, VideoReport, Base
    from unittest.mock import AsyncMock, patch

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        reporter1 = User(telegram_id=777001, display_name="R1")
        reporter2 = User(telegram_id=777002, display_name="R2")
        uploader = User(telegram_id=777003, display_name="U")
        session.add_all([reporter1, reporter2, uploader])
        await session.flush()

        v1 = Video(uploader_user_id=uploader.id, telegram_file_id="v1", telegram_file_unique_id="u1", status="approved")
        v2 = Video(uploader_user_id=uploader.id, telegram_file_id="v2", telegram_file_unique_id="u2", status="approved")
        session.add_all([v1, v2])
        await session.flush()

        rep1 = VideoReport(video_id=v1.id, reporter_user_id=reporter1.id, reason="spam", status="pending")
        rep2 = VideoReport(video_id=v2.id, reporter_user_id=reporter2.id, reason="shock", status="pending")
        session.add_all([rep1, rep2])
        await session.commit()

        r1_id, r2_id = rep1.id, rep2.id
        v1_id, v2_id = v1.id, v2.id

    with patch("app.admin_handlers.async_session", Session), \
         patch("app.admin_handlers.check_admin", AsyncMock(return_value=True)):

        # 1) Dismiss report 1 (video stays)
        cb1 = AsyncMock()
        cb1.from_user.id = 999999
        cb1.data = f"report_dismiss:{r1_id}"
        cb1.bot = AsyncMock()

        await report_dismiss(cb1)

        cb1.bot.send_message.assert_called_once_with(
            777001,
            f"📢 Админ рассмотрел вашу жалобу на видео #{v1_id} и принятое решение: Оставить видео"
        )

        # 2) Remove video 2 by report
        cb2 = AsyncMock()
        cb2.from_user.id = 999999
        cb2.data = f"report_remove_video:{r2_id}:{v2_id}"
        cb2.bot = AsyncMock()

        await report_remove_video(cb2)

        cb2.bot.send_message.assert_called_once_with(
            777002,
            f"📢 Админ рассмотрел вашу жалобу на видео #{v2_id} и принятое решение: Удалить видео"
        )

    await engine.dispose()


@pytest.mark.asyncio
async def test_promo_otzyv_seed_and_title_management():
    from app.services import seed_default_promo_messages, add_promo_message, update_promo_message, delete_promo_message, list_promo_messages
    from app.models import PromoMessage, Base
    from app.config import DEFAULT_PROMO_MESSAGES

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Check "Отзыв" is in DEFAULT_PROMO_MESSAGES
    otzyv_item = next((d for d in DEFAULT_PROMO_MESSAGES if isinstance(d, dict) and d.get("title") == "Отзыв"), None)
    assert otzyv_item is not None
    assert "Нам очень важно ваше мнение" in otzyv_item["text"]

    async with Session() as session:
        added = await seed_default_promo_messages(session)
        assert added == len(DEFAULT_PROMO_MESSAGES)

        msgs = await list_promo_messages(session, offset=0, limit=100)
        seeded_otzyv = next((m for m in msgs if m.title == "Отзыв"), None)
        assert seeded_otzyv is not None
        assert "отзыв" in seeded_otzyv.text.lower()

        # Custom promo message with title
        custom = await add_promo_message(session, "Текст новой промо аккаунта", title="Мой Отзыв")
        assert custom.title == "Мой Отзыв"
        assert custom.text == "Текст новой промо аккаунта"

        # Update title & text
        ok = await update_promo_message(session, custom.id, text="Обновленный текст", title="Новый Заголовок")
        assert ok is True

        refreshed = (await session.execute(select(PromoMessage).where(PromoMessage.id == custom.id))).scalar_one()
        assert refreshed.title == "Новый Заголовок"
        assert refreshed.text == "Обновленный текст"

        # Delete
        deleted = await delete_promo_message(session, custom.id)
        assert deleted is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_donationalerts_integration():
    from app.services import process_donationalerts_donation, has_active_perk
    from app.models import User, Payment, Base
    from unittest.mock import AsyncMock

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        u1 = User(telegram_id=888001, balance=Decimal("100.00"), nickname_set=True, display_name="Donor1")
        session.add(u1)
        await session.commit()

        # 1. Process donation for coins (100 RUB = 1000 coins)
        mock_bot = AsyncMock()
        ok, msg = await process_donationalerts_donation(
            session=session,
            donation_id="da_test_100",
            amount_rub=100,
            telegram_user_id=888001,
            comment="12345 888001 привет!",
            bot=mock_bot
        )
        assert ok is True
        assert "+1 000 монет" in msg

        # Check balance increased to 1100
        refreshed_u1 = (await session.execute(select(User).where(User.telegram_id == 888001))).scalar_one()
        assert refreshed_u1.balance == Decimal("1100.00")

        # Check notification sent to user
        mock_bot.send_message.assert_called()

        # 2. Idempotency test (same donation_id)
        ok2, msg2 = await process_donationalerts_donation(
            session=session,
            donation_id="da_test_100",
            amount_rub=100,
            telegram_user_id=888001,
            comment="888001",
            bot=mock_bot
        )
        assert ok2 is False
        assert "уже был обработан" in msg2

        # 3. Process VIP donation (150 RUB or comment containing "vip")
        ok3, msg3 = await process_donationalerts_donation(
            session=session,
            donation_id="da_test_vip",
            amount_rub=150,
            telegram_user_id=888001,
            comment="888001 vip",
            bot=mock_bot
        )
        assert ok3 is True
        assert "VIP" in msg3
        assert await has_active_perk(session, u1.id, "vip") is True

    await engine.dispose()
