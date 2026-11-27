"""Re-uploading the original media can refresh a proven-invalid Telegram file_id."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, User, Video
from app.services import save_photo, save_video


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content_type", "save", "reason"),
    [
        (
            "video",
            save_video,
            "send_failed: Telegram server says - Bad Request: wrong file identifier/HTTP URL specified",
        ),
        (
            "photo",
            save_photo,
            "send_failed: Telegram server says - Bad Request: MEDIA_FILE_INVALID",
        ),
    ],
)
async def test_owner_reupload_restores_invalid_media_without_reward(content_type, save, reason):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        owner = User(
            telegram_id=79001,
            balance=Decimal("25.00"),
            nickname_set=True,
            display_name="Owner",
        )
        session.add(owner)
        await session.flush()
        row = Video(
            uploader_user_id=owner.id,
            content_type=content_type,
            telegram_file_id="stale-file-id",
            telegram_file_unique_id=f"unique-{content_type}",
            status="broken",
            rejection_reason=reason,
        )
        session.add(row)
        await session.commit()
        row_id = row.id
        balance_before = owner.balance

        if content_type == "video":
            saved, is_duplicate = await save(
                session, owner.id, "refreshed-file-id", row.telegram_file_unique_id, 12, 4096
            )
        else:
            saved, is_duplicate = await save(
                session, owner.id, "refreshed-file-id", row.telegram_file_unique_id, 4096
            )

        assert saved.id == row_id
        assert is_duplicate is False
        assert saved.telegram_file_id == "refreshed-file-id"
        assert saved.status == "approved"
        assert saved.rejection_reason is None
        assert owner.balance == balance_before

    await engine.dispose()


@pytest.mark.asyncio
async def test_reupload_by_another_user_does_not_revive_broken_media():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        owner = User(telegram_id=79002, balance=Decimal("0"), nickname_set=True)
        other = User(telegram_id=79003, balance=Decimal("0"), nickname_set=True)
        session.add_all([owner, other])
        await session.flush()
        row = Video(
            uploader_user_id=owner.id,
            content_type="video",
            telegram_file_id="stale-file-id",
            telegram_file_unique_id="shared-unique-id",
            status="broken",
            rejection_reason=(
                "send_failed: Telegram server says - Bad Request: "
                "wrong file identifier/HTTP URL specified"
            ),
        )
        session.add(row)
        await session.commit()

        saved, is_duplicate = await save_video(
            session, other.id, "other-user-file-id", "shared-unique-id", 12, 4096
        )

        assert is_duplicate is True
        assert saved.telegram_file_id == "stale-file-id"
        assert saved.status == "broken"
        assert saved.uploader_user_id == owner.id

    await engine.dispose()


@pytest.mark.asyncio
async def test_reupload_does_not_restore_moderation_rejection():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        owner = User(telegram_id=79004, balance=Decimal("0"), nickname_set=True)
        session.add(owner)
        await session.flush()
        row = Video(
            uploader_user_id=owner.id,
            content_type="video",
            telegram_file_id="old-file-id",
            telegram_file_unique_id="rejected-unique-id",
            status="rejected",
            rejection_reason="Нарушает правила",
        )
        session.add(row)
        await session.commit()

        saved, is_duplicate = await save_video(
            session, owner.id, "new-file-id", "rejected-unique-id", 12, 4096
        )
        refreshed = await session.scalar(select(Video).where(Video.id == row.id))

        assert is_duplicate is True
        assert refreshed.status == "rejected"
        assert refreshed.telegram_file_id == "old-file-id"
        assert saved.id == row.id

    await engine.dispose()
