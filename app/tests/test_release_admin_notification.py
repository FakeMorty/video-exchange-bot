"""Admin release notifications are once per applied build."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, BotSetting


@pytest.mark.asyncio
async def test_release_notification_is_sent_once_per_build(monkeypatch):
    import app.main as main
    import app.release_notes as release_notes

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(main, "async_session", session_factory)
    monkeypatch.setattr(main, "ADMINS", [10001])
    monkeypatch.setattr(main, "notify_admins", AsyncMock(return_value=1))
    monkeypatch.setattr(release_notes, "CURRENT_VERSION", "test-release-v1")
    monkeypatch.setenv("VERCEL_GIT_COMMIT_SHA", "0123456789abcdef")

    bot = object()
    assert await main._notify_admins_release_applied(bot) is True
    assert await main._notify_admins_release_applied(bot) is True

    main.notify_admins.assert_awaited_once()
    sent_text = main.notify_admins.await_args.args[1]
    assert "Обновление бота применено" in sent_text
    assert "test-release-v1" in sent_text

    async with session_factory() as session:
        setting = await session.scalar(
            select(BotSetting).where(BotSetting.key == "last_admin_release_notice")
        )
        assert setting.value == "test-release-v1:0123456789abcdef"

    await engine.dispose()


@pytest.mark.asyncio
async def test_failed_admin_delivery_releases_marker_for_retry(monkeypatch):
    import app.main as main
    import app.release_notes as release_notes

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(main, "async_session", session_factory)
    monkeypatch.setattr(main, "ADMINS", [10002])
    monkeypatch.setattr(main, "notify_admins", AsyncMock(side_effect=[0, 1]))
    monkeypatch.setattr(release_notes, "CURRENT_VERSION", "test-release-retry")
    monkeypatch.delenv("VERCEL_GIT_COMMIT_SHA", raising=False)
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)

    bot = object()
    assert await main._notify_admins_release_applied(bot) is False
    assert await main._notify_admins_release_applied(bot) is True
    assert main.notify_admins.await_count == 2

    async with session_factory() as session:
        setting = await session.scalar(
            select(BotSetting).where(BotSetting.key == "last_admin_release_notice")
        )
        assert setting.value == "test-release-retry:test-release-retry"

    await engine.dispose()


async def _invoke_asgi(app, *, query: str, body: bytes):
    messages = [{"type": "http.request", "body": body, "more_body": False}]
    sent = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    await app(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/index",
            "query_string": query.encode(),
            "headers": [],
        },
        receive,
        send,
    )
    status = next(message["status"] for message in sent if message["type"] == "http.response.start")
    response = next(message["body"] for message in sent if message["type"] == "http.response.body")
    return status, json.loads(response)


@pytest.mark.asyncio
async def test_vercel_promotion_notifies_immediately_without_waiting_for_telegram_update(monkeypatch):
    import api.index as vercel_entrypoint
    import app.main as main

    notify = AsyncMock(return_value=True)
    bot = SimpleNamespace(
        set_webhook=AsyncMock(),
        get_webhook_info=AsyncMock(return_value=SimpleNamespace(
            url="https://bot.example.com/webhook", pending_update_count=0
        )),
    )
    monkeypatch.setattr(main, "_notify_admins_release_applied", notify)
    monkeypatch.setattr(vercel_entrypoint, "_get_bot_and_dispatcher", lambda: (bot, object()))
    monkeypatch.setenv("VERCEL_RELEASE_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setenv("WEBHOOK_BASE", "https://bot.example.com")
    monkeypatch.setenv("WEBHOOK_PATH", "/webhook")
    monkeypatch.setenv("WEBHOOK_SECRET", "telegram-secret")
    event = {
        "type": "deployment.promoted",
        "payload": {
            "deployment": {
                "id": "dpl_applied123",
                "target": "production",
                "meta": {"githubCommitSha": "abc123"},
            }
        },
    }

    status, response = await _invoke_asgi(
        vercel_entrypoint.app,
        query="__vercel_path=%2Fapi%2Frelease-applied&key=test-secret",
        body=json.dumps(event).encode(),
    )

    assert status == 200
    assert response == {"ok": True, "webhook_configured": True}
    bot.set_webhook.assert_awaited_once_with(
        url="https://bot.example.com/webhook",
        secret_token="telegram-secret",
        drop_pending_updates=False,
    )
    bot.get_webhook_info.assert_awaited_once()
    notify.assert_awaited_once()
    assert notify.await_args.kwargs == {"build_id": "dpl_applied123"}


@pytest.mark.asyncio
async def test_vercel_release_webhook_rejects_bad_secret_and_ignores_preview(monkeypatch):
    import api.index as vercel_entrypoint
    import app.main as main

    notify = AsyncMock(return_value=True)
    monkeypatch.setattr(main, "_notify_admins_release_applied", notify)
    monkeypatch.setattr(vercel_entrypoint, "_get_bot_and_dispatcher", lambda: (object(), object()))
    monkeypatch.setenv("VERCEL_RELEASE_WEBHOOK_SECRET", "test-secret")
    body = json.dumps({"type": "deployment.promoted", "payload": {"target": "preview"}}).encode()

    status, response = await _invoke_asgi(
        vercel_entrypoint.app,
        query="__vercel_path=%2Fapi%2Frelease-applied&key=wrong",
        body=body,
    )
    assert status == 403
    assert response["error"] == "bad key"

    status, response = await _invoke_asgi(
        vercel_entrypoint.app,
        query="__vercel_path=%2Fapi%2Frelease-applied&key=test-secret",
        body=body,
    )
    assert status == 200
    assert response["ignored"] == "not production"
    notify.assert_not_awaited()
