"""Регрессионные тесты к исправлениям аудита 2026-10-13 (docs/bug-report-2026-10-13.md)."""
import asyncio
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import BalanceLog, Base, Offer, Payment, User, UserPerk, Video, utc_now


async def _mem_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


# ───────────────────────── B-01 / B-02 / B-04: сломанные хендлеры ─────────────────────────

def test_lottery_buy_button_is_bound_to_real_handler_not_formatter():
    """На кнопку «Купить билеты» раньше висел форматтер (TypeError на каждом нажатии)."""
    from app.user_handlers import router, _format_lottery_purchase_summary

    bound = [h.callback for h in router.callback_query.handlers]
    assert _format_lottery_purchase_summary not in bound
    assert any(h.callback.__name__ == "lottery_buy" for h in router.callback_query.handlers)


def test_admin_db_keyboard_builds():
    """`t` затенялась переменной цикла — кнопка «База данных» падала."""
    from app.keyboards import admin_db_keyboard

    kb = admin_db_keyboard(["users", "videos"])
    assert kb.inline_keyboard


def test_nickname_regex_does_not_admit_backslash():
    from app.services import validate_nickname_format

    assert validate_nickname_format("cool\\nick")[0] is False
    assert validate_nickname_format("cool_nick")[0] is True


# ───────────────────────── B-05: атомарное списание ─────────────────────────

@pytest.mark.asyncio
async def test_change_balance_atomic_rejects_overdraft_with_stale_object():
    from app.services import InsufficientBalanceError, change_balance_atomic

    engine, Session = await _mem_engine()
    async with Session() as session:
        user = User(telegram_id=510001, balance=Decimal("5000"), nickname_set=True, display_name="Racer")
        session.add(user)
        await session.commit()
        uid = user.id

        # Первое списание проходит, второе (по «устаревшему» балансу) — нет.
        await change_balance_atomic(session, uid, Decimal("-4000"), "test_debit")
        await session.commit()
        with pytest.raises(InsufficientBalanceError):
            await change_balance_atomic(session, uid, Decimal("-4000"), "test_debit")
        await session.rollback()

        balance = (await session.execute(select(User.balance).where(User.id == uid))).scalar_one()
        assert balance == Decimal("1000")

        # Штраф с allow_negative может увести в минус осознанно
        await change_balance_atomic(session, uid, Decimal("-1500"), "penalty", allow_negative=True)
        await session.commit()
        balance = (await session.execute(select(User.balance).where(User.id == uid))).scalar_one()
        assert balance == Decimal("-500")
    await engine.dispose()


# ───────────────────────── B-12: множитель монет ─────────────────────────

@pytest.mark.asyncio
async def test_coin_multiplier_takes_best_of_vip_and_perk():
    from app.config import VIP_BONUS_MULTIPLIER
    from app.services import get_coin_multiplier

    engine, Session = await _mem_engine()
    async with Session() as session:
        user = User(telegram_id=510002, balance=Decimal("0"), vip_until=utc_now() + timedelta(days=5))
        session.add(user)
        await session.commit()
        session.add(UserPerk(user_id=user.id, perk_type="coin_multiplier", is_active=True,
                             active_until=utc_now() + timedelta(days=5)))
        await session.commit()
        assert await get_coin_multiplier(session, user.id) == max(float(VIP_BONUS_MULTIPLIER), 1.5)
    await engine.dispose()


# ───────────────────────── B-16: бесплатный VIP-промокод раз в месяц ─────────────────────────

def test_vip_free_promo_counter_resets_on_new_month():
    from app.services import _promo_month_key, vip_free_promos_used_this_month

    stale = SimpleNamespace(promo_month=_promo_month_key() - 1, promo_created_this_month=1)
    fresh = SimpleNamespace(promo_month=_promo_month_key(), promo_created_this_month=1)
    assert vip_free_promos_used_this_month(stale) == 0
    assert vip_free_promos_used_this_month(fresh) == 1


# ───────────────────────── B-17: награда за загрузку один раз ─────────────────────────

@pytest.mark.asyncio
async def test_upload_reward_is_not_paid_twice_after_reject_restore_approve():
    from app.services import approve_video, reject_video, restore_rejected_video

    engine, Session = await _mem_engine()
    async with Session() as session:
        author = User(telegram_id=510003, balance=Decimal("0"), nickname_set=True, display_name="Author")
        session.add(author)
        await session.commit()
        video = Video(uploader_user_id=author.id, content_type="video", telegram_file_id="f1",
                      telegram_file_unique_id="u1", status="pending")
        session.add(video)
        await session.commit()

        assert await approve_video(session, video.id) is not None
        assert await approve_video(session, video.id) is None  # повторное одобрение — no-op
        assert await reject_video(session, video.id, "oops") is not None
        assert await reject_video(session, video.id, "oops") is None  # уже отклонено
        assert await restore_rejected_video(session, video.id) is not None
        assert await approve_video(session, video.id) is not None

        rewards = (await session.execute(
            select(func.count(BalanceLog.id)).where(
                BalanceLog.source == "upload_approved", BalanceLog.source_id == video.id
            )
        )).scalar_one()
        assert rewards == 1
    await engine.dispose()


# ───────────────────────── B-21: XP за просмотр/игру ─────────────────────────

@pytest.mark.asyncio
async def test_grant_xp_updates_xp_and_level_atomically():
    from app.services import calc_level_xp_required, grant_xp

    engine, Session = await _mem_engine()
    async with Session() as session:
        user = User(telegram_id=510004, balance=Decimal("0"), xp=0, level=1)
        session.add(user)
        await session.commit()
        need = calc_level_xp_required(1)
        new_level, leveled = await grant_xp(session, user.id, need, apply_multiplier=False)
        await session.commit()
        assert (new_level, leveled) == (2, True)
        row = (await session.execute(select(User.xp, User.level).where(User.id == user.id))).one()
        assert row == (need, 2)
    await engine.dispose()


# ───────────────────────── B-22: поиск пользователей с «_» ─────────────────────────

@pytest.mark.asyncio
async def test_search_users_admin_keeps_underscore_literal():
    from app.services import search_users_admin

    engine, Session = await _mem_engine()
    async with Session() as session:
        session.add_all([
            User(telegram_id=510005, display_name="cool_user"),
            User(telegram_id=510006, display_name="cool user"),
        ])
        await session.commit()
        found = await search_users_admin(session, "cool_u")
        assert [u.display_name for u in found] == ["cool_user"]
    await engine.dispose()


# ───────────────────────── B-24: бонусы покупки без MultipleResultsFound ─────────────────────────

@pytest.mark.asyncio
async def test_purchase_bonus_context_survives_many_paid_payments_today():
    from app.services import purchase_bonus_context

    engine, Session = await _mem_engine()
    async with Session() as session:
        user = User(telegram_id=510007, balance=Decimal("0"))
        session.add(user)
        await session.commit()
        for i in range(3):
            session.add(Payment(user_id=user.id, payload=f"p_{i}", stars_amount=10,
                                coins_amount=Decimal("100"), status="paid"))
        await session.commit()
        _mult, first_today = await purchase_bonus_context(session, user.id)
        assert first_today is False
    await engine.dispose()


# ───────────────────────── B-30: ссылка на пост → @канал ─────────────────────────

def test_offer_chat_id_from_url_handles_post_links_and_invites():
    from app.services import offer_chat_id_from_url

    assert offer_chat_id_from_url("https://t.me/example_channel/123") == "@example_channel"
    assert offer_chat_id_from_url("@example_channel") == "@example_channel"
    assert offer_chat_id_from_url("https://t.me/+AbCdEf") is None


# ───────────────────────── B-09: проверка подписки — три состояния ─────────────────────────

@pytest.mark.asyncio
async def test_is_subscribed_returns_none_when_telegram_check_fails():
    from aiogram.exceptions import TelegramBadRequest
    import app.main as m

    bot = AsyncMock()
    bot.get_chat_member = AsyncMock(side_effect=TelegramBadRequest(method=SimpleNamespace(), message="chat not found"))
    assert await m._is_subscribed(bot, 1, "https://t.me/example_channel") is None

    bot.get_chat_member = AsyncMock(return_value=SimpleNamespace(status="left"))
    assert await m._is_subscribed(bot, 1, "https://t.me/example_channel") is False

    bot.get_chat_member = AsyncMock(return_value=SimpleNamespace(status="member"))
    assert await m._is_subscribed(bot, 1, "https://t.me/example_channel") is True


# ───────────────────────── B-11: эскроу-бюджет пользовательских офферов ─────────────────────────

@pytest.mark.asyncio
async def test_offer_budget_limits_participants_and_refunds_remainder():
    from app.services import (
        is_offer_available, offer_budget_remaining, refund_offer_budget,
        start_offer_participation,
    )

    engine, Session = await _mem_engine()
    async with Session() as session:
        creator = User(telegram_id=510010, balance=Decimal("0"), nickname_set=True, display_name="Creator")
        p1 = User(telegram_id=510011, balance=Decimal("0"), nickname_set=True, display_name="P1")
        p2 = User(telegram_id=510012, balance=Decimal("0"), nickname_set=True, display_name="P2")
        session.add_all([creator, p1, p2])
        await session.commit()
        offer = Offer(
            title="Budget", description="Budget", channel_url="https://t.me/example_channel",
            reward_preview=Decimal("10"), reward_final=Decimal("50"), duration_days=7,
            status="approved", is_active=True, approved_at=utc_now(),
            creator_user_id=creator.id, budget_total=Decimal("50"), budget_spent=Decimal("0"),
            max_participants=1,
        )
        session.add(offer)
        await session.commit()

        part1, new1 = await start_offer_participation(session, p1.id, offer.id)
        assert part1 is not None and new1 is True
        await session.refresh(offer)
        assert offer_budget_remaining(offer) == Decimal("40")

        # Второй участник не помещается в оплаченные места
        part2, _ = await start_offer_participation(session, p2.id, offer.id)
        assert part2 is None
        assert is_offer_available(offer) is False or offer_budget_remaining(offer) < Decimal("50")

        # Остаток возвращается автору ровно один раз
        refunded = await refund_offer_budget(session, offer, reason="test")
        await session.refresh(creator)
        assert refunded == Decimal("40")
        assert creator.balance == Decimal("40")
        assert await refund_offer_budget(session, offer, reason="test") == Decimal("0")
    await engine.dispose()


# ───────────────────────── B-07: лента Mini App только с initData ─────────────────────────

@pytest.mark.asyncio
async def test_videofeed_feed_requires_telegram_init_data():
    import app.main as m

    class DummyRequest:
        headers: dict = {}
        query: dict = {}

        def get(self, key, default=None):
            return default

        def __setitem__(self, key, value):
            pass

    resp = await m.api_videofeed_feed(DummyRequest())
    assert resp.status == 401


def test_video_stream_signature_roundtrip():
    import app.main as m

    url = m._video_stream_url(42, 777)
    assert url.startswith("/api/video/42?")
    query = dict(part.split("=", 1) for part in url.split("?", 1)[1].split("&"))

    class DummyRequest:
        def __init__(self, q):
            self.query = q
            self.headers = {}

        def get(self, key, default=None):
            return default

        def __setitem__(self, key, value):
            pass

    assert m._video_stream_authorized(DummyRequest(query), 42) is True
    assert m._video_stream_authorized(DummyRequest(query), 43) is False  # подпись на другое видео
    bad = dict(query, sig="0" * 32)
    assert m._video_stream_authorized(DummyRequest(bad), 42) is False
    assert m._video_stream_authorized(DummyRequest({}), 42) is False


# ───────────────────────── B-14: повторные алерты по DA-исключениям ─────────────────────────

@pytest.mark.asyncio
async def test_donationalerts_exception_marks_only_first_record_as_new():
    from app.services import record_donationalerts_exception

    engine, Session = await _mem_engine()
    async with Session() as session:
        first = await record_donationalerts_exception(
            session, donation_id="dup-1", amount_rub=Decimal("10"), currency="RUB",
            message="hi", donor_name="x", reason="order_not_found",
        )
        assert getattr(first, "is_new") is True
    async with Session() as session:  # следующий цикл REST-сверки — новая сессия
        second = await record_donationalerts_exception(
            session, donation_id="dup-1", amount_rub=Decimal("10"), currency="RUB",
            message="hi", donor_name="x", reason="order_not_found",
        )
        assert getattr(second, "is_new") is False
    await engine.dispose()


# ───────────────────────── B-08: имя из Telegram экранируется один раз ─────────────────────────

@pytest.mark.asyncio
async def test_styled_display_name_escapes_html_from_telegram_name():
    from app.services import get_styled_display_name

    engine, Session = await _mem_engine()
    async with Session() as session:
        user = User(telegram_id=510020, first_name="<3 Аня & Co", balance=Decimal("0"))
        session.add(user)
        await session.commit()
        styled = await get_styled_display_name(session, user)
        assert "<3" not in styled
        assert "&lt;3" in styled and "&amp;" in styled
    await engine.dispose()


# ───────────────────────── B-03 / B-10 / B-19: розыгрыш Секслото от начала до рассылки ─────────────────────────

@pytest.mark.asyncio
async def test_lottery_pool_counts_only_paid_tickets():
    from app.services import buy_lottery_tickets, ensure_current_lottery_round

    engine, Session = await _mem_engine()
    async with Session() as session:
        player = User(telegram_id=510030, balance=Decimal("1000"), nickname_set=True, display_name="Lotto")
        admin = User(telegram_id=510031, balance=Decimal("0"), nickname_set=True, display_name="Adm")
        session.add_all([player, admin])
        await session.commit()

        round_obj = await ensure_current_lottery_round(session)
        price = Decimal(round_obj.ticket_price)
        tickets, total_cost, error = await buy_lottery_tickets(session, player, 3)
        assert error is None and len(tickets) == 3 and total_cost == price * 3
        await session.refresh(round_obj)
        assert Decimal(round_obj.prize_pool) == price * 3

        # Админский бесплатный билет пул не раздувает (раньше — добавлял цену билета)
        free_tickets, _cost, err = await buy_lottery_tickets(session, admin, 1, is_admin_free=True)
        assert err is None and len(free_tickets) == 1
        await session.refresh(round_obj)
        assert Decimal(round_obj.prize_pool) == price * 3
    await engine.dispose()


@pytest.mark.asyncio
async def test_lottery_stale_round_is_recovered_settled_and_results_are_sent():
    """Раунд, оставшийся open после окна розыгрыша (бот был офлайн), дорозыгрывается;
    итоги рассылаются участникам (раньше notify_lottery_results падал на затенённой t)."""
    import app.main as m
    from app.models import LotteryRound, LotteryTicket

    engine, Session = await _mem_engine()
    async with Session() as session:
        p1 = User(telegram_id=510032, balance=Decimal("1000"), nickname_set=True, display_name="Lotto1")
        p2 = User(telegram_id=510033, balance=Decimal("1000"), nickname_set=True, display_name="Lotto2")
        session.add_all([p1, p2])
        await session.commit()
        now = utc_now()
        stale = LotteryRound(
            week_key="stale-test", status="open", ticket_price=Decimal("30"),
            numbers_pool=36, numbers_per_ticket=6, prize_pool=Decimal("90"),
            starts_at=now - timedelta(days=1), draw_starts_at=now - timedelta(hours=2),
            draw_ends_at=now - timedelta(hours=1),
        )
        session.add(stale)
        await session.commit()
        session.add_all([
            LotteryTicket(round_id=stale.id, user_id=p1.id, numbers="1,2,3,4,5,6"),
            LotteryTicket(round_id=stale.id, user_id=p1.id, numbers="7,8,9,10,11,12"),
            LotteryTicket(round_id=stale.id, user_id=p2.id, numbers="13,14,15,16,17,18"),
        ])
        await session.commit()

        bot = AsyncMock()
        stop_event = asyncio.Event()
        with patch.object(m, "notify_lottery_results", wraps=m.notify_lottery_results) as notify:
            await m._recover_stale_lottery_rounds(bot, session, stop_event, current_round_id=-1)
            notify.assert_awaited_once()

        await session.refresh(stale)
        assert stale.status == "completed"
        assert len(m._deserialize_numbers(stale.drawn_numbers)) == 6
        # Каждый участник получил итоговое сообщение
        recipients = {call.args[0] for call in bot.send_message.await_args_list}
        assert {510032, 510033} <= recipients
        matched = (await session.execute(
            select(LotteryTicket.matched_count).where(LotteryTicket.round_id == stale.id)
        )).scalars().all()
        assert len(matched) == 3 and all(mc is not None for mc in matched)
    await engine.dispose()
