from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.models import VideoReport

import math
import asyncio
import uuid
import random
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_DOWN
from sqlalchemy import select, func, desc, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.logger import get_logger, log_error
from app.models import (
    utc_now,
    ActiveSale, Event,
    User, Video, VideoView, VideoRating, Payment,
    Offer, OfferParticipation,
    Comment, ContentReaction, GameHistory,
    GameSession,
    UserActionLog, BalanceLog, UserAdState,
    Promocode, PromocodeActivation, Feedback,
    LotteryRound, LotteryTicket,
    LootboxOpen,
    TrustedUploader, UserPerk,
)

logger = get_logger(__name__)

from app.config import (
    STARTING_BALANCE, WATCH_COST, UPLOAD_REWARD, PHOTO_UPLOAD_REWARD,
    REFERRAL_REWARD_INVITER, REFERRAL_REWARD_NEW_USER, STARS_PACKAGES, STARS_TO_COINS_RATE,
    NICKNAME_CHANGE_COST, NICKNAME_MIN_LENGTH, NICKNAME_MAX_LENGTH,
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
    SMART_AD_VIDEO_CHANCE, SMART_AD_FORCED_WATCH_SECONDS,
    OFFER_DAILY_REWARD_CAP,
    LOTTERY_TICKET_PRICE, LOTTERY_NUMBERS_POOL, LOTTERY_NUMBERS_PER_TICKET,
    ENABLE_LOOTBOXES, LOOTBOX_COIN_PRICE, LOOTBOX_STAR_PRICE,
    ENABLE_AUTO_MODERATION,
    VIP_PRICE_STARS, VIP_DURATION_DAYS, VIP_BONUS_MULTIPLIER, VIP_WATCH_DISCOUNT,
    ENABLE_ADMIN_FREE,
    ADMINS,
)



# ============================
# ЛУТБОКСЫ
# ============================
def _roll_lootbox_reward_coins() -> tuple[Decimal, str]:
    r = random.random()
    if r < 0.70:
        return to_decimal(random.randint(10, 30)), "common"
    if r < 0.95:
        return to_decimal(random.randint(40, 100)), "rare"
    if r < 0.995:
        return to_decimal(random.randint(140, 300)), "epic"
    return to_decimal(random.randint(500, 2000)), "jackpot"


async def open_lootbox_for_coins(session: AsyncSession, user_id: int) -> tuple[Decimal, str] | tuple[None, str]:
    if not ENABLE_LOOTBOXES:
        return None, "Лутбоксы временно отключены."
    user = await get_user_by_id(session, user_id)
    if not user:
        return None, "Пользователь не найден."

    price = to_decimal(LOOTBOX_COIN_PRICE)
    if user.balance < price:
        return None, "Недостаточно монет."

    reward, rarity = _roll_lootbox_reward_coins()

    await change_balance_atomic(session, user.id, -price, "lootbox_buy", details="currency=coins")
    await change_balance_atomic(
        session,
        user.id,
        reward,
        "lootbox_reward",
        details=f"rarity={rarity}",
    )
    session.add(LootboxOpen(
        user_id=user.id,
        payment_payload=None,
        pay_currency="coins",
        price_coins=price,
        price_stars=0,
        reward_coins=reward,
        rarity=rarity,
    ))
    await session.commit()
    return reward, rarity


async def open_lootbox_for_stars(
    session: AsyncSession,
    telegram_user_id: int,
    payment_payload: str,
) -> tuple[Decimal, str] | tuple[None, str]:
    """
    Called after successful Telegram Stars payment.
    Idempotent by payload.
    """
    if not ENABLE_LOOTBOXES:
        return None, "Лутбоксы временно отключены."

    user = await get_user(session, telegram_user_id)
    if not user:
        return None, "Пользователь не найден."

    existing = (await session.execute(
        select(LootboxOpen).where(LootboxOpen.payment_payload == payment_payload)
    )).scalar_one_or_none()
    if existing:
        return None, "Этот платёж уже обработан."

    reward, rarity = _roll_lootbox_reward_coins()
    stars_price = int(LOOTBOX_STAR_PRICE)

    await change_balance_atomic(
        session,
        user.id,
        reward,
        "lootbox_reward",
        details=f"currency=stars;rarity={rarity};stars={stars_price}",
    )
    session.add(LootboxOpen(
        user_id=user.id,
        payment_payload=payment_payload,
        pay_currency="stars",
        price_coins=Decimal("0"),
        price_stars=stars_price,
        reward_coins=reward,
        rarity=rarity,
    ))
    await log_user_action(session, user.id, "lootbox_open", f"payload={payment_payload}")
    await session.commit()
    return reward, rarity

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


async def get_nick_style_id(session: AsyncSession, user_id: int) -> int | None:
    """Возвращает style_id активного перка ника (1-50) или None.

    Приоритет: custom_nick со style_id > gold_nick (→2) > color_nick (→1).
    """
    from app.nick_styles import LEGACY_PERK_MAP

    # Сначала проверяем custom_nick (новый формат)
    # Используем SAVEPOINT чтобы не испортить внешнюю транзакцию при отсутствии колонки style_id
    try:
        async with session.begin_nested():
            result = await session.execute(
                select(UserPerk).where(
                    UserPerk.user_id == user_id,
                    UserPerk.perk_type == "custom_nick",
                    UserPerk.is_active == True,
                    UserPerk.active_until > utc_now(),
                )
            )
            custom = result.scalar_one_or_none()
            if custom:
                sid = getattr(custom, 'style_id', None)
                if sid:
                    return sid
    except Exception:
        # Колонка style_id отсутствует в БД, или другая ошибка – молча fallback
        # begin_nested автоматически откатит savepoint, внешняя транзакция цела,
        # объекты не expired
        pass

    # Легаси: color_nick / gold_nick маппятся на стили 1 / 2
    try:
        for perk_type, mapped_id in LEGACY_PERK_MAP.items():
            result = await session.execute(
                select(UserPerk).where(
                    UserPerk.user_id == user_id,
                    UserPerk.perk_type == perk_type,
                    UserPerk.is_active == True,
                    UserPerk.active_until > utc_now(),
                )
            )
            perk = result.scalar_one_or_none()
            if perk:
                return mapped_id
    except Exception:
        pass

    return None


async def get_styled_display_name(
    session: AsyncSession,
    user: "User",
    *,
    card: bool = False,
) -> str:
    """Возвращает стилизованный ник с учётом активных перков.

    Parameters
    ----------
    card : bool
        False (default) — inline-режим: короткий, для строк
        True           — card-режим: многострочный, для профиля
    """
    from app.nick_styles import format_nick_inline, format_nick_card

    name = get_display_name(user)
    try:
        style_id = await get_nick_style_id(session, user.id)
    except Exception:
        style_id = None

    if card:
        return format_nick_card(name, style_id)
    return format_nick_inline(name, style_id)


def is_admin_or_super(telegram_id: int, user: "User" = None) -> bool:
    if telegram_id in ADMINS:
        return True
    if user and user.is_admin:
        return True
    return False


async def is_admin_free_eligible(session: AsyncSession, telegram_id: int, user: "User" = None) -> bool:
    """
    Проверяет, может ли пользователь покупать всё бесплатно.
    Работает только для ADMINS или is_admin=True.
    Настройка берётся из БД (runtime) или env (fallback).
    """
    if telegram_id not in ADMINS and not (user and user.is_admin):
        return False

    # Сначала проверяем БД (runtime-настройка)
    db_val = await get_setting(session, "admin_free_enabled", "")
    if db_val:
        return db_val.lower() == "true"

    # Фоллбэк на env
    return ENABLE_ADMIN_FREE


# ============================
# ЛОГИРОВАНИЕ БАЛАНСА И ДЕЙСТВИЙ
# ============================

def is_vip(user: "User") -> bool:
    """Проверка, является ли пользователь VIP (активен ли статус на текущий момент)."""
    return bool(user.vip_until and user.vip_until > utc_now())
async def change_balance_atomic(
    session: AsyncSession,
    user_id: int,
    amount: Decimal,
    source: str,
    source_id: int = None,
    admin_id: int = None,
    details: str = None,
) -> "User | None":
    """
    Atomically updates user balance and logs the change.
    Returns the updated user object.
    """
    from sqlalchemy import update
    
    # 1. Atomic update in DB
    stmt = (
        update(User)
        .where(User.id == user_id)
        .values(balance=User.balance + amount)
        .returning(User)
    )
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        return None
    
    # 2. Log the change
    # Note: we use the updated balance from the returning clause
    # To get the balance BEFORE, we'd need to fetch it first or use a more complex query.
    # For the log, we can approximate or fetch the old balance.
    # Since we already have 'user' (updated), let's just record it.
    # To be precise about balance_before, we can fetch the user before updating,
    # but that introduces a race condition unless we use SELECT FOR UPDATE.
    
    # Better approach for logging: Use the balance from the returning User object
    # and calculate 'before' as 'after - amount'.
    balance_after = user.balance
    balance_before = balance_after - amount
    
    log = BalanceLog(
        user_id=user_id,
        amount=amount,
        balance_before=balance_before,
        balance_after=balance_after,
        source=source,
        source_id=source_id,
        admin_id=admin_id,
        details=details,
    )
    session.add(log)
    return user


async def log_user_action(
    session: AsyncSession,
    user_id: int,
    action: str,
    details: str = None,
    *,
    auto_commit: bool = True,
):
    log = UserActionLog(user_id=user_id, action=action, details=details)
    session.add(log)
    if auto_commit:
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            session.expunge_all()


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
    inviter = None
    starting_bonus = to_decimal(STARTING_BALANCE)
    referral_new_user_bonus = Decimal("0")
    if referral_code:
        inviter = (await session.execute(
            select(User).where(User.referral_code == referral_code)
        )).scalar_one_or_none()
        if inviter and inviter.telegram_id != telegram_id:
            referred_by = inviter.id
            referral_new_user_bonus = to_decimal(REFERRAL_REWARD_NEW_USER)

    created = False
    try:
        # Создаём пользователя с нулевым балансом и начисляем стартовые деньги отдельно,
        # чтобы не было двойного начисления при логировании регистрации.
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            balance=Decimal("0"),
            referral_code=uuid.uuid4().hex[:8],
            referred_by_user_id=referred_by,
        )
        session.add(user)
        await session.flush()

        total_start_credit = starting_bonus + referral_new_user_bonus
        await change_balance_atomic(
            session,
            user.id,
            total_start_credit,
            "registration",
            details=(
                f"Starting balance={starting_bonus}; "
                f"referral_bonus={referral_new_user_bonus}; referred_by={referred_by}"
            ),
        )

        if inviter is not None:
            inviter.referrals_count = (inviter.referrals_count or 0) + 1

        await session.commit()
        created = True
    except Exception:
        await session.rollback()
        user = await get_user(session, telegram_id)
        if not user:
            raise

    await log_user_action(
        session,
        user.id,
        "registration",
        f"tg_id={telegram_id}, referred_by={referred_by}",
    )
    return user, created


# ============================
# НИКНЕЙМ
# ============================
async def set_display_name(session: AsyncSession, user: "User", name: str,
                           admin_free: bool = False) -> tuple[bool, str]:
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
    if not is_first and not admin_free:
        cost = to_decimal(NICKNAME_CHANGE_COST)
        if user.balance < cost:
            return False, f"Недостаточно монет. Нужно: {cost}, у вас: {user.balance}"
        await change_balance_atomic(session, user.id, -cost, "nickname_change",
                                    details=f"{user.display_name} -> {name}")

    old_name = user.display_name
    user.display_name = name
    user.nickname_set = True
    await session.commit()
    await log_user_action(session, user.id, "set_nickname", f"{old_name} -> {name}")
    if is_first:
        return True, f"Ник <b>{name}</b> установлен бесплатно!"
    if admin_free:
        return True, f"Ник изменён на <b>{name}</b>! 🆓 <b>ADMIN FREE — бесплатно!</b>"
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


async def _get_runtime_upload_reward(session: AsyncSession, content_type: str) -> Decimal:
    if content_type == "photo":
        db_val = await get_setting(session, "photo_upload_reward", "")
        fallback = PHOTO_UPLOAD_REWARD
    else:
        db_val = await get_setting(session, "upload_reward", "")
        fallback = UPLOAD_REWARD

    if db_val:
        try:
            return to_decimal(db_val)
        except Exception:
            pass
    return to_decimal(fallback)


async def calculate_upload_reward(
    session: AsyncSession,
    uploader_user_id: int,
    content_type: str,
) -> Decimal:
    reward = await _get_runtime_upload_reward(session, content_type)
    multiplier = await get_coin_multiplier(session, uploader_user_id)
    return round_coin(reward * to_decimal(multiplier))


async def approve_video(session: AsyncSession, video_id: int) -> "Video | None":
    v = (await session.execute(
        select(Video).where(Video.id == video_id)
    )).scalar_one_or_none()
    if not v or v.status != "pending":
        return None
    v.status = "approved"
    uploader = await get_user_by_id(session, v.uploader_user_id)
    if uploader:
        reward = await calculate_upload_reward(session, uploader.id, v.content_type)
        await change_balance_atomic(session, uploader.id, reward, "upload_approved", source_id=v.id)
        await log_user_action(session, uploader.id, "video_approved",
                              f"id={v.id}, type={v.content_type}, reward={reward}")
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


async def is_trusted_uploader(session: AsyncSession, user_id: int) -> bool:
    """Проверяет, является ли пользователь доверенным автором"""
    # Проверяем runtime-настройку
    db_val = await get_setting(session, "auto_moderation_enabled", "")
    if db_val:
        enabled = db_val.lower() == "true"
    else:
        enabled = ENABLE_AUTO_MODERATION
    if not enabled:
        return False
    trusted = (await session.execute(
        select(TrustedUploader).where(TrustedUploader.trusted_user_id == user_id)
    )).scalar_one_or_none()
    return trusted is not None


async def auto_approve_if_trusted(
    session: AsyncSession,
    video_id: int,
    uploader_user_id: int,
) -> tuple[bool, Decimal]:
    """
    Если авто-модерация включена и пользователь доверенный — сразу одобряет видео.
    Возвращает (было_ли_автоодобрение, фактическая_награда).
    """
    if not await is_trusted_uploader(session, uploader_user_id):
        return False, Decimal("0")

    v = (await session.execute(
        select(Video).where(Video.id == video_id, Video.status == "pending")
    )).scalar_one_or_none()
    if not v:
        return False, Decimal("0")

    v.status = "approved"
    v.rejection_reason = None
    reward = Decimal("0")

    uploader = await get_user_by_id(session, uploader_user_id)
    if uploader:
        reward = await calculate_upload_reward(session, uploader.id, v.content_type)
        uploader = await change_balance_atomic(
            session,
            uploader.id,
            reward,
            "upload_approved",
            source_id=v.id,
        ) or uploader
        await log_user_action(session, uploader.id, "video_auto_approved",
                              f"id={v.id}, type={v.content_type}, reward={reward} (trusted)")

    await session.commit()
    return True, reward


async def get_random_video_for_user(session: AsyncSession, user_id: int) -> "Video | None":
    return (await session.execute(
        select(Video).where(
            Video.status == "approved",
            Video.content_type == "video",
            Video.uploader_user_id != user_id,
            ~select(VideoView.id).where(VideoView.video_id == Video.id, VideoView.user_id == user_id).exists()
        ).order_by(func.random()).limit(1)
    )).scalar_one_or_none()


async def get_random_photo_for_user(session: AsyncSession, user_id: int) -> "Video | None":
    return (await session.execute(
        select(Video).where(
            Video.status == "approved",
            Video.content_type == "photo",
            Video.uploader_user_id != user_id,
            ~select(VideoView.id).where(VideoView.video_id == Video.id, VideoView.user_id == user_id).exists()
        ).order_by(func.random()).limit(1)
    )).scalar_one_or_none()


# record_view_and_charge removed - dead code, use record_view_and_charge_with_cost instead
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
    await change_balance_atomic(session, user.id, -cost, "watch", source_id=video_id)
    from sqlalchemy.exc import IntegrityError
    try:
        session.add(VideoView(user_id=user_id, video_id=video_id, watched_at=utc_now()))
        await session.commit()
    except IntegrityError:
        await session.rollback()
        session.expunge_all()
        return False
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
    await change_balance_atomic(
        session,
        user.id,
        cost,
        "watch_refund",
        source_id=video_id,
        details=reason,
    )
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
        view = VideoView(user_id=user_id, video_id=photo_id, watched_at=utc_now())
        session.add(view)
        await session.commit()
    return True


async def check_daily_photo_limit(session: AsyncSession, user_id: int) -> bool:
    today = utc_now().date()
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
    await change_balance_atomic(session, user_id, amount, "admin_balance", admin_id=admin_id,
                                    details=f"Manual by admin {admin_id}")
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
    now = utc_now()
    if user.last_bonus_at and user.last_bonus_at.date() == now.date():
        return False, "Вы уже получили бонус сегодня."
    streak = 1
    if user.last_bonus_at and (now.date() - user.last_bonus_at.date()).days == 1:
        streak = min(user.bonus_streak + 1, MAX_BONUS_STREAK)
    reward = DAILY_BONUS_STREAK_BASE + DAILY_BONUS_STREAK_INCREASE * (streak - 1)
    await change_balance_atomic(session, user.id, to_decimal(reward), "daily_bonus")
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
    """Начисляем награду, если реферал посмотрел 5 видео.

    Считаются именно просмотры видео, а не фото и не любые записи VideoView.
    """
    refs = (await session.execute(
        select(User).where(User.referred_by_user_id == referrer_id)
    )).scalars().all()
    for ref in refs:
        views = (await session.execute(
            select(func.count(VideoView.id))
            .join(Video, Video.id == VideoView.video_id)
            .where(
                VideoView.user_id == ref.id,
                Video.content_type == "video",
            )
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
                    await change_balance_atomic(
                        session,
                        inviter.id,
                        reward,
                        "referral_reward",
                        details=f"ref_user_id={ref.id}",
                    )
                    inviter.referral_earnings += reward
                    await session.commit()


# ============================
# ПЛАТЕЖИ
# ============================
async def create_payment(
    session: AsyncSession,
    user_id: int,
    pack_key: str,
    *,
    stars_amount_override: int | None = None,
) -> Payment:
    pack = STARS_PACKAGES.get(pack_key)
    if not pack:
        raise ValueError("Unknown pack")
    coins = to_decimal(pack["coins"])
    payload = f"{pack_key}_{user_id}_{uuid.uuid4().hex[:6]}"
    payment = Payment(
        user_id=user_id,
        payload=payload,
        stars_amount=int(stars_amount_override if stars_amount_override is not None else pack["stars"]),
        coins_amount=coins,
        status="pending",
    )
    session.add(payment)
    await session.commit()
    return payment


async def create_custom_payment(
    session: AsyncSession,
    user_id: int,
    stars: int,
    *,
    billed_stars_amount: int | None = None,
) -> Payment:
    coins = to_decimal(stars * STARS_TO_COINS_RATE)
    payload = f"custom_{user_id}_{uuid.uuid4().hex[:6]}"
    payment = Payment(
        user_id=user_id,
        payload=payload,
        stars_amount=int(billed_stars_amount if billed_stars_amount is not None else stars),
        coins_amount=coins,
        status="pending",
    )
    session.add(payment)
    await session.commit()
    return payment


async def ensure_payment_pending(
    session: AsyncSession,
    *,
    user_id: int,
    payload: str,
    stars_amount: int,
    coins_amount: Decimal = Decimal("0"),
) -> Payment:
    """
    Ensure a pending payment row exists for payload.
    Used for VIP / promo / lootbox stars flows to guarantee idempotency.
    """
    payment = (await session.execute(
        select(Payment).where(Payment.payload == payload)
    )).scalar_one_or_none()
    if payment:
        return payment
    payment = Payment(
        user_id=user_id,
        payload=payload,
        stars_amount=int(stars_amount),
        coins_amount=to_decimal(coins_amount),
        status="pending",
    )
    session.add(payment)
    await session.flush()
    return payment


async def mark_payment_paid_once(session: AsyncSession, payload: str) -> bool:
    """
    Atomically mark payment as paid exactly once.
    Returns True only for the first successful transition pending -> paid.
    """
    result = await session.execute(
        update(Payment)
        .where(Payment.payload == payload, Payment.status == "pending")
        .values(status="paid")
    )
    await session.flush()
    return bool(result.rowcount)


async def get_payment_by_payload(session: AsyncSession, payload: str) -> Payment | None:
    return (await session.execute(
        select(Payment).where(Payment.payload == payload)
    )).scalar_one_or_none()


async def apply_successful_payment(session: AsyncSession, payload: str) -> tuple[Payment | None, Decimal]:
    payment = (await session.execute(
        select(Payment).where(Payment.payload == payload)
    )).scalar_one_or_none()
    if not payment:
        return None, Decimal("0")
    if not await mark_payment_paid_once(session, payload):
        return None, Decimal("0")
    await session.refresh(payment)
    credited_total = Decimal("0")
    user = await get_user_by_id(session, payment.user_id)
    if user:
        bonus_multiplier = 1.0
        # Динамический курс
        if DYNAMIC_STAR_DISCOUNT_ENABLED:
            try:
                start_h, end_h = map(int, DYNAMIC_STAR_DISCOUNT_HOURS.split("-"))
                now_h = utc_now().hour
                if start_h <= now_h < end_h:
                    bonus_multiplier = DYNAMIC_STAR_DISCOUNT_MULTIPLIER
            except Exception:
                pass
        # Первая покупка за день
        today = utc_now().date()
        first_today = not (await session.execute(
            select(Payment).where(
                Payment.user_id == user.id,
                Payment.status == "paid",
                func.date(Payment.created_at) == today,
                Payment.id != payment.id,
            )
        )).scalar_one_or_none()
        credited_total = payment.coins_amount * to_decimal(bonus_multiplier)
        if first_today:
            credited_total += to_decimal(FIRST_PURCHASE_DAILY_BONUS)
        await change_balance_atomic(session, user.id, credited_total, "purchase",
                                    details=f"payload={payload}, bonus_mult={bonus_multiplier}, first_today={first_today}")
        await session.commit()
    return payment, credited_total


# ============================
# ОФФЕРЫ
# ============================
async def get_active_offers(session: AsyncSession) -> list["Offer"]:
    return (await session.execute(
        select(Offer).where(Offer.is_active, Offer.status == "approved")
    )).scalars().all()


async def get_rentable_offers(session: AsyncSession) -> list["Offer"]:
    return (await session.execute(
        select(Offer).where(
            Offer.is_active,
            Offer.status == "approved",
            Offer.is_rentable,
        )
    )).scalars().all()


async def get_offer_by_id(session: AsyncSession, offer_id: int) -> "Offer | None":
    return (await session.execute(
        select(Offer).where(Offer.id == offer_id)
    )).scalar_one_or_none()


async def _get_today_offer_rewards_total(session: AsyncSession, user_id: int) -> Decimal:
    today = utc_now().date()
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
        await change_balance_atomic(
            session,
            user.id,
            preview_reward,
            "offer_preview",
            source_id=offer_id,
        )
        # user.balance += preview_reward  # Handled by change_balance_atomic
    session.add(part)
    await session.commit()
    return part, True


async def verify_offer_subscription(
    session: AsyncSession,
    user_id: int,
    offer_id: int,
) -> tuple[bool, Decimal]:
    """Mark offer participation as completed and return actual paid amount.

    The payout can be lower than offer.reward_final because OFFER_DAILY_REWARD_CAP
    limits total offer rewards per day. The second tuple item is the amount that
    was really added to the balance during this call.
    """
    part = (await session.execute(
        select(OfferParticipation).where(
            OfferParticipation.user_id == user_id,
            OfferParticipation.offer_id == offer_id,
        )
    )).scalar_one_or_none()
    if not part:
        return False, Decimal("0")
    if part.status == "completed":
        return True, Decimal("0")

    offer = await get_offer_by_id(session, offer_id)
    user = await get_user_by_id(session, user_id)
    if not offer or not user:
        return False, Decimal("0")

    part.status = "completed"
    part.checked_at = utc_now()

    already_paid = to_decimal(part.reward_given)
    today_offer_rewards = await _get_today_offer_rewards_total(session, user_id)
    cap_remaining = max(to_decimal(OFFER_DAILY_REWARD_CAP) - today_offer_rewards, Decimal("0"))
    additional = min(
        max(to_decimal(offer.reward_final) - already_paid, Decimal("0")),
        cap_remaining,
    )
    if additional > 0:
        await change_balance_atomic(
            session,
            user.id,
            additional,
            "offer_complete",
            source_id=offer_id,
        )
        # user.balance += additional  # Handled by change_balance_atomic
        part.reward_given = already_paid + additional

    await session.commit()
    return True, additional


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

    await change_balance_atomic(
        session,
        user.id,
        -total_charge,
        "offer_unsubscribe_penalty",
        source_id=offer.id,
        details=f"reward_revoke={rewarded_total}; extra_penalty={extra_penalty}",
    )
    # user.balance -= total_charge # Handled by change_balance_atomic
    part.status = "unsubscribed"
    part.unsubscribed_penalized_at = utc_now()
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
        .order_by(OfferParticipation.checked_at.asc().nullsfirst())
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


# Система аренды слотов отключена (OfferRental удалена)


# ============================
# ИГРОВЫЕ СЕССИИ
# ============================
async def get_or_create_game_session(session: AsyncSession, user_id: int) -> GameSession:
    now = utc_now()
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
    await change_balance_atomic(session, user.id, -cost, "game_session_paid")
    gs = await get_or_create_game_session(session, user_id)
    gs.games_played = 0
    gs.window_start = utc_now()
    gs.paid_at = utc_now()
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
        select(func.count(User.id)).where(User.vip_until > utc_now())
    )).scalar_one()
    with_nickname = (await session.execute(
        select(func.count(User.id)).where(User.nickname_set)
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
    return {
        "users": users, "vip": vip, "with_nickname": with_nickname,
        "comments": comments, "reactions": reactions, "games": games,
        "offers": offers, "active_rentals": 0,
        "total_balance_in_system": total_balance,
        "total_admin_given": total_admin_given,
        "total_game_profit": total_game_profit,
        "total_rent_income": Decimal("0"),
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
    week_ago = utc_now() - timedelta(days=7)
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
    auto_commit: bool = True,
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
    # Dead call removed: is_admin_or_super(creator_tg_id, user)

    if not admin_free:
        # Проверка VIP (бесплатный промокод раз в месяц)
        # Correct logic: separate month-tracking field
        if user.vip_until and user.vip_until > utc_now():
            month_key = utc_now().year * 12 + utc_now().month
            # Use dedicated promo_month field to track last reset month
            promo_month = getattr(user, 'promo_month', 0) or 0
            # Сбрасываем счётчик если новый месяц
            if promo_month != month_key:
                user.promo_created_this_month = 0
                user.promo_month = month_key
            if user.promo_created_this_month < VIP_FREE_PROMO_PER_MONTH:
                star_cost = 0
                user.promo_created_this_month += 1

        # Если не админ и нужна оплата -> нужен инвойс (здесь просто возвращаем стоимость)
        if star_cost > 0:
            # Проверяем только стоимость, само списание будет через инвойс
            pass

    code = generate_promocode_str()
    expires_at = utc_now() + timedelta(hours=hours)

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
    if auto_commit:
        await session.commit()
    else:
        await session.flush()
    await log_user_action(session, user.id, "create_promocode",
                          f"code={code}, amount={coin_amount}, uses={max_uses}, admin_free={admin_free}",
                          auto_commit=auto_commit)
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
    if promo.expires_at and promo.expires_at < utc_now():
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
    await change_balance_atomic(session, user.id, amount, "promocode_activation",
                                 details=f"code={promo.code}")
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
            await change_balance_atomic(session, creator.id, bonus, "promocode_creator_bonus",
                                         details=f"code={promo.code}, activator={user_id}")
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
async def _get_lottery_window(session, dt: datetime) -> tuple[str, datetime, datetime, datetime]:
    from app.config import LOTTERY_INTERVAL_HOURS, LOTTERY_DRAW_DURATION_HOURS
    
    db_interval = await get_setting(session, "lottery_interval_hours", "")
    db_duration = await get_setting(session, "lottery_draw_duration_hours", "")
    
    interval = int(db_interval) if db_interval.isdigit() else LOTTERY_INTERVAL_HOURS
    draw_dur = int(db_duration) if db_duration.isdigit() else LOTTERY_DRAW_DURATION_HOURS
    
    epoch = datetime(1970, 1, 1, 20, 0, 0)
    delta = dt - epoch
    
    if interval < 1: interval = 48
    if draw_dur < 1: draw_dur = 2
    
    cycle_idx = int(delta.total_seconds() // (interval * 3600))
    
    start = epoch + timedelta(hours=cycle_idx * interval)
    draw_start = start + timedelta(hours=max(1, interval - draw_dur))
    draw_end = start + timedelta(hours=interval)
    
    key = f"lottery_{interval}h_{cycle_idx}"
    return key, start, draw_start, draw_end

def _serialize_numbers(nums: list[int], *, sort_numbers: bool = True) -> str:
    values = sorted(nums) if sort_numbers else list(nums)
    return ",".join(str(n) for n in values)

def _deserialize_numbers(raw: str | None) -> list[int]:
    if not raw:
        return []
    try:
        return [int(x) for x in raw.split(",") if x.strip()]
    except Exception:
        return []

async def ensure_current_lottery_round(session: AsyncSession) -> LotteryRound:
    now = utc_now()
    key, start, draw_start, draw_end = await _get_lottery_window(session, now)
    
    existing = (await session.execute(
        select(LotteryRound).where(LotteryRound.week_key == key)
    )).scalar_one_or_none()
    
    if existing:
        return existing

    round_obj = LotteryRound(
        week_key=key,
        status="open",
        ticket_price=to_decimal(LOTTERY_TICKET_PRICE),
        numbers_pool=max(10, LOTTERY_NUMBERS_POOL),
        numbers_per_ticket=max(3, LOTTERY_NUMBERS_PER_TICKET),
        drawn_numbers="",
        prize_pool=Decimal("0"),
        starts_at=start,
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
    now = utc_now()
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
    tickets_count = int(round_obj.prize_pool / round_obj.ticket_price) if round_obj.ticket_price else 0
    return {
        "round_id": round_obj.id,
        "week_key": round_obj.week_key,
        "status": round_obj.status,
        "ticket_price": float(round_obj.ticket_price),
        "prize_pool": float(round_obj.prize_pool),
        "tickets_count": tickets_count,
        "numbers_pool": round_obj.numbers_pool,
        "numbers_per_ticket": round_obj.numbers_per_ticket,
        "drawn_numbers": drawn,
        "draw_starts_at": round_obj.draw_starts_at.isoformat(),
        "draw_ends_at": round_obj.draw_ends_at.isoformat(),
    }


async def draw_next_lottery_number(session: AsyncSession, round_obj: LotteryRound) -> int | None:
    drawn = _deserialize_numbers(round_obj.drawn_numbers)
    drawn_set = set(drawn)
    all_numbers = set(range(1, round_obj.numbers_pool + 1))
    available = sorted(all_numbers - drawn_set)
    if not available:
        return None

    next_num = random.choice(available)
    drawn.append(next_num)
    round_obj.drawn_numbers = _serialize_numbers(drawn, sort_numbers=False)
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
        n = round_obj.numbers_per_ticket
        if matched >= n:
            winners_6.append(t)
        elif matched == n - 1:
            winners_5.append(t)
        elif matched == n - 2:
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
            await change_balance_atomic(
                session,
                user.id,
                per_ticket,
                source,
                source_id=round_obj.id,
                details=f"ticket_id={t.id}; matched={t.matched_count}",
            )
            t.reward_paid = True
            paid_total += per_ticket

    # Рассчитываем ставки на первый/последний бочонок Секслото.
    # Берём данные напрямую из drawn_numbers текущего раунда,
    # чтобы settlement не зависел от сторонних runtime-настроек.
    try:
        drawn_list = _deserialize_numbers(round_obj.drawn_numbers)
        if drawn_list:
            first_num = drawn_list[0]
            last_num = drawn_list[-1]

            from app.models import LotteryBet
            bets_result = await session.execute(
                select(LotteryBet).where(
                    LotteryBet.round_id == round_obj.id,
                    LotteryBet.is_settled == False,
                )
            )
            bets = bets_result.scalars().all()

            for bet in bets:
                is_won = False
                if bet.bet_type == "first_even" and first_num % 2 == 0:
                    is_won = True
                elif bet.bet_type == "first_odd" and first_num % 2 != 0:
                    is_won = True
                elif bet.bet_type == "last_even" and last_num % 2 == 0:
                    is_won = True
                elif bet.bet_type == "last_odd" and last_num % 2 != 0:
                    is_won = True

                bet.is_settled = True
                bet.is_won = is_won

                if is_won:
                    win_amount = bet.amount * to_decimal(2.0)
                    user = await get_user_by_id(session, bet.user_id)
                    if user:
                        await change_balance_atomic(
                            session,
                            user.id,
                            win_amount,
                            "lottery_bet_win",
                            source_id=round_obj.id,
                            details=f"bet_id={bet.id}; type={bet.bet_type}; win={win_amount}",
                        )
    except Exception as e:
        logger.warning(f"Error settling lottery bets: {e}")

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


async def should_show_ad_after_video(session: AsyncSession, user_id: int) -> bool:
    """
    Проверяет, пора ли показать рекламу.
    Реклама показывается каждое 10-е видео.
    """
    state = await get_or_create_user_ad_state(session, user_id)
    # Каждое 10-е видео
    return state.videos_watched_since_ad >= 10


async def increment_video_watched(session: AsyncSession, user_id: int) -> int:
    """Увеличить счётчик просмотренных видео. Возвращает новое значение."""
    state = await get_or_create_user_ad_state(session, user_id)
    state.videos_watched_since_ad += 1
    await session.commit()
    return state.videos_watched_since_ad


async def reset_ad_counter(session: AsyncSession, user_id: int) -> None:
    """Сбросить счётчик после показа рекламы."""
    state = await get_or_create_user_ad_state(session, user_id)
    state.videos_watched_since_ad = 0
    state.updated_at = utc_now()
    await session.commit()


async def can_show_offer_to_user(session: AsyncSession, user_id: int) -> bool:
    state = await get_or_create_user_ad_state(session, user_id)
    if state.last_offer_shown_at is None:
        return True
    elapsed = (utc_now() - state.last_offer_shown_at).total_seconds() / 60
    return elapsed >= SMART_AD_MIN_INTERVAL_MINUTES


async def mark_offer_shown(session: AsyncSession, user_id: int,
                           offer_id: int = None, forced: bool = False) -> None:
    state = await get_or_create_user_ad_state(session, user_id)
    state.last_offer_shown_at = utc_now()
    state.updated_at = utc_now()
    if forced and offer_id:
        state.forced_offer_id = offer_id
        state.forced_offer_shown_at = utc_now()
    await session.commit()


async def should_show_low_balance_hint(session: AsyncSession, user: "User") -> bool:
    if float(user.balance) > SMART_AD_LOW_BALANCE_THRESHOLD:
        return False
    state = await get_or_create_user_ad_state(session, user.id)
    if state.last_low_balance_hint_at is None:
        return True
    elapsed = (utc_now() - state.last_low_balance_hint_at).total_seconds() / 60
    return elapsed >= SMART_AD_LOW_BALANCE_HINT_INTERVAL_MINUTES


async def mark_low_balance_hint_shown(session: AsyncSession, user_id: int) -> None:
    state = await get_or_create_user_ad_state(session, user_id)
    state.last_low_balance_hint_at = utc_now()
    state.updated_at = utc_now()
    await session.commit()


async def get_random_active_offer(session: AsyncSession) -> "Offer | None":
    return (await session.execute(
        select(Offer).where(
            Offer.is_active, Offer.status == "approved",
        ).order_by(func.random()).limit(1)
    )).scalar_one_or_none()


def should_inject_ad_in_video() -> bool:
    return random.random() < SMART_AD_VIDEO_CHANCE


async def get_active_sale(session: AsyncSession):
    stmt = select(ActiveSale).where(ActiveSale.end_date > utc_now()).order_by(ActiveSale.id.desc()).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()

def _discount_stars_amount(base_stars: int, discount: float) -> int:
    return max(1, math.ceil(base_stars * (1.0 - discount)))


async def get_current_prices(session: AsyncSession, user_id: int | None = None):
    try:
        from app.config import VIP_PRICE_STARS, STARS_PACKAGES
        sale = await get_active_sale(session)
        active_events = await get_active_events(session)

        vip_price = int(VIP_PRICE_STARS)
        packs = {}
        for k, v in STARS_PACKAGES.items():
            packs[k] = {"stars": v["stars"], "coins": v["coins"], "title": v["title"]}

        # Применяем скидки от событий
        total_discount = 0
        if active_events:
            for ev in active_events:
                total_discount = max(total_discount, ev.discount_percent)

        if total_discount > 0:
            discount = total_discount / 100.0
            if any(e.applies_vip for e in active_events):
                vip_price = _discount_stars_amount(vip_price, discount)
            if any(e.applies_coins for e in active_events):
                for k in packs:
                    packs[k]["stars"] = _discount_stars_amount(packs[k]["stars"], discount)

        # Также применяем старую систему ActiveSale
        if sale:
            discount = sale.discount_percent / 100.0
            if sale.applies_to in ("all", "vip"):
                vip_price = _discount_stars_amount(vip_price, discount)
            if sale.applies_to in ("all", "coins"):
                for k in packs:
                    packs[k]["stars"] = _discount_stars_amount(packs[k]["stars"], discount)

        # Персональная скидка за перк действует поверх акций/сейлов.
        if user_id is not None:
            stars_discount = await get_stars_discount(session, user_id)
            if stars_discount > 0:
                vip_price = _discount_stars_amount(vip_price, stars_discount)
                for k in packs:
                    packs[k]["stars"] = _discount_stars_amount(packs[k]["stars"], stars_discount)

        return vip_price, packs, sale
    except Exception as e:
        log_error(logger, f"Error in get_current_prices: {e}")
        raise


async def get_active_events(session: AsyncSession):
    """Получить все активные события"""
    stmt = select(Event).where(
        Event.is_active == True,
        Event.end_date > utc_now()
    ).order_by(Event.discount_percent.desc())
    result = await session.execute(stmt)
    return result.scalars().all()


# ============================
# ПЕРКИ ПОЛЬЗОВАТЕЛЕЙ (UserPerk)
# ============================
async def has_active_perk(session: AsyncSession, user_id: int, perk_type: str) -> bool:
    """Проверка, есть ли у пользователя активный перк указанного типа"""
    now = utc_now()
    perk = (await session.execute(
        select(UserPerk).where(
            UserPerk.user_id == user_id,
            UserPerk.perk_type == perk_type,
            UserPerk.is_active == True,
            UserPerk.active_until > now,
        )
    )).scalar_one_or_none()
    return perk is not None


async def get_coin_multiplier(session: AsyncSession, user_id: int) -> float:
    """Получить множитель монет для пользователя (учитывает VIP и перки)"""
    user = await get_user_by_id(session, user_id)
    if not user:
        return 1.0
    
    # VIP даёт множитель
    multiplier = 1.0
    if user.vip_until and user.vip_until > utc_now():
        from app.config import VIP_BONUS_MULTIPLIER
        multiplier = float(VIP_BONUS_MULTIPLIER)
    
    # Перк coin_multiplier переопределяет
    coin_boost = (await session.execute(
        select(UserPerk).where(
            UserPerk.user_id == user_id,
            UserPerk.perk_type == "coin_multiplier",
            UserPerk.is_active == True,
            UserPerk.active_until > utc_now(),
        )
    )).scalar_one_or_none()
    if coin_boost:
        multiplier = 1.5  # фиксированный бонус бустера
    
    return multiplier


async def get_xp_multiplier(session: AsyncSession, user_id: int) -> float:
    """Получить множитель XP для пользователя"""
    xp_boost = (await session.execute(
        select(UserPerk).where(
            UserPerk.user_id == user_id,
            UserPerk.perk_type == "xp_multiplier",
            UserPerk.is_active == True,
            UserPerk.active_until > utc_now(),
        )
    )).scalar_one_or_none()
    return 2.0 if xp_boost else 1.0


async def get_active_perks(session: AsyncSession, user_id: int) -> list[UserPerk]:
    """Получить все активные перки пользователя"""
    now = utc_now()
    return (await session.execute(
        select(UserPerk).where(
            UserPerk.user_id == user_id,
            UserPerk.is_active == True,
            UserPerk.active_until > now,
        ).order_by(UserPerk.active_until)
    )).scalars().all()


async def get_stars_discount(session: AsyncSession, user_id: int) -> float:
    """Получить скидку на Stars (0.0 = нет скидки, 0.25 = 25%)"""
    user = await get_user_by_id(session, user_id)
    if not user:
        return 0.0
    
    # Проверяем перк
    stars_discount_perk = (await session.execute(
        select(UserPerk).where(
            UserPerk.user_id == user_id,
            UserPerk.perk_type == "stars_discount",
            UserPerk.is_active == True,
            UserPerk.active_until > utc_now(),
        )
    )).scalar_one_or_none()
    if stars_discount_perk:
        return 0.25
    
    return 0.0


async def activate_perk(
    session: AsyncSession,
    user_id: int,
    perk_type: str,
    duration_days: int,
    *,
    style_id: int | None = None,
) -> UserPerk:
    """Активировать/продлить перк для пользователя.

    style_id: 1-50 для custom_nick, None для остальных.
    При продлении custom_nick: если передан новый style_id — заменяет старый.
    """
    now = utc_now()
    existing = (await session.execute(
        select(UserPerk).where(
            UserPerk.user_id == user_id,
            UserPerk.perk_type == perk_type,
            UserPerk.is_active == True,
        )
    )).scalar_one_or_none()
    
    if existing:
        # Продлеваем существующий
        new_end = max(existing.active_until, now) + timedelta(days=duration_days)
        existing.active_until = new_end
        # Для custom_nick — обновляем style_id если передан
        if perk_type == "custom_nick" and style_id is not None:
            existing.style_id = style_id
        await session.commit()
        return existing
    else:
        perk = UserPerk(
            user_id=user_id,
            perk_type=perk_type,
            style_id=style_id,
            active_until=now + timedelta(days=duration_days),
        )
        session.add(perk)
        await session.commit()
        return perk


async def deactivate_perk(session: AsyncSession, user_id: int, perk_type: str) -> bool:
    """Деактивировать перк"""
    perk = (await session.execute(
        select(UserPerk).where(
            UserPerk.user_id == user_id,
            UserPerk.perk_type == perk_type,
            UserPerk.is_active == True,
        )
    )).scalar_one_or_none()
    if perk:
        perk.is_active = False
        await session.commit()
        return True
    return False


PERK_ICONS = {
    "custom_nick": "🎨",
    "coin_multiplier": "💰",
    "xp_multiplier": "📈",
    "stars_discount": "⭐",
    "priority_moderation": "⚡",
    "exclusive_reactions": "✨",
}


PERK_NAMES = {
    "custom_nick": "🎨 Кастомный ник",
    "coin_multiplier": "💰 Бустер монет x1.5",
    "xp_multiplier": "📈 Бустер XP x2",
    "stars_discount": "⭐ Скидка 25% на Stars",
    "priority_moderation": "⚡ Приоритетная модерация",
    "exclusive_reactions": "✨ Эксклюзивные реакции",
}


# ============================
# ЖАЛОБЫ НА ВИДЕО (VideoReport)
# ============================

REPORT_REASONS = {
    "spam": "Спам / реклама",
    "shock": "Шок-контент",
    "copyright": "Нарушение авторских прав",
    "other": "Другое",
}


async def create_video_report(
    session: AsyncSession,
    reporter_user_id: int,
    video_id: int,
    reason: str,
    comment: str | None = None,
) -> "VideoReport | None":
    """Создать жалобу на видео. Одна жалоба от юзера на одно видео."""
    from app.models import VideoReport
    if reason not in REPORT_REASONS:
        return None
    # Проверяем, не жаловался ли уже
    existing = (await session.execute(
        select(VideoReport).where(
            VideoReport.reporter_user_id == reporter_user_id,
            VideoReport.video_id == video_id,
        )
    )).scalar_one_or_none()
    if existing:
        return None
    report = VideoReport(
        reporter_user_id=reporter_user_id,
        video_id=video_id,
        reason=reason,
        comment=comment,
    )
    session.add(report)
    await session.commit()
    return report


async def get_pending_reports(session: AsyncSession, limit: int = 50) -> list:
    from app.models import VideoReport
    return (await session.execute(
        select(VideoReport).where(
            VideoReport.status == "pending",
        ).order_by(VideoReport.created_at.desc()).limit(limit)
    )).scalars().all()


async def dismiss_report(session: AsyncSession, report_id: int, admin_id: int) -> bool:
    from app.models import VideoReport
    report = (await session.execute(
        select(VideoReport).where(VideoReport.id == report_id)
    )).scalar_one_or_none()
    if not report:
        return False
    report.status = "reviewed"
    report.reviewed_by = admin_id
    await session.commit()
    return True


# ============================
# АГРЕГИРОВАННЫЕ УВЕДОМЛЕНИЯ МОДЕРАЦИИ
# ============================

# Минимальная пауза между уведомлениями одного вида (секунды)
_MOD_NOTIFY_COOLDOWN = 120


async def schedule_mod_notification(session: AsyncSession, kind: str) -> None:
    """Запланировать агрегированное уведомление.
    
    Вместо 500 пушей при 500 видео — одна запись с count.
    Если unsent-запись того же вида уже есть — +1 к count.
    """
    from app.models import ModNotification
    existing = (await session.execute(
        select(ModNotification).where(
            ModNotification.kind == kind,
            ModNotification.is_sent == False,
        )
    )).scalar_one_or_none()
    if existing:
        existing.count += 1
        await session.commit()
    else:
        n = ModNotification(kind=kind, count=1, is_sent=False)
        session.add(n)
        await session.commit()


async def flush_mod_notifications(bot, session: AsyncSession) -> int:
    """Отправить все несент-уведомления админам.
    
    Группирует по kind, отправляет одно сообщение на вид.
    Возвращает количество отправленных.
    """
    from app.models import ModNotification
    pending = (await session.execute(
        select(ModNotification).where(ModNotification.is_sent == False)
    )).scalars().all()
    if not pending:
        return 0

    # Агрегируем
    by_kind: dict[str, int] = {}
    for n in pending:
        by_kind[n.kind] = by_kind.get(n.kind, 0) + n.count

    kind_labels = {
        "video": "📹 Видео/фото на модерации",
        "offer": "📢 Офферы на модерации",
        "report": "🚨 Жалобы на контент",
    }

    lines = ["🔔 <b>Модерация: сводка</b>\n"]
    for kind, count in by_kind.items():
        label = kind_labels.get(kind, kind)
        lines.append(f"  {label}: <b>{count}</b>")

    lines.append("\n/admin — панель модерации")
    text = "\n".join(lines)

    sent = 0
    for admin_tid in ADMINS:
        try:
            await bot.send_message(admin_tid, text, parse_mode="HTML")
            sent += 1
        except Exception:
            pass

    # Пометить как отправленные
    for n in pending:
        n.is_sent = True
        n.sent_at = utc_now()
    await session.commit()
    return sent


async def should_flush_notifications(session: AsyncSession) -> bool:
    """Пора ли отправлять сводку? Да, если есть несент-записи
    и с момента последней отправки прошло >COOLDOWN секунд."""
    from app.models import ModNotification
    pending = (await session.execute(
        select(ModNotification).where(ModNotification.is_sent == False)
    )).scalars().all()
    if not pending:
        return False
    # Если последняя отправка была недавно — подождём, накопим ещё
    last_sent = (await session.execute(
        select(ModNotification).where(
            ModNotification.is_sent == True,
            ModNotification.sent_at.isnot(None),
        ).order_by(ModNotification.sent_at.desc()).limit(1)
    )).scalar_one_or_none()
    if last_sent and (utc_now() - last_sent.sent_at).total_seconds() < _MOD_NOTIFY_COOLDOWN:
        return False
    return True


# ============================
# APPROVE ALL
# ============================

async def approve_all_pending(session: AsyncSession, admin_id: int, limit: int = None) -> int:
    """Одобрить все pending-видео и фото. Возвращает количество."""
    from app.models import Video, User
    query = select(Video).where(Video.status == "pending")
    if limit:
        query = query.limit(limit)
    pending = (await session.execute(query)).scalars().all()
    if not pending:
        return 0
    # N+1 fix: load all uploaders in one query
    uploader_ids = list({v.uploader_user_id for v in pending})
    uploaders = (await session.execute(
        select(User).where(User.id.in_(uploader_ids))
    )).scalars().all()
    uploader_map = {u.id: u for u in uploaders}
    count = 0
    for v in pending:
        v.status = "approved"
        v.rejection_reason = None
        # Начисляем награду загрузчику
        uploader = uploader_map.get(v.uploader_user_id)
        if uploader:
            reward = await calculate_upload_reward(session, uploader.id, v.content_type)
            await change_balance_atomic(session, uploader.id, reward, "upload_approved", source_id=v.id)
        count += 1
    await session.commit()
    await log_user_action(session, admin_id, "approve_all", f"count={count}")
    return count


async def broadcast_event_to_users(bot, event: Event) -> int:
    """
    Рассылка уведомления о новом событии всем активным пользователям.
    Возвращает количество отправленных сообщений.
    """
    from app.db import async_session
    
    async with async_session() as session:
        users = (await session.execute(
            select(User.telegram_id, User.first_name).where(User.status == "active")
        )).all()
    
    applies = []
    if event.applies_vip:
        applies.append("VIP")
    if event.applies_coins:
        applies.append("монеты")
    if event.applies_lootbox:
        applies.append("лутбоксы")
    if event.applies_cases:
        applies.append("кейсы")
    
    applies_text = ", ".join(applies) if applies else "всё"
    end_text = event.end_date.strftime("%d.%m.%Y")
    
    text = (
        f"🎉 <b>{event.name}</b>\n\n"
        f"{event.description}\n\n"
        f"🔥 Скидка <b>{event.discount_percent}%</b> на {applies_text}!\n"
        f"⏰ Акция до {end_text}\n\n"
        f"Не пропусти!"
    )
    
    sent = 0
    for tid, first_name in users:
        try:
            if event.image_file_id:
                await bot.send_photo(tid, event.image_file_id, caption=text, parse_mode="HTML")
            else:
                await bot.send_message(tid, text, parse_mode="HTML")
            sent += 1
            if sent % 20 == 0:
                await asyncio.sleep(0.5)  # anti-spam
        except Exception:
            pass
    
    return sent


async def broadcast_sale_to_users(bot, sale: ActiveSale) -> int:
    """
    Рассылка уведомления о новой акции всем активным пользователям.
    """
    from app.db import async_session
    
    async with async_session() as session:
        users = (await session.execute(
            select(User.telegram_id).where(User.status == "active")
        )).scalars().all()
    
    applies_map = {"all": "всё", "vip": "VIP", "coins": "монеты"}
    applies_text = applies_map.get(sale.applies_to, sale.applies_to)
    end_text = sale.end_date.strftime("%d.%m.%Y %H:%M")
    announcement = sale.announcement or f"Скидка {sale.discount_percent}% на {applies_text}!"
    
    text = (
        f"🛍 <b>Акция!</b>\n\n"
        f"{announcement}\n\n"
        f"🔥 Скидка <b>{sale.discount_percent}%</b> на {applies_text}\n"
        f"⏰ До {end_text}\n\n"
        f"Успей воспользоваться!"
    )
    
    sent = 0
    for tid in users:
        try:
            await bot.send_message(tid, text, parse_mode="HTML")
            sent += 1
            if sent % 20 == 0:
                await asyncio.sleep(0.5)
        except Exception:
            pass
    
    return sent


# ============================
# STUBS FOR DISABLED RENTAL SYSTEM (to prevent import errors)
# ============================
async def count_active_rentals(session):
    return 0

async def expire_old_rentals(session):
    return 0

async def create_offer_rental(session, offer_id, user_id, channel_title, channel_url, rent_days):
    return None, "Rental system is disabled in this version."

async def get_user_rentals(session, user_id):
    return []

# ============================
# BOT SETTINGS
# ============================
async def get_setting(session: AsyncSession, key: str, default: str = "") -> str:
    from app.models import BotSetting
    from sqlalchemy import select
    result = await session.execute(select(BotSetting).where(BotSetting.key == key))
    setting = result.scalar_one_or_none()
    return setting.value if setting else default

async def set_setting(session: AsyncSession, key: str, value: str):
    from app.models import BotSetting
    from sqlalchemy import select
    result = await session.execute(select(BotSetting).where(BotSetting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        setting = BotSetting(key=key, value=value)
        session.add(setting)
    await session.commit()


async def get_config_value(session: AsyncSession, key: str, default=None):
    """
    Читает значение настройки: сначала из БД (runtime), потом из config.py (fallback).
    Возвращает строку, если значение найдено, иначе default.
    """
    db_val = await get_setting(session, key, "")
    if db_val:
        return db_val
    return default


# Маппинг ключей настроек → значения из config.py по умолчанию
_SETTINGS_DEFAULTS = {
    # Экономика
    "starting_balance": STARTING_BALANCE,
    "watch_cost": WATCH_COST,
    "upload_reward": UPLOAD_REWARD,
    "photo_upload_reward": PHOTO_UPLOAD_REWARD,
    "stars_to_coins_rate": STARS_TO_COINS_RATE,
    "referral_reward_inviter": REFERRAL_REWARD_INVITER,
    "referral_reward_new_user": REFERRAL_REWARD_NEW_USER,
    "daily_bonus_base": DAILY_BONUS_STREAK_BASE,
    "daily_bonus_increase": DAILY_BONUS_STREAK_INCREASE,
    "daily_bonus_streak_max": MAX_BONUS_STREAK,
    "first_purchase_daily_bonus": FIRST_PURCHASE_DAILY_BONUS,
    # VIP
    "vip_price_stars": VIP_PRICE_STARS,
    "vip_duration_days": VIP_DURATION_DAYS,
    "vip_bonus_multiplier": VIP_BONUS_MULTIPLIER,
    "vip_watch_discount": VIP_WATCH_DISCOUNT,
    # Никнеймы
    "nickname_change_cost": NICKNAME_CHANGE_COST,
    "nickname_min_length": NICKNAME_MIN_LENGTH,
    "nickname_max_length": NICKNAME_MAX_LENGTH,
    "daily_photo_limit": DAILY_PHOTO_LIMIT,
    # Игры
    "dice_min_bet": 1,  # DICE_MIN_BET
    "dice_max_bet": 50,  # DICE_MAX_BET
    "free_games_per_session": FREE_GAMES_PER_SESSION,
    "game_session_hours": GAME_SESSION_HOURS,
    "game_session_cost": GAME_SESSION_COST,
    # Лотерея
    "lottery_ticket_price": LOTTERY_TICKET_PRICE,
    "lottery_numbers_pool": LOTTERY_NUMBERS_POOL,
    "lottery_numbers_per_ticket": LOTTERY_NUMBERS_PER_TICKET,
    # Лутбоксы
    "lootbox_coin_price": LOOTBOX_COIN_PRICE,
    "lootbox_star_price": LOOTBOX_STAR_PRICE,
    # Реклама
    "smart_ad_video_chance": SMART_AD_VIDEO_CHANCE,
    "smart_ad_forced_watch_seconds": SMART_AD_FORCED_WATCH_SECONDS,
    "smart_ad_min_interval_minutes": SMART_AD_MIN_INTERVAL_MINUTES,
    "smart_ad_low_balance_threshold": SMART_AD_LOW_BALANCE_THRESHOLD,
    "smart_ad_low_balance_hint_interval": SMART_AD_LOW_BALANCE_HINT_INTERVAL_MINUTES,
    "offer_daily_reward_cap": OFFER_DAILY_REWARD_CAP,
    "videos_per_ad_interval": 10,
    # Промокоды
    "promocode_creation_star_rate": PROMOCODE_CREATION_STAR_RATE,
    "promocode_bulk_discount_threshold": PROMOCODE_BULK_DISCOUNT_THRESHOLD,
    "promocode_bulk_discount_rate": PROMOCODE_BULK_DISCOUNT_RATE,
    "promocode_creator_bonus_percent": PROMOCODE_CREATOR_BONUS_PERCENT,
    "promocode_max_amount": PROMOCODE_MAX_AMOUNT,
    "promocode_max_uses": PROMOCODE_MAX_USES,
    "promocode_max_hours": PROMOCODE_MAX_HOURS,
    "vip_free_promo_per_month": VIP_FREE_PROMO_PER_MONTH,
}


async def get_runtime_value(session: AsyncSession, key: str):
    """
    Возвращает runtime-значение настройки (из БД или config.py fallback).
    Автоматически конвертирует тип.
    """
    db_val = await get_setting(session, key, "")
    if db_val:
        # Пробуем int → float → str
        try:
            return int(db_val)
        except (ValueError, TypeError):
            pass
        try:
            return float(db_val)
        except (ValueError, TypeError):
            pass
        return db_val
    
    return _SETTINGS_DEFAULTS.get(key)

async def log_balance_change(
    session: AsyncSession,
    user: "User",
    amount: Decimal,
    source: str,
    source_id: int = None,
    admin_id: int = None,
    details: str = None,
):
    """
    Записывает изменение баланса в лог, но не меняет сам баланс пользователя.

    Исторически многие места в коде сначала вызывают этот логгер, а потом уже
    вручную меняют `user.balance += amount` / `-=`. Поэтому здесь намеренно
    только логирование, без повторного списания/начисления.
    """
    before = user.balance if user.balance is not None else Decimal("0")
    after = before + amount
    log = BalanceLog(
        user_id=user.id,
        amount=amount,
        balance_before=before,
        balance_after=after,
        source=source,
        source_id=source_id,
        admin_id=admin_id,
        details=details,
    )
    session.add(log)
