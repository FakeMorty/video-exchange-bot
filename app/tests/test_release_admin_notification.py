"""Admin release notifications are once-per-build, including Vercel cold starts."""

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
        assert setting.value == "test-release-v1:0123456789ab"

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
        assert setting.value == "test-release-retry:test-release"

    await engine.dispose()


@pytest.mark.asyncio
async def test_vercel_checks_release_notice_once_per_warm_instance(monkeypatch):
    import api.index as vercel_entrypoint
    import app.main as main

    notify = AsyncMock(return_value=True)
    monkeypatch.setattr(main, "_notify_admins_release_applied", notify)
    monkeypatch.setattr(vercel_entrypoint, "_release_notification_checked", False)

    bot = object()
    await vercel_entrypoint._ensure_release_notification(bot)
    await vercel_entrypoint._ensure_release_notification(bot)

    notify.assert_awaited_once_with(bot)
