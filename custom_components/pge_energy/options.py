"""Config-entry option helpers and history/backfill pure functions."""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any, Never

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_HISTORY_MODE,
    CONF_HISTORY_START_DATE,
    CONF_POLLING_INTERVAL,
    CONF_POLLING_INTERVAL_UNIT,
    CONF_SYNC_LOCAL_TIME,
    DEFAULT_HISTORY_FLOOR,
    DEFAULT_HISTORY_MODE,
    DEFAULT_POLLING_INTERVAL,
    DEFAULT_POLLING_INTERVAL_UNIT,
    DEFAULT_SYNC_LOCAL_HOUR,
    DEFAULT_SYNC_LOCAL_TIME,
    MIN_POLLING_INTERVAL,
    HistoryMode,
    PollingIntervalUnit,
)
from .time_util import PGE_TZ, local_day_bounds, today_local


def get_entry_option(entry: ConfigEntry, key: str, default: Any) -> Any:
    """Read option from entry.options, then entry.data, then default."""
    options = entry.options
    if isinstance(options, Mapping) and key in options:
        return options[key]
    data = entry.data
    if isinstance(data, Mapping) and key in data:
        return data[key]
    return default


def pge_display_name(account_id: str) -> str:
    """User-facing name for config entries, devices, and Energy sources."""
    return f"PGE {account_id}"


def polling_interval_to_minutes(value: int | float, unit: str | PollingIntervalUnit) -> int:
    """Convert a polling value + unit into whole minutes."""
    amount = max(1, int(value))
    unit_enum = PollingIntervalUnit(unit)
    if unit_enum is PollingIntervalUnit.MINUTES:
        minutes = amount
    elif unit_enum is PollingIntervalUnit.HOURS:
        minutes = amount * 60
    elif unit_enum is PollingIntervalUnit.DAYS:
        minutes = amount * 24 * 60
    else:
        _exhaustive: Never = unit_enum
        raise ValueError(f"Unsupported polling unit: {_exhaustive}")
    return max(MIN_POLLING_INTERVAL, minutes)


def minutes_to_polling_display(minutes: int) -> tuple[int, PollingIntervalUnit]:
    """Pick a compact value+unit for the options UI from stored minutes."""
    minutes = max(MIN_POLLING_INTERVAL, int(minutes))
    if minutes % (24 * 60) == 0:
        return minutes // (24 * 60), PollingIntervalUnit.DAYS
    if minutes % 60 == 0:
        return minutes // 60, PollingIntervalUnit.HOURS
    return minutes, PollingIntervalUnit.MINUTES


def resolve_polling_value_unit(entry: ConfigEntry) -> tuple[int, PollingIntervalUnit | None]:
    """Return (value, unit) from entry options/data.

    ``unit is None`` means a legacy minutes-only stored value.
    """
    options = entry.options if isinstance(entry.options, Mapping) else {}
    data = entry.data if isinstance(entry.data, Mapping) else {}
    has_value = CONF_POLLING_INTERVAL in options or CONF_POLLING_INTERVAL in data
    has_unit = CONF_POLLING_INTERVAL_UNIT in options or CONF_POLLING_INTERVAL_UNIT in data
    if not has_value and not has_unit:
        return DEFAULT_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL_UNIT

    raw_value = int(get_entry_option(entry, CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL))
    raw_unit = get_entry_option(entry, CONF_POLLING_INTERVAL_UNIT, None)
    if raw_unit is None:
        return raw_value, None
    return raw_value, PollingIntervalUnit(str(raw_unit))


def resolve_polling_interval_minutes(entry: ConfigEntry) -> int:
    """Coordinator polling interval in minutes from entry options."""
    raw_value, raw_unit = resolve_polling_value_unit(entry)
    if raw_unit is None:
        # Legacy entries stored minutes only (often 60). Keep that meaning.
        return max(MIN_POLLING_INTERVAL, int(raw_value))
    return polling_interval_to_minutes(raw_value, raw_unit)


def parse_sync_local_time(value: str | None) -> tuple[int, int]:
    """Parse ``HH:MM`` / ``HH:MM:SS`` into (hour, minute); fall back to default 00:00."""
    raw = (value or DEFAULT_SYNC_LOCAL_TIME).strip()
    parts = raw.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (TypeError, ValueError, IndexError):
        return DEFAULT_SYNC_LOCAL_HOUR, 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return DEFAULT_SYNC_LOCAL_HOUR, 0
    return hour, minute


def format_sync_local_time(hour: int, minute: int = 0) -> str:
    """Format a Pacific sync clock as ``HH:MM:SS`` for the options Time selector."""
    return f"{max(0, min(23, int(hour))):02d}:{max(0, min(59, int(minute))):02d}:00"


def resolve_sync_local_time(entry: ConfigEntry) -> str:
    """Configured daily sync clock (``HH:MM:SS``) in America/Los_Angeles."""
    raw = get_entry_option(entry, CONF_SYNC_LOCAL_TIME, DEFAULT_SYNC_LOCAL_TIME)
    hour, minute = parse_sync_local_time(str(raw) if raw is not None else None)
    return format_sync_local_time(hour, minute)


def next_day_aligned_sync(
    now: datetime,
    *,
    every_days: int = 1,
    hour: int = DEFAULT_SYNC_LOCAL_HOUR,
    minute: int = 0,
) -> datetime:
    """Next ``hour:minute`` America/Los_Angeles slot at least ``every_days`` after the last slot."""
    every = max(1, int(every_days))
    sync_hour = max(0, min(23, int(hour)))
    sync_minute = max(0, min(59, int(minute)))
    now_local = now.astimezone(PGE_TZ)
    today_slot = now_local.replace(hour=sync_hour, minute=sync_minute, second=0, microsecond=0)
    last_slot = today_slot if now_local >= today_slot else today_slot - timedelta(days=1)
    next_slot = last_slot + timedelta(days=every)
    while next_slot <= now_local:
        next_slot += timedelta(days=every)
    return next_slot.astimezone(UTC)


def next_hour_aligned_sync(
    now: datetime,
    *,
    every_hours: int = 4,
    hour: int = DEFAULT_SYNC_LOCAL_HOUR,
    minute: int = 0,
) -> datetime:
    """Next America/Los_Angeles slot on an ``every_hours`` grid from ``hour:minute``.

    Example: every 4 hours from 00:00 → 00:00, 04:00, 08:00, 12:00, 16:00, 20:00.
    """
    every = max(1, int(every_hours))
    sync_hour = max(0, min(23, int(hour)))
    sync_minute = max(0, min(59, int(minute)))
    now_local = now.astimezone(PGE_TZ)
    slot = now_local.replace(hour=sync_hour, minute=sync_minute, second=0, microsecond=0)
    # If we're before today's anchor, start from yesterday's anchor so the grid
    # still includes any remaining overnight slots (e.g. 20:00 → 00:00).
    if slot > now_local:
        slot -= timedelta(days=1)
    while slot <= now_local:
        slot += timedelta(hours=every)
    return slot.astimezone(UTC)


def resolve_polling_timedelta(
    entry: ConfigEntry,
    *,
    now: datetime | None = None,
) -> timedelta:
    """Delay until the next coordinator poll.

    Hour and day units align to ``sync_local_time`` in America/Los_Angeles
    (default every 4 hours from midnight). Minute units (and legacy unit-less
    values) use a fixed interval with a 15-minute floor.
    """
    when = now or datetime.now(UTC)
    raw_value, raw_unit = resolve_polling_value_unit(entry)
    if raw_unit is None:
        return timedelta(minutes=max(MIN_POLLING_INTERVAL, int(raw_value)))
    hour, minute = parse_sync_local_time(resolve_sync_local_time(entry))
    if raw_unit is PollingIntervalUnit.DAYS:
        target = next_day_aligned_sync(when, every_days=int(raw_value), hour=hour, minute=minute)
        delay = target - when.astimezone(UTC)
        return delay if delay.total_seconds() > 0 else timedelta(minutes=MIN_POLLING_INTERVAL)
    if raw_unit is PollingIntervalUnit.HOURS:
        target = next_hour_aligned_sync(when, every_hours=int(raw_value), hour=hour, minute=minute)
        delay = target - when.astimezone(UTC)
        return delay if delay.total_seconds() > 0 else timedelta(minutes=MIN_POLLING_INTERVAL)
    return timedelta(minutes=polling_interval_to_minutes(raw_value, raw_unit))


def resolve_polling_interval_form_defaults(entry: ConfigEntry) -> tuple[int, str]:
    """Return (value, unit) defaults for the options form."""
    options = entry.options if isinstance(entry.options, Mapping) else {}
    has_value = CONF_POLLING_INTERVAL in options
    has_unit = CONF_POLLING_INTERVAL_UNIT in options
    if not has_value and not has_unit:
        return DEFAULT_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL_UNIT.value

    raw_value = get_entry_option(entry, CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL)
    raw_unit = get_entry_option(entry, CONF_POLLING_INTERVAL_UNIT, None)
    if raw_unit is None:
        value, unit = minutes_to_polling_display(int(raw_value))
        return value, unit.value
    unit = PollingIntervalUnit(str(raw_unit))
    return int(raw_value), unit.value


def resolve_history_start(
    history_mode: str | HistoryMode,
    history_start_date: str | None,
    *,
    floor: date = DEFAULT_HISTORY_FLOOR,
) -> date:
    """Resolve the oldest local calendar day for history sync."""
    mode = HistoryMode(history_mode)
    if mode is HistoryMode.FULL:
        return floor
    if mode is HistoryMode.START_DATE:
        if not history_start_date:
            return floor
        parsed = date.fromisoformat(history_start_date)
        return max(parsed, floor)
    _exhaustive: Never = mode
    raise ValueError(f"Unsupported history mode: {_exhaustive}")


def resolve_history_end(*, today: date | None = None) -> date:
    """Newest closed local day available for history sync (yesterday)."""
    return (today or today_local()) - timedelta(days=1)


def resolve_history_bounds(
    entry: ConfigEntry,
    *,
    today: date | None = None,
    floor: date = DEFAULT_HISTORY_FLOOR,
) -> tuple[date, date]:
    """Return inclusive (start_day, end_day) for history sync from entry options."""
    mode = get_entry_option(entry, CONF_HISTORY_MODE, DEFAULT_HISTORY_MODE)
    start_raw = get_entry_option(entry, CONF_HISTORY_START_DATE, None)
    start = resolve_history_start(mode, start_raw, floor=floor)
    end = resolve_history_end(today=today)
    if start > end:
        return end, end
    return start, end


def history_window_datetimes(start_day: date, end_day: date) -> tuple[datetime, datetime]:
    """UTC datetimes covering [start_day, end_day] inclusive for backfill targets."""
    start_dt, _ = local_day_bounds(start_day)
    _, end_exclusive = local_day_bounds(end_day)
    return start_dt, end_exclusive - timedelta(milliseconds=1)


def compute_hourly_date_range(
    start: date,
    end: date,
    hourly_backfill_days: int,
) -> tuple[date, date] | None:
    """Newest up-to-N closed days within [start, end] inclusive."""
    if start > end or hourly_backfill_days <= 0:
        return None
    span = (end - start).days + 1
    take = min(int(hourly_backfill_days), span)
    hourly_start = end - timedelta(days=take - 1)
    return hourly_start, end


def compute_pre_hourly_date_range(
    start: date,
    end: date,
    hourly_range: tuple[date, date] | None,
) -> tuple[date, date] | None:
    """Days in [start, end] strictly before the hourly window."""
    if hourly_range is None:
        if start <= end:
            return start, end
        return None
    hourly_start, _ = hourly_range
    daily_end = hourly_start - timedelta(days=1)
    if start <= daily_end:
        return start, daily_end
    return None


def iter_month_windows(start: date, end: date) -> list[tuple[date, date]]:
    """Inclusive calendar-month windows clipped to [start, end]."""
    if start > end:
        return []
    windows: list[tuple[date, date]] = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        last_day = monthrange(cursor.year, cursor.month)[1]
        month_end = date(cursor.year, cursor.month, last_day)
        win_start = max(start, cursor)
        win_end = min(end, month_end)
        if win_start <= win_end:
            windows.append((win_start, win_end))
        cursor = date(cursor.year + 1, 1, 1) if cursor.month == 12 else date(cursor.year, cursor.month + 1, 1)
    return windows


def days_covered_by_interval(start: datetime, end: datetime) -> list[date]:
    """Local calendar days covered by [start, end) (or [start, end] if end is midnight-exclusive)."""
    start_day = start.astimezone(PGE_TZ).date()
    end_local = end.astimezone(PGE_TZ)
    # Treat end as exclusive when it lands on midnight; otherwise include that day.
    if end_local.hour == 0 and end_local.minute == 0 and end_local.second == 0 and end_local.microsecond == 0:
        end_day = end_local.date() - timedelta(days=1)
    else:
        end_day = end_local.date()
    if end_day < start_day:
        return [start_day]
    days: list[date] = []
    current = start_day
    while current <= end_day:
        days.append(current)
        current += timedelta(days=1)
    return days


def history_incomplete(
    start_day: date,
    end_day: date,
    completed_local_dates: list[str] | set[str],
) -> bool:
    """True when any closed day in range is missing from completed set."""
    completed = set(completed_local_dates)
    current = start_day
    while current <= end_day:
        if current.isoformat() not in completed:
            return True
        current += timedelta(days=1)
    return False
