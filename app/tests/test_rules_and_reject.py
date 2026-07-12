from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, User, Video
from app.rules_text import FULL_RULES_TEXT, SHORT_RULES_TEXT
from app.services import reject_video


def test_rules_text_contains_key_sections():
    full = FULL_RULES_TEXT.lower()
    assert "18+" in SHORT_RULES_TEXT
    assert "некрофилия" in full
    assert "зоофилия" in full
    assert "копрофилия" in full
    assert "эмодзи" in full
    assert "мультиакки" in full
    assert "каналы, группы, чаты и ботов" in full


@pytest.mark.asyncio
async def test_reject_video_stores_reason_and_admin_comment():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with Session() as session:
        user = User(telegram_id=991001, balance=Decimal("0.00"), nickname_set=True, display_name="Uploader")
        session.add(user)
        await session.flush()
        video = Video(
            uploader_user_id=user.id,
            telegram_file_id="vid1",
            telegram_file_unique_id="uniq_vid1",
            status="pending",
        )
        session.add(video)
        await session.commit()

        updated = await reject_video(session, video.id, "Не по теме", "Нужно показать контент открыто, без эмодзи и рук")
        assert updated is not None
        assert updated.status == "rejected"
        assert updated.rejection_reason == "Не по теме. Комментарий модератора: Нужно показать контент открыто, без эмодзи и рук"

    await engine.dispose()
