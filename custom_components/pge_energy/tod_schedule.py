"""Offline Time of Day (E-TOU) schedule engine.

Pure functions (no Home Assistant imports) that answer:

- :func:`is_holiday` / :func:`holiday_calendar` — PGE-recognized holidays
  including observed shifts.
- :func:`period_at` — the E-TOU period for a Pacific local date/time.
- :func:`next_transition` — when the current period next changes.
- :func:`rate_for_period` — offline default price for a period.

E-TOU (Oregon residential) weekday windows (all times Pacific):
    off-peak [21:00, 07:00), mid-peak [07:00, 17:00), on-peak [17:00, 21:00).

Off-peak days — Saturday, Sunday, and observed holidays — are off-peak all day.

The E-TOU calendar and default prices are adapted from the MIT-licensed
"PGE Time-of-Day Price" integration by LJspice
(https://github.com/LJspice/PGE-Pricing-HASS) — see the MIT attribution in
``const.py``. All times are Pacific (America/Los_Angeles); callers must pass
Pacific-local ``datetime`` / ``date`` / ``time`` values (see
:mod:`custom_components.pge_energy.time_util`).
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta
from functools import cache

from .const import DEFAULT_TOD_RATES, E_TOU_PERIODS, TodPeriod

# Fixed-date holidays that PGE observes (shifted when they fall on a weekend).
_FIXED_HOLIDAYS: tuple[tuple[int, int], ...] = (
    (1, 1),  # New Year's Day
    (7, 4),  # Independence Day
    (12, 25),  # Christmas Day
)

# Floating holidays: (month, week_index, weekday).  week_index uses Python's
# calendar: 1 = first, -1 = last; weekday 0 = Monday … 6 = Sunday.
_FLOATING_HOLIDAYS: tuple[tuple[int, int, int], ...] = (
    (5, -1, 0),  # Memorial Day — last Monday in May
    (9, 1, 0),  # Labor Day — first Monday in September
    (11, 4, 3),  # Thanksgiving — fourth Thursday in November
)

# Long off-peak runs (e.g. observed holiday + weekend + Monday holiday) can
# span more than four Pacific days before the next period change.
_NEXT_TRANSITION_SCAN_DAYS = 10
_WEEKDAY_WINDOWS: tuple[tuple[time, time, TodPeriod], ...] = (
    (time(0, 0), time(7, 0), TodPeriod.OFF_PEAK),
    (time(7, 0), time(17, 0), TodPeriod.MID_PEAK),
    (time(17, 0), time(21, 0), TodPeriod.ON_PEAK),
    (time(21, 0), time(23, 59, 59), TodPeriod.OFF_PEAK),
)

# Weekend + holiday windows: off-peak all day.
_WEEKEND_WINDOWS: tuple[tuple[time, time, TodPeriod], ...] = ((time(0, 0), time(23, 59, 59), TodPeriod.OFF_PEAK),)


def is_holiday(day: date) -> bool:
    """Return True when *day* is a PGE-recognized holiday (observed date)."""
    if day.weekday() >= 5:
        return False
    return day in holiday_calendar(day.year)


@cache
def holiday_calendar(year: int) -> frozenset[date]:
    """All observed PGE holidays in *year*.

    Fixed-date holidays that fall on Saturday are observed the preceding
    Friday; Sunday holidays are observed the following Monday. The Dec 31
    edge case (next Jan 1 on Saturday) is included, matching LJspice.
    """
    holidays: set[date] = set()

    for month, day_num in _FIXED_HOLIDAYS:
        observed = _observed(date(year, month, day_num))
        if observed.year == year:
            holidays.add(observed)

    for month, week_index, weekday in _FLOATING_HOLIDAYS:
        holidays.add(_nth_weekday(year, month, week_index, weekday))

    # Edge case: next year's Jan 1 on Saturday is observed Dec 31 this year.
    if date(year + 1, 1, 1).weekday() == 5:
        holidays.add(date(year, 12, 31))

    return frozenset(holidays)


def is_off_peak_day(day: date) -> bool:
    """True for Saturday, Sunday, or a PGE holiday (all-day off-peak)."""
    if day.weekday() >= 5:
        return True
    return is_holiday(day)


def period_at(day: date, t: time) -> TodPeriod:
    """E-TOU period for a Pacific-local date/time."""
    windows = _WEEKEND_WINDOWS if is_off_peak_day(day) else _WEEKDAY_WINDOWS
    for start, end, period in windows:
        if start <= t < end:
            return period
    # Fall back to the last window (never returns None for a valid time).
    return windows[-1][2]


def rate_for_period(period: TodPeriod) -> float:
    """Offline default price (USD/kWh) for an E-TOU period."""
    return float(DEFAULT_TOD_RATES.get(period.value, 0.0))


def next_transition(dt: datetime) -> tuple[TodPeriod, datetime]:
    """Next period change strictly after *dt*.

    Returns ``(period, transition_datetime)`` where ``period`` is the period
    that begins at ``transition_datetime``. ``dt`` must be Pacific-local and
    tz-aware.
    """
    if dt.tzinfo is None:
        raise ValueError("next_transition requires a tz-aware Pacific datetime")

    current_period = period_at(dt.date(), dt.time().replace(second=0, microsecond=0))

    # Candidate boundaries: window start times for the next few Pacific days.
    boundaries: list[datetime] = []
    for offset in range(_NEXT_TRANSITION_SCAN_DAYS):
        day = dt.date() + timedelta(days=offset)
        windows = _WEEKEND_WINDOWS if is_off_peak_day(day) else _WEEKDAY_WINDOWS
        for start, _, _ in windows:
            boundary = datetime.combine(day, start, tzinfo=dt.tzinfo)
            if boundary > dt:
                boundaries.append(boundary)

    for boundary in sorted(boundaries):
        boundary_period = period_at(boundary.date(), boundary.time())
        if boundary_period != current_period:
            return boundary_period, boundary

    # Defensive: no transition found within the window — tomorrow midnight.
    tomorrow = dt.date() + timedelta(days=1)
    return period_at(tomorrow, time(0, 0)), datetime.combine(tomorrow, time(0, 0), tzinfo=dt.tzinfo)


# --------------------------------------------------------------------------
# Private helpers
# --------------------------------------------------------------------------


def _observed(day: date) -> date:
    """Shift a fixed-date holiday to its observed day (LJspice rule)."""
    if day.weekday() == 5:  # Saturday → preceding Friday
        return day - timedelta(days=1)
    if day.weekday() == 6:  # Sunday → following Monday
        return day + timedelta(days=1)
    return day


def _nth_weekday(year: int, month: int, nth: int, weekday: int) -> date:
    """Date of the nth (or -1 = last) weekday in a month."""
    monthcal = calendar.Calendar(firstweekday=calendar.SUNDAY).monthdatescalendar(year, month)
    dates = [d for week in monthcal for d in week if d.month == month and d.weekday() == weekday]
    if not dates:
        raise ValueError(f"No weekday {weekday} in {year}-{month}")
    return dates[nth - 1] if nth > 0 else dates[nth]


# Re-export for introspection/tests.
__all__ = [
    "E_TOU_PERIODS",
    "TodPeriod",
    "holiday_calendar",
    "is_holiday",
    "is_off_peak_day",
    "next_transition",
    "period_at",
    "rate_for_period",
]
