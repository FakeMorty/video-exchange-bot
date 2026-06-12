"""
Исправления для лотереи-лото.
Логика:
- Можно купить билет до draw_starts_at (включительно).
- Если сейчас идёт розыгрыш — билет идёт на следующий раунд.
- Если нет билетов или призовой фонд = 0 — розыгрыш не проводится.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LotteryRound, LotteryTicket
from app.services import (
    to_decimal, log_balance_change, 
    _serialize_numbers, _deserialize_numbers
)


async def _create_next_lottery_round(session: AsyncSession, current_round: LotteryRound) -> LotteryRound:
    """Создаёт следующий раунд лотереи"""
    next_start = current_round.starts_at + timedelta(hours=48)
    draw_start = next_start + timedelta(hours=46)
    draw_end = next_start + timedelta(hours=48)
    
    key = f"c48_{int((next_start - datetime(1970,1,1,20,0)).total_seconds() // (48*3600))}"
    
    new_round = LotteryRound(
        week_key=key,
        status="open",
        ticket_price=current_round.ticket_price,
        numbers_pool=current_round.numbers_pool,
        numbers_per_ticket=current_round.numbers_per_ticket,
        drawn_numbers="",
        prize_pool=Decimal("0"),
        starts_at=next_start,
        draw_starts_at=draw_start,
        draw_ends_at=draw_end,
    )
    session.add(new_round)
    await session.commit()
    return new_round


async def buy_lottery_ticket_fixed(session: AsyncSession, user) -> tuple:
    """
    Исправленная покупка билета.
    Можно купить до draw_starts_at включительно.
    Если сейчас розыгрыш — билет на следующий раунд.
    """
    now = datetime.utcnow()
    round_obj = await ensure_current_lottery_round(session)

    # Если сейчас розыгрыш — создаём следующий раунд
    if round_obj.status != "open" or now >= round_obj.draw_starts_at:
        round_obj = await _create_next_lottery_round(session, round_obj)

    price = to_decimal(round_obj.ticket_price)
    if user.balance < price:
        return None, f"Недостаточно монет. Билет стоит {price}."

    pool = list(range(1, round_obj.numbers_pool + 1))
    pick_count = min(round_obj.numbers_per_ticket, len(pool))
    numbers = sorted(random.sample(pool, k=pick_count))

    ticket = LotteryTicket(
        round_id=round_obj.id,
        user_id=user.id,
        numbers=_serialize_numbers(numbers),
    )
    user.balance -= price
    round_obj.prize_pool += price

    await log_balance_change(
        session, user, -price, "lottery_ticket_purchase",
        source_id=round_obj.id, details=f"numbers={ticket.numbers}"
    )
    session.add(ticket)
    await session.commit()
    return ticket, None


async def settle_lottery_round_fixed(session: AsyncSession, round_obj: LotteryRound) -> dict:
    """Исправленный розыгрыш — не проводим если нет билетов или призовой фонд пуст"""
    drawn = set(_deserialize_numbers(round_obj.drawn_numbers))
    tickets = (await session.execute(
        select(LotteryTicket).where(LotteryTicket.round_id == round_obj.id)
    )).scalars().all()
    
    if not tickets or round_obj.prize_pool <= 0:
        round_obj.status = "completed"
        await session.commit()
        return {"tickets": 0, "winners": 0, "paid_total": 0.0, "skipped": True}

    # ... остальная логика розыгрыша (оставляем как было)
    winners_6, winners_5, winners_4 = [], [], []
    for t in tickets:
        matched = len(set(_deserialize_numbers(t.numbers)) & drawn)
        t.matched_count = matched
        if matched >= 6: winners_6.append(t)
        elif matched == 5: winners_5.append(t)
        elif matched == 4: winners_4.append(t)

    pool = to_decimal(round_obj.prize_pool)
    payout_map = [
        (winners_6, Decimal("0.70"), "lottery_win_6"),
        (winners_5, Decimal("0.20"), "lottery_win_5"),
        (winners_4, Decimal("0.10"), "lottery_win_4"),
    ]
    paid_total = Decimal("0")
    
    for winner_group, share, source in payout_map:
        if not winner_group: continue
        group_total = round_coin(pool * share)
        per_ticket = round_coin(group_total / len(winner_group))
        for t in winner_group:
            user = await get_user_by_id(session, t.user_id)
            if not user or t.reward_paid: continue
            user.balance += per_ticket
            t.reward_paid = True
            paid_total += per_ticket
            await log_balance_change(session, user, per_ticket, source,
                source_id=round_obj.id, details=f"ticket_id={t.id}; matched={t.matched_count}")

    round_obj.status = "completed"
    await session.commit()
    return {
        "tickets": len(tickets),
        "winners": len(winners_6) + len(winners_5) + len(winners_4),
        "paid_total": float(paid_total),
    }