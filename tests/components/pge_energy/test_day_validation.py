from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from custom_components.pge_energy.day_validation import clip_hourly_to_local_day, validate_hourly_day
from custom_components.pge_energy.models import UsageInterval, UsageResolution
from custom_components.pge_energy.time_util import local_day_bounds, today_local

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "usage"


def _iv(start: datetime, kwh: str = "1.0") -> UsageInterval:
    return UsageInterval(
        account_key="key",
        resolution=UsageResolution.HOURLY,
        start=start,
        end=start + timedelta(hours=1),
        kwh=Decimal(kwh),
        amount=None,
        temperature=None,
        usage_status=None,
        interval_size=None,
        source_timestamp=None,
    )


def _intervals_from_fixture(path: Path) -> tuple[date, list[UsageInterval]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    day = date.fromisoformat(payload["local_day"])
    intervals = [_iv(datetime.fromisoformat(row["start"]), str(row["kwh"])) for row in payload["intervals"]]
    return day, intervals


class TestValidateHourlyDay:
    def test_empty_closed_day(self):
        day = today_local() - timedelta(days=2)
        ok, reason = validate_hourly_day(day, [])
        assert ok is False
        assert reason == "empty_closed_day"

    def test_complete_closed_day(self):
        day = today_local() - timedelta(days=3)
        day_start, _ = local_day_bounds(day)
        intervals = [_iv(day_start + timedelta(hours=h)) for h in range(24)]
        ok, reason = validate_hourly_day(day, intervals)
        assert ok is True
        assert reason == "complete"

    def test_current_day_never_completes(self):
        day = today_local()
        day_start, _ = local_day_bounds(day)
        intervals = [_iv(day_start)]
        ok, reason = validate_hourly_day(day, intervals)
        assert ok is False
        assert reason == "current_day_partial"

    def test_duplicate_starts(self):
        day = today_local() - timedelta(days=4)
        day_start, _ = local_day_bounds(day)
        intervals = [_iv(day_start), _iv(day_start)]
        ok, reason = validate_hourly_day(day, intervals)
        assert ok is False
        assert reason == "duplicate_starts"

    def test_start_outside_day_without_clip(self):
        day = today_local() - timedelta(days=5)
        ok, reason = validate_hourly_day(
            day,
            [_iv(datetime(2010, 1, 1, tzinfo=UTC))],
            clip_boundary=False,
        )
        assert ok is False
        assert reason == "start_outside_local_day"

    def test_gap_incomplete(self):
        day = today_local() - timedelta(days=6)
        day_start, _ = local_day_bounds(day)
        # Missing hour 1
        intervals = [_iv(day_start), _iv(day_start + timedelta(hours=2))]
        ok, reason = validate_hourly_day(day, intervals)
        assert ok is False
        assert reason == "gap"

    def test_complete_with_explicit_null_gap(self):
        day = today_local() - timedelta(days=7)
        day_start, _ = local_day_bounds(day)
        intervals = [_iv(day_start + timedelta(hours=h)) for h in range(24)]
        # Explicit PGE null occupies hour 7 (covers the July-27 generating-account shape).
        null_hour = intervals[7]
        intervals[7] = UsageInterval(
            account_key=null_hour.account_key,
            resolution=null_hour.resolution,
            start=null_hour.start,
            end=null_hour.end,
            kwh=None,
            amount=None,
            temperature=Decimal("60"),
            usage_status="kWh-Delivered",
            interval_size=900,
            source_timestamp=None,
        )
        ok, reason = validate_hourly_day(day, intervals)
        assert ok is True
        assert reason == "complete_with_gap"

    def test_live_25_row_boundary_fixture_completes(self):
        day, intervals = _intervals_from_fixture(FIXTURES / "hourly_day_with_boundary.json")
        assert len(intervals) == 25
        clipped = clip_hourly_to_local_day(day, intervals)
        assert len(clipped) == 24
        ok, reason = validate_hourly_day(day, intervals)
        assert ok is True
        assert reason == "complete"

    def test_adjacent_day_boundary_deduped(self):
        """Shared boundary hour is kept only for the day that owns its start."""
        day_a, intervals_a = _intervals_from_fixture(FIXTURES / "hourly_day_with_boundary.json")
        day_b = day_a + timedelta(days=1)
        day_b_start, day_b_end = local_day_bounds(day_b)
        # Synthesize next-day payload that also includes the shared boundary
        # (start == day_a day_end == day_b day_start) plus the rest of day_b.
        shared = intervals_a[-1]
        day_b_hours = [_iv(day_b_start + timedelta(hours=h)) for h in range(24)]
        # Ensure first hour equals the shared boundary start
        assert shared.start == day_b_start
        combined_b = [shared, *day_b_hours[1:], _iv(day_b_end)]  # +1 next boundary
        clipped_a = clip_hourly_to_local_day(day_a, intervals_a)
        clipped_b = clip_hourly_to_local_day(day_b, combined_b)
        starts_a = {iv.start for iv in clipped_a}
        starts_b = {iv.start for iv in clipped_b}
        assert shared.start not in starts_a
        assert shared.start in starts_b
        assert len(starts_a & starts_b) == 0
        ok_a, _ = validate_hourly_day(day_a, intervals_a)
        ok_b, _ = validate_hourly_day(day_b, combined_b)
        assert ok_a is True
        assert ok_b is True


class TestDailyShortWindowFixture:
    def test_error_message_shape(self):
        payload = json.loads((FIXTURES / "daily_short_window_error.json").read_text(encoding="utf-8"))
        assert "Something unexpected happened" in payload["error"]


class TestMonthlyFixture:
    def test_latest_twelve_shape(self):
        payload = json.loads((FIXTURES / "monthly_latest_12.json").read_text(encoding="utf-8"))
        assert len(payload["intervals"]) == 12
