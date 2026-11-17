from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

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


def _coordinator(hass, entry_id: str) -> PGECoordinator:
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {
        "account_id": "acct",
        "account_key": "keykeykeykeykeyk",
        "bearer_token": "old",
    }
    auth = MagicMock()
    auth.account_key = "keykeykeykeykeyk"
    auth.auth_mode = "credential"
    auth.persistable_auth_data = lambda: {"bearer_token": "renewed"}
    coord = PGECoordinator(hass, entry, auth, MagicMock())
    hass.data[DOMAIN][entry_id] = coord
    return coord


@pytest.mark.asyncio
async def test_unload_stops_post_setup():
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.config_entries.async_update_entry = MagicMock()
    hass.services.async_remove = MagicMock()
    hass.services.has_service = MagicMock(return_value=True)
    coord = _coordinator(hass, "entry1")
    started = asyncio.Event()
    release = asyncio.Event()

    async def post_setup():
        started.set()
        await release.wait()
        coord.persist_auth_to_entry()
        coord.try_reserve_backfill()

    task = asyncio.create_task(post_setup())
    coord.bind_post_setup_task(task)
    await started.wait()

    ok = await async_unload_entry(hass, coord.entry)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert ok is True
    hass.config_entries.async_update_entry.assert_not_called()
    assert coord.retired is True


@pytest.mark.asyncio
async def test_retired_writer_cannot_update_entry():
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.config_entries.async_update_entry = MagicMock()
    coord = _coordinator(hass, "entry1")
    release = asyncio.Event()

    async def late_writer():
        await release.wait()
        coord.persist_auth_to_entry()
        assert coord.try_reserve_backfill() is False

    task = asyncio.create_task(late_writer())
    await asyncio.sleep(0)
    coord.retire()
    release.set()
    await task
    hass.config_entries.async_update_entry.assert_not_called()
    with patch(
        "custom_components.pge_energy.coordinator.async_save_import_state",
        AsyncMock(),
    ) as save_state:
        await coord.async_persist_sensor_snapshots()
        await coord.async_persist_sync_progress()
    save_state.assert_not_called()
    coord.persist_auth_to_entry()
    hass.config_entries.async_update_entry.assert_not_called()
    assert coord.try_reserve_backfill() is False


@pytest.mark.asyncio
async def test_failed_unload_keeps_entry_and_spares_sibling():
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)
    hass.config_entries.async_update_entry = MagicMock()
    hass.services.async_remove = MagicMock()
    hass.services.has_service = MagicMock(return_value=False)
    first = _coordinator(hass, "entry1")
    second = _coordinator(hass, "entry2")

    ok = await async_unload_entry(hass, first.entry)
    assert ok is False
    assert first.retired is False
    assert second.retired is False
    assert hass.data[DOMAIN]["entry1"] is first
    assert hass.data[DOMAIN]["entry2"] is second

    second.persist_auth_to_entry()
    hass.config_entries.async_update_entry.assert_called_once()
