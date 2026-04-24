import uuid
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    User, Video, VideoView, VideoRating,
    Payment, Offer, OfferParticipation, OfferRental,
    Comment, ContentReaction, GameHistory,
    DailyQuestProgress, GameSession,
    UserActionLog, BalanceLog,
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
)

PHOTO_UPLOAD_REWARD = Decimal("0.1")
OFFER_STEP_1_REWARD = Decimal("5")
OFFER_PENALTY = Decimal("40")
GAME_SESSION_LIMIT = 10
GAME_SESSION_COST = Decimal("10")
GAME_SESSION_HOURS = 4


# =========================
# УТИЛИТЫ
# =========================
def to_decimal(val) -> Decimal:
    return Decimal(str(val))


def round_coin(val: Decimal) -> Decimal:
    return val.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def get_display_name(user: "User") -> str:
    """Отображаемое имя пользователя."""
    if user.display_name:
        return user.display_name
    if user.first_name:
        return user.first_name
    if user.username:
        return f"@{user.username}"
    return f"User#{user.telegram_id}"


# =========================
# ЛОГИРОВАНИЕ
# =========================
async def log_balance_change(
    session: AsyncSession,
    user: "User",
    amount: Decimal,
    source: str,
    source_id: int = None,
    admin_id: int = None,
    details: str = None,
):
    """Логирует каждое изменение баланса."""
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


# =========================
# ПОЛЬЗОВАТЕЛИ
# =========================
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
            await log_balance_change(
                session, inviter,
                to_decimal(REFERRAL_REWARD_INVITER),
                "referral_inviter",
                details=f"New user tg_id={telegram_id}"
            )
            inviter.balance += to_decimal(REFERRAL_REWARD_INVITER)
            inviter.referral_earnings += to_decimal(REFERRAL_REWARD_INVITER)
            starting_bonus += to_decimal(REFERRAL_REWARD_NEW_USER)

    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        balance=starting_bonus,
        referral_code=uuid.uuid4().hex[:8],
        referred_by_user_id=referred_by,
        is_admin=False,
        nickname_set=False,
    )
    session.add(user)
    await session.flush()

    await log_balance_change(
        session, user, starting_bonus,
        "registration",
        details=f"Starting balance. Referred by: {referred_by}"
    )
    await session.commit()
    await log_user_action(
        session, user.id,
        "registration",
        f"tg_id={telegram_id}, referred_by={referred_by}"
    )
    return user, True


# =========================
# НИКИ
# =========================
async def set_display_name(
    session: AsyncSession,
    user: "User",
    name: str
) -> tuple[bool, str]:
    import re

    name = name.strip()

    if len(name) < NICKNAME_MIN_LENGTH:
        return False, f"❌ Ник слишком короткий. Минимум {NICKNAME_MIN_LENGTH} символа."
    if len(name) > NICKNAME_MAX_LENGTH:
        return False, f"❌ Ник слишком длинный. Максимум {NICKNAME_MAX_LENGTH} символов."

    if not re.match(r'^[a-zA-Zа-яА-ЯёЁ0-9_\-]+$', name):
        return False, (
            "❌ Ник может содержать только буквы (рус/лат), цифры, _ и -\n"
            "Точки, пробелы и спецсимволы запрещены."
        )

    if len(set(name.lower().replace("_", "").replace("-", ""))) < 2:
        return False, "❌ Ник должен содержать хотя бы 2 разных буквы/цифры."

    existing = await get_user_by_display_name(session, name)
    if existing and existing.id != user.id:
        return False, "❌ Этот ник уже занят. Придумайте другой."

    is_first = not user.nickname_set

    if not is_first:
        cost = to_decimal(NICKNAME_CHANGE_COST)
        if user.balance < cost:
            return False, (
                f"❌ Недостаточно монет для смены ника.\n"
                f"Нужно: {cost}, у вас: {user.balance}"
            )
        old_name = user.display_name
        await log_balance_change(
            session, user, -cost,
            "nickname_change",
            details=f"{old_name} -> {name}"
        )
        user.balance -= cost

    old_name = user.display_name
    user.display_name = name
    user.nickname_set = True
    await session.commit()
    await log_user_action(
        session, user.id,
        "set_nickname",
        f"{old_name} -> {name}"
    )

    if is_first:
        return True, f"✅ Ник <b>{name}</b> установлен бесплатно!"
    return True, f"✅ Ник изменён на <b>{name}</b>! Списано {NICKNAME_CHANGE_COST} монет."


# =========================
# ВИДЕО / МОДЕРАЦИЯ
# =========================
async def approve_video(session: AsyncSession, video_id: int) -> "Video | None":
    v = (await session.execute(
        select(Video).where(Video.id == video_id)
    )).scalar_one_or_none()
    if not v or v.status != "pending":
        return v
    v.status = "approved"
    uploader = await get_user_by_id(session, v.uploader_user_id)
    if uploader:
        reward = (
            PHOTO_UPLOAD_REWARD
            if v.content_type == "photo"
            else to_decimal(UPLOAD_REWARD)
        )
        await log_balance_change(
            session, uploader, reward,
            "upload_approved", source_id=v.id
        )
        uploader.balance += reward
        await log_user_action(
            session, uploader.id,
            "video_approved",
            f"video_id={v.id}, reward={reward}"
        )
    await session.commit()
    return v


async def reject_video(
    session: AsyncSession,
    video_id: int,
    reason: str
) -> "Video | None":
    v = (await session.execute(
        select(Video).where(Video.id == video_id)
    )).scalar_one_or_none()
    if not v:
        return None
    v.status = "rejected"
    v.rejection_reason = reason
    await session.commit()
    await log_user_action(
        session, v.uploader_user_id,
        "video_rejected",
        f"video_id={v.id}, reason={reason}"
    )
    return v


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


async def save_video(
    session: AsyncSession,
    user_id: int,
    file_id: str,
    file_unique_id: str,
    duration: int = None,
    file_size: int = None,
) -> tuple["Video", bool]:
    """Возвращает (video, is_duplicate)"""
    # Проверка дубликата по file_unique_id
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


async def save_photo(
    session: AsyncSession,
    user_id: int,
    file_id: str,
    file_unique_id: str,
    file_size: int = None,
) -> tuple["Video", bool]:
    """Возвращает (photo, is_duplicate)"""
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

async def get_random_video_for_user(
    session: AsyncSession,
    user_id: int
) -> "Video | None":
    viewed = select(VideoView.video_id).where(VideoView.user_id == user_id)
    return (await session.execute(
        select(Video).where(
            Video.status == "approved",
            Video.content_type == "video",
            Video.uploader_user_id != user_id,
            ~Video.id.in_(viewed)
        ).order_by(func.random()).limit(1)
    )).scalar_one_or_none()


async def get_random_photo_for_user(
    session: AsyncSession,
    user_id: int
) -> "Video | None":
    return (await session.execute(
        select(Video).where(
            Video.status == "approved",
            Video.content_type == "photo",
            Video.uploader_user_id != user_id,
        ).order_by(func.random()).limit(1)
    )).scalar_one_or_none()


async def record_view_and_charge(
    session: AsyncSession,
    user_id: int,
    video_id: int
) -> bool:
    user = await get_user_by_id(session, user_id)
    if not user:
        return False
    cost = to_decimal(WATCH_COST)
    if user.balance < cost:
        return False
    await log_balance_change(
        session, user, -cost, "watch", source_id=video_id
    )
    user.balance -= cost
    from app.config import XP_PER_WATCH
    user.xp += XP_PER_WATCH
    view = VideoView(user_id=user_id, video_id=video_id)
    session.add(view)
    try:
        await session.commit()
        return True
    except Exception:
        await session.rollback()
        return False


async def record_photo_view(
    session: AsyncSession,
    user_id: int,
    photo_id: int
):
    view = VideoView(user_id=user_id, video_id=photo_id)
    session.add(view)
    try:
        await session.commit()
    except Exception:
        await session.rollback()


async def rate_video(
    session: AsyncSession,
    user_id: int,
    video_id: int,
    rating: int
):
    existing = (await session.execute(
        select(VideoRating).where(
            VideoRating.user_id == user_id,
            VideoRating.video_id == video_id
        )
    )).scalar_one_or_none()
    if existing:
        existing.rating = rating
    else:
        session.add(VideoRating(
            user_id=user_id,
            video_id=video_id,
            rating=rating
        ))
    await session.commit()


# =========================
# БАЛАНС / БОНУС
# =========================
async def claim_daily_bonus(
    session: AsyncSession,
    user_id: int
) -> tuple[bool, object]:
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
    return (await session.execute(
        select(func.count(User.id)).where(User.referred_by_user_id == user_id)
    )).scalar_one()


async def update_user_balance(
    session: AsyncSession,
    user_id: int,
    amount: Decimal,
    admin_id: int
) -> bool:
    user = await get_user_by_id(session, user_id)
    if not user:
        return False
    await log_balance_change(
        session, user, amount,
        "admin_balance",
        admin_id=admin_id,
        details=f"Manual by admin {admin_id}"
    )
    user.balance += amount
    await log_user_action(
        session, user_id,
        "balance_update",
        f"admin={admin_id}, amount={amount}"
    )
    await session.commit()
    return True


async def set_user_ban_status(
    session: AsyncSession,
    user_id: int,
    is_banned: bool,
    admin_id: int
) -> bool:
    user = await get_user_by_id(session, user_id)
    if not user:
        return False
    user.status = "banned" if is_banned else "active"
    await log_user_action(
        session, user_id,
        "ban_status_change",
        f"admin={admin_id}, banned={is_banned}"
    )
    await session.commit()
    return True


# =========================
# ПЛАТЕЖИ
# =========================
async def create_payment(
    session: AsyncSession,
    user_id: int,
    pack_key: str
) -> "Payment | None":
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


async def create_custom_payment(
    session: AsyncSession,
    user_id: int,
    stars: int
) -> "Payment":
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


async def apply_successful_payment(
    session: AsyncSession,
    payload: str
) -> "Payment | None":
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
            "stars_payment",
            source_id=payment.id,
            details=f"stars={payment.stars_amount}, payload={payload}"
        )
        user.balance += payment.coins_amount
    await session.commit()
    return payment


# =========================
# ОФФЕРЫ
# =========================
async def get_active_offers(session: AsyncSession) -> list["Offer"]:
    return (await session.execute(
        select(Offer).where(
            Offer.is_active == True,
            Offer.status == "approved"
        ).order_by(desc(Offer.created_at))
    )).scalars().all()


async def get_rentable_offers(session: AsyncSession) -> list["Offer"]:
    """Офферы доступные для аренды."""
    return (await session.execute(
        select(Offer).where(
            Offer.is_active == True,
            Offer.status == "approved",
            Offer.is_rentable == True,
        ).order_by(desc(Offer.created_at))
    )).scalars().all()


async def get_offer_by_id(
    session: AsyncSession,
    offer_id: int
) -> "Offer | None":
    return (await session.execute(
        select(Offer).where(Offer.id == offer_id)
    )).scalar_one_or_none()


async def start_offer_participation(
    session: AsyncSession,
    user_id: int,
    offer_id: int
) -> tuple["OfferParticipation | None", bool]:
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
        reward_given=offer.reward_preview,
    )
    session.add(part)
    await session.commit()
    return part, True


async def verify_offer_subscription(
    session: AsyncSession,
    user_id: int,
    offer_id: int
) -> bool:
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


async def admin_create_offer(
    session: AsyncSession,
    title: str,
    description: str,
    channel_url: str,
    reward_preview: Decimal,
    reward_final: Decimal,
    is_rentable: bool = False,
    rent_cost_per_day: Decimal = Decimal("0"),
    max_simultaneous_rentals: int = 1,
) -> "Offer":
    """Создание оффера администратором — бесплатно, сразу активен."""
    offer = Offer(
        creator_user_id=None,
        title=title,
        description=description,
        channel_url=channel_url,
        reward_preview=reward_preview,
        reward_final=reward_final,
        is_active=True,
        status="approved",
        is_rentable=is_rentable,
        rent_cost_per_day=rent_cost_per_day,
        max_simultaneous_rentals=max_simultaneous_rentals,
    )
    session.add(offer)
    await session.commit()
    return offer


# =========================
# АРЕНДА ОФФЕРОВ
# =========================
async def count_active_rentals(session: AsyncSession) -> int:
    try:
        return (await session.execute(
            select(func.count(OfferRental.id)).where(
                OfferRental.status == "active"
            )
        )).scalar_one()
    except Exception:
        return 0


async def expire_old_rentals(session: AsyncSession) -> int:
    """Завершает просроченные аренды."""
    try:
        now = datetime.utcnow()
        expired = (await session.execute(
            select(OfferRental).where(
                OfferRental.status == "active",
                OfferRental.expires_at <= now
            )
        )).scalars().all()
        count = 0
        for r in expired:
            r.status = "expired"
            count += 1
        await session.commit()
        return count
    except Exception:
        return 0


async def create_offer_rental(
    session: AsyncSession,
    offer_id: int,
    user_id: int,
    channel_title: str,
    channel_url: str,
    rent_days: int,
) -> tuple["OfferRental | None", "str | None"]:
    """
    Создать заявку на аренду рекламного слота.
    Возвращает (rental, None) при успехе или (None, error_text).
    """
    if rent_days < OFFER_MIN_RENT_DAYS or rent_days > OFFER_MAX_RENT_DAYS:
        return None, (
            f"❌ Допустимое количество дней: "
            f"{OFFER_MIN_RENT_DAYS}–{OFFER_MAX_RENT_DAYS}."
        )

    offer = await get_offer_by_id(session, offer_id)
    if not offer:
        return None, "❌ Оффер не найден."
    if not offer.is_rentable:
        return None, "❌ Этот оффер не поддерживает аренду."
    if not offer.is_active:
        return None, "❌ Оффер неактивен."

    # Проверяем количество слотов
    active_count = (await session.execute(
        select(func.count(OfferRental.id)).where(
            OfferRental.offer_id == offer_id,
            OfferRental.status.in_(["active", "pending"])
        )
    )).scalar_one()
    if active_count >= offer.max_simultaneous_rentals:
        return None, (
            f"❌ Все слоты заняты ({active_count}/{offer.max_simultaneous_rentals}).\n"
            f"Попробуйте позже."
        )

    # Нет ли уже аренды у этого пользователя
    existing = (await session.execute(
        select(OfferRental).where(
            OfferRental.offer_id == offer_id,
            OfferRental.renter_user_id == user_id,
            OfferRental.status.in_(["pending", "active"])
        )
    )).scalar_one_or_none()
    if existing:
        return None, "❌ У вас уже есть активная или ожидающая аренда в этом оффере."

    cost = to_decimal(offer.rent_cost_per_day) * rent_days
    user = await get_user_by_id(session, user_id)
    if not user:
        return None, "❌ Пользователь не найден."
    if user.balance < cost:
        return None, f"❌ Недостаточно монет.\nНужно: {cost}, у вас: {user.balance}"

    await log_balance_change(
        session, user, -cost,
        "offer_rental", source_id=offer_id,
        details=f"Аренда {rent_days} дней: {channel_title}"
    )
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


async def get_user_rentals(
    session: AsyncSession,
    user_id: int
) -> list["OfferRental"]:
    return (await session.execute(
        select(OfferRental)
        .where(OfferRental.renter_user_id == user_id)
        .order_by(desc(OfferRental.created_at))
        .limit(10)
    )).scalars().all()


# =========================
# СТАТИСТИКА
# =========================
async def get_admin_extended_stats(session: AsyncSession) -> dict:
    users = (await session.execute(
        select(func.count(User.id))
    )).scalar_one()

    vip = (await session.execute(
        select(func.count(User.id)).where(User.vip_until > datetime.utcnow())
    )).scalar_one()

    with_nickname = (await session.execute(
        select(func.count(User.id)).where(User.nickname_set == True)
    )).scalar_one()

    comments = (await session.execute(
        select(func.count(Comment.id))
    )).scalar_one()

    reactions = (await session.execute(
        select(func.count(ContentReaction.id))
    )).scalar_one()

    games = (await session.execute(
        select(func.count(GameHistory.id))
    )).scalar_one()

    offers = (await session.execute(
        select(func.count(Offer.id))
    )).scalar_one()

    total_balance = (await session.execute(
        select(func.sum(User.balance))
    )).scalar_one() or Decimal("0")

    total_admin_given = (await session.execute(
        select(func.sum(BalanceLog.amount)).where(
            BalanceLog.source == "admin_balance",
            BalanceLog.amount > 0
        )
    )).scalar_one() or Decimal("0")

    total_game_profit = (await session.execute(
        select(func.sum(GameHistory.result))
    )).scalar_one() or Decimal("0")

    try:
        active_rentals = (await session.execute(
            select(func.count(OfferRental.id)).where(
                OfferRental.status == "active"
            )
        )).scalar_one()

        total_rent_income = (await session.execute(
            select(func.sum(BalanceLog.amount)).where(
                BalanceLog.source == "offer_rental"
            )
        )).scalar_one() or Decimal("0")
    except Exception:
        active_rentals = 0
        total_rent_income = Decimal("0")

    return {
        "users": users,
        "vip": vip,
        "with_nickname": with_nickname,
        "comments": comments,
        "reactions": reactions,
        "games": games,
        "offers": offers,
        "active_rentals": active_rentals,
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

    balance_logs = (await session.execute(
        select(BalanceLog).where(BalanceLog.user_id == user_id)
        .order_by(desc(BalanceLog.created_at))
        .limit(50)
    )).scalars().all()

    total_earned = (await session.execute(
        select(func.sum(BalanceLog.amount)).where(
            BalanceLog.user_id == user_id,
            BalanceLog.amount > 0
        )
    )).scalar_one() or Decimal("0")

    total_spent = (await session.execute(
        select(func.sum(BalanceLog.amount)).where(
            BalanceLog.user_id == user_id,
            BalanceLog.amount < 0
        )
    )).scalar_one() or Decimal("0")

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
# =========================
# УМНАЯ РЕКЛАМА
# =========================
from app.config import (
    SMART_AD_MIN_INTERVAL_MINUTES,
    SMART_AD_LOW_BALANCE_THRESHOLD,
    SMART_AD_LOW_BALANCE_HINT_INTERVAL_MINUTES,
    SMART_AD_VIDEO_CHANCE,
    SMART_AD_FORCED_WATCH_SECONDS,
)


async def get_or_create_user_ad_state(
    session: AsyncSession,
    user_id: int,
) -> "UserAdState":
    from app.models import UserAdState
    state = (await session.execute(
        select(UserAdState).where(UserAdState.user_id == user_id)
    )).scalar_one_or_none()
    if not state:
        state = UserAdState(user_id=user_id)
        session.add(state)
        await session.flush()
    return state


async def can_show_offer_to_user(
    session: AsyncSession,
    user_id: int,
) -> bool:
    """Проверяет, прошло ли достаточно времени с последнего показа оффера."""
    from app.models import UserAdState
    state = await get_or_create_user_ad_state(session, user_id)
    if state.last_offer_shown_at is None:
        return True
    elapsed = (datetime.utcnow() - state.last_offer_shown_at).total_seconds() / 60
    return elapsed >= SMART_AD_MIN_INTERVAL_MINUTES


async def mark_offer_shown(
    session: AsyncSession,
    user_id: int,
    offer_id: int | None = None,
    forced: bool = False,
) -> None:
    """Обновляет время последнего показа оффера."""
    state = await get_or_create_user_ad_state(session, user_id)
    state.last_offer_shown_at = datetime.utcnow()
    state.updated_at = datetime.utcnow()
    if forced and offer_id:
        state.forced_offer_id = offer_id
        state.forced_offer_shown_at = datetime.utcnow()
    await session.commit()


async def should_show_low_balance_hint(
    session: AsyncSession,
    user: "User",
) -> bool:
    """
    Возвращает True если:
    - баланс ниже порога
    - прошло достаточно времени с последней подсказки
    """
    if float(user.balance) > SMART_AD_LOW_BALANCE_THRESHOLD:
        return False
    state = await get_or_create_user_ad_state(session, user.id)
    if state.last_low_balance_hint_at is None:
        return True
    elapsed = (datetime.utcnow() - state.last_low_balance_hint_at).total_seconds() / 60
    return elapsed >= SMART_AD_LOW_BALANCE_HINT_INTERVAL_MINUTES


async def mark_low_balance_hint_shown(
    session: AsyncSession,
    user_id: int,
) -> None:
    state = await get_or_create_user_ad_state(session, user_id)
    state.last_low_balance_hint_at = datetime.utcnow()
    state.updated_at = datetime.utcnow()
    await session.commit()


async def get_random_active_offer(session: AsyncSession) -> "Offer | None":
    """Возвращает случайный активный оффер для принудительного показа."""
    return (await session.execute(
        select(Offer).where(
            Offer.is_active == True,
            Offer.status == "approved",
        ).order_by(func.random()).limit(1)
    )).scalar_one_or_none()


def should_inject_ad_in_video() -> bool:
    """35% шанс показа рекламы во время просмотра видео."""
    import random
    return random.random() < SMART_AD_VIDEO_CHANCE