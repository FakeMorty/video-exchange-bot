from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, BalanceLog, LotteryRound, LotteryTicket, Payment, User, UserActionLog, Video, VideoView, utc_now


@pytest.mark.asyncio
async def test_build_user_report_pdf_smoke(monkeypatch):
    import app.reports as reports

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(reports, "async_session", Session)

    async with Session() as session:
        user = User(telegram_id=1111001, balance=Decimal("123.45"), nickname_set=True, display_name="PdfUser")
        session.add(user)
        await session.commit()

    pdf_path, filename = await reports.build_user_report_pdf(1111001)
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
    assert filename.endswith(".pdf")
    pdf_path.unlink(missing_ok=True)
    await engine.dispose()


@pytest.mark.asyncio
async def test_build_bot_report_pdf_smoke(monkeypatch):
    import app.reports as reports

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(reports, "async_session", Session)

    async with Session() as session:
        user = User(telegram_id=1111002, balance=Decimal("50.00"), nickname_set=True, display_name="BotUser")
        session.add(user)
        await session.commit()

    pdf_path, filename = await reports.build_bot_report_pdf()
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
    assert filename.endswith(".pdf")
    pdf_path.unlink(missing_ok=True)
    await engine.dispose()


@pytest.mark.asyncio
async def test_build_all_users_report_pdf_smoke(monkeypatch):
    import app.reports as reports

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(reports, "async_session", Session)

    async with Session() as session:
        session.add_all([
            User(telegram_id=1111003, balance=Decimal("10.00"), nickname_set=True, display_name="UserA"),
            User(telegram_id=1111004, balance=Decimal("20.00"), nickname_set=True, display_name="UserB"),
        ])
        await session.commit()

    pdf_path, filename = await reports.build_all_users_report_pdf()
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
    assert filename.endswith(".pdf")
    pdf_path.unlink(missing_ok=True)
    await engine.dispose()


@pytest.mark.asyncio
async def test_collect_user_report_data_adds_profile_and_payment_metrics(monkeypatch):
    import app.reports as reports

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(reports, "async_session", Session)

    async with Session() as session:
        user = User(telegram_id=2222001, balance=Decimal("200.00"), nickname_set=True, display_name="MetricsUser")
        session.add(user)
        await session.flush()
        session.add(Payment(user_id=user.id, payload="pay_user_report", stars_amount=30, coins_amount=Decimal("300.00"), status="paid"))
        session.add(BalanceLog(user_id=user.id, amount=Decimal("50.00"), balance_before=Decimal("150.00"), balance_after=Decimal("200.00"), source="purchase"))
        session.add(UserActionLog(user_id=user.id, action="open_menu", details="test"))
        await session.commit()

    data = await reports.collect_user_report_data(2222001)
    assert data["payments"]["count"] == 1
    assert data["payments"]["stars_total"] == 30
    assert data["payments"]["types"]
    assert data["profile"]["active_days_30"] >= 1
    assert data["content"]["efficiency"]["uploads_total"] >= 0
    assert data["comparison"]["rows"]
    assert data["comparison"]["population"] >= 1
    assert data["insights"]["purchase_comment"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_collect_bot_report_data_adds_conversion_metrics(monkeypatch):
    import app.reports as reports

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(reports, "async_session", Session)

    now = utc_now()
    async with Session() as session:
        user1 = User(
            telegram_id=3333001,
            balance=Decimal("100.00"),
            nickname_set=True,
            display_name="Buyer",
            agreed_to_rules=True,
            created_at=now - timedelta(days=10),
        )
        session.add(user1)
        await session.flush()
        user2 = User(
            telegram_id=3333002,
            balance=Decimal("0.00"),
            nickname_set=True,
            display_name="Referral",
            agreed_to_rules=True,
            referred_by_user_id=user1.id,
            created_at=now - timedelta(days=10),
        )
        session.add(user2)
        await session.flush()

        video = Video(
            uploader_user_id=user1.id,
            telegram_file_id="file1",
            telegram_file_unique_id="uniq1",
            status="approved",
            created_at=now - timedelta(days=9),
        )
        session.add(video)
        await session.flush()
        session.add(VideoView(user_id=user1.id, video_id=video.id, created_at=now - timedelta(days=9), watched_at=now - timedelta(days=9)))

        lottery_round = LotteryRound(
            week_key="lottery_20260701",
            starts_at=now - timedelta(days=9),
            draw_starts_at=now - timedelta(days=9),
            draw_ends_at=now - timedelta(days=9) + timedelta(minutes=2),
        )
        session.add(lottery_round)
        await session.flush()
        session.add(LotteryTicket(round_id=lottery_round.id, user_id=user1.id, numbers="1,2,3,4,5,6", created_at=now - timedelta(days=8)))

        session.add(Payment(user_id=user1.id, payload="pay_bot_report", stars_amount=40, coins_amount=Decimal("400.00"), status="paid", created_at=now - timedelta(days=9)))
        session.add(UserActionLog(user_id=user1.id, action="returned_d1", details="test", created_at=now - timedelta(days=9)))
        session.add(UserActionLog(user_id=user1.id, action="returned_d7", details="test", created_at=now - timedelta(days=3)))
        await session.commit()

    data = await reports.collect_bot_report_data()
    assert data["summary"]["payer_count"] == 1
    assert data["summary"]["payment_conversion_pct"] == pytest.approx(50.0)
    assert data["economy"]["payment_type_counts"]
    assert data["payments_analytics"]["rows"]
    assert data["retention"]["referred_total"] == 1
    assert len(data["retention"]["active_users_daily_30"]) == 30
    assert data["segments"]["rows"]
    assert data["leaders"]["payments"]
    assert data["churn"]["rows"]
    assert data["activity_heatmap"]["hours"][0] == "00"
    assert len(data["activity_heatmap"]["matrix"]) == 7
    assert data["funnel"]["rows"][0]["label"] == "Регистрация"
    assert data["funnel"]["rows"][3]["count"] == 1
    assert data["cohorts"]["d1"]["eligible"] >= 2
    assert data["cohorts"]["d1"]["retained"] >= 1
    await engine.dispose()
