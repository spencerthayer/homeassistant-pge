from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from homeassistant.util import dt as dt_util

from custom_components.pge_energy.const import (
    STATISTIC_ID_SUFFIX_CONSUMPTION,
    STATISTIC_ID_SUFFIX_COST,
    STATISTIC_ID_SUFFIX_TEMPERATURE,
)
from custom_components.pge_energy.models import UsageInterval, UsageResolution
from custom_components.pge_energy.statistics import (
    _async_mirror_entity_statistics,
    _build_cost_metadata,
    _build_cost_statistics,
    _build_entity_consumption_metadata,
    _build_entity_temperature_metadata,
    _build_incremental_statistics,
    _build_statistics,
    _build_temperature_metadata,
    _build_temperature_statistics,
    _get_statistic_id,
    _recalculate_sums,
)


def _make_interval(
    start_hour: int,
    kwh: float,
    amount: float | None = None,
    day: int = 1,
    month: int = 7,
    temperature: float | None = None,
) -> UsageInterval:
    start = datetime(2025, month, day, start_hour, 0, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)
    return UsageInterval(
        account_key="test_key",
        resolution=UsageResolution.HOURLY,
        start=start,
        end=end,
        kwh=Decimal(str(kwh)),
        amount=Decimal(str(amount)) if amount is not None else None,
        temperature=Decimal(str(temperature)) if temperature is not None else None,
        usage_status="kWh-Delivered",
        interval_size=900,
        source_timestamp=None,
    )


class TestStatisticId:
    def test_consumption_id(self):
        sid = _get_statistic_id("abc123", STATISTIC_ID_SUFFIX_CONSUMPTION)
        assert sid == "pge_energy:abc123_consumption"

    def test_cost_id(self):
        sid = _get_statistic_id("abc123", STATISTIC_ID_SUFFIX_COST)
        assert sid == "pge_energy:abc123_cost"

    def test_temperature_id(self):
        sid = _get_statistic_id("abc123", STATISTIC_ID_SUFFIX_TEMPERATURE)
        assert sid == "pge_energy:abc123_temperature"


class TestSumRecalculation:
    def test_basic_sums(self):
        stats = [
            {"start": datetime(2025, 1, 1), "state": 10.0, "sum": 0.0},
            {"start": datetime(2025, 1, 2), "state": 20.0, "sum": 0.0},
            {"start": datetime(2025, 1, 3), "state": 15.0, "sum": 0.0},
        ]
        _recalculate_sums(stats)
        assert stats[0]["sum"] == 10.0
        assert stats[1]["sum"] == 30.0
        assert stats[2]["sum"] == 45.0

    def test_empty_stats(self):
        stats = []
        _recalculate_sums(stats)
        assert stats == []


class TestBuildStatistics:
    def test_basic(self):
        intervals = [
            _make_interval(0, 1.5, 0.29, day=1),
            _make_interval(1, 2.0, 0.40, day=1),
        ]
        stats = _build_statistics(intervals)
        assert len(stats) == 2
        assert stats[0]["state"] == 1.5
        assert stats[1]["state"] == 2.0
        assert stats[1]["sum"] == 3.5

    def test_signed_export_splits_to_non_negative_import(self):
        from custom_components.pge_energy.statistics import _build_return_statistics

        intervals = [
            _make_interval(0, 1.0, 0.20, day=1),
            _make_interval(1, -2.5, -0.50, day=1),
        ]
        cons = _build_statistics(intervals)
        ret = _build_return_statistics(intervals)
        assert cons[0]["state"] == 1.0
        assert cons[1]["state"] == 0.0
        assert len(ret) == 1
        assert ret[0]["state"] == 2.5

    def test_sorted_by_start(self):
        intervals = [
            _make_interval(2, 3.0, 0.60, day=1),
            _make_interval(0, 1.0, 0.20, day=1),
            _make_interval(1, 2.0, 0.40, day=1),
        ]
        stats = _build_statistics(intervals)
        assert stats[0]["state"] == 1.0
        assert stats[1]["state"] == 2.0
        assert stats[2]["state"] == 3.0


class TestCostStatistics:
    def test_with_costs(self):
        intervals = [
            _make_interval(0, 1.5, 0.29, day=1),
            _make_interval(1, 2.0, 0.40, day=1),
        ]
        stats = _build_cost_statistics(intervals)
        assert len(stats) == 2
        assert stats[0]["state"] == 0.29
        assert stats[1]["state"] == 0.40

    def test_without_costs(self):
        intervals = [
            _make_interval(0, 1.5, None, day=1),
        ]
        stats = _build_cost_statistics(intervals)
        assert len(stats) == 0


class TestTemperatureStatistics:
    def test_with_temperatures(self):
        intervals = [
            _make_interval(0, 1.5, 0.29, day=1, temperature=67),
            _make_interval(1, 2.0, 0.40, day=1, temperature=68.5),
            _make_interval(2, 1.0, 0.20, day=1, temperature=None),
        ]
        stats = _build_temperature_statistics(intervals)
        assert len(stats) == 2
        assert stats[0]["mean"] == 67.0
        assert stats[0]["state"] == 67.0
        assert stats[0]["sum"] is None
        assert stats[1]["mean"] == 68.5

    def test_temperature_metadata(self):
        meta = _build_temperature_metadata("abc123", "1122334455")
        assert meta["statistic_id"] == "pge_energy:abc123_temperature"
        assert meta["has_mean"] is True
        assert meta["has_sum"] is False
        assert meta["unit_class"] == "temperature"
        assert meta["unit_of_measurement"] == "°F"
        assert "temperature" in meta["name"].lower() or "PGE" in meta["name"]
        # Cost metadata stays sum-based for contrast.
        cost = _build_cost_metadata("abc123", "1122334455")
        assert cost["has_sum"] is True

    def test_entity_mirror_metadata(self):
        energy = _build_entity_consumption_metadata("sensor.pge_x_energy", "PGE energy")
        assert energy["source"] == "recorder"
        assert energy["statistic_id"] == "sensor.pge_x_energy"
        temp = _build_entity_temperature_metadata("sensor.pge_x_outdoor_temperature", "PGE temperature")
        assert temp["has_mean"] is True
        assert temp["has_sum"] is False


class TestIncrementalStatistics:
    def test_with_baseline(self):
        intervals = [
            _make_interval(0, 10.0, day=1),
            _make_interval(1, 20.0, day=1),
        ]
        stats = _build_incremental_statistics(intervals, 100.0)
        assert stats[0]["sum"] == 110.0
        assert stats[1]["sum"] == 130.0

    def test_cost_mode(self):
        intervals = [
            _make_interval(0, 10.0, 2.50, day=1),
            _make_interval(1, 20.0, 5.00, day=1),
        ]
        stats = _build_incremental_statistics(intervals, 0.0, use_cost=True)
        assert stats[0]["state"] == 2.50
        assert stats[1]["state"] == 5.00
        assert stats[1]["sum"] == 7.50


class TestMirrorEntityStatisticsCompileCutoff:
    def _mirror(self, import_mock, stats):
        _async_mirror_entity_statistics(
            MagicMock(),
            account_key="abc123",
            unique_suffix="energy",
            entity_metadata=MagicMock(),
            stats=stats,
        )
        return import_mock.call_args[0][2] if import_mock.call_count else None

    def test_skips_unfinalized_hours(self):
        """Only rows at least two hours past the current hour are mirrored.

        HA Core's compile_statistics finalizes hour H during the 5-min slot at
        H+55; a mirror row written earlier collides with its plain INSERT on
        UNIQUE(metadata_id, start_ts).
        """
        now = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        stats = [
            {"start": now, "state": 1.0, "sum": 1.0},
            {"start": now - timedelta(hours=1), "state": 2.0, "sum": 3.0},
            {"start": now - timedelta(hours=2), "state": 3.0, "sum": 6.0},
            {"start": now - timedelta(hours=3), "state": 4.0, "sum": 10.0},
            {"start": now - timedelta(hours=4), "state": 5.0, "sum": 15.0},
        ]
        with (
            patch(
                "custom_components.pge_energy.statistics.async_resolve_sensor_entity_id",
                return_value="sensor.pge_x_energy",
            ),
            patch("custom_components.pge_energy.statistics.ha_async_import_statistics") as import_mock,
        ):
            mirrored = self._mirror(import_mock, stats)
        assert [s["start"] for s in mirrored] == [now - timedelta(hours=3), now - timedelta(hours=4)]

    def test_all_new_rows_skipped_without_import(self):
        now = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        stats = [
            {"start": now, "state": 1.0, "sum": 1.0},
            {"start": now - timedelta(hours=1), "state": 2.0, "sum": 3.0},
        ]
        with (
            patch(
                "custom_components.pge_energy.statistics.async_resolve_sensor_entity_id",
                return_value="sensor.pge_x_energy",
            ),
            patch("custom_components.pge_energy.statistics.ha_async_import_statistics") as import_mock,
        ):
            self._mirror(import_mock, stats)
        import_mock.assert_not_called()

    def test_older_rows_still_mirrored(self):
        now = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        stats = [{"start": now - timedelta(hours=5), "state": 6.0, "sum": 21.0}]
        with (
            patch(
                "custom_components.pge_energy.statistics.async_resolve_sensor_entity_id",
                return_value="sensor.pge_x_energy",
            ),
            patch("custom_components.pge_energy.statistics.ha_async_import_statistics") as import_mock,
        ):
            mirrored = self._mirror(import_mock, stats)
        assert mirrored == stats
