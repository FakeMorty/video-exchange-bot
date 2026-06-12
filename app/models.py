from datetime import datetime
from decimal import Decimal
from sqlalchemy import (
    func,
    BigInteger, String, Numeric, Boolean,
    Integer, DateTime, ForeignKey, UniqueConstraint, Text, Date,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from typing import List


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(50), default="active")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    agreed_to_rules: Mapped[bool] = mapped_column(Boolean, default=False)
    nickname_set: Mapped[bool] = mapped_column(Boolean, default=False)
    referral_code: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True)
    referred_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    referral_earnings: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    referrals_count: Mapped[int] = mapped_column(Integer, default=0)
    referral_milestone_level: Mapped[int] = mapped_column(Integer, default=0)
    last_bonus_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    bonus_streak: Mapped[int] = mapped_column(Integer, default=0)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[int] = mapped_column(Integer, default=1)
    vip_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    promo_created_this_month: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Отношения
    videos: Mapped[List["Video"]] = relationship(back_populates="uploader")
    views: Mapped[List["VideoView"]] = relationship(back_populates="user")
    ratings: Mapped[List["VideoRating"]] = relationship(back_populates="user")
    payments: Mapped[List["Payment"]] = relationship(back_populates="user")
    comments: Mapped[List["Comment"]] = relationship(back_populates="user")
    reactions: Mapped[List["ContentReaction"]] = relationship(back_populates="user")
    game_history: Mapped[List["GameHistory"]] = relationship(back_populates="user")
    quest_progress: Mapped[List["DailyQuestProgress"]] = relationship(back_populates="user")
    game_sessions: Mapped[List["GameSession"]] = relationship(back_populates="user")
    action_logs: Mapped[List["UserActionLog"]] = relationship(back_populates="user")
    balance_logs: Mapped[List["BalanceLog"]] = relationship(back_populates="user")
    user_offers: Mapped[List["Offer"]] = relationship(back_populates="creator")
    rentals: Mapped[List["OfferRental"]] = relationship(
        back_populates="renter", foreign_keys="OfferRental.renter_user_id"
    )
    ad_state: Mapped["UserAdState"] = relationship(back_populates="user", uselist=False)
    created_promocodes: Mapped[List["Promocode"]] = relationship(back_populates="creator")
    activated_promocodes: Mapped[List["PromocodeActivation"]] = relationship(back_populates="user")
    lottery_tickets: Mapped[List["LotteryTicket"]] = relationship(back_populates="user")
    lootbox_opens: Mapped[List["LootboxOpen"]] = relationship(back_populates="user")
    trusted_uploaders: Mapped[List["TrustedUploader"]] = relationship(
        back_populates="admin",
        foreign_keys="TrustedUploader.admin_user_id",
    )


class LootboxOpen(Base):
    __tablename__ = "lootbox_opens"
    __table_args__ = (
        UniqueConstraint("payment_payload", name="uq_lootbox_payment_payload"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    payment_payload: Mapped[str | None] = mapped_column(String(255), nullable=True)
    pay_currency: Mapped[str] = mapped_column(String(10), nullable=False)  # "coins" | "stars"
    price_coins: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    price_stars: Mapped[int] = mapped_column(Integer, default=0)
    reward_coins: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    rarity: Mapped[str] = mapped_column(String(20), default="common")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    user: Mapped["User"] = relationship(back_populates="lootbox_opens")


class TrustedUploader(Base):
    """
    Per-admin whitelist of uploaders whose content can be auto-moderated.
    """
    __tablename__ = "trusted_uploaders"
    __table_args__ = (
        UniqueConstraint("admin_user_id", "trusted_user_id", name="uq_admin_trusted_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    trusted_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    admin: Mapped["User"] = relationship(foreign_keys=[admin_user_id], back_populates="trusted_uploaders")
    trusted: Mapped["User"] = relationship(foreign_keys=[trusted_user_id])


class UserActionLog(Base):
    __tablename__ = "user_action_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="action_logs")


class BalanceLog(Base):
    __tablename__ = "balance_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    balance_before: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    admin_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    user: Mapped["User"] = relationship(back_populates="balance_logs")


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uploader_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    content_type: Mapped[str] = mapped_column(String(20), default="video")
    telegram_file_id: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_file_unique_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    uploader: Mapped["User"] = relationship(back_populates="videos")
    views: Mapped[List["VideoView"]] = relationship(back_populates="video")
    ratings: Mapped[List["VideoRating"]] = relationship(back_populates="video")
    comments: Mapped[List["Comment"]] = relationship(back_populates="video")
    reactions: Mapped[List["ContentReaction"]] = relationship(back_populates="video")


class VideoView(Base):
    __tablename__ = "video_views"
    __table_args__ = (
        UniqueConstraint("user_id", "video_id", name="uq_user_video_view"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), nullable=False)
    watched_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        server_default=func.now(),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        server_default=func.now(),
    )

    user: Mapped["User"] = relationship(back_populates="views")
    video: Mapped["Video"] = relationship(back_populates="views")


class VideoRating(Base):
    __tablename__ = "video_ratings"
    __table_args__ = (
        UniqueConstraint("user_id", "video_id", name="uq_user_video_rating"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="ratings")
    video: Mapped["Video"] = relationship(back_populates="ratings")


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="comments")
    video: Mapped["Video"] = relationship(back_populates="comments")


class ContentReaction(Base):
    __tablename__ = "content_reactions"
    __table_args__ = (
        UniqueConstraint("user_id", "video_id", name="uq_user_video_reaction"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id"), nullable=False)
    reaction_type: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="reactions")
    video: Mapped["Video"] = relationship(back_populates="reactions")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    payload: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    stars_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    coins_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="payments")


class Offer(Base):
    __tablename__ = "offers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    creator_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    channel_url: Mapped[str] = mapped_column(Text, nullable=False)
    reward_preview: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("50"))
    reward_final: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("350"))
    penalty_unsubscribe: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("400"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="approved")
    
    # Новые поля для пользовательских офферов
    duration_days: Mapped[int] = mapped_column(Integer, default=30)           # на сколько дней создан оффер
    placement_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))  # сколько заплатил создатель
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    creator: Mapped["User"] = relationship(back_populates="user_offers")
    participations: Mapped[List["OfferParticipation"]] = relationship(back_populates="offer")


class OfferParticipation(Base):
    __tablename__ = "offer_participations"
    __table_args__ = (
        UniqueConstraint("user_id", "offer_id", name="uq_user_offer"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="started")
    reward_given: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    unsubscribed_penalized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    offer: Mapped["Offer"] = relationship(back_populates="participations")


# OfferRental удалена — система аренды слотов отключена


class GameHistory(Base):
    __tablename__ = "game_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    game_type: Mapped[str] = mapped_column(String(50), nullable=False)
    bet: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    result: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    user: Mapped["User"] = relationship(back_populates="game_history")


class DailyQuestProgress(Base):
    __tablename__ = "daily_quest_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "quest_type", "quest_date", name="uq_user_quest_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    quest_type: Mapped[str] = mapped_column(String(50), nullable=False)
    quest_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    target: Mapped[int] = mapped_column(Integer, nullable=False)
    reward: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    reward_claimed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="quest_progress")


class GameSession(Base):
    __tablename__ = "game_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    games_played: Mapped[int] = mapped_column(Integer, default=0)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="game_sessions")


class UserAdState(Base):
    __tablename__ = "user_ad_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, unique=True, index=True
    )
    last_offer_shown_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_low_balance_hint_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    forced_offer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forced_offer_shown_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="ad_state")


# ============================
# ПРОМОКОДЫ (НОВАЯ ТАБЛИЦА)
# ============================
class Promocode(Base):
    """Промокод, создаваемый пользователем за Stars."""
    __tablename__ = "promocodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    creator_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    coin_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    created_via_stars: Mapped[bool] = mapped_column(Boolean, default=True)  # False если админ создал бесплатно
    stars_paid: Mapped[int] = mapped_column(Integer, default=0)              # сколько Stars заплачено
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    creator: Mapped["User"] = relationship(back_populates="created_promocodes")
    activations: Mapped[List["PromocodeActivation"]] = relationship(back_populates="promocode")


class PromocodeActivation(Base):
    """Запись об активации промокода."""
    __tablename__ = "promocode_activations"
    __table_args__ = (
        UniqueConstraint("promocode_id", "user_id", name="uq_promo_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    promocode_id: Mapped[int] = mapped_column(
        ForeignKey("promocodes.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    promocode: Mapped["Promocode"] = relationship(back_populates="activations")
    user: Mapped["User"] = relationship(back_populates="activated_promocodes")


class Feedback(Base):
    __tablename__ = "feedback_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="suggestion")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class LotteryRound(Base):
    __tablename__ = "lottery_rounds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    week_key: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    ticket_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("3"))
    numbers_pool: Mapped[int] = mapped_column(Integer, nullable=False, default=36)
    numbers_per_ticket: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    drawn_numbers: Mapped[str | None] = mapped_column(Text, nullable=True)
    prize_pool: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    draw_starts_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    draw_ends_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    tickets: Mapped[List["LotteryTicket"]] = relationship(back_populates="round")


class LotteryTicket(Base):
    __tablename__ = "lottery_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("lottery_rounds.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    numbers: Mapped[str] = mapped_column(String(100), nullable=False)
    matched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reward_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    round: Mapped["LotteryRound"] = relationship(back_populates="tickets")
    user: Mapped["User"] = relationship(back_populates="lottery_tickets")


class ActiveSale(Base):
    __tablename__ = "active_sales"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discount_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    applies_to: Mapped[str] = mapped_column(String(50), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    announcement: Mapped[str] = mapped_column(Text, nullable=True)


# ============================
# НОВЫЕ СОБЫТИЯ (EVENTS) — гибкая система скидок
# ============================
class Event(Base):
    """
    Событие с гибкой настройкой скидок.
    Применяется к покупкам VIP, монет, лутбоксов и т.д.
    """
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    discount_percent: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-99
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)

    # Гибкие флаги применения
    applies_vip: Mapped[bool] = mapped_column(Boolean, default=False)
    applies_coins: Mapped[bool] = mapped_column(Boolean, default=False)
    applies_lootbox: Mapped[bool] = mapped_column(Boolean, default=False)
    applies_cases: Mapped[bool] = mapped_column(Boolean, default=False)  # если будут кейсы

    # Опциональная картинка (telegram_file_id)
    image_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    start_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    creator: Mapped["User"] = relationship(foreign_keys=[created_by])