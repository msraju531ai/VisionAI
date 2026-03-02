import datetime


def now_utc() -> datetime.datetime:
    return datetime.datetime.utcnow()


def start_of_today() -> datetime.datetime:
    now = datetime.datetime.utcnow()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def hours_ago(hours: int) -> datetime.datetime:
    return datetime.datetime.utcnow() - datetime.timedelta(hours=hours)


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    return f"{seconds / 3600:.1f}h"
