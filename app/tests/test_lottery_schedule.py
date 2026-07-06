from datetime import datetime

import pytest

from app.services import _get_lottery_window


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
