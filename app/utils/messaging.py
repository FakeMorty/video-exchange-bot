from datetime import datetime, timezone
import zoneinfo

def format_time_for_user(dt: datetime, user_timezone: str = None) -> str:
    """
    Форматирует время. Если у юзера есть часовой пояс (например Asia/Sakhalin),
    показывает его локальное время. Иначе пишет "через X часов/минут" + МСК.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
        
    now = datetime.now(timezone.utc)
    
    if user_timezone:
        try:
            tz = zoneinfo.ZoneInfo(user_timezone)
            local_dt = dt.astimezone(tz)
            return f"в {local_dt.strftime('%H:%M')} (по вашему времени)"
        except Exception:
            pass

    # Fallback: relative time + MSK
    diff = dt - now
    total_seconds = int(diff.total_seconds())
    
    if total_seconds <= 0:
        return "прямо сейчас"
        
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    
    time_parts = []
    if hours > 0:
        time_parts.append(f"{hours} ч")
    if minutes > 0:
        time_parts.append(f"{minutes} мин")
        
    rel_str = " ".join(time_parts) if time_parts else "меньше минуты"
    
    from datetime import timedelta
    msk_dt = dt + timedelta(hours=3)
    return f"через {rel_str} (в {msk_dt.strftime('%H:%M')} МСК)"
