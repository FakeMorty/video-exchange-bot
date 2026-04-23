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
    BalanceLog,
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
    NICKNAME_CHANGE_COST,
    NICKNAME_FIRST_FREE,
)

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


def get_display_name(user: User) -> str:
    """Получить отображаемое имя пользователя для топов и т.д."""
    if user.display_name:
        return user.display_name
    if user.first_name:
        return user.first_name
    if user.username:
        return f"@{user.username}"
    return f"User#{user.telegram_id}"


async def log_balance_change(
    session: AsyncSession,
    user: User,
    amount: Decimal,
    source: str,
    source_id: int = None,
    admin_id: int = None,
    details: str = None,
):
    """Логирует каждое изменение баланса для расследований."""
    balance_before = user.balance
    balance_after = user.balance + amount
    log = BalanceLog(
        user_id=user.id,
        amount=amount,
        balance_before=balance_before,
        balance_after=balance_after,
        source=source,
        source_id=source_id,
        admin_id=admin_id,
        details=details,
    )
    session.add(log)


async def log_user_action(session: AsyncSession, user_id: int, action: str, details: str = None):
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


async def get_user_by_display_name(session: AsyncSession, display_name: str):
    return (await session.execute(
        select(User).where(User.display_name == display_name)
    )).scalar_one_or_none()


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
        inviter = (await session.execute(
            select(User).where(User.referral_code == referral_code)
        )).scalar_one_or_none()
        if inviter and inviter.telegram_id != telegram_id:
            referred_by = inviter.id
            inviter.balance += to_decimal(REFERRAL_REWARD_INVITER)
            inviter.referral_earnings += to_decimal(REFERRAL_REWARD_INVITER)
            await log_balance_change(
                session, inviter, to_decimal(REFERRAL_REWARD_INVITER),
                "referral_inviter", details=f"New user tg_id: {telegram_id}"
            )

    starting_balance = to_decimal(STARTING_BALANCE) + (to_decimal(REFERRAL_REWARD_NEW_USER) if referred_by else 0)

    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        balance=starting_balance,
        referral_code=uuid.uuid4().hex[:8],
        referred_by_user_id=referred_by,
        is_admin=False,
        nickname_set=False,
    )
    session.add(user)
    await session.flush()  # чтобы получить user.id

    await log_balance_change(
        session, user, starting_balance,
        "registration", details=f"Starting balance. Referred by: {referred_by}"
    )
    await session.commit()
    await log_user_action(session, user.id, "registration", f"Referred by: {referred_by}")
    return user, True


async def set_display_name(session: AsyncSession, user: User, name: str) -> tuple[bool, str]:
    """
    Установить ник пользователю.
    Возвращает (успех, сообщение).
    """
    from app.config import NICKNAME_MIN_LENGTH, NICKNAME_MAX_LENGTH

    # Проверка длины
    if len(name) < NICKNAME_MIN_LENGTH:
        return False, f"❌ Ник слишком короткий. Минимум {NICKNAME_MIN_LENGTH} символа."
    if len(name) > NICKNAME_MAX_LENGTH:
        return False, f"❌ Ник слишком длинный. Максимум {NICKNAME_MAX_LENGTH} символов."

    # Проверка символов — только буквы, цифры, _, -
    import re
    if not re.match(r'^[a-zA-Zа-яА-ЯёЁ0-9_\-]+$', name):
        return False, (
            "❌ Ник может содержать только буквы (рус/лат), цифры, _ и -\n"
            "Нельзя использовать: точки, пробелы, спецсимволы."
        )

    # Проверка на «пустышки» — только из одинаковых символов
    if len(set(name.lower())) < 2:
        return False, "❌ Ник должен содержать хотя бы 2 разных символа."

    # Проверка уникальности
    existing = await get_user_by_display_name(session, name)
    if existing and existing.id != user.id:
        return False, "❌ Этот ник уже занят. Придумайте другой."

    is_first = not user.nickname_set

    if not is_first:
        # Проверяем баланс за смену
        cost = to_decimal(NICKNAME_CHANGE_COST)
        if user.balance < cost:
            return False, f"❌ Недостаточно монет для смены ника.\nНужно: {cost}, у вас: {user.balance}"
        old_name = user.display_name
        user.balance -= cost
        await log_balance_change(
            session, user, -cost,
            "nickname_change", details=f"Old: {old_name} -> New: {name}"
        )

    old_name = user.display_name
    user.display_name = name
    user.nickname_set = True
    await session.commit()
    await log_user_action(session, user.id, "set_nickname", f"Old: {old_name} -> New: {name}")

    if is_first:
        return True, f"✅ Ник <b>{name}</b> установлен бесплатно!"
    else:
        return True, f"✅ Ник изменён на <b>{name}</b>! Списано {NICKNAME_CHANGE_COST} монет."


async def approve_video(session: AsyncSession, video_id: int):
    v = (await session.execute(select(Video).where(Video.id == video_id))).scalar_one_or_none()
    if not v or v.status != "pending":
        return v
    v.status = "approved"
    up = await get_user_by_id(session, v.uploader_user_id)
    if up:
        reward = PHOTO_UPLOAD_REWARD if v.content_type == "photo" else to_decimal(UPLOAD_REWARD)
        await log_balance_change(session, up, reward, "upload_approved", source_id=v.id)
        up.balance += reward
        await log_user_action(session, up.id, "video_approved", f"Video ID: {v.id}, Reward: {reward}")
    await session.commit()
    return v


async def reject_video(session: AsyncSession, video_id: int, reason: str):
    v = (await session.execute(select(Video).where(Video.id == video_id))).scalar_one_or_none()
    if not v:
        return None
    v.status = "rejected"
    v.rejection_reason = reason
    await session.commit()
    await log_user_action(session, v.uploader_user_id, "video_rejected", f"Video ID: {v.id}, Reason: {reason}")
    return v


async def get_user_dossier(session: AsyncSession, user_id: int):
    user = await get_user_by_id(session, user_id)
    if not user:
        return None

    games_count = (await session.execute(
        select(func.count(GameHistory.id)).where(GameHistory.user_id == user_id)
    )).scalar_one()

    # Сумма выигрышей и проигрышей в играх
    game_profit = (await session.execute(
        select(func.sum(GameHistory.result)).where(GameHistory.user_id == user_id)
    )).scalar_one() or Decimal("0")

    # Подозрительные игры (очень быстрый профит)
    suspicious_games = (await session.execute(
        select(GameHistory).where(
            GameHistory.user_id == user_id,
            GameHistory.result > to_decimal(50)
        ).order_by(desc(GameHistory.created_at))
    )).scalars().all()

    videos_uploaded = (await session.execute(
        select(func.count(Video.id)).where(Video.uploader_user_id == user_id)
    )).scalar_one()

    videos_watched = (await session.execute(
        select(func.count(VideoView.id)).where(VideoView.user_id == user_id)
    )).scalar_one()

    # Баланс-логи
    balance_logs = (await session.execute(
        select(BalanceLog).where(BalanceLog.user_id == user_id)
        .order_by(desc(BalanceLog.created_at))
        .limit(50)
    )).scalars().all()

    # Общая сумма начислений
    total_earned = (await session.execute(
        select(func.sum(BalanceLog.amount)).where(
            BalanceLog.user_id == user_id,
            BalanceLog.amount > 0
        )
    )).scalar_one() or Decimal("0")

    # Общая сумма списаний
    total_spent = (await session.execute(
        select(func.sum(BalanceLog.amount)).where(
            BalanceLog.user_id == user_id,
            BalanceLog.amount < 0
        )
    )).scalar_one() or Decimal("0")

    # Начислений от админа
    admin_given = (await session.execute(
        select(func.sum(BalanceLog.amount)).where(
            BalanceLog.user_id == user_id,
            BalanceLog.source == "admin_balance",
            BalanceLog.amount > 0
        )
    )).scalar_one() or Decimal("0")

    logs = (await session.execute(
        select(UserActionLog).where(UserActionLog.user_id == user_id)
        .order_by(desc(UserActionLog.created_at))
        .limit(20)
    )).scalars().all()

    return {
        "user": user,
        "games_count": games_count,
        "game_profit": game_profit,
        "suspicious_games": suspicious_games,
        "videos_uploaded": videos_uploaded,
        "videos_watched": videos_watched,
        "balance_logs": balance_logs,
        "total_earned": total_earned,
        "total_spent": total_spent,
        "admin_given": admin_given,
        "logs": logs,
    }


async def update_user_balance(session: AsyncSession, user_id: int, amount: Decimal, admin_id: int):
    user = await get_user_by_id(session, user_id)
    if user:
        await log_balance_change(
            session, user, amount,
            "admin_balance", admin_id=admin_id,
            details=f"Manual by admin {admin_id}"
        )
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


async def get_next_pending_video(session):
    return (await session.execute(
        select(Video).where(Video.status == "pending").order_by(Video.created_at).limit(1)
    )).scalar_one_or_none()


async def count_pending_videos(session):
    return (await session.execute(
        select(func.count(Video.id)).where(Video.status == "pending")
    )).scalar_one()


async def count_approved_videos(session):
    return (await session.execute(
        select(func.count(Video.id)).where(Video.status == "approved")
    )).scalar_one()


async def count_rejected_videos(session):
    return (await session.execute(
        select(func.count(Video.id)).where(Video.status == "rejected")
    )).scalar_one()


async def get_admin_extended_stats(session):
    return {
        "users": (await session.execute(select(func.count(User.id)))).scalar_one(),
        "vip": (await session.execute(
            select(func.count(User.id)).where(User.vip_until > datetime.utcnow())
        )).scalar_one(),
        "with_nickname": (await session.execute(
            select(func.count(User.id)).where(User.nickname_set == True)
        )).scalar_one(),
        "comments": (await session.execute(select(func.count(Comment.id)))).scalar_one(),
        "reactions": (await session.execute(select(func.count(ContentReaction.id)))).scalar_one(),
        "games": (await session.execute(select(func.count(GameHistory.id)))).scalar_one(),
        "offers": (await session.execute(select(func.count(Offer.id)))).scalar_one(),
        "total_balance_in_system": (await session.execute(
            select(func.sum(User.balance))
        )).scalar_one() or Decimal("0"),
        "total_admin_given": (await session.execute(
            select(func.sum(BalanceLog.amount)).where(
                BalanceLog.source == "admin_balance",
                BalanceLog.amount > 0
            )
        )).scalar_one() or Decimal("0"),
        "total_game_profit": (await session.execute(
            select(func.sum(GameHistory.result))
        )).scalar_one() or Decimal("0"),
    }


async def save_video(session: AsyncSession, user_id: int, file_id: str, file_unique_id: str,
                     duration: int = None, file_size: int = None):
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


async def save_photo(session: AsyncSession, user_id: int, file_id: str, file_unique_id: str,
                     file_size: int = None):
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
    await log_balance_change(session, user, -cost, "watch", source_id=video_id)
    user.balance -= cost
    from app.config import XP_PER_WATCH
    user.xp += XP_PER_WATCH
    view = VideoView(user_id=user_id, video_id=video_id)
    session.add(view)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        return False
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
        select(VideoRating).where(
            VideoRating.user_id == user_id,
            VideoRating.video_id == video_id
        )
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
        return False, f"⏳ Бонус уже получен. Следующий через {hours}ч {minutes}мин"
    bonus = to_decimal(1.0)
    await log_balance_change(session, user, bonus, "daily_bonus")
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
        await log_balance_change(
            session, user, payment.coins_amount,
            "stars_payment", source_id=payment.id,
            details=f"Stars: {payment.stars_amount}, Payload: {payload}"
        )
        user.balance += payment.coins_amount
    await session.commit()
    return payment


async def get_active_offers(session: AsyncSession):
    stmt = select(Offer).where(Offer.is_active == True, Offer.status == "approved")
    return (await session.execute(stmt)).scalars().all()


async def get_offer_by_id(session: AsyncSession, offer_id: int):
    return (await session.execute(
        select(Offer).where(Offer.id == offer_id)
    )).scalar_one_or_none()


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
        await log_balance_change(
            session, user, offer.reward_preview,
            "offer_start", source_id=offer_id
        )
        user.balance += offer.reward_preview
    part = OfferParticipation(
        user_id=user_id,
        offer_id=offer_id,
        status="started",
        reward_given=offer.reward_preview
    )
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
            await log_balance_change(
                session, user, additional,
                "offer_complete", source_id=offer_id
            )
            user.balance += additional
            part.reward_given = offer.reward_final
    await session.commit()
    return True