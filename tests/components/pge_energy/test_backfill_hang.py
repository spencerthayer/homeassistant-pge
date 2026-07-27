"""Regression tests for backfill deadlock + hang recovery."""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.pge_energy import (
    _async_backfill_with_watchdog,
    _async_resume_backfill,
    _async_run_backfill,
    _async_watch_backfill_stall,
    _start_backfill_task,
    async_unload_entry,
)
from custom_components.pge_energy.backfill import async_backfill_range
from custom_components.pge_energy.const import (
    DOMAIN,
    SYNC_STATUS_BACKFILLING,
    SYNC_STATUS_FAILED,
)
from custom_components.pge_energy.coordinator import PGECoordinator
from custom_components.pge_energy.statistics import async_wait_recorder_queue
from custom_components.pge_energy.store import ImportStoreData, async_save_import_state


def _make_coordinator() -> PGECoordinator:
    hass = MagicMock()
    hass.is_stopping = False
    hass.async_create_background_task = MagicMock(
        side_effect=lambda coro, name="", eager_start=False: asyncio.create_task(coro)
    )
    hass.config_entries.async_update_entry = MagicMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.services.async_remove = MagicMock()
    hass.services.has_service = MagicMock(return_value=True)
    hass.data = {DOMAIN: {}}
    entry = MagicMock()
    entry.entry_id = "entry1"
    entry.data = {
        "account_id": "acct",
        "account_key": "keykeykeykeykeyk",
        "correction_window": 2,
    }
    auth = MagicMock()
    auth.account_key = "keykeykeykeykeyk"
    auth.auth_mode = "credential"
    auth.ensure_valid_token = AsyncMock(return_value="tok")
    auth.persistable_auth_data = MagicMock(return_value={})
    client = MagicMock()
    coord = PGECoordinator(hass, entry, auth, client)
    coord._import_store = ImportStoreData(account_key="keykeykeykeykeyk")
    coord.async_update_listeners = MagicMock()
    hass.data[DOMAIN][entry.entry_id] = coord
    return coord


@pytest.mark.asyncio
async def test_async_wait_recorder_queue_skips_hass_block_till_done():
    hass = MagicMock()
    hass.async_block_till_done = AsyncMock()
    recorder = MagicMock()
    recorder.async_block_till_done = AsyncMock()
    with patch(
        "custom_components.pge_energy.statistics.get_instance",
        return_value=recorder,
    ):
        await async_wait_recorder_queue(hass)
    recorder.async_block_till_done.assert_awaited_once()
    hass.async_block_till_done.assert_not_called()


def test_backfill_task_sites_use_background_task():
    source = inspect.getsource(_start_backfill_task)
    assert "async_create_background_task" in source
    assert "async_create_task" not in source


@pytest.mark.asyncio
async def test_poll_defers_while_backfill_in_progress():
    coord = _make_coordinator()
    coord.set_backfill_state(True)
    coord._recent_intervals = []
    coord.data = {"intervals": [], "stale": False}
    with patch.object(coord, "async_get_usage_with_auth_retry", AsyncMock()) as usage:
        payload = await coord._async_poll_usage()
    usage.assert_not_awaited()
    assert payload.get("stale") is True


@pytest.mark.asyncio
async def test_watchdog_stall_aborts_and_clears_targets(monkeypatch):
    coord = _make_coordinator()
    coord.set_backfill_state(True)
    coord.import_store.target_start = "2024-01-01T00:00:00+00:00"
    coord.import_store.target_end = "2024-01-31T00:00:00+00:00"
    coord.note_backfill_activity()
    # Freeze heartbeat in the past.
    coord._last_progress_monotonic = asyncio.get_running_loop().time() - 10_000

    monkeypatch.setattr(
        "custom_components.pge_energy._async_watch_backfill_stall.__module__",
        "custom_components.pge_energy",
    )
    monkeypatch.setattr(
        "custom_components.pge_energy.BACKFILL_STALL_POLL_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        "custom_components.pge_energy.BACKFILL_STALL_TIMEOUT",
        timedelta(milliseconds=1),
    )
    monkeypatch.setattr(
        "custom_components.pge_energy.BACKFILL_CANCEL_GRACE",
        0.01,
    )

    abort = AsyncMock()
    coord.request_backfill_abort = MagicMock(
        side_effect=lambda reason, clear_targets=False: coord.__class__.request_backfill_abort(
            coord, reason, clear_targets=clear_targets
        )
    )
    coord.force_release_backfill = abort

    # progress_stalled with short timeout
    assert coord.progress_stalled(timedelta(milliseconds=1)) is True

    hung = asyncio.Event()

    async def never_ends(*_a, **_k):
        hung.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise

    task = asyncio.create_task(never_ends())
    gen = coord.set_backfill_task(task)
    assert gen is not None

    with patch(
        "custom_components.pge_energy.coordinator.async_save_import_state",
        AsyncMock(),
    ):
        await _async_watch_backfill_stall(coord.hass, coord)

    coord.request_backfill_abort.assert_called()
    abort.assert_awaited()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_hard_release_unblocks_sync_job():
    coord = _make_coordinator()

    async def swallow_cancel():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await asyncio.sleep(3600)

    task = asyncio.create_task(swallow_cancel())
    coord.set_backfill_task(task)
    coord.set_backfill_state(True)
    coord.begin_sync_job(
        status=SYNC_STATUS_BACKFILLING,
        phase="hourly",
        total=10,
        message="Hourly 0/10",
    )

    with patch(
        "custom_components.pge_energy.coordinator.async_save_import_state",
        AsyncMock(),
    ):
        await coord.force_release_backfill("Stalled backfill did not respond to cancel")

    assert coord.backfill_in_progress is False
    assert coord.sync_progress.status == SYNC_STATUS_FAILED
    assert coord.try_reserve_backfill() is True
    task.cancel()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_generation_guard_blocks_orphan_finally():
    coord = _make_coordinator()
    task1 = asyncio.create_task(asyncio.sleep(0))
    gen1 = coord.set_backfill_task(task1)
    coord.set_backfill_state(True, generation=gen1)
    token = coord.bind_backfill_run_generation(gen1)
    with patch(
        "custom_components.pge_energy.coordinator.async_save_import_state",
        AsyncMock(),
    ):
        await coord.force_release_backfill("orphan")
    coord.reset_backfill_run_generation(token)

    # New job starts after force release (fresh context, no stale generation).
    task2 = asyncio.create_task(asyncio.sleep(3600))
    gen2 = coord.set_backfill_task(task2)
    coord.set_backfill_state(True, generation=gen2)
    coord.begin_sync_job(
        status=SYNC_STATUS_BACKFILLING,
        phase="hourly",
        total=5,
        message="new",
    )
    # Orphan finally with stale generation must not clear the new job.
    coord.set_backfill_state(False, generation=gen1)
    coord.set_backfill_task(None, generation=gen1)
    assert coord.backfill_in_progress is True
    assert coord.sync_progress.status == SYNC_STATUS_BACKFILLING
    assert coord.sync_progress.message == "new"
    task2.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task2
    await task1


@pytest.mark.asyncio
async def test_cancelled_error_retains_targets():
    coord = _make_coordinator()
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 10, tzinfo=UTC)

    async def hang_range(*_a, **_k):
        await asyncio.sleep(3600)

    task_holder: dict[str, asyncio.Task] = {}

    async def runner():
        task_holder["t"] = asyncio.current_task()
        await _async_run_backfill(coord.hass, coord.entry.entry_id, coord, start, end)

    with (
        patch(
            "custom_components.pge_energy.async_save_import_state",
            AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.async_backfill_range",
            hang_range,
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_save_import_state",
            AsyncMock(),
        ),
    ):
        gen = coord.set_backfill_task(asyncio.create_task(asyncio.sleep(0)))
        # Replace with the real runner task.
        run = asyncio.create_task(runner())
        coord.set_backfill_task(run)
        await asyncio.sleep(0.05)
        run.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run

    assert coord.sync_progress.status == SYNC_STATUS_FAILED
    assert coord.import_store.target_start == start.isoformat()
    assert coord.import_store.target_end == end.isoformat()
    assert coord.backfill_in_progress is False
    del gen


@pytest.mark.asyncio
async def test_bounded_unload_with_uncancellable_task(monkeypatch):
    coord = _make_coordinator()
    monkeypatch.setattr(
        "custom_components.pge_energy.coordinator.BACKFILL_CANCEL_GRACE",
        0.05,
    )

    async def swallow():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await asyncio.sleep(3600)

    task = asyncio.create_task(swallow())
    coord.set_backfill_task(task)
    coord.set_backfill_state(True)
    coord.begin_sync_job(
        status=SYNC_STATUS_BACKFILLING,
        phase="hourly",
        total=1,
        message="x",
    )

    with patch(
        "custom_components.pge_energy.coordinator.async_save_import_state",
        AsyncMock(),
    ):
        started = asyncio.get_running_loop().time()
        ok = await async_unload_entry(coord.hass, coord.entry)
        elapsed = asyncio.get_running_loop().time() - started

    assert ok is True
    assert elapsed < 2.0
    assert coord.backfill_in_progress is False
    task.cancel()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_tier_timeout_continues_to_daily(monkeypatch):
    coord = _make_coordinator()
    monkeypatch.setattr(
        "custom_components.pge_energy.backfill.BACKFILL_TIER_TIMEOUT",
        timedelta(milliseconds=20),
    )
    store = coord.import_store
    # One incomplete day in hourly window.
    day = date.today() - timedelta(days=2)
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    end = start + timedelta(days=1)

    async def hang_hourly(*_a, **_k):
        await asyncio.sleep(3600)

    daily = AsyncMock()
    monthly = AsyncMock()

    with (
        patch(
            "custom_components.pge_energy.backfill._async_backfill_hourly",
            hang_hourly,
        ),
        patch(
            "custom_components.pge_energy.backfill._async_backfill_daily",
            daily,
        ),
        patch(
            "custom_components.pge_energy.backfill._async_backfill_monthly",
            monthly,
        ),
        patch(
            "custom_components.pge_energy.backfill.async_save_import_state",
            AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_save_import_state",
            AsyncMock(),
        ),
        patch.object(coord.auth_manager, "ensure_valid_token", AsyncMock()),
        patch.object(coord, "persist_auth_to_entry", MagicMock()),
    ):
        await async_backfill_range(coord.hass, coord.entry.entry_id, coord, start, end)

    daily.assert_awaited()
    monthly.assert_awaited()
    assert store is coord.import_store


@pytest.mark.asyncio
async def test_save_timeout_critical_vs_noncritical(monkeypatch):
    hass = MagicMock()
    store_mock = MagicMock()

    async def hang_save(_data):
        await asyncio.sleep(3600)

    store_mock.async_save = hang_save
    store_mock.hass = hass
    monkeypatch.setattr(
        "custom_components.pge_energy.store.IMPORT_STATE_SAVE_TIMEOUT",
        0.05,
    )
    with patch(
        "custom_components.pge_energy.store._store_for_entry",
        return_value=store_mock,
    ):
        data = ImportStoreData(account_key="k")
        with pytest.raises(TimeoutError):
            await async_save_import_state(hass, "entry1xxxx", data, critical=True)
        # Non-critical must not raise.
        await async_save_import_state(hass, "entry1xxxx", data, critical=False)


@pytest.mark.asyncio
async def test_poll_zombie_recovery():
    coord = _make_coordinator()
    done_task = asyncio.create_task(asyncio.sleep(0))
    await done_task
    coord.set_backfill_task(done_task)
    coord._backfill_in_progress = True
    coord.begin_sync_job(
        status=SYNC_STATUS_BACKFILLING,
        phase="hourly",
        total=3,
        message="stuck",
    )
    with patch(
        "custom_components.pge_energy.coordinator.async_save_import_state",
        AsyncMock(),
    ):
        payload = await coord._async_poll_usage()
    assert coord.backfill_in_progress is False
    assert coord.sync_progress.status == SYNC_STATUS_FAILED
    assert "terminated unexpectedly" in (coord.sync_progress.error or "")
    assert payload.get("stale") is True


@pytest.mark.asyncio
async def test_boot_repair_clears_restored_backfilling():
    coord = _make_coordinator()
    coord._import_store.sync_status = SYNC_STATUS_BACKFILLING
    coord._import_store.sync_phase = "hourly"
    coord._import_store.sync_done = 3
    coord._import_store.sync_total = 10
    with patch(
        "custom_components.pge_energy.coordinator.async_load_import_state",
        AsyncMock(return_value=coord._import_store),
    ), patch.object(coord, "async_refresh_lifetime_totals", AsyncMock()):
        await coord.async_load_store()
    assert coord.sync_progress.status == SYNC_STATUS_FAILED
    assert coord.sync_progress.error == "Interrupted by restart"


@pytest.mark.asyncio
async def test_pre_try_zombie_window_on_initial_save_timeout():
    coord = _make_coordinator()
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 2, tzinfo=UTC)
    gen = coord.set_backfill_task(asyncio.create_task(asyncio.sleep(0)))
    await asyncio.sleep(0)

    with patch(
        "custom_components.pge_energy.async_save_import_state",
        AsyncMock(side_effect=TimeoutError()),
    ), patch(
        "custom_components.pge_energy.coordinator.async_save_import_state",
        AsyncMock(),
    ):
        await _async_run_backfill(coord.hass, coord.entry.entry_id, coord, start, end)

    assert coord._backfill_in_progress is False
    assert coord.sync_progress.status == SYNC_STATUS_FAILED
    assert coord.import_store.target_start is None
    del gen


@pytest.mark.asyncio
async def test_resume_releases_reservation_when_targets_missing():
    coord = _make_coordinator()
    assert coord.try_reserve_backfill() is True
    gen = coord.set_backfill_task(asyncio.create_task(asyncio.sleep(0)))
    await asyncio.sleep(0)
    coord.import_store.target_start = None
    coord.import_store.target_end = None
    await _async_resume_backfill(coord.hass, coord.entry.entry_id, coord)
    assert coord.backfill_in_progress is False
    assert coord.sync_job_in_progress is False
    del gen


@pytest.mark.asyncio
async def test_watchdog_wrapper_cancels_stall_task():
    coord = _make_coordinator()
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 2, tzinfo=UTC)

    with (
        patch(
            "custom_components.pge_energy._async_run_backfill",
            AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy._async_watch_backfill_stall",
            AsyncMock(),
        ) as watch,
    ):
        gen = coord.set_backfill_task(asyncio.create_task(asyncio.sleep(0)))
        await _async_backfill_with_watchdog(coord.hass, coord.entry.entry_id, coord, start, end)
        watch.assert_called()
        del gen
