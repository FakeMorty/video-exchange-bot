from datetime import datetime, timezone, timedelta
import zoneinfo

from app.i18n import t


def _humanize_relative_time(target_dt: datetime) -> str:
    now = datetime.now(timezone.utc)
    diff = target_dt - now
    total_seconds = int(diff.total_seconds())
    if total_seconds <= 0:
        return t("прямо сейчас")

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    parts: list[str] = []
    if hours > 0:
        parts.append(t("{hours} ч", hours=hours))
    if minutes > 0:
        parts.append(t("{minutes} мин", minutes=minutes))
    if parts:
        return t("через {parts}", parts=" ".join(parts))
    return t("меньше минуты")


def format_time_for_user(dt: datetime, user_timezone: str = None) -> str:
    """
    Форматирует время розыгрыша/события в понятный человеку вид (с переводом).

    Пример:
    - "через 3 ч 15 мин (ровно в 20:00 по твоему времени / 17:00 МСК)"
    - "через 40 мин (ровно в 17:00 МСК)"
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    relative = _humanize_relative_time(dt)
    msk_tz = timezone(timedelta(hours=3))
    msk_dt = dt.astimezone(msk_tz)

    if user_timezone:
        try:
            tz = zoneinfo.ZoneInfo(user_timezone)
            local_dt = dt.astimezone(tz)
            return t(
                "{relative} (ровно в {local} по твоему времени / {msk} МСК)",
                relative=relative,
                local=local_dt.strftime('%H:%M'),
                msk=msk_dt.strftime('%H:%M'),
            )
        except Exception:
            pass

    return t(
        "{relative} (ровно в {msk} МСК)",
        relative=relative,
        msk=msk_dt.strftime('%H:%M'),
    )
