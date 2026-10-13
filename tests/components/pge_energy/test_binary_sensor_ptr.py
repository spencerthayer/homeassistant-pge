"""Billing-off setup still exposes the manual PTR active sensor."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.pge_energy.binary_sensor import (
    PGEPtrEventActiveBinarySensor,
    PGEPtrEventDetectedBinarySensor,
    async_setup_entry,
)
from custom_components.pge_energy.const import CONF_INCLUDE_BILLING, DOMAIN
from custom_components.pge_energy.store import ImportStoreData


def _entry(*, include_billing: bool) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry1"
    entry.options = {CONF_INCLUDE_BILLING: include_billing}
    entry.data = {}
    return entry


def _hass(entry: MagicMock) -> MagicMock:
    hass = MagicMock()
    coordinator = MagicMock()
    coordinator.account_key = "abc"
    hass.data = {DOMAIN: {entry.entry_id: coordinator}}
    return hass


@pytest.mark.asyncio
async def test_billing_disabled_registers_only_the_manual_active_sensor():
    entry = _entry(include_billing=False)
    added: list = []

    await async_setup_entry(_hass(entry), entry, added.extend)

    assert len(added) == 1
    assert isinstance(added[0], PGEPtrEventActiveBinarySensor)


@pytest.mark.asyncio
async def test_billing_enabled_registers_detection_and_the_manual_sensor():
    entry = _entry(include_billing=True)
    added: list = []

    await async_setup_entry(_hass(entry), entry, added.extend)

    assert any(isinstance(entity, PGEPtrEventActiveBinarySensor) for entity in added)
    assert any(isinstance(entity, PGEPtrEventDetectedBinarySensor) for entity in added)
    assert len(added) > 2


def test_missing_detection_flag_stays_unset_until_seen_dates_exist():
    fresh = ImportStoreData.from_dict({"account_key": "acct", "ptr_seen_event_dates": []})
    assert fresh.ptr_detection_initialized is False
    seeded = ImportStoreData.from_dict({"account_key": "acct", "ptr_seen_event_dates": ["2026-08-05"]})
    assert seeded.ptr_detection_initialized is True
    explicit = ImportStoreData.from_dict(
        {
            "account_key": "acct",
            "ptr_seen_event_dates": [],
            "ptr_detection_initialized": True,
        }
    )
    assert explicit.ptr_detection_initialized is True
