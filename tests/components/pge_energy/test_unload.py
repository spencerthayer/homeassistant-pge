from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.pge_energy import async_unload_entry
from custom_components.pge_energy.const import DOMAIN
from custom_components.pge_energy.coordinator import PGECoordinator


@pytest.mark.asyncio
async def test_unload_cancels_backfill_task():
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.services.async_remove = MagicMock()
    hass.services.has_service = MagicMock(return_value=True)

    entry = MagicMock()
    entry.entry_id = "entry1"
    entry.data = {"account_id": "acct", "account_key": "keykeykeykeykeyk"}

    auth = MagicMock()
    auth.account_key = "keykeykeykeykeyk"
    auth.auth_mode = "credential"
    client = MagicMock()
    coord = PGECoordinator(hass, entry, auth, client)

    started = asyncio.Event()

    async def long_job():
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise

    task = asyncio.create_task(long_job())
    coord.set_backfill_task(task)
    coord.set_backfill_state(True)
    hass.data[DOMAIN][entry.entry_id] = coord

    await started.wait()
    ok = await async_unload_entry(hass, entry)
    assert ok is True
    assert task.done()
    assert entry.entry_id not in hass.data.get(DOMAIN, {})
