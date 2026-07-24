"""
Тесты серверного ядра «Космической аркады» и bot-меню:
старт забега, исходы волн, вывод с дневным капом, идемпотентность,
возврат протухших забегов, меню Mini App.
"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.arcade as arcade
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
    import app.arcade_handlers as ah
    monkeypatch.setattr(ah, "async_session", Session)

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
