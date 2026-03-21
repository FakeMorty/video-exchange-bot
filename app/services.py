import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Video, VideoView, VideoRating, Payment
from app.config import (
    STARTING_BALANCE, WATCH_COST, UPLOAD_REWARD,
    REFERRAL_REWARD_INVITER, REFERRAL_REWARD_NEW_USER,
    STARS_PACKAGES,
)

BONUS_AMOUNT = Decimal("1.00")
BONUS_COOLDOWN_HOURS = 4


# ===== FORMAT =====

def format_duration(seconds: int | None) -> str:
    if not seconds:
        return "0 сек"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours} ч {minutes:02d} мин {secs:02d} сек"
    if minutes > 0:
        return f"{minutes} мин {secs:02d} сек"
    return f"{secs} сек"


def format_file_size(size_bytes: int | None) -> str:
    if not size_bytes:
        return "0 Б"

    kb = 1024
    mb = kb * 1024
    gb = mb * 1024

    if size_bytes >= gb:
        return f"{size_bytes / gb:.2f} ГБ"
    if size_bytes >= mb:
        return f"{size_bytes / mb:.2f} МБ"
    if size_bytes >= kb:
        return f"{size_bytes / kb:.2f} КБ"
    return f"{size_bytes} Б"


# ===== USER =====

async def get_user(session: AsyncSession, telegram_id: int) -> User | None:
    stmt = select(User).where(User.telegram_id == telegram_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    stmt = select(User).where(User.id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_referral_code(session: AsyncSession, referral_code: str) -> User | None:
    stmt = select(User).where(User.referral_code == referral_code)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    referral_code: str | None = None,
) -> tuple[User, bool]:
    stmt = select(User).where(User.telegram_id == telegram_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user:
        user.username = username
        user.first_name = first_name
        user.last_name = last_name
        await session.commit()
        await session.refresh(user)
        return user, False

    referred_by_user_id = None
    inviter = None

    if referral_code:
        inviter = await get_user_by_referral_code(session, referral_code)
        if inviter and inviter.telegram_id != telegram_id:
            referred_by_user_id = inviter.id

    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        balance=Decimal(str(STARTING_BALANCE)),
        referral_code=uuid.uuid4().hex[:8],
        referred_by_user_id=referred_by_user_id,
        referral_earnings=Decimal("0.00"),
    )
    session.add(user)
    await session.flush()

    if inviter:
        inviter.balance += Decimal(str(REFERRAL_REWARD_INVITER))
        inviter.referral_earnings += Decimal(str(REFERRAL_REWARD_INVITER))
        user.balance += Decimal(str(REFERRAL_REWARD_NEW_USER))

    await session.commit()
    await session.refresh(user)
    return user, True


async def agree_to_rules(session: AsyncSession, telegram_id: int) -> User | None:
    user = await get_user(session, telegram_id)
    if user:
        user.agreed_to_rules = True
        await session.commit()
        await session.refresh(user)
    return user


async def claim_daily_bonus(session: AsyncSession, telegram_id: int) -> tuple[bool, str]:
    user = await get_user(session, telegram_id)
    if not user:
        return False, "Пользователь не найден."

    now = datetime.utcnow()

    if user.last_bonus_at:
        next_available = user.last_bonus_at + timedelta(hours=BONUS_COOLDOWN_HOURS)
        if now < next_available:
            remaining = next_available - now
            total_seconds = int(remaining.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return False, f"Бонус будет доступен через {hours} ч. {minutes} мин."

    user.balance += BONUS_AMOUNT
    user.last_bonus_at = now
    await session.commit()
    await session.refresh(user)
    return True, f"Вам начислена {BONUS_AMOUNT} монета. Баланс: {user.balance}"


async def count_referrals(session: AsyncSession, user_id: int) -> int:
    stmt = select(func.count(User.id)).where(User.referred_by_user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one()


# ===== PAYMENTS =====

async def create_payment(session: AsyncSession, user: User, package_key: str) -> Payment | None:
    package = STARS_PACKAGES.get(package_key)
    if not package:
        return None

    payload = f"{package_key}:{user.telegram_id}:{uuid.uuid4().hex[:12]}"

    payment = Payment(
        user_id=user.id,
        payload=payload,
        stars_amount=package["stars"],
        coins_amount=Decimal(str(package["coins"])),
        status="pending",
    )
    session.add(payment)
    await session.commit()
    await session.refresh(payment)
    return payment


async def get_payment_by_payload(session: AsyncSession, payload: str) -> Payment | None:
    stmt = select(Payment).where(Payment.payload == payload)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def apply_successful_payment(session: AsyncSession, payload: str) -> tuple[bool, str]:
    payment = await get_payment_by_payload(session, payload)
    if not payment:
        return False, "Платёж не найден."

    if payment.status == "paid":
        return True, "Платёж уже обработан."

    user = await get_user_by_id(session, payment.user_id)
    if not user:
        return False, "Пользователь не найден."

    payment.status = "paid"
    user.balance += payment.coins_amount

    await session.commit()
    await session.refresh(user)
    return True, f"Начислено {payment.coins_amount} монет. Баланс: {user.balance}"


# ===== VIDEO =====

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


async def get_next_pending_video(session: AsyncSession) -> Video | None:
    stmt = (
        select(Video)
        .where(Video.status == "pending")
        .order_by(Video.created_at.asc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def approve_video(session: AsyncSession, video_id: int) -> Video | None:
    stmt = select(Video).where(Video.id == video_id)
    result = await session.execute(stmt)
    video = result.scalar_one_or_none()
    if not video:
        return None

    if video.status != "pending":
        return video

    video.status = "approved"
    video.rejection_reason = None

    stmt2 = select(User).where(User.id == video.uploader_user_id)
    result2 = await session.execute(stmt2)
    uploader = result2.scalar_one_or_none()
    if uploader:
        uploader.balance += Decimal(str(UPLOAD_REWARD))

    await session.commit()
    await session.refresh(video)
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
    await session.refresh(video)
    return video


async def count_pending_videos(session: AsyncSession) -> int:
    stmt = select(func.count(Video.id)).where(Video.status == "pending")
    result = await session.execute(stmt)
    return result.scalar_one()


async def count_approved_videos(session: AsyncSession) -> int:
    stmt = select(func.count(Video.id)).where(Video.status == "approved")
    result = await session.execute(stmt)
    return result.scalar_one()


async def count_rejected_videos(session: AsyncSession) -> int:
    stmt = select(func.count(Video.id)).where(Video.status == "rejected")
    result = await session.execute(stmt)
    return result.scalar_one()


# ===== WATCHING =====

async def get_video_stats_for_user(session: AsyncSession, user: User) -> dict:
    total_approved_stmt = select(func.count(Video.id)).where(Video.status == "approved")
    total_approved = (await session.execute(total_approved_stmt)).scalar_one()

    approved_not_own_stmt = select(func.count(Video.id)).where(
        Video.status == "approved",
        Video.uploader_user_id != user.id,
    )
    approved_not_own = (await session.execute(approved_not_own_stmt)).scalar_one()

    watched_subq = select(VideoView.video_id).where(VideoView.user_id == user.id)

    available_stmt = select(func.count(Video.id)).where(
        Video.status == "approved",
        Video.uploader_user_id != user.id,
        Video.id.notin_(watched_subq),
    )
    available = (await session.execute(available_stmt)).scalar_one()

    return {
        "total_approved": total_approved,
        "approved_not_own": approved_not_own,
        "available": available,
    }


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

    stmt = select(VideoView).where(
        VideoView.user_id == user.id,
        VideoView.video_id == video.id,
    )
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        return False

    session.add(VideoView(user_id=user.id, video_id=video.id))
    user.balance -= Decimal(str(WATCH_COST))
    await session.commit()
    return True


# ===== RATING =====

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
        session.add(VideoRating(user_id=user_id, video_id=video_id, rating=rating))

    await session.commit()
