"""Tests for coalesced/deduplicated import-state saves (#33).

Covers the slow-storage resilience layer in ``store.py``:
- non-critical saves coalesce into one debounced disk write,
- content-hash dedupe skips unchanged payloads (and skips ``last_commit``),
- critical saves stay synchronous/durable (crash-safety checkpoints),
- timeouts never abort backfill batches (log-and-continue),
- pending writers are flushed/cancelled on clear/unload.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.pge_energy import backfill
from custom_components.pge_energy import store as store_mod
from custom_components.pge_energy.store import (
    ImportStoreData,
    async_clear_import_state,
    async_flush_import_state,
    async_load_import_state,
    async_save_import_state,
    discard_store_cache,
)


class _FakeHass:
    """Just enough hass for the debounced-writer scheduling path."""

    def __init__(self) -> None:
        self.is_stopping = False

    def async_create_background_task(self, target, *, name=None, eager_start=False):  # noqa: ARG002
        return asyncio.get_running_loop().create_task(target)


class _FakeStore:
    def __init__(self) -> None:
        self.hass = None
        self.saves: list[dict] = []
        self.calls = 0
        self.delay = 0.0

    async def async_save(self, payload):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        self.saves.append(payload)

    async def async_load(self):
        return self.saves[-1] if self.saves else None


@pytest.fixture(autouse=True)
def _fast_debounce(monkeypatch):
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_DEBOUNCE_SECONDS", 0.02)
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_TIMEOUT", 5.0)


@pytest.fixture(autouse=True)
def _reset_registry():
    yield
    for state in list(store_mod._SAVE_STATES.values()):
        if state.task is not None and not state.task.done():
            state.task.cancel()
        if state.inflight is not None and not state.inflight.done():
            # Real teardown never cancels executor-backed writes, but tests must
            # not leak pending tasks into a closing event loop.
            state.inflight.cancel()
    store_mod._SAVE_STATES.clear()
    store_mod._STORES.clear()


@pytest.fixture
def fake_store():
    return _FakeStore()


@pytest.fixture
def patched_store(fake_store):
    with patch.object(store_mod, "_store_for_entry", return_value=fake_store):
        yield fake_store


async def test_burst_noncritical_saves_coalesce_into_one_write(patched_store):
    """A rapid sequence of non-critical saves results in fewer writes than calls."""
    hass = _FakeHass()
    data = ImportStoreData(account_key="k")
    for i in range(10):
        data.completed_local_dates.append(f"2024-01-{i + 1:02d}")
        await async_save_import_state(hass, "entry1", data, critical=False)
    # Writer still inside the debounce window: nothing written yet.
    assert patched_store.calls == 0
    await async_flush_import_state(hass, "entry1")
    assert patched_store.calls == 1
    # Final payload wins: all ten days are present.
    assert len(patched_store.saves[-1]["completed_local_dates"]) == 10


async def test_noncritical_burst_writes_once_after_debounce(patched_store):
    """Even without an explicit flush the single writer persists the latest state."""
    hass = _FakeHass()
    data = ImportStoreData(account_key="k")
    for i in range(5):
        data.sync_done = i + 1
        await async_save_import_state(hass, "entry1", data, critical=False)
    await asyncio.sleep(0.15)
    assert patched_store.calls == 1
    assert patched_store.saves[0]["sync_done"] == 5


async def test_critical_save_is_durable_before_caller_proceeds(patched_store):
    """critical=True writes inline: the payload is on disk when the await returns."""
    hass = _FakeHass()
    data = ImportStoreData(account_key="k", dirty_from="2024-01-01T00:00:00-08:00")
    await async_save_import_state(hass, "entry1", data, critical=True)
    assert patched_store.calls == 1
    assert patched_store.saves[0]["dirty_from"] == "2024-01-01T00:00:00-08:00"


async def test_dirty_checkpoint_persisted_before_recorder_import(monkeypatch):
    """Backfill batch order: checkpoint save → recorder import → completion save."""
    order: list[str] = []
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

    async def _record_save(hass, entry_id, data, **kwargs):  # noqa: ARG001
        order.append("save")

    async def _record_import(*args, **kwargs):  # noqa: ARG002, ARG001
        order.append("import")
        return SimpleNamespace(cost_failed_days=[])

    monkeypatch.setattr(backfill, "async_save_import_state", _record_save)
    monkeypatch.setattr(backfill, "async_import_with_baseline", _record_import)

    ok = await backfill._async_import_batch(_FakeHass(), "entry1", coord, [interval])
    assert ok == backfill.BATCH_OK
    assert order == ["save", "import", "save"]


async def test_batch_deferred_when_preimport_checkpoint_times_out(monkeypatch):
    """A timed-out pre-import checkpoint defers the batch — recorder untouched."""
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

    async def _timeout_save(*args, **kwargs):  # noqa: ARG001
        raise TimeoutError

    record_import = AsyncMock(return_value=SimpleNamespace(cost_failed_days=[]))
    monkeypatch.setattr(backfill, "async_save_import_state", _timeout_save)
    monkeypatch.setattr(backfill, "async_import_with_baseline", record_import)

    ok = await backfill._async_import_batch(_FakeHass(), "entry1", coord, [interval])
    assert ok == backfill.BATCH_DEFERRED
    record_import.assert_not_awaited()  # never import without a durable dirty_from
    # In-memory marker must be cleared so a later debounced progress save
    # cannot persist a phantom dirty_from that never reached disk.
    assert coord.import_store.dirty_from is None


async def test_deferred_batch_progress_save_does_not_persist_phantom_dirty(monkeypatch):
    """Hourly caller progress save after DEFERRED must not write dirty_from."""
    store = ImportStoreData(account_key="k")
    coord = SimpleNamespace(
        import_store=store,
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
    saved_payloads: list[ImportStoreData] = []

    async def _timeout_then_record(hass, entry_id, data, *, critical=True):  # noqa: ARG001
        if critical:
            raise TimeoutError
        # Capture a snapshot of the fields that matter for the phantom leak.
        saved_payloads.append(
            ImportStoreData(
                account_key=data.account_key,
                dirty_from=data.dirty_from,
                failed_local_dates=list(data.failed_local_dates),
            )
        )

    monkeypatch.setattr(backfill, "async_save_import_state", _timeout_then_record)
    monkeypatch.setattr(
        backfill,
        "async_import_with_baseline",
        AsyncMock(return_value=SimpleNamespace(cost_failed_days=[])),
    )

    ok = await backfill._async_import_batch(_FakeHass(), "entry1", coord, [interval])
    assert ok == backfill.BATCH_DEFERRED
    assert store.dirty_from is None

    # Mimic the hourly caller after DEFERRED: progress save only, days stay
    # incomplete and are not classified as failed.
    await backfill._async_save_checkpoint(_FakeHass(), "entry1", store)
    assert saved_payloads, "expected a debounced progress save after DEFERRED"
    assert all(payload.dirty_from is None for payload in saved_payloads)
    assert store.failed_local_dates == []


def _tier_coord(store: ImportStoreData) -> SimpleNamespace:
    return SimpleNamespace(
        import_store=store,
        import_lock=asyncio.Lock(),
        account_key="acct",
        account_id="aid",
        entry=SimpleNamespace(options={}, data={}),
        async_refresh_lifetime_totals=AsyncMock(),
        update_sync_progress=MagicMock(),
        async_persist_sync_progress=AsyncMock(),
        async_get_usage_with_auth_retry=AsyncMock(),
    )


async def test_hourly_deferred_does_not_mark_days_failed(monkeypatch):
    """A deferred hourly batch stays incomplete — not classified as failed."""
    day = date(2024, 1, 15)
    store = ImportStoreData(account_key="k")
    coord = _tier_coord(store)
    interval = SimpleNamespace(
        start=datetime(2024, 1, 15, 8, tzinfo=UTC),
        end=datetime(2024, 1, 15, 9, tzinfo=UTC),
    )

    async def _fetch(_coordinator, fetched_day):
        return fetched_day, [interval]

    monkeypatch.setattr(backfill, "BACKFILL_DELAY_BETWEEN_CHUNKS", 0)
    monkeypatch.setattr(backfill, "_concurrency", lambda _c: 1)
    monkeypatch.setattr(backfill, "async_fetch_hourly_day", _fetch)
    monkeypatch.setattr(backfill, "clip_hourly_to_local_day", lambda _d, iv: iv)
    monkeypatch.setattr(backfill, "validate_hourly_day", lambda *_a, **_k: (True, "ok"))
    monkeypatch.setattr(backfill, "explicit_gap_intervals", lambda _clipped: [])
    monkeypatch.setattr(backfill, "is_invalid_closed_day", lambda *_a, **_k: False)
    monkeypatch.setattr(backfill, "_async_import_batch", AsyncMock(return_value=backfill.BATCH_DEFERRED))
    monkeypatch.setattr(backfill, "async_save_import_state", AsyncMock())

    await backfill._async_backfill_hourly(_FakeHass(), "entry1", coord, day, day)
    assert store.failed_local_dates == []
    assert day.isoformat() not in store.completed_local_dates


async def test_hourly_failed_still_marks_days_failed(monkeypatch):
    """A real recorder import failure still records the day as failed."""
    day = date(2024, 1, 15)
    store = ImportStoreData(account_key="k")
    coord = _tier_coord(store)
    interval = SimpleNamespace(
        start=datetime(2024, 1, 15, 8, tzinfo=UTC),
        end=datetime(2024, 1, 15, 9, tzinfo=UTC),
    )

    async def _fetch(_coordinator, fetched_day):
        return fetched_day, [interval]

    monkeypatch.setattr(backfill, "BACKFILL_DELAY_BETWEEN_CHUNKS", 0)
    monkeypatch.setattr(backfill, "_concurrency", lambda _c: 1)
    monkeypatch.setattr(backfill, "async_fetch_hourly_day", _fetch)
    monkeypatch.setattr(backfill, "clip_hourly_to_local_day", lambda _d, iv: iv)
    monkeypatch.setattr(backfill, "validate_hourly_day", lambda *_a, **_k: (True, "ok"))
    monkeypatch.setattr(backfill, "explicit_gap_intervals", lambda _clipped: [])
    monkeypatch.setattr(backfill, "is_invalid_closed_day", lambda *_a, **_k: False)
    monkeypatch.setattr(backfill, "_async_import_batch", AsyncMock(return_value=backfill.BATCH_FAILED))
    monkeypatch.setattr(backfill, "async_save_import_state", AsyncMock())

    await backfill._async_backfill_hourly(_FakeHass(), "entry1", coord, day, day)
    assert day.isoformat() in store.failed_local_dates
    assert day.isoformat() not in store.completed_local_dates


async def test_daily_deferred_does_not_mark_days_failed(monkeypatch):
    """A deferred daily batch stays incomplete — not classified as failed."""
    from decimal import Decimal

    from custom_components.pge_energy.models import UsageInterval, UsageResolution, UsageResponse

    day = date(2024, 1, 15)
    store = ImportStoreData(account_key="k")
    coord = _tier_coord(store)
    start = datetime(2024, 1, 15, 8, tzinfo=UTC)
    iv = UsageInterval(
        account_key="k",
        resolution=UsageResolution.DAILY,
        start=start,
        end=start + timedelta(days=1),
        kwh=Decimal("1"),
        amount=Decimal("0.1"),
        temperature=None,
        usage_status="kWh-Delivered",
        interval_size=None,
        source_timestamp=None,
    )
    coord.async_get_usage_with_auth_retry = AsyncMock(
        return_value=UsageResponse(
            resolution=UsageResolution.DAILY,
            intervals=[iv],
            total_kwh=None,
            total_cost=None,
            is_tod=None,
            acct_type=None,
        )
    )
    monkeypatch.setattr(backfill, "BACKFILL_DELAY_BETWEEN_CHUNKS", 0)
    monkeypatch.setattr(backfill, "_async_import_batch", AsyncMock(return_value=backfill.BATCH_DEFERRED))
    monkeypatch.setattr(backfill, "async_save_import_state", AsyncMock())

    await backfill._async_backfill_daily(_FakeHass(), "entry1", coord, day, day)
    assert store.failed_local_dates == []
    assert day.isoformat() not in store.completed_local_dates


async def test_postimport_checkpoint_is_enqueued_not_inline(monkeypatch):
    """Post-import saves ride the debounced writer instead of blocking the tier."""
    calls: list[str] = []
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
    criticals: list[bool] = []

    async def _record_save(hass, entry_id, data, *, critical=True):  # noqa: ARG001
        criticals.append(critical)
        if not critical:
            return
        calls.append("durable")

    async def _record_import(*args, **kwargs):  # noqa: ARG002, ARG001
        return SimpleNamespace(cost_failed_days=[])

    monkeypatch.setattr(backfill, "async_save_import_state", _record_save)
    monkeypatch.setattr(backfill, "async_import_with_baseline", _record_import)

    ok = await backfill._async_import_batch(_FakeHass(), "entry1", coord, [interval])
    assert ok == backfill.BATCH_OK
    assert calls == ["durable"]  # exactly one inline durable write: pre-import
    assert criticals == [True, False]  # post-import save enqueued debounced


async def test_timeout_matrix_critical_raises_noncritical_swallows(monkeypatch, patched_store):
    """Timeout re-raises for critical callers and is swallowed for cosmetic ones."""
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_TIMEOUT", 0.05)
    patched_store.delay = 10.0
    hass = _FakeHass()
    data = ImportStoreData(account_key="k")

    with pytest.raises(TimeoutError):
        await async_save_import_state(hass, "entry1", data, critical=True)
    # The timed-out write keeps running behind the shield and is tracked per
    # entry so later writes can order behind it.
    state = store_mod._SAVE_STATES["entry1"]
    assert state.inflight is not None and not state.inflight.done()

    # Non-critical schedules the writer; the writer must await the parked
    # in-flight operation instead of starting a newer overlapping write, so
    # its bounded wait also times out against the SAME stuck write.
    await async_save_import_state(hass, "entry1", data, critical=False)
    await asyncio.sleep(0.3)
    assert patched_store.calls == 1  # newer write deferred; original still parked


class _OrderedStore(_FakeStore):
    """Fake store recording start/finish order with per-write delays."""

    def __init__(self) -> None:
        super().__init__()
        self.delays: list[float] = []
        self.order: list[str] = []

    async def async_save(self, payload):
        self.calls += 1
        self.order.append(f"start:{payload['sync_done'] or 'empty'}")
        delay = self.delays[min(len(self.saves), len(self.delays) - 1)] if self.delays else 0.0
        if delay:
            await asyncio.sleep(delay)
        self.saves.append(payload)
        self.order.append(f"done:{payload['sync_done'] or 'empty'}")

    async def async_load(self):
        return self.saves[-1] if self.saves else None


async def test_next_write_awaits_parked_inflight_before_writing(monkeypatch):
    """A later save waits out the timed-out executor write — never overlaps."""
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_TIMEOUT", 0.06)
    ordered = _OrderedStore()
    ordered.delays = [0.1, 0.0]
    hass = _FakeHass()
    with patch.object(store_mod, "_store_for_entry", return_value=ordered):
        data = ImportStoreData(account_key="k")
        data.sync_done = 1
        with pytest.raises(TimeoutError):
            await async_save_import_state(hass, "entry1", data, critical=True)
        state = store_mod._SAVE_STATES["entry1"]
        assert state.inflight is not None and not state.inflight.done()
        assert ordered.order == ["start:1"]

        data.sync_done = 2
        await async_save_import_state(hass, "entry1", data, critical=True)

    # Payload 1 finished BEFORE payload 2 started: strict on-disk ordering.
    assert ordered.order == ["start:1", "done:1", "start:2", "done:2"]
    assert ordered.saves[-1]["sync_done"] == 2
    assert store_mod._SAVE_STATES["entry1"].inflight is None


async def test_clear_lands_after_parked_stale_write(monkeypatch):
    """Clear awaits the timed-out stale write so emptied state cannot be resurrected."""
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_TIMEOUT", 0.06)
    ordered = _OrderedStore()
    ordered.delays = [0.1, 0.0]
    hass = _FakeHass()
    with patch.object(store_mod, "_store_for_entry", return_value=ordered):
        data = ImportStoreData(
            account_key="stale",
            sync_status="backfilling",
            dirty_from="2024-01-01T00:00:00-08:00",
        )
        data.sync_done = 7
        with pytest.raises(TimeoutError):
            await async_save_import_state(hass, "entry1", data, critical=True)
        assert ordered.order == ["start:7"]

        await async_clear_import_state(hass, "entry1")

    last = ordered.saves[-1]
    assert ordered.order == ["start:7", "done:7", "start:empty", "done:empty"]
    assert last["completed_local_dates"] == []
    assert last["sync_status"] is None
    assert ordered.saves[0]["sync_status"] == "backfilling"  # stale write did land first
    state = store_mod._SAVE_STATES["entry1"]
    assert state.data is None and state.dirty is False
    assert state.last_written_hash is not None


async def test_content_dedupe_skips_unchanged_payload_and_last_commit(patched_store):
    """Identical payloads hit dedupe: no second write, no last_commit bump."""
    hass = _FakeHass()
    data = ImportStoreData(account_key="k", sync_done=3)
    await async_save_import_state(hass, "entry1", data, critical=True)
    first_commit = data.last_commit
    assert patched_store.calls == 1

    await async_save_import_state(hass, "entry1", data, critical=True)
    assert patched_store.calls == 1  # deduped
    assert data.last_commit == first_commit

    data.sync_done = 4  # mutation changes the payload → real write again
    await async_save_import_state(hass, "entry1", data, critical=True)
    assert patched_store.calls == 2
    assert patched_store.saves[-1]["sync_done"] == 4


async def test_clear_cancels_pending_writer_so_it_cannot_resurrect_data(patched_store):
    """async_clear_import_state flushes/cancels first; cleared state stays cleared."""
    hass = _FakeHass()
    data = ImportStoreData(account_key="k", sync_status="backfilling")
    await async_save_import_state(hass, "entry1", data, critical=False)
    await async_clear_import_state(hass, "entry1")
    await asyncio.sleep(0.15)  # give any leaked writer a chance to misbehave

    last = patched_store.saves[-1]
    assert last["sync_status"] is None
    assert last["completed_local_dates"] == []
    state = store_mod._SAVE_STATES["entry1"]
    assert state.dirty is False
    assert state.data is None


async def test_discard_store_cache_cancels_pending_task(fake_store):
    """Unloading drops per-entry save coordination and cancels the writer."""
    hass = _FakeHass()

    class _HassStore(_FakeStore):
        def __init__(self):
            super().__init__()
            self.hass = hass

    with patch.object(store_mod, "_store_for_entry", return_value=_HassStore()):
        data = ImportStoreData(account_key="k")
        await async_save_import_state(hass, "entry9", data, critical=False)
        state = store_mod._SAVE_STATES.get("entry9")
        assert state is not None and state.task is not None
        discard_store_cache("entry9")
        await asyncio.sleep(0.05)
        assert "entry9" not in store_mod._SAVE_STATES
        assert state.task.cancelled() or state.task.done()


async def test_flush_after_pending_critical_supersedes_debounced_state(patched_store):
    """Flush lands the newest shared state durably even mid-debounce."""
    hass = _FakeHass()
    data = ImportStoreData(account_key="k")
    await async_save_import_state(hass, "entry1", data, critical=False)
    data.newest_interval = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    await async_flush_import_state(hass, "entry1", data=data)
    assert patched_store.calls == 1
    assert patched_store.saves[0]["newest_interval"] == data.newest_interval


async def test_flush_reraises_caller_cancellation(patched_store):
    """Watchdog/shutdown cancellation of flush propagates — no extra 60s write."""
    hass = _FakeHass()
    data = ImportStoreData(account_key="k")
    patched_store.delay = 0.5
    await async_save_import_state(hass, "entryX", data, critical=False)
    await asyncio.sleep(0.06)  # writer entered store.async_save (writing=True)
    flushed = asyncio.create_task(async_flush_import_state(hass, "entryX"))
    await asyncio.sleep(0.05)
    flushed.cancel()
    with pytest.raises(asyncio.CancelledError):
        await flushed
    assert flushed.cancelled()
    await asyncio.sleep(0.55)  # let the in-flight writer finish; no inline duplicate
    assert patched_store.calls == 1


async def test_clear_does_not_persist_stale_payload(patched_store):
    """Clearing discards the pending write instead of flushing it to disk first."""
    hass = _FakeHass()
    data = ImportStoreData(account_key="stale", completed_local_dates=["2024-05-01"])
    await async_save_import_state(hass, "entry1", data, critical=False)
    await async_clear_import_state(hass, "entry1")
    await asyncio.sleep(0.15)

    # Exactly one disk write happened: the empty clear payload.
    assert len(patched_store.saves) == 1
    assert patched_store.saves[0]["completed_local_dates"] == []
    assert patched_store.saves[0]["account_key"] == ""
    # The empty write went through the bounded path and recorded its digest.
    assert store_mod._SAVE_STATES["entry1"].last_written_hash is not None


async def test_reverted_payload_after_completed_timeout_is_rewritten(monkeypatch):
    """A completed timed-out write invalidates dedupe: reverts force a rewrite."""
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_TIMEOUT", 0.06)
    ordered = _OrderedStore()
    ordered.delays = [0.0, 0.1, 0.0]
    hass = _FakeHass()
    with patch.object(store_mod, "_store_for_entry", return_value=ordered):
        data = ImportStoreData(account_key="k")
        data.sync_done = 1
        await async_save_import_state(hass, "entry1", data, critical=True)
        baseline_hash = store_mod._SAVE_STATES["entry1"].last_written_hash
        assert baseline_hash is not None

        data.dirty_from = "2024-02-01"
        with pytest.raises(TimeoutError):
            await async_save_import_state(hass, "entry1", data, critical=True)
        # The parked executor-side write finishes BETWEEN saves.
        await asyncio.sleep(0.08)
        state = store_mod._SAVE_STATES["entry1"]
        assert state.inflight is not None and state.inflight.done()

        # Revert memory to the pre-timeout payload: digest matches the old
        # hash, but the disk now holds the timed-out content — must rewrite.
        data.dirty_from = None
        await async_save_import_state(hass, "entry1", data, critical=True)

    assert ordered.calls == 3
    assert ordered.saves[-1]["dirty_from"] is None
    state = store_mod._SAVE_STATES["entry1"]
    assert state.inflight is None
    assert state.last_written_hash is not None


async def test_discard_keeps_coordination_until_parked_write_drains(monkeypatch):
    """Unload drops the Store but orders reload writes behind the parked one."""
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_TIMEOUT", 0.06)
    ordered = _OrderedStore()
    ordered.delays = [0.09, 0.0]
    hass = _FakeHass()
    with patch.object(store_mod, "_store_for_entry", return_value=ordered):
        data = ImportStoreData(account_key="k")
        data.sync_done = 1
        with pytest.raises(TimeoutError):
            await async_save_import_state(hass, "entry1", data, critical=True)
        state = store_mod._SAVE_STATES["entry1"]

        discard_store_cache("entry1")
        # The Store is dropped immediately; coordination survives until drain.
        assert "entry1" not in store_mod._STORES
        assert store_mod._SAVE_STATES.get("entry1") is state

        # A prompt reload starts fresh saves that must order behind the old write.
        data.sync_done = 2
        await async_save_import_state(hass, "entry1", data, critical=True)
        assert ordered.order == ["start:1", "done:1", "start:2", "done:2"]

        await asyncio.sleep(0.01)  # drain callback fires — but the reload SAVED,
        # claiming the state, so it must NOT have been released by the callback.
        assert store_mod._SAVE_STATES.get("entry1") is state

        # A later unload with nothing parked cleans up normally.
        discard_store_cache("entry1")
        assert "entry1" not in store_mod._SAVE_STATES


async def test_concurrent_timeout_keeps_single_tracked_write(monkeypatch):
    """Per-entry lock: a second concurrent save reconciles instead of overlapping."""
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_TIMEOUT", 0.06)
    ordered = _OrderedStore()
    ordered.delays = [0.15, 0.15]
    hass = _FakeHass()
    with patch.object(store_mod, "_store_for_entry", return_value=ordered):
        data_a = ImportStoreData(account_key="k")
        data_a.sync_done = 1
        data_b = ImportStoreData(account_key="k")
        data_b.sync_done = 2

        results = await asyncio.gather(
            async_save_import_state(hass, "entry1", data_a, critical=True),
            async_save_import_state(hass, "entry1", data_b, critical=True),
            return_exceptions=True,
        )
        assert all(isinstance(r, TimeoutError) for r in results)

        state = store_mod._SAVE_STATES["entry1"]
        # Exactly ONE filesystem write is parked and tracked: the concurrent
        # caller deferred behind it instead of overwriting state.inflight.
        assert ordered.calls == 1
        assert state.inflight is not None and not state.inflight.done()

        await asyncio.sleep(0.06)  # let the parked write drain
        assert ordered.order == ["start:1", "done:1"]


async def test_load_awaits_parked_write_before_hydrating(monkeypatch):
    """A prompt reload reads the file only after the parked write lands."""
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_TIMEOUT", 0.08)
    ordered = _OrderedStore()
    ordered.delays = [0.12]
    hass = _FakeHass()
    with patch.object(store_mod, "_store_for_entry", return_value=ordered):
        data = ImportStoreData(account_key="k")
        data.sync_done = 9
        with pytest.raises(TimeoutError):
            await async_save_import_state(hass, "entry1", data, critical=True)
        assert ordered.saves == []  # write still parked

        loaded = await async_load_import_state(hass, "entry1")
        assert loaded.sync_done == 9  # hydrated AFTER the parked write landed
        assert ordered.order == ["start:9", "done:9"]


class _FirstWriteFailsStore(_OrderedStore):
    """First save stalls past any window then fails executor-side."""

    def __init__(self) -> None:
        super().__init__()
        self._first_attempt_started = False

    async def async_save(self, payload):
        if not self._first_attempt_started:
            self._first_attempt_started = True
            self.calls += 1
            self.order.append(f"start:{payload['sync_done']}")
            await asyncio.sleep(0.15)
            raise OSError("storage went away mid-write")
        await super().async_save(payload)


async def test_reconcile_retrieves_completed_failed_parked_write(monkeypatch):
    """Awaiting an already-failed parked task retrieves its exception cleanly."""
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_TIMEOUT", 0.06)
    ordered = _FirstWriteFailsStore()
    hass = _FakeHass()
    with patch.object(store_mod, "_store_for_entry", return_value=ordered):
        data = ImportStoreData(account_key="k")
        data.sync_done = 1
        with pytest.raises(TimeoutError):
            await async_save_import_state(hass, "entry1", data, critical=True)

        # Let the parked write FAIL on disk before the next save.
        await asyncio.sleep(0.12)
        state = store_mod._SAVE_STATES["entry1"]
        assert state.inflight.done()

        data.sync_done = 2
        await async_save_import_state(hass, "entry1", data, critical=True)
        assert ordered.saves[-1]["sync_done"] == 2
        assert store_mod._SAVE_STATES["entry1"].inflight is None
        assert store_mod._SAVE_STATES["entry1"].last_written_hash is not None


async def test_load_raises_when_parked_write_exceeds_window(monkeypatch):
    """Reload must abort (setup retries) rather than read a stale file."""
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_TIMEOUT", 0.05)
    ordered = _OrderedStore()
    ordered.delays = [0.4]
    hass = _FakeHass()
    with patch.object(store_mod, "_store_for_entry", return_value=ordered):
        data = ImportStoreData(account_key="k")
        data.sync_done = 3
        with pytest.raises(TimeoutError):
            await async_save_import_state(hass, "entry1", data, critical=True)

        with pytest.raises(TimeoutError):
            await async_load_import_state(hass, "entry1")
        assert ordered.saves == []  # nothing was read mid-write or overwritten


async def test_critical_save_snapshots_before_lock_wait(monkeypatch):
    """A critical checkpoint persists call-time state even if mutated mid-wait."""
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_TIMEOUT", 0.06)
    ordered = _OrderedStore()
    ordered.delays = [0.09, 0.0]
    hass = _FakeHass()
    with patch.object(store_mod, "_store_for_entry", return_value=ordered):
        shared = ImportStoreData(account_key="k")
        shared.sync_done = 1
        shared.dirty_from = "2024-03-01T00:00:00-08:00"
        with pytest.raises(TimeoutError):
            await async_save_import_state(hass, "entry1", shared, critical=True)

        # Concurrent critical checkpoint while the parked write drains; another
        # task clears the shared dirty_from mid-wait (backfill/poll pattern).
        saver = asyncio.create_task(async_save_import_state(hass, "entry1", shared, critical=True))
        await asyncio.sleep(0.005)
        shared.dirty_from = None
        await saver

    assert ordered.saves[-1]["dirty_from"] == "2024-03-01T00:00:00-08:00"


async def test_discard_consumes_completed_failed_inflight(monkeypatch):
    """Unloading right after a parked write failed must retrieve its exception."""
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_TIMEOUT", 0.06)
    ordered = _FirstWriteFailsStore()
    hass = _FakeHass()
    with patch.object(store_mod, "_store_for_entry", return_value=ordered):
        data = ImportStoreData(account_key="k")
        data.sync_done = 1
        with pytest.raises(TimeoutError):
            await async_save_import_state(hass, "entry1", data, critical=True)
        await asyncio.sleep(0.12)  # the parked write fails on disk
        assert store_mod._SAVE_STATES["entry1"].inflight.done()

        discard_store_cache("entry1")
        assert "entry1" not in store_mod._SAVE_STATES


async def test_critical_snapshot_survives_flush_writer_wait(patched_store):
    """Critical checkpoint keeps call-time content across the busy-writer wait."""
    hass = _FakeHass()
    patched_store.delay = 0.4
    shared = ImportStoreData(account_key="k")
    await async_save_import_state(hass, "entry1", shared, critical=False)
    await asyncio.sleep(0.06)  # writer entered store.async_save (writing=True)
    assert store_mod._SAVE_STATES["entry1"].writing is True

    shared.dirty_from = "2024-04-01T00:00:00-08:00"
    crit = asyncio.create_task(async_save_import_state(hass, "entry1", shared, critical=True))
    await asyncio.sleep(0.01)  # snapshot taken; now blocked on the writer task
    shared.dirty_from = None  # concurrent backfill/poll mutation mid-wait
    await crit

    # The landed checkpoint carries the call-time marker, not the mutation;
    # the requeue then lands the newer shared state behind it.
    assert patched_store.saves[-1]["dirty_from"] == "2024-04-01T00:00:00-08:00"
    await asyncio.sleep(0.5)
    assert patched_store.calls == 3
    assert patched_store.saves[-1]["dirty_from"] is None


async def test_flush_requeues_state_newer_than_critical_snapshot(patched_store):
    """Newer shared state survives a stale critical snapshot overwrite."""
    hass = _FakeHass()
    patched_store.delay = 0.05
    shared = ImportStoreData(account_key="k")
    shared.sync_done = 1
    await async_save_import_state(hass, "entry1", shared, critical=False)
    await asyncio.sleep(0.06)  # writer entered store.async_save (writing=True)
    assert store_mod._SAVE_STATES["entry1"].writing is True

    # Critical checkpoint snapshots call-time state (sync_done=1) and waits out
    # the busy writer...
    crit = asyncio.create_task(async_save_import_state(hass, "entry1", shared, critical=True))
    await asyncio.sleep(0.01)
    # ...while a non-critical save marks newer state the writer will consume.
    shared.sync_done = 2
    await async_save_import_state(hass, "entry1", shared, critical=False)
    await crit
    await asyncio.sleep(0.35)

    # Writer(1) -> queued writer consumes newer(2). The stale snapshot may
    # dedupe or land before a requeue; either way nothing newer is ever lost.
    sync_values = [s.get("sync_done") for s in patched_store.saves]
    assert sync_values[-1] == 2
    assert patched_store.saves[-1]["sync_done"] == 2


async def test_save_queued_behind_load_discarded_after_bind(monkeypatch):
    """A save entering during a reload is discarded once the load binds."""
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_TIMEOUT", 5.0)
    hass = _FakeHass()

    class _GatedLoadStore(_OrderedStore):
        def __init__(self) -> None:
            super().__init__()
            self.load_started = asyncio.Event()
            self.release_load = asyncio.Event()

        async def async_load(self):
            self.load_started.set()
            await self.release_load.wait()
            return {"account_key": "disk", "sync_done": 5}

    gated = _GatedLoadStore()
    with patch.object(store_mod, "_store_for_entry", return_value=gated):
        # Reload holds the per-entry lock while reading.
        loader = asyncio.create_task(async_load_import_state(hass, "entry1"))
        await gated.load_started.wait()

        # An old-run background task enters before the load binds its object.
        straggler = ImportStoreData(account_key="straggler", sync_done=99)
        saver = asyncio.create_task(async_save_import_state(hass, "entry1", straggler, critical=True))
        await asyncio.sleep(0.01)  # saver queued behind the load lock

        gated.release_load.set()  # load completes and binds the loaded object
        await asyncio.gather(loader, saver)
        await asyncio.sleep(0.05)

    assert all(s.get("account_key") != "straggler" for s in gated.saves)


async def test_cancelled_clear_schedules_prior_restore():
    """A cancelled reset still restores the prior payload behind the empty."""
    hass = _FakeHass()

    class _GatedStore(_OrderedStore):
        def __init__(self) -> None:
            super().__init__()
            self.empty_started = asyncio.Event()
            self.release_empty = asyncio.Event()

        async def async_save(self, payload):
            if payload.get("account_key") == "":
                self.empty_started.set()
                await self.release_empty.wait()
            await super().async_save(payload)

    gated = _GatedStore()
    with patch.object(store_mod, "_store_for_entry", return_value=gated):
        data = ImportStoreData(
            account_key="k",
            sync_status="complete",
            completed_local_dates=["2024-01-01"],
        )
        await async_save_import_state(hass, "entry1", data, critical=True)

        clearer = asyncio.create_task(async_clear_import_state(hass, "entry1"))
        await gated.empty_started.wait()  # empty parked mid-write
        clearer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await clearer

        gated.release_empty.set()  # empty lands; restore orders behind it
        await asyncio.sleep(0.1)

    assert [s.get("account_key") for s in gated.saves] == ["k", "", "k"]
    assert gated.saves[-1]["completed_local_dates"] == ["2024-01-01"]
    assert gated.saves[-1]["sync_status"] == "complete"


async def test_restore_rechecks_epoch_under_lock(monkeypatch):
    """A newer reset that wins the lock race stays authoritative over restore."""
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_TIMEOUT", 5.0)
    hass = _FakeHass()
    state = store_mod._save_state("entry1")
    state.clear_epoch = 7
    prior_obj = ImportStoreData(account_key="old", sync_done=1)
    prior_payload = prior_obj.to_dict()

    writes: list[str] = []

    async def fake_write(hass, entry_id, data, **kwargs):  # noqa: ARG001
        writes.append(entry_id)

    lock_held = asyncio.Event()
    release_lock = asyncio.Event()

    async def block_then_reset():
        # A newer reset queued behind another writer grabs the lock first and
        # bumps clear_epoch while holding it.
        async with state.lock:
            lock_held.set()
            await release_lock.wait()
            state.clear_epoch += 1

    with patch.object(store_mod, "_write_payload_locked", side_effect=fake_write):
        resetter = asyncio.create_task(block_then_reset())
        await lock_held.wait()
        restore = asyncio.create_task(
            store_mod._restore_prior_payload(
                hass,
                "entry1",
                prior_obj,
                prior_payload,
                state,
                7,
            )
        )
        await asyncio.sleep(0.05)  # restore passes the pre-lock guard, queues on the lock
        release_lock.set()
        await asyncio.gather(resetter, restore)

    # The pre-lock guard passed (epoch still 7), but the epoch moved while the
    # restore waited — it must skip instead of resurrecting over the newer
    # reset's empty payload.
    assert writes == []


async def test_flush_queued_behind_load_discarded_after_bind(monkeypatch):
    """A crossed critical flush cannot overwrite freshly reloaded state."""
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_TIMEOUT", 5.0)
    hass = _FakeHass()

    class _GatedLoadStore(_OrderedStore):
        def __init__(self) -> None:
            super().__init__()
            self.load_started = asyncio.Event()
            self.release_load = asyncio.Event()

        async def async_load(self):
            self.load_started.set()
            await self.release_load.wait()
            return {"account_key": "disk", "sync_done": 5}

    gated = _GatedLoadStore()
    with patch.object(store_mod, "_store_for_entry", return_value=gated):
        # Reload holds the per-entry lock while reading.
        loader = asyncio.create_task(async_load_import_state(hass, "entry1"))
        await gated.load_started.wait()

        # A pre-reload critical flush queues behind the load lock.
        stale = ImportStoreData(account_key="stale", sync_status="backfilling")
        flusher = asyncio.create_task(async_flush_import_state(hass, "entry1", data=stale))
        await asyncio.sleep(0.01)  # flush queued behind the load lock

        gated.release_load.set()  # load binds its object and releases
        await asyncio.gather(loader, flusher)
        await asyncio.sleep(0.05)

    assert all(s.get("account_key") != "stale" for s in gated.saves)


async def test_discarded_critical_save_reports_false_real_layer(patched_store):
    """Real store layer: stale critical save returns False (not silent success)."""
    hass = _FakeHass()
    old = ImportStoreData(account_key="old", sync_done=1)
    fresh = ImportStoreData(account_key="fresh")
    await async_save_import_state(hass, "entry1", old, critical=True)
    store_mod.bind_import_state_object(hass, "entry1", fresh)
    await async_clear_import_state(hass, "entry1")

    result = await async_save_import_state(hass, "entry1", old, critical=True)
    assert result is False  # propagated through wrapper/flush/save chain

    result_ok = await async_save_import_state(hass, "entry1", fresh, critical=True)
    assert result_ok is not False


async def test_deferred_write_keeps_dirty_for_retry(monkeypatch):
    """A deferred/timed-out pass keeps dirty so the newest payload is retried."""
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_TIMEOUT", 0.06)
    hass = _FakeHass()

    class _SlowOnceStore:
        """First write stalls past the window; later writes are instant."""

        def __init__(self) -> None:
            self.saves: list[dict] = []
            self.calls = 0

        async def async_save(self, payload):
            self.calls += 1
            if self.calls == 1:
                await asyncio.sleep(0.15)  # outlast the timeout window once
            self.saves.append(payload)

    slow = _SlowOnceStore()
    with patch.object(store_mod, "_store_for_entry", return_value=slow):
        shared = ImportStoreData(account_key="k")
        shared.sync_done = 1
        await async_save_import_state(hass, "entry1", shared, critical=False)
        await asyncio.sleep(0.09)  # pass deferred (timeout) and re-dirtied

        # Newer progress saved to memory only; the re-dirtied writer retries
        # and lands it without any additional save call.
        shared.sync_done = 2
        await asyncio.sleep(0.4)

    assert [w.get("sync_done") for w in slow.saves][-1] == 2


async def test_load_serializes_with_queued_critical_write(monkeypatch):
    """A reload waits out queued writes instead of hydrating mid-flight."""
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_TIMEOUT", 0.06)
    ordered = _OrderedStore()
    ordered.delays = [0.09, 0.02]
    hass = _FakeHass()
    with patch.object(store_mod, "_store_for_entry", return_value=ordered):
        first = ImportStoreData(account_key="k")
        first.sync_done = 1
        with pytest.raises(TimeoutError):
            await async_save_import_state(hass, "entry1", first, critical=True)

        second = ImportStoreData(account_key="k")
        second.sync_done = 2
        saver = asyncio.create_task(async_save_import_state(hass, "entry1", second, critical=True))
        await asyncio.sleep(0.001)  # saver takes the per-entry lock first
        loader = asyncio.create_task(async_load_import_state(hass, "entry1"))
        loaded = await loader
        await saver

    # The read happened after the queued critical write landed, not mid-flight.
    assert loaded.sync_done == 2
    assert ordered.order == ["start:1", "done:1", "start:2", "done:2"]


async def test_clear_remains_authoritative_over_racing_critical_save(monkeypatch):
    """A critical save started mid-reset cannot resurrect wiped checkpoint state."""
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_TIMEOUT", 5.0)
    hass = _FakeHass()

    class _SlowEmptyStore(_OrderedStore):
        """The reset's empty write stalls so a racer queues behind the lock."""

        async def async_save(self, payload):
            if payload.get("account_key") == "":
                await asyncio.sleep(0.15)
            await super().async_save(payload)

    slow = _SlowEmptyStore()
    with patch.object(store_mod, "_store_for_entry", return_value=slow):
        # Reset starts first and holds the per-entry lock across its slow
        # empty write.
        clearer = asyncio.create_task(async_clear_import_state(hass, "entry1"))
        await asyncio.sleep(0.02)  # empty write now in flight
        assert slow.saves == []  # still parked on the stall

        # A correction-style critical checkpoint snapshots pre-reset state and
        # enters while the reset is running: it must NOT resurrect the marker.
        stale = ImportStoreData(account_key="stale", sync_status="backfilling")
        stale.dirty_from = "2024-05-01T00:00:00-08:00"
        await async_save_import_state(hass, "entry1", stale, critical=True)
        await clearer
        await asyncio.sleep(0.05)

    landed_markers = [s.get("dirty_from") for s in slow.saves]
    assert "2024-05-01T00:00:00-08:00" not in landed_markers
    assert slow.saves[-1]["account_key"] == ""  # reset stays authoritative


async def test_load_claims_state_against_drain_callback(monkeypatch):
    """A draining parked write must not drop coordination a reload is using."""
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_TIMEOUT", 0.06)
    ordered = _OrderedStore()
    ordered.delays = [0.07]
    hass = _FakeHass()
    with patch.object(store_mod, "_store_for_entry", return_value=ordered):
        data = ImportStoreData(account_key="k")
        data.sync_done = 1
        with pytest.raises(TimeoutError):
            await async_save_import_state(hass, "entry1", data, critical=True)
        discard_store_cache("entry1")  # arms the drain callback (draining=True)
        assert store_mod._SAVE_STATES["entry1"].draining is True

        # The load claims the state; the drain callback must leave it alone.
        loaded = await async_load_import_state(hass, "entry1")
        assert loaded.sync_done == 1
        await asyncio.sleep(0.01)
        assert store_mod._SAVE_STATES.get("entry1") is not None

        # And the claimed state still cleans up on unload.
        discard_store_cache("entry1")
        assert "entry1" not in store_mod._SAVE_STATES


async def test_flush_does_not_cache_stale_target_across_reset(monkeypatch):
    """A crossed critical flush must not leave its stale object for unload."""
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_TIMEOUT", 5.0)
    hass = _FakeHass()

    class _SlowEmptyStore(_OrderedStore):
        async def async_save(self, payload):
            if payload.get("account_key") == "":
                await asyncio.sleep(0.12)
            await super().async_save(payload)

    slow = _SlowEmptyStore()
    with patch.object(store_mod, "_store_for_entry", return_value=slow):
        clearer = asyncio.create_task(async_clear_import_state(hass, "entry1"))
        await asyncio.sleep(0.02)  # reset holds the lock; empty write stalling

        stale = ImportStoreData(account_key="stale", sync_status="backfilling")
        saver = asyncio.create_task(async_save_import_state(hass, "entry1", stale, critical=True))
        await asyncio.sleep(0.01)  # entered during the reset
        await clearer
        await saver

        # Unload-time flush with no explicit data must not resurrect stale:
        # the crossed flush never cached its stale object as the target.
        state = store_mod._SAVE_STATES["entry1"]
        assert state.data is None
        await async_flush_import_state(hass, "entry1")
        await asyncio.sleep(0.05)

    assert slow.saves[-1]["account_key"] == ""


async def test_pre_reset_object_saves_are_discarded_after_bind(patched_store):
    """Saves carrying a replaced store object are discarded, never rewritten."""
    hass = _FakeHass()
    old = ImportStoreData(account_key="old", sync_done=1)
    await async_save_import_state(hass, "entry1", old, critical=True)

    # Reset binds a fresh canonical object (coordinator-style replacement).
    fresh = ImportStoreData(account_key="new")
    store_mod.bind_import_state_object(hass, "entry1", fresh)
    await async_clear_import_state(hass, "entry1")

    # A straggler holding the PRE-reset object saves late: discarded outright
    # (no stale payload, and no redundant empty rewrite either).
    old.sync_done = 2
    await async_save_import_state(hass, "entry1", old, critical=True)

    # Non-critical stragglers are dropped as well.
    await async_save_import_state(hass, "entry1", old, critical=False)

    # The bound post-reset object still lands normally; the straggler's own
    # save reported False through the real wrapper/flush chain.
    fresh.sync_done = 3
    result = await async_save_import_state(hass, "entry1", fresh, critical=True)
    assert result is True
    assert patched_store.saves[-1]["account_key"] == "new"
    assert all(s.get("account_key") != "old" for s in patched_store.saves[1:])


async def test_load_rebinds_coordination_for_new_run(patched_store):
    """A reload binds the loaded object so old-run stragglers are rejected."""
    hass = _FakeHass()
    old_run = ImportStoreData(account_key="old-run", sync_done=1)
    await async_save_import_state(hass, "entry1", old_run, critical=True)
    fresh = ImportStoreData(account_key="new-run")
    store_mod.bind_import_state_object(hass, "entry1", fresh)

    loaded = await async_load_import_state(hass, "entry1")
    state = store_mod._SAVE_STATES["entry1"]
    assert state.bound_obj == id(loaded)
    assert state.data is loaded

    # The freshly loaded object saves normally (it IS the canonical object).
    loaded.sync_done = 9
    await async_save_import_state(hass, "entry1", loaded, critical=True)
    assert patched_store.saves[-1]["account_key"] == "old-run"
    assert patched_store.saves[-1]["sync_done"] == 9

    # A straggler from the previous run is rejected against the new binding.
    old_run.sync_done = 7
    await async_save_import_state(hass, "entry1", old_run, critical=False)
    assert patched_store.saves[-1]["sync_done"] == 9


async def test_flush_cancels_stuck_midwrite_writer_instead_of_awaiting_forever(
    monkeypatch,
):
    """A writing debounced writer must not hang flush past the save window."""
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_TIMEOUT", 0.3)

    class _FirstCallStalls(_FakeStore):
        def __init__(self) -> None:
            super().__init__()
            self.release_first = asyncio.Event()

        async def async_save(self, payload):
            self.calls += 1
            if self.calls == 1:
                # Stall only the writer's executor task; the flush's own
                # inline write must order behind the parked task, not this.
                await self.release_first.wait()
            self.saves.append(payload)

    stall_store = _FirstCallStalls()
    hass = _FakeHass()
    data = ImportStoreData(account_key="k")
    data.sync_done = 1
    with patch.object(store_mod, "_store_for_entry", return_value=stall_store):
        await async_save_import_state(hass, "entry1", data, critical=False)
        state = store_mod._SAVE_STATES["entry1"]
        while not (state.task and not state.task.done() and state.writing):
            await asyncio.sleep(0.01)
        writer = state.task

        flush_task = asyncio.get_running_loop().create_task(async_flush_import_state(hass, "entry1"))
        # Regression guard: without the mid-write cancel this wait never
        # completes because the retrying writer never exits its loop.
        done, _ = await asyncio.wait({flush_task}, timeout=2.0)
        assert done, "flush hung awaiting a stuck mid-write debounced writer"
        # Bounded outcome: the flush reconciles behind the still-parked
        # executor write and its critical wait times out (never hangs).
        with pytest.raises(TimeoutError):
            flush_task.result()
        assert writer.done()
        # The writer task was taken over: no orphaned coordination remains.
        assert state.task is None

        stall_store.release_first.set()


async def test_restore_retries_until_parked_write_drains(monkeypatch):
    """A deferred restore retries until it lands behind the parked write."""
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_TIMEOUT", 0.1)

    class _StallableStore(_FakeStore):
        def __init__(self) -> None:
            super().__init__()
            self.stall_next = False
            self.release = asyncio.Event()

        async def async_save(self, payload):
            self.calls += 1
            if self.stall_next:
                self.stall_next = False
                await self.release.wait()
            self.saves.append(payload)

    stall_store = _StallableStore()
    hass = _FakeHass()
    with patch.object(store_mod, "_store_for_entry", return_value=stall_store):
        prior = ImportStoreData(account_key="k")
        prior.sync_done = 1
        await async_save_import_state(hass, "entry1", prior, critical=True)

        # Park an "empty" write the way a timed-out clear leaves it: executor
        # task still running, tracked in state.inflight.
        state = store_mod._save_state("entry1")
        stall_store.stall_next = True
        parked_empty = asyncio.get_running_loop().create_task(stall_store.async_save({"sync_done": 99}))
        state.inflight = parked_empty

        restore_task = asyncio.get_running_loop().create_task(
            store_mod._restore_prior_payload(
                hass,
                "entry1",
                prior,
                prior.to_dict(),
                state,
                state.clear_epoch,
            )
        )
        # Mid-first-window: the restore must be deferring behind the parked
        # write -- nothing beyond the seed has landed and it has not given up.
        await asyncio.sleep(0.04)
        assert not restore_task.done(), "restore finished without its payload landing"
        assert len(stall_store.saves) == 1

        stall_store.release.set()
        await asyncio.wait_for(restore_task, 5.0)
        # The parked empty write drained first; the restored checkpoint landed last.
        assert stall_store.saves[-2]["sync_done"] == 99
        assert stall_store.saves[-1]["sync_done"] == 1


async def test_timed_out_clear_schedules_restore_and_stays_bounded(monkeypatch):
    """A timed-out reset re-raises promptly and restores via a background task."""
    monkeypatch.setattr(store_mod, "IMPORT_STATE_SAVE_TIMEOUT", 0.1)
    hass = _FakeHass()

    class _GatedStore(_OrderedStore):
        def __init__(self) -> None:
            super().__init__()
            self.empty_started = asyncio.Event()
            self.release_empty = asyncio.Event()

        async def async_save(self, payload):
            if payload.get("account_key") == "":
                self.empty_started.set()
                await self.release_empty.wait()
            await super().async_save(payload)

    gated = _GatedStore()
    with patch.object(store_mod, "_store_for_entry", return_value=gated):
        data = ImportStoreData(
            account_key="k",
            sync_status="complete",
            completed_local_dates=["2024-01-01"],
        )
        await async_save_import_state(hass, "entry1", data, critical=True)

        clearer = asyncio.create_task(async_clear_import_state(hass, "entry1"))
        await gated.empty_started.wait()  # empty write parked mid-flight
        started = asyncio.get_running_loop().time()
        # The reset must fail bounded (timeout re-raised) WITHOUT awaiting the
        # never-draining empty write under the persistence lock.
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(clearer, 5.0)
        elapsed = asyncio.get_running_loop().time() - started
        assert elapsed < 1.0, "reset hung awaiting the stalled empty write"
        assert gated.release_empty.is_set() is False

        # The scheduled background restore lands once the empty write drains.
        gated.release_empty.set()
        await asyncio.sleep(0.3)

    assert [s.get("account_key") for s in gated.saves] == ["k", "", "k"]
    assert gated.saves[-1]["completed_local_dates"] == ["2024-01-01"]
    assert gated.saves[-1]["sync_status"] == "complete"
