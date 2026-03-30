import uuid
import random
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN

from sqlalchemy import select, func
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
    LEVEL_XP_BASE,
    LEVEL_XP_MULTIPLIER,
    XP_PER_WATCH,
    XP_PER_UPLOAD,
    XP_PER_RATING,
    XP_PER_COMMENT,
    XP_PER_REACTION,
    XP_PER_GAME,
    VIP_PRICE_STARS,
    VIP_DURATION_DAYS,
    VIP_BONUS_MULTIPLIER,
    VIP_WATCH_DISCOUNT,
    LOOTBOX_COST,
    LOOTBOX_REWARDS,
    DICE_MIN_BET,
    DICE_MAX_BET,
    DAILY_QUESTS,
    PREMIUM_DAILY_QUESTS,
    REACTION_TYPES,
    COMMENTS_PER_10_MIN,
    COMMENT_MIN_INTERVAL_SEC,
    WEEKLY_TOP1_REWARD,
    WEEKLY_TOP2_REWARD,
    WEEKLY_TOP3_REWARD,
    PIN_OFFER_COST,
    BUMP_VIDEO_COST,
)

BONUS_AMOUNT = Decimal("1.00")
BONUS_COOLDOWN_HOURS = 4
PHOTO_UPLOAD_REWARD = Decimal("0.10")
FREE_PHOTO_LIMIT_PER_4H = 20
OFFER_STEP_1_REWARD = Decimal("5.00")
OFFER_PENALTY = Decimal("40.00")


def to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_coin(v) -> Decimal:
    return to_decimal(v).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


# ========== FORMAT ==========

def format_duration(seconds):
    if not seconds:
        return "0 \u0441\u0435\u043a"

    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60

    if h > 0:
        return f"{h}\u0447 {m:02d}\u043c {s:02d}\u0441"
    if m > 0:
        return f"{m}\u043c {s:02d}\u0441"
    return f"{s}\u0441"


def format_file_size(b):
    if not b:
        return "0"
    if b >= 1048576:
        return f"{b / 1048576:.1f}MB"
    if b >= 1024:
        return f"{b / 1024:.1f}KB"
    return f"{b}B"


# ========== LEVELS ==========

def calc_level_info(total_xp):
    level = 1
    xp_rem = total_xp

    while True:
        needed = int(LEVEL_XP_BASE * (LEVEL_XP_MULTIPLIER ** (level - 1)))
        if xp_rem < needed:
            return level, xp_rem, needed
        xp_rem -= needed
        level += 1


async def add_xp(session, user, amount):
    user.xp += int(amount)
    new_level, _, _ = calc_level_info(user.xp)
    old_level = user.level
    user.level = new_level
    await session.commit()
    return new_level > old_level, new_level


# ========== VIP ==========

def is_vip(user):
    if not user.vip_until:
        return False
    return user.vip_until > datetime.utcnow()


def get_watch_cost_for_user(user):
    base = to_decimal(WATCH_COST)
    if is_vip(user):
        discounted = base * to_decimal(VIP_WATCH_DISCOUNT)
        return round_coin(discounted)
    return round_coin(base)


async def activate_vip(session, user):
    now = datetime.utcnow()
    if user.vip_until and user.vip_until > now:
        user.vip_until = user.vip_until + timedelta(days=VIP_DURATION_DAYS)
    else:
        user.vip_until = now + timedelta(days=VIP_DURATION_DAYS)

    await session.commit()
    await session.refresh(user)
    return user


async def create_vip_payment(session, user):
    payload = f"vip:{user.telegram_id}:{uuid.uuid4().hex[:12]}"
    payment = Payment(
        user_id=user.id,
        payload=payload,
        stars_amount=VIP_PRICE_STARS,
        coins_amount=Decimal("0"),
        status="pending",
    )
    session.add(payment)
    await session.commit()
    await session.refresh(payment)
    return payment


# ========== ADMINS ==========

async def get_user_by_username(session, username):
    clean = username.strip().lstrip("@").lower()
    stmt = select(User).where(func.lower(User.username) == clean)
    return (await session.execute(stmt)).scalar_one_or_none()


async def set_user_admin(session, user, value):
    user.is_admin = bool(value)
    await session.commit()
    await session.refresh(user)
    return user


async def get_db_admins(session):
    stmt = select(User).where(User.is_admin == True).order_by(User.id)
    return list((await session.execute(stmt)).scalars().all())


# ========== USER ==========

async def get_user(session, telegram_id):
    stmt = select(User).where(User.telegram_id == telegram_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_user_by_id(session, user_id):
    return (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()


async def get_user_by_referral_code(session, code):
    return (await session.execute(select(User).where(User.referral_code == code))).scalar_one_or_none()


async def get_all_users(session):
    return list(
        (await session.execute(select(User).where(User.agreed_to_rules == True))).scalars().all()
    )


async def get_or_create_user(
    session,
    telegram_id,
    username=None,
    first_name=None,
    last_name=None,
    referral_code=None,
):
    user = await get_user(session, telegram_id)

    if user:
        user.username = username
        user.first_name = first_name
        user.last_name = last_name
        await session.commit()
        await session.refresh(user)
        return user, False

    referred_by = None
    inviter = None

    if referral_code:
        inviter = await get_user_by_referral_code(session, referral_code)
        if inviter and inviter.telegram_id != telegram_id:
            referred_by = inviter.id

    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        balance=to_decimal(STARTING_BALANCE),
        referral_code=uuid.uuid4().hex[:8],
        referred_by_user_id=referred_by,
        referral_earnings=Decimal("0"),
        is_admin=False,
        xp=0,
        level=1,
    )
    session.add(user)
    await session.flush()

    if inviter:
        inviter.balance += to_decimal(REFERRAL_REWARD_INVITER)
        inviter.referral_earnings += to_decimal(REFERRAL_REWARD_INVITER)
        user.balance += to_decimal(REFERRAL_REWARD_NEW_USER)

    await session.commit()
    await session.refresh(user)
    return user, True


async def agree_to_rules(session, telegram_id):
    user = await get_user(session, telegram_id)
    if user:
        user.agreed_to_rules = True
        await session.commit()
        await session.refresh(user)
    return user


async def claim_daily_bonus(session, telegram_id):
    user = await get_user(session, telegram_id)
    if not user:
        return False, "\u041d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d."

    now = datetime.utcnow()

    if user.last_bonus_at:
        nxt = user.last_bonus_at + timedelta(hours=BONUS_COOLDOWN_HOURS)
        if now < nxt:
            rem = nxt - now
            h = int(rem.total_seconds()) // 3600
            m = (int(rem.total_seconds()) % 3600) // 60
            return False, f"\u0427\u0435\u0440\u0435\u0437 {h}\u0447 {m}\u043c."

    bonus = BONUS_AMOUNT
    if is_vip(user):
        bonus = round_coin(bonus * to_decimal(VIP_BONUS_MULTIPLIER))

    user.balance += bonus
    user.last_bonus_at = now

    await session.commit()
    await session.refresh(user)

    vip_mark = " (VIP bonus)" if is_vip(user) else ""
    return True, f"+{bonus}{vip_mark}. \u0411\u0430\u043b\u0430\u043d\u0441: {user.balance}"


async def count_referrals(session, user_id):
    return (
        await session.execute(
            select(func.count(User.id)).where(User.referred_by_user_id == user_id)
        )
    ).scalar_one()


# ========== PAYMENTS ==========

async def create_payment(session, user, package_key):
    pkg = STARS_PACKAGES.get(package_key)
    if not pkg:
        return None

    payload = f"{package_key}:{user.telegram_id}:{uuid.uuid4().hex[:12]}"
    p = Payment(
        user_id=user.id,
        payload=payload,
        stars_amount=pkg["stars"],
        coins_amount=to_decimal(pkg["coins"]),
        status="pending",
    )
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return p


async def create_custom_payment(session, user, stars):
    coins = round_coin(to_decimal(stars) * to_decimal(STARS_TO_COINS_RATE))
    payload = f"custom:{user.telegram_id}:{uuid.uuid4().hex[:12]}"
    p = Payment(
        user_id=user.id,
        payload=payload,
        stars_amount=stars,
        coins_amount=coins,
        status="pending",
    )
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return p


async def create_money_payment(session, user, package_key):
    pkg = MONEY_PACKAGES.get(package_key)
    if not pkg:
        return None

    payload = f"money:{package_key}:{user.telegram_id}:{uuid.uuid4().hex[:12]}"
    p = Payment(
        user_id=user.id,
        payload=payload,
        stars_amount=0,
        coins_amount=to_decimal(pkg["coins"]),
        status="pending",
    )
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return p


async def get_payment_by_payload(session, payload):
    return (
        await session.execute(select(Payment).where(Payment.payload == payload))
    ).scalar_one_or_none()


async def apply_successful_payment(session, payload):
    payment = await get_payment_by_payload(session, payload)
    if not payment:
        return False, "\u041d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d."
    if payment.status == "paid":
        return True, "\u0423\u0436\u0435 \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u0430\u043d."

    user = await get_user_by_id(session, payment.user_id)
    if not user:
        return False, "\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d."

    payment.status = "paid"

    if payload.startswith("vip:"):
        await activate_vip(session, user)
        return True, f"VIP \u0434\u043e {user.vip_until.strftime('%d.%m.%Y')}!"

    user.balance += payment.coins_amount
    await session.commit()
    await session.refresh(user)
    return True, f"+{payment.coins_amount}. \u0411\u0430\u043b\u0430\u043d\u0441: {user.balance}"


# ========== OFFERS ==========

async def create_offer(session, title, description, channel_url):
    o = Offer(
        title=title,
        description=description,
        channel_url=channel_url,
        reward_preview=OFFER_STEP_1_REWARD,
        reward_final=Decimal("35"),
        penalty_unsubscribe=OFFER_PENALTY,
        is_active=True,
    )
    session.add(o)
    await session.commit()
    await session.refresh(o)
    return o


async def get_active_offers(session):
    return list(
        (
            await session.execute(
                select(Offer)
                .where(Offer.is_active == True)
                .order_by(Offer.created_at.desc())
            )
        ).scalars().all()
    )


async def get_all_offers(session):
    return list(
        (await session.execute(select(Offer).order_by(Offer.created_at.desc()))).scalars().all()
    )


async def get_offer_by_id(session, oid):
    return (await session.execute(select(Offer).where(Offer.id == oid))).scalar_one_or_none()


async def toggle_offer_active(session, oid):
    o = await get_offer_by_id(session, oid)
    if not o:
        return None

    o.is_active = not o.is_active
    await session.commit()
    await session.refresh(o)
    return o


async def pin_offer_for_coins(session, user, offer_id):
    offer = await get_offer_by_id(session, offer_id)
    if not offer:
        return False, "\u041e\u0444\u0444\u0435\u0440 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d."

    cost = to_decimal(PIN_OFFER_COST)
    if user.balance < cost:
        return False, "\u041d\u0435\u0445\u0432\u0430\u0442\u0430\u0435\u0442 \u043c\u043e\u043d\u0435\u0442."

    user.balance -= cost
    offer.created_at = datetime.utcnow()
    await session.commit()
    return True, f"\u041e\u0444\u0444\u0435\u0440 #{offer.id} \u043f\u043e\u0434\u043d\u044f\u0442 \u0437\u0430 {cost} \u043c\u043e\u043d\u0435\u0442."


async def start_offer_participation(session, user, offer):
    existing = (
        await session.execute(
            select(OfferParticipation).where(
                OfferParticipation.user_id == user.id,
                OfferParticipation.offer_id == offer.id,
            )
        )
    ).scalar_one_or_none()

    if existing:
        return False, "\u0423\u0436\u0435 \u0443\u0447\u0430\u0441\u0442\u0432\u0443\u0435\u0442\u0435."

    session.add(
        OfferParticipation(
            user_id=user.id,
            offer_id=offer.id,
            status="started",
            reward_given=OFFER_STEP_1_REWARD,
        )
    )
    user.balance += OFFER_STEP_1_REWARD
    await session.commit()
    return True, f"+{OFFER_STEP_1_REWARD} \u043c\u043e\u043d\u0435\u0442."


async def verify_offer_subscription(session, user, offer, is_sub):
    part = (
        await session.execute(
            select(OfferParticipation).where(
                OfferParticipation.user_id == user.id,
                OfferParticipation.offer_id == offer.id,
            )
        )
    ).scalar_one_or_none()

    if not part:
        return False, "\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u043d\u0430\u0447\u043d\u0438\u0442\u0435."

    part.checked_at = datetime.utcnow()

    if is_sub:
        if part.status == "verified":
            return True, "\u0423\u0436\u0435 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u043e."

        part.status = "verified"
        await session.commit()
        return True, "\u041f\u043e\u0434\u043f\u0438\u0441\u043a\u0430 OK."

    if part.status == "verified":
        user.balance = max(Decimal("0"), to_decimal(user.balance) - OFFER_PENALTY)
        part.status = "penalized"
        await session.commit()
        return False, f"\u0428\u0442\u0440\u0430\u0444 {OFFER_PENALTY}."

    await session.commit()
    return False, "\u041d\u0435 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u043e."


async def get_users_without_offer(session, offer_id):
    sub = select(OfferParticipation.user_id).where(OfferParticipation.offer_id == offer_id)
    return list(
        (
            await session.execute(
                select(User).where(
                    User.agreed_to_rules == True,
                    User.id.notin_(sub),
                )
            )
        ).scalars().all()
    )


# ========== CONTENT ==========

async def save_video(session, uploader, file_id, file_unique_id, duration, file_size):
    exists = (
        await session.execute(
            select(Video).where(Video.telegram_file_unique_id == file_unique_id)
        )
    ).scalar_one_or_none()
    if exists:
        return None

    v = Video(
        uploader_user_id=uploader.id,
        content_type="video",
        telegram_file_id=file_id,
        telegram_file_unique_id=file_unique_id,
        duration_seconds=duration,
        file_size=file_size,
        status="pending",
    )
    session.add(v)
    await session.commit()
    await session.refresh(v)
    return v


async def save_photo(session, uploader, file_id, file_unique_id, file_size):
    exists = (
        await session.execute(
            select(Video).where(Video.telegram_file_unique_id == file_unique_id)
        )
    ).scalar_one_or_none()
    if exists:
        return None

    p = Video(
        uploader_user_id=uploader.id,
        content_type="photo",
        telegram_file_id=file_id,
        telegram_file_unique_id=file_unique_id,
        file_size=file_size,
        status="pending",
    )
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return p


async def bump_video_for_coins(session, user, video_id):
    video = (
        await session.execute(
            select(Video).where(
                Video.id == video_id,
                Video.uploader_user_id == user.id,
            )
        )
    ).scalar_one_or_none()

    if not video:
        return False, "\u0412\u0438\u0434\u0435\u043e \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e."

    cost = to_decimal(BUMP_VIDEO_COST)
    if user.balance < cost:
        return False, "\u041d\u0435\u0445\u0432\u0430\u0442\u0430\u0435\u0442 \u043c\u043e\u043d\u0435\u0442."

    user.balance -= cost
    video.created_at = datetime.utcnow()
    await session.commit()
    return True, f"\u0412\u0438\u0434\u0435\u043e #{video.id} \u043f\u043e\u0434\u043d\u044f\u0442\u043e \u0437\u0430 {cost} \u043c\u043e\u043d\u0435\u0442."


# ========== MODERATION ==========

async def get_next_pending_video(session):
    return (
        await session.execute(
            select(Video)
            .where(Video.status == "pending")
            .order_by(Video.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()


async def approve_video(session, video_id):
    v = (await session.execute(select(Video).where(Video.id == video_id))).scalar_one_or_none()
    if not v or v.status != "pending":
        return v

    v.status = "approved"
    v.rejection_reason = None

    up = (
        await session.execute(select(User).where(User.id == v.uploader_user_id))
    ).scalar_one_or_none()
    if up:
        reward = PHOTO_UPLOAD_REWARD if v.content_type == "photo" else to_decimal(UPLOAD_REWARD)
        up.balance += reward

    await session.commit()
    await session.refresh(v)
    return v


async def approve_all_pending(session):
    vids = list(
        (await session.execute(select(Video).where(Video.status == "pending"))).scalars().all()
    )

    for v in vids:
        v.status = "approved"
        v.rejection_reason = None

        up = (
            await session.execute(select(User).where(User.id == v.uploader_user_id))
        ).scalar_one_or_none()
        if up:
            reward = PHOTO_UPLOAD_REWARD if v.content_type == "photo" else to_decimal(UPLOAD_REWARD)
            up.balance += reward

    await session.commit()
    return len(vids)


async def reject_video(session, video_id, reason):
    v = (await session.execute(select(Video).where(Video.id == video_id))).scalar_one_or_none()
    if not v:
        return None

    v.status = "rejected"
    v.rejection_reason = reason
    await session.commit()
    await session.refresh(v)
    return v


async def count_pending_videos(session):
    return (
        await session.execute(select(func.count(Video.id)).where(Video.status == "pending"))
    ).scalar_one()


async def count_approved_videos(session):
    return (
        await session.execute(select(func.count(Video.id)).where(Video.status == "approved"))
    ).scalar_one()


async def count_rejected_videos(session):
    return (
        await session.execute(select(func.count(Video.id)).where(Video.status == "rejected"))
    ).scalar_one()


# ========== WATCH VIDEO ==========

async def get_video_stats_for_user(session, user):
    total = (
        await session.execute(
            select(func.count(Video.id)).where(
                Video.status == "approved",
                Video.content_type == "video",
            )
        )
    ).scalar_one()

    wsub = select(VideoView.video_id).where(VideoView.user_id == user.id)

    avail = (
        await session.execute(
            select(func.count(Video.id)).where(
                Video.status == "approved",
                Video.content_type == "video",
                Video.uploader_user_id != user.id,
                Video.id.notin_(wsub),
            )
        )
    ).scalar_one()

    return {
        "total_approved": total,
        "available": avail,
    }


async def get_random_video_for_user(session, user):
    wsub = select(VideoView.video_id).where(VideoView.user_id == user.id)
    return (
        await session.execute(
            select(Video).where(
                Video.status == "approved",
                Video.content_type == "video",
                Video.uploader_user_id != user.id,
                Video.id.notin_(wsub),
            ).order_by(func.random()).limit(1)
        )
    ).scalar_one_or_none()


async def record_view_and_charge(session, user, video):
    cost = get_watch_cost_for_user(user)

    if user.balance < cost:
        return False

    exists = (
        await session.execute(
            select(VideoView).where(
                VideoView.user_id == user.id,
                VideoView.video_id == video.id,
            )
        )
    ).scalar_one_or_none()

    if exists:
        return False

    session.add(VideoView(user_id=user.id, video_id=video.id))
    user.balance -= cost
    await session.commit()
    return True


# ========== WATCH PHOTO ==========

async def count_photo_views_last_4h(session, user_id):
    since = datetime.utcnow() - timedelta(hours=4)
    return (
        await session.execute(
            select(func.count(VideoView.id))
            .join(Video)
            .where(
                VideoView.user_id == user_id,
                Video.content_type == "photo",
                VideoView.watched_at >= since,
            )
        )
    ).scalar_one()


async def get_random_photo_for_user(session, user):
    wsub = select(VideoView.video_id).where(VideoView.user_id == user.id)
    return (
        await session.execute(
            select(Video).where(
                Video.status == "approved",
                Video.content_type == "photo",
                Video.uploader_user_id != user.id,
                Video.id.notin_(wsub),
            ).order_by(func.random()).limit(1)
        )
    ).scalar_one_or_none()


async def record_photo_view(session, user, photo):
    exists = (
        await session.execute(
            select(VideoView).where(
                VideoView.user_id == user.id,
                VideoView.video_id == photo.id,
            )
        )
    ).scalar_one_or_none()

    if exists:
        return False

    session.add(VideoView(user_id=user.id, video_id=photo.id))
    await session.commit()
    return True


# ========== RATING ==========

async def rate_video(session, user_id, video_id, rating):
    existing = (
        await session.execute(
            select(VideoRating).where(
                VideoRating.user_id == user_id,
                VideoRating.video_id == video_id,
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.rating = rating
    else:
        session.add(VideoRating(user_id=user_id, video_id=video_id, rating=rating))

    await session.commit()


# ========== COMMENTS ==========

async def can_user_comment(session, user_id):
    now = datetime.utcnow()
    window_start = now - timedelta(minutes=10)

    recent_count = (
        await session.execute(
            select(func.count(Comment.id)).where(
                Comment.user_id == user_id,
                Comment.created_at >= window_start,
            )
        )
    ).scalar_one()

    last_comment = (
        await session.execute(
            select(Comment)
            .where(Comment.user_id == user_id)
            .order_by(Comment.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if recent_count >= COMMENTS_PER_10_MIN:
        return False, "\u0421\u043b\u0438\u0448\u043a\u043e\u043c \u043c\u043d\u043e\u0433\u043e \u043a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0435\u0432. \u041f\u043e\u0434\u043e\u0436\u0434\u0438\u0442\u0435."

    if last_comment:
        delta = (now - last_comment.created_at).total_seconds()
        if delta < COMMENT_MIN_INTERVAL_SEC:
            wait_sec = int(COMMENT_MIN_INTERVAL_SEC - delta)
            return False, f"\u041f\u043e\u0434\u043e\u0436\u0434\u0438\u0442\u0435 {wait_sec} \u0441\u0435\u043a."

    return True, ""


async def add_comment(session, user_id, video_id, text):
    c = Comment(user_id=user_id, video_id=video_id, text=text[:500])
    session.add(c)
    await session.commit()
    await session.refresh(c)
    return c


async def get_video_comments(session, video_id, limit=10):
    stmt = (
        select(Comment, User.username, User.first_name)
        .join(User, User.id == Comment.user_id)
        .where(Comment.video_id == video_id)
        .order_by(Comment.created_at.desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()

    result = []
    for comment, uname, fname in rows:
        name = f"@{uname}" if uname else (fname or "Anon")
        result.append({
            "id": comment.id,
            "text": comment.text,
            "author": name,
            "at": comment.created_at,
        })

    return result


async def count_user_comments_today(session, user_id):
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        await session.execute(
            select(func.count(Comment.id)).where(
                Comment.user_id == user_id,
                Comment.created_at >= today_start,
            )
        )
    ).scalar_one()


# ========== REACTIONS ==========

async def add_reaction(session, user_id, video_id, reaction_type):
    existing = (
        await session.execute(
            select(ContentReaction).where(
                ContentReaction.user_id == user_id,
                ContentReaction.video_id == video_id,
            )
        )
    ).scalar_one_or_none()

    if existing:
        existing.reaction_type = reaction_type
    else:
        session.add(
            ContentReaction(
                user_id=user_id,
                video_id=video_id,
                reaction_type=reaction_type,
            )
        )

    await session.commit()


async def get_reaction_counts(session, video_id):
    stmt = (
        select(ContentReaction.reaction_type, func.count(ContentReaction.id))
        .where(ContentReaction.video_id == video_id)
        .group_by(ContentReaction.reaction_type)
    )
    rows = (await session.execute(stmt)).all()
    return {r: c for r, c in rows}


# ========== GAMES ==========

async def play_lootbox(session, user):
    cost = to_decimal(LOOTBOX_COST)
    if user.balance < cost:
        return False, 0, "\u041d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e \u043c\u043e\u043d\u0435\u0442."

    user.balance -= cost

    roll = random.random()
    cumul = 0
    reward = 1

    for prob, coins in LOOTBOX_REWARDS:
        cumul += prob
        if roll <= cumul:
            reward = coins
            break

    user.balance += to_decimal(reward)

    session.add(
        GameHistory(
            user_id=user.id,
            game_type="lootbox",
            bet=cost,
            result=to_decimal(reward),
            details=f"won {reward}",
        )
    )
    await session.commit()
    await session.refresh(user)
    return True, reward, ""


async def play_dice(session, user, bet):
    bet_d = to_decimal(bet)

    if bet < DICE_MIN_BET or bet > DICE_MAX_BET:
        return False, 0, Decimal("0"), f"\u0421\u0442\u0430\u0432\u043a\u0430 {DICE_MIN_BET}-{DICE_MAX_BET}."
    if user.balance < bet_d:
        return False, 0, Decimal("0"), "\u041d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e."

    user.balance -= bet_d
    roll = random.randint(1, 6)

    if roll >= 4:
        win = bet_d * 2
        user.balance += win
    else:
        win = Decimal("0")

    session.add(
        GameHistory(
            user_id=user.id,
            game_type="dice",
            bet=bet_d,
            result=win,
            details=f"roll={roll}",
        )
    )
    await session.commit()
    await session.refresh(user)
    return True, roll, win, ""


async def play_coinflip(session, user, bet):
    bet_d = to_decimal(bet)

    if bet < 1 or bet > DICE_MAX_BET:
        return False, "", Decimal("0"), "\u0421\u0442\u0430\u0432\u043a\u0430 1-50."
    if user.balance < bet_d:
        return False, "", Decimal("0"), "\u041d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e."

    user.balance -= bet_d
    side = random.choice(["heads", "tails"])

    if side == "heads":
        win = bet_d * 2
        user.balance += win
    else:
        win = Decimal("0")

    session.add(
        GameHistory(
            user_id=user.id,
            game_type="coinflip",
            bet=bet_d,
            result=win,
            details=side,
        )
    )
    await session.commit()
    await session.refresh(user)
    return True, side, win, ""


async def play_guess(session, user, guess, bet):
    bet_d = to_decimal(bet)

    if guess < 1 or guess > 10:
        return False, 0, Decimal("0"), "\u0427\u0438\u0441\u043b\u043e 1-10."
    if bet < 1 or bet > DICE_MAX_BET:
        return False, 0, Decimal("0"), "\u0421\u0442\u0430\u0432\u043a\u0430 1-50."
    if user.balance < bet_d:
        return False, 0, Decimal("0"), "\u041d\u0435\u0434\u043e\u0441\u0442\u0430\u0442\u043e\u0447\u043d\u043e."

    user.balance -= bet_d
    answer = random.randint(1, 10)

    if guess == answer:
        win = bet_d * 5
        user.balance += win
    else:
        win = Decimal("0")

    session.add(
        GameHistory(
            user_id=user.id,
            game_type="guess",
            bet=bet_d,
            result=win,
            details=f"g={guess},a={answer}",
        )
    )
    await session.commit()
    await session.refresh(user)
    return True, answer, win, ""


# ========== QUESTS ==========

async def ensure_daily_quests(session, user_id, user=None):
    today = datetime.utcnow().date()

    existing = list(
        (
            await session.execute(
                select(DailyQuestProgress).where(
                    DailyQuestProgress.user_id == user_id,
                    DailyQuestProgress.quest_date == today,
                )
            )
        ).scalars().all()
    )
    if existing:
        return existing

    quests = []
    all_quests = list(DAILY_QUESTS)

    if user and is_vip(user):
        all_quests.extend(PREMIUM_DAILY_QUESTS)

    for q in all_quests:
        qp = DailyQuestProgress(
            user_id=user_id,
            quest_type=q["type"],
            quest_date=today,
            progress=0,
            target=q["target"],
            reward=to_decimal(q["reward"]),
            completed=False,
            reward_claimed=False,
        )
        session.add(qp)
        quests.append(qp)

    await session.commit()
    for qp in quests:
        await session.refresh(qp)

    return quests


async def increment_quest(session, user_id, quest_type):
    today = datetime.utcnow().date()
    q_all = list(
        (
            await session.execute(
                select(DailyQuestProgress).where(
                    DailyQuestProgress.user_id == user_id,
                    DailyQuestProgress.quest_type == quest_type,
                    DailyQuestProgress.quest_date == today,
                    DailyQuestProgress.completed == False,
                )
            )
        ).scalars().all()
    )

    for q in q_all:
        q.progress += 1
        if q.progress >= q.target:
            q.completed = True

    await session.commit()


async def claim_quest_reward(session, user, quest_id):
    q = (
        await session.execute(
            select(DailyQuestProgress).where(
                DailyQuestProgress.id == quest_id,
                DailyQuestProgress.user_id == user.id,
                DailyQuestProgress.completed == True,
                DailyQuestProgress.reward_claimed == False,
            )
        )
    ).scalar_one_or_none()

    if not q:
        return False, "\u041d\u0435\u0442 \u043d\u0430\u0433\u0440\u0430\u0434\u044b."

    user.balance += q.reward
    q.reward_claimed = True
    await session.commit()
    await session.refresh(user)
    return True, f"+{q.reward}. \u0411\u0430\u043b\u0430\u043d\u0441: {user.balance}"


# ========== TOPS ==========

async def get_top_uploaders(session, limit=10):
    stmt = (
        select(
            User.username,
            User.first_name,
            User.telegram_id,
            func.count(Video.id).label("cnt"),
        )
        .join(Video, Video.uploader_user_id == User.id)
        .where(Video.status == "approved")
        .group_by(User.id)
        .order_by(func.count(Video.id).desc())
        .limit(limit)
    )
    return (await session.execute(stmt)).all()


async def get_top_viewers(session, limit=10):
    stmt = (
        select(
            User.username,
            User.first_name,
            User.telegram_id,
            func.count(VideoView.id).label("cnt"),
        )
        .join(VideoView, VideoView.user_id == User.id)
        .group_by(User.id)
        .order_by(func.count(VideoView.id).desc())
        .limit(limit)
    )
    return (await session.execute(stmt)).all()


async def get_top_by_level(session, limit=10):
    stmt = select(User).where(User.agreed_to_rules == True).order_by(User.xp.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def get_top_richest(session, limit=10):
    stmt = select(User).where(User.agreed_to_rules == True).order_by(User.balance.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


# ========== WEEKLY REWARDS ==========

async def reward_weekly_top_users(session):
    rewarded = []
    richest = await get_top_richest(session, limit=3)

    rewards = [
        to_decimal(WEEKLY_TOP1_REWARD),
        to_decimal(WEEKLY_TOP2_REWARD),
        to_decimal(WEEKLY_TOP3_REWARD),
    ]

    for idx, user in enumerate(richest):
        reward = rewards[idx]
        user.balance += reward
        rewarded.append((user, reward))

    await session.commit()
    return rewarded


# ========== ADMIN STATS ==========

async def get_admin_extended_stats(session):
    users_count = (await session.execute(select(func.count(User.id)))).scalar_one()

    vip_count = (
        await session.execute(
            select(func.count(User.id)).where(
                User.vip_until.is_not(None),
                User.vip_until > datetime.utcnow(),
            )
        )
    ).scalar_one()

    comments_count = (await session.execute(select(func.count(Comment.id)))).scalar_one()
    reactions_count = (await session.execute(select(func.count(ContentReaction.id)))).scalar_one()
    games_count = (await session.execute(select(func.count(GameHistory.id)))).scalar_one()
    offers_count = (await session.execute(select(func.count(Offer.id)))).scalar_one()

    return {
        "users": users_count,
        "vip": vip_count,
        "comments": comments_count,
        "reactions": reactions_count,
        "games": games_count,
        "offers": offers_count,
    }