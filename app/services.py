import uuid
import random
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import (
    User, Video, VideoView, VideoRating, Payment,
    Offer, OfferParticipation, OfferRental,
    Comment, ContentReaction, GameHistory,
    DailyQuestProgress, GameSession,
    UserActionLog, BalanceLog, UserAdState,
    Promocode, PromocodeActivation, Feedback,
    LotteryRound, LotteryTicket,
)
from app.config import (
    STARTING_BALANCE, WATCH_COST, UPLOAD_REWARD,
    REFERRAL_REWARD_INVITER, REFERRAL_REWARD_NEW_USER,
    STARS_PACKAGES, STARS_TO_COINS_RATE,
    WEEKLY_TOP1_REWARD, WEEKLY_TOP2_REWARD, WEEKLY_TOP3_REWARD,
    DAILY_QUESTS, PREMIUM_DAILY_QUESTS,
    BUMP_VIDEO_COST, PIN_OFFER_COST,
    NICKNAME_CHANGE_COST, NICKNAME_FIRST_FREE,
    NICKNAME_MIN_LENGTH, NICKNAME_MAX_LENGTH,
    OFFER_MIN_RENT_DAYS, OFFER_MAX_RENT_DAYS,
    DAILY_BONUS_STREAK_BASE, DAILY_BONUS_STREAK_INCREASE,
    MAX_BONUS_STREAK,
    DAILY_PHOTO_LIMIT,
    FREE_GAMES_PER_SESSION, GAME_SESSION_HOURS, GAME_SESSION_COST,
    PROMOCODE_CREATION_STAR_RATE,
    PROMOCODE_BULK_DISCOUNT_THRESHOLD,
    PROMOCODE_BULK_DISCOUNT_RATE,
    PROMOCODE_CREATOR_BONUS_PERCENT,
    PROMOCODE_MAX_AMOUNT, PROMOCODE_MAX_USES, PROMOCODE_MAX_HOURS,
    VIP_FREE_PROMO_PER_MONTH,
    DYNAMIC_STAR_DISCOUNT_ENABLED,
    DYNAMIC_STAR_DISCOUNT_HOURS,
    DYNAMIC_STAR_DISCOUNT_MULTIPLIER,
    FIRST_PURCHASE_DAILY_BONUS,
    SMART_AD_MIN_INTERVAL_MINUTES,
    SMART_AD_LOW_BALANCE_THRESHOLD,
    SMART_AD_LOW_BALANCE_HINT_INTERVAL_MINUTES,
    SMART_AD_VIDEO_CHANCE,
    SMART_AD_FORCED_WATCH_SECONDS,
    OFFER_DAILY_REWARD_CAP,
    LOTTERY_TICKET_PRICE, LOTTERY_NUMBERS_POOL, LOTTERY_NUMBERS_PER_TICKET,
    LOTTERY_DRAW_START_HOUR_UTC, LOTTERY_DRAW_END_HOUR_UTC,
    ADMINS,
)

PHOTO_UPLOAD_REWARD = Decimal("0.1")
OFFER_STEP_1_REWARD = Decimal("5")
OFFER_PENALTY = Decimal("40")


def to_decimal(val) -> Decimal:
    return Decimal(str(val))


def round_coin(val: Decimal) -> Decimal:
    return val.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def get_display_name(user: "User") -> str:
    if user.display_name:
        return user.display_name
    if user.first_name:
        return user.first_name
    if user.username:
        return f"@{user.username}"
    return f"User#{user.telegram_id}"


def is_admin_or_super(telegram_id: int, user: "User" = None) -> bool:
    if telegram_id in ADMINS:
        return True
    if user and user.is_admin:
        return True
    return False


# ============================
# ЛОГИРОВАНИЕ БАЛАНСА И ДЕЙСТВИЙ
# ============================
async def log_balance_change(
    session: AsyncSession,
    user: "User",
    amount: Decimal,
    source: str,
    source_id: int = None,
    admin_id: int = None,
    details: str = None,
):
    log = BalanceLog(
        user_id=user.id,
        amount=amount,
        balance_before=user.balance,
        balance_after=user.balance + amount,
        source=source,
        source_id=source_id,
        admin_id=admin_id,
        details=details,
    )
    session.add(log)


async def log_user_action(
    session: AsyncSession,
    user_id: int,
    action: str,
    details: str = None
):
    log = UserActionLog(user_id=user_id, action=action, details=details)
    session.add(log)
    try:
        await session.commit()
    except Exception:
        await session.rollback()


# ============================
# ПОЛУЧЕНИЕ ПОЛЬЗОВАТЕЛЕЙ
# ============================
async def get_user(session: AsyncSession, telegram_id: int) -> "User | None":
    return (await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )).scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: int) -> "User | None":
    return (await session.execute(
        select(User).where(User.id == user_id)
    )).scalar_one_or_none()


async def get_user_by_username(session: AsyncSession, username: str) -> "User | None":
    if username.startswith("@"):
        username = username[1:]
    return (await session.execute(
        select(User).where(User.username == username)
    )).scalar_one_or_none()


async def get_user_by_display_name(session: AsyncSession, display_name: str) -> "User | None":
    return (await session.execute(
        select(User).where(User.display_name == display_name)
    )).scalar_one_or_none()


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: str = None,
    first_name: str = None,
    last_name: str = None,
    referral_code: str = None,
) -> tuple["User", bool]:
    user = await get_user(session, telegram_id)
    if user:
        user.username = username
        user.first_name = first_name
        user.last_name = last_name
        await session.commit()
        return user, False

    referred_by = None
    starting_bonus = to_decimal(STARTING_BALANCE)
    if referral_code:
        inviter = (await session.execute(
            select(User).where(User.referral_code == referral_code)
        )).scalar_one_or_none()
        if inviter and inviter.telegram_id != telegram_id:
            referred_by = inviter.id

    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        balance=starting_bonus,
        referral_code=uuid.uuid4().hex[:8],
        referred_by_user_id=referred_by,
    )
    session.add(user)
    await session.flush()
    await log_balance_change(session, user, starting_bonus, "registration",
                             details=f"Starting balance. Referred by: {referred_by}")
    await session.commit()
    await log_user_action(session, user.id, "registration",
                          f"tg_id={telegram_id}, referred_by={referred_by}")
    return user, True


# ============================
# НИКНЕЙМ
# ============================
async def set_display_name(session: AsyncSession, user: "User", name: str) -> tuple[bool, str]:
    import re
    name = name.strip()
    if len(name) < NICKNAME_MIN_LENGTH:
        return False, f"Ник слишком короткий. Минимум {NICKNAME_MIN_LENGTH} символов."
    if len(name) > NICKNAME_MAX_LENGTH:
        return False, f"Ник слишком длинный. Максимум {NICKNAME_MAX_LENGTH} символов."
    if not re.match(r'^[a-zA-Zа-яА-ЯёЁ0-9_\-]+$', name):
        return False, "Ник может содержать только буквы, цифры, _ и -"
    existing = await get_user_by_display_name(session, name)
    if existing and existing.id != user.id:
        return False, "Этот ник уже занят."

    is_first = not user.nickname_set
    if not is_first:
        cost = to_decimal(NICKNAME_CHANGE_COST)
        if user.balance < cost:
            return False, f"Недостаточно монет. Нужно: {cost}, у вас: {user.balance}"
        await log_balance_change(session, user, -cost, "nickname_change",
                                 details=f"{user.display_name} -> {name}")
        user.balance -= cost

    old_name = user.display_name
    user.display_name = name
    user.nickname_set = True
    await session.commit()
    await log_user_action(session, user.id, "set_nickname", f"{old_name} -> {name}")
    if is_first:
        return True, f"Ник <b>{name}</b> установлен бесплатно!"
    return True, f"Ник изменён на <b>{name}</b>! Списано {NICKNAME_CHANGE_COST} монет."


# ============================
# ВИДЕО / ФОТО
# ============================
async def get_next_pending_video(session: AsyncSession) -> "Video | None":
    return (await session.execute(
        select(Video)
        .where(Video.status == "pending")
        .order_by(Video.created_at)
        .limit(1)
    )).scalar_one_or_none()


async def count_pending_videos(session: AsyncSession) -> int:
    return (await session.execute(
        select(func.count(Video.id)).where(Video.status == "pending")
    )).scalar_one()


async def count_approved_videos(session: AsyncSession) -> int:
    return (await session.execute(
        select(func.count(Video.id)).where(Video.status == "approved")
    )).scalar_one()


async def count_rejected_videos(session: AsyncSession) -> int:
    return (await session.execute(
        select(func.count(Video.id)).where(Video.status == "rejected")
    )).scalar_one()


async def approve_video(session: AsyncSession, video_id: int) -> "Video | None":
    v = (await session.execute(
        select(Video).where(Video.id == video_id)
    )).scalar_one_or_none()
    if not v or v.status != "pending":
        return None
    v.status = "approved"
    uploader = await get_user_by_id(session, v.uploader_user_id)
    if uploader:
        reward = PHOTO_UPLOAD_REWARD if v.content_type == "photo" else to_decimal(UPLOAD_REWARD)
        await log_balance_change(session, uploader, reward, "upload_approved", source_id=v.id)
        uploader.balance += reward
        await log_user_action(session, uploader.id, "video_approved",
                              f"video_id={v.id}, reward={reward}")
    await session.commit()
    return v


async def reject_video(session: AsyncSession, video_id: int, reason: str) -> "Video | None":
    v = (await session.execute(
        select(Video).where(Video.id == video_id)
    )).scalar_one_or_none()
    if not v:
        return None
    v.status = "rejected"
    v.rejection_reason = reason
    await session.commit()
    await log_user_action(session, v.uploader_user_id, "video_rejected",
                          f"video_id={v.id}, reason={reason}")
    return v


async def save_video(session: AsyncSession, user_id: int, file_id: str,
                     file_unique_id: str, duration: int = None,
                     file_size: int = None) -> tuple["Video", bool]:
    existing = (await session.execute(
        select(Video).where(Video.telegram_file_unique_id == file_unique_id)
    )).scalar_one_or_none()
    if existing:
        return existing, True
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
    await log_user_action(session, user_id, "upload_video", f"file={file_unique_id}")
    return video, False


async def save_photo(session: AsyncSession, user_id: int, file_id: str,
                     file_unique_id: str, file_size: int = None) -> tuple["Video", bool]:
    existing = (await session.execute(
        select(Video).where(Video.telegram_file_unique_id == file_unique_id)
    )).scalar_one_or_none()
    if existing:
        return existing, True
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
    await log_user_action(session, user_id, "upload_photo", f"file={file_unique_id}")
    return photo, False


async def get_random_video_for_user(session: AsyncSession, user_id: int) -> "Video | None":
    viewed = select(VideoView.video_id).where(VideoView.user_id == user_id)
    return (await session.execute(
        select(Video).where(
            Video.status == "approved",
            Video.content_type == "video",
            Video.uploader_user_id != user_id,
            ~Video.id.in_(viewed)
        ).order_by(func.random()).limit(1)
    )).scalar_one_or_none()


async def get_random_photo_for_user(session: AsyncSession, user_id: int) -> "Video | None":
    return (await session.execute(
        select(Video).where(
            Video.status == "approved",
            Video.content_type == "photo",
            Video.uploader_user_id != user_id,
        ).order_by(func.random()).limit(1)
    )).scalar_one_or_none()


async def record_view_and_charge(session: AsyncSession, user_id: int, video_id: int) -> bool:
    user = await get_user_by_id(session, user_id)
    if not user:
        return False
    cost = to_decimal(WATCH_COST)
    if user.balance < cost:
        return False
    await log_balance_change(session, user, -cost, "watch", source_id=video_id)
    user.balance -= cost
    view = VideoView(user_id=user_id, video_id=video_id)
    session.add(view)
    await session.commit()
    return True


async def record_view_and_charge_with_cost(
    session: AsyncSession,
    user_id: int,
    video_id: int,
    cost: Decimal,
) -> bool:
    user = await get_user_by_id(session, user_id)
    if not user:
        return False
    cost = to_decimal(cost)
    if user.balance < cost:
        return False
    await log_balance_change(session, user, -cost, "watch", source_id=video_id)
    user.balance -= cost
    session.add(VideoView(user_id=user_id, video_id=video_id))
    await session.commit()
    return True


async def refund_watch_and_unview(
    session: AsyncSession,
    user_id: int,
    video_id: int,
    cost: Decimal,
    reason: str,
) -> None:
    from sqlalchemy import delete

    user = await get_user_by_id(session, user_id)
    if not user:
        return

    cost = to_decimal(cost)
    await log_balance_change(
        session,
        user,
        cost,
        "watch_refund",
        source_id=video_id,
        details=reason,
    )
    user.balance += cost
    await session.execute(
        delete(VideoView).where(VideoView.user_id == user_id, VideoView.video_id == video_id)
    )
    await session.commit()


async def mark_content_broken(session: AsyncSession, video_id: int, reason: str) -> None:
    v = (await session.execute(select(Video).where(Video.id == video_id))).scalar_one_or_none()
    if not v:
        return
    v.status = "broken"
    v.rejection_reason = (reason or "")[:255]
    await session.commit()


async def record_photo_view(session: AsyncSession, user_id: int, photo_id: int) -> bool:
    existing = (await session.execute(
        select(VideoView).where(
            VideoView.user_id == user_id, VideoView.video_id == photo_id
        )
    )).scalar_one_or_none()
    if not existing:
        view = VideoView(user_id=user_id, video_id=photo_id)
        session.add(view)
        await session.commit()
    return True


async def check_daily_photo_limit(session: AsyncSession, user_id: int) -> bool:
    today = datetime.utcnow().date()
    count = (await session.execute(
        select(func.count(VideoView.id)).where(
            VideoView.user_id == user_id,
            func.date(VideoView.created_at) == today,
            VideoView.video_id.in_(
                select(Video.id).where(Video.content_type == "photo")
            )
        )
    )).scalar_one()
    return count < DAILY_PHOTO_LIMIT


# ============================
# РЕЙТИНГИ
# ============================
async def rate_video(session: AsyncSession, user_id: int, video_id: int, rating: int) -> bool:
    existing = (await session.execute(
        select(VideoRating).where(
            VideoRating.user_id == user_id, VideoRating.video_id == video_id
        )
    )).scalar_one_or_none()
    if existing:
        existing.rating = rating
    else:
        session.add(VideoRating(user_id=user_id, video_id=video_id, rating=rating))
    await session.commit()
    return True


# ============================
# БАЛАНС И БАН
# ============================
async def update_user_balance(session: AsyncSession, user_id: int, amount: Decimal,
                              admin_id: int = None) -> bool:
    user = await get_user_by_id(session, user_id)
    if not user:
        return False
    await log_balance_change(session, user, amount, "admin_balance", admin_id=admin_id,
                             details=f"Manual by admin {admin_id}")
    user.balance += amount
    await log_user_action(session, user_id, "balance_update",
                          f"admin={admin_id}, amount={amount}")
    await session.commit()
    return True


async def set_user_ban_status(session: AsyncSession, user_id: int, is_banned: bool,
                              admin_id: int) -> bool:
    user = await get_user_by_id(session, user_id)
    if not user:
        return False
    user.status = "banned" if is_banned else "active"
    await log_user_action(session, user_id, "ban_status_change",
                          f"admin={admin_id}, banned={is_banned}")
    await session.commit()
    return True


# ============================
# ЕЖЕДНЕВНЫЙ БОНУС (ПРОГРЕССИВНЫЙ)
# ============================
async def claim_daily_bonus(session: AsyncSession, user_id: int) -> tuple[bool, str]:
    user = await get_user_by_id(session, user_id)
    if not user:
        return False, "Пользователь не найден."
    now = datetime.utcnow()
    if user.last_bonus_at and user.last_bonus_at.date() == now.date():
        return False, "Вы уже получили бонус сегодня."
    streak = 1
    if user.last_bonus_at and (now.date() - user.last_bonus_at.date()).days == 1:
        streak = min(user.bonus_streak + 1, MAX_BONUS_STREAK)
    reward = DAILY_BONUS_STREAK_BASE + DAILY_BONUS_STREAK_INCREASE * (streak - 1)
    await log_balance_change(session, user, to_decimal(reward), "daily_bonus")
    user.balance += to_decimal(reward)
    user.last_bonus_at = now
    user.bonus_streak = streak
    await session.commit()
    return True, f"Ежедневный бонус: +{reward:.0f} монет! Дней подряд: {streak}"


# ============================
# РЕФЕРАЛЫ
# ============================
async def count_referrals(session: AsyncSession, user_id: int) -> int:
    return (await session.execute(
        select(func.count(User.id)).where(User.referred_by_user_id == user_id)
    )).scalar_one()


async def process_referral_reward(session: AsyncSession, referrer_id: int):
    """Начисляем награду, если реферал посмотрел 5 видео."""
    refs = (await session.execute(
        select(User).where(User.referred_by_user_id == referrer_id)
    )).scalars().all()
    for ref in refs:
        views = (await session.execute(
            select(func.count(VideoView.id)).where(VideoView.user_id == ref.id)
        )).scalar_one()
        if views >= 5:
            inviter = await get_user_by_id(session, referrer_id)
            if inviter:
                already = (await session.execute(
                    select(BalanceLog).where(
                        BalanceLog.user_id == referrer_id,
                        BalanceLog.source == "referral_reward",
                        BalanceLog.details == f"ref_user_id={ref.id}"
                    )
                )).scalar_one_or_none()
                if not already:
                    reward = to_decimal(REFERRAL_REWARD_INVITER)
                    await log_balance_change(session, inviter, reward, "referral_reward",
                                             details=f"ref_user_id={ref.id}")
                    inviter.balance += reward
                    inviter.referral_earnings += reward
                    await session.commit()


# ============================
# ПЛАТЕЖИ
# ============================
async def create_payment(session: AsyncSession, user_id: int, pack_key: str) -> Payment:
    pack = STARS_PACKAGES.get(pack_key)
    if not pack:
        raise ValueError("Unknown pack")
    coins = to_decimal(pack["coins"])
    payload = f"{pack_key}_{user_id}_{uuid.uuid4().hex[:6]}"
    payment = Payment(
        user_id=user_id,
        payload=payload,
        stars_amount=pack["stars"],
        coins_amount=coins,
        status="pending",
    )
    session.add(payment)
    await session.commit()
    return payment


async def create_custom_payment(session: AsyncSession, user_id: int, stars: int) -> Payment:
    coins = to_decimal(stars * STARS_TO_COINS_RATE)
    payload = f"custom_{user_id}_{uuid.uuid4().hex[:6]}"
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


async def apply_successful_payment(session: AsyncSession, payload: str) -> Payment | None:
    payment = (await session.execute(
        select(Payment).where(Payment.payload == payload)
    )).scalar_one_or_none()
    if not payment or payment.status != "pending":
        return None
    payment.status = "paid"
    user = await get_user_by_id(session, payment.user_id)
    if user:
        bonus_multiplier = 1.0
        # Динамический курс
        if DYNAMIC_STAR_DISCOUNT_ENABLED:
            try:
                start_h, end_h = map(int, DYNAMIC_STAR_DISCOUNT_HOURS.split("-"))
                now_h = datetime.utcnow().hour
                if start_h <= now_h < end_h:
                    bonus_multiplier = DYNAMIC_STAR_DISCOUNT_MULTIPLIER
            except Exception:
                pass
        # Первая покупка за день
        today = datetime.utcnow().date()
        first_today = not (await session.execute(
            select(Payment).where(
                Payment.user_id == user.id,
                Payment.status == "paid",
                func.date(Payment.created_at) == today,
                Payment.id != payment.id,
            )
        )).scalar_one_or_none()
        total_coins = payment.coins_amount * to_decimal(bonus_multiplier)
        if first_today:
            total_coins += to_decimal(FIRST_PURCHASE_DAILY_BONUS)
        await log_balance_change(session, user, total_coins, "purchase",
                                 details=f"payload={payload}, bonus_mult={bonus_multiplier}, first_today={first_today}")
        user.balance += total_coins
        await session.commit()
    return payment


# ============================
# ОФФЕРЫ
# ============================
async def get_active_offers(session: AsyncSession) -> list["Offer"]:
    return (await session.execute(
        select(Offer).where(Offer.is_active == True, Offer.status == "approved")
    )).scalars().all()


async def get_rentable_offers(session: AsyncSession) -> list["Offer"]:
    return (await session.execute(
        select(Offer).where(
            Offer.is_active == True,
            Offer.status == "approved",
            Offer.is_rentable == True,
        )
    )).scalars().all()


async def get_offer_by_id(session: AsyncSession, offer_id: int) -> "Offer | None":
    return (await session.execute(
        select(Offer).where(Offer.id == offer_id)
    )).scalar_one_or_none()


async def _get_today_offer_rewards_total(session: AsyncSession, user_id: int) -> Decimal:
    today = datetime.utcnow().date()
    value = (await session.execute(
        select(func.sum(BalanceLog.amount)).where(
            BalanceLog.user_id == user_id,
            BalanceLog.amount > 0,
            BalanceLog.source.in_(["offer_preview", "offer_complete"]),
            func.date(BalanceLog.created_at) == today,
        )
    )).scalar_one() or Decimal("0")
    return to_decimal(value)


async def start_offer_participation(session: AsyncSession, user_id: int,
                                    offer_id: int) -> tuple["OfferParticipation | None", bool]:
    offer = await get_offer_by_id(session, offer_id)
    user = await get_user_by_id(session, user_id)
    if not offer or not user:
        return None, False

    existing = (await session.execute(
        select(OfferParticipation).where(
            OfferParticipation.user_id == user_id,
            OfferParticipation.offer_id == offer_id,
        )
    )).scalar_one_or_none()
    if existing:
        return existing, False
    today_offer_rewards = await _get_today_offer_rewards_total(session, user_id)
    cap_remaining = max(to_decimal(OFFER_DAILY_REWARD_CAP) - today_offer_rewards, Decimal("0"))
    preview_reward = min(to_decimal(offer.reward_preview), cap_remaining)
    part = OfferParticipation(
        user_id=user_id,
        offer_id=offer_id,
        status="started",
        reward_given=preview_reward,
    )
    if preview_reward > 0:
        await log_balance_change(
            session,
            user,
            preview_reward,
            "offer_preview",
            source_id=offer_id,
        )
        user.balance += preview_reward
    session.add(part)
    await session.commit()
    return part, True


async def verify_offer_subscription(session: AsyncSession, user_id: int,
                                    offer_id: int) -> bool:
    part = (await session.execute(
        select(OfferParticipation).where(
            OfferParticipation.user_id == user_id,
            OfferParticipation.offer_id == offer_id,
        )
    )).scalar_one_or_none()
    if not part:
        return False
    if part.status == "completed":
        return True

    offer = await get_offer_by_id(session, offer_id)
    user = await get_user_by_id(session, user_id)
    if not offer or not user:
        return False

    part.status = "completed"
    part.checked_at = datetime.utcnow()

    today_offer_rewards = await _get_today_offer_rewards_total(session, user_id)
    cap_remaining = max(to_decimal(OFFER_DAILY_REWARD_CAP) - today_offer_rewards, Decimal("0"))
    additional = min(
        to_decimal(offer.reward_final) - to_decimal(part.reward_given),
        cap_remaining,
    )
    if additional > 0:
        await log_balance_change(
            session,
            user,
            additional,
            "offer_complete",
            source_id=offer_id,
        )
        user.balance += additional
        part.reward_given = to_decimal(offer.reward_final)

    await session.commit()
    return True


def calculate_offer_unsubscribe_amounts(offer: "Offer", part: "OfferParticipation") -> tuple[Decimal, Decimal, Decimal]:
    rewarded_total = max(to_decimal(part.reward_given), Decimal("0"))
    if rewarded_total <= 0:
        return Decimal("0"), Decimal("0"), Decimal("0")

    max_extra_penalty = round_coin(rewarded_total * Decimal("0.5"))
    requested_penalty = max(to_decimal(offer.penalty_unsubscribe), Decimal("0"))
    extra_penalty = min(requested_penalty, max_extra_penalty)
    total_charge = round_coin(rewarded_total + extra_penalty)
    return round_coin(rewarded_total), round_coin(extra_penalty), total_charge


async def apply_offer_unsubscribe_penalty(
    session: AsyncSession,
    user: "User",
    offer: "Offer",
    part: "OfferParticipation",
) -> tuple[Decimal, Decimal, Decimal]:
    rewarded_total, extra_penalty, total_charge = calculate_offer_unsubscribe_amounts(offer, part)
    if total_charge <= 0:
        return rewarded_total, extra_penalty, total_charge

    await log_balance_change(
        session,
        user,
        -total_charge,
        "offer_unsubscribe_penalty",
        source_id=offer.id,
        details=f"reward_revoke={rewarded_total}; extra_penalty={extra_penalty}",
    )
    user.balance -= total_charge
    part.status = "unsubscribed"
    part.unsubscribed_penalized_at = datetime.utcnow()
    await session.commit()
    return rewarded_total, extra_penalty, total_charge


async def get_offer_participations_for_subscription_audit(
    session: AsyncSession,
    limit: int = 200,
) -> list["OfferParticipation"]:
    return (await session.execute(
        select(OfferParticipation)
        .where(
            OfferParticipation.status == "completed",
            OfferParticipation.reward_given > 0,
            OfferParticipation.unsubscribed_penalized_at.is_(None),
        )
        .order_by(OfferParticipation.checked_at.desc().nullslast())
        .limit(limit)
    )).scalars().all()


async def admin_create_offer(session: AsyncSession, title: str, description: str,
                             channel_url: str, reward_preview: Decimal,
                             reward_final: Decimal, is_rentable: bool = False,
                             penalty_unsubscribe: Decimal = Decimal("0"),
                             rent_cost_per_day: Decimal = Decimal("0"),
                             max_simultaneous_rentals: int = 1) -> "Offer":
    offer = Offer(
        creator_user_id=None,
        title=title,
        description=description,
        channel_url=channel_url,
        reward_preview=reward_preview,
        reward_final=reward_final,
        penalty_unsubscribe=penalty_unsubscribe,
        is_active=True,
        status="approved",
        is_rentable=is_rentable,
        rent_cost_per_day=rent_cost_per_day,
        max_simultaneous_rentals=max_simultaneous_rentals,
    )
    session.add(offer)
    await session.commit()
    return offer


async def count_active_rentals(session: AsyncSession) -> int:
    try:
        return (await session.execute(
            select(func.count(OfferRental.id)).where(OfferRental.status == "active")
        )).scalar_one()
    except Exception:
        return 0


async def expire_old_rentals(session: AsyncSession) -> int:
    try:
        now = datetime.utcnow()
        expired = (await session.execute(
            select(OfferRental).where(
                OfferRental.status == "active",
                OfferRental.expires_at <= now
            )
        )).scalars().all()
        for r in expired:
            r.status = "expired"
        await session.commit()
        return len(expired)
    except Exception:
        return 0


async def create_offer_rental(session: AsyncSession, offer_id: int, user_id: int,
                              channel_title: str, channel_url: str,
                              rent_days: int) -> tuple["OfferRental | None", str | None]:
    if rent_days < OFFER_MIN_RENT_DAYS or rent_days > OFFER_MAX_RENT_DAYS:
        return None, f"Аренда от {OFFER_MIN_RENT_DAYS} до {OFFER_MAX_RENT_DAYS} дней."
    offer = await get_offer_by_id(session, offer_id)
    if not offer:
        return None, "Оффер не найден."
    if not offer.is_rentable:
        return None, "Этот оффер нельзя арендовать."
    if not offer.is_active:
        return None, "Оффер не активен."
    active_count = (await session.execute(
        select(func.count(OfferRental.id)).where(
            OfferRental.offer_id == offer_id,
            OfferRental.status.in_(["active", "pending"])
        )
    )).scalar_one()
    if active_count >= offer.max_simultaneous_rentals:
        return None, "Все слоты аренды заняты."
    existing = (await session.execute(
        select(OfferRental).where(
            OfferRental.offer_id == offer_id,
            OfferRental.renter_user_id == user_id,
            OfferRental.status.in_(["pending", "active"])
        )
    )).scalar_one_or_none()
    if existing:
        return None, "У вас уже есть аренда этого оффера."

    cost = to_decimal(offer.rent_cost_per_day) * rent_days
    user = await get_user_by_id(session, user_id)
    if not user:
        return None, "Пользователь не найден."
    if user.balance < cost:
        return None, f"Недостаточно монет. Нужно: {cost}, у вас: {user.balance}"

    await log_balance_change(session, user, -cost, "offer_rental", source_id=offer_id,
                             details=f"rent_days={rent_days}")
    user.balance -= cost
    rental = OfferRental(
        offer_id=offer_id,
        renter_user_id=user_id,
        renter_channel_title=channel_title,
        renter_channel_url=channel_url,
        rent_days=rent_days,
        cost_paid=cost,
        status="pending",
    )
    session.add(rental)
    await session.commit()
    return rental, None


async def get_user_rentals(session: AsyncSession, user_id: int) -> list["OfferRental"]:
    return (await session.execute(
        select(OfferRental)
        .where(OfferRental.renter_user_id == user_id)
        .order_by(desc(OfferRental.created_at))
        .limit(10)
    )).scalars().all()


# ============================
# ИГРОВЫЕ СЕССИИ
# ============================
async def get_or_create_game_session(session: AsyncSession, user_id: int) -> GameSession:
    now = datetime.utcnow()
    window_start = now - timedelta(hours=GAME_SESSION_HOURS)
    gs = (await session.execute(
        select(GameSession).where(
            GameSession.user_id == user_id,
            GameSession.window_start >= window_start,
        )
    )).scalar_one_or_none()
    if not gs:
        gs = GameSession(user_id=user_id, window_start=now)
        session.add(gs)
        await session.commit()
    return gs


async def can_play_free_game(session: AsyncSession, user_id: int) -> bool:
    gs = await get_or_create_game_session(session, user_id)
    return gs.games_played < FREE_GAMES_PER_SESSION


async def pay_for_game_session(session: AsyncSession, user_id: int) -> bool:
    user = await get_user_by_id(session, user_id)
    if not user:
        return False
    cost = to_decimal(GAME_SESSION_COST)
    if user.balance < cost:
        return False
    await log_balance_change(session, user, -cost, "game_session_paid")
    user.balance -= cost
    gs = await get_or_create_game_session(session, user_id)
    gs.games_played = 0
    gs.window_start = datetime.utcnow()
    gs.paid_at = datetime.utcnow()
    await session.commit()
    return True


async def increment_game_played(session: AsyncSession, user_id: int):
    gs = await get_or_create_game_session(session, user_id)
    gs.games_played += 1
    await session.commit()


# ============================
# СТАТИСТИКА
# ============================
async def get_admin_extended_stats(session: AsyncSession) -> dict:
    users = (await session.execute(select(func.count(User.id)))).scalar_one()
    vip = (await session.execute(
        select(func.count(User.id)).where(User.vip_until > datetime.utcnow())
    )).scalar_one()
    with_nickname = (await session.execute(
        select(func.count(User.id)).where(User.nickname_set == True)
    )).scalar_one()
    comments = (await session.execute(select(func.count(Comment.id)))).scalar_one()
    reactions = (await session.execute(select(func.count(ContentReaction.id)))).scalar_one()
    games = (await session.execute(select(func.count(GameHistory.id)))).scalar_one()
    offers = (await session.execute(select(func.count(Offer.id)))).scalar_one()
    total_balance = (await session.execute(
        select(func.sum(User.balance))
    )).scalar_one() or Decimal("0")
    total_admin_given = (await session.execute(
        select(func.sum(BalanceLog.amount)).where(
            BalanceLog.source == "admin_balance", BalanceLog.amount > 0
        )
    )).scalar_one() or Decimal("0")
    total_game_profit = (await session.execute(
        select(func.sum(GameHistory.result))
    )).scalar_one() or Decimal("0")
    try:
        active_rentals = (await session.execute(
            select(func.count(OfferRental.id)).where(OfferRental.status == "active")
        )).scalar_one()
        total_rent_income = (await session.execute(
            select(func.sum(BalanceLog.amount)).where(BalanceLog.source == "offer_rental")
        )).scalar_one() or Decimal("0")
    except Exception:
        active_rentals = 0
        total_rent_income = Decimal("0")
    return {
        "users": users, "vip": vip, "with_nickname": with_nickname,
        "comments": comments, "reactions": reactions, "games": games,
        "offers": offers, "active_rentals": active_rentals,
        "total_balance_in_system": total_balance,
        "total_admin_given": total_admin_given,
        "total_game_profit": total_game_profit,
        "total_rent_income": total_rent_income,
    }


async def get_user_dossier(session: AsyncSession, user_id: int) -> dict | None:
    user = await get_user_by_id(session, user_id)
    if not user:
        return None
    games_count = (await session.execute(
        select(func.count(GameHistory.id)).where(GameHistory.user_id == user_id)
    )).scalar_one()
    game_profit = (await session.execute(
        select(func.sum(GameHistory.result)).where(GameHistory.user_id == user_id)
    )).scalar_one() or Decimal("0")
    suspicious_games = (await session.execute(
        select(GameHistory).where(
            GameHistory.user_id == user_id, GameHistory.result > to_decimal(50)
        ).order_by(desc(GameHistory.created_at))
    )).scalars().all()
    videos_uploaded = (await session.execute(
        select(func.count(Video.id)).where(Video.uploader_user_id == user_id)
    )).scalar_one()
    videos_watched = (await session.execute(
        select(func.count(VideoView.id)).where(VideoView.user_id == user_id)
    )).scalar_one()
    comments_count = (await session.execute(
        select(func.count(Comment.id)).where(Comment.user_id == user_id)
    )).scalar_one()
    reactions_count = (await session.execute(
        select(func.count(ContentReaction.id)).where(ContentReaction.user_id == user_id)
    )).scalar_one()
    avg_rating = (await session.execute(
        select(func.avg(VideoRating.rating)).where(
            VideoRating.video_id.in_(
                select(Video.id).where(Video.uploader_user_id == user_id)
            )
        )
    )).scalar_one()
    avg_rating = float(avg_rating) if avg_rating else 0.0
    week_ago = datetime.utcnow() - timedelta(days=7)
    weekly_earned = (await session.execute(
        select(func.sum(BalanceLog.amount)).where(
            BalanceLog.user_id == user_id, BalanceLog.amount > 0,
            BalanceLog.created_at >= week_ago
        )
    )).scalar_one() or Decimal("0")
    weekly_spent = (await session.execute(
        select(func.sum(BalanceLog.amount)).where(
            BalanceLog.user_id == user_id, BalanceLog.amount < 0,
            BalanceLog.created_at >= week_ago
        )
    )).scalar_one() or Decimal("0")
    balance_logs = (await session.execute(
        select(BalanceLog).where(BalanceLog.user_id == user_id)
        .order_by(desc(BalanceLog.created_at)).limit(50)
    )).scalars().all()
    action_logs = (await session.execute(
        select(UserActionLog).where(UserActionLog.user_id == user_id)
        .order_by(desc(UserActionLog.created_at)).limit(20)
    )).scalars().all()
    total_earned = (await session.execute(
        select(func.sum(BalanceLog.amount)).where(
            BalanceLog.user_id == user_id, BalanceLog.amount > 0
        )
    )).scalar_one() or Decimal("0")
    total_spent = (await session.execute(
        select(func.sum(BalanceLog.amount)).where(
            BalanceLog.user_id == user_id, BalanceLog.amount < 0
        )
    )).scalar_one() or Decimal("0")
    admin_given = (await session.execute(
        select(func.sum(BalanceLog.amount)).where(
            BalanceLog.user_id == user_id,
            BalanceLog.source == "admin_balance", BalanceLog.amount > 0
        )
    )).scalar_one() or Decimal("0")
    return {
        "user": user, "games_count": games_count,
        "game_profit": game_profit, "suspicious_games": suspicious_games,
        "videos_uploaded": videos_uploaded, "videos_watched": videos_watched,
        "comments_count": comments_count, "reactions_count": reactions_count,
        "avg_rating": round(avg_rating, 2),
        "weekly_earned": weekly_earned, "weekly_spent": weekly_spent,
        "balance_logs": balance_logs, "action_logs": action_logs,
        "total_earned": total_earned, "total_spent": total_spent,
        "admin_given": admin_given,
    }


# ============================
# ПРОМОКОДЫ
# ============================
def generate_promocode_str(length: int = 10) -> str:
    chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return ''.join(random.choices(chars, k=length))


def calculate_promocode_star_cost(coin_amount: Decimal, max_uses: int) -> int:
    """Рассчёт стоимости промокода в Stars."""
    base = float(coin_amount) * max_uses * PROMOCODE_CREATION_STAR_RATE
    if max_uses >= PROMOCODE_BULK_DISCOUNT_THRESHOLD:
        base *= PROMOCODE_BULK_DISCOUNT_RATE
    return max(1, int(base))


async def create_promocode(
    session: AsyncSession,
    creator_tg_id: int,
    coin_amount: Decimal,
    max_uses: int,
    hours: int = 24,
    is_public: bool = False,
    admin_free: bool = False,
) -> tuple["Promocode | None", int, str | None]:
    """
    Создаёт промокод.
    admin_free=True — бесплатно для админа (без списания Stars).
    Возвращает (промокод, цена_Stars, ошибка).
    """
    user = await get_user(session, creator_tg_id)
    if not user:
        return None, 0, "Пользователь не найден."

    if coin_amount <= 0 or coin_amount > PROMOCODE_MAX_AMOUNT:
        return None, 0, f"Сумма от 1 до {PROMOCODE_MAX_AMOUNT} монет."
    if max_uses < 1 or max_uses > PROMOCODE_MAX_USES:
        return None, 0, f"Использований от 1 до {PROMOCODE_MAX_USES}."
    if hours < 1 or hours > PROMOCODE_MAX_HOURS:
        return None, 0, f"Срок от 1 до {PROMOCODE_MAX_HOURS} часов."

    star_cost = calculate_promocode_star_cost(coin_amount, max_uses)
    is_admin = is_admin_or_super(creator_tg_id, user)

    if not admin_free:
        # Проверка VIP (бесплатный промокод раз в месяц)
        if user.vip_until and user.vip_until > datetime.utcnow():
            this_month = datetime.utcnow().month
            promo_month = user.promo_created_this_month
            # Сбрасываем счётчик если новый месяц
            if promo_month != this_month:
                user.promo_created_this_month = 0
            if user.promo_created_this_month < VIP_FREE_PROMO_PER_MONTH:
                star_cost = 0
                user.promo_created_this_month += 1

        # Если не админ и нужна оплата -> нужен инвойс (здесь просто возвращаем стоимость)
        if star_cost > 0:
            # Проверяем только стоимость, само списание будет через инвойс
            pass

    code = generate_promocode_str()
    expires_at = datetime.utcnow() + timedelta(hours=hours)

    promo = Promocode(
        creator_user_id=user.id,
        code=code,
        coin_amount=to_decimal(coin_amount),
        max_uses=max_uses,
        used_count=0,
        is_active=True,
        is_public=is_public,
        created_via_stars=(star_cost > 0 and not admin_free),
        stars_paid=0 if (admin_free or (star_cost == 0 and user.vip_until)) else star_cost,
        expires_at=expires_at,
    )
    session.add(promo)
    await session.commit()
    await log_user_action(session, user.id, "create_promocode",
                          f"code={code}, amount={coin_amount}, uses={max_uses}, admin_free={admin_free}")
    return promo, star_cost, None


async def activate_promocode(session: AsyncSession, user_id: int, code: str) -> str:
    """Активация промокода. Возвращает сообщение."""
    user = await get_user_by_id(session, user_id)
    if not user:
        return "Пользователь не найден."
    promo = (await session.execute(
        select(Promocode).where(Promocode.code == code.upper().strip())
    )).scalar_one_or_none()
    if not promo:
        return "Промокод не найден."
    if not promo.is_active:
        return "Промокод отключён."
    if promo.expires_at and promo.expires_at < datetime.utcnow():
        return "Промокод истёк."
    if promo.used_count >= promo.max_uses:
        return "Лимит использований исчерпан."
    # Проверка на повторную активацию
    already = (await session.execute(
        select(PromocodeActivation).where(
            PromocodeActivation.promocode_id == promo.id,
            PromocodeActivation.user_id == user_id,
        )
    )).scalar_one_or_none()
    if already:
        return "Вы уже активировали этот промокод."
    # Начисление
    amount = promo.coin_amount
    await log_balance_change(session, user, amount, "promocode_activation",
                             details=f"code={promo.code}")
    user.balance += amount
    promo.used_count += 1
    if promo.used_count >= promo.max_uses:
        promo.is_active = False
    # Запись активации
    activation = PromocodeActivation(promocode_id=promo.id, user_id=user_id)
    session.add(activation)
    # Бонус создателю
    if PROMOCODE_CREATOR_BONUS_PERCENT > 0:
        creator = await get_user_by_id(session, promo.creator_user_id)
        if creator and creator.id != user_id:
            bonus = amount * to_decimal(PROMOCODE_CREATOR_BONUS_PERCENT / 100)
            await log_balance_change(session, creator, bonus, "promocode_creator_bonus",
                                     details=f"code={promo.code}, activator={user_id}")
            creator.balance += bonus
    await session.commit()
    return f"✅ Промокод активирован! Начислено {amount} монет."


async def create_feedback(
    session: AsyncSession,
    user_id: int,
    kind: str,
    text_value: str,
) -> Feedback:
    feedback = Feedback(
        user_id=user_id,
        kind=kind,
        text=text_value.strip(),
        status="new",
    )
    session.add(feedback)
    await session.commit()
    return feedback


async def get_recent_feedback(session: AsyncSession, limit: int = 20) -> list[Feedback]:
    return (await session.execute(
        select(Feedback)
        .order_by(desc(Feedback.created_at))
        .limit(limit)
    )).scalars().all()


# ============================
# ЛОТЕРЕЯ-ЛОТО
# ============================
def _week_key(dt: datetime) -> str:
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _serialize_numbers(nums: list[int]) -> str:
    return ",".join(str(n) for n in sorted(nums))


def _deserialize_numbers(raw: str | None) -> list[int]:
    if not raw:
        return []
    return [int(x) for x in raw.split(",") if x.strip().isdigit()]


async def ensure_current_lottery_round(session: AsyncSession) -> LotteryRound:
    now = datetime.utcnow()
    key = _week_key(now)
    existing = (await session.execute(
        select(LotteryRound).where(LotteryRound.week_key == key)
    )).scalar_one_or_none()
    if existing:
        return existing

    week_start = now - timedelta(days=now.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(days=6, hours=23, minutes=59)
    draw_start = week_start + timedelta(days=6, hours=LOTTERY_DRAW_START_HOUR_UTC)
    draw_end = week_start + timedelta(days=6, hours=LOTTERY_DRAW_END_HOUR_UTC)
    if draw_end <= draw_start:
        draw_end = draw_start + timedelta(hours=2)

    round_obj = LotteryRound(
        week_key=key,
        status="open",
        ticket_price=to_decimal(LOTTERY_TICKET_PRICE),
        numbers_pool=max(10, LOTTERY_NUMBERS_POOL),
        numbers_per_ticket=max(3, LOTTERY_NUMBERS_PER_TICKET),
        drawn_numbers="",
        prize_pool=Decimal("0"),
        starts_at=week_start,
        draw_starts_at=draw_start,
        draw_ends_at=draw_end,
    )
    session.add(round_obj)
    await session.commit()
    return round_obj


async def get_latest_lottery_round(session: AsyncSession) -> LotteryRound | None:
    return (await session.execute(
        select(LotteryRound).order_by(desc(LotteryRound.created_at)).limit(1)
    )).scalar_one_or_none()


async def buy_lottery_ticket(session: AsyncSession, user: User) -> tuple[LotteryTicket | None, str | None]:
    round_obj = await ensure_current_lottery_round(session)
    now = datetime.utcnow()
    if round_obj.status != "open" or now >= round_obj.draw_starts_at:
        return None, "Продажа билетов закрыта до следующей недели."

    price = to_decimal(round_obj.ticket_price)
    if user.balance < price:
        return None, f"Недостаточно монет. Билет стоит {price}."

    pool = list(range(1, round_obj.numbers_pool + 1))
    pick_count = min(round_obj.numbers_per_ticket, len(pool))
    numbers = sorted(random.sample(pool, k=pick_count))
    ticket = LotteryTicket(
        round_id=round_obj.id,
        user_id=user.id,
        numbers=_serialize_numbers(numbers),
    )
    user.balance -= price
    round_obj.prize_pool += price
    await log_balance_change(
        session,
        user,
        -price,
        "lottery_ticket_purchase",
        source_id=round_obj.id,
        details=f"numbers={ticket.numbers}",
    )
    session.add(ticket)
    await session.commit()
    return ticket, None


async def get_user_lottery_tickets(
    session: AsyncSession,
    user_id: int,
    round_id: int | None = None,
    limit: int = 20,
) -> list[LotteryTicket]:
    query = select(LotteryTicket).where(LotteryTicket.user_id == user_id)
    if round_id is not None:
        query = query.where(LotteryTicket.round_id == round_id)
    return (await session.execute(
        query.order_by(desc(LotteryTicket.created_at)).limit(limit)
    )).scalars().all()


def get_lottery_state_dict(round_obj: LotteryRound | None) -> dict:
    if not round_obj:
        return {"status": "no_round"}
    drawn = _deserialize_numbers(round_obj.drawn_numbers)
    return {
        "round_id": round_obj.id,
        "week_key": round_obj.week_key,
        "status": round_obj.status,
        "ticket_price": float(round_obj.ticket_price),
        "prize_pool": float(round_obj.prize_pool),
        "numbers_pool": round_obj.numbers_pool,
        "numbers_per_ticket": round_obj.numbers_per_ticket,
        "drawn_numbers": drawn,
        "draw_starts_at": round_obj.draw_starts_at.isoformat(),
        "draw_ends_at": round_obj.draw_ends_at.isoformat(),
    }


async def draw_next_lottery_number(session: AsyncSession, round_obj: LotteryRound) -> int | None:
    drawn = set(_deserialize_numbers(round_obj.drawn_numbers))
    all_numbers = set(range(1, round_obj.numbers_pool + 1))
    available = sorted(all_numbers - drawn)
    if not available:
        return None
    next_num = random.choice(available)
    drawn.add(next_num)
    round_obj.drawn_numbers = _serialize_numbers(list(drawn))
    if len(drawn) >= round_obj.numbers_per_ticket:
        round_obj.status = "completed"
    else:
        round_obj.status = "drawing"
    await session.commit()
    return next_num


async def settle_lottery_round(session: AsyncSession, round_obj: LotteryRound) -> dict:
    drawn = set(_deserialize_numbers(round_obj.drawn_numbers))
    tickets = (await session.execute(
        select(LotteryTicket).where(LotteryTicket.round_id == round_obj.id)
    )).scalars().all()
    if not tickets:
        round_obj.status = "completed"
        await session.commit()
        return {"tickets": 0, "winners": 0, "paid_total": 0.0}

    winners_6: list[LotteryTicket] = []
    winners_5: list[LotteryTicket] = []
    winners_4: list[LotteryTicket] = []
    for t in tickets:
        matched = len(set(_deserialize_numbers(t.numbers)) & drawn)
        t.matched_count = matched
        if matched >= 6:
            winners_6.append(t)
        elif matched == 5:
            winners_5.append(t)
        elif matched == 4:
            winners_4.append(t)

    pool = to_decimal(round_obj.prize_pool)
    payout_map = [
        (winners_6, to_decimal(0.70), "lottery_win_6"),
        (winners_5, to_decimal(0.20), "lottery_win_5"),
        (winners_4, to_decimal(0.10), "lottery_win_4"),
    ]
    paid_total = Decimal("0")
    for winner_group, share, source in payout_map:
        if not winner_group:
            continue
        group_total = round_coin(pool * share)
        per_ticket = round_coin(group_total / len(winner_group))
        for t in winner_group:
            user = await get_user_by_id(session, t.user_id)
            if not user or t.reward_paid:
                continue
            user.balance += per_ticket
            t.reward_paid = True
            paid_total += per_ticket
            await log_balance_change(
                session,
                user,
                per_ticket,
                source,
                source_id=round_obj.id,
                details=f"ticket_id={t.id}; matched={t.matched_count}",
            )

    round_obj.status = "completed"
    await session.commit()
    return {
        "tickets": len(tickets),
        "winners": len(winners_6) + len(winners_5) + len(winners_4),
        "paid_total": float(paid_total),
    }

# ============================
# УМНЫЕ ОФФЕРЫ
# ============================
async def get_or_create_user_ad_state(session: AsyncSession, user_id: int) -> "UserAdState":
    state = (await session.execute(
        select(UserAdState).where(UserAdState.user_id == user_id)
    )).scalar_one_or_none()
    if not state:
        state = UserAdState(user_id=user_id)
        session.add(state)
        await session.flush()
    return state


async def can_show_offer_to_user(session: AsyncSession, user_id: int) -> bool:
    state = await get_or_create_user_ad_state(session, user_id)
    if state.last_offer_shown_at is None:
        return True
    elapsed = (datetime.utcnow() - state.last_offer_shown_at).total_seconds() / 60
    return elapsed >= SMART_AD_MIN_INTERVAL_MINUTES


async def mark_offer_shown(session: AsyncSession, user_id: int,
                           offer_id: int = None, forced: bool = False) -> None:
    state = await get_or_create_user_ad_state(session, user_id)
    state.last_offer_shown_at = datetime.utcnow()
    state.updated_at = datetime.utcnow()
    if forced and offer_id:
        state.forced_offer_id = offer_id
        state.forced_offer_shown_at = datetime.utcnow()
    await session.commit()


async def should_show_low_balance_hint(session: AsyncSession, user: "User") -> bool:
    if float(user.balance) > SMART_AD_LOW_BALANCE_THRESHOLD:
        return False
    state = await get_or_create_user_ad_state(session, user.id)
    if state.last_low_balance_hint_at is None:
        return True
    elapsed = (datetime.utcnow() - state.last_low_balance_hint_at).total_seconds() / 60
    return elapsed >= SMART_AD_LOW_BALANCE_HINT_INTERVAL_MINUTES


async def mark_low_balance_hint_shown(session: AsyncSession, user_id: int) -> None:
    state = await get_or_create_user_ad_state(session, user_id)
    state.last_low_balance_hint_at = datetime.utcnow()
    state.updated_at = datetime.utcnow()
    await session.commit()


async def get_random_active_offer(session: AsyncSession) -> "Offer | None":
    return (await session.execute(
        select(Offer).where(
            Offer.is_active == True, Offer.status == "approved",
        ).order_by(func.random()).limit(1)
    )).scalar_one_or_none()


def should_inject_ad_in_video() -> bool:
    return random.random() < SMART_AD_VIDEO_CHANCE
