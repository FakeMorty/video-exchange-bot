from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, User


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
