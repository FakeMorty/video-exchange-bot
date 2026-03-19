import uuid
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Video, VideoView, VideoRating
from app.config import STARTING_BALANCE, WATCH_COST, UPLOAD_REWARD


# ──────────────────────────── USER ────────────────────────────

async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> tuple[User, bool]:
    stmt = select(User).where(User.telegram_id == telegram_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user:
        user.username = username
        user.first_name = first_name
        user.last_name = last_name
        await session.commit()
        return user, False

    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        balance=Decimal(str(STARTING_BALANCE)),
        referral_code=uuid.uuid4().hex[:8],
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user, True


async def get_user(session: AsyncSession, telegram_id: int) -> User | None:
    stmt = select(User).where(User.telegram_id == telegram_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def agree_to_rules(session: AsyncSession, telegram_id: int) -> User | None:
    user = await get_user(session, telegram_id)
    if user:
        user.agreed_to_rules = True
        await session.commit()
    return user


# ──────────────────────────── VIDEO UPLOAD ────────────────────

async def save_video(
    session: AsyncSession,
    uploader: User,
    file_id: str,
    file_unique_id: str,
    duration: int | None,
    file_size: int | None,
) -> Video | None:
    stmt = select(Video).where(Video.telegram_file_unique_id == file_unique_id)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        return None

    video = Video(
        uploader_user_id=uploader.id,
        telegram_file_id=file_id,
        telegram_file_unique_id=file_unique_id,
        duration_seconds=duration,
        file_size=file_size,
        status="pending",
    )
    session.add(video)
    await session.commit()
    await session.refresh(video)
    return video


# ──────────────────────────── MODERATION ──────────────────────

async def get_next_pending_video(session: AsyncSession) -> Video | None:
    stmt = select(Video).where(Video.status == "pending").order_by(Video.created_at.asc()).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def approve_video(session: AsyncSession, video_id: int) -> Video | None:
    stmt = select(Video).where(Video.id == video_id)
    result = await session.execute(stmt)
    video = result.scalar_one_or_none()
    if not video:
        return None

    video.status = "approved"
    await session.commit()

    stmt2 = select(User).where(User.id == video.uploader_user_id)
    result2 = await session.execute(stmt2)
    uploader = result2.scalar_one_or_none()
    if uploader:
        uploader.balance += Decimal(str(UPLOAD_REWARD))
        await session.commit()

    return video


async def reject_video(session: AsyncSession, video_id: int, reason: str) -> Video | None:
    stmt = select(Video).where(Video.id == video_id)
    result = await session.execute(stmt)
    video = result.scalar_one_or_none()
    if not video:
        return None

    video.status = "rejected"
    video.rejection_reason = reason
    await session.commit()
    return video


async def count_pending_videos(session: AsyncSession) -> int:
    stmt = select(func.count(Video.id)).where(Video.status == "pending")
    result = await session.execute(stmt)
    return result.scalar_one()


# ──────────────────────────── WATCHING ────────────────────────

async def get_random_video_for_user(session: AsyncSession, user: User) -> Video | None:
    watched_subq = select(VideoView.video_id).where(VideoView.user_id == user.id)

    stmt = (
        select(Video)
        .where(
            Video.status == "approved",
            Video.uploader_user_id != user.id,
            Video.id.notin_(watched_subq),
        )
        .order_by(func.random())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def record_view_and_charge(session: AsyncSession, user: User, video: Video) -> bool:
    if user.balance < Decimal(str(WATCH_COST)):
        return False

    view = VideoView(user_id=user.id, video_id=video.id)
    session.add(view)
    user.balance -= Decimal(str(WATCH_COST))
    await session.commit()
    return True


# ──────────────────────────── RATING ──────────────────────────

async def rate_video(session: AsyncSession, user_id: int, video_id: int, rating: int) -> None:
    stmt = select(VideoRating).where(
        VideoRating.user_id == user_id,
        VideoRating.video_id == video_id,
    )
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        existing.rating = rating
    else:
        r = VideoRating(user_id=user_id, video_id=video_id, rating=rating)
        session.add(r)

    await session.commit()
