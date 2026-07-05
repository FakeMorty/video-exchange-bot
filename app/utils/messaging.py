from datetime import datetime, timezone, timedelta
import zoneinfo


def _humanize_relative_time(target_dt: datetime) -> str:
    now = datetime.now(timezone.utc)
    diff = target_dt - now
    total_seconds = int(diff.total_seconds())
    if total_seconds <= 0:
        return "прямо сейчас"

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    parts: list[str] = []
    if hours > 0:
        parts.append(f"{hours} ч")
    if minutes > 0:
        parts.append(f"{minutes} мин")
    return "через " + (" ".join(parts) if parts else "меньше минуты")


def format_time_for_user(dt: datetime, user_timezone: str = None) -> str:
    """
    Форматирует время розыгрыша/события в понятный человеку вид.

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
            return (
                f"{relative} "
                f"(ровно в {local_dt.strftime('%H:%M')} по твоему времени / "
                f"{msk_dt.strftime('%H:%M')} МСК)"
            )
        except Exception:
            pass

    return f"{relative} (ровно в {msk_dt.strftime('%H:%M')} МСК)"
