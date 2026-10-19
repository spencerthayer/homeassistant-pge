from __future__ import annotations

from datetime import UTC, datetime

from custom_components.pge_energy.statistics import (
    _as_utc_datetime,
    _build_compensation_metadata,
    _build_consumption_metadata,
    _build_cost_metadata,
    _build_return_metadata,
    _entity_statistic_name,
)
from custom_components.pge_energy.time_util import iter_local_days, local_day_bounds


class TestAsUtcDatetime:
    def test_unix_float(self):
        dt = _as_utc_datetime(1751328000.0)  # 2025-07-01 00:00 UTC
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt == datetime.fromtimestamp(1751328000.0, tz=UTC)

    def test_datetime_naive(self):
        dt = _as_utc_datetime(datetime(2025, 7, 1, 0, 0, 0))
        assert dt == datetime(2025, 7, 1, 0, 0, 0, tzinfo=UTC)

    def test_compare_safe(self):
        last_start = _as_utc_datetime(1751328000.0)
        iv_start = datetime(2025, 7, 1, 1, 0, 0, tzinfo=UTC)
        assert iv_start > last_start


class TestLocalDays:
    def test_bounds(self):
        start, end = local_day_bounds(datetime(2025, 7, 1).date())
        assert start.tzinfo is not None
        assert (end - start).total_seconds() in (23 * 3600, 24 * 3600, 25 * 3600)

    def test_iter(self):
        start = datetime(2025, 7, 1, 12, 0, tzinfo=UTC)
        end = datetime(2025, 7, 3, 12, 0, tzinfo=UTC)
        days = iter_local_days(start, end)
        assert len(days) >= 2


class TestStatisticDisplayNames:
    def test_energy_source_uses_account_number(self):
        meta = _build_consumption_metadata("abc123key", account_id="1071234567")
        assert meta["name"] == "PGE 1071234567 grid consumption"
        assert _entity_statistic_name() == "Lifetime import"

    def test_cost_source_uses_account_number(self):
        meta = _build_cost_metadata("abc123key", account_id="1071234567")
        assert meta["name"] == "PGE 1071234567 energy cost"
        assert _entity_statistic_name(cost=True) == "Lifetime cost"

    def test_return_and_compensation_names(self):
        account_id = "1071234567"
        key = "abc123key"
        assert _build_return_metadata(key, account_id=account_id)["name"] == "PGE 1071234567 return to grid"
        assert _entity_statistic_name(return_energy=True) == "Lifetime export"
        assert _build_compensation_metadata(key, account_id=account_id)["name"] == "PGE 1071234567 export compensation"
        assert _entity_statistic_name(compensation=True) == "Lifetime compensation"
