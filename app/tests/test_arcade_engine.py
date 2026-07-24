"""Тесты движка «Космической аркады»: математика волн, EV, конфиг."""
import random
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.arcade as arcade
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
