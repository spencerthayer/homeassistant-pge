from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from custom_components.pge_energy.tod_schedule import (
    TodPeriod,
    holiday_calendar,
    is_holiday,
    is_off_peak_day,
    next_transition,
    period_at,
    rate_for_period,
)

_PACIFIC = ZoneInfo("America/Los_Angeles")


def _pacific(dt: datetime) -> datetime:
    return dt.replace(tzinfo=_PACIFIC)


class TestWeekdaySchedule:
    def test_weekday_windows(self):
        day = date(2026, 8, 3)  # Monday, not a holiday
        assert period_at(day, time(0, 0)) is TodPeriod.OFF_PEAK
        assert period_at(day, time(6, 59)) is TodPeriod.OFF_PEAK
        assert period_at(day, time(7, 0)) is TodPeriod.MID_PEAK
        assert period_at(day, time(16, 59)) is TodPeriod.MID_PEAK
        assert period_at(day, time(17, 0)) is TodPeriod.ON_PEAK
        assert period_at(day, time(20, 59)) is TodPeriod.ON_PEAK
        assert period_at(day, time(21, 0)) is TodPeriod.OFF_PEAK
        assert period_at(day, time(23, 59)) is TodPeriod.OFF_PEAK

    def test_weekend_all_day_off_peak(self):
        for day in (date(2026, 8, 8), date(2026, 8, 9)):  # Sat, Sun
            for hour in (0, 6, 12, 18, 23):
                assert period_at(day, time(hour, 30)) is TodPeriod.OFF_PEAK


class TestHolidays:
    def test_fixed_holiday_unshifted(self):
        # 2026-12-25 is a Friday → unshifted.
        assert is_holiday(date(2026, 12, 25))
        assert not is_holiday(date(2026, 12, 24))
        assert not is_holiday(date(2026, 12, 26))

    def test_saturday_holiday_observed_friday(self):
        # 2026-07-04 is a Saturday → observed Friday 2026-07-03.
        assert is_holiday(date(2026, 7, 3))
        assert not is_holiday(date(2026, 7, 4))  # weekend itself never "holiday"

    def test_sunday_holiday_observed_monday(self):
        # 2027-07-04 is a Sunday → observed Monday 2027-07-05.
        assert is_holiday(date(2027, 7, 5))
        assert not is_holiday(date(2027, 7, 4))

    def test_floating_holidays(self):
        # Thanksgiving 2026 = Nov 26 (4th Thursday).
        assert is_holiday(date(2026, 11, 26))
        # Memorial Day 2026 = May 25 (last Monday).
        assert is_holiday(date(2026, 5, 25))
        # Labor Day 2026 = Sep 7 (first Monday).
        assert is_holiday(date(2026, 9, 7))

    def test_dec_31_edge_case(self):
        # 2026: next Jan 1 (2027) is a Friday → no Dec 31 edge.
        assert not is_holiday(date(2026, 12, 31))
        # 2021: Jan 1 2022 was a Saturday → Dec 31 2021 observed.
        assert is_holiday(date(2021, 12, 31))

    def test_holiday_calendar_complete(self):
        cal = holiday_calendar(2026)
        # 6 dates: 2 unshifted fixed (NYD, Christmas) + 1 observed (Independence)
        # + 3 floating (Memorial, Labor, Thanksgiving).
        assert len(cal) == 6
        assert date(2026, 1, 1) in cal
        assert date(2026, 7, 3) in cal  # observed Independence Day
        assert date(2026, 12, 25) in cal
        assert date(2026, 11, 26) in cal
        assert all(d.year == 2026 for d in cal)

    def test_weekend_is_not_holiday(self):
        assert is_holiday(date(2026, 8, 8)) is False  # Saturday
        assert is_off_peak_day(date(2026, 8, 8)) is True

    def test_holiday_uses_off_peak_all_day(self):
        # 2026-07-03 observed Independence Day → off-peak all day.
        assert period_at(date(2026, 7, 3), time(12, 0)) is TodPeriod.OFF_PEAK
        assert period_at(date(2026, 7, 3), time(18, 0)) is TodPeriod.OFF_PEAK


class TestNextTransition:
    def test_weekday_mid_peak_to_on_peak(self):
        start = _pacific(datetime(2026, 8, 3, 16, 30))  # Monday
        period, transition = next_transition(start)
        assert period is TodPeriod.ON_PEAK
        assert transition == _pacific(datetime(2026, 8, 3, 17, 0))

    def test_on_peak_to_off_peak(self):
        start = _pacific(datetime(2026, 8, 3, 20, 30))
        period, transition = next_transition(start)
        assert period is TodPeriod.OFF_PEAK
        assert transition == _pacific(datetime(2026, 8, 3, 21, 0))

    def test_overnight_weekday_to_weekend(self):
        # Friday 23:30 is already off-peak; weekend is all-day off-peak, so the
        # next transition is Monday 07:00 mid-peak.
        start = _pacific(datetime(2026, 8, 7, 23, 30))
        period, transition = next_transition(start)
        assert period is TodPeriod.MID_PEAK
        assert transition == _pacific(datetime(2026, 8, 10, 7, 0))

    def test_dst_transition(self):
        # 2026-11-01 01:30 PDT (fall back at 02:00 → 01:00 PST). Weekend day
        # (all off-peak) → next transition is Monday 07:00.
        start = _pacific(datetime(2026, 11, 1, 1, 30))
        period, transition = next_transition(start)
        assert period is TodPeriod.MID_PEAK
        assert transition == _pacific(datetime(2026, 11, 2, 7, 0))

    def test_mid_peak_to_off_peak_after_midnight(self):
        # Monday 06:30 → 07:00 mid-peak.
        start = _pacific(datetime(2026, 8, 3, 6, 30))
        period, transition = next_transition(start)
        assert period is TodPeriod.MID_PEAK
        assert transition == _pacific(datetime(2026, 8, 3, 7, 0))

    def test_requires_tz_aware(self):
        with pytest.raises(ValueError):
            next_transition(datetime(2026, 8, 3, 16, 30))

    def test_long_off_peak_run_holiday_weekend(self):
        # Fri 21:30 off-peak → Sat/Sun/Mon (Memorial) all off-peak → Tue 07:00 mid-peak.
        start = _pacific(datetime(2026, 5, 22, 21, 30))
        period, transition = next_transition(start)
        assert period is TodPeriod.MID_PEAK
        assert transition == _pacific(datetime(2026, 5, 26, 7, 0))


class TestRates:
    def test_e_tou_rate_defaults(self):
        assert rate_for_period(TodPeriod.OFF_PEAK) == 0.0893
        assert rate_for_period(TodPeriod.MID_PEAK) == 0.1670
        assert rate_for_period(TodPeriod.ON_PEAK) == 0.4313

    def test_unknown_period_zero(self):
        assert rate_for_period(TodPeriod.HIGH_PEAK) == 0.0
