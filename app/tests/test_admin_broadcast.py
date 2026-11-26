import asyncio

import pytest

import app.admin_handlers as admin_handlers
from app.admin_handlers import _send_broadcast_batch


class _FakeBot:
    def __init__(self, failed_ids=()):
        self.failed_ids = set(failed_ids)
        self.sent_ids = []
        self.active_sends = 0
        self.max_active_sends = 0

    async def send_message(self, telegram_id, text, **kwargs):
        self.active_sends += 1
        self.max_active_sends = max(self.max_active_sends, self.active_sends)
        try:
            await asyncio.sleep(0.001)
            if telegram_id in self.failed_ids:
                raise RuntimeError("recipient unavailable")
            self.sent_ids.append(telegram_id)
        finally:
            self.active_sends -= 1


@pytest.mark.asyncio
async def test_broadcast_batch_sends_concurrently_and_counts_failures():
    bot = _FakeBot(failed_ids={4, 9})
    recipients = list(range(1, 13))

    sent, failed = await _send_broadcast_batch(
        bot,
        recipients,
        "test broadcast",
        max_per_second=10_000,
        concurrency=4,
    )

    assert sent == 10
    assert failed == 2
    assert sorted(bot.sent_ids) == [1, 2, 3, 5, 6, 7, 8, 10, 11, 12]
    assert 1 < bot.max_active_sends <= 4


@pytest.mark.asyncio
async def test_broadcast_batch_handles_empty_recipient_list():
    bot = _FakeBot()

    assert await _send_broadcast_batch(bot, [], "test") == (0, 0)
    assert bot.sent_ids == []


@pytest.mark.asyncio
async def test_broadcast_runner_awaits_job_in_serverless(monkeypatch):
    monkeypatch.setattr(admin_handlers, "IS_SERVERLESS", True)
    completed = False

    async def job():
        nonlocal completed
        await asyncio.sleep(0)
        completed = True

    await admin_handlers._run_report_job(job)

    assert completed
