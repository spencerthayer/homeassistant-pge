"""PGE Energy sensors — current values plus attributes linking to statistics."""

from __future__ import annotations

import logging
import zoneinfo
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .billing_models import BillDetails, EnergyTrackerEstimates
from .const import (
    CONF_INCLUDE_BILLING,
    CONF_INCLUDE_DIAGNOSTICS,
    DEFAULT_INCLUDE_BILLING,
    DEFAULT_INCLUDE_DIAGNOSTICS,
    DOMAIN,
    ENTITY_UNIQUE_ACCOUNT_BALANCE,
    ENTITY_UNIQUE_AMOUNT_DUE,
    ENTITY_UNIQUE_BILL_AVG_TEMPERATURE,
    ENTITY_UNIQUE_BILL_CURRENT_CHARGES,
    ENTITY_UNIQUE_BILL_PREVIOUS_BALANCE,
    ENTITY_UNIQUE_BILLING_CYCLE_DAY,
    ENTITY_UNIQUE_BILLING_CYCLE_TOTAL_DAYS,
    ENTITY_UNIQUE_BILLING_LAST_SYNC,
    ENTITY_UNIQUE_COST,
    ENTITY_UNIQUE_CURRENT_BILL_AMOUNT,
    ENTITY_UNIQUE_CURRENT_BILL_END,
    ENTITY_UNIQUE_CURRENT_BILL_KWH,
    ENTITY_UNIQUE_CURRENT_BILL_START,
    ENTITY_UNIQUE_DUE_DATE,
    ENTITY_UNIQUE_ENERGY,
    ENTITY_UNIQUE_EST_CURRENT_CHARGES,
    ENTITY_UNIQUE_EST_NEXT_BILL_MAX,
    ENTITY_UNIQUE_EST_NEXT_BILL_MIN,
    ENTITY_UNIQUE_HOURLY_COST,
    ENTITY_UNIQUE_HOURLY_ENERGY,
    ENTITY_UNIQUE_LAST_PAYMENT_AMOUNT,
    ENTITY_UNIQUE_LAST_PAYMENT_DATE,
    ENTITY_UNIQUE_LIFETIME_BILLED,
    ENTITY_UNIQUE_LIFETIME_PAYMENTS,
    ENTITY_UNIQUE_SYNC_DETAIL,
    ENTITY_UNIQUE_SYNC_ERROR,
    ENTITY_UNIQUE_SYNC_ETA,
    ENTITY_UNIQUE_SYNC_PHASE,
    ENTITY_UNIQUE_SYNC_PROGRESS,
    ENTITY_UNIQUE_SYNC_STATUS,
    ENTITY_UNIQUE_TEMPERATURE,
    ENTITY_UNIQUE_YESTERDAY_COST,
    ENTITY_UNIQUE_YESTERDAY_ENERGY,
    ENTITY_UNIQUE_YTD_PROGRAM_SAVINGS,
    STATISTIC_ID_SUFFIX_ACCOUNT_BALANCE,
    STATISTIC_ID_SUFFIX_AMOUNT_DUE,
    STATISTIC_ID_SUFFIX_BILL_AMOUNT,
    STATISTIC_ID_SUFFIX_BILL_AVG_TEMPERATURE,
    STATISTIC_ID_SUFFIX_CONSUMPTION,
    STATISTIC_ID_SUFFIX_COST,
    STATISTIC_ID_SUFFIX_LAST_PAYMENT_AMOUNT,
    STATISTIC_ID_SUFFIX_PAYMENT_AMOUNT,
    STATISTIC_ID_SUFFIX_TEMPERATURE,
    STATISTIC_ID_SUFFIX_YTD_PROGRAM_SAVINGS,
)
from .coordinator import PGECoordinator
from .entity import PGEBaseEntity
from .models import UsageInterval
from .options import get_entry_option
from .statistics import _get_statistic_id

_LOGGER = logging.getLogger(__name__)

_PGE_TZ = zoneinfo.ZoneInfo("America/Los_Angeles")


def _pacific_day_bounds_utc(day_offset: int = 0) -> tuple[datetime, datetime]:
    """Return [start, end) UTC for a Pacific local calendar day."""
    now_pacific = datetime.now(_PGE_TZ)
    day_start = (now_pacific - timedelta(days=day_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    return day_start.astimezone(UTC), day_end.astimezone(UTC)


def _intervals_in_range(
    intervals: list[UsageInterval],
    start: datetime,
    end: datetime,
) -> list[UsageInterval]:
    return [iv for iv in intervals if start <= iv.start < end]


def _sum_kwh(intervals: list[UsageInterval]) -> float | None:
    if not intervals:
        return None
    return float(sum(iv.kwh for iv in intervals))


def _sum_cost(intervals: list[UsageInterval]) -> float | None:
    costs = [iv.amount for iv in intervals if iv.amount is not None]
    if not costs:
        return None
    return float(sum(costs))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PGECoordinator = hass.data[DOMAIN][entry.entry_id]
    account_key = coordinator.account_key

    entities: list[PGEBaseEntity] = [
        PGEEnergySensor(coordinator, account_key),
        PGECostSensor(coordinator, account_key),
        PGEOutdoorTemperatureSensor(coordinator, account_key),
        PGEHourlyEnergySensor(coordinator, account_key),
        PGEHourlyCostSensor(coordinator, account_key),
        PGECurrentDayEnergySensor(coordinator, account_key),
        PGECurrentDayCostSensor(coordinator, account_key),
        PGEYesterdayEnergySensor(coordinator, account_key),
        PGEYesterdayCostSensor(coordinator, account_key),
        PGELastUpdateSensor(coordinator, account_key),
        PGELatestIntervalSensor(coordinator, account_key),
        PGEDataAgeSensor(coordinator, account_key),
        PGESyncStatusSensor(coordinator, account_key),
        PGESyncPhaseSensor(coordinator, account_key),
        PGESyncProgressSensor(coordinator, account_key),
        PGESyncEtaSensor(coordinator, account_key),
        PGESyncDetailSensor(coordinator, account_key),
        PGESyncErrorSensor(coordinator, account_key),
    ]
    if bool(get_entry_option(entry, CONF_INCLUDE_DIAGNOSTICS, DEFAULT_INCLUDE_DIAGNOSTICS)):
        entities.extend(
            [
                PGEAuthExpirationSensor(coordinator, account_key),
                PGELastApiErrorSensor(coordinator, account_key),
            ]
        )

    if bool(get_entry_option(entry, CONF_INCLUDE_BILLING, DEFAULT_INCLUDE_BILLING)):
        entities.extend(
            [
                PGEAccountBalanceSensor(coordinator, account_key),
                PGEAmountDueSensor(coordinator, account_key),
                PGEDueDateSensor(coordinator, account_key),
                PGELastPaymentAmountSensor(coordinator, account_key),
                PGELastPaymentDateSensor(coordinator, account_key),
                PGECurrentBillAmountSensor(coordinator, account_key),
                PGECurrentBillKwhSensor(coordinator, account_key),
                PGECurrentBillStartSensor(coordinator, account_key),
                PGECurrentBillEndSensor(coordinator, account_key),
                PGEBillPreviousBalanceSensor(coordinator, account_key),
                PGEBillCurrentChargesSensor(coordinator, account_key),
                PGEBillAvgTemperatureSensor(coordinator, account_key),
                PGEYtdProgramSavingsSensor(coordinator, account_key),
                PGELifetimePaymentsSensor(coordinator, account_key),
                PGELifetimeBilledSensor(coordinator, account_key),
                PGEEstCurrentChargesSensor(coordinator, account_key),
                PGEEstNextBillMinSensor(coordinator, account_key),
                PGEEstNextBillMaxSensor(coordinator, account_key),
                PGEBillingCycleDaySensor(coordinator, account_key),
                PGEBillingCycleTotalDaysSensor(coordinator, account_key),
                PGEBillingLastSyncSensor(coordinator, account_key),
            ]
        )

    async_add_entities(entities)


class _StatisticLinkedSensor(PGEBaseEntity, SensorEntity):
    """Sensor that exposes the matching external statistic_id for automations/cards."""

    _statistic_suffix: str
    _attr_unique_id: str

    def __init__(self, coordinator: PGECoordinator, account_key: str, unique_suffix: str) -> None:
        super().__init__(coordinator)
        self._account_key = account_key
        self._attr_unique_id = f"{account_key}_{unique_suffix}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "account_key": self._account_key,
            "external_statistic_id": _get_statistic_id(self._account_key, self._statistic_suffix),
            "entity_statistic_id": self.entity_id,
        }
        if self.coordinator.account_id:
            attrs["account_id"] = self.coordinator.account_id
        latest = self._latest_interval()
        if latest is not None:
            attrs["interval_start"] = latest.start.isoformat()
            attrs["interval_end"] = latest.end.isoformat()
        return attrs

    def _latest_interval(self) -> UsageInterval | None:
        intervals = self.coordinator.recent_intervals
        if not intervals:
            return None
        return max(intervals, key=lambda x: x.end)


class PGEEnergySensor(_StatisticLinkedSensor):
    """Lifetime imported energy (kWh). State is lifetime cumulative sum."""

    _attr_name = "Energy"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _statistic_suffix = STATISTIC_ID_SUFFIX_CONSUMPTION

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator, account_key, ENTITY_UNIQUE_ENERGY)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.lifetime_energy_kwh


class PGECostSensor(_StatisticLinkedSensor):
    """Lifetime imported cost (USD). State is lifetime cumulative sum."""

    _attr_name = "Cost"
    _attr_native_unit_of_measurement = "USD"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _statistic_suffix = STATISTIC_ID_SUFFIX_COST

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator, account_key, ENTITY_UNIQUE_COST)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.lifetime_cost_usd


class PGEOutdoorTemperatureSensor(_StatisticLinkedSensor):
    """Latest PGE-reported outdoor temperature (°F) for an interval."""

    _attr_name = "Outdoor temperature"
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _statistic_suffix = STATISTIC_ID_SUFFIX_TEMPERATURE

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        # Keep legacy unique_id so existing entity registry rows continue to work.
        super().__init__(coordinator, account_key, ENTITY_UNIQUE_TEMPERATURE)

    @property
    def native_value(self) -> float | None:
        intervals = self.coordinator.recent_intervals
        with_temp = [iv for iv in intervals if iv.temperature is not None]
        if not with_temp:
            return self.coordinator.latest_temperature_f
        latest = max(with_temp, key=lambda x: x.end)
        assert latest.temperature is not None
        return float(latest.temperature)


class PGEHourlyEnergySensor(PGEBaseEntity, SensorEntity):
    """Most recent hourly interval energy (kWh for that hour)."""

    _attr_name = "Hourly energy"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_unique_id: str

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._account_key = account_key
        self._attr_unique_id = f"{account_key}_{ENTITY_UNIQUE_HOURLY_ENERGY}"

    @property
    def native_value(self) -> float | None:
        intervals = self.coordinator.recent_intervals
        if not intervals:
            return None
        latest = max(intervals, key=lambda x: x.end)
        return float(latest.kwh)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "account_key": self._account_key,
            "external_statistic_id": _get_statistic_id(self._account_key, STATISTIC_ID_SUFFIX_CONSUMPTION),
            "note": "Point value for the latest hour; full history is on Energy / external stats",
        }


class PGEHourlyCostSensor(PGEBaseEntity, SensorEntity):
    """Most recent hourly interval cost (USD for that hour)."""

    _attr_name = "Hourly cost"
    _attr_native_unit_of_measurement = "USD"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_unique_id: str

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._account_key = account_key
        self._attr_unique_id = f"{account_key}_{ENTITY_UNIQUE_HOURLY_COST}"

    @property
    def native_value(self) -> float | None:
        intervals = self.coordinator.recent_intervals
        with_cost = [iv for iv in intervals if iv.amount is not None]
        if not with_cost:
            return None
        latest = max(with_cost, key=lambda x: x.end)
        assert latest.amount is not None
        return float(latest.amount)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "account_key": self._account_key,
            "external_statistic_id": _get_statistic_id(self._account_key, STATISTIC_ID_SUFFIX_COST),
            "note": "Point value for the latest hour; full history is on Cost / external stats",
        }


class PGECurrentDayEnergySensor(PGEBaseEntity, SensorEntity):
    _attr_name = "Current day energy"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_unique_id: str

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{account_key}_current_day_energy"

    @property
    def native_value(self) -> float | None:
        start, end = _pacific_day_bounds_utc(0)
        return _sum_kwh(_intervals_in_range(self.coordinator.recent_intervals, start, end))


class PGECurrentDayCostSensor(PGEBaseEntity, SensorEntity):
    _attr_name = "Current day cost"
    _attr_native_unit_of_measurement = "USD"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_unique_id: str

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{account_key}_current_day_cost"

    @property
    def native_value(self) -> float | None:
        start, end = _pacific_day_bounds_utc(0)
        return _sum_cost(_intervals_in_range(self.coordinator.recent_intervals, start, end))


class PGEYesterdayEnergySensor(PGEBaseEntity, SensorEntity):
    _attr_name = "Yesterday energy"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_unique_id: str

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{account_key}_{ENTITY_UNIQUE_YESTERDAY_ENERGY}"

    @property
    def native_value(self) -> float | None:
        start, end = _pacific_day_bounds_utc(1)
        return _sum_kwh(_intervals_in_range(self.coordinator.recent_intervals, start, end))


class PGEYesterdayCostSensor(PGEBaseEntity, SensorEntity):
    _attr_name = "Yesterday cost"
    _attr_native_unit_of_measurement = "USD"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_unique_id: str

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{account_key}_{ENTITY_UNIQUE_YESTERDAY_COST}"

    @property
    def native_value(self) -> float | None:
        start, end = _pacific_day_bounds_utc(1)
        return _sum_cost(_intervals_in_range(self.coordinator.recent_intervals, start, end))


class PGELastUpdateSensor(PGEBaseEntity, SensorEntity):
    _attr_name = "Last successful update"
    _attr_unique_id: str
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{account_key}_last_update"

    @property
    def native_value(self) -> datetime | None:
        if self.coordinator.freshness.last_successful_update:
            return self.coordinator.freshness.last_successful_update
        return None


class PGELatestIntervalSensor(PGEBaseEntity, SensorEntity):
    _attr_name = "Latest available interval"
    _attr_unique_id: str
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{account_key}_latest_interval"

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.freshness.newest_interval


class PGEDataAgeSensor(PGEBaseEntity, SensorEntity):
    _attr_name = "Data age"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_unique_id: str

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{account_key}_data_age"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.freshness.data_age_seconds


class PGEAuthExpirationSensor(PGEBaseEntity, SensorEntity):
    _attr_name = "Authentication expiration"
    _attr_unique_id: str
    _attr_entity_registry_enabled_default = False
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{account_key}_auth_expiration"

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.auth_manager.token_expires_at


class PGELastApiErrorSensor(PGEBaseEntity, SensorEntity):
    _attr_name = "Last API error"
    _attr_unique_id: str
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{account_key}_last_api_error"

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> str | None:
        return self.coordinator.freshness.last_api_error


class PGESyncStatusSensor(PGEBaseEntity, SensorEntity):
    _attr_name = "Sync status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{account_key}_{ENTITY_UNIQUE_SYNC_STATUS}"

    @property
    def available(self) -> bool:
        # Always show sync health, including after auth/poll failures.
        return True

    @property
    def native_value(self) -> str:
        return self.coordinator.sync_progress.status


class PGESyncPhaseSensor(PGEBaseEntity, SensorEntity):
    _attr_name = "Sync phase"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{account_key}_{ENTITY_UNIQUE_SYNC_PHASE}"

    @property
    def native_value(self) -> str:
        return self.coordinator.sync_progress.phase


class PGESyncProgressSensor(PGEBaseEntity, SensorEntity):
    _attr_name = "Sync progress"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{account_key}_{ENTITY_UNIQUE_SYNC_PROGRESS}"

    @property
    def native_value(self) -> int:
        return int(self.coordinator.sync_progress.percent)


class PGESyncEtaSensor(PGEBaseEntity, SensorEntity):
    _attr_name = "Sync ETA"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_device_class = SensorDeviceClass.DURATION

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{account_key}_{ENTITY_UNIQUE_SYNC_ETA}"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.sync_progress.eta_seconds


class PGESyncDetailSensor(PGEBaseEntity, SensorEntity):
    _attr_name = "Sync detail"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{account_key}_{ENTITY_UNIQUE_SYNC_DETAIL}"

    @property
    def native_value(self) -> str:
        return self.coordinator.sync_progress.message or "—"


class PGESyncErrorSensor(PGEBaseEntity, SensorEntity):
    _attr_name = "Sync last error"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{account_key}_{ENTITY_UNIQUE_SYNC_ERROR}"

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> str | None:
        return self.coordinator.sync_progress.error


# ---------------------------------------------------------------------------
# Billing / programs sensors (gated on include_billing)
# ---------------------------------------------------------------------------


class _BillingStatSensor(PGEBaseEntity, SensorEntity):
    """Billing sensor that links to its dual-publish external statistic id."""

    _statistic_suffix: str
    _attr_unique_id: str

    def __init__(self, coordinator: PGECoordinator, account_key: str, unique_suffix: str) -> None:
        super().__init__(coordinator)
        self._account_key = account_key
        self._attr_unique_id = f"{account_key}_{unique_suffix}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "account_key": self._account_key,
            "external_statistic_id": _get_statistic_id(self._account_key, self._statistic_suffix),
            "entity_statistic_id": self.entity_id,
        }
        if self.coordinator.account_id:
            attrs["account_id"] = self.coordinator.account_id
        return attrs


def _bill(coordinator: PGECoordinator) -> BillDetails | None:
    snapshot = coordinator.account_snapshot
    return snapshot.bill if snapshot is not None else None


class PGEAccountBalanceSensor(_BillingStatSensor):
    _attr_translation_key = "account_balance"
    _attr_native_unit_of_measurement = "USD"
    _attr_device_class = SensorDeviceClass.MONETARY
    # HA rejects measurement + monetary; balance is a point sample (stats use mean).
    _attr_state_class = None
    _statistic_suffix = STATISTIC_ID_SUFFIX_ACCOUNT_BALANCE

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator, account_key, ENTITY_UNIQUE_ACCOUNT_BALANCE)

    @property
    def native_value(self) -> float | None:
        snapshot = self.coordinator.account_snapshot
        return snapshot.amount_due if snapshot is not None else None


class PGEAmountDueSensor(_BillingStatSensor):
    _attr_translation_key = "amount_due"
    _attr_native_unit_of_measurement = "USD"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = None
    _statistic_suffix = STATISTIC_ID_SUFFIX_AMOUNT_DUE

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator, account_key, ENTITY_UNIQUE_AMOUNT_DUE)

    @property
    def native_value(self) -> float | None:
        snapshot = self.coordinator.account_snapshot
        return snapshot.amount_due if snapshot is not None else None


class PGEDueDateSensor(PGEBaseEntity, SensorEntity):
    _attr_translation_key = "due_date"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_unique_id: str

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{account_key}_{ENTITY_UNIQUE_DUE_DATE}"

    @property
    def native_value(self) -> datetime | None:
        snapshot = self.coordinator.account_snapshot
        return snapshot.due_date if snapshot is not None else None


class PGELastPaymentAmountSensor(_BillingStatSensor):
    _attr_translation_key = "last_payment_amount"
    _attr_native_unit_of_measurement = "USD"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = None
    _statistic_suffix = STATISTIC_ID_SUFFIX_LAST_PAYMENT_AMOUNT

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator, account_key, ENTITY_UNIQUE_LAST_PAYMENT_AMOUNT)

    @property
    def native_value(self) -> float | None:
        snapshot = self.coordinator.account_snapshot
        return snapshot.last_payment_amount if snapshot is not None else None


class PGELastPaymentDateSensor(PGEBaseEntity, SensorEntity):
    _attr_translation_key = "last_payment_date"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_unique_id: str

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{account_key}_{ENTITY_UNIQUE_LAST_PAYMENT_DATE}"

    @property
    def native_value(self) -> datetime | None:
        snapshot = self.coordinator.account_snapshot
        return snapshot.last_payment_date if snapshot is not None else None


class PGECurrentBillAmountSensor(PGEBaseEntity, SensorEntity):
    _attr_translation_key = "current_bill_amount"
    _attr_native_unit_of_measurement = "USD"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = None
    _attr_unique_id: str

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._account_key = account_key
        self._attr_unique_id = f"{account_key}_{ENTITY_UNIQUE_CURRENT_BILL_AMOUNT}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "account_key": self._account_key,
            "external_statistic_id": _get_statistic_id(self._account_key, STATISTIC_ID_SUFFIX_BILL_AMOUNT),
        }

    @property
    def native_value(self) -> float | None:
        bill = _bill(self.coordinator)
        if bill is None:
            return None
        if bill.amount_due is not None:
            return bill.amount_due
        return bill.total_current_charges


class PGECurrentBillKwhSensor(PGEBaseEntity, SensorEntity):
    _attr_translation_key = "current_bill_kwh"
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    # Point sample of the current bill (not a cumulative meter).
    _attr_state_class = None
    _attr_unique_id: str

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{account_key}_{ENTITY_UNIQUE_CURRENT_BILL_KWH}"

    @property
    def native_value(self) -> float | None:
        bill = _bill(self.coordinator)
        return bill.kwh if bill is not None else None


class PGECurrentBillStartSensor(PGEBaseEntity, SensorEntity):
    _attr_translation_key = "current_bill_start"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_unique_id: str

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{account_key}_{ENTITY_UNIQUE_CURRENT_BILL_START}"

    @property
    def native_value(self) -> datetime | None:
        bill = _bill(self.coordinator)
        return bill.period_start if bill is not None else None


class PGECurrentBillEndSensor(PGEBaseEntity, SensorEntity):
    _attr_translation_key = "current_bill_end"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_unique_id: str

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{account_key}_{ENTITY_UNIQUE_CURRENT_BILL_END}"

    @property
    def native_value(self) -> datetime | None:
        bill = _bill(self.coordinator)
        return bill.period_end if bill is not None else None


class PGEBillPreviousBalanceSensor(PGEBaseEntity, SensorEntity):
    _attr_translation_key = "bill_previous_balance"
    _attr_native_unit_of_measurement = "USD"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = None
    _attr_unique_id: str

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{account_key}_{ENTITY_UNIQUE_BILL_PREVIOUS_BALANCE}"

    @property
    def native_value(self) -> float | None:
        bill = _bill(self.coordinator)
        return bill.previous_balance if bill is not None else None


class PGEBillCurrentChargesSensor(PGEBaseEntity, SensorEntity):
    _attr_translation_key = "bill_current_charges"
    _attr_native_unit_of_measurement = "USD"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = None
    _attr_unique_id: str

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{account_key}_{ENTITY_UNIQUE_BILL_CURRENT_CHARGES}"

    @property
    def native_value(self) -> float | None:
        bill = _bill(self.coordinator)
        return bill.total_current_charges if bill is not None else None


class PGEBillAvgTemperatureSensor(_BillingStatSensor):
    _attr_translation_key = "bill_avg_temperature"
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _statistic_suffix = STATISTIC_ID_SUFFIX_BILL_AVG_TEMPERATURE

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator, account_key, ENTITY_UNIQUE_BILL_AVG_TEMPERATURE)

    @property
    def native_value(self) -> float | None:
        bill = _bill(self.coordinator)
        return bill.avg_temperature_f if bill is not None else None


class PGEYtdProgramSavingsSensor(_BillingStatSensor):
    _attr_translation_key = "ytd_program_savings"
    _attr_native_unit_of_measurement = "USD"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = None
    _statistic_suffix = STATISTIC_ID_SUFFIX_YTD_PROGRAM_SAVINGS

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator, account_key, ENTITY_UNIQUE_YTD_PROGRAM_SAVINGS)

    @property
    def native_value(self) -> float | None:
        programs = self.coordinator.programs_snapshot
        return programs.ytd_flex_load_earnings if programs is not None else None


class PGELifetimePaymentsSensor(_BillingStatSensor):
    _attr_translation_key = "lifetime_payments"
    _attr_native_unit_of_measurement = "USD"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _statistic_suffix = STATISTIC_ID_SUFFIX_PAYMENT_AMOUNT

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator, account_key, ENTITY_UNIQUE_LIFETIME_PAYMENTS)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.lifetime_payments_usd


class PGELifetimeBilledSensor(_BillingStatSensor):
    _attr_translation_key = "lifetime_billed"
    _attr_native_unit_of_measurement = "USD"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _statistic_suffix = STATISTIC_ID_SUFFIX_BILL_AMOUNT

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator, account_key, ENTITY_UNIQUE_LIFETIME_BILLED)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.lifetime_billed_usd


def _tracker(coordinator: PGECoordinator) -> EnergyTrackerEstimates | None:
    """Open-cycle estimates; only surfaced once PGE marks details available."""
    estimates = coordinator.tracker_estimates
    if estimates is None or not estimates.details_available:
        return None
    return estimates


class _TrackerEstimateSensor(PGEBaseEntity, SensorEntity):
    """Estimate sensor sourced from the portal Current Use card.

    PGE derives these itself; they intentionally do not reconcile with the
    imported hourly intervals.
    """

    _attr_unique_id: str

    def __init__(self, coordinator: PGECoordinator, account_key: str, unique_suffix: str) -> None:
        super().__init__(coordinator)
        self._account_key = account_key
        self._attr_unique_id = f"{account_key}_{unique_suffix}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {"account_key": self._account_key, "source": "getEnergyTrackerData"}
        estimates = self.coordinator.tracker_estimates
        if estimates is not None:
            attrs["details_available"] = estimates.details_available
            attrs["has_more_than_15_days"] = estimates.has_more_than_15_days
        return attrs


class PGEEstCurrentChargesSensor(_TrackerEstimateSensor):
    _attr_translation_key = "est_current_charges"
    _attr_native_unit_of_measurement = "USD"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = None

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator, account_key, ENTITY_UNIQUE_EST_CURRENT_CHARGES)

    @property
    def native_value(self) -> float | None:
        estimates = _tracker(self.coordinator)
        return estimates.bill_to_date_amount if estimates is not None else None


class PGEEstNextBillMinSensor(_TrackerEstimateSensor):
    _attr_translation_key = "est_next_bill_min"
    _attr_native_unit_of_measurement = "USD"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = None

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator, account_key, ENTITY_UNIQUE_EST_NEXT_BILL_MIN)

    @property
    def native_value(self) -> float | None:
        estimates = _tracker(self.coordinator)
        return estimates.projected_min_amount if estimates is not None else None


class PGEEstNextBillMaxSensor(_TrackerEstimateSensor):
    _attr_translation_key = "est_next_bill_max"
    _attr_native_unit_of_measurement = "USD"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = None

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator, account_key, ENTITY_UNIQUE_EST_NEXT_BILL_MAX)

    @property
    def native_value(self) -> float | None:
        estimates = _tracker(self.coordinator)
        return estimates.projected_max_amount if estimates is not None else None


class PGEBillingCycleDaySensor(_TrackerEstimateSensor):
    _attr_translation_key = "billing_cycle_day"
    _attr_native_unit_of_measurement = "d"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator, account_key, ENTITY_UNIQUE_BILLING_CYCLE_DAY)

    @property
    def native_value(self) -> int | None:
        estimates = _tracker(self.coordinator)
        return estimates.billing_cycle_day if estimates is not None else None


class PGEBillingCycleTotalDaysSensor(_TrackerEstimateSensor):
    _attr_translation_key = "billing_cycle_total_days"
    _attr_native_unit_of_measurement = "d"
    _attr_state_class = None

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator, account_key, ENTITY_UNIQUE_BILLING_CYCLE_TOTAL_DAYS)

    @property
    def native_value(self) -> int | None:
        estimates = _tracker(self.coordinator)
        return estimates.billing_cycle_total_days if estimates is not None else None


class PGEBillingLastSyncSensor(PGEBaseEntity, SensorEntity):
    _attr_translation_key = "billing_last_sync"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_unique_id: str

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{account_key}_{ENTITY_UNIQUE_BILLING_LAST_SYNC}"

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.billing_freshness.last_success
