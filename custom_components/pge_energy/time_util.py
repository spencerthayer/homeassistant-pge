from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

PGE_TZ = ZoneInfo("America/Los_Angeles")


def local_day_bounds(day: date) -> tuple[datetime, datetime]:
    """Return [start, end) UTC bounds for a PGE-local calendar day."""
    start_local = datetime(day.year, day.month, day.day, 0, 0, 0, tzinfo=PGE_TZ)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def iter_local_days(start: datetime, end: datetime) -> list[date]:
    """Return PGE-local calendar dates from start through end (inclusive by local date)."""
    start_day = start.astimezone(PGE_TZ).date()
    end_day = end.astimezone(PGE_TZ).date()
    if end_day < start_day:
        return []
    days: list[date] = []
    current = start_day
    while current <= end_day:
        days.append(current)
        current = current + timedelta(days=1)
    return days


def today_local() -> date:
    return datetime.now(PGE_TZ).date()
