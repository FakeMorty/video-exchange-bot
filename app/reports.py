from __future__ import annotations

import asyncio
import math
import os
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import and_, func, or_, select

from app.db import async_session
from app.models import (
    BalanceLog,
    Comment,
    ContentReaction,
    KatyaChat,
    KatyaMessage,
    LootboxOpen,
    LotteryRound,
    LotteryTicket,
    Payment,
    Promocode,
    PromocodeActivation,
    TrustedUploader,
    User,
    UserActionLog,
    Video,
    VideoRating,
    VideoView,
    utc_now,
)
from app.services import get_styled_display_name

PERIODS: list[tuple[str, int | None]] = [
    ("7 дней", 7),
    ("30 дней", 30),
    ("365 дней", 365),
    ("Всё время", None),
]

INCOME_SOURCE_LABELS = {
    "registration": "Стартовый баланс",
    "upload_approved": "Одобрение загрузок",
    "offer_preview": "Офферы: старт",
    "offer_complete": "Офферы: подтверждение",
    "referral_reward": "Рефералы",
    "purchase": "Покупки",
    "purchase_admin_free": "ADMIN FREE",
    "lootbox_reward": "Лутбоксы",
    "lootbox_reward_admin_free": "Лутбоксы (ADMIN FREE)",
    "daily_bonus": "Бонусы",
    "freebie_reward": "Еженедельная халява",
    "welcome_lootbox": "Стартовый лутбокс",
    "promocode_activation": "Промокоды",
    "lottery_win_4": "Секслото: 4 совпадения",
    "lottery_win_5": "Секслото: 5 совпадений",
    "lottery_win_6": "Секслото: 6 совпадений",
    "lottery_bet_win": "Секслото: ставки",
}

EXPENSE_SOURCE_LABELS = {
    "watch": "Просмотры",
    "donation_purchase": "Магазин",
    "nickname_change": "Смена ника",
    "katya_chat": "ИИ-общение",
    "lottery_ticket_purchase": "Секслото: билеты",
    "lottery_bet": "Секслото: ставки",
    "game_session_paid": "Игровая сессия",
    "promocode_creator_cost": "Создание промокода",
    "offer_unsubscribe_penalty": "Штрафы офферов",
    "user_offer_placement": "Размещение оффера",
    "lootbox_buy": "Лутбоксы",
}

LOTTERY_BALANCE_SOURCES = {
    "lottery_ticket_purchase",
    "lottery_ticket_admin_free",
    "lottery_bet",
    "lottery_bet_win",
    "lottery_win_4",
    "lottery_win_5",
    "lottery_win_6",
}


def _fmt_dec(value: Decimal | float | int | None) -> str:
    if value is None:
        return "0"
    dec = Decimal(str(value))
    if dec == dec.to_integral_value():
        return f"{dec:,.0f}".replace(",", " ")
    return f"{dec:,.2f}".replace(",", " ")


def _period_start(days: int | None):
    if days is None:
        return None
    return utc_now() - timedelta(days=days)


def _daterange(days: int) -> list[str]:
    today = utc_now().date()
    return [str(today - timedelta(days=days - 1 - idx)) for idx in range(days)]


def _group_daily(rows, key_fn, value_fn=float) -> dict[str, float]:
    result: dict[str, float] = defaultdict(float)
    for row in rows:
        result[key_fn(row)] += float(value_fn(row))
    return dict(result)


def _prepare_line_series(day_map: dict[str, float], days: int) -> tuple[list[str], list[float]]:
    labels = _daterange(days)
    values = [float(day_map.get(day, 0)) for day in labels]
    return labels, values


def _top_items(items: dict[str, float], mapping: dict[str, str], limit: int = 6) -> dict[str, float]:
    ranked = sorted(items.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return {mapping.get(k, k): v for k, v in ranked if v > 0}


async def _sum_balance(session, user_id: int | None, *, positive: bool | None = None, start=None, sources: set[str] | None = None) -> Decimal:
    stmt = select(func.sum(BalanceLog.amount))
    conds = []
    if user_id is not None:
        conds.append(BalanceLog.user_id == user_id)
    if positive is True:
        conds.append(BalanceLog.amount > 0)
    elif positive is False:
        conds.append(BalanceLog.amount < 0)
    if start is not None:
        conds.append(BalanceLog.created_at >= start)
    if sources:
        conds.append(BalanceLog.source.in_(sources))
    if conds:
        stmt = stmt.where(and_(*conds))
    value = (await session.execute(stmt)).scalar_one() or Decimal("0")
    return Decimal(str(value))


async def _count_query(session, stmt) -> int:
    return int((await session.execute(stmt)).scalar_one() or 0)


def _register_fonts() -> str:
    try:
        font_path = font_manager.findfont("DejaVu Sans")
        pdfmetrics.registerFont(TTFont("DejaVuSans", font_path))
        return "DejaVuSans"
    except Exception:
        return "Helvetica"


def _build_styles(font_name: str):
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H1Custom", parent=styles["Heading1"], fontName=font_name, fontSize=18, leading=22, textColor=colors.HexColor("#2A2A2A")))
    styles.add(ParagraphStyle(name="H2Custom", parent=styles["Heading2"], fontName=font_name, fontSize=13, leading=16, textColor=colors.HexColor("#3A3A3A"), spaceBefore=10, spaceAfter=6))
    styles.add(ParagraphStyle(name="BodyCustom", parent=styles["BodyText"], fontName=font_name, fontSize=9.5, leading=13))
    styles.add(ParagraphStyle(name="SmallCustom", parent=styles["BodyText"], fontName=font_name, fontSize=8, leading=11, textColor=colors.HexColor("#666666")))
    return styles


def _table(data, font_name: str, col_widths=None):
    table = Table(data, colWidths=col_widths, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8ECF4")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _save_chart(fig, path: Path):
    fig.tight_layout()
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return str(path)


def _chart_line(title: str, labels: list[str], values: list[float], path: Path, color="#5B21B6"):
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.plot(range(len(values)), values, color=color, linewidth=2)
    ax.fill_between(range(len(values)), values, color=color, alpha=0.15)
    step = max(1, len(labels) // 6)
    ax.set_xticks(range(0, len(labels), step))
    ax.set_xticklabels([labels[i][5:] for i in range(0, len(labels), step)], rotation=0)
    ax.set_title(title)
    ax.grid(alpha=0.2)
    return _save_chart(fig, path)


def _chart_dual_bar(title: str, labels: list[str], left_values: list[float], right_values: list[float], path: Path, left_label="Доход", right_label="Расход"):
    fig, ax = plt.subplots(figsize=(8, 3.2))
    x = list(range(len(labels)))
    ax.bar([v - 0.2 for v in x], left_values, width=0.4, label=left_label, color="#16A34A")
    ax.bar([v + 0.2 for v in x], right_values, width=0.4, label=right_label, color="#DC2626")
    step = max(1, len(labels) // 6)
    ax.set_xticks(range(0, len(labels), step))
    ax.set_xticklabels([labels[i][5:] for i in range(0, len(labels), step)])
    ax.set_title(title)
    ax.legend()
    ax.grid(axis="y", alpha=0.2)
    return _save_chart(fig, path)


def _chart_horizontal_bar(title: str, mapping: dict[str, float], path: Path, color="#2563EB"):
    labels = list(mapping.keys())
    values = list(mapping.values())
    fig, ax = plt.subplots(figsize=(8, max(2.8, len(labels) * 0.45)))
    ax.barh(labels, values, color=color)
    ax.set_title(title)
    ax.grid(axis="x", alpha=0.2)
    return _save_chart(fig, path)


def _chart_stacked(title: str, labels: list[str], series: dict[str, list[float]], path: Path):
    fig, ax = plt.subplots(figsize=(8, 3.2))
    bottom = [0.0] * len(labels)
    palette = ["#0EA5E9", "#8B5CF6", "#F59E0B", "#10B981", "#EF4444", "#6366F1"]
    for idx, (name, values) in enumerate(series.items()):
        ax.bar(range(len(labels)), values, bottom=bottom, label=name, color=palette[idx % len(palette)])
        bottom = [bottom[i] + values[i] for i in range(len(values))]
    step = max(1, len(labels) // 6)
    ax.set_xticks(range(0, len(labels), step))
    ax.set_xticklabels([labels[i][5:] for i in range(0, len(labels), step)])
    ax.set_title(title)
    ax.legend(fontsize=7, ncol=2)
    ax.grid(axis="y", alpha=0.2)
    return _save_chart(fig, path)


def _chart_distribution(title: str, mapping: dict[str, float], path: Path):
    fig, ax = plt.subplots(figsize=(7, 3))
    labels = list(mapping.keys())
    values = list(mapping.values())
    ax.bar(labels, values, color="#7C3AED")
    ax.set_title(title)
    ax.grid(axis="y", alpha=0.2)
    return _save_chart(fig, path)


def _bullet(text: str, styles):
    return Paragraph(f"• {text}", styles["BodyCustom"])


async def collect_user_report_data(telegram_user_id: int) -> dict:
    async with async_session() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_user_id))
        if not user:
            raise ValueError("Пользователь не найден")

        now = utc_now()
        period_starts = {label: _period_start(days) for label, days in PERIODS}

        # Summary profile
        display_name = await get_styled_display_name(session, user)
        is_vip = bool(user.vip_until and user.vip_until > now)

        # Balance logs
        all_logs = (await session.execute(select(BalanceLog).where(BalanceLog.user_id == user.id).order_by(BalanceLog.created_at.asc()))).scalars().all()
        logs_30 = [log for log in all_logs if log.created_at >= (now - timedelta(days=30))]

        economy_rows = []
        for label, days in PERIODS:
            start = period_starts[label]
            relevant = [log for log in all_logs if start is None or log.created_at >= start]
            earned = sum((log.amount for log in relevant if log.amount > 0), Decimal("0"))
            spent = sum((-log.amount for log in relevant if log.amount < 0), Decimal("0"))
            net = earned - spent
            day_span = days or max(1, (now.date() - user.created_at.date()).days + 1)
            avg_daily = (net / Decimal(day_span)) if day_span else Decimal("0")
            economy_rows.append({
                "period": label,
                "earned": earned,
                "spent": spent,
                "net": net,
                "avg_daily": avg_daily,
            })

        last_30_labels = _daterange(30)
        daily_net = defaultdict(Decimal)
        daily_income = defaultdict(Decimal)
        daily_expense = defaultdict(Decimal)
        for log in logs_30:
            day = str(log.created_at.date())
            daily_net[day] += log.amount
            if log.amount > 0:
                daily_income[day] += log.amount
            else:
                daily_expense[day] += -log.amount
        start_balance = user.balance - sum((log.amount for log in logs_30), Decimal("0"))
        running = start_balance
        balance_series = []
        for day in last_30_labels:
            running += daily_net.get(day, Decimal("0"))
            balance_series.append(float(running))
        income_series = [float(daily_income.get(day, Decimal("0"))) for day in last_30_labels]
        expense_series = [float(daily_expense.get(day, Decimal("0"))) for day in last_30_labels]

        source_income = defaultdict(float)
        source_expense = defaultdict(float)
        for log in all_logs:
            if log.amount > 0:
                source_income[log.source] += float(log.amount)
            elif log.amount < 0:
                source_expense[log.source] += float(-log.amount)

        # Content & activity
        uploads = (await session.execute(select(Video).where(Video.uploader_user_id == user.id))).scalars().all()
        ratings_avg = (await session.execute(
            select(func.avg(VideoRating.rating)).join(Video, Video.id == VideoRating.video_id).where(Video.uploader_user_id == user.id)
        )).scalar_one()
        own_content_views = await _count_query(
            session,
            select(func.count(VideoView.id)).join(Video, Video.id == VideoView.video_id).where(Video.uploader_user_id == user.id, VideoView.user_id != user.id),
        )
        own_views = await _count_query(session, select(func.count(VideoView.id)).where(VideoView.user_id == user.id))
        comments_count = await _count_query(session, select(func.count(Comment.id)).where(Comment.user_id == user.id))
        reactions_count = await _count_query(session, select(func.count(ContentReaction.id)).where(ContentReaction.user_id == user.id))
        uploads_30 = [video for video in uploads if video.created_at >= (now - timedelta(days=30))]
        upload_daily_video = defaultdict(float)
        upload_daily_photo = defaultdict(float)
        status_counts = Counter()
        for video in uploads:
            status_counts[video.status] += 1
        for video in uploads_30:
            day = str(video.created_at.date())
            if video.content_type == "photo":
                upload_daily_photo[day] += 1
            else:
                upload_daily_video[day] += 1
        upload_series = {
            "Видео": [upload_daily_video.get(day, 0.0) for day in last_30_labels],
            "Фото": [upload_daily_photo.get(day, 0.0) for day in last_30_labels],
        }
        actions_30 = (await session.execute(
            select(UserActionLog.action, func.count(UserActionLog.id))
            .where(UserActionLog.user_id == user.id, UserActionLog.created_at >= now - timedelta(days=30))
            .group_by(UserActionLog.action)
        )).all()
        action_counts = {action: float(count) for action, count in actions_30}

        # Lottery
        tickets = (await session.execute(select(LotteryTicket).where(LotteryTicket.user_id == user.id).order_by(LotteryTicket.created_at.asc()))).scalars().all()
        lottery_logs = [log for log in all_logs if log.source in LOTTERY_BALANCE_SOURCES]
        lottery_rows = []
        for label, days in PERIODS:
            start = period_starts[label]
            rel_tickets = [t for t in tickets if start is None or t.created_at >= start]
            rel_logs = [log for log in lottery_logs if start is None or log.created_at >= start]
            spent = sum((-log.amount for log in rel_logs if log.source == "lottery_ticket_purchase" and log.amount < 0), Decimal("0"))
            won = sum((log.amount for log in rel_logs if log.source.startswith("lottery_win_") or log.source == "lottery_bet_win"), Decimal("0"))
            lottery_rows.append({
                "period": label,
                "tickets": len(rel_tickets),
                "spent": spent,
                "won": won,
                "net": won - spent,
            })
        best_ticket = None
        if tickets:
            best_ticket = max(tickets, key=lambda t: (t.matched_count, t.created_at))
        match_distribution = Counter(str(t.matched_count) for t in tickets)
        ticket_daily = defaultdict(float)
        lottery_net_daily = defaultdict(Decimal)
        for ticket in tickets:
            if ticket.created_at >= now - timedelta(days=30):
                ticket_daily[str(ticket.created_at.date())] += 1
        for log in lottery_logs:
            if log.created_at >= now - timedelta(days=30):
                lottery_net_daily[str(log.created_at.date())] += log.amount
        ticket_series = [ticket_daily.get(day, 0.0) for day in last_30_labels]
        lottery_net_series = [float(lottery_net_daily.get(day, Decimal("0"))) for day in last_30_labels]

        # Referrals
        referrals = (await session.execute(select(User).where(User.referred_by_user_id == user.id).order_by(User.created_at.asc()))).scalars().all()
        active_referrals = 0
        for ref in referrals:
            video_views = await _count_query(
                session,
                select(func.count(VideoView.id)).join(Video, Video.id == VideoView.video_id).where(VideoView.user_id == ref.id, Video.content_type == "video"),
            )
            if video_views >= 5:
                active_referrals += 1
        referral_daily = defaultdict(float)
        for ref in referrals:
            if ref.created_at >= now - timedelta(days=30):
                referral_daily[str(ref.created_at.date())] += 1
        referral_income_logs = [log for log in all_logs if log.source == "referral_reward"]
        referral_income_daily = defaultdict(Decimal)
        for log in referral_income_logs:
            if log.created_at >= now - timedelta(days=30):
                referral_income_daily[str(log.created_at.date())] += log.amount
        referral_rows = []
        for label, days in PERIODS:
            start = period_starts[label]
            refs = [ref for ref in referrals if start is None or ref.created_at >= start]
            income = sum((log.amount for log in referral_income_logs if start is None or log.created_at >= start), Decimal("0"))
            referral_rows.append({"period": label, "count": len(refs), "income": income})

        # AI
        chats = (await session.execute(select(KatyaChat).where(KatyaChat.user_id == user.id))).scalars().all()
        ai_messages = (await session.execute(
            select(KatyaMessage, KatyaChat.character)
            .join(KatyaChat, KatyaChat.id == KatyaMessage.chat_id)
            .where(KatyaChat.user_id == user.id)
            .order_by(KatyaMessage.created_at.asc())
        )).all()
        ai_logs = [log for log in all_logs if log.source == "katya_chat"]
        ai_rows = []
        for label, days in PERIODS:
            start = period_starts[label]
            msgs = [m for m, _c in ai_messages if start is None or m.created_at >= start]
            spent = sum((-log.amount for log in ai_logs if (start is None or log.created_at >= start) and log.amount < 0), Decimal("0"))
            ai_rows.append({"period": label, "messages": len(msgs), "spent": spent})
        ai_daily = defaultdict(float)
        ai_character_counts = Counter()
        for message_obj, character in ai_messages:
            ai_character_counts[character or "katya"] += 1
            if message_obj.created_at >= now - timedelta(days=30):
                ai_daily[str(message_obj.created_at.date())] += 1

        # Insights
        dominant_map = {
            "контент-мейкер": len(uploads),
            "зритель": own_views,
            "игрок Секслото": len(tickets),
            "любитель ИИ-общения": len(ai_messages),
        }
        dominant_type = max(dominant_map, key=dominant_map.get) if dominant_map else "пользователь"
        top_income = max(source_income.items(), key=lambda kv: kv[1])[0] if source_income else None
        top_expense = max(source_expense.items(), key=lambda kv: kv[1])[0] if source_expense else None
        lottery_all_time = next((row for row in lottery_rows if row["period"] == "Всё время"), None)
        if lottery_all_time:
            lottery_comment = "Секслото приносит плюс" if lottery_all_time["net"] > 0 else "Секслото пока убыточно"
        else:
            lottery_comment = "Секслото пока не использовалось"

    return {
        "user": user,
        "display_name": display_name,
        "is_vip": is_vip,
        "economy_rows": economy_rows,
        "balance_labels_30": last_30_labels,
        "balance_series_30": balance_series,
        "income_series_30": income_series,
        "expense_series_30": expense_series,
        "source_income": _top_items(source_income, INCOME_SOURCE_LABELS),
        "source_expense": _top_items(source_expense, EXPENSE_SOURCE_LABELS),
        "content": {
            "videos": sum(1 for v in uploads if v.content_type == "video"),
            "photos": sum(1 for v in uploads if v.content_type == "photo"),
            "approved": status_counts.get("approved", 0),
            "rejected": status_counts.get("rejected", 0),
            "pending": status_counts.get("pending", 0),
            "avg_rating": round(float(ratings_avg or 0), 2),
            "own_content_views": own_content_views,
            "own_views": own_views,
            "comments": comments_count,
            "reactions": reactions_count,
        },
        "upload_series": upload_series,
        "status_counts": {k: float(v) for k, v in status_counts.items()},
        "action_counts": _top_items(action_counts, {}),
        "lottery_rows": lottery_rows,
        "best_ticket": best_ticket,
        "match_distribution": {str(i): float(match_distribution.get(str(i), 0)) for i in range(7)},
        "ticket_series_30": ticket_series,
        "lottery_net_series_30": lottery_net_series,
        "referrals": {
            "total": len(referrals),
            "active": active_referrals,
            "earned_total": user.referral_earnings,
            "rows": referral_rows,
        },
        "referral_labels_30": last_30_labels,
        "referral_series_30": [referral_daily.get(day, 0.0) for day in last_30_labels],
        "referral_income_series_30": [float(referral_income_daily.get(day, Decimal("0"))) for day in last_30_labels],
        "ai": {
            "chat_count": len(chats),
            "rows": ai_rows,
            "character_counts": {k: float(v) for k, v in ai_character_counts.items()},
            "daily_series_30": [ai_daily.get(day, 0.0) for day in last_30_labels],
        },
        "insights": {
            "dominant": dominant_type,
            "top_income": INCOME_SOURCE_LABELS.get(top_income, top_income) if top_income else "—",
            "top_expense": EXPENSE_SOURCE_LABELS.get(top_expense, top_expense) if top_expense else "—",
            "lottery_comment": lottery_comment,
        },
    }


async def collect_bot_report_data() -> dict:
    async with async_session() as session:
        now = utc_now()
        period_starts = {label: _period_start(days) for label, days in PERIODS}

        total_users = await _count_query(session, select(func.count(User.id)))
        active_users = await _count_query(session, select(func.count(User.id)).where(User.status == "active"))
        vip_users = await _count_query(session, select(func.count(User.id)).where(User.vip_until.is_not(None), User.vip_until > now))
        trusted_uploaders = await _count_query(session, select(func.count(TrustedUploader.id)))
        total_balance = Decimal(str((await session.execute(select(func.sum(User.balance)))).scalar_one() or 0))
        avg_balance = Decimal(str((await session.execute(select(func.avg(User.balance)))).scalar_one() or 0))
        purchases_paid = Decimal(str((await session.execute(select(func.sum(Payment.stars_amount)).where(Payment.status == "paid"))).scalar_one() or 0))

        new_users_rows = []
        for label, days in PERIODS:
            start = period_starts[label]
            stmt = select(func.count(User.id))
            if start is not None:
                stmt = stmt.where(User.created_at >= start)
            new_users_rows.append({"period": label, "count": await _count_query(session, stmt)})

        dau = await _count_query(session, select(func.count(func.distinct(UserActionLog.user_id))).where(UserActionLog.created_at >= now - timedelta(days=1)))
        wau = await _count_query(session, select(func.count(func.distinct(UserActionLog.user_id))).where(UserActionLog.created_at >= now - timedelta(days=7)))
        mau = await _count_query(session, select(func.count(func.distinct(UserActionLog.user_id))).where(UserActionLog.created_at >= now - timedelta(days=30)))

        # Growth series
        reg_rows = (await session.execute(
            select(func.date(User.created_at), func.count(User.id))
            .where(User.created_at >= now - timedelta(days=30))
            .group_by(func.date(User.created_at))
            .order_by(func.date(User.created_at))
        )).all()
        labels_30 = _daterange(30)
        reg_map = {str(day): float(count) for day, count in reg_rows}
        reg_series = [reg_map.get(day, 0.0) for day in labels_30]
        cumulative = []
        running = total_users - int(sum(reg_series))
        for value in reg_series:
            running += int(value)
            cumulative.append(float(running))

        # Content
        content_total = await _count_query(session, select(func.count(Video.id)))
        content_approved = await _count_query(session, select(func.count(Video.id)).where(Video.status == "approved"))
        content_rejected = await _count_query(session, select(func.count(Video.id)).where(Video.status == "rejected"))
        content_pending = await _count_query(session, select(func.count(Video.id)).where(Video.status == "pending"))
        auto_approved = await _count_query(session, select(func.count(UserActionLog.id)).where(UserActionLog.action == "video_auto_approved"))
        total_views = await _count_query(session, select(func.count(VideoView.id)))
        avg_rating = (await session.execute(select(func.avg(VideoRating.rating)))).scalar_one() or 0
        upload_rows = (await session.execute(
            select(func.date(Video.created_at), func.count(Video.id))
            .where(Video.created_at >= now - timedelta(days=30))
            .group_by(func.date(Video.created_at))
            .order_by(func.date(Video.created_at))
        )).all()
        upload_map = {str(day): float(count) for day, count in upload_rows}
        upload_series = [upload_map.get(day, 0.0) for day in labels_30]

        # Economy
        positive_total = Decimal(str((await session.execute(select(func.sum(BalanceLog.amount)).where(BalanceLog.amount > 0))).scalar_one() or 0))
        negative_total = Decimal(str((await session.execute(select(func.sum(BalanceLog.amount)).where(BalanceLog.amount < 0))).scalar_one() or 0))
        source_income_rows = (await session.execute(
            select(BalanceLog.source, func.sum(BalanceLog.amount)).where(BalanceLog.amount > 0).group_by(BalanceLog.source)
        )).all()
        source_expense_rows = (await session.execute(
            select(BalanceLog.source, func.sum(-BalanceLog.amount)).where(BalanceLog.amount < 0).group_by(BalanceLog.source)
        )).all()
        source_income = _top_items({src: float(val or 0) for src, val in source_income_rows}, INCOME_SOURCE_LABELS, limit=8)
        source_expense = _top_items({src: float(val or 0) for src, val in source_expense_rows}, EXPENSE_SOURCE_LABELS, limit=8)
        econ_rows = (await session.execute(
            select(func.date(BalanceLog.created_at), func.sum(BalanceLog.amount))
            .where(BalanceLog.created_at >= now - timedelta(days=30))
            .group_by(func.date(BalanceLog.created_at))
            .order_by(func.date(BalanceLog.created_at))
        )).all()
        econ_map = {str(day): float(val or 0) for day, val in econ_rows}
        econ_series = [econ_map.get(day, 0.0) for day in labels_30]

        # Lottery
        lottery_ticket_rows = []
        for label, days in PERIODS:
            start = period_starts[label]
            stmt = select(func.count(LotteryTicket.id))
            if start is not None:
                stmt = stmt.where(LotteryTicket.created_at >= start)
            lottery_ticket_rows.append({"period": label, "tickets": await _count_query(session, stmt)})
        avg_prize_pool = Decimal(str((await session.execute(select(func.avg(LotteryRound.prize_pool)))).scalar_one() or 0))
        lottery_ticket_subq = (
            select(
                LotteryRound.id.label("round_id"),
                func.count(LotteryTicket.id).label("ticket_count"),
            )
            .join(LotteryTicket, LotteryTicket.round_id == LotteryRound.id, isouter=True)
            .group_by(LotteryRound.id)
            .subquery()
        )
        avg_tickets_per_round = Decimal(str((await session.execute(
            select(func.avg(lottery_ticket_subq.c.ticket_count))
        )).scalar_one() or 0))
        win_counts = {
            "6 совпадений": await _count_query(session, select(func.count(BalanceLog.id)).where(BalanceLog.source == "lottery_win_6")),
            "5 совпадений": await _count_query(session, select(func.count(BalanceLog.id)).where(BalanceLog.source == "lottery_win_5")),
            "4 совпадения": await _count_query(session, select(func.count(BalanceLog.id)).where(BalanceLog.source == "lottery_win_4")),
        }
        lottery_spent = await _sum_balance(session, None, positive=False, sources={"lottery_ticket_purchase"})
        lottery_paid = await _sum_balance(session, None, positive=True, sources={"lottery_win_4", "lottery_win_5", "lottery_win_6", "lottery_bet_win"})
        rtp = float((lottery_paid / lottery_spent) * 100) if lottery_spent > 0 else 0.0
        ticket_daily_rows = (await session.execute(
            select(func.date(LotteryTicket.created_at), func.count(LotteryTicket.id))
            .where(LotteryTicket.created_at >= now - timedelta(days=30))
            .group_by(func.date(LotteryTicket.created_at))
            .order_by(func.date(LotteryTicket.created_at))
        )).all()
        ticket_daily_map = {str(day): float(count) for day, count in ticket_daily_rows}
        prize_pool_rows = (await session.execute(
            select(func.date(LotteryRound.draw_starts_at), func.avg(LotteryRound.prize_pool))
            .where(LotteryRound.draw_starts_at >= now - timedelta(days=30))
            .group_by(func.date(LotteryRound.draw_starts_at))
            .order_by(func.date(LotteryRound.draw_starts_at))
        )).all()
        prize_pool_map = {str(day): float(val or 0) for day, val in prize_pool_rows}
        match_dist_rows = (await session.execute(select(LotteryTicket.matched_count, func.count(LotteryTicket.id)).group_by(LotteryTicket.matched_count))).all()
        match_distribution = {str(int(m or 0)): float(c) for m, c in match_dist_rows}

        # Referrals / retention
        referred_rows = []
        for label, days in PERIODS:
            start = period_starts[label]
            stmt = select(func.count(User.id)).where(User.referred_by_user_id.is_not(None))
            if start is not None:
                stmt = stmt.where(User.created_at >= start)
            referred_rows.append({"period": label, "count": await _count_query(session, stmt)})
        retention_pushes = await _count_query(session, select(func.count(UserActionLog.id)).where(UserActionLog.action == "retention_push"))
        weekly_promo_activations = await _count_query(
            session,
            select(func.count(PromocodeActivation.id)).join(Promocode, Promocode.id == PromocodeActivation.promocode_id).where(Promocode.code.like("FREEBIE_%")),
        )
        retention_rows = (await session.execute(
            select(func.date(User.created_at), func.count(User.id)).where(User.referred_by_user_id.is_not(None), User.created_at >= now - timedelta(days=30)).group_by(func.date(User.created_at))
        )).all()
        retention_map = {str(day): float(count) for day, count in retention_rows}

    return {
        "summary": {
            "total_users": total_users,
            "active_users": active_users,
            "vip_users": vip_users,
            "trusted_uploaders": trusted_uploaders,
            "avg_balance": avg_balance,
            "total_balance": total_balance,
            "paid_stars_total": purchases_paid,
            "new_users": new_users_rows,
            "dau": dau,
            "wau": wau,
            "mau": mau,
        },
        "growth": {
            "labels_30": labels_30,
            "registrations_30": reg_series,
            "cumulative_30": cumulative,
        },
        "content": {
            "total": content_total,
            "approved": content_approved,
            "rejected": content_rejected,
            "pending": content_pending,
            "auto_approved": auto_approved,
            "views": total_views,
            "avg_rating": round(float(avg_rating or 0), 2),
            "uploads_30": upload_series,
        },
        "economy": {
            "positive_total": positive_total,
            "negative_total": abs(negative_total),
            "source_income": source_income,
            "source_expense": source_expense,
            "daily_net_30": econ_series,
            "labels_30": labels_30,
        },
        "lottery": {
            "rows": lottery_ticket_rows,
            "avg_prize_pool": avg_prize_pool,
            "avg_tickets_per_round": avg_tickets_per_round,
            "win_counts": win_counts,
            "rtp": rtp,
            "ticket_series_30": [ticket_daily_map.get(day, 0.0) for day in labels_30],
            "prize_pool_series_30": [prize_pool_map.get(day, 0.0) for day in labels_30],
            "match_distribution": {str(i): float(match_distribution.get(str(i), 0)) for i in range(7)},
            "labels_30": labels_30,
            "spent": lottery_spent,
            "paid": lottery_paid,
        },
        "retention": {
            "rows": referred_rows,
            "retention_pushes": retention_pushes,
            "weekly_promo_activations": weekly_promo_activations,
            "referred_daily_30": [retention_map.get(day, 0.0) for day in labels_30],
            "labels_30": labels_30,
        },
    }


def _user_summary_table(data: dict):
    user = data["user"]
    vip_text = "Да" if data["is_vip"] else "Нет"
    rows = [
        ["Параметр", "Значение"],
        ["Ник", data["display_name"]],
        ["Telegram ID", str(user.telegram_id)],
        ["Дата регистрации", user.created_at.strftime("%d.%m.%Y %H:%M")],
        ["Текущий баланс", _fmt_dec(user.balance)],
        ["VIP", vip_text],
        ["Уровень / XP", f"{user.level} / {user.xp}"],
    ]
    return rows


def _bot_summary_table(data: dict):
    summary = data["summary"]
    rows = [["Параметр", "Значение"]]
    rows.extend([
        ["Всего пользователей", str(summary["total_users"])],
        ["Активных пользователей", str(summary["active_users"])],
        ["VIP", str(summary["vip_users"])],
        ["Доверенные авторы", str(summary["trusted_uploaders"])],
        ["Средний баланс", _fmt_dec(summary["avg_balance"])],
        ["Монет в системе", _fmt_dec(summary["total_balance"])],
        ["Оплачено Stars", _fmt_dec(summary["paid_stars_total"])],
        ["DAU / WAU / MAU", f"{summary['dau']} / {summary['wau']} / {summary['mau']}"],
    ])
    return rows


def _render_user_report_sync(data: dict, output_path: Path):
    font_name = _register_fonts()
    styles = _build_styles(font_name)
    story = []

    with tempfile.TemporaryDirectory(prefix="user_report_assets_") as tmpdir:
        tmp = Path(tmpdir)

        story.append(Paragraph("Статистика пользователя", styles["H1Custom"]))
        story.append(Paragraph("Подробный отчёт по активности, экономике и Секслото", styles["SmallCustom"]))
        story.append(Spacer(1, 0.3 * cm))
        story.append(_table(_user_summary_table(data), font_name, col_widths=[5 * cm, 10.5 * cm]))
        story.append(PageBreak())

        story.append(Paragraph("1. Экономика", styles["H2Custom"]))
        eco_table = [["Период", "Заработано", "Потрачено", "Чистый результат", "Средний день"]]
        for row in data["economy_rows"]:
            eco_table.append([
                row["period"],
                _fmt_dec(row["earned"]),
                _fmt_dec(row["spent"]),
                _fmt_dec(row["net"]),
                _fmt_dec(row["avg_daily"]),
            ])
        story.append(_table(eco_table, font_name, col_widths=[3 * cm, 3 * cm, 3 * cm, 3.5 * cm, 3 * cm]))
        story.append(Spacer(1, 0.2 * cm))
        bal_chart = _chart_line("Динамика баланса за 30 дней", data["balance_labels_30"], data["balance_series_30"], tmp / "balance.png")
        story.append(Image(bal_chart, width=17 * cm, height=6.5 * cm))
        story.append(Spacer(1, 0.15 * cm))
        ie_chart = _chart_dual_bar("Доходы и расходы по дням", data["balance_labels_30"], data["income_series_30"], data["expense_series_30"], tmp / "income_expense.png")
        story.append(Image(ie_chart, width=17 * cm, height=6.5 * cm))
        story.append(Spacer(1, 0.15 * cm))
        if data["source_income"]:
            story.append(Image(_chart_horizontal_bar("Топ источников дохода", data["source_income"], tmp / "income_sources.png", color="#16A34A"), width=17 * cm, height=6 * cm))
            story.append(Spacer(1, 0.15 * cm))
        if data["source_expense"]:
            story.append(Image(_chart_horizontal_bar("Топ источников расходов", data["source_expense"], tmp / "expense_sources.png", color="#DC2626"), width=17 * cm, height=6 * cm))
        story.append(PageBreak())

        story.append(Paragraph("2. Контент и активность", styles["H2Custom"]))
        content = data["content"]
        content_table = [
            ["Метрика", "Значение"],
            ["Загружено видео", str(content["videos"])],
            ["Загружено фото", str(content["photos"])],
            ["Одобрено", str(content["approved"])],
            ["Отклонено", str(content["rejected"])],
            ["На модерации", str(content["pending"])],
            ["Средний рейтинг", str(content["avg_rating"])],
            ["Просмотры вашего контента", str(content["own_content_views"])],
            ["Ваши просмотры", str(content["own_views"])],
            ["Комментарии", str(content["comments"])],
            ["Реакции", str(content["reactions"])],
        ]
        story.append(_table(content_table, font_name, col_widths=[7 * cm, 8.5 * cm]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Image(_chart_stacked("Загрузки по дням", data["balance_labels_30"], data["upload_series"], tmp / "uploads.png"), width=17 * cm, height=6.5 * cm))
        story.append(Spacer(1, 0.15 * cm))
        if data["status_counts"]:
            story.append(Image(_chart_distribution("Статусы загруженного контента", data["status_counts"], tmp / "content_status.png"), width=16 * cm, height=5 * cm))
        if data["action_counts"]:
            story.append(Spacer(1, 0.15 * cm))
            story.append(Image(_chart_horizontal_bar("Активность по типам действий (30 дней)", data["action_counts"], tmp / "actions.png", color="#0EA5E9"), width=17 * cm, height=5.5 * cm))
        story.append(PageBreak())

        story.append(Paragraph("3. Секслото", styles["H2Custom"]))
        lot_table = [["Период", "Билетов", "Потрачено", "Выиграно", "Результат"]]
        for row in data["lottery_rows"]:
            lot_table.append([row["period"], str(row["tickets"]), _fmt_dec(row["spent"]), _fmt_dec(row["won"]), _fmt_dec(row["net"])])
        story.append(_table(lot_table, font_name, col_widths=[3 * cm, 2 * cm, 3.5 * cm, 3.5 * cm, 3.5 * cm]))
        best_ticket = data.get("best_ticket")
        if best_ticket:
            story.append(Spacer(1, 0.15 * cm))
            story.append(Paragraph(f"Лучший билет: <b>#{best_ticket.id}</b> — <code>{best_ticket.numbers}</code>, совпадений: <b>{best_ticket.matched_count}</b>", styles["BodyCustom"]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Image(_chart_line("Билеты по дням", data["balance_labels_30"], data["ticket_series_30"], tmp / "lottery_tickets.png", color="#F59E0B"), width=17 * cm, height=6 * cm))
        story.append(Spacer(1, 0.15 * cm))
        story.append(Image(_chart_line("Чистый результат Секслото по дням", data["balance_labels_30"], data["lottery_net_series_30"], tmp / "lottery_net.png", color="#7C3AED"), width=17 * cm, height=6 * cm))
        story.append(Spacer(1, 0.15 * cm))
        story.append(Image(_chart_distribution("Распределение совпадений", data["match_distribution"], tmp / "lottery_dist.png"), width=16 * cm, height=5 * cm))
        story.append(PageBreak())

        story.append(Paragraph("4. Рефералы", styles["H2Custom"]))
        ref = data["referrals"]
        ref_table = [["Метрика", "Значение"], ["Приглашено всего", str(ref["total"])], ["Активных рефералов", str(ref["active"])], ["Заработано с рефералов", _fmt_dec(ref["earned_total"])]]
        story.append(_table(ref_table, font_name, col_widths=[7 * cm, 8.5 * cm]))
        ref_period_table = [["Период", "Новых рефералов", "Доход"]]
        for row in ref["rows"]:
            ref_period_table.append([row["period"], str(row["count"]), _fmt_dec(row["income"])])
        story.append(Spacer(1, 0.15 * cm))
        story.append(_table(ref_period_table, font_name, col_widths=[4 * cm, 4 * cm, 4 * cm]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Image(_chart_dual_bar("Рефералы и доход от них (30 дней)", data["referral_labels_30"], data["referral_series_30"], data["referral_income_series_30"], tmp / "referrals.png", left_label="Новые рефералы", right_label="Доход"), width=17 * cm, height=6.5 * cm))
        story.append(PageBreak())

        story.append(Paragraph("5. ИИ-общение", styles["H2Custom"]))
        ai = data["ai"]
        ai_table = [["Период", "Сообщений", "Потрачено"]]
        for row in ai["rows"]:
            ai_table.append([row["period"], str(row["messages"]), _fmt_dec(row["spent"])])
        story.append(_table([["Чатов", str(ai["chat_count"])]], font_name, col_widths=[7 * cm, 4 * cm]))
        story.append(Spacer(1, 0.15 * cm))
        story.append(_table(ai_table, font_name, col_widths=[4 * cm, 4 * cm, 4 * cm]))
        if ai["character_counts"]:
            story.append(Spacer(1, 0.2 * cm))
            story.append(Image(_chart_horizontal_bar("Активность по персонажам", ai["character_counts"], tmp / "ai_characters.png", color="#EC4899"), width=17 * cm, height=5 * cm))
        if any(ai["daily_series_30"]):
            story.append(Spacer(1, 0.15 * cm))
            story.append(Image(_chart_line("Сообщения по дням", data["balance_labels_30"], ai["daily_series_30"], tmp / "ai_daily.png", color="#EC4899"), width=17 * cm, height=6 * cm))
        story.append(PageBreak())

        story.append(Paragraph("6. Итоговый профиль", styles["H2Custom"]))
        story.append(_bullet(f"Вы больше похожи на: <b>{data['insights']['dominant']}</b>", styles))
        story.append(_bullet(f"Основной источник дохода: <b>{data['insights']['top_income']}</b>", styles))
        story.append(_bullet(f"Основной источник расходов: <b>{data['insights']['top_expense']}</b>", styles))
        story.append(_bullet(data['insights']['lottery_comment'], styles))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Paragraph("Этот отчёт собран автоматически на основе ваших действий в боте. Используйте его, чтобы понять, где вы растёте быстрее всего и какие режимы приносят больше пользы.", styles["BodyCustom"]))

        doc = SimpleDocTemplate(str(output_path), pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.2 * cm, bottomMargin=1.2 * cm)
        doc.build(story)


def _render_bot_report_sync(data: dict, output_path: Path):
    font_name = _register_fonts()
    styles = _build_styles(font_name)
    story = []

    with tempfile.TemporaryDirectory(prefix="bot_report_assets_") as tmpdir:
        tmp = Path(tmpdir)

        story.append(Paragraph("Отчёт по боту", styles["H1Custom"]))
        story.append(Paragraph("Общая аналитика по пользователям, экономике, контенту и Секслото", styles["SmallCustom"]))
        story.append(Spacer(1, 0.3 * cm))
        story.append(_table(_bot_summary_table(data), font_name, col_widths=[7 * cm, 8.5 * cm]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(_table([["Период", "Новых пользователей"]] + [[row["period"], str(row["count"])] for row in data["summary"]["new_users"]], font_name, col_widths=[5 * cm, 5 * cm]))
        story.append(PageBreak())

        story.append(Paragraph("1. Рост аудитории", styles["H2Custom"]))
        story.append(Image(_chart_dual_bar("Регистрации и cumulative users (30 дней)", data["growth"]["labels_30"], data["growth"]["registrations_30"], data["growth"]["cumulative_30"], tmp / "growth.png", left_label="Новые", right_label="Всего"), width=17 * cm, height=6.5 * cm))
        story.append(PageBreak())

        story.append(Paragraph("2. Контент", styles["H2Custom"]))
        content = data["content"]
        content_table = [["Метрика", "Значение"], ["Загружено всего", str(content["total"])], ["Одобрено", str(content["approved"])], ["Отклонено", str(content["rejected"])], ["На модерации", str(content["pending"])], ["Автоодобрено", str(content["auto_approved"])], ["Просмотров", str(content["views"])], ["Средний рейтинг", str(content["avg_rating"])]]
        story.append(_table(content_table, font_name, col_widths=[7 * cm, 8.5 * cm]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Image(_chart_line("Загрузки по дням", data["growth"]["labels_30"], content["uploads_30"], tmp / "uploads_bot.png", color="#0EA5E9"), width=17 * cm, height=6 * cm))
        status_map = {"Одобрено": float(content["approved"]), "Отклонено": float(content["rejected"]), "На модерации": float(content["pending"]), "Автоодобрено": float(content["auto_approved"])}
        story.append(Spacer(1, 0.15 * cm))
        story.append(Image(_chart_distribution("Статусы контента", status_map, tmp / "content_status_bot.png"), width=16 * cm, height=5 * cm))
        story.append(PageBreak())

        story.append(Paragraph("3. Экономика бота", styles["H2Custom"]))
        econ = data["economy"]
        econ_table = [["Показатель", "Значение"], ["Сгенерировано монет", _fmt_dec(econ["positive_total"])], ["Сожжено монет", _fmt_dec(econ["negative_total"])]]
        story.append(_table(econ_table, font_name, col_widths=[7 * cm, 8.5 * cm]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Image(_chart_line("Чистая динамика экономики (30 дней)", econ["labels_30"], econ["daily_net_30"], tmp / "economy_net.png", color="#10B981"), width=17 * cm, height=6 * cm))
        if econ["source_income"]:
            story.append(Spacer(1, 0.15 * cm))
            story.append(Image(_chart_horizontal_bar("Топ источников притока", econ["source_income"], tmp / "econ_income.png", color="#16A34A"), width=17 * cm, height=6 * cm))
        if econ["source_expense"]:
            story.append(Spacer(1, 0.15 * cm))
            story.append(Image(_chart_horizontal_bar("Топ источников списаний", econ["source_expense"], tmp / "econ_expense.png", color="#DC2626"), width=17 * cm, height=6 * cm))
        story.append(PageBreak())

        story.append(Paragraph("4. Секслото", styles["H2Custom"]))
        lottery = data["lottery"]
        lot_table = [["Период", "Билетов"]] + [[row["period"], str(row["tickets"])] for row in lottery["rows"]]
        story.append(_table(lot_table, font_name, col_widths=[5 * cm, 5 * cm]))
        story.append(Spacer(1, 0.15 * cm))
        story.append(_table([
            ["Метрика", "Значение"],
            ["Средний призовой фонд", _fmt_dec(lottery["avg_prize_pool"])],
            ["Среднее билетов на розыгрыш", _fmt_dec(lottery["avg_tickets_per_round"])],
            ["Потрачено на билеты", _fmt_dec(lottery["spent"])],
            ["Выплачено игрокам", _fmt_dec(lottery["paid"])],
            ["RTP (грубая оценка)", f"{lottery['rtp']:.2f}%"],
        ], font_name, col_widths=[7 * cm, 8.5 * cm]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Image(_chart_line("Билеты по дням", lottery["labels_30"], lottery["ticket_series_30"], tmp / "lottery_tickets_bot.png", color="#F59E0B"), width=17 * cm, height=6 * cm))
        story.append(Spacer(1, 0.15 * cm))
        story.append(Image(_chart_line("Средний призовой фонд по дням", lottery["labels_30"], lottery["prize_pool_series_30"], tmp / "lottery_pool_bot.png", color="#7C3AED"), width=17 * cm, height=6 * cm))
        story.append(Spacer(1, 0.15 * cm))
        story.append(Image(_chart_distribution("Распределение совпадений", lottery["match_distribution"], tmp / "lottery_match_bot.png"), width=16 * cm, height=5 * cm))
        story.append(PageBreak())

        story.append(Paragraph("5. Рефералы и удержание", styles["H2Custom"]))
        retention = data["retention"]
        ret_table = [["Показатель", "Значение"], ["Retention push-уведомлений", str(retention["retention_pushes"])], ["Активаций weekly promo", str(retention["weekly_promo_activations"])]]
        story.append(_table(ret_table, font_name, col_widths=[7 * cm, 8.5 * cm]))
        story.append(Spacer(1, 0.15 * cm))
        story.append(_table([["Период", "Новых пользователей по рефералке"]] + [[row["period"], str(row["count"])] for row in retention["rows"]], font_name, col_widths=[6 * cm, 6 * cm]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Image(_chart_line("Новые пользователи по рефералке (30 дней)", retention["labels_30"], retention["referred_daily_30"], tmp / "retention_referrals.png", color="#2563EB"), width=17 * cm, height=6 * cm))

        doc = SimpleDocTemplate(str(output_path), pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.2 * cm, bottomMargin=1.2 * cm)
        doc.build(story)


async def build_user_report_pdf(telegram_user_id: int) -> tuple[Path, str]:
    data = await collect_user_report_data(telegram_user_id)
    reports_dir = Path(tempfile.gettempdir()) / "video_exchange_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    filename = f"user_report_{telegram_user_id}_{utc_now().strftime('%Y%m%d_%H%M%S')}.pdf"
    output_path = reports_dir / filename
    await asyncio.to_thread(_render_user_report_sync, data, output_path)
    return output_path, filename


async def build_bot_report_pdf() -> tuple[Path, str]:
    data = await collect_bot_report_data()
    reports_dir = Path(tempfile.gettempdir()) / "video_exchange_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    filename = f"bot_report_{utc_now().strftime('%Y%m%d_%H%M%S')}.pdf"
    output_path = reports_dir / filename
    await asyncio.to_thread(_render_bot_report_sync, data, output_path)
    return output_path, filename
