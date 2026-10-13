"""Manual PTR window sensors stay available when billing import is off."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.pge_energy.const import CONF_INCLUDE_BILLING, DOMAIN
from custom_components.pge_energy.sensor import (
    PGENextPtrEventDateSensor,
    PGEPtrEventEndSensor,
    PGEPtrEventStartSensor,
    async_setup_entry,
)


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
async def test_billing_disabled_registers_manual_ptr_window_sensors():
    entry = _entry(include_billing=False)
    added: list = []

    await async_setup_entry(_hass(entry), entry, added.extend)

    kinds = {type(entity) for entity in added}
    assert PGEPtrEventStartSensor in kinds
    assert PGEPtrEventEndSensor in kinds
    assert PGENextPtrEventDateSensor not in kinds


@pytest.mark.asyncio
async def test_billing_enabled_keeps_graphql_ptr_date_sensor():
    entry = _entry(include_billing=True)
    added: list = []

    await async_setup_entry(_hass(entry), entry, added.extend)

    kinds = {type(entity) for entity in added}
    assert PGEPtrEventStartSensor in kinds
    assert PGEPtrEventEndSensor in kinds
    assert PGENextPtrEventDateSensor in kinds
