"""
🚀 Космическая Аркада — движок и серверное ядро риск-игры «а-ля Galaga».

Игра работает как Telegram Mini App (HTML5 canvas), но все исходы считает
СЕРВЕР (crash-модель, как в Aviator): при старте забега сервер заранее
разыгрывает `crash_wave` — волну, на которой флот гарантированно прорвётся.
Клиенту crash_wave не отдаётся, поэтому «накрутить» выигрыш невозможно:
EV раунда полностью определяется серверной математикой ниже.

Механика
--------
Игрок делает ставку монетами и отбивает волны инопланетного флота 👾.
За каждую уничтоженную волну множитель ставки растёт. Игрок в любой момент
может забрать выигрыш (ставка × множитель). На crash-волне флот прорывается
(босс-таран/мега-метеорит) — ставка сгорает.

Математика (жёстко зашита здесь, без админ-настроек)
----------------------------------------------------
* Шанс «выживания» волны №k (0-индексация): max(MIN_HIT, BASE_HIT - DECAY*k)
  → 0.72, 0.675, 0.630, 0.585, ... пол 0.30.
* Шаг множителя за волну №k: min(MAX_STEP, BASE_STEP + GROWTH*k)
  → x1.35, x1.40, x1.45, x1.50, ... потолок x1.80.
* EV-фактор одной волны = шанс * шаг: ~0.97 на первых волнах (игроку весело,
  первые волны почти безубыточны) и быстро уходит вниз на поздних волнах
  (преимущество бота растёт). На длинной дистанции бот всегда в плюсе.

Защита экономики (настраивается админом / в config.py)
------------------------------------------------------
* лимиты ставки (min/max),
* потолок множителя (авто-вывод при достижении),
* дневной кап ЧИСТОЙ прибыли игрока (arcade_daily_profit_cap),
* TTL забега с возвратом ставки, если забег «протух».
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import config as app_config

# --- Математика волн ---
BASE_HIT_CHANCE = 0.72     # шанс пережить первую волну
HIT_CHANCE_DECAY = 0.045   # уменьшение шанса за каждую следующую волну
MIN_HIT_CHANCE = 0.30      # нижняя граница шанса
BASE_MULT_STEP = 1.35      # множитель за первую волну
MULT_STEP_GROWTH = 0.05    # прирост шага множителя за волну
MAX_MULT_STEP = 1.80       # потолок шага множителя
MAX_SIMULATED_WAVES = 60   # техпотолок для генерации crash-волны

# Общий RNG (однопоточный asyncio — достаточно).
_rng = random.Random()

TWO_PLACES = Decimal("0.01")
GAME_TYPE = "arcade"


# ============================
# МАТЕМАТИКА
# ============================

def wave_hit_chance(wave: int) -> float:
    """Шанс пережить волну с 0-индексом `wave` (0 = первая волна)."""
    return max(MIN_HIT_CHANCE, BASE_HIT_CHANCE - HIT_CHANCE_DECAY * max(wave, 0))


def wave_mult_step(wave: int) -> Decimal:
    """Шаг множителя за волну с 0-индексом `wave`."""
    step = min(MAX_MULT_STEP, BASE_MULT_STEP + MULT_STEP_GROWTH * max(wave, 0))
    return Decimal(str(round(step, 2)))


def resolve_shot(rng: random.Random, wave: int) -> bool:
    """True = флот волны перебит, False = aliens прорвались."""
    return rng.random() < wave_hit_chance(wave)


def roll_shot(wave: int) -> bool:
    """Боевой розыгрыш выстрела по волне (для тестов/совместимости)."""
    return resolve_shot(_rng, wave)


def draw_crash_wave(rng: random.Random | None = None) -> int:
    """
    Разыгрывает 0-индекс волны, на которой флот прорвётся.
    Распределение точно соответствует по-волновой математике:
    P(crash == k) = prod(hit_chance[0..k-1]) * (1 - hit_chance[k]).
    """
    r = rng or _rng
    w = 0
    while w < MAX_SIMULATED_WAVES and r.random() < wave_hit_chance(w):
        w += 1
    return w


def multiplier_after(waves_cleared: int, cap: Decimal | None = None) -> Decimal:
    """Итоговый множитель после `waves_cleared` уничтоженных волн (с учётом потолка)."""
    mult = Decimal("1")
    for w in range(max(waves_cleared, 0)):
        mult = (mult * wave_mult_step(w)).quantize(TWO_PLACES, rounding=ROUND_DOWN)
        if cap is not None and mult >= cap:
            return Decimal(cap).quantize(TWO_PLACES)
    return mult


def next_multiplier(current: Decimal, wave: int, cap: Decimal) -> tuple[Decimal, bool]:
    """
    Множитель после уничтожения волны `wave` (0-индекс = текущее число
    очищенных волн). Возвращает (новый_множитель, достигнут_ли_потолок).
    """
    nxt = (Decimal(current) * wave_mult_step(wave)).quantize(TWO_PLACES, rounding=ROUND_DOWN)
    capped = nxt >= cap
    if capped:
        nxt = Decimal(cap).quantize(TWO_PLACES)
    return nxt, capped


def payout_for(bet: Decimal, multiplier: Decimal) -> Decimal:
    """Выплата = ставка × множитель, округление вниз до копеек."""
    return (Decimal(bet) * Decimal(multiplier)).quantize(TWO_PLACES, rounding=ROUND_DOWN)


# ============================
# НАСТРОЙКИ (runtime)
# ============================

@dataclass
class ArcadeConfig:
    """Рабочие настройки аркады: БД (админка) → config.py → дефолт."""
    enabled: bool = True
    min_bet: Decimal = Decimal("10")
    max_bet: Decimal = Decimal("250")
    max_multiplier: Decimal = Decimal("50")
    daily_profit_cap: Decimal = Decimal("500")
    run_ttl_minutes: int = 30


def _to_decimal(raw, default: Decimal) -> Decimal:
    try:
        return Decimal(str(raw).strip().replace(",", "."))
    except Exception:
        return default


async def load_arcade_config(session: AsyncSession) -> ArcadeConfig:
    """Читает настройки из BotSetting (админка) с фолбэком в config.py."""
    from app.services import get_setting

    enabled_raw = await get_setting(session, "arcade_enabled", "")
    if enabled_raw:
        enabled = enabled_raw.strip().lower() in ("on", "1", "true", "yes", "вкл")
    else:
        enabled = bool(app_config.ENABLE_ARCADE)

    min_bet = _to_decimal(
        await get_setting(session, "arcade_min_bet", ""),
        Decimal(str(app_config.ARCADE_MIN_BET)),
    )
    max_bet = _to_decimal(
        await get_setting(session, "arcade_max_bet", ""),
        Decimal(str(app_config.ARCADE_MAX_BET)),
    )
    max_mult = _to_decimal(
        await get_setting(session, "arcade_max_multiplier", ""),
        Decimal(str(app_config.ARCADE_MAX_MULTIPLIER)),
    )
    daily_cap = _to_decimal(
        await get_setting(session, "arcade_daily_profit_cap", ""),
        Decimal(str(app_config.ARCADE_DAILY_PROFIT_CAP)),
    )
    try:
        ttl = int(str(await get_setting(session, "arcade_run_ttl_minutes", "")).strip())
    except Exception:
        ttl = int(app_config.ARCADE_RUN_TTL_MINUTES)

    if min_bet <= 0:
        min_bet = Decimal("10")
    if max_bet < min_bet:
        max_bet = min_bet
    if max_mult < Decimal("1.1"):
        max_mult = Decimal("50")
    if daily_cap < 0:
        daily_cap = Decimal("0")

    return ArcadeConfig(
        enabled=enabled,
        min_bet=min_bet.quantize(TWO_PLACES),
        max_bet=max_bet.quantize(TWO_PLACES),
        max_multiplier=max_mult.quantize(TWO_PLACES),
        daily_profit_cap=daily_cap.quantize(TWO_PLACES),
        run_ttl_minutes=max(ttl, 1),
    )


# ============================
# СЕРВЕРНОЕ ЯДРО (транзакционные операции)
# ============================

def _utc_now():
    from app.models import utc_now
    return utc_now()


async def get_active_run(session: AsyncSession, user_db_id: int):
    from app.models import ArcadeRun
    return (await session.execute(
        select(ArcadeRun)
        .where(ArcadeRun.user_id == user_db_id, ArcadeRun.status == "active")
        .order_by(ArcadeRun.id.desc())
        .limit(1)
    )).scalar_one_or_none()


async def expire_stale_runs(session: AsyncSession, user_db_id: int, cfg: ArcadeConfig) -> None:
    """
    «Зависшие» забеги (рестарт бота, игрок ушёл) старше TTL:
    возвращаем ставку и закрываем забег.
    """
    from app.models import ArcadeRun, GameHistory
    from app.services import change_balance_atomic

    cutoff = _utc_now() - timedelta(minutes=cfg.run_ttl_minutes)
    stale = (await session.execute(
        select(ArcadeRun).where(
            ArcadeRun.user_id == user_db_id,
            ArcadeRun.status == "active",
            ArcadeRun.created_at < cutoff,
        )
    )).scalars().all()
    for run in stale:
        run.status = "expired"
        run.finished_at = _utc_now()
        await change_balance_atomic(
            session, user_db_id, Decimal(run.bet),
            source="arcade_refund", source_id=run.id,
            details=f"Возврат ставки: забег протух (волна {run.wave})",
        )
        session.add(GameHistory(
            user_id=user_db_id, game_type=GAME_TYPE,
            bet=Decimal(run.bet), result=Decimal("0"),
            details="Забег протух, ставка возвращена",
        ))
    if stale:
        await session.commit()


async def daily_arcade_profit(session: AsyncSession, user_db_id: int) -> Decimal:
    """Чистая прибыль игрока в аркаде за текущие сутки (UTC)."""
    from app.models import GameHistory
    day_start = datetime.combine(_utc_now().date(), datetime.min.time())
    row = (await session.execute(
        select(func.coalesce(func.sum(GameHistory.result), 0)).where(
            GameHistory.user_id == user_db_id,
            GameHistory.game_type == GAME_TYPE,
            GameHistory.created_at >= day_start,
        )
    )).scalar_one()
    return Decimal(row)


async def start_run(session: AsyncSession, user, bet: Decimal, cfg: ArcadeConfig) -> tuple[object | None, str]:
    """
    Старт забега: валидация, атомарное списание ставки, серверный розыгрыш
    crash-волны. Возвращает (run, error_code); error_code == "" при успехе.
    """
    from app.models import ArcadeRun
    from app.services import change_balance_atomic

    bet = Decimal(bet).quantize(TWO_PLACES, rounding=ROUND_DOWN)
    if not cfg.enabled:
        return None, "disabled"
    if bet < cfg.min_bet or bet > cfg.max_bet:
        return None, "bad_bet"

    await expire_stale_runs(session, user.id, cfg)
    if await get_active_run(session, user.id):
        return None, "run_in_progress"
    if Decimal(user.balance) < bet:
        return None, "no_funds"

    await change_balance_atomic(
        session, user.id, -bet,
        source="arcade_bet",
        details="Ставка в Космической аркаде",
    )
    run = ArcadeRun(
        user_id=user.id,
        bet=bet,
        wave=0,
        multiplier=Decimal("1.00"),
        crash_wave=draw_crash_wave(),
        status="active",
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run, ""


async def advance_wave(session: AsyncSession, run, cfg: ArcadeConfig) -> dict:
    """
    Серверный исход следующей волны. Атомарно (WHERE status='active' AND wave=
    ожидаемая) — защита от двойных запросов.

    Возвращает dict:
      {"outcome": "hit", "wave": N, "multiplier": D, "next_chance": f}
      {"outcome": "cashed_out", "capped": True, "payout": D, "cap_applied": b, ...}
      {"outcome": "lost", "wave": N}
      {"outcome": "stale"}  — гонка/забег уже закрыт
    """
    from app.models import ArcadeRun, GameHistory

    expected_wave = int(run.wave)

    if expected_wave >= int(run.crash_wave):
        # --- ПРОРЫВ ФЛОТА ---
        res = await session.execute(
            update(ArcadeRun)
            .where(ArcadeRun.id == run.id, ArcadeRun.status == "active", ArcadeRun.wave == expected_wave)
            .values(status="lost", finished_at=_utc_now())
        )
        if res.rowcount == 0:
            await session.rollback()
            return {"outcome": "stale"}
        run.status = "lost"
        run.finished_at = _utc_now()
        session.add(GameHistory(
            user_id=run.user_id, game_type=GAME_TYPE,
            bet=Decimal(run.bet), result=-Decimal(run.bet),
            details=f"Прорыв на волне {expected_wave + 1}, множитель x{_fmt(run.multiplier)}",
        ))
        await session.commit()
        return {"outcome": "lost", "wave": expected_wave}

    new_mult, capped = next_multiplier(Decimal(run.multiplier), expected_wave, cfg.max_multiplier)
    res = await session.execute(
        update(ArcadeRun)
        .where(ArcadeRun.id == run.id, ArcadeRun.status == "active", ArcadeRun.wave == expected_wave)
        .values(wave=expected_wave + 1, multiplier=new_mult)
    )
    if res.rowcount == 0:
        await session.rollback()
        return {"outcome": "stale"}
    run.wave = expected_wave + 1
    run.multiplier = new_mult
    await session.commit()

    base = {
        "wave": run.wave,
        "multiplier": run.multiplier,
        "next_chance": round(wave_hit_chance(run.wave) * 100),
    }
    if capped:
        cash = await apply_cashout(session, run, cfg, supernova=True)
        if cash["ok"]:
            return {"outcome": "cashed_out", "capped": True, **base, **cash}
        return {"outcome": "stale"}
    return {"outcome": "hit", **base}


async def apply_cashout(session: AsyncSession, run, cfg: ArcadeConfig, *, supernova: bool = False) -> dict:
    """
    Атомарно закрывает активный забег как выигрыш и начисляет выплату
    с учётом дневного капа чистой прибыли.
    """
    from app.models import ArcadeRun, GameHistory
    from app.services import change_balance_atomic

    res = await session.execute(
        update(ArcadeRun)
        .where(ArcadeRun.id == run.id, ArcadeRun.status == "active")
        .values(status="won", finished_at=_utc_now())
    )
    if res.rowcount == 0:
        await session.rollback()
        return {"ok": False}

    raw_payout = payout_for(run.bet, run.multiplier)

    # Дневной кап чистой прибыли — «чтобы не сильно богатели».
    earned_today = await daily_arcade_profit(session, run.user_id)
    remaining = cfg.daily_profit_cap - earned_today
    if remaining < 0:
        remaining = Decimal("0")
    profit = raw_payout - Decimal(run.bet)
    cap_applied = profit > remaining
    payout = (Decimal(run.bet) + min(profit, remaining)).quantize(TWO_PLACES, rounding=ROUND_DOWN)

    await change_balance_atomic(
        session, run.user_id, payout,
        source="arcade_win", source_id=run.id,
        details=(
            f"Выигрыш x{_fmt(run.multiplier)} на волне {run.wave}"
            + (" (сверхновая, авто-вывод)" if supernova else "")
            + (" [дневной кап]" if cap_applied else "")
        ),
    )
    run.status = "won"
    run.payout = payout
    run.finished_at = _utc_now()
    session.add(GameHistory(
        user_id=run.user_id, game_type=GAME_TYPE,
        bet=Decimal(run.bet), result=payout - Decimal(run.bet),
        details=(
            f"Волн: {run.wave}, множитель x{_fmt(run.multiplier)}"
            + (", сверхновая" if supernova else "")
            + (", дневной кап" if cap_applied else "")
        ),
    ))
    await session.commit()
    return {
        "ok": True,
        "payout": payout,
        "profit": payout - Decimal(run.bet),
        "multiplier": Decimal(run.multiplier),
        "wave": run.wave,
        "cap_applied": cap_applied,
    }


async def cashout_run(session: AsyncSession, run, cfg: ArcadeConfig) -> dict:
    """Кнопка «Забрать»: валидация + атомарный вывод."""
    if run.status != "active":
        return {"ok": False, "error": "not_active"}
    if int(run.wave) < 1:
        return {"ok": False, "error": "no_waves"}
    result = await apply_cashout(session, run, cfg, supernova=False)
    if not result.get("ok"):
        return {"ok": False, "error": "stale"}
    return result


def _fmt(value) -> str:
    """10.00 → '10', 12.50 → '12.5'."""
    d = Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_DOWN)
    s = f"{d:.2f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"
