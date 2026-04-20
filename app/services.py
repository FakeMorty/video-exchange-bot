import uuid
import random
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import (
    User,
    Video,
    VideoView,
    VideoRating,
    Payment,
    Offer,
    OfferParticipation,
    Comment,
    ContentReaction,
    GameHistory,
    DailyQuestProgress,
    GameSession,
    UserActionLog,
)
from app.config import (
    STARTING_BALANCE,
    WATCH_COST,
    UPLOAD_REWARD,
    REFERRAL_REWARD_INVITER,
    REFERRAL_REWARD_NEW_USER,
    STARS_PACKAGES,
    STARS_TO_COINS_RATE,
    MONEY_PACKAGES,
    WEEKLY_TOP1_REWARD,
    WEEKLY_TOP2_REWARD,
    WEEKLY_TOP3_REWARD,
    DAILY_QUESTS,
    PREMIUM_DAILY_QUESTS,
    BUMP_VIDEO_COST,
    PIN_OFFER_COST,
)

# Constants missing in PDF but used in code
PHOTO_UPLOAD_REWARD = Decimal("0.1")
OFFER_STEP_1_REWARD = Decimal("5")
OFFER_PENALTY = Decimal("40")
GAME_SESSION_LIMIT = 10
GAME_SESSION_COST = Decimal("10")
GAME_SESSION_HOURS = 4

def to_decimal(val) -> Decimal:
    return Decimal(str(val))

def round_coin(val: Decimal) -> Decimal:
    return val.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

async def log_user_action(session: AsyncSession, user_id: int, action: str, details: str = None):
    """Логирует каждое действие пользователя в базу данных."""
    log = UserActionLog(user_id=user_id, action=action, details=details)
    session.add(log)
    await session.commit()

async def get_user(session: AsyncSession, telegram_id: int):
    stmt = select(User).where(User.telegram_id == telegram_id)
    return (await session.execute(stmt)).scalar_one_or_none()

async def get_user_by_id(session: AsyncSession, user_id: int):
    return (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()

async def get_user_by_username(session: AsyncSession, username: str):
    if username.startswith("@"):
        username = username[1:]
    return (await session.execute(select(User).where(User.username == username))).scalar_one_or_none()

async def get_or_create_user(session, telegram_id, username=None, first_name=None, last_name=None, referral_code=None):
    user = await get_user(session, telegram_id)
    if user:
        user.username = username
        user.first_name = first_name
        user.last_name = last_name
        await session.commit()
        return user, False
    
    referred_by = None
    if referral_code:
        inviter = (await session.execute(select(User).where(User.referral_code == referral_code))).scalar_one_or_none()
        if inviter and inviter.telegram_id != telegram_id:
            referred_by = inviter.id
            inviter.balance += to_decimal(REFERRAL_REWARD_INVITER)
            inviter.referral_earnings += to_decimal(REFERRAL_REWARD_INVITER)

    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        balance=to_decimal(STARTING_BALANCE) + (to_decimal(REFERRAL_REWARD_NEW_USER) if referred_by else 0),
        referral_code=uuid.uuid4().hex[:8],
        referred_by_user_id=referred_by,
        is_admin=False,
    )
    session.add(user)
    await session.commit()
    await log_user_action(session, user.id, "registration", f"Referred by: {referred_by}")
    return user, True

async def approve_video(session: AsyncSession, video_id: int):
    """Исправленная функция одобрения видео с начислением награды."""
    v = (await session.execute(select(Video).where(Video.id == video_id))).scalar_one_or_none()
    if not v or v.status != "pending":
        return v
    v.status = "approved"
    up = await get_user_by_id(session, v.uploader_user_id)
    if up:
        reward = PHOTO_UPLOAD_REWARD if v.content_type == "photo" else to_decimal(UPLOAD_REWARD)
        up.balance += reward
        await log_user_action(session, up.id, "video_approved", f"Video ID: {v.id}, Reward: {reward}")
    await session.commit()
    return v

async def reject_video(session: AsyncSession, video_id: int, reason: str):
    v = (await session.execute(select(Video).where(Video.id == video_id))).scalar_one_or_none()
    if not v: return None
    v.status = "rejected"
    v.rejection_reason = reason
    await session.commit()
    await log_user_action(session, v.uploader_user_id, "video_rejected", f"Video ID: {v.id}, Reason: {reason}")
    return v

async def get_user_dossier(session: AsyncSession, user_id: int):
    """Получает полное досье пользователя со ВСЕМИ логами действий."""
    user = await get_user_by_id(session, user_id)
    if not user: return None
    
    games_count = (await session.execute(select(func.count(GameHistory.id)).where(GameHistory.user_id == user_id))).scalar_one()
    videos_uploaded = (await session.execute(select(func.count(Video.id)).where(Video.uploader_user_id == user_id))).scalar_one()
    videos_watched = (await session.execute(select(func.count(VideoView.id)).where(VideoView.user_id == user_id))).scalar_one()
    
    # Получаем ВСЕ логи действий без ограничений
    logs = (await session.execute(select(UserActionLog).where(UserActionLog.user_id == user_id).order_by(desc(UserActionLog.created_at)))).scalars().all()
    
    return {
        "user": user,
        "games_count": games_count,
        "videos_uploaded": videos_uploaded,
        "videos_watched": videos_watched,
        "logs": logs
    }

async def update_user_balance(session: AsyncSession, user_id: int, amount: Decimal, admin_id: int):
    user = await get_user_by_id(session, user_id)
    if user:
        user.balance += amount
        await log_user_action(session, user_id, "balance_update", f"By admin {admin_id}, Amount: {amount}")
        await session.commit()
        return True
    return False

async def set_user_ban_status(session: AsyncSession, user_id: int, is_banned: bool, admin_id: int):
    user = await get_user_by_id(session, user_id)
    if user:
        user.status = "banned" if is_banned else "active"
        await log_user_action(session, user_id, "ban_status_change", f"By admin {admin_id}, Banned: {is_banned}")
        await session.commit()
        return True
    return False

# Остальные вспомогательные функции
async def get_next_pending_video(session):
    return (await session.execute(select(Video).where(Video.status == "pending").order_by(Video.created_at).limit(1))).scalar_one_or_none()

async def count_pending_videos(session):
    return (await session.execute(select(func.count(Video.id)).where(Video.status == "pending"))).scalar_one()

async def count_approved_videos(session):
    return (await session.execute(select(func.count(Video.id)).where(Video.status == "approved"))).scalar_one()

async def count_rejected_videos(session):
    return (await session.execute(select(func.count(Video.id)).where(Video.status == "rejected"))).scalar_one()

async def get_admin_extended_stats(session):
    return {
        "users": (await session.execute(select(func.count(User.id)))).scalar_one(),
        "vip": (await session.execute(select(func.count(User.id)).where(User.vip_until > datetime.utcnow()))).scalar_one(),
        "comments": (await session.execute(select(func.count(Comment.id)))).scalar_one(),
        "reactions": (await session.execute(select(func.count(ContentReaction.id)))).scalar_one(),
        "games": (await session.execute(select(func.count(GameHistory.id)))).scalar_one(),
        "offers": (await session.execute(select(func.count(Offer.id)))).scalar_one(),
    }
async def save_video(session: AsyncSession, user_id: int, file_id: str, file_unique_id: str, duration: int = None, file_size: int = None):
    video = Video(
        uploader_user_id=user_id,
        content_type="video",
        telegram_file_id=file_id,
        telegram_file_unique_id=file_unique_id,
        duration_seconds=duration,
        file_size=file_size,
        status="pending",
    )
    session.add(video)
    await session.commit()
    await log_user_action(session, user_id, "upload_video", f"File: {file_unique_id}")
    return video

async def save_photo(session: AsyncSession, user_id: int, file_id: str, file_unique_id: str, file_size: int = None):
    photo = Video(
        uploader_user_id=user_id,
        content_type="photo",
        telegram_file_id=file_id,
        telegram_file_unique_id=file_unique_id,
        file_size=file_size,
        status="pending",
    )
    session.add(photo)
    await session.commit()
    await log_user_action(session, user_id, "upload_photo", f"File: {file_unique_id}")
    return photo

async def get_random_video_for_user(session: AsyncSession, user_id: int):
    viewed = select(VideoView.video_id).where(VideoView.user_id == user_id)
    stmt = select(Video).where(
        Video.status == "approved",
        Video.content_type == "video",
        Video.uploader_user_id != user_id,
        ~Video.id.in_(viewed)
    ).order_by(func.random()).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()

async def get_random_photo_for_user(session: AsyncSession, user_id: int):
    stmt = select(Video).where(
        Video.status == "approved",
        Video.content_type == "photo",
        Video.uploader_user_id != user_id,
    ).order_by(func.random()).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()

async def record_view_and_charge(session: AsyncSession, user_id: int, video_id: int):
    user = await get_user_by_id(session, user_id)
    if not user:
        return False
    cost = to_decimal(WATCH_COST)
    if user.balance < cost:
        return False
    user.balance -= cost
    user.xp += 5
    view = VideoView(user_id=user_id, video_id=video_id)
    session.add(view)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
    return True

async def record_photo_view(session: AsyncSession, user_id: int, photo_id: int):
    view = VideoView(user_id=user_id, video_id=photo_id)
    session.add(view)
    try:
        await session.commit()
    except Exception:
        await session.rollback()

async def count_photo_views_last_4h(session: AsyncSession, user_id: int) -> int:
    since = datetime.utcnow() - timedelta(hours=4)
    stmt = select(func.count(VideoView.id)).where(
        VideoView.user_id == user_id,
        VideoView.watched_at >= since,
    )
    return (await session.execute(stmt)).scalar_one()

async def rate_video(session: AsyncSession, user_id: int, video_id: int, rating: int):
    existing = (await session.execute(
        select(VideoRating).where(VideoRating.user_id == user_id, VideoRating.video_id == video_id)
    )).scalar_one_or_none()
    if existing:
        existing.rating = rating
    else:
        session.add(VideoRating(user_id=user_id, video_id=video_id, rating=rating))
    await session.commit()

async def claim_daily_bonus(session: AsyncSession, user_id: int):
    user = await get_user_by_id(session, user_id)
    if not user:
        return False, "Пользователь не найден"
    now = datetime.utcnow()
    if user.last_bonus_at and (now - user.last_bonus_at).total_seconds() < 86400:
        remaining = 86400 - (now - user.last_bonus_at).total_seconds()
        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)
        return False, f"Бонус уже получен. Следующий через {hours}ч {minutes}мин"
    bonus = to_decimal(1.0)
    user.balance += bonus
    user.last_bonus_at = now
    await session.commit()
    return True, bonus

async def count_referrals(session: AsyncSession, user_id: int) -> int:
    stmt = select(func.count(User.id)).where(User.referred_by_user_id == user_id)
    return (await session.execute(stmt)).scalar_one()

async def create_payment(session: AsyncSession, user_id: int, pack_key: str):
    pack = STARS_PACKAGES.get(pack_key)
    if not pack:
        return None
    payload = f"{user_id}_{pack_key}_{uuid.uuid4().hex[:8]}"
    payment = Payment(
        user_id=user_id,
        payload=payload,
        stars_amount=pack["stars"],
        coins_amount=to_decimal(pack["coins"]),
        status="pending",
    )
    session.add(payment)
    await session.commit()
    return payment

async def create_custom_payment(session: AsyncSession, user_id: int, stars: int):
    coins = to_decimal(stars) * to_decimal(STARS_TO_COINS_RATE)
    payload = f"{user_id}_custom_{uuid.uuid4().hex[:8]}"
    payment = Payment(
        user_id=user_id,
        payload=payload,
        stars_amount=stars,
        coins_amount=coins,
        status="pending",
    )
    session.add(payment)
    await session.commit()
    return payment

async def apply_successful_payment(session: AsyncSession, payload: str):
    payment = (await session.execute(
        select(Payment).where(Payment.payload == payload)
    )).scalar_one_or_none()
    if not payment or payment.status == "completed":
        return None
    payment.status = "completed"
    user = await get_user_by_id(session, payment.user_id)
    if user:
        user.balance += payment.coins_amount
    await session.commit()
    return payment

async def get_active_offers(session: AsyncSession):
    stmt = select(Offer).where(Offer.is_active == True, Offer.status == "approved")
    return (await session.execute(stmt)).scalars().all()

async def get_offer_by_id(session: AsyncSession, offer_id: int):
    return (await session.execute(select(Offer).where(Offer.id == offer_id))).scalar_one_or_none()

async def start_offer_participation(session: AsyncSession, user_id: int, offer_id: int):
    existing = (await session.execute(
        select(OfferParticipation).where(
            OfferParticipation.user_id == user_id,
            OfferParticipation.offer_id == offer_id
        )
    )).scalar_one_or_none()
    if existing:
        return existing, False
    offer = await get_offer_by_id(session, offer_id)
    if not offer:
        return None, False
    user = await get_user_by_id(session, user_id)
    if user:
        user.balance += offer.reward_preview
    part = OfferParticipation(user_id=user_id, offer_id=offer_id, status="started", reward_given=offer.reward_preview)
    session.add(part)
    await session.commit()
    return part, True

async def verify_offer_subscription(session: AsyncSession, user_id: int, offer_id: int):
    part = (await session.execute(
        select(OfferParticipation).where(
            OfferParticipation.user_id == user_id,
            OfferParticipation.offer_id == offer_id
        )
    )).scalar_one_or_none()
    if not part:
        return False
    if part.status == "completed":
        return True
    part.status = "completed"
    part.checked_at = datetime.utcnow()
    offer = await get_offer_by_id(session, offer_id)
    user = await get_user_by_id(session, user_id)
    if offer and user:
        additional = offer.reward_final - part.reward_given
        if additional > 0:
            user.balance += additional
            part.reward_given = offer.reward_final
    await session.commit()
    return True