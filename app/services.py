import uuid
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Video, VideoView, VideoRating, Payment, Offer, OfferParticipation
from app.config import (
    STARTING_BALANCE, WATCH_COST, UPLOAD_REWARD,
    REFERRAL_REWARD_INVITER, REFERRAL_REWARD_NEW_USER,
    STARS_PACKAGES,
)

BONUS_AMOUNT = Decimal("1.00")
BONUS_COOLDOWN_HOURS = 4

PHOTO_UPLOAD_REWARD = Decimal("0.10")
FREE_PHOTO_LIMIT_PER_4H = 20

OFFER_STEP_1_REWARD = Decimal("5.00")
OFFER_STEP_2_REWARD = Decimal("10.00")
OFFER_STEP_3_REWARD = Decimal("10.00")
OFFER_STEP_4_REWARD = Decimal("15.00")
OFFER_PENALTY = Decimal("40.00")


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


def round_bot_friendly(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


# ===== ADMINS =====

async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    clean_username = username.strip().lstrip("@").lower()
    stmt = select(User).where(func.lower(User.username) == clean_username)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def set_user_admin(session: AsyncSession, user: User, value: bool) -> User:
    user.is_admin = value
    await session.commit()
    await session.refresh(user)
    return user


async def get_db_admins(session: AsyncSession) -> list[User]:
    stmt = select(User).where(User.is_admin == True).order_by(User.id.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


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
        is_admin=False,
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


# ===== OFFERS =====

async def create_offer(
    session: AsyncSession,
    title: str,
    description: str,
    channel_url: str,
) -> Offer:
    offer = Offer(
        title=title,
        description=description,
        channel_url=channel_url,
        reward_preview=OFFER_STEP_1_REWARD,
        reward_final=OFFER_STEP_2_REWARD + OFFER_STEP_3_REWARD + OFFER_STEP_4_REWARD,
        penalty_unsubscribe=OFFER_PENALTY,
        is_active=True,
    )
    session.add(offer)
    await session.commit()
    await session.refresh(offer)
    return offer


async def get_active_offers(session: AsyncSession) -> list[Offer]:
    stmt = select(Offer).where(Offer.is_active == True).order_by(Offer.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_all_offers(session: AsyncSession) -> list[Offer]:
    stmt = select(Offer).order_by(Offer.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_offer_by_id(session: AsyncSession, offer_id: int) -> Offer | None:
    stmt = select(Offer).where(Offer.id == offer_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def toggle_offer_active(session: AsyncSession, offer_id: int) -> Offer | None:
    offer = await get_offer_by_id(session, offer_id)
    if not offer:
        return None

    offer.is_active = not offer.is_active
    await session.commit()
    await session.refresh(offer)
    return offer


async def get_offer_participation(session: AsyncSession, user_id: int, offer_id: int) -> OfferParticipation | None:
    stmt = select(OfferParticipation).where(
        OfferParticipation.user_id == user_id,
        OfferParticipation.offer_id == offer_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def start_offer_participation(session: AsyncSession, user: User, offer: Offer) -> tuple[bool, str]:
    existing = await get_offer_participation(session, user.id, offer.id)
    if existing:
        return False, "Вы уже участвуете в этом оффере."

    participation = OfferParticipation(
        user_id=user.id,
        offer_id=offer.id,
        status="started",
        reward_given=OFFER_STEP_1_REWARD,
    )
    session.add(participation)
    user.balance += OFFER_STEP_1_REWARD

    await session.commit()
    return True, f"Вы начали участие в оффере и получили {OFFER_STEP_1_REWARD} монет."


async def verify_offer_subscription(
    session: AsyncSession,
    user: User,
    offer: Offer,
    is_subscribed: bool,
) -> tuple[bool, str]:
    participation = await get_offer_participation(session, user.id, offer.id)
    if not participation:
        return False, "Сначала начните участие в оффере."

    participation.checked_at = datetime.utcnow()

    if is_subscribed:
        if participation.status == "verified":
            return True, "Подписка уже подтверждена ранее."

        participation.status = "verified"
        await session.commit()
        return True, "Подписка подтверждена. Дальнейшие начисления будут происходить автоматически."
    else:
        if participation.status == "verified":
            user.balance = max(Decimal("0.00"), Decimal(str(user.balance)) - OFFER_PENALTY)
            participation.status = "penalized"
            await session.commit()
            return False, f"Вы отписались от канала. Применён штраф {OFFER_PENALTY} монет."

        await session.commit()
        return False, "Подписка не подтверждена. Подпишитесь на канал и попробуйте снова."


async def get_verified_offer_participations(session: AsyncSession) -> list[OfferParticipation]:
    stmt = select(OfferParticipation).where(OfferParticipation.status == "verified")
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def process_offer_reward_step(
    session: AsyncSession,
    participation: OfferParticipation,
    offer: Offer,
    user: User,
) -> tuple[bool, str]:
    now = datetime.utcnow()
    started_at = participation.created_at
    elapsed = now - started_at
    reward_given = Decimal(str(participation.reward_given))

    target_1 = OFFER_STEP_1_REWARD
    target_2 = OFFER_STEP_1_REWARD + OFFER_STEP_2_REWARD
    target_3 = OFFER_STEP_1_REWARD + OFFER_STEP_2_REWARD + OFFER_STEP_3_REWARD
    target_4 = OFFER_STEP_1_REWARD + OFFER_STEP_2_REWARD + OFFER_STEP_3_REWARD + OFFER_STEP_4_REWARD

    reward_to_add = Decimal("0.00")
    message = ""

    if elapsed >= timedelta(hours=24) and reward_given < target_4:
        reward_to_add = target_4 - reward_given
        message = f"Начислен финальный этап оффера: +{reward_to_add}"
    elif elapsed >= timedelta(minutes=30) and reward_given < target_3:
        reward_to_add = target_3 - reward_given
        message = f"Начислен этап оффера за 30 минут: +{reward_to_add}"
    elif elapsed >= timedelta(minutes=5) and reward_given < target_2:
        reward_to_add = target_2 - reward_given
        message = f"Начислен этап оффера за 5 минут: +{reward_to_add}"

    if reward_to_add <= 0:
        return False, "Новый этап пока не достигнут."

    user.balance += reward_to_add
    participation.reward_given = reward_given + reward_to_add
    participation.checked_at = now

    await session.commit()
    return True, message


async def apply_offer_penalty(session: AsyncSession, participation: OfferParticipation, offer: Offer, user: User) -> tuple[bool, str]:
    if participation.status != "verified":
        return False, "Штраф не требуется."

    user.balance = max(Decimal("0.00"), Decimal(str(user.balance)) - OFFER_PENALTY)
    participation.status = "penalized"
    participation.checked_at = datetime.utcnow()

    await session.commit()
    return True, f"Применён штраф {OFFER_PENALTY} монет."


# ===== CONTENT SAVE =====

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
        content_type="video",
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


async def save_photo(
    session: AsyncSession,
    uploader: User,
    file_id: str,
    file_unique_id: str,
    file_size: int | None,
) -> Video | None:
    stmt = select(Video).where(Video.telegram_file_unique_id == file_unique_id)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        return None

    photo = Video(
        uploader_user_id=uploader.id,
        content_type="photo",
        telegram_file_id=file_id,
        telegram_file_unique_id=file_unique_id,
        duration_seconds=None,
        file_size=file_size,
        status="pending",
    )
    session.add(photo)
    await session.commit()
    await session.refresh(photo)
    return photo


# ===== MODERATION =====

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
        if video.content_type == "photo":
            uploader.balance += round_bot_friendly(PHOTO_UPLOAD_REWARD)
        else:
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


# ===== WATCHING VIDEO =====

async def get_video_stats_for_user(session: AsyncSession, user: User) -> dict:
    total_approved_stmt = select(func.count(Video.id)).where(
        Video.status == "approved",
        Video.content_type == "video",
    )
    total_approved = (await session.execute(total_approved_stmt)).scalar_one()

    approved_not_own_stmt = select(func.count(Video.id)).where(
        Video.status == "approved",
        Video.content_type == "video",
        Video.uploader_user_id != user.id,
    )
    approved_not_own = (await session.execute(approved_not_own_stmt)).scalar_one()

    watched_subq = select(VideoView.video_id).where(VideoView.user_id == user.id)

    available_stmt = select(func.count(Video.id)).where(
        Video.status == "approved",
        Video.content_type == "video",
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
            Video.content_type == "video",
            Video.uploader_user_id != user.id,
            Video.id.notin_(watched_subq),
        )
        .order_by(func.random())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# ===== WATCHING PHOTO =====

async def count_photo_views_last_4h(session: AsyncSession, user_id: int) -> int:
    since = datetime.utcnow() - timedelta(hours=4)

    stmt = (
        select(func.count(VideoView.id))
        .join(Video, Video.id == VideoView.video_id)
        .where(
            VideoView.user_id == user_id,
            Video.content_type == "photo",
            VideoView.watched_at >= since,
        )
    )
    result = await session.execute(stmt)
    return result.scalar_one()


async def get_random_photo_for_user(session: AsyncSession, user: User) -> Video | None:
    watched_subq = select(VideoView.video_id).where(VideoView.user_id == user.id)

    stmt = (
        select(Video)
        .where(
            Video.status == "approved",
            Video.content_type == "photo",
            Video.uploader_user_id != user.id,
            Video.id.notin_(watched_subq),
        )
        .order_by(func.random())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def record_photo_view(session: AsyncSession, user: User, photo: Video) -> bool:
    stmt = select(VideoView).where(
        VideoView.user_id == user.id,
        VideoView.video_id == photo.id,
    )
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        return False

    session.add(VideoView(user_id=user.id, video_id=photo.id))
    await session.commit()
    return True


# ===== COMMON VIEW =====

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
