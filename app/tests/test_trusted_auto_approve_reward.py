from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, User, Video, TrustedUploader, UserPerk, BotSetting, utc_now
from app.services import auto_approve_if_trusted


@pytest.mark.asyncio
async def test_trusted_auto_approve_uses_runtime_reward_and_multiplier():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        admin = User(telegram_id=9701, balance=Decimal("0.00"), is_admin=True)
        uploader = User(telegram_id=9702, balance=Decimal("0.00"), nickname_set=True, display_name="TrustedUploader")
        session.add_all([admin, uploader])
        await session.flush()

        session.add(TrustedUploader(admin_user_id=admin.id, trusted_user_id=uploader.id))
        session.add(BotSetting(key="auto_moderation_enabled", value="true"))
        session.add(BotSetting(key="upload_reward", value="55"))
        session.add(UserPerk(
            user_id=uploader.id,
            perk_type="coin_multiplier",
            active_until=utc_now() + timedelta(days=7),
            is_active=True,
        ))

        video = Video(
            uploader_user_id=uploader.id,
            content_type="video",
            telegram_file_id="file_1",
            telegram_file_unique_id="uniq_1",
            status="pending",
        )
        session.add(video)
        await session.commit()

        approved, reward = await auto_approve_if_trusted(session, video.id, uploader.id)
        await session.refresh(uploader)
        await session.refresh(video)

        assert approved is True
        assert reward == Decimal("82.50")
        assert uploader.balance == Decimal("82.50")
        assert video.status == "approved"

    await engine.dispose()
