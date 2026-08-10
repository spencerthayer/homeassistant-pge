"""PGE Energy binary sensors — autopay / paperless / program enrollment."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    BINARY_UNIQUE_AUTOPAY,
    BINARY_UNIQUE_PAPERLESS_BILL,
    BINARY_UNIQUE_PROGRAM_GREEN_FUTURE,
    BINARY_UNIQUE_PROGRAM_HABITAT_SUPPORT,
    BINARY_UNIQUE_PROGRAM_PEAK_TIME_REBATES,
    BINARY_UNIQUE_PROGRAM_SMART_BATTERY,
    BINARY_UNIQUE_PROGRAM_SMART_CHARGING,
    BINARY_UNIQUE_PROGRAM_SMART_THERMOSTAT,
    BINARY_UNIQUE_PROGRAM_TIME_OF_DAY,
    CONF_INCLUDE_BILLING,
    DEFAULT_INCLUDE_BILLING,
    DOMAIN,
)
from .coordinator import PGECoordinator
from .entity import PGEBaseEntity
from .options import get_entry_option

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    if not bool(get_entry_option(entry, CONF_INCLUDE_BILLING, DEFAULT_INCLUDE_BILLING)):
        return

    coordinator: PGECoordinator = hass.data[DOMAIN][entry.entry_id]
    account_key = coordinator.account_key

    async_add_entities(
        [
            PGEAutopayBinarySensor(coordinator, account_key),
            PGEPaperlessBinarySensor(coordinator, account_key),
            PGEPeakTimeRebatesBinarySensor(coordinator, account_key),
            PGEGreenFutureBinarySensor(coordinator, account_key),
            PGETimeOfDayBinarySensor(coordinator, account_key),
            PGESmartThermostatBinarySensor(coordinator, account_key),
            PGEHabitatSupportBinarySensor(coordinator, account_key),
            PGESmartChargingBinarySensor(coordinator, account_key),
            PGESmartBatteryBinarySensor(coordinator, account_key),
        ]
    )


class _PGEBinarySensor(PGEBaseEntity, BinarySensorEntity):
    """Base for PGE enrollment/state binary sensors."""

    _attr_unique_id: str

    def __init__(self, coordinator: PGECoordinator, account_key: str, unique_suffix: str) -> None:
        super().__init__(coordinator)
        self._account_key = account_key
        self._attr_unique_id = f"{account_key}_{unique_suffix}"


class PGEAutopayBinarySensor(_PGEBinarySensor):
    _attr_translation_key = "autopay"

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator, account_key, BINARY_UNIQUE_AUTOPAY)

    @property
    def is_on(self) -> bool | None:
        snapshot = self.coordinator.account_snapshot
        return snapshot.autopay_enrolled if snapshot is not None else None


class PGEPaperlessBinarySensor(_PGEBinarySensor):
    _attr_translation_key = "paperless_bill"

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator, account_key, BINARY_UNIQUE_PAPERLESS_BILL)

    @property
    def is_on(self) -> bool | None:
        snapshot = self.coordinator.account_snapshot
        return snapshot.paperless_enrolled if snapshot is not None else None


class _PGEProgramBinarySensor(_PGEBinarySensor):
    """Program-enrollment binary sensor with rich attributes."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _program_attr: str
    _eligible_attr: str | None = None
    _attr_keys: tuple[str, ...] = ()

    @property
    def is_on(self) -> bool | None:
        programs = self.coordinator.programs_snapshot
        if programs is None:
            return None
        return getattr(programs, self._program_attr, None)

    def _eligibility_attrs(self, programs: Any) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        if self._eligible_attr is not None:
            eligible = getattr(programs, self._eligible_attr, None)
            if eligible is not None:
                attrs["is_eligible"] = eligible
        return attrs

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        programs = self.coordinator.programs_snapshot
        if programs is None:
            return {}
        attrs: dict[str, Any] = {}
        attrs.update(self._eligibility_attrs(programs))
        for key in self._attr_keys:
            value = getattr(programs, key, None)
            if value is not None:
                attrs[key] = value
        return attrs


class PGEPeakTimeRebatesBinarySensor(_PGEProgramBinarySensor):
    _attr_translation_key = "program_peak_time_rebates"
    _program_attr = "peak_time_rebates_enrolled"
    _eligible_attr = "peak_time_rebates_eligible"

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator, account_key, BINARY_UNIQUE_PROGRAM_PEAK_TIME_REBATES)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        programs = self.coordinator.programs_snapshot
        if programs is None:
            return {}
        attrs: dict[str, Any] = {}
        attrs.update(self._eligibility_attrs(programs))
        detail = programs.attributes.get("peak_time_rebate")
        if isinstance(detail, dict):
            for key in (
                "peak_time_events",
                "seasonal_dates",
                "activePTRSeason",
                "lastPTRSeason",
                "nextPTRSeason",
            ):
                if detail.get(key) is not None:
                    attrs[key] = detail[key]
        return attrs


class PGEGreenFutureBinarySensor(_PGEProgramBinarySensor):
    _attr_translation_key = "program_green_future"
    _program_attr = "green_future_enrolled"
    _eligible_attr = "green_future_eligible"
    _attr_keys = ("green_future_pct",)

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator, account_key, BINARY_UNIQUE_PROGRAM_GREEN_FUTURE)


class PGETimeOfDayBinarySensor(_PGEProgramBinarySensor):
    _attr_translation_key = "program_time_of_day"
    _program_attr = "time_of_day_enrolled"
    _eligible_attr = "time_of_day_eligible"

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator, account_key, BINARY_UNIQUE_PROGRAM_TIME_OF_DAY)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        programs = self.coordinator.programs_snapshot
        if programs is None:
            return {}
        attrs: dict[str, Any] = {}
        attrs.update(self._eligibility_attrs(programs))
        detail = programs.attributes.get("tod_enrollment_detail")
        if isinstance(detail, dict):
            for key in (
                "annualLookBackEarnedCredit",
                "offPeakCharges",
                "midPeakCharges",
                "onPeakCharges",
                "planSavings",
            ):
                val = detail.get(key)
                if val is not None:
                    attrs[key] = val
        return attrs


class PGESmartThermostatBinarySensor(_PGEProgramBinarySensor):
    _attr_translation_key = "program_smart_thermostat"
    _program_attr = "smart_thermostat_enrolled"
    _eligible_attr = "smart_thermostat_eligible"

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator, account_key, BINARY_UNIQUE_PROGRAM_SMART_THERMOSTAT)


class PGEHabitatSupportBinarySensor(_PGEProgramBinarySensor):
    _attr_translation_key = "program_habitat_support"
    _program_attr = "habitat_support_enrolled"
    _eligible_attr = "habitat_support_eligible"

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator, account_key, BINARY_UNIQUE_PROGRAM_HABITAT_SUPPORT)


class PGESmartChargingBinarySensor(_PGEProgramBinarySensor):
    _attr_translation_key = "program_smart_charging"
    _program_attr = "smart_charging_enrolled"

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator, account_key, BINARY_UNIQUE_PROGRAM_SMART_CHARGING)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        programs = self.coordinator.programs_snapshot
        if programs is None:
            return {}
        attrs: dict[str, Any] = {}
        if programs.smart_charging_eligible is not None:
            attrs["is_eligible"] = programs.smart_charging_eligible
        detail = programs.attributes.get("smart_charging_detail")
        if isinstance(detail, dict):
            attrs["smart_charging_detail"] = detail
        return attrs


class PGESmartBatteryBinarySensor(_PGEProgramBinarySensor):
    _attr_translation_key = "program_smart_battery"
    _program_attr = "smart_battery_enrolled"

    def __init__(self, coordinator: PGECoordinator, account_key: str) -> None:
        super().__init__(coordinator, account_key, BINARY_UNIQUE_PROGRAM_SMART_BATTERY)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        programs = self.coordinator.programs_snapshot
        if programs is None:
            return {}
        attrs: dict[str, Any] = {}
        if programs.smart_battery_eligible is not None:
            attrs["is_eligible"] = programs.smart_battery_eligible
        detail = programs.attributes.get("smart_battery_detail")
        if isinstance(detail, dict):
            attrs["smart_battery_detail"] = detail
        return attrs
