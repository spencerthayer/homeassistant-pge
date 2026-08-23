"""Regression tests for backfill deadlock + hang recovery."""

from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.pge_energy import (
    _async_backfill_with_watchdog,
    _async_resume_backfill,
    _async_run_backfill,
    _async_watch_backfill_stall,
    _start_backfill_task,
    async_unload_entry,
    backfill,
)
from custom_components.pge_energy.backfill import _async_backfill_hourly, async_backfill_range
from custom_components.pge_energy.const import (
    DOMAIN,
    SYNC_STATUS_BACKFILLING,
    SYNC_STATUS_FAILED,
)
from custom_components.pge_energy.coordinator import PGECoordinator
from custom_components.pge_energy.models import UsageInterval, UsageResolution, UsageResponse
from custom_components.pge_energy.statistics import ImportBaselineResult, async_wait_recorder_queue
from custom_components.pge_energy.store import ImportStoreData, async_save_import_state
from custom_components.pge_energy.time_util import local_day_bounds, today_local


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
    coord.async_request_refresh = AsyncMock()
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
async def test_poll_fetches_correction_window_while_backfill_in_progress():
    """History backfill must not freeze the tip: correction polls still fetch."""
    coord = _make_coordinator()
    coord.set_backfill_state(True)
    coord._recent_intervals = []
    coord.data = {"intervals": [], "stale": False}
    yesterday = today_local() - timedelta(days=1)
    day_start, _ = local_day_bounds(yesterday)
    hour = UsageInterval(
        account_key="keykeykeykeykeyk",
        resolution=UsageResolution.HOURLY,
        start=day_start,
        end=day_start + timedelta(hours=1),
        kwh=Decimal("0.5"),
        amount=Decimal("0.1"),
        temperature=None,
        usage_status="kWh-Delivered",
        interval_size=None,
        source_timestamp=None,
    )

    async def fake_usage(start, end, resolution=UsageResolution.HOURLY):
        day = start.astimezone(day_start.tzinfo).date()
        if day == yesterday:
            return UsageResponse(
                resolution=UsageResolution.HOURLY,
                intervals=[hour],
                total_kwh=None,
                total_cost=None,
                is_tod=None,
                acct_type=None,
            )
        return UsageResponse(
            resolution=UsageResolution.HOURLY,
            intervals=[],
            total_kwh=None,
            total_cost=None,
            is_tod=None,
            acct_type=None,
        )

    coord.async_get_usage_with_auth_retry = AsyncMock(side_effect=fake_usage)
    with (
        patch(
            "custom_components.pge_energy.coordinator.async_import_with_baseline",
            AsyncMock(return_value=ImportBaselineResult(1)),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_save_import_state",
            AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_run_billing_sync",
            AsyncMock(),
        ),
    ):
        payload = await coord._async_poll_usage()
    assert coord.async_get_usage_with_auth_retry.await_count >= 1
    assert payload.get("stale") is not True
    assert coord.freshness.newest_interval == hour.end


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

    # Daily reports "no fatal batch" (False): this test exercises tier
    # continuation after an hourly TIMEOUT, not fatal gating.
    daily = AsyncMock(return_value=False)
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
    with (
        patch(
            "custom_components.pge_energy.coordinator.async_load_import_state",
            AsyncMock(return_value=coord._import_store),
        ),
        patch.object(coord, "async_refresh_lifetime_totals", AsyncMock()),
    ):
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

    with (
        patch(
            "custom_components.pge_energy.async_save_import_state",
            AsyncMock(side_effect=TimeoutError()),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_save_import_state",
            AsyncMock(),
        ),
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


@pytest.mark.asyncio
async def test_orphan_does_not_clear_successor_targets():
    """An orphaned job shares import_store with its successor; it must not touch it."""
    coord = _make_coordinator()
    a_start, a_end = datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 10, tzinfo=UTC)
    b_start, b_end = datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 10, tzinfo=UTC)

    async def hang(*_a, **_k):
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            # Models a non-cancellable await (recorder executor job): the cancel is
            # observed only after a newer job has already claimed the coordinator.
            await asyncio.sleep(0.1)
            raise

    with (
        patch("custom_components.pge_energy.async_save_import_state", AsyncMock()),
        patch("custom_components.pge_energy.async_backfill_range", hang),
        patch("custom_components.pge_energy.coordinator.async_save_import_state", AsyncMock()),
    ):
        orphan = asyncio.create_task(_async_run_backfill(coord.hass, coord.entry.entry_id, coord, a_start, a_end))
        coord.set_backfill_task(orphan)
        await asyncio.sleep(0.02)

        coord.request_backfill_abort("Stalled: no progress", clear_targets=True)
        await coord.force_release_backfill("Stalled backfill did not respond to cancel")

        successor = asyncio.create_task(_async_run_backfill(coord.hass, coord.entry.entry_id, coord, b_start, b_end))
        coord.set_backfill_task(successor)
        await asyncio.sleep(0.02)
        assert coord.import_store.target_start == b_start.isoformat()

        with pytest.raises(asyncio.CancelledError):
            await orphan
        await asyncio.sleep(0.02)

        assert coord.import_store.target_start == b_start.isoformat()
        assert coord.import_store.target_end == b_end.isoformat()
        assert coord.backfill_in_progress is True
        successor.cancel()
        with pytest.raises(asyncio.CancelledError):
            await successor


@pytest.mark.asyncio
async def test_abort_reason_is_not_consumed_by_a_later_job():
    """A stall abort aimed at job A must not fail job B with A's reason/targets."""
    coord = _make_coordinator()
    orphan = asyncio.create_task(asyncio.sleep(3600))
    coord.set_backfill_task(orphan)
    coord.request_backfill_abort("Stalled: no progress", clear_targets=True)
    with patch(
        "custom_components.pge_energy.coordinator.async_save_import_state",
        AsyncMock(),
    ):
        await coord.force_release_backfill("did not respond to cancel")

    successor = asyncio.create_task(asyncio.sleep(3600))
    generation = coord.set_backfill_task(successor)
    reason, clear_targets = coord.consume_backfill_abort(generation)
    assert reason is None
    assert clear_targets is False

    orphan.cancel()
    successor.cancel()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_unload_cancels_orphaned_tasks():
    coord = _make_coordinator()

    async def swallow():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await asyncio.sleep(3600)

    orphan = asyncio.create_task(swallow())
    coord.set_backfill_task(orphan)
    with patch(
        "custom_components.pge_energy.coordinator.async_save_import_state",
        AsyncMock(),
    ):
        await coord.force_release_backfill("orphaned")
        await coord.async_cancel_backfill()

    assert orphan.cancelling() > 0
    orphan.cancel()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_boot_repair_clears_restored_refreshing():
    coord = _make_coordinator()
    coord._import_store.sync_status = "refreshing"
    with (
        patch(
            "custom_components.pge_energy.coordinator.async_load_import_state",
            AsyncMock(return_value=coord._import_store),
        ),
        patch.object(coord, "async_refresh_lifetime_totals", AsyncMock()),
    ):
        await coord.async_load_store()
    assert coord.sync_progress.status == SYNC_STATUS_FAILED


@pytest.mark.asyncio
async def test_hourly_backfill_fetches_newest_incomplete_day_first():
    """Yesterday must not wait behind a 365-day oldest-first walk."""
    store = ImportStoreData(account_key="key")
    older = date(2026, 8, 10)
    mid = date(2026, 8, 11)
    newer = date(2026, 8, 12)
    fetched: list[date] = []

    async def fake_fetch(_coord, day: date):
        fetched.append(day)
        return day, []

    coord = _make_coordinator()
    coord._import_store = store
    coord.entry.options = {"backfill_concurrency": 1}
    coord.update_sync_progress = MagicMock()
    with (
        patch(
            "custom_components.pge_energy.backfill.async_fetch_hourly_day",
            fake_fetch,
        ),
        patch(
            "custom_components.pge_energy.backfill.async_save_import_state",
            AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_save_import_state",
            AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.backfill.BACKFILL_DELAY_BETWEEN_CHUNKS",
            0,
        ),
    ):
        await _async_backfill_hourly(coord.hass, coord.entry.entry_id, coord, older, newer)
    assert fetched == [newer, mid, older]


@pytest.mark.asyncio
async def test_backfill_exit_requests_tip_refresh():
    """After history backfill ends, do not wait until the next 4h grid slot."""
    coord = _make_coordinator()
    coord.async_request_refresh = AsyncMock()
    start = datetime(2026, 8, 1, tzinfo=UTC)
    end = datetime(2026, 8, 2, tzinfo=UTC)
    with (
        patch(
            "custom_components.pge_energy.async_backfill_range",
            AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.async_run_billing_sync",
            AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.async_save_import_state",
            AsyncMock(),
        ),
    ):
        await _async_run_backfill(coord.hass, coord.entry.entry_id, coord, start, end)
    coord.async_request_refresh.assert_awaited()


@pytest.mark.asyncio
async def test_batch_checkpoint_transaction_holds_import_lock(monkeypatch):
    """Marker save, import, and clear-save all run inside the import_lock."""
    coord = SimpleNamespace(
        import_store=ImportStoreData(account_key="k"),
        import_lock=asyncio.Lock(),
        account_key="acct",
        account_id="aid",
        entry=SimpleNamespace(options={}, data={}),
        async_refresh_lifetime_totals=AsyncMock(),
    )
    interval = SimpleNamespace(
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 2, tzinfo=UTC),
    )
    events = []

    async def _rec_save(hass, entry_id, data, *, critical=True):  # noqa: ARG001
        events.append(("save", coord.import_lock.locked()))

    async def _rec_import(*args, **kwargs):  # noqa: ARG002, ARG001
        events.append(("import", coord.import_lock.locked()))
        return SimpleNamespace(cost_failed_days=[])

    monkeypatch.setattr(backfill, "async_save_import_state", _rec_save)
    monkeypatch.setattr(backfill, "async_import_with_baseline", _rec_import)

    ok = await backfill._async_import_batch(MagicMock(), "entry1", coord, [interval])
    assert ok == backfill.BATCH_OK
    assert coord.import_store.dirty_from is None
    # Every step of the crash-recovery transaction holds the lock.
    assert events == [("save", True), ("import", True), ("save", True)]


@pytest.mark.asyncio
async def test_retry_rebinds_store_replaced_by_reset_during_fetch(monkeypatch):
    """A retry must mutate/persist the CURRENT store, not a pre-reset capture."""
    import custom_components.pge_energy as pge_root

    coord = SimpleNamespace(
        import_store=ImportStoreData(account_key="k"),
        import_lock=asyncio.Lock(),
        account_key="acct",
        account_id="aid",
        entry=SimpleNamespace(entry_id="entry1", options={}, data={}),
    )
    old_store = coord.import_store
    old_store.failed_local_dates = ["2024-01-01"]
    new_store = ImportStoreData(account_key="k")
    saved_ids: list[int] = []
    import_markers: list[str | None] = []

    async def _fetch(coordinator, day):  # noqa: ARG001
        # The reset replaces the store while this network fetch is running.
        coordinator.import_store = new_store
        return None, [
            UsageInterval(
                account_key="acct",
                resolution=UsageResolution.HOURLY,
                start=datetime(2024, 1, 1, tzinfo=UTC),
                end=datetime(2024, 1, 1, 1, tzinfo=UTC),
                kwh=Decimal("1.0"),
                amount=Decimal("0.1"),
                temperature=None,
                usage_status=None,
                interval_size=None,
                source_timestamp=None,
            )
        ]

    async def _rec_save(hass, entry_id, data, *, critical=True):  # noqa: ARG001
        saved_ids.append(id(data))

    async def _rec_import(hass, account_key, intervals, **kwargs):  # noqa: ARG002, ARG001
        import_markers.append(coord.import_store.dirty_from)
        return SimpleNamespace(cost_failed_days=[])

    monkeypatch.setattr(pge_root, "async_fetch_hourly_day", _fetch)
    monkeypatch.setattr(pge_root, "clip_hourly_to_local_day", lambda day, iv, **k: iv)
    monkeypatch.setattr(pge_root, "validate_hourly_day", lambda *a, **k: (True, ""))
    monkeypatch.setattr(pge_root, "is_invalid_closed_day", lambda ok, reason: not ok)
    monkeypatch.setattr(pge_root, "async_import_with_baseline", _rec_import)
    monkeypatch.setattr(pge_root, "async_save_import_state", _rec_save)

    await pge_root._async_retry_failed_ranges(MagicMock(), coord)

    # The transaction mutated and persisted the CURRENT store object.
    assert saved_ids and all(sid == id(new_store) for sid in saved_ids)
    assert import_markers == ["2024-01-01T00:00:00+00:00"]  # marker on live store
    assert new_store.dirty_from is None  # cleared after successful import
    assert old_store.dirty_from is None  # obsolete capture untouched


@pytest.mark.asyncio
async def test_batch_defers_when_store_discards_stale_critical_save(monkeypatch):
    """An orphaned batch whose checkpoint is stale-deferred never imports."""
    coord = SimpleNamespace(
        import_store=ImportStoreData(account_key="k"),
        import_lock=asyncio.Lock(),
        account_key="acct",
        account_id="aid",
        entry=SimpleNamespace(options={}, data={}),
    )
    interval = SimpleNamespace(
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 2, tzinfo=UTC),
    )
    record_import = AsyncMock(return_value=SimpleNamespace(cost_failed_days=[]))

    async def _rec_save(hass, entry_id, data, *, critical=True):  # noqa: ARG001
        return False  # store layer discarded the save as stale

    monkeypatch.setattr(backfill, "async_save_import_state", _rec_save)
    monkeypatch.setattr(backfill, "async_import_with_baseline", record_import)

    ok = await backfill._async_import_batch(MagicMock(), "entry1", coord, [interval])
    assert ok == backfill.BATCH_DEFERRED
    assert coord.import_store.dirty_from is None
    record_import.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_fatal_on_import_error_retains_marker(monkeypatch):
    """Import exception keeps dirty_from, repairs best-effort, returns FATAL."""
    coord = SimpleNamespace(
        import_store=ImportStoreData(account_key="k"),
        import_lock=asyncio.Lock(),
        account_key="acct",
        account_id="aid",
        entry=SimpleNamespace(options={}, data={}),
        async_repair_dirty_if_needed=AsyncMock(),
    )
    interval = SimpleNamespace(
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 2, tzinfo=UTC),
    )

    async def _rec_save(hass, entry_id, data, *, critical=True):  # noqa: ARG001
        return None

    async def _boom(hass, account_key, intervals, **kwargs):  # noqa: ARG001
        raise RuntimeError("recorder exploded mid-import")

    monkeypatch.setattr(backfill, "async_save_import_state", _rec_save)
    monkeypatch.setattr(backfill, "async_import_with_baseline", _boom)

    ok = await backfill._async_import_batch(MagicMock(), "entry1", coord, [interval])
    assert ok == backfill.BATCH_FATAL
    assert coord.import_store.dirty_from == "2024-01-01T00:00:00+00:00"
    # Best-effort runtime repair runs after the lock releases so waiters are
    # gated on a repaired marker instead of replacing the boundary.
    coord.async_repair_dirty_if_needed.assert_awaited_once()


@pytest.mark.asyncio
async def test_batch_defers_when_recovery_marker_retained(monkeypatch):
    """A batch must not replace a prior importer's unrepaired recovery marker."""
    coord = SimpleNamespace(
        import_store=ImportStoreData(account_key="k"),
        import_lock=asyncio.Lock(),
        account_key="acct",
        account_id="aid",
        entry=SimpleNamespace(options={}, data={}),
    )
    coord.import_store.dirty_from = "2023-12-01T00:00:00+00:00"
    interval = SimpleNamespace(
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 2, tzinfo=UTC),
    )
    record_import = AsyncMock(return_value=SimpleNamespace(cost_failed_days=[]))
    monkeypatch.setattr(backfill, "async_save_import_state", AsyncMock())
    monkeypatch.setattr(backfill, "async_import_with_baseline", record_import)

    ok = await backfill._async_import_batch(MagicMock(), "entry1", coord, [interval])
    assert ok == backfill.BATCH_DEFERRED
    record_import.assert_not_awaited()
    # The earliest repair boundary stays exactly as the failed importer left it.
    assert coord.import_store.dirty_from == "2023-12-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_hourly_fatal_stops_daily_and_monthly_tiers(monkeypatch):
    """A fatal hourly batch stops the job before daily/monthly replace the marker."""
    coord = _make_coordinator()
    coord.async_repair_dirty_if_needed = AsyncMock()
    day = today_local() - timedelta(days=2)
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    end = start + timedelta(days=1)

    interval = UsageInterval(
        account_key="keykeykeykeykeyk",
        resolution=UsageResolution.HOURLY,
        start=start,
        end=start + timedelta(hours=1),
        kwh=Decimal("1.0"),
        amount=Decimal("0.1"),
        temperature=None,
        usage_status=None,
        interval_size=None,
        source_timestamp=None,
    )

    async def fake_fetch(coordinator, d):  # noqa: ARG001
        return d, [interval]

    async def _boom(hass, account_key, intervals, **kwargs):  # noqa: ARG001
        raise RuntimeError("recorder exploded mid-import")

    daily = AsyncMock()
    monthly = AsyncMock()

    with (
        patch.object(backfill, "async_fetch_hourly_day", fake_fetch),
        patch.object(backfill, "clip_hourly_to_local_day", lambda d, iv, **k: iv),
        patch.object(backfill, "validate_hourly_day", lambda *a, **k: (True, "")),
        patch.object(backfill, "is_invalid_closed_day", lambda ok, reason: not ok),
        patch.object(backfill, "async_import_with_baseline", _boom),
        patch.object(backfill, "async_save_import_state", AsyncMock()),
        patch.object(backfill, "_async_backfill_daily", daily),
        patch.object(backfill, "_async_backfill_monthly", monthly),
        patch("custom_components.pge_energy.coordinator.async_save_import_state", AsyncMock()),
        patch.object(coord.auth_manager, "ensure_valid_token", AsyncMock()),
        patch.object(coord, "persist_auth_to_entry", MagicMock()),
    ):
        await async_backfill_range(coord.hass, coord.entry.entry_id, coord, start, end)

    daily.assert_not_awaited()
    monthly.assert_not_awaited()
    # Marker retained for repair; repair was attempted at the source.
    assert coord.import_store.dirty_from == start.isoformat()
    coord.async_repair_dirty_if_needed.assert_awaited_once()


@pytest.mark.asyncio
async def test_batch_defers_when_generation_stale(monkeypatch):
    """A hard-released orphan defers instead of adopting the live store."""
    coord = SimpleNamespace(
        import_store=ImportStoreData(account_key="k"),
        import_lock=asyncio.Lock(),
        account_key="acct",
        account_id="aid",
        entry=SimpleNamespace(options={}, data={}),
        _is_stale_backfill_generation=lambda: True,
    )
    interval = SimpleNamespace(
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 1, 2, tzinfo=UTC),
    )
    record_import = AsyncMock(return_value=SimpleNamespace(cost_failed_days=[]))
    monkeypatch.setattr(backfill, "async_save_import_state", AsyncMock())
    monkeypatch.setattr(backfill, "async_import_with_baseline", record_import)

    ok = await backfill._async_import_batch(MagicMock(), "entry1", coord, [interval])
    assert ok == backfill.BATCH_DEFERRED
    record_import.assert_not_awaited()
    assert coord.import_store.dirty_from is None


def _retry_interval(day_start: datetime) -> UsageInterval:
    return UsageInterval(
        account_key="acct",
        resolution=UsageResolution.HOURLY,
        start=day_start,
        end=day_start + timedelta(hours=1),
        kwh=Decimal("1.0"),
        amount=Decimal("0.1"),
        temperature=None,
        usage_status=None,
        interval_size=None,
        source_timestamp=None,
    )


@pytest.mark.asyncio
async def test_retry_stops_after_import_failure_keeping_marker(monkeypatch):
    """An import failure stops the retry loop so later days cannot replace the marker."""
    import custom_components.pge_energy as pge_root

    coord = SimpleNamespace(
        import_store=ImportStoreData(account_key="k"),
        import_lock=asyncio.Lock(),
        account_key="acct",
        account_id="aid",
        entry=SimpleNamespace(entry_id="entry1", options={}, data={}),
        async_repair_dirty_if_needed=AsyncMock(),
    )
    coord.import_store.failed_local_dates = ["2024-01-01", "2024-01-02"]
    fetched: list[str] = []
    imported: list[str] = []

    async def _fetch(coordinator, day):  # noqa: ARG001
        fetched.append(day.isoformat())
        start = datetime(day.year, day.month, day.day, tzinfo=UTC)
        return day, [_retry_interval(start)]

    async def _boom(hass, account_key, intervals, **kwargs):  # noqa: ARG001
        imported.append(intervals[0].start.date().isoformat())
        raise RuntimeError("recorder exploded mid-import")

    monkeypatch.setattr(pge_root, "async_fetch_hourly_day", _fetch)
    monkeypatch.setattr(pge_root, "clip_hourly_to_local_day", lambda d, iv, **k: iv)
    monkeypatch.setattr(pge_root, "validate_hourly_day", lambda *a, **k: (True, ""))
    monkeypatch.setattr(pge_root, "is_invalid_closed_day", lambda ok, reason: not ok)
    monkeypatch.setattr(pge_root, "async_import_with_baseline", _boom)
    monkeypatch.setattr(pge_root, "async_save_import_state", AsyncMock())

    await pge_root._async_retry_failed_ranges(MagicMock(), coord)

    # The second day was never attempted: its transaction would have replaced
    # the first day's retained repair boundary.
    assert fetched == ["2024-01-01"]
    assert imported == ["2024-01-01"]
    assert coord.import_store.dirty_from == "2024-01-01T00:00:00+00:00"
    assert coord.import_store.completed_local_dates == []
    coord.async_repair_dirty_if_needed.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_skips_when_recovery_marker_already_pending(monkeypatch):
    """Retries must not run while another importer's recovery marker is unrepaired."""
    import custom_components.pge_energy as pge_root

    coord = SimpleNamespace(
        import_store=ImportStoreData(account_key="k"),
        import_lock=asyncio.Lock(),
        account_key="acct",
        account_id="aid",
        entry=SimpleNamespace(entry_id="entry1", options={}, data={}),
        async_repair_dirty_if_needed=AsyncMock(),
    )
    coord.import_store.failed_local_dates = ["2024-01-01"]
    coord.import_store.dirty_from = "2023-12-01T00:00:00+00:00"
    fetched: list[str] = []

    async def _fetch(coordinator, day):  # noqa: ARG001
        fetched.append(day.isoformat())
        start = datetime(day.year, day.month, day.day, tzinfo=UTC)
        return day, [_retry_interval(start)]

    record_import = AsyncMock(return_value=SimpleNamespace(cost_failed_days=[]))
    monkeypatch.setattr(pge_root, "async_fetch_hourly_day", _fetch)
    monkeypatch.setattr(pge_root, "clip_hourly_to_local_day", lambda d, iv, **k: iv)
    monkeypatch.setattr(pge_root, "validate_hourly_day", lambda *a, **k: (True, ""))
    monkeypatch.setattr(pge_root, "is_invalid_closed_day", lambda ok, reason: not ok)
    monkeypatch.setattr(pge_root, "async_import_with_baseline", record_import)
    monkeypatch.setattr(pge_root, "async_save_import_state", AsyncMock())

    await pge_root._async_retry_failed_ranges(MagicMock(), coord)

    # Fetch is lock-free and still ran, but the transaction never replaced the
    # pending marker and nothing was imported.
    assert fetched == ["2024-01-01"]
    record_import.assert_not_awaited()
    assert coord.import_store.dirty_from == "2023-12-01T00:00:00+00:00"
    coord.async_repair_dirty_if_needed.assert_awaited_once()


@pytest.mark.asyncio
async def test_daily_fatal_stops_monthly_tier_even_after_repair(monkeypatch):
    """A fatal daily batch keeps monthly from starting once repair clears the marker."""
    coord = _make_coordinator()
    coord.async_repair_dirty_if_needed = AsyncMock()
    day = today_local() - timedelta(days=2)
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    end = start + timedelta(days=1)

    daily = AsyncMock(return_value=True)  # tier reports BATCH_FATAL
    monthly = AsyncMock()

    with (
        patch.object(backfill, "compute_hourly_date_range", lambda *a, **k: None),
        patch.object(backfill, "_async_backfill_daily", daily),
        patch.object(backfill, "_async_backfill_monthly", monthly),
        patch.object(backfill, "async_save_import_state", AsyncMock()),
        patch("custom_components.pge_energy.coordinator.async_save_import_state", AsyncMock()),
    ):
        await async_backfill_range(coord.hass, coord.entry.entry_id, coord, start, end)

    daily.assert_awaited_once()
    # The captured fatal outcome (not just the retained marker) gates monthly:
    # even if the immediate repair cleared dirty_from, monthly must not start.
    monthly.assert_not_awaited()
