"""Validate hourly day batches against the PGE local-day contract."""

from __future__ import annotations

from datetime import date, timedelta

from .models import UsageInterval
from .time_util import local_day_bounds, today_local


def clip_hourly_to_local_day(
    day: date,
    intervals: list[UsageInterval],
) -> list[UsageInterval]:
    """Keep intervals whose start lies in [day_start, day_end).

    Live HOURLY day responses include a +1 boundary hour that starts exactly at
    ``day_end`` (next local midnight). Drop that row so it neither fails
    validation nor double-imports when the adjacent day is fetched.
    """
    day_start, day_end = local_day_bounds(day)
    clipped: list[UsageInterval] = []
    for iv in intervals:
        start = iv.start.astimezone(day_start.tzinfo)
        if day_start <= start < day_end:
            clipped.append(iv)
    return clipped


def validate_hourly_day(
    day: date,
    intervals: list[UsageInterval],
    *,
    allow_partial_today: bool = True,
    clip_boundary: bool = True,
) -> tuple[bool, str]:
    """Return (ok_to_complete, reason).

    - Empty closed day → incomplete (not ok_to_complete)
    - Current local day may update but never complete
    - Starts must lie within [day_start, day_end)
    - Starts must be unique after normalization
    - Closed days must be contiguous hourly intervals spanning the local day
      (23/25-hour DST days are handled via local_day_bounds length)
    - When clip_boundary=True (default), the PGE +1 day_end boundary hour is
      removed before validation
    """
    if clip_boundary:
        intervals = clip_hourly_to_local_day(day, intervals)

    is_today = day == today_local()
    day_start, day_end = local_day_bounds(day)

    if not intervals:
        if is_today and allow_partial_today:
            return False, "current_day_empty"
        return False, "empty_closed_day"

    starts = sorted(iv.start.astimezone(day_start.tzinfo) for iv in intervals)
    if len(starts) != len(set(starts)):
        return False, "duplicate_starts"

    for start in starts:
        if start < day_start or start >= day_end:
            return False, "start_outside_local_day"

    if is_today and allow_partial_today:
        return False, "current_day_partial"

    # Contiguity: each successive start must equal previous + 1 hour, and cover
    # the full local day from day_start through the last hour before day_end.
    expected = day_start
    for start in starts:
        if start != expected:
            return False, "gap"
        expected = start + timedelta(hours=1)
    if expected != day_end:
        return False, "gap"

    return True, "complete"


def is_invalid_closed_day(ok_complete: bool, reason: str) -> bool:
    """True when a closed-day response must not advance completion."""
    if ok_complete:
        return False
    return reason not in {"current_day_empty", "current_day_partial"}
