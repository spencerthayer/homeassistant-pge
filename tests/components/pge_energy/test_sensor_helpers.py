"""Unit tests for sensor day aggregation helpers and statistic-linked sensors."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock

from homeassistant.components.sensor import SensorStateClass

from custom_components.pge_energy.const import (
    ENTITY_UNIQUE_ENERGY,
    STATISTIC_ID_SUFFIX_CONSUMPTION,
)
from custom_components.pge_energy.models import UsageInterval, UsageResolution
from custom_components.pge_energy.sensor import (
    PGEEnergySensor,
    PGEHourlyEnergySensor,
    _intervals_in_range,
    _sum_cost,
    _sum_kwh,
)
from custom_components.pge_energy.statistics import (
    _build_entity_consumption_metadata,
    _get_statistic_id,
)


def _iv(hour: int, kwh: float, amount: float | None = 0.1, day: int = 23) -> UsageInterval:
    start = datetime(2026, 7, day, hour, 0, 0, tzinfo=UTC)
    return UsageInterval(
        account_key="abc",
        resolution=UsageResolution.HOURLY,
        start=start,
        end=start + timedelta(hours=1),
        kwh=Decimal(str(kwh)),
        amount=Decimal(str(amount)) if amount is not None else None,
        temperature=Decimal("70"),
        usage_status="kWh-Delivered",
        interval_size=900,
        source_timestamp=None,
    )


class TestDayHelpers:
    def test_sum_kwh_and_cost(self):
        intervals = [_iv(0, 1.5, 0.3), _iv(1, 2.0, 0.4), _iv(2, 1.0, None)]
        assert _sum_kwh(intervals) == 4.5
        assert _sum_cost(intervals) == 0.7

    def test_intervals_in_range(self):
        intervals = [_iv(0, 1.0, day=22), _iv(0, 2.0, day=23), _iv(1, 3.0, day=23)]
        start = datetime(2026, 7, 23, 0, 0, 0, tzinfo=UTC)
        end = datetime(2026, 7, 24, 0, 0, 0, tzinfo=UTC)
        day = _intervals_in_range(intervals, start, end)
        assert len(day) == 2
        assert _sum_kwh(day) == 5.0


class TestEntityMetadata:
    def test_entity_consumption_metadata_uses_recorder_source(self):
        meta = _build_entity_consumption_metadata("sensor.pge_1_energy", "PGE Energy")
        assert meta["source"] == "recorder"
        assert meta["statistic_id"] == "sensor.pge_1_energy"
        assert meta["has_sum"] is True
        assert meta["unit_of_measurement"] == "kWh"


class TestStatisticLinkedAttributes:
    def test_energy_sensor_exposes_external_statistic_id(self):
        coordinator = MagicMock()
        coordinator.account_key = "65f4efbe98987963"
        coordinator.account_id = "1122334455"
        coordinator.lifetime_energy_kwh = 1234.5
        coordinator.recent_intervals = []
        sensor = PGEEnergySensor(coordinator, "65f4efbe98987963")
        # entity_id is assigned by HA after add; attribute still lists external id.
        sensor.hass = MagicMock()
        sensor.entity_id = "sensor.pge_1122334455_energy"
        attrs = sensor.extra_state_attributes
        assert attrs["external_statistic_id"] == _get_statistic_id("65f4efbe98987963", STATISTIC_ID_SUFFIX_CONSUMPTION)
        assert attrs["entity_statistic_id"] == "sensor.pge_1122334455_energy"
        assert attrs["account_id"] == "1122334455"
        assert sensor.unique_id.endswith(ENTITY_UNIQUE_ENERGY)
        assert sensor.native_value == 1234.5

    def test_hourly_energy_is_measurement(self):
        coordinator = MagicMock()
        coordinator.recent_intervals = [_iv(5, 2.5)]
        sensor = PGEHourlyEnergySensor(coordinator, "abc")
        assert sensor.native_value == 2.5
        assert sensor.state_class == SensorStateClass.MEASUREMENT
