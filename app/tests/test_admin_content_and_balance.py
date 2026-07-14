from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.admin_handlers import _parse_video_number
from app.models import BalanceLog, Base, User, UserActionLog, Video
from app.services import (
    AdminBalanceError,
    adjust_balance_by_admin,
    get_rejected_video,
    get_video_by_id,
    restore_rejected_video,
)


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as session:
        yield session
    await engine.dispose()


def test_parse_video_number_accepts_hash_and_plain_id():
    assert _parse_video_number("#1234") == 1234
    assert _parse_video_number(" 1234 ") == 1234
    assert _parse_video_number("#0") is None
    assert _parse_video_number("video 1234") is None


@pytest.mark.asyncio
async def test_rejected_archive_lookup_and_restore(db_session):
    user = User(telegram_id=700001, display_name="Author", balance=Decimal("0"))
    db_session.add(user)
    await db_session.flush()
    first = Video(
        uploader_user_id=user.id,
        telegram_file_id="file-1",
        telegram_file_unique_id="unique-1",
        status="rejected",
        rejection_reason="duplicate",
    )
    second = Video(
        uploader_user_id=user.id,
        telegram_file_id="file-2",
        telegram_file_unique_id="unique-2",
        status="rejected",
        rejection_reason="off topic",
    )
    db_session.add_all([first, second])
    await db_session.commit()

    found = await get_video_by_id(db_session, first.id)
    newest = await get_rejected_video(db_session, 0)
    assert found.id == first.id
    assert newest.id == second.id

    restored = await restore_rejected_video(db_session, second.id)
    assert restored.status == "pending"
    assert restored.rejection_reason is None
    assert (await get_rejected_video(db_session, 0)).id == first.id


@pytest.mark.asyncio
async def test_admin_balance_change_is_logged_once(db_session):
    admin = User(telegram_id=800001, display_name="Admin", balance=Decimal("0"), is_admin=True)
    target = User(telegram_id=800002, display_name="Target", balance=Decimal("100"))
    db_session.add_all([admin, target])
    await db_session.commit()

    changed = await adjust_balance_by_admin(db_session, target.id, Decimal("25.129"), admin.id)
    await db_session.commit()
    assert changed.balance == Decimal("125.13")

    logs = (await db_session.execute(select(BalanceLog))).scalars().all()
    assert len(logs) == 1
    assert logs[0].amount == Decimal("25.13")
    assert logs[0].balance_before == Decimal("100")
    assert logs[0].balance_after == Decimal("125.13")
    assert logs[0].admin_id == admin.id
    actions = (await db_session.execute(select(UserActionLog))).scalars().all()
    assert len(actions) == 1


@pytest.mark.asyncio
async def test_admin_cannot_create_negative_balance_or_zero_change(db_session):
    admin = User(telegram_id=900001, display_name="Admin", balance=Decimal("0"), is_admin=True)
    target = User(telegram_id=900002, display_name="Target", balance=Decimal("10"))
    db_session.add_all([admin, target])
    await db_session.commit()

    with pytest.raises(AdminBalanceError, match="Нельзя списать"):
        await adjust_balance_by_admin(db_session, target.id, Decimal("-11"), admin.id)
    with pytest.raises(AdminBalanceError, match="ненулевым"):
        await adjust_balance_by_admin(db_session, target.id, Decimal("0"), admin.id)

    await db_session.refresh(target)
    assert target.balance == Decimal("10")
    assert (await db_session.execute(select(BalanceLog))).scalars().all() == []
