from __future__ import annotations

from datetime import UTC, datetime

from custom_components.pge_energy.api import _parse_hourly_timestamp
from custom_components.pge_energy.time_util import local_day_bounds


class TestDSTBounds:
    def test_spring_forward_day_length(self):
        # 2025-03-09 Pacific spring forward
        start, end = local_day_bounds(datetime(2025, 3, 9).date())
        assert (end - start).total_seconds() == 23 * 3600

    def test_fall_back_day_length(self):
        # 2025-11-02 Pacific fall back
        start, end = local_day_bounds(datetime(2025, 11, 2).date())
        assert (end - start).total_seconds() == 25 * 3600

    def test_parse_spring_forward_morning(self):
        # 02:00 local does not exist; zoneinfo may fold — document via parse of 03:00
        ts = _parse_hourly_timestamp("09-MAR-2025 03:00:00")
        assert ts.tzinfo == UTC
        assert ts.hour in (10, 11)  # PDT UTC offset
