from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import BalanceLog, Base, User, Video
from app.services import reject_video


@pytest.mark.asyncio
async def test_admin_removal_of_approved_video_charges_author_once():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        author = User(telegram_id=984001, display_name="Uploader", balance=Decimal("100"))
        session.add(author)
        await session.flush()
        video = Video(
            uploader_user_id=author.id,
            telegram_file_id="file",
            telegram_file_unique_id="unique-file",
            status="approved",
        )
        session.add(video)
        await session.commit()
        author_id, video_id = author.id, video.id

    async with session_factory() as session:
        removed = await reject_video(session, video_id, "removed_from_feed_by_admin")
        assert removed is not None

    # A duplicate removal is a no-op and must not apply another penalty.
    async with session_factory() as session:
        assert await reject_video(session, video_id, "removed_from_feed_by_admin") is None
        author = await session.get(User, author_id)
        logs = (await session.execute(select(BalanceLog).where(BalanceLog.user_id == author_id))).scalars().all()
        assert author.balance == Decimal("60.00")
        assert len(logs) == 1
        assert logs[0].source == "admin_content_removal_penalty"
        assert logs[0].amount == Decimal("-40.00")

    await engine.dispose()
