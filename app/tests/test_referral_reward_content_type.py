from decimal import Decimal

import pytest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, User, Video, VideoView, BalanceLog
from app.services import process_referral_reward


@pytest.mark.asyncio
async def test_referral_reward_requires_video_views_not_photo_views():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        inviter = User(telegram_id=9301, balance=Decimal("0.00"), nickname_set=True, display_name="Inviter")
        referred = User(telegram_id=9302, balance=Decimal("0.00"), nickname_set=True, display_name="Referred")
        session.add_all([inviter, referred])
        await session.flush()
        referred.referred_by_user_id = inviter.id

        for idx in range(5):
            photo = Video(
                uploader_user_id=inviter.id,
                content_type="photo",
                telegram_file_id=f"photo_{idx}",
                telegram_file_unique_id=f"photo_unique_{idx}",
                status="approved",
            )
            session.add(photo)
            await session.flush()
            session.add(VideoView(user_id=referred.id, video_id=photo.id))
        await session.commit()

        await process_referral_reward(session, inviter.id)
        await session.refresh(inviter)
        assert inviter.balance == Decimal("0.00")

        videos = []
        for idx in range(5):
            video = Video(
                uploader_user_id=inviter.id,
                content_type="video",
                telegram_file_id=f"video_{idx}",
                telegram_file_unique_id=f"video_unique_{idx}",
                status="approved",
            )
            session.add(video)
            await session.flush()
            videos.append(video)
            session.add(VideoView(user_id=referred.id, video_id=video.id))
        await session.commit()

        await process_referral_reward(session, inviter.id)
        await session.refresh(inviter)
        reward_logs = (await session.execute(
            select(func.count(BalanceLog.id)).where(BalanceLog.source == "referral_reward")
        )).scalar_one()

        assert inviter.balance > Decimal("0.00")
        assert reward_logs == 1

    await engine.dispose()
