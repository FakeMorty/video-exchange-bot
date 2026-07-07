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

PAYMENT_TYPE_LABELS = {
    "pack": "Пакеты монет",
    "custom": "Свободное пополнение",
    "vip": "VIP",
    "promo": "Промокоды",
    "lootbox": "Лутбоксы",
    "user_offer": "Офферы пользователей",
    "other": "Другое",
}


def _detect_payment_type(payload: str | None) -> str:
    if not payload:
        return "other"
    for key in ("pack", "custom", "vip", "promo", "lootbox", "user_offer"):
        if payload.startswith(f"{key}_"):
            return key
    return "other"


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
        plt.rcParams["font.family"] = "DejaVu Sans"
        plt.rcParams["axes.unicode_minus"] = False
        return "DejaVuSans"
    except Exception:
        return "Helvetica"



def _build_styles(font_name: str):
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H1Custom", parent=styles["Heading1"], fontName=font_name, fontSize=18, leading=22, textColor=colors.HexColor("#2A2A2A")))
    styles.add(ParagraphStyle(name="H2Custom", parent=styles["Heading2"], fontName=font_name, fontSize=13, leading=16, textColor=colors.HexColor("#3A3A3A"), spaceBefore=10, spaceAfter=6))
    styles.add(ParagraphStyle(name="H3Custom", parent=styles["Heading3"], fontName=font_name, fontSize=11, leading=14, textColor=colors.HexColor("#475569"), spaceBefore=8, spaceAfter=4))
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


def _chart_heatmap(title: str, matrix: list[list[float]], x_labels: list[str], y_labels: list[str], path: Path, cmap: str = "YlOrRd"):
    fig, ax = plt.subplots(figsize=(10, 3.8))
    image = ax.imshow(matrix, aspect="auto", cmap=cmap)
    ax.set_xticks(range(len(x_labels)))
    ax.set_xticklabels(x_labels, fontsize=7)
    ax.set_yticks(range(len(y_labels)))
    ax.set_yticklabels(y_labels, fontsize=8)
    ax.set_title(title)
    ax.set_xlabel("Часы")
    ax.set_ylabel("Дни недели")
    fig.colorbar(image, ax=ax, fraction=0.03, pad=0.02)
    return _save_chart(fig, path)



def _bullet(text: str, styles):
    return Paragraph(f"• {text}", styles["BodyCustom"])


def _safe_div(numerator, denominator) -> float:
    if not denominator:
        return 0.0
    return float(numerator) / float(denominator)


def _fmt_pct(value: Decimal | float | int | None) -> str:
    if value is None:
        return "0%"
    dec = Decimal(str(value)).quantize(Decimal("0.1"))
    text = f"{dec}".replace(".", ",")
    if text.endswith(",0"):
        text = text[:-2]
    return f"{text}%"


def _describe_activity_segment(active_days_30: int) -> str:
    if active_days_30 >= 20:
        return "ядро аудитории"
    if active_days_30 >= 10:
        return "регулярный пользователь"
    if active_days_30 >= 3:
        return "эпизодический пользователь"
    return "редко возвращается"


def _report_footer(canvas, doc, *, title: str, generated_at: str, font_name: str):
    canvas.saveState()
    canvas.setFont(font_name, 8)
    canvas.setFillColor(colors.HexColor("#64748B"))
    canvas.drawString(doc.leftMargin, 0.75 * cm, f"{title} • сгенерировано {generated_at}")
    canvas.drawRightString(A4[0] - doc.rightMargin, 0.75 * cm, f"Стр. {canvas.getPageNumber()}")
    canvas.restoreState()


def _median_number(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _build_comparison_row(label: str, value: float | int | Decimal, population_values: list[float | int | Decimal]) -> dict:
    values = [float(v or 0) for v in population_values] or [0.0]
    current = float(value or 0)
    total = len(values)
    rank = 1 + sum(1 for item in values if item > current)
    percentile = _safe_div(sum(1 for item in values if item <= current) * 100, total)
    return {
        "label": label,
        "value": current,
        "avg": _safe_div(sum(values), total),
        "median": _median_number(values),
        "rank": rank,
        "total": total,
        "percentile": percentile,
    }


def _report_user_name(user: User) -> str:
    if user.display_name:
        return user.display_name
    if user.username:
        return f"@{user.username}"
    return f"ID {user.telegram_id}"


def _top_user_rows(users: list[User], value_getter, limit: int = 10) -> list[dict]:
    ranked = sorted(users, key=lambda item: (float(value_getter(item) or 0), item.id), reverse=True)
    rows: list[dict] = []
    for user in ranked:
        value = float(value_getter(user) or 0)
        if value <= 0:
            continue
        rows.append({
            "name": _report_user_name(user),
            "telegram_id": user.telegram_id,
            "value": value,
        })
        if len(rows) >= limit:
            break
    return rows


async def _collect_activity_dates(session) -> dict[int, set]:
    activity_dates: dict[int, set] = defaultdict(set)
    statements = [
        select(UserActionLog.user_id, UserActionLog.created_at),
        select(VideoView.user_id, VideoView.created_at),
        select(Comment.user_id, Comment.created_at),
        select(ContentReaction.user_id, ContentReaction.created_at),
        select(Payment.user_id, Payment.created_at).where(Payment.status == "paid"),
        select(LotteryTicket.user_id, LotteryTicket.created_at),
        select(Video.uploader_user_id, Video.created_at),
        select(KatyaChat.user_id, KatyaMessage.created_at).join(KatyaMessage, KatyaMessage.chat_id == KatyaChat.id),
    ]
    for stmt in statements:
        for user_id, created_at in (await session.execute(stmt)).all():
            if user_id and created_at:
                activity_dates[int(user_id)].add(created_at.date())
    return activity_dates


async def _collect_activity_timestamps(session, start) -> list:
    timestamps = []
    statements = [
        select(UserActionLog.created_at).where(UserActionLog.created_at >= start),
        select(VideoView.created_at).where(VideoView.created_at >= start),
        select(Comment.created_at).where(Comment.created_at >= start),
        select(ContentReaction.created_at).where(ContentReaction.created_at >= start),
        select(Payment.created_at).where(Payment.status == "paid", Payment.created_at >= start),
        select(LotteryTicket.created_at).where(LotteryTicket.created_at >= start),
        select(Video.created_at).where(Video.created_at >= start),
        select(KatyaMessage.created_at).where(KatyaMessage.created_at >= start),
    ]
    for stmt in statements:
        timestamps.extend([ts for ts in (await session.execute(stmt)).scalars().all() if ts])
    return timestamps


def _build_hour_weekday_heatmap(timestamps: list) -> dict:
    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    hours = [f"{hour:02d}" for hour in range(24)]
    matrix = [[0.0 for _ in range(24)] for _ in range(7)]
    for timestamp in timestamps:
        matrix[timestamp.weekday()][timestamp.hour] += 1.0
    return {"weekdays": weekdays, "hours": hours, "matrix": matrix}


def _build_cohort_retention(users: list[tuple[int, object]], activity_dates: dict[int, set], as_of_date) -> dict:
    summary = {
        1: {"eligible": 0, "retained": 0},
        7: {"eligible": 0, "retained": 0},
        30: {"eligible": 0, "retained": 0},
    }
    weekly = defaultdict(lambda: {"size": 0, "retained_d7": 0})

    for user_id, created_at in users:
        reg_date = created_at.date()
        user_activity = activity_dates.get(int(user_id), set())
        for day in (1, 7, 30):
            if (as_of_date - reg_date).days >= day:
                summary[day]["eligible"] += 1
                if reg_date + timedelta(days=day) in user_activity:
                    summary[day]["retained"] += 1
        if (as_of_date - reg_date).days >= 7:
            year, week, _ = reg_date.isocalendar()
            key = f"{year}-W{week:02d}"
            weekly[key]["size"] += 1
            if reg_date + timedelta(days=7) in user_activity:
                weekly[key]["retained_d7"] += 1

    weekly_rows = []
    for cohort_key in sorted(weekly.keys())[-6:]:
        row = weekly[cohort_key]
        rate = _safe_div(row["retained_d7"] * 100, row["size"])
        weekly_rows.append({
            "cohort": cohort_key,
            "size": row["size"],
            "retained_d7": row["retained_d7"],
            "d7_rate": rate,
        })

    return {
        "d1": {**summary[1], "rate": _safe_div(summary[1]["retained"] * 100, summary[1]["eligible"])},
        "d7": {**summary[7], "rate": _safe_div(summary[7]["retained"] * 100, summary[7]["eligible"])},
        "d30": {**summary[30], "rate": _safe_div(summary[30]["retained"] * 100, summary[30]["eligible"])},
        "weekly_rows": weekly_rows,
        "weekly_chart": {row["cohort"]: row["d7_rate"] for row in weekly_rows},
    }


async def collect_user_report_data(telegram_user_id: int) -> dict:
    async with async_session() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_user_id))
        if not user:
            raise ValueError("Пользователь не найден")

        now = utc_now()
        generated_at = now.strftime("%d.%m.%Y %H:%M UTC")
        period_starts = {label: _period_start(days) for label, days in PERIODS}
        reg_days = max(1, (now.date() - user.created_at.date()).days + 1)

        display_name = await get_styled_display_name(session, user)
        is_vip = bool(user.vip_until and user.vip_until > now)

        all_logs = (await session.execute(select(BalanceLog).where(BalanceLog.user_id == user.id).order_by(BalanceLog.created_at.asc()))).scalars().all()
        logs_30 = [log for log in all_logs if log.created_at >= (now - timedelta(days=30))]

        payments = (await session.execute(select(Payment).where(Payment.user_id == user.id, Payment.status == "paid").order_by(Payment.created_at.asc()))).scalars().all()
        payments_30 = [payment for payment in payments if payment.created_at >= (now - timedelta(days=30))]
        paid_stars_total = sum(int(payment.stars_amount or 0) for payment in payments)
        paid_stars_30 = sum(int(payment.stars_amount or 0) for payment in payments_30)
        paid_coins_total = sum((Decimal(str(payment.coins_amount or 0)) for payment in payments), Decimal("0"))
        payment_type_counts = Counter(PAYMENT_TYPE_LABELS.get(_detect_payment_type(payment.payload), "Другое") for payment in payments)
        payment_stars_daily = defaultdict(float)
        payment_count_daily = defaultdict(float)
        for payment in payments_30:
            day = str(payment.created_at.date())
            payment_stars_daily[day] += float(payment.stars_amount or 0)
            payment_count_daily[day] += 1.0

        economy_rows = []
        for label, days in PERIODS:
            start = period_starts[label]
            relevant = [log for log in all_logs if start is None or log.created_at >= start]
            earned = sum((log.amount for log in relevant if log.amount > 0), Decimal("0"))
            spent = sum((-log.amount for log in relevant if log.amount < 0), Decimal("0"))
            net = earned - spent
            day_span = days or reg_days
            avg_daily = (net / Decimal(day_span)) if day_span else Decimal("0")
            economy_rows.append({"period": label, "earned": earned, "spent": spent, "net": net, "avg_daily": avg_daily})

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

        uploads = (await session.execute(select(Video).where(Video.uploader_user_id == user.id))).scalars().all()
        ratings_avg = (await session.execute(select(func.avg(VideoRating.rating)).join(Video, Video.id == VideoRating.video_id).where(Video.uploader_user_id == user.id))).scalar_one()
        own_content_views = await _count_query(session, select(func.count(VideoView.id)).join(Video, Video.id == VideoView.video_id).where(Video.uploader_user_id == user.id, VideoView.user_id != user.id))
        own_views = await _count_query(session, select(func.count(VideoView.id)).where(VideoView.user_id == user.id))
        comments = (await session.execute(select(Comment).where(Comment.user_id == user.id))).scalars().all()
        reactions = (await session.execute(select(ContentReaction).where(ContentReaction.user_id == user.id))).scalars().all()
        own_view_rows_30 = (await session.execute(select(VideoView.created_at).where(VideoView.user_id == user.id, VideoView.created_at >= now - timedelta(days=30)))).scalars().all()
        actions_30 = (await session.execute(select(UserActionLog.action, func.count(UserActionLog.id)).where(UserActionLog.user_id == user.id, UserActionLog.created_at >= now - timedelta(days=30)).group_by(UserActionLog.action))).all()
        action_dates_30 = (await session.execute(select(UserActionLog.created_at).where(UserActionLog.user_id == user.id, UserActionLog.created_at >= now - timedelta(days=30)))).scalars().all()

        uploads_30 = [video for video in uploads if video.created_at >= (now - timedelta(days=30))]
        comments_30 = [comment for comment in comments if comment.created_at >= (now - timedelta(days=30))]
        reactions_30 = [reaction for reaction in reactions if reaction.created_at >= (now - timedelta(days=30))]

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
        upload_series = {"Видео": [upload_daily_video.get(day, 0.0) for day in last_30_labels], "Фото": [upload_daily_photo.get(day, 0.0) for day in last_30_labels]}
        action_counts = {action: float(count) for action, count in actions_30}
        approval_rate_pct = _safe_div(status_counts.get("approved", 0) * 100, len(uploads))
        content_efficiency = {
            "uploads_total": len(uploads),
            "approved_share_pct": approval_rate_pct,
            "views_per_upload": _safe_div(own_content_views, len(uploads)),
            "views_per_approved_upload": _safe_div(own_content_views, status_counts.get("approved", 0)),
        }
        activity_mix_30 = {
            "Просмотры": float(len(own_view_rows_30)),
            "Загрузки": float(len(uploads_30)),
            "Комментарии": float(len(comments_30)),
            "Реакции": float(len(reactions_30)),
        }

        tickets = (await session.execute(select(LotteryTicket).where(LotteryTicket.user_id == user.id).order_by(LotteryTicket.created_at.asc()))).scalars().all()
        lottery_logs = [log for log in all_logs if log.source in LOTTERY_BALANCE_SOURCES]
        lottery_rows = []
        for label, days in PERIODS:
            start = period_starts[label]
            rel_tickets = [ticket for ticket in tickets if start is None or ticket.created_at >= start]
            rel_logs = [log for log in lottery_logs if start is None or log.created_at >= start]
            spent = sum((-log.amount for log in rel_logs if log.source == "lottery_ticket_purchase" and log.amount < 0), Decimal("0"))
            won = sum((log.amount for log in rel_logs if log.source.startswith("lottery_win_") or log.source == "lottery_bet_win"), Decimal("0"))
            lottery_rows.append({"period": label, "tickets": len(rel_tickets), "spent": spent, "won": won, "net": won - spent})
        best_ticket = max(tickets, key=lambda ticket: (ticket.matched_count, ticket.created_at), default=None)
        match_distribution = Counter(str(ticket.matched_count) for ticket in tickets)
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
        lottery_win_tickets = sum(1 for ticket in tickets if ticket.matched_count >= 4)
        lottery_avg_matches = _safe_div(sum(ticket.matched_count for ticket in tickets), len(tickets))
        lottery_win_rate = _safe_div(lottery_win_tickets * 100, len(tickets))
        lottery_rounds_played = len({ticket.round_id for ticket in tickets})
        lottery_spent_total = sum((-log.amount for log in lottery_logs if log.source == "lottery_ticket_purchase" and log.amount < 0), Decimal("0"))
        lottery_won_total = sum((log.amount for log in lottery_logs if log.source.startswith("lottery_win_") or log.source == "lottery_bet_win"), Decimal("0"))
        lottery_roi_pct = _safe_div(lottery_won_total * 100, lottery_spent_total)

        referrals = (await session.execute(select(User).where(User.referred_by_user_id == user.id).order_by(User.created_at.asc()))).scalars().all()
        referral_ids = [ref.id for ref in referrals]
        active_referrals = 0
        if referral_ids:
            referral_view_rows = (await session.execute(select(VideoView.user_id, func.count(VideoView.id)).join(Video, Video.id == VideoView.video_id).where(VideoView.user_id.in_(referral_ids), Video.content_type == "video").group_by(VideoView.user_id))).all()
            active_referrals = sum(1 for _ref_id, view_count in referral_view_rows if (view_count or 0) >= 5)
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
        referral_activation_rate = _safe_div(active_referrals * 100, len(referrals))

        chats = (await session.execute(select(KatyaChat).where(KatyaChat.user_id == user.id))).scalars().all()
        ai_messages = (await session.execute(select(KatyaMessage, KatyaChat.character).join(KatyaChat, KatyaChat.id == KatyaMessage.chat_id).where(KatyaChat.user_id == user.id).order_by(KatyaMessage.created_at.asc()))).all()
        ai_logs = [log for log in all_logs if log.source == "katya_chat"]
        ai_rows = []
        for label, days in PERIODS:
            start = period_starts[label]
            msgs = [message for message, _character in ai_messages if start is None or message.created_at >= start]
            spent = sum((-log.amount for log in ai_logs if (start is None or log.created_at >= start) and log.amount < 0), Decimal("0"))
            ai_rows.append({"period": label, "messages": len(msgs), "spent": spent})
        ai_daily = defaultdict(float)
        ai_character_counts = Counter()
        ai_user_messages = 0
        ai_assistant_messages = 0
        for message_obj, character in ai_messages:
            ai_character_counts[character or "katya"] += 1
            if message_obj.role == "user":
                ai_user_messages += 1
            else:
                ai_assistant_messages += 1
            if message_obj.created_at >= now - timedelta(days=30):
                ai_daily[str(message_obj.created_at.date())] += 1
        activity_mix_30["ИИ-сообщения"] = float(sum(ai_daily.values()))
        activity_mix_30["Билеты Секслото"] = float(sum(ticket_series))
        ai_spent_total = sum((-log.amount for log in ai_logs if log.amount < 0), Decimal("0"))
        ai_cost_per_user_message = _safe_div(ai_spent_total, ai_user_messages)

        active_dates_30 = {str(log.created_at.date()) for log in logs_30}
        active_dates_30.update(str(video.created_at.date()) for video in uploads_30)
        active_dates_30.update(str(comment.created_at.date()) for comment in comments_30)
        active_dates_30.update(str(reaction.created_at.date()) for reaction in reactions_30)
        active_dates_30.update(str(dt.date()) for dt in own_view_rows_30)
        active_dates_30.update(str(dt.date()) for dt in action_dates_30)
        active_dates_30.update(str(message.created_at.date()) for message, _character in ai_messages if message.created_at >= now - timedelta(days=30))
        active_days_30 = len(active_dates_30)
        activity_segment = _describe_activity_segment(active_days_30)

        dominant_map = {"контент-мейкер": len(uploads), "зритель": own_views, "игрок Секслото": len(tickets), "любитель ИИ-общения": len(ai_messages)}
        dominant_type = max(dominant_map, key=dominant_map.get) if dominant_map else "пользователь"
        top_income = max(source_income.items(), key=lambda kv: kv[1])[0] if source_income else None
        top_expense = max(source_expense.items(), key=lambda kv: kv[1])[0] if source_expense else None
        lottery_all_time = next((row for row in lottery_rows if row["period"] == "Всё время"), None)
        if lottery_all_time and lottery_all_time["tickets"]:
            lottery_comment = "Секслото приносит плюс" if lottery_all_time["net"] > 0 else "Секслото пока убыточно"
        else:
            lottery_comment = "Секслото пока не использовалось"

        last_30_net = next((row["net"] for row in economy_rows if row["period"] == "30 дней"), Decimal("0"))
        balance_comment = "За 30 дней баланс растёт" if last_30_net > 0 else ("За 30 дней баланс снижается" if last_30_net < 0 else "Баланс за 30 дней почти без изменений")
        referral_comment = f"Реферальный канал даёт {_fmt_pct(referral_activation_rate)} активных приглашённых" if referrals else "Рефералы пока не используются"
        content_comment = f"Контент одобряется с конверсией {_fmt_pct(approval_rate_pct)}" if uploads else "Пользователь пока не загружал контент"
        purchase_comment = f"Успешных покупок: {len(payments)} на {paid_stars_total} Stars" if payments else "Платных покупок пока не было"

        user_ids = [row[0] for row in (await session.execute(select(User.id).order_by(User.id.asc()))).all()]
        upload_count_map = {uid: int(cnt) for uid, cnt in (await session.execute(select(Video.uploader_user_id, func.count(Video.id)).group_by(Video.uploader_user_id))).all()}
        view_count_map = {uid: int(cnt) for uid, cnt in (await session.execute(select(VideoView.user_id, func.count(VideoView.id)).group_by(VideoView.user_id))).all()}
        payment_stars_map = {uid: int(total or 0) for uid, total in (await session.execute(select(Payment.user_id, func.sum(Payment.stars_amount)).where(Payment.status == "paid").group_by(Payment.user_id))).all()}
        lottery_ticket_map = {uid: int(cnt) for uid, cnt in (await session.execute(select(LotteryTicket.user_id, func.count(LotteryTicket.id)).group_by(LotteryTicket.user_id))).all()}
        referral_count_map = {uid: int(cnt) for uid, cnt in (await session.execute(select(User.referred_by_user_id, func.count(User.id)).where(User.referred_by_user_id.is_not(None)).group_by(User.referred_by_user_id))).all()}

        all_balances = (await session.execute(select(User.balance))).scalars().all()
        all_xp = (await session.execute(select(User.xp))).scalars().all()
        comparison_rows = [
            _build_comparison_row("Баланс", user.balance, list(all_balances)),
            _build_comparison_row("XP", user.xp, list(all_xp)),
            _build_comparison_row("Загружено контента", len(uploads), [upload_count_map.get(uid, 0) for uid in user_ids]),
            _build_comparison_row("Просмотров", own_views, [view_count_map.get(uid, 0) for uid in user_ids]),
            _build_comparison_row("Рефералов", len(referrals), [referral_count_map.get(uid, 0) for uid in user_ids]),
            _build_comparison_row("Потрачено Stars", paid_stars_total, [payment_stars_map.get(uid, 0) for uid in user_ids]),
            _build_comparison_row("Билетов Секслото", len(tickets), [lottery_ticket_map.get(uid, 0) for uid in user_ids]),
        ]
        strongest_metric = max(comparison_rows, key=lambda row: row["percentile"], default=None)
        weakest_metric = min(comparison_rows, key=lambda row: row["percentile"], default=None)

    return {
        "generated_at": generated_at,
        "user": user,
        "display_name": display_name,
        "is_vip": is_vip,
        "profile": {"registration_days": reg_days, "bonus_streak": user.bonus_streak, "active_days_30": active_days_30, "activity_segment": activity_segment},
        "payments": {"count": len(payments), "count_30": len(payments_30), "stars_total": paid_stars_total, "stars_30": paid_stars_30, "coins_total": paid_coins_total, "types": {k: float(v) for k, v in payment_type_counts.items()}, "stars_series_30": [payment_stars_daily.get(day, 0.0) for day in last_30_labels], "count_series_30": [payment_count_daily.get(day, 0.0) for day in last_30_labels]},
        "economy_rows": economy_rows,
        "balance_labels_30": last_30_labels,
        "balance_series_30": balance_series,
        "income_series_30": income_series,
        "expense_series_30": expense_series,
        "source_income": _top_items(source_income, INCOME_SOURCE_LABELS),
        "source_expense": _top_items(source_expense, EXPENSE_SOURCE_LABELS),
        "content": {"videos": sum(1 for video in uploads if video.content_type == "video"), "photos": sum(1 for video in uploads if video.content_type == "photo"), "approved": status_counts.get("approved", 0), "rejected": status_counts.get("rejected", 0), "pending": status_counts.get("pending", 0), "avg_rating": round(float(ratings_avg or 0), 2), "own_content_views": own_content_views, "own_views": own_views, "comments": len(comments), "reactions": len(reactions), "approval_rate_pct": approval_rate_pct, "efficiency": content_efficiency},
        "upload_series": upload_series,
        "status_counts": {k: float(v) for k, v in status_counts.items()},
        "action_counts": _top_items(action_counts, {}),
        "activity_mix_30": activity_mix_30,
        "lottery_rows": lottery_rows,
        "best_ticket": best_ticket,
        "match_distribution": {str(i): float(match_distribution.get(str(i), 0)) for i in range(7)},
        "ticket_series_30": ticket_series,
        "lottery_net_series_30": lottery_net_series,
        "lottery": {"rounds_played": lottery_rounds_played, "tickets_total": len(tickets), "win_tickets": lottery_win_tickets, "win_rate_pct": lottery_win_rate, "avg_matches": lottery_avg_matches, "spent_total": lottery_spent_total, "won_total": lottery_won_total, "roi_pct": lottery_roi_pct},
        "referrals": {"total": len(referrals), "active": active_referrals, "activation_rate_pct": referral_activation_rate, "earned_total": user.referral_earnings, "rows": referral_rows},
        "referral_labels_30": last_30_labels,
        "referral_series_30": [referral_daily.get(day, 0.0) for day in last_30_labels],
        "referral_income_series_30": [float(referral_income_daily.get(day, Decimal("0"))) for day in last_30_labels],
        "ai": {"chat_count": len(chats), "rows": ai_rows, "user_messages": ai_user_messages, "assistant_messages": ai_assistant_messages, "avg_messages_per_chat": _safe_div(len(ai_messages), len(chats)), "avg_cost_per_user_message": ai_cost_per_user_message, "character_counts": {k: float(v) for k, v in ai_character_counts.items()}, "daily_series_30": [ai_daily.get(day, 0.0) for day in last_30_labels]},
        "comparison": {
            "rows": comparison_rows,
            "population": len(user_ids),
            "strongest": strongest_metric["label"] if strongest_metric else "—",
            "weakest": weakest_metric["label"] if weakest_metric else "—",
        },
        "insights": {"dominant": dominant_type, "activity_segment": activity_segment, "top_income": INCOME_SOURCE_LABELS.get(top_income, top_income) if top_income else "—", "top_expense": EXPENSE_SOURCE_LABELS.get(top_expense, top_expense) if top_expense else "—", "lottery_comment": lottery_comment, "balance_comment": balance_comment, "referral_comment": referral_comment, "content_comment": content_comment, "purchase_comment": purchase_comment},
    }



async def collect_bot_report_data() -> dict:
    async with async_session() as session:
        now = utc_now()
        generated_at = now.strftime("%d.%m.%Y %H:%M UTC")
        period_starts = {label: _period_start(days) for label, days in PERIODS}

        total_users = await _count_query(session, select(func.count(User.id)))
        active_users = await _count_query(session, select(func.count(User.id)).where(User.status == "active"))
        vip_users = await _count_query(session, select(func.count(User.id)).where(User.vip_until.is_not(None), User.vip_until > now))
        trusted_uploaders = await _count_query(session, select(func.count(TrustedUploader.id)))
        total_balance = Decimal(str((await session.execute(select(func.sum(User.balance)))).scalar_one() or 0))
        avg_balance = Decimal(str((await session.execute(select(func.avg(User.balance)))).scalar_one() or 0))
        purchases_paid = Decimal(str((await session.execute(select(func.sum(Payment.stars_amount)).where(Payment.status == "paid"))).scalar_one() or 0))
        payer_count = await _count_query(session, select(func.count(func.distinct(Payment.user_id))).where(Payment.status == "paid"))
        payments_count = await _count_query(session, select(func.count(Payment.id)).where(Payment.status == "paid"))
        paid_payments = (await session.execute(select(Payment).where(Payment.status == "paid"))).scalars().all()
        payment_type_counts = Counter()
        payment_type_stars = defaultdict(float)
        payment_type_coins = defaultdict(float)
        for payment in paid_payments:
            label = PAYMENT_TYPE_LABELS.get(_detect_payment_type(payment.payload), "Другое")
            payment_type_counts[label] += 1
            payment_type_stars[label] += float(payment.stars_amount or 0)
            payment_type_coins[label] += float(payment.coins_amount or 0)
        payment_breakdown_rows = [
            {
                "label": label,
                "count": int(payment_type_counts[label]),
                "stars_total": float(payment_type_stars[label]),
                "coins_total": float(payment_type_coins[label]),
                "avg_stars": _safe_div(payment_type_stars[label], payment_type_counts[label]),
            }
            for label in sorted(payment_type_counts.keys(), key=lambda key: payment_type_stars[key], reverse=True)
        ]

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
        sticky_pct = _safe_div(dau * 100, mau)

        reg_rows = (await session.execute(select(func.date(User.created_at), func.count(User.id)).where(User.created_at >= now - timedelta(days=30)).group_by(func.date(User.created_at)).order_by(func.date(User.created_at)))).all()
        labels_30 = _daterange(30)
        reg_map = {str(day): float(count) for day, count in reg_rows}
        reg_series = [reg_map.get(day, 0.0) for day in labels_30]
        cumulative = []
        running = total_users - int(sum(reg_series))
        for value in reg_series:
            running += int(value)
            cumulative.append(float(running))
        registrations_last_7 = int(sum(reg_series[-7:]))
        registrations_prev_7 = int(sum(reg_series[-14:-7])) if len(reg_series) >= 14 else 0

        payment_rows_30 = (await session.execute(select(func.date(Payment.created_at), func.sum(Payment.stars_amount), func.count(Payment.id)).where(Payment.status == "paid", Payment.created_at >= now - timedelta(days=30)).group_by(func.date(Payment.created_at)).order_by(func.date(Payment.created_at)))).all()
        payment_stars_map = {str(day): float(total or 0) for day, total, _count in payment_rows_30}
        payment_count_map = {str(day): float(count or 0) for day, _total, count in payment_rows_30}

        content_total = await _count_query(session, select(func.count(Video.id)))
        content_approved = await _count_query(session, select(func.count(Video.id)).where(Video.status == "approved"))
        content_rejected = await _count_query(session, select(func.count(Video.id)).where(Video.status == "rejected"))
        content_pending = await _count_query(session, select(func.count(Video.id)).where(Video.status == "pending"))
        auto_approved = await _count_query(session, select(func.count(UserActionLog.id)).where(UserActionLog.action == "video_auto_approved"))
        total_views = await _count_query(session, select(func.count(VideoView.id)))
        avg_rating = (await session.execute(select(func.avg(VideoRating.rating)))).scalar_one() or 0
        creators_total = await _count_query(session, select(func.count(func.distinct(Video.uploader_user_id))))
        creators_30 = await _count_query(session, select(func.count(func.distinct(Video.uploader_user_id))).where(Video.created_at >= now - timedelta(days=30)))
        viewers_30 = await _count_query(session, select(func.count(func.distinct(VideoView.user_id))).where(VideoView.created_at >= now - timedelta(days=30)))
        upload_rows = (await session.execute(select(func.date(Video.created_at), func.count(Video.id)).where(Video.created_at >= now - timedelta(days=30)).group_by(func.date(Video.created_at)).order_by(func.date(Video.created_at)))).all()
        upload_map = {str(day): float(count) for day, count in upload_rows}
        upload_series = [upload_map.get(day, 0.0) for day in labels_30]
        approval_rate_pct = _safe_div(content_approved * 100, content_total)
        avg_views_per_upload = _safe_div(total_views, content_approved or content_total)
        avg_uploads_per_creator = _safe_div(content_total, creators_total)

        positive_total = Decimal(str((await session.execute(select(func.sum(BalanceLog.amount)).where(BalanceLog.amount > 0))).scalar_one() or 0))
        negative_total_raw = Decimal(str((await session.execute(select(func.sum(BalanceLog.amount)).where(BalanceLog.amount < 0))).scalar_one() or 0))
        negative_total = abs(negative_total_raw)
        net_total = positive_total - negative_total
        source_income_rows = (await session.execute(select(BalanceLog.source, func.sum(BalanceLog.amount)).where(BalanceLog.amount > 0).group_by(BalanceLog.source))).all()
        source_expense_rows = (await session.execute(select(BalanceLog.source, func.sum(-BalanceLog.amount)).where(BalanceLog.amount < 0).group_by(BalanceLog.source))).all()
        source_income = _top_items({src: float(val or 0) for src, val in source_income_rows}, INCOME_SOURCE_LABELS, limit=8)
        source_expense = _top_items({src: float(val or 0) for src, val in source_expense_rows}, EXPENSE_SOURCE_LABELS, limit=8)
        econ_rows = (await session.execute(select(func.date(BalanceLog.created_at), func.sum(BalanceLog.amount)).where(BalanceLog.created_at >= now - timedelta(days=30)).group_by(func.date(BalanceLog.created_at)).order_by(func.date(BalanceLog.created_at)))).all()
        econ_map = {str(day): float(val or 0) for day, val in econ_rows}
        econ_series = [econ_map.get(day, 0.0) for day in labels_30]

        lottery_ticket_rows = []
        for label, days in PERIODS:
            start = period_starts[label]
            stmt = select(func.count(LotteryTicket.id))
            if start is not None:
                stmt = stmt.where(LotteryTicket.created_at >= start)
            lottery_ticket_rows.append({"period": label, "tickets": await _count_query(session, stmt)})
        rounds_total = await _count_query(session, select(func.count(LotteryRound.id)))
        total_tickets = await _count_query(session, select(func.count(LotteryTicket.id)))
        players_total = await _count_query(session, select(func.count(func.distinct(LotteryTicket.user_id))))
        players_30 = await _count_query(session, select(func.count(func.distinct(LotteryTicket.user_id))).where(LotteryTicket.created_at >= now - timedelta(days=30)))
        avg_prize_pool = Decimal(str((await session.execute(select(func.avg(LotteryRound.prize_pool)))).scalar_one() or 0))
        lottery_ticket_subq = (select(LotteryRound.id.label("round_id"), func.count(LotteryTicket.id).label("ticket_count")).join(LotteryTicket, LotteryTicket.round_id == LotteryRound.id, isouter=True).group_by(LotteryRound.id).subquery())
        avg_tickets_per_round = Decimal(str((await session.execute(select(func.avg(lottery_ticket_subq.c.ticket_count)))).scalar_one() or 0))
        win_counts = {"6 совпадений": await _count_query(session, select(func.count(BalanceLog.id)).where(BalanceLog.source == "lottery_win_6")), "5 совпадений": await _count_query(session, select(func.count(BalanceLog.id)).where(BalanceLog.source == "lottery_win_5")), "4 совпадения": await _count_query(session, select(func.count(BalanceLog.id)).where(BalanceLog.source == "lottery_win_4"))}
        lottery_spent = await _sum_balance(session, None, positive=False, sources={"lottery_ticket_purchase"})
        lottery_paid = await _sum_balance(session, None, positive=True, sources={"lottery_win_4", "lottery_win_5", "lottery_win_6", "lottery_bet_win"})
        rtp = float((lottery_paid / lottery_spent) * 100) if lottery_spent > 0 else 0.0
        penetration_pct = _safe_div(players_total * 100, total_users)
        avg_tickets_per_player = _safe_div(total_tickets, players_total)
        ticket_daily_rows = (await session.execute(select(func.date(LotteryTicket.created_at), func.count(LotteryTicket.id)).where(LotteryTicket.created_at >= now - timedelta(days=30)).group_by(func.date(LotteryTicket.created_at)).order_by(func.date(LotteryTicket.created_at)))).all()
        ticket_daily_map = {str(day): float(count) for day, count in ticket_daily_rows}
        lottery_player_daily_rows = (await session.execute(select(func.date(LotteryTicket.created_at), func.count(func.distinct(LotteryTicket.user_id))).where(LotteryTicket.created_at >= now - timedelta(days=30)).group_by(func.date(LotteryTicket.created_at)).order_by(func.date(LotteryTicket.created_at)))).all()
        lottery_player_daily_map = {str(day): float(count) for day, count in lottery_player_daily_rows}
        prize_pool_rows = (await session.execute(select(func.date(LotteryRound.draw_starts_at), func.avg(LotteryRound.prize_pool)).where(LotteryRound.draw_starts_at >= now - timedelta(days=30)).group_by(func.date(LotteryRound.draw_starts_at)).order_by(func.date(LotteryRound.draw_starts_at)))).all()
        prize_pool_map = {str(day): float(val or 0) for day, val in prize_pool_rows}
        match_dist_rows = (await session.execute(select(LotteryTicket.matched_count, func.count(LotteryTicket.id)).group_by(LotteryTicket.matched_count))).all()
        match_distribution = {str(int(m or 0)): float(c) for m, c in match_dist_rows}

        referred_total = await _count_query(session, select(func.count(User.id)).where(User.referred_by_user_id.is_not(None)))
        referred_share_pct = _safe_div(referred_total * 100, total_users)
        referred_rows = []
        for label, days in PERIODS:
            start = period_starts[label]
            stmt = select(func.count(User.id)).where(User.referred_by_user_id.is_not(None))
            if start is not None:
                stmt = stmt.where(User.created_at >= start)
            referred_rows.append({"period": label, "count": await _count_query(session, stmt)})
        retention_pushes = await _count_query(session, select(func.count(UserActionLog.id)).where(UserActionLog.action == "retention_push"))
        weekly_promo_activations = await _count_query(session, select(func.count(PromocodeActivation.id)).join(Promocode, Promocode.id == PromocodeActivation.promocode_id).where(Promocode.code.like("FREEBIE_%")))
        retention_rows = (await session.execute(select(func.date(User.created_at), func.count(User.id)).where(User.referred_by_user_id.is_not(None), User.created_at >= now - timedelta(days=30)).group_by(func.date(User.created_at)))).all()
        retention_map = {str(day): float(count) for day, count in retention_rows}

        if registrations_last_7 > registrations_prev_7:
            growth_comment = "Рост ускоряется относительно предыдущей недели"
        elif registrations_last_7 < registrations_prev_7:
            growth_comment = "Рост замедлился относительно предыдущей недели"
        else:
            growth_comment = "Темп регистраций стабилен"
        monetization_comment = f"Платёжная конверсия держится на уровне {_fmt_pct(_safe_div(payer_count * 100, total_users))}" if payer_count else "Платящих пользователей пока нет"
        content_comment = f"Контент одобряется с конверсией {_fmt_pct(approval_rate_pct)}" if content_total else "Контента пока нет"
        lottery_comment = f"В Секслото уже вовлечено {_fmt_pct(penetration_pct)} базы, RTP ≈ {_fmt_pct(rtp)}" if total_tickets else "Секслото пока не набрало истории"
        retention_comment = f"Липкость аудитории DAU/MAU = {_fmt_pct(sticky_pct)}; по рефералке пришло {_fmt_pct(referred_share_pct)} базы" if total_users else "Недостаточно данных для удержания"

        activity_dates = await _collect_activity_dates(session)
        activity_timestamps_30 = await _collect_activity_timestamps(session, now - timedelta(days=30))
        activity_heatmap = _build_hour_weekday_heatmap(activity_timestamps_30)
        cohort_users = (await session.execute(select(User.id, User.created_at).order_by(User.created_at.asc()))).all()
        cohorts = _build_cohort_retention(cohort_users, activity_dates, now.date())

        all_users = (await session.execute(select(User))).scalars().all()
        all_user_ids = {user.id for user in all_users}
        agreed_ids = {user.id for user in all_users if user.agreed_to_rules}
        nicknamed_ids = {user.id for user in all_users if user.nickname_set and user.display_name}
        referred_user_ids = {user.id for user in all_users if user.referred_by_user_id is not None}
        recent_cutoff = now.date() - timedelta(days=30)
        recent_active_ids = {user_id for user_id, dates in activity_dates.items() if any(day >= recent_cutoff for day in dates)}
        sleeper_ids = all_user_ids - recent_active_ids

        viewer_ids = set((await session.execute(select(func.distinct(VideoView.user_id)))).scalars().all())
        creator_ids = set((await session.execute(select(func.distinct(Video.uploader_user_id)))).scalars().all())
        payer_ids = set((await session.execute(select(func.distinct(Payment.user_id)).where(Payment.status == "paid"))).scalars().all())
        lottery_player_ids = set((await session.execute(select(func.distinct(LotteryTicket.user_id)))).scalars().all())
        ai_user_ids = set((await session.execute(select(func.distinct(KatyaChat.user_id)))).scalars().all())
        upload_count_map = {uid: int(count or 0) for uid, count in (await session.execute(select(Video.uploader_user_id, func.count(Video.id)).group_by(Video.uploader_user_id))).all()}
        referral_count_map = {uid: int(count or 0) for uid, count in (await session.execute(select(User.referred_by_user_id, func.count(User.id)).where(User.referred_by_user_id.is_not(None)).group_by(User.referred_by_user_id))).all()}
        payment_stars_by_user = defaultdict(float)
        for payment in paid_payments:
            payment_stars_by_user[payment.user_id] += float(payment.stars_amount or 0)
        activity_dates_str = {user_id: {str(day) for day in dates} for user_id, dates in activity_dates.items()}
        active_users_daily_series = [float(sum(1 for dates in activity_dates_str.values() if day_label in dates)) for day_label in labels_30]
        vip_share_pct = _safe_div(vip_users * 100, total_users)
        nickname_set_pct = _safe_div(len(nicknamed_ids) * 100, total_users)
        rules_accept_pct = _safe_div(len(agreed_ids) * 100, total_users)
        dormant_30_pct = _safe_div(len(sleeper_ids) * 100, total_users)

        segment_rows = [
            {"label": "Активны за 30 дней", "count": len(recent_active_ids), "share": _safe_div(len(recent_active_ids) * 100, total_users)},
            {"label": "Плательщики", "count": len(payer_ids), "share": _safe_div(len(payer_ids) * 100, total_users)},
            {"label": "Авторы контента", "count": len(creator_ids), "share": _safe_div(len(creator_ids) * 100, total_users)},
            {"label": "Зрители", "count": len(viewer_ids), "share": _safe_div(len(viewer_ids) * 100, total_users)},
            {"label": "Игроки Секслото", "count": len(lottery_player_ids), "share": _safe_div(len(lottery_player_ids) * 100, total_users)},
            {"label": "Пользователи ИИ", "count": len(ai_user_ids), "share": _safe_div(len(ai_user_ids) * 100, total_users)},
            {"label": "Пришедшие по рефералке", "count": len(referred_user_ids), "share": _safe_div(len(referred_user_ids) * 100, total_users)},
            {"label": "Спящие 30+ дней", "count": len(sleeper_ids), "share": _safe_div(len(sleeper_ids) * 100, total_users)},
        ]
        segment_chart = {row["label"]: row["count"] for row in segment_rows if row["count"] > 0}

        funnel_rows = []
        current_ids = set(all_user_ids)
        raw_funnel_steps = [
            ("Регистрация", set(all_user_ids)),
            ("Приняли правила", agreed_ids),
            ("Поставили ник", nicknamed_ids),
            ("Посмотрели контент", viewer_ids),
            ("Сделали оплату", payer_ids),
            ("Купили билет Секслото", lottery_player_ids),
        ]
        previous_count = total_users
        for idx, (label, step_ids) in enumerate(raw_funnel_steps):
            current_ids = set(step_ids) if idx == 0 else current_ids & set(step_ids)
            count = len(current_ids)
            funnel_rows.append({
                "label": label,
                "count": count,
                "step_rate": 100.0 if idx == 0 else _safe_div(count * 100, previous_count),
                "total_rate": _safe_div(count * 100, total_users),
            })
            previous_count = count
        funnel_chart = {row["label"]: row["count"] for row in funnel_rows}

        leader_rows = {
            "balance": _top_user_rows(all_users, lambda candidate: candidate.balance),
            "xp": _top_user_rows(all_users, lambda candidate: candidate.xp),
            "payments": _top_user_rows(all_users, lambda candidate: payment_stars_by_user.get(candidate.id, 0)),
            "uploads": _top_user_rows(all_users, lambda candidate: upload_count_map.get(candidate.id, 0)),
            "referrals": _top_user_rows(all_users, lambda candidate: referral_count_map.get(candidate.id, 0)),
        }

        churn_rows = [
            {"label": "Приняли правила, но не поставили ник", "count": len(agreed_ids - nicknamed_ids), "share": _safe_div(len(agreed_ids - nicknamed_ids) * 100, total_users)},
            {"label": "Поставили ник, но не посмотрели контент", "count": len(nicknamed_ids - viewer_ids), "share": _safe_div(len(nicknamed_ids - viewer_ids) * 100, total_users)},
            {"label": "Поставили ник, но не сделали оплату", "count": len(nicknamed_ids - payer_ids), "share": _safe_div(len(nicknamed_ids - payer_ids) * 100, total_users)},
            {"label": "Смотрели контент, но не оплатили", "count": len(viewer_ids - payer_ids), "share": _safe_div(len(viewer_ids - payer_ids) * 100, total_users)},
            {"label": "Платили, но спят 30+ дней", "count": len(payer_ids & sleeper_ids), "share": _safe_div(len(payer_ids & sleeper_ids) * 100, total_users)},
        ]
        churn_chart = {row["label"]: row["count"] for row in churn_rows if row["count"] > 0}

        biggest_segment = max(segment_rows, key=lambda row: row["count"], default=None)
        weakest_funnel_step = min(funnel_rows[1:], key=lambda row: row["step_rate"], default=None)
        hottest_hour = max(range(24), key=lambda hour: sum(day[hour] for day in activity_heatmap["matrix"])) if activity_heatmap["matrix"] else 0
        hottest_day_index = max(range(7), key=lambda day_index: sum(activity_heatmap["matrix"][day_index])) if activity_heatmap["matrix"] else 0
        segment_comment = (
            f"Самый крупный сегмент сейчас — {biggest_segment['label']} ({_fmt_pct(biggest_segment['share'])} базы)"
            if biggest_segment else
            "Сегменты пока не набрали истории"
        )
        funnel_comment = (
            f"Главный обрыв продуктовой воронки — этап «{weakest_funnel_step['label']}» ({_fmt_pct(weakest_funnel_step['step_rate'])} от предыдущего шага)"
            if weakest_funnel_step else
            "Воронка пока недостаточно заполнена"
        )
        churn_comment = (
            f"Самая крупная зона потерь — «{max(churn_rows, key=lambda row: row['count'])['label']}»"
            if churn_rows else
            "Зоны оттока пока не набрали истории"
        )
        heatmap_comment = f"Пик активности — {activity_heatmap['weekdays'][hottest_day_index]} около {hottest_hour:02d}:00"

    return {
        "generated_at": generated_at,
        "summary": {"total_users": total_users, "active_users": active_users, "vip_users": vip_users, "trusted_uploaders": trusted_uploaders, "avg_balance": avg_balance, "total_balance": total_balance, "paid_stars_total": purchases_paid, "payer_count": payer_count, "payments_count": payments_count, "payment_conversion_pct": _safe_div(payer_count * 100, total_users), "avg_stars_per_payer": _safe_div(purchases_paid, payer_count), "avg_stars_per_payment": _safe_div(purchases_paid, payments_count), "vip_share_pct": vip_share_pct, "nickname_set_pct": nickname_set_pct, "rules_accept_pct": rules_accept_pct, "dormant_30_pct": dormant_30_pct, "new_users": new_users_rows, "dau": dau, "wau": wau, "mau": mau, "sticky_pct": sticky_pct},
        "growth": {"labels_30": labels_30, "registrations_30": reg_series, "cumulative_30": cumulative, "registrations_last_7": registrations_last_7, "registrations_prev_7": registrations_prev_7},
        "content": {"total": content_total, "approved": content_approved, "rejected": content_rejected, "pending": content_pending, "auto_approved": auto_approved, "views": total_views, "avg_rating": round(float(avg_rating or 0), 2), "uploads_30": upload_series, "creators_total": creators_total, "creators_30": creators_30, "viewers_30": viewers_30, "approval_rate_pct": approval_rate_pct, "avg_views_per_upload": avg_views_per_upload, "avg_uploads_per_creator": avg_uploads_per_creator},
        "economy": {"positive_total": positive_total, "negative_total": negative_total, "net_total": net_total, "source_income": source_income, "source_expense": source_expense, "daily_net_30": econ_series, "payment_stars_series_30": [payment_stars_map.get(day, 0.0) for day in labels_30], "payment_count_series_30": [payment_count_map.get(day, 0.0) for day in labels_30], "payment_type_counts": {k: float(v) for k, v in payment_type_counts.items()}, "labels_30": labels_30},
        "lottery": {"rows": lottery_ticket_rows, "rounds_total": rounds_total, "total_tickets": total_tickets, "players_total": players_total, "players_30": players_30, "penetration_pct": penetration_pct, "avg_tickets_per_player": avg_tickets_per_player, "avg_prize_pool": avg_prize_pool, "avg_tickets_per_round": avg_tickets_per_round, "win_counts": win_counts, "rtp": rtp, "ticket_series_30": [ticket_daily_map.get(day, 0.0) for day in labels_30], "player_series_30": [lottery_player_daily_map.get(day, 0.0) for day in labels_30], "prize_pool_series_30": [prize_pool_map.get(day, 0.0) for day in labels_30], "match_distribution": {str(i): float(match_distribution.get(str(i), 0)) for i in range(7)}, "labels_30": labels_30, "spent": lottery_spent, "paid": lottery_paid},
        "retention": {"rows": referred_rows, "retention_pushes": retention_pushes, "weekly_promo_activations": weekly_promo_activations, "referred_total": referred_total, "referred_share_pct": referred_share_pct, "referred_daily_30": [retention_map.get(day, 0.0) for day in labels_30], "active_users_daily_30": active_users_daily_series, "labels_30": labels_30},
        "payments_analytics": {"rows": payment_breakdown_rows, "stars_chart": {row['label']: row['stars_total'] for row in payment_breakdown_rows}, "count_chart": {row['label']: row['count'] for row in payment_breakdown_rows}},
        "leaders": leader_rows,
        "churn": {"rows": churn_rows, "chart": churn_chart},
        "activity_heatmap": activity_heatmap,
        "segments": {"rows": segment_rows, "chart": segment_chart},
        "funnel": {"rows": funnel_rows, "chart": funnel_chart},
        "cohorts": cohorts,
        "insights": {"growth_comment": growth_comment, "monetization_comment": monetization_comment, "content_comment": content_comment, "lottery_comment": lottery_comment, "retention_comment": retention_comment, "segment_comment": segment_comment, "funnel_comment": funnel_comment, "churn_comment": churn_comment, "heatmap_comment": heatmap_comment},
    }



def _user_summary_table(data: dict):
    user = data["user"]
    vip_text = "Да" if data["is_vip"] else "Нет"
    rows = [
        ["Параметр", "Значение"],
        ["Ник", data["display_name"]],
        ["Telegram ID", str(user.telegram_id)],
        ["Дата регистрации", user.created_at.strftime("%d.%m.%Y %H:%M")],
        ["Возраст профиля", f"{data['profile']['registration_days']} дн."],
        ["Текущий баланс", _fmt_dec(user.balance)],
        ["VIP", vip_text],
        ["Уровень / XP", f"{user.level} / {user.xp}"],
        ["Активных дней за 30", str(data["profile"]["active_days_30"])],
        ["Сегмент активности", data["profile"]["activity_segment"]],
    ]
    return rows



def _bot_summary_table(data: dict):
    summary = data["summary"]
    rows = [["Параметр", "Значение"]]
    rows.extend([
        ["Всего пользователей", str(summary["total_users"])],
        ["Активных пользователей", str(summary["active_users"])],
        ["VIP", f"{summary['vip_users']} ({_fmt_pct(summary['vip_share_pct'])})"],
        ["Поставили ник", _fmt_pct(summary["nickname_set_pct"])],
        ["Приняли правила", _fmt_pct(summary["rules_accept_pct"])],
        ["Спящие 30+ дней", _fmt_pct(summary["dormant_30_pct"])],
        ["Доверенные авторы", str(summary["trusted_uploaders"])],
        ["Средний баланс", _fmt_dec(summary["avg_balance"])],
        ["Монет в системе", _fmt_dec(summary["total_balance"])],
        ["Оплачено Stars", _fmt_dec(summary["paid_stars_total"])],
        ["Платящих пользователей", str(summary["payer_count"])],
        ["Платёжная конверсия", _fmt_pct(summary["payment_conversion_pct"])],
        ["DAU / WAU / MAU", f"{summary['dau']} / {summary['wau']} / {summary['mau']}"],
        ["Sticky factor DAU/MAU", _fmt_pct(summary["sticky_pct"])],
    ])
    return rows



def _render_user_report_sync(data: dict, output_path: Path):
    font_name = _register_fonts()
    styles = _build_styles(font_name)
    story = []

    with tempfile.TemporaryDirectory(prefix="user_report_assets_") as tmpdir:
        tmp = Path(tmpdir)
        story.append(Paragraph("1. Сводка и профиль", styles["H1Custom"]))
        story.append(Paragraph("Подробный отчёт по активности, экономике и Секслото", styles["SmallCustom"]))
        story.append(Paragraph(f"Собран: {data['generated_at']}", styles["SmallCustom"]))
        story.append(Spacer(1, 0.25 * cm))
        story.append(_table(_user_summary_table(data), font_name, col_widths=[5 * cm, 10.5 * cm]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(_table([["Платёжная сводка", "Значение"], ["Успешных оплат", str(data["payments"]["count"])], ["Успешных оплат за 30 дней", str(data["payments"]["count_30"])], ["Всего потрачено Stars", _fmt_dec(data["payments"]["stars_total"])], ["Stars за 30 дней", _fmt_dec(data["payments"]["stars_30"])], ["Монет начислено покупками", _fmt_dec(data["payments"]["coins_total"])]] , font_name, col_widths=[7 * cm, 8.5 * cm]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Paragraph("Короткие выводы", styles["H3Custom"]))
        story.append(_bullet(f"Главный паттерн поведения: <b>{data['insights']['dominant']}</b>", styles))
        story.append(_bullet(f"Сегмент активности: <b>{data['insights']['activity_segment']}</b>", styles))
        story.append(_bullet(data['insights']['balance_comment'], styles))
        story.append(_bullet(data['insights']['purchase_comment'], styles))
        story.append(PageBreak())

        story.append(Paragraph("2. Экономика", styles["H2Custom"]))
        eco_table = [["Период", "Заработано", "Потрачено", "Чистый результат", "Средний день"]]
        for row in data["economy_rows"]:
            eco_table.append([row["period"], _fmt_dec(row["earned"]), _fmt_dec(row["spent"]), _fmt_dec(row["net"]), _fmt_dec(row["avg_daily"])])
        story.append(_table(eco_table, font_name, col_widths=[3 * cm, 3 * cm, 3 * cm, 3.5 * cm, 3 * cm]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Image(_chart_line("Динамика баланса за 30 дней", data["balance_labels_30"], data["balance_series_30"], tmp / "balance.png"), width=17 * cm, height=6.5 * cm))
        story.append(Spacer(1, 0.15 * cm))
        story.append(Image(_chart_dual_bar("Доходы и расходы по дням", data["balance_labels_30"], data["income_series_30"], data["expense_series_30"], tmp / "income_expense.png"), width=17 * cm, height=6.5 * cm))
        story.append(Spacer(1, 0.15 * cm))
        if data["source_income"]:
            story.append(Image(_chart_horizontal_bar("Топ источников дохода", data["source_income"], tmp / "income_sources.png", color="#16A34A"), width=17 * cm, height=6 * cm))
            story.append(Spacer(1, 0.15 * cm))
        if data["source_expense"]:
            story.append(Image(_chart_horizontal_bar("Топ источников расходов", data["source_expense"], tmp / "expense_sources.png", color="#DC2626"), width=17 * cm, height=6 * cm))
        if any(data["payments"]["stars_series_30"]):
            story.append(Spacer(1, 0.15 * cm))
            story.append(Image(_chart_line("Stars по покупкам за 30 дней", data["balance_labels_30"], data["payments"]["stars_series_30"], tmp / "payment_stars.png", color="#F59E0B"), width=17 * cm, height=6 * cm))
        if any(data["payments"]["count_series_30"]):
            story.append(Spacer(1, 0.15 * cm))
            story.append(Image(_chart_line("Количество оплат по дням", data["balance_labels_30"], data["payments"]["count_series_30"], tmp / "payment_counts.png", color="#0EA5E9"), width=17 * cm, height=6 * cm))
        if data["payments"]["types"]:
            story.append(Spacer(1, 0.15 * cm))
            story.append(Image(_chart_horizontal_bar("Структура платных покупок", data["payments"]["types"], tmp / "payment_types.png", color="#F97316"), width=17 * cm, height=5.6 * cm))
        story.append(PageBreak())

        content = data["content"]
        story.append(Paragraph("3. Контент и активность", styles["H2Custom"]))
        content_table = [["Метрика", "Значение"], ["Загружено видео", str(content["videos"])], ["Загружено фото", str(content["photos"])], ["Одобрено", str(content["approved"])], ["Отклонено", str(content["rejected"])], ["На модерации", str(content["pending"])], ["Доля одобрения", _fmt_pct(content["approval_rate_pct"])], ["Средний рейтинг", str(content["avg_rating"])], ["Просмотры вашего контента", str(content["own_content_views"])], ["Ваши просмотры", str(content["own_views"])], ["Комментарии", str(content["comments"])], ["Реакции", str(content["reactions"])]]
        story.append(_table(content_table, font_name, col_widths=[7 * cm, 8.5 * cm]))
        story.append(Spacer(1, 0.15 * cm))
        story.append(_table([["Эффективность контента", "Значение"], ["Всего загрузок", str(content["efficiency"]["uploads_total"])], ["Одобрено", _fmt_pct(content["efficiency"]["approved_share_pct"])], ["Просмотров на загрузку", _fmt_dec(content["efficiency"]["views_per_upload"])], ["Просмотров на одобренную загрузку", _fmt_dec(content["efficiency"]["views_per_approved_upload"])]], font_name, col_widths=[7 * cm, 8.5 * cm]))
        story.append(Spacer(1, 0.15 * cm))
        story.append(_bullet(data['insights']['content_comment'], styles))
        story.append(Spacer(1, 0.15 * cm))
        story.append(Image(_chart_stacked("Загрузки по дням", data["balance_labels_30"], data["upload_series"], tmp / "uploads.png"), width=17 * cm, height=6.5 * cm))
        story.append(Spacer(1, 0.15 * cm))
        if data["status_counts"]:
            story.append(Image(_chart_distribution("Статусы загруженного контента", data["status_counts"], tmp / "content_status.png"), width=16 * cm, height=5 * cm))
        if data["action_counts"]:
            story.append(Spacer(1, 0.15 * cm))
            story.append(Image(_chart_horizontal_bar("Активность по типам действий (30 дней)", data["action_counts"], tmp / "actions.png", color="#0EA5E9"), width=17 * cm, height=5.5 * cm))
        if data["activity_mix_30"]:
            story.append(Spacer(1, 0.15 * cm))
            story.append(Image(_chart_horizontal_bar("Микс активности за 30 дней", data["activity_mix_30"], tmp / "activity_mix.png", color="#8B5CF6"), width=17 * cm, height=5.8 * cm))
        story.append(PageBreak())

        lottery = data["lottery"]
        story.append(Paragraph("4. Секслото", styles["H2Custom"]))
        story.append(_table([["Метрика", "Значение"], ["Раундов участия", str(lottery["rounds_played"])], ["Куплено билетов", str(lottery["tickets_total"])], ["Выигрышных билетов (4+)", str(lottery["win_tickets"])], ["Частота выигрыша", _fmt_pct(lottery["win_rate_pct"])], ["Среднее совпадений на билет", _fmt_dec(lottery["avg_matches"])], ["Потрачено всего", _fmt_dec(lottery["spent_total"])], ["Выиграно всего", _fmt_dec(lottery["won_total"])], ["ROI", _fmt_pct(lottery["roi_pct"])]] , font_name, col_widths=[7 * cm, 8.5 * cm]))
        story.append(Spacer(1, 0.15 * cm))
        lot_table = [["Период", "Билетов", "Потрачено", "Выиграно", "Результат"]]
        for row in data["lottery_rows"]:
            lot_table.append([row["period"], str(row["tickets"]), _fmt_dec(row["spent"]), _fmt_dec(row["won"]), _fmt_dec(row["net"])])
        story.append(_table(lot_table, font_name, col_widths=[3 * cm, 2 * cm, 3.5 * cm, 3.5 * cm, 3.5 * cm]))
        if data.get("best_ticket"):
            ticket = data["best_ticket"]
            story.append(Spacer(1, 0.15 * cm))
            story.append(Paragraph(f"Лучший билет: <b>#{ticket.id}</b> — <code>{ticket.numbers}</code>, совпадений: <b>{ticket.matched_count}</b>", styles["BodyCustom"]))
        story.append(Spacer(1, 0.15 * cm))
        story.append(_bullet(data['insights']['lottery_comment'], styles))
        story.append(Spacer(1, 0.15 * cm))
        story.append(Image(_chart_line("Билеты по дням", data["balance_labels_30"], data["ticket_series_30"], tmp / "lottery_tickets.png", color="#F59E0B"), width=17 * cm, height=6 * cm))
        story.append(Spacer(1, 0.15 * cm))
        story.append(Image(_chart_line("Чистый результат Секслото по дням", data["balance_labels_30"], data["lottery_net_series_30"], tmp / "lottery_net.png", color="#7C3AED"), width=17 * cm, height=6 * cm))
        story.append(Spacer(1, 0.15 * cm))
        story.append(Image(_chart_distribution("Распределение совпадений", data["match_distribution"], tmp / "lottery_dist.png"), width=16 * cm, height=5 * cm))
        story.append(PageBreak())

        ref = data["referrals"]
        story.append(Paragraph("5. Рефералы", styles["H2Custom"]))
        story.append(_table([["Метрика", "Значение"], ["Приглашено всего", str(ref["total"])], ["Активных рефералов", str(ref["active"])], ["Доля активных", _fmt_pct(ref["activation_rate_pct"])], ["Заработано с рефералов", _fmt_dec(ref["earned_total"])]] , font_name, col_widths=[7 * cm, 8.5 * cm]))
        story.append(Spacer(1, 0.15 * cm))
        story.append(_bullet(data['insights']['referral_comment'], styles))
        ref_period_table = [["Период", "Новых рефералов", "Доход"]]
        for row in ref["rows"]:
            ref_period_table.append([row["period"], str(row["count"]), _fmt_dec(row["income"])])
        story.append(Spacer(1, 0.15 * cm))
        story.append(_table(ref_period_table, font_name, col_widths=[4 * cm, 4 * cm, 4 * cm]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Image(_chart_dual_bar("Рефералы и доход от них (30 дней)", data["referral_labels_30"], data["referral_series_30"], data["referral_income_series_30"], tmp / "referrals.png", left_label="Новые рефералы", right_label="Доход"), width=17 * cm, height=6.5 * cm))
        story.append(PageBreak())

        ai = data["ai"]
        story.append(Paragraph("6. ИИ-общение", styles["H2Custom"]))
        story.append(_table([["Метрика", "Значение"], ["Чатов", str(ai["chat_count"])], ["Сообщений пользователя", str(ai["user_messages"])], ["Ответов ассистента", str(ai["assistant_messages"])], ["Среднее сообщений на чат", _fmt_dec(ai["avg_messages_per_chat"])], ["Средняя стоимость сообщения пользователя", _fmt_dec(ai["avg_cost_per_user_message"])]] , font_name, col_widths=[7 * cm, 8.5 * cm]))
        ai_table = [["Период", "Сообщений", "Потрачено"]]
        for row in ai["rows"]:
            ai_table.append([row["period"], str(row["messages"]), _fmt_dec(row["spent"])])
        story.append(Spacer(1, 0.15 * cm))
        story.append(_table(ai_table, font_name, col_widths=[4 * cm, 4 * cm, 4 * cm]))
        if ai["character_counts"]:
            story.append(Spacer(1, 0.2 * cm))
            story.append(Image(_chart_horizontal_bar("Активность по персонажам", ai["character_counts"], tmp / "ai_characters.png", color="#EC4899"), width=17 * cm, height=5 * cm))
        if any(ai["daily_series_30"]):
            story.append(Spacer(1, 0.15 * cm))
            story.append(Image(_chart_line("Сообщения по дням", data["balance_labels_30"], ai["daily_series_30"], tmp / "ai_daily.png", color="#EC4899"), width=17 * cm, height=6 * cm))
        story.append(PageBreak())

        story.append(Paragraph("7. Сравнение с базой", styles["H2Custom"]))
        comparison_rows = [["Метрика", "Пользователь", "Среднее", "Медиана", "Позиция"]]
        for row in data["comparison"]["rows"]:
            comparison_rows.append([
                row["label"],
                _fmt_dec(row["value"]),
                _fmt_dec(row["avg"]),
                _fmt_dec(row["median"]),
                f"#{row['rank']} / {row['total']} ({_fmt_pct(row['percentile'])})",
            ])
        story.append(_table(comparison_rows, font_name, col_widths=[4.2 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm, 4.1 * cm]))
        percentile_chart = {row["label"]: row["percentile"] for row in data["comparison"]["rows"]}
        if percentile_chart:
            story.append(Spacer(1, 0.15 * cm))
            story.append(Image(_chart_horizontal_bar("Процентили относительно базы", percentile_chart, tmp / "comparison_percentiles.png", color="#14B8A6"), width=17 * cm, height=5.8 * cm))
        story.append(Spacer(1, 0.2 * cm))
        story.append(_bullet(f"Сильнее всего пользователь выделяется по метрике: <b>{data['comparison']['strongest']}</b>", styles))
        story.append(_bullet(f"Слабее всего относительно базы выглядит метрика: <b>{data['comparison']['weakest']}</b>", styles))
        story.append(_bullet(f"Размер базы для сравнения: <b>{data['comparison']['population']}</b> пользователей", styles))
        story.append(PageBreak())

        story.append(Paragraph("8. Итоговый профиль", styles["H2Custom"]))
        story.append(_bullet(f"Вы больше похожи на: <b>{data['insights']['dominant']}</b>", styles))
        story.append(_bullet(f"Основной источник дохода: <b>{data['insights']['top_income']}</b>", styles))
        story.append(_bullet(f"Основной источник расходов: <b>{data['insights']['top_expense']}</b>", styles))
        story.append(_bullet(data['insights']['balance_comment'], styles))
        story.append(_bullet(data['insights']['purchase_comment'], styles))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Paragraph("Этот отчёт собран автоматически на основе действий пользователя в боте. Он помогает быстро увидеть монетизацию, вклад в контент, вовлечённость и игровые привычки.", styles["BodyCustom"]))
        doc = SimpleDocTemplate(str(output_path), pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.2 * cm, bottomMargin=1.4 * cm)
        footer = lambda canvas, doc: _report_footer(canvas, doc, title="Отчёт по пользователю", generated_at=data["generated_at"], font_name=font_name)
        doc.build(story, onFirstPage=footer, onLaterPages=footer)



def _render_bot_report_sync(data: dict, output_path: Path):
    font_name = _register_fonts()
    styles = _build_styles(font_name)
    story = []

    with tempfile.TemporaryDirectory(prefix="bot_report_assets_") as tmpdir:
        tmp = Path(tmpdir)
        story.append(Paragraph("1. Общая сводка", styles["H1Custom"]))
        story.append(Paragraph("Общая аналитика по пользователям, экономике, контенту и Секслото", styles["SmallCustom"]))
        story.append(Paragraph(f"Собран: {data['generated_at']}", styles["SmallCustom"]))
        story.append(Spacer(1, 0.25 * cm))
        story.append(_table(_bot_summary_table(data), font_name, col_widths=[7 * cm, 8.5 * cm]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(_table([["Монетизация", "Значение"], ["Оплат всего", str(data["summary"]["payments_count"])], ["Средний чек на плательщика (Stars)", _fmt_dec(data["summary"]["avg_stars_per_payer"])], ["Средний чек на оплату (Stars)", _fmt_dec(data["summary"]["avg_stars_per_payment"])]] , font_name, col_widths=[7 * cm, 8.5 * cm]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(_table([["Период", "Новых пользователей"]] + [[row["period"], str(row["count"])] for row in data["summary"]["new_users"]], font_name, col_widths=[5 * cm, 5 * cm]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Paragraph("Ключевые выводы", styles["H3Custom"]))
        story.append(_bullet(data['insights']['growth_comment'], styles))
        story.append(_bullet(data['insights']['monetization_comment'], styles))
        story.append(_bullet(data['insights']['content_comment'], styles))
        story.append(_bullet(data['insights']['lottery_comment'], styles))
        story.append(_bullet(data['insights']['retention_comment'], styles))
        story.append(_bullet(data['insights']['segment_comment'], styles))
        story.append(_bullet(data['insights']['funnel_comment'], styles))
        story.append(_bullet(data['insights']['churn_comment'], styles))
        story.append(_bullet(data['insights']['heatmap_comment'], styles))
        story.append(PageBreak())

        segments = data["segments"]
        funnel = data["funnel"]
        story.append(Paragraph("2. Сегменты и воронка", styles["H2Custom"]))
        segment_table = [["Сегмент", "Пользователей", "Доля базы"]]
        for row in segments["rows"]:
            segment_table.append([row["label"], str(row["count"]), _fmt_pct(row["share"])])
        story.append(_table(segment_table, font_name, col_widths=[7 * cm, 4 * cm, 4 * cm]))
        story.append(Spacer(1, 0.15 * cm))
        story.append(Paragraph("Сегменты пересекаются: один и тот же пользователь может входить сразу в несколько категорий.", styles["SmallCustom"]))
        if segments["chart"]:
            story.append(Spacer(1, 0.15 * cm))
            story.append(Image(_chart_horizontal_bar("Крупные пользовательские сегменты", segments["chart"], tmp / "segments.png", color="#2563EB"), width=17 * cm, height=6.2 * cm))
        story.append(Spacer(1, 0.2 * cm))
        funnel_table = [["Этап", "Пользователей", "От прошлого шага", "От всей базы"]]
        for row in funnel["rows"]:
            funnel_table.append([row["label"], str(row["count"]), _fmt_pct(row["step_rate"]), _fmt_pct(row["total_rate"])])
        story.append(_table(funnel_table, font_name, col_widths=[6 * cm, 3 * cm, 3.2 * cm, 3.2 * cm]))
        if funnel["chart"]:
            story.append(Spacer(1, 0.15 * cm))
            story.append(Image(_chart_horizontal_bar("Базовая продуктовая воронка", funnel["chart"], tmp / "funnel.png", color="#7C3AED"), width=17 * cm, height=5.8 * cm))
        story.append(PageBreak())

        story.append(Paragraph("3. Рост аудитории", styles["H2Custom"]))
        story.append(_table([["Метрика", "Значение"], ["Регистраций за последние 7 дней", str(data["growth"]["registrations_last_7"])], ["Регистраций за предыдущие 7 дней", str(data["growth"]["registrations_prev_7"])]] , font_name, col_widths=[7 * cm, 8.5 * cm]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Image(_chart_dual_bar("Новые пользователи и размер базы (30 дней)", data["growth"]["labels_30"], data["growth"]["registrations_30"], data["growth"]["cumulative_30"], tmp / "growth.png", left_label="Новые", right_label="Всего"), width=17 * cm, height=6.5 * cm))
        story.append(PageBreak())

        content = data["content"]
        story.append(Paragraph("4. Контент", styles["H2Custom"]))
        story.append(_table([["Метрика", "Значение"], ["Загружено всего", str(content["total"])], ["Одобрено", str(content["approved"])], ["Отклонено", str(content["rejected"])], ["На модерации", str(content["pending"])], ["Автоодобрено", str(content["auto_approved"])], ["Доля одобрения", _fmt_pct(content["approval_rate_pct"])], ["Просмотров", str(content["views"])], ["Средний рейтинг", str(content["avg_rating"])], ["Авторов всего", str(content["creators_total"])], ["Авторов за 30 дней", str(content["creators_30"])], ["Зрителей за 30 дней", str(content["viewers_30"])], ["Средне просмотров на загрузку", _fmt_dec(content["avg_views_per_upload"])], ["Средне загрузок на автора", _fmt_dec(content["avg_uploads_per_creator"])]] , font_name, col_widths=[7 * cm, 8.5 * cm]))
        story.append(Spacer(1, 0.15 * cm))
        story.append(_bullet(data['insights']['content_comment'], styles))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Image(_chart_line("Загрузки по дням", data["growth"]["labels_30"], content["uploads_30"], tmp / "uploads_bot.png", color="#0EA5E9"), width=17 * cm, height=6 * cm))
        status_map = {"Одобрено": float(content["approved"]), "Отклонено": float(content["rejected"]), "На модерации": float(content["pending"]), "Автоодобрено": float(content["auto_approved"])}
        story.append(Spacer(1, 0.15 * cm))
        story.append(Image(_chart_distribution("Статусы контента", status_map, tmp / "content_status_bot.png"), width=16 * cm, height=5 * cm))
        story.append(PageBreak())

        econ = data["economy"]
        story.append(Paragraph("5. Экономика бота", styles["H2Custom"]))
        story.append(_table([["Показатель", "Значение"], ["Сгенерировано монет", _fmt_dec(econ["positive_total"])], ["Сожжено монет", _fmt_dec(econ["negative_total"])], ["Чистый баланс экономики", _fmt_dec(econ["net_total"])]] , font_name, col_widths=[7 * cm, 8.5 * cm]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Image(_chart_line("Чистая динамика экономики (30 дней)", econ["labels_30"], econ["daily_net_30"], tmp / "economy_net.png", color="#10B981"), width=17 * cm, height=6 * cm))
        if econ["source_income"]:
            story.append(Spacer(1, 0.15 * cm))
            story.append(Image(_chart_horizontal_bar("Топ источников притока", econ["source_income"], tmp / "econ_income.png", color="#16A34A"), width=17 * cm, height=6 * cm))
        if econ["source_expense"]:
            story.append(Spacer(1, 0.15 * cm))
            story.append(Image(_chart_horizontal_bar("Топ источников списаний", econ["source_expense"], tmp / "econ_expense.png", color="#DC2626"), width=17 * cm, height=6 * cm))
        if any(econ["payment_stars_series_30"]):
            story.append(Spacer(1, 0.15 * cm))
            story.append(Image(_chart_line("Stars-платежи по дням", econ["labels_30"], econ["payment_stars_series_30"], tmp / "bot_payment_stars.png", color="#F59E0B"), width=17 * cm, height=6 * cm))
        if any(econ["payment_count_series_30"]):
            story.append(Spacer(1, 0.15 * cm))
            story.append(Image(_chart_line("Количество оплат по дням", econ["labels_30"], econ["payment_count_series_30"], tmp / "bot_payment_counts.png", color="#0EA5E9"), width=17 * cm, height=6 * cm))
        if econ["payment_type_counts"]:
            story.append(Spacer(1, 0.15 * cm))
            story.append(Image(_chart_horizontal_bar("Структура платных продуктов", econ["payment_type_counts"], tmp / "bot_payment_types.png", color="#F97316"), width=17 * cm, height=5.8 * cm))
        story.append(PageBreak())

        payments_analytics = data["payments_analytics"]
        story.append(Paragraph("6. Платежи и продукты", styles["H2Custom"]))
        payment_rows = [["Продукт", "Оплат", "Stars", "Монет начислено", "Средний чек"]]
        for row in payments_analytics["rows"]:
            payment_rows.append([row["label"], str(row["count"]), _fmt_dec(row["stars_total"]), _fmt_dec(row["coins_total"]), _fmt_dec(row["avg_stars"])])
        story.append(_table(payment_rows, font_name, col_widths=[4.8 * cm, 2.2 * cm, 2.4 * cm, 3.5 * cm, 2.6 * cm]))
        if payments_analytics["stars_chart"]:
            story.append(Spacer(1, 0.15 * cm))
            story.append(Image(_chart_horizontal_bar("Stars по типам продуктов", payments_analytics["stars_chart"], tmp / "payment_stars_breakdown.png", color="#F97316"), width=17 * cm, height=5.8 * cm))
        if payments_analytics["count_chart"]:
            story.append(Spacer(1, 0.15 * cm))
            story.append(Image(_chart_horizontal_bar("Количество оплат по продуктам", payments_analytics["count_chart"], tmp / "payment_count_breakdown.png", color="#0EA5E9"), width=17 * cm, height=5.8 * cm))
        story.append(PageBreak())

        lottery = data["lottery"]
        story.append(Paragraph("7. Секслото", styles["H2Custom"]))
        story.append(_table([["Метрика", "Значение"], ["Раундов в истории", str(lottery["rounds_total"])], ["Билетов всего", str(lottery["total_tickets"])], ["Игроков всего", str(lottery["players_total"])], ["Игроков за 30 дней", str(lottery["players_30"])], ["Проникновение в базу", _fmt_pct(lottery["penetration_pct"])], ["Среднее билетов на игрока", _fmt_dec(lottery["avg_tickets_per_player"])], ["RTP (грубая оценка)", _fmt_pct(lottery["rtp"])]] , font_name, col_widths=[7 * cm, 8.5 * cm]))
        story.append(Spacer(1, 0.15 * cm))
        story.append(_table([["Период", "Билетов"]] + [[row["period"], str(row["tickets"])] for row in lottery["rows"]], font_name, col_widths=[5 * cm, 5 * cm]))
        story.append(Spacer(1, 0.15 * cm))
        story.append(_table([["Метрика", "Значение"], ["Средний призовой фонд", _fmt_dec(lottery["avg_prize_pool"])], ["Среднее билетов на розыгрыш", _fmt_dec(lottery["avg_tickets_per_round"])], ["Потрачено на билеты", _fmt_dec(lottery["spent"])], ["Выплачено игрокам", _fmt_dec(lottery["paid"])]] , font_name, col_widths=[7 * cm, 8.5 * cm]))
        story.append(Spacer(1, 0.15 * cm))
        story.append(_bullet(data['insights']['lottery_comment'], styles))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Image(_chart_line("Билеты по дням", lottery["labels_30"], lottery["ticket_series_30"], tmp / "lottery_tickets_bot.png", color="#F59E0B"), width=17 * cm, height=6 * cm))
        story.append(Spacer(1, 0.15 * cm))
        story.append(Image(_chart_line("Игроки Секслото по дням", lottery["labels_30"], lottery["player_series_30"], tmp / "lottery_players_bot.png", color="#0EA5E9"), width=17 * cm, height=6 * cm))
        story.append(Spacer(1, 0.15 * cm))
        story.append(Image(_chart_line("Средний призовой фонд по дням", lottery["labels_30"], lottery["prize_pool_series_30"], tmp / "lottery_pool_bot.png", color="#7C3AED"), width=17 * cm, height=6 * cm))
        story.append(Spacer(1, 0.15 * cm))
        story.append(Image(_chart_distribution("Распределение совпадений", lottery["match_distribution"], tmp / "lottery_match_bot.png"), width=16 * cm, height=5 * cm))
        story.append(PageBreak())

        retention = data["retention"]
        cohorts = data["cohorts"]
        story.append(Paragraph("8. Рефералы, удержание и когорты", styles["H2Custom"]))
        story.append(_table([["Показатель", "Значение"], ["Retention push-уведомлений", str(retention["retention_pushes"])], ["Активаций weekly promo", str(retention["weekly_promo_activations"])], ["Пользователей по рефералке", str(retention["referred_total"])], ["Доля реферальной базы", _fmt_pct(retention["referred_share_pct"])], ["Sticky factor DAU/MAU", _fmt_pct(data["summary"]["sticky_pct"])]] , font_name, col_widths=[7 * cm, 8.5 * cm]))
        story.append(Spacer(1, 0.15 * cm))
        story.append(_bullet(data['insights']['retention_comment'], styles))
        story.append(Spacer(1, 0.15 * cm))
        story.append(_table([["Период", "Новых пользователей по рефералке"]] + [[row["period"], str(row["count"])] for row in retention["rows"]], font_name, col_widths=[6 * cm, 6 * cm]))
        story.append(Spacer(1, 0.2 * cm))
        story.append(Image(_chart_line("Новые пользователи по рефералке (30 дней)", retention["labels_30"], retention["referred_daily_30"], tmp / "retention_referrals.png", color="#2563EB"), width=17 * cm, height=6 * cm))
        story.append(Spacer(1, 0.15 * cm))
        story.append(Image(_chart_line("Активные пользователи по дням", retention["labels_30"], retention["active_users_daily_30"], tmp / "active_users_daily.png", color="#10B981"), width=17 * cm, height=6 * cm))
        story.append(Spacer(1, 0.2 * cm))
        story.append(_table([
            ["Когорта", "Удержание", "Вернулось", "Подходящая база"],
            ["D1", _fmt_pct(cohorts["d1"]["rate"]), str(cohorts["d1"]["retained"]), str(cohorts["d1"]["eligible"])],
            ["D7", _fmt_pct(cohorts["d7"]["rate"]), str(cohorts["d7"]["retained"]), str(cohorts["d7"]["eligible"])],
            ["D30", _fmt_pct(cohorts["d30"]["rate"]), str(cohorts["d30"]["retained"]), str(cohorts["d30"]["eligible"])],
        ], font_name, col_widths=[3 * cm, 4 * cm, 4 * cm, 4 * cm]))
        story.append(Spacer(1, 0.15 * cm))
        story.append(Image(_chart_distribution("D1 / D7 / D30 удержание", {"D1": cohorts["d1"]["rate"], "D7": cohorts["d7"]["rate"], "D30": cohorts["d30"]["rate"]}, tmp / "cohorts_overall.png"), width=16 * cm, height=5 * cm))
        if cohorts["weekly_rows"]:
            story.append(Spacer(1, 0.15 * cm))
            weekly_rows_table = [["Когорта", "Размер", "Вернулось на D7", "D7 retention"]]
            for row in cohorts["weekly_rows"]:
                weekly_rows_table.append([row["cohort"], str(row["size"]), str(row["retained_d7"]), _fmt_pct(row["d7_rate"])])
            story.append(_table(weekly_rows_table, font_name, col_widths=[4 * cm, 3 * cm, 4 * cm, 4 * cm]))
            story.append(Spacer(1, 0.15 * cm))
            story.append(Image(_chart_distribution("D7 retention по последним когортам", cohorts["weekly_chart"], tmp / "cohorts_weekly.png"), width=16 * cm, height=5 * cm))
        story.append(PageBreak())

        leaders = data["leaders"]
        story.append(Paragraph("9. Топ-10 пользователей", styles["H2Custom"]))
        leader_sections = [
            ("По балансу", leaders["balance"]),
            ("По XP", leaders["xp"]),
            ("По потраченным Stars", leaders["payments"]),
            ("По загрузкам", leaders["uploads"]),
            ("По рефералам", leaders["referrals"]),
        ]
        for title, rows in leader_sections:
            if not rows:
                continue
            story.append(Paragraph(title, styles["H3Custom"]))
            table_rows = [["#", "Пользователь", "Telegram ID", "Значение"]]
            for idx, row in enumerate(rows, start=1):
                table_rows.append([str(idx), row["name"], str(row["telegram_id"]), _fmt_dec(row["value"])])
            story.append(_table(table_rows, font_name, col_widths=[1 * cm, 7 * cm, 4 * cm, 3.5 * cm]))
            story.append(Spacer(1, 0.12 * cm))
        story.append(PageBreak())

        churn = data["churn"]
        story.append(Paragraph("10. Отток и провалы", styles["H2Custom"]))
        story.append(Paragraph("Здесь показаны зоны, где пользователи доходят до одного шага, но не переходят к следующему важному действию.", styles["SmallCustom"]))
        churn_table = [["Зона риска", "Пользователей", "Доля базы"]]
        for row in churn["rows"]:
            churn_table.append([row["label"], str(row["count"]), _fmt_pct(row["share"])])
        story.append(_table(churn_table, font_name, col_widths=[8.5 * cm, 3 * cm, 3 * cm]))
        story.append(Spacer(1, 0.15 * cm))
        story.append(_bullet(data['insights']['churn_comment'], styles))
        if churn["chart"]:
            story.append(Spacer(1, 0.15 * cm))
            story.append(Image(_chart_horizontal_bar("Крупнейшие зоны продуктового оттока", churn["chart"], tmp / "churn.png", color="#DC2626"), width=17 * cm, height=6.2 * cm))
        story.append(PageBreak())

        heatmap = data["activity_heatmap"]
        story.append(Paragraph("11. Тепловая карта активности", styles["H2Custom"]))
        story.append(Paragraph("Чем ярче ячейка, тем больше действий пользователей в этот день недели и час суток за последние 30 дней.", styles["SmallCustom"]))
        story.append(Spacer(1, 0.15 * cm))
        story.append(_bullet(data['insights']['heatmap_comment'], styles))
        story.append(Spacer(1, 0.15 * cm))
        story.append(Image(_chart_heatmap("Активность по дням недели и часам", heatmap["matrix"], heatmap["hours"], heatmap["weekdays"], tmp / "activity_heatmap.png"), width=18 * cm, height=6.8 * cm))
        doc = SimpleDocTemplate(str(output_path), pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.2 * cm, bottomMargin=1.4 * cm)
        footer = lambda canvas, doc: _report_footer(canvas, doc, title="Отчёт по боту", generated_at=data["generated_at"], font_name=font_name)
        doc.build(story, onFirstPage=footer, onLaterPages=footer)


def _all_users_overview_table(data: dict):
    rows = [["Параметр", "Значение"]]
    rows.extend([
        ["Пользователей в выгрузке", str(data["users_count"])],
        ["VIP-пользователей", str(data["vip_count"])],
        ["С покупками", str(data["payers_count"])],
        ["С загрузками контента", str(data["creators_count"])],
        ["С билетами Секслото", str(data["lottery_players_count"])],
        ["С чатами ИИ", str(data["ai_users_count"])],
    ])
    return rows


def _render_all_users_report_sync(data: dict, output_path: Path):
    font_name = _register_fonts()
    styles = _build_styles(font_name)
    story = []

    story.append(Paragraph("1. Сводка по всем пользователям", styles["H1Custom"]))
    story.append(Paragraph("Сводный PDF-экспорт по всем пользователям бота", styles["SmallCustom"]))
    story.append(Paragraph(f"Собран: {data['generated_at']}", styles["SmallCustom"]))
    story.append(Spacer(1, 0.25 * cm))
    story.append(_table(_all_users_overview_table(data), font_name, col_widths=[7 * cm, 8.5 * cm]))
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(
        "Ниже идут последовательные карточки всех пользователей. Это не общий бот-отчёт, а единый документ с пользовательскими срезами по всей базе.",
        styles["BodyCustom"],
    ))

    for idx, user_data in enumerate(data["users"], start=1):
        story.append(PageBreak())
        user = user_data["user"]
        story.append(Paragraph(f"2.{idx}. Пользователь #{idx}", styles["H2Custom"]))
        story.append(Paragraph(f"{user_data['display_name']} • Telegram ID {user.telegram_id}", styles["SmallCustom"]))
        story.append(Spacer(1, 0.15 * cm))
        story.append(_table(_user_summary_table(user_data), font_name, col_widths=[5 * cm, 10.5 * cm]))
        story.append(Spacer(1, 0.15 * cm))

        content = user_data["content"]
        lottery = user_data["lottery"]
        referrals = user_data["referrals"]
        ai = user_data["ai"]
        comparison = user_data.get("comparison", {})
        economy_30 = next((row for row in user_data["economy_rows"] if row["period"] == "30 дней"), None)
        economy_all = next((row for row in user_data["economy_rows"] if row["period"] == "Всё время"), None)

        details_table = [
            ["Блок", "Метрика", "Значение"],
            ["Платежи", "Успешных оплат", str(user_data["payments"]["count"])],
            ["Платежи", "Потрачено Stars", _fmt_dec(user_data["payments"]["stars_total"])],
            ["Экономика", "Чистый итог за 30 дней", _fmt_dec(economy_30["net"] if economy_30 else 0)],
            ["Экономика", "Чистый итог за всё время", _fmt_dec(economy_all["net"] if economy_all else 0)],
            ["Контент", "Загружено", str(content["videos"] + content["photos"])],
            ["Контент", "Одобрение", _fmt_pct(content["approval_rate_pct"])],
            ["Контент", "Просмотры", str(content["own_views"])],
            ["Секслото", "Билетов", str(lottery["tickets_total"])],
            ["Секслото", "Частота выигрыша", _fmt_pct(lottery["win_rate_pct"])],
            ["Рефералы", "Приглашено", str(referrals["total"])],
            ["Рефералы", "Активных", str(referrals["active"])],
            ["ИИ", "Чатов", str(ai["chat_count"])],
            ["ИИ", "Сообщений пользователя", str(ai["user_messages"])],
        ]
        story.append(_table(details_table, font_name, col_widths=[3.2 * cm, 6 * cm, 6.3 * cm]))
        story.append(Spacer(1, 0.15 * cm))
        story.append(Paragraph("Ключевые выводы", styles["H3Custom"]))
        story.append(_bullet(f"Профиль поведения: <b>{user_data['insights']['dominant']}</b>", styles))
        story.append(_bullet(user_data['insights']['balance_comment'], styles))
        story.append(_bullet(user_data['insights']['content_comment'], styles))
        story.append(_bullet(user_data['insights']['lottery_comment'], styles))
        story.append(_bullet(user_data['insights']['purchase_comment'], styles))
        if comparison:
            story.append(_bullet(f"Сильнее всего выделяется по метрике: <b>{comparison.get('strongest', '—')}</b>", styles))
            story.append(_bullet(f"Слабее всего выглядит метрика: <b>{comparison.get('weakest', '—')}</b>", styles))

    doc = SimpleDocTemplate(str(output_path), pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.2 * cm, bottomMargin=1.4 * cm)
    footer = lambda canvas, doc: _report_footer(canvas, doc, title="Отчёт по всем пользователям", generated_at=data["generated_at"], font_name=font_name)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


async def build_all_users_report_pdf() -> tuple[Path, str]:
    async with async_session() as session:
        users = (await session.execute(select(User).order_by(User.created_at.asc(), User.id.asc()))).scalars().all()
        telegram_ids = [user.telegram_id for user in users]

    reports = []
    for telegram_id in telegram_ids:
        try:
            reports.append(await collect_user_report_data(telegram_id))
        except Exception:
            continue

    data = {
        "generated_at": utc_now().strftime('%d.%m.%Y %H:%M UTC'),
        "users": reports,
        "users_count": len(reports),
        "vip_count": sum(1 for report in reports if report.get("is_vip")),
        "payers_count": sum(1 for report in reports if report.get("payments", {}).get("count", 0) > 0),
        "creators_count": sum(1 for report in reports if (report.get("content", {}).get("videos", 0) + report.get("content", {}).get("photos", 0)) > 0),
        "lottery_players_count": sum(1 for report in reports if report.get("lottery", {}).get("tickets_total", 0) > 0),
        "ai_users_count": sum(1 for report in reports if report.get("ai", {}).get("chat_count", 0) > 0),
    }

    reports_dir = Path(tempfile.gettempdir()) / "video_exchange_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    filename = f"all_users_report_{utc_now().strftime('%Y%m%d_%H%M%S')}.pdf"
    output_path = reports_dir / filename
    await asyncio.to_thread(_render_all_users_report_sync, data, output_path)
    return output_path, filename


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
