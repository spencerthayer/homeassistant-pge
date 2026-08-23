from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .bill_pdf_models import BillPdfIndexEntry
from .const import (
    DOMAIN,
    IMPORT_STATE_SAVE_DEBOUNCE_SECONDS,
    IMPORT_STATE_SAVE_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 2
STORAGE_KEY = f"{DOMAIN}.import_state"

# One Store per entry so Store._write_lock serializes concurrent saves.
_STORES: dict[str, ImportStateStore] = {}

# Per-entry debounced-write coordination (dirty flag + pending writer task).
_SAVE_STATES: dict[str, _SaveState] = {}


@dataclass
class _SaveState:
    """Per-entry coordination for coalesced, deduplicated import-state writes."""

    # Latest shared ``ImportStoreData`` instance to persist; callers mutate the
    # same object, so the debounced writer serializes whatever is newest.
    data: ImportStoreData | None = None
    dirty: bool = False
    writing: bool = False
    task: asyncio.Task | None = None
    # Store write currently executing executor-side. ``asyncio.wait_for`` cannot
    # cancel the underlying filesystem operation once submitted, so a timed-out
    # save is kept alive behind ``asyncio.shield`` here and every later write
    # (including the empty clear write) awaits it before writing newer payload.
    inflight: asyncio.Task | None = None
    # Digest of the last successfully-written payload (sans ``last_commit``).
    last_written_hash: str | None = None
    # Serializes the reconcile → dedupe → write sequence per entry so concurrent
    # critical callers cannot race each other's parked in-flight tasks.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # True between ``discard_store_cache`` and drain; cleared when a new save
    # claims the state so the drain callback only releases an unclaimed one.
    draining: bool = False
    # Bumped by ``async_clear_import_state`` while it holds the lock: writers
    # registered before the bump (debounced fire or pre-reset critical snapshot)
    # detect it and yield to the authoritative empty payload.
    clear_epoch: int = 0
    # True for the whole span of a checkpoint reset, so saves that ENTER during
    # one are recognized even though clear_epoch was already bumped at entry.
    clear_inflight: bool = False
    # id() of the store object the post-reset world owns (bound by the reset via
    # bind_import_state_object). Saves carrying any other object are pre-reset
    # stragglers and are discarded, never resurrecting wiped checkpoint state.
    bound_obj: int | None = None


class ImportStateStore(Store):
    """HA Store with v1 → v2 migration for bill PDF index fields."""

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        if old_major_version < STORAGE_VERSION:
            migrated = dict(old_data)
            migrated.setdefault("bill_pdf_index", {})
            migrated.setdefault("bill_pdf_last_success", None)
            migrated.setdefault("bill_pdf_last_error", None)
            migrated["schema_version"] = STORAGE_VERSION
            return migrated
        return old_data


@dataclass
class ImportStoreData:
    """Versioned per-entry import/backfill state."""

    schema_version: int = STORAGE_VERSION
    account_key: str = ""
    target_start: str | None = None
    target_end: str | None = None
    completed_local_dates: list[str] = field(default_factory=list)
    failed_local_dates: list[str] = field(default_factory=list)
    dirty_from: str | None = None
    last_commit: str | None = None
    last_imported_start: str | None = None
    last_imported_end: str | None = None
    # Last-known manual sync / backfill progress (optional; for sensors across reloads).
    sync_status: str | None = None
    sync_phase: str | None = None
    sync_done: int | None = None
    sync_total: int | None = None
    sync_percent: int | None = None
    # Wall-clock ISO when the job started (monotonic values are process-local).
    sync_started_at: str | float | None = None
    sync_eta_seconds: float | None = None
    sync_message: str | None = None
    sync_error: str | None = None
    # Billing / payment ledger import checkpoint (optional; survives reloads).
    billing_history_offset: int = 0
    billing_history_total: int | None = None
    billing_history_complete: bool = False
    billing_last_success: str | None = None
    billing_failed_pages: list[str] = field(default_factory=list)
    billing_last_error: str | None = None
    # One-time clear of entity statistics for monetary mean sensors that no
    # longer carry a state_class (stops STATE_CLASS_REMOVED_ISSUE repairs).
    billing_mirror_cleanup_done: bool = False
    # One-time clear of bill avg temperature entity statistics (stops recorder
    # "Blocked attempt to insert duplicated statistic rows" after the series
    # became external-only).
    bill_avg_temp_mirror_cleanup_done: bool = False
    # One-time split of signed fine-grained consumption/cost into
    # return/compensation series for net-metered accounts.
    signed_usage_split_migration_done: bool = False
    # Bill PDF index and phase summaries (binary retention independent of normalized data).
    bill_pdf_index: dict[str, BillPdfIndexEntry] = field(default_factory=dict)
    bill_pdf_last_success: str | None = None
    bill_pdf_last_error: str | None = None
    # Last-good portal Time of Day pricing snapshot (rates/savings). Additive:
    # keeps the offline rates card warm across reloads without a version bump.
    tod_snapshot: dict[str, Any] | None = None
    # Last-good net-metering statement fields (diagnostic strings until UAT).
    net_metering_snapshot: dict[str, Any] | None = None
    # Last-good TOD vs Basic rate-compare aggregates (diagnostic).
    rate_compare_snapshot: dict[str, Any] | None = None
    # Last-good tip/billing sensor snapshots so cold-boot soft-fail does not
    # leave entities at ``unknown`` when history/checkpoints alone exist.
    account_snapshot: dict[str, Any] | None = None
    programs_snapshot: dict[str, Any] | None = None
    tracker_estimates: dict[str, Any] | None = None
    tip_intervals: list[dict[str, Any]] = field(default_factory=list)
    last_successful_update: str | None = None
    newest_interval: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["bill_pdf_index"] = {k: v.to_dict() for k, v in self.bill_pdf_index.items()}
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ImportStoreData:
        if not data:
            return cls()
        started_raw = data.get("sync_started_at")
        tip_raw = data.get("tip_intervals")
        return cls(
            schema_version=int(data.get("schema_version", STORAGE_VERSION)),
            account_key=str(data.get("account_key", "")),
            target_start=data.get("target_start"),
            target_end=data.get("target_end"),
            completed_local_dates=list(data.get("completed_local_dates") or []),
            failed_local_dates=list(data.get("failed_local_dates") or []),
            dirty_from=data.get("dirty_from"),
            last_commit=data.get("last_commit"),
            last_imported_start=data.get("last_imported_start"),
            last_imported_end=data.get("last_imported_end"),
            sync_status=data.get("sync_status"),
            sync_phase=data.get("sync_phase"),
            sync_done=int(data["sync_done"]) if data.get("sync_done") is not None else None,
            sync_total=int(data["sync_total"]) if data.get("sync_total") is not None else None,
            sync_percent=(int(data["sync_percent"]) if data.get("sync_percent") is not None else None),
            sync_started_at=started_raw,
            sync_eta_seconds=(float(data["sync_eta_seconds"]) if data.get("sync_eta_seconds") is not None else None),
            sync_message=data.get("sync_message"),
            sync_error=data.get("sync_error"),
            billing_history_offset=int(data.get("billing_history_offset", 0) or 0),
            billing_history_total=(
                int(data["billing_history_total"]) if data.get("billing_history_total") is not None else None
            ),
            billing_history_complete=bool(data.get("billing_history_complete", False)),
            billing_last_success=data.get("billing_last_success"),
            billing_failed_pages=list(data.get("billing_failed_pages") or []),
            billing_last_error=data.get("billing_last_error"),
            billing_mirror_cleanup_done=bool(data.get("billing_mirror_cleanup_done", False)),
            bill_avg_temp_mirror_cleanup_done=bool(data.get("bill_avg_temp_mirror_cleanup_done", False)),
            signed_usage_split_migration_done=bool(data.get("signed_usage_split_migration_done", False)),
            bill_pdf_index=_load_bill_pdf_index(data),
            bill_pdf_last_success=data.get("bill_pdf_last_success"),
            bill_pdf_last_error=data.get("bill_pdf_last_error"),
            tod_snapshot=_load_tod_snapshot(data),
            net_metering_snapshot=_load_dict_snapshot(data, "net_metering_snapshot"),
            rate_compare_snapshot=_load_dict_snapshot(data, "rate_compare_snapshot"),
            account_snapshot=_load_dict_snapshot(data, "account_snapshot"),
            programs_snapshot=_load_dict_snapshot(data, "programs_snapshot"),
            tracker_estimates=_load_dict_snapshot(data, "tracker_estimates"),
            tip_intervals=list(tip_raw) if isinstance(tip_raw, list) else [],
            last_successful_update=data.get("last_successful_update"),
            newest_interval=data.get("newest_interval"),
        )


def _load_bill_pdf_index(data: dict[str, Any]) -> dict[str, BillPdfIndexEntry]:
    raw = data.get("bill_pdf_index") or {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): BillPdfIndexEntry.from_dict(v) for k, v in raw.items()}


def _load_tod_snapshot(data: dict[str, Any]) -> dict[str, Any] | None:
    return _load_dict_snapshot(data, "tod_snapshot")


def _load_dict_snapshot(data: dict[str, Any], key: str) -> dict[str, Any] | None:
    raw = data.get(key)
    if not raw or not isinstance(raw, dict):
        return None
    return dict(raw)


def _store_for_entry(hass: HomeAssistant, entry_id: str) -> ImportStateStore:
    store = _STORES.get(entry_id)
    if store is None or store.hass is not hass:
        store = ImportStateStore(hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry_id}")
        _STORES[entry_id] = store
    return store


def discard_store_cache(entry_id: str) -> None:
    """Drop the cached Store on unload so removed entries do not pin a hass ref.

    A timed-out save keeps running executor-side behind its shield, so the
    per-entry coordination stays registered until that write drains. A prompt
    config-entry reload then orders new writes behind it (via ``_save_state``)
    instead of overlapping them on a fresh Store instance.
    """
    # Drop the Store immediately: only coordination must survive the unload.
    _STORES.pop(entry_id, None)
    state = _SAVE_STATES.get(entry_id)
    if state is not None:
        if state.task is not None and not state.task.done():
            state.task.cancel()
        inflight = state.inflight
        if inflight is not None:
            if not inflight.done():
                state.draining = True

                def _release(task: asyncio.Task) -> None:
                    if not task.cancelled():
                        task.exception()  # consume to avoid unretrieved warnings
                    # Only release an unclaimed drained state: a prompt reload's
                    # saves mark it claimed (draining=False) before they await.
                    if state.draining and _SAVE_STATES.get(entry_id) is state:
                        _SAVE_STATES.pop(entry_id, None)

                inflight.add_done_callback(_release)
                return  # coordination stays alive until the parked write drains
            if not inflight.cancelled():
                inflight.exception()  # consume a completed task's result before dropping it
    _SAVE_STATES.pop(entry_id, None)


def _reset_token(state: _SaveState) -> tuple[int, bool]:
    """Snapshot the reset generation at API entry."""
    return (state.clear_epoch, state.clear_inflight)


def _reset_crossed(state: _SaveState, token: tuple[int, bool] | None) -> bool:
    """True when a checkpoint reset started/ran after ``token`` was captured.

    A token captured mid-reset (``during=True``) is always treated as crossed:
    its payload predates the authoritative empty state no matter the timing.
    """
    if token is None:
        return False
    epoch, entered_during = token
    return state.clear_epoch != epoch or entered_during


def _stale_object(state: _SaveState, data: ImportStoreData) -> bool:
    """True when data is not the object the post-reset world owns."""
    return state.bound_obj is not None and id(data) != state.bound_obj


def bind_import_state_object(hass: HomeAssistant, entry_id: str, obj: object) -> None:
    """Record the canonical post-reset store object (call under import_lock).

    Later saves carrying a different object are pre-reset stragglers and are
    discarded.
    """
    state = _save_state(entry_id)
    state.bound_obj = id(obj)
    state.data = obj


def _save_state(entry_id: str) -> _SaveState:
    state = _SAVE_STATES.get(entry_id)
    if state is None:
        state = _SaveState()
        _SAVE_STATES[entry_id] = state
    # Any load/save touching the entry claims it back from drain-only status.
    state.draining = False
    return state


def _payload_digest(payload: dict[str, Any]) -> str:
    # ``last_commit`` is excluded so an unchanged payload dedupes even though a
    # prior write stamped it onto the shared dataclass.
    payload = {k: v for k, v in payload.items() if k != "last_commit"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


async def _write_payload(
    hass: HomeAssistant,
    entry_id: str,
    data: ImportStoreData,
    *,
    critical: bool,
    snapshot: dict[str, Any] | None = None,
    reset_token: tuple[int, bool] | None = None,
    identity_obj: ImportStoreData | None = None,
) -> bool | None:
    """Serialize + dedupe + timed disk write; raises TimeoutError only when critical.

    Returns False when the save was discarded as stale (a checkpoint reset or
    reload replaced the canonical store object); True/None otherwise.

    The whole reconcile → dedupe → write sequence holds the per-entry lock so
    concurrent callers cannot race each other's parked in-flight tasks (each
    waiter reconciles what the previous one parked instead of overlapping it).
    Critical saves serialize BEFORE any await — either a ``snapshot`` captured
    by the caller pre-wait or one taken at entry here — so backfill/correction
    mutation of the shared object cannot alter what lands. Debounced
    non-critical keeps latest-at-fire serialization inside the lock.
    ``reset_token`` is the caller's reset generation: if a checkpoint reset
    crossed this call before it reached the lock, the stale payload yields to
    the authoritative empty state.
    """
    state = _save_state(entry_id)
    snap = snapshot if snapshot is not None else (data.to_dict() if critical else None)
    async with state.lock:
        return await _write_payload_locked(
            hass,
            entry_id,
            data,
            critical=critical,
            snapshot=snap,
            state=state,
            reset_token=reset_token,
            identity_obj=identity_obj,
        )


async def _write_payload_locked(
    hass: HomeAssistant,
    entry_id: str,
    data: ImportStoreData,
    *,
    critical: bool,
    snapshot: dict[str, Any] | None = None,
    state: _SaveState | None = None,
    reset_token: tuple[int, bool] | None = None,
    identity_exempt: bool = False,
    identity_obj: ImportStoreData | None = None,
) -> bool | None:
    """Write core; the caller must already hold ``state.lock``.

    Returns True (written or dedupe-skipped), False (discarded as stale /
    crossed reset), or None (deferred behind a parked write, or the
    non-critical write itself timed out without bookkeeping) — mirroring
    ``_write_payload``.
    """
    if state is None:
        state = _save_state(entry_id)
    # Re-verify object identity UNDER the lock: a save may have queued before
    # a reload bound its canonical object, and the entry-time check cannot see
    # bindings that happen while it waits. Reset-internal empty/restore writes
    # pass identity_exempt=True. Flush callers pass the ORIGINATING object as
    # ``identity_obj`` so a stale snapshot cannot ride in behind a newly bound
    # ``state.data``.
    identity_target = identity_obj if identity_obj is not None else data
    if not identity_exempt and _stale_object(state, identity_target):
        _LOGGER.info(
            "Discarding import state save from a replaced store object for %s",
            entry_id[:8],
        )
        return False
    if _reset_crossed(state, reset_token):
        # The payload predates a checkpoint reset that already persisted its
        # authoritative empty state: DISCARD it. Rewriting an empty payload
        # here could clobber newer bound-object state that queued meanwhile.
        _LOGGER.info(
            "Checkpoint reset superseded a pre-reset import state save for %s",
            entry_id[:8],
        )
        return False
    snap = snapshot if snapshot is not None else (data.to_dict() if critical else None)
    store = _store_for_entry(hass, entry_id)

    # Reconcile any parked write before touching the file. An earlier save
    # that timed out is still running executor-side behind its shield — and
    # one that already completed between saves still bypassed its
    # bookkeeping. Never start a newer write (or the empty clear write)
    # until the parked operation is reconciled, or an older filesystem
    # write could land last and resurrect stale checkpoint state / a
    # phantom recovery marker.
    prior = state.inflight
    if prior is not None:
        try:
            # Await unconditionally: a completed task returns or raises
            # immediately (retrieving its exception), a pending one stays
            # bounded by the same window.
            await asyncio.wait_for(asyncio.shield(prior), timeout=IMPORT_STATE_SAVE_TIMEOUT)
        except TimeoutError:
            _LOGGER.warning(
                "PGE import state save still in flight for %s; deferring newer write",
                entry_id[:8],
            )
            if critical:
                raise
            return
        except Exception:  # noqa: BLE001 - a failed prior write must not block newer one
            _LOGGER.debug("Prior import state save failed for %s; superseding", entry_id[:8])
        finally:
            # Its outcome bypassed normal bookkeeping (a completed timed-out
            # write may have landed content newer than last_written_hash),
            # so dedupe must force one superseding write instead of skipping.
            state.last_written_hash = None
            # Release the slot only once the prior write actually finished;
            # a deferred (still-running) write stays parked for later writers.
            if prior.done() and state.inflight is prior:
                state.inflight = None

    if snap is None:
        # Non-critical debounced saves serialize at fire time: whatever the
        # shared object holds now is the newest state to persist.
        snap = data.to_dict()
    payload = snap
    digest = _payload_digest(payload)
    if digest == state.last_written_hash:
        return True  # unchanged since the last successful write — skip disk entirely
    now_iso = datetime.now(UTC).isoformat()
    data.last_commit = now_iso
    payload["last_commit"] = now_iso
    save_task = asyncio.create_task(store.async_save(payload))
    state.inflight = save_task
    try:
        # Shield: on timeout the executor-backed filesystem write keeps
        # running. The task stays parked in ``state.inflight`` so every
        # later write and the clear path order behind it instead of
        # overlapping on disk.
        await asyncio.wait_for(asyncio.shield(save_task), timeout=IMPORT_STATE_SAVE_TIMEOUT)
    except TimeoutError:
        _LOGGER.warning("PGE import state save timed out for %s", entry_id[:8])
        if critical:
            raise
        return  # non-critical: leave the task parked for later writers to await
    if state.inflight is save_task:
        state.inflight = None
    state.last_written_hash = digest
    return True


async def _async_debounced_save(hass: HomeAssistant, entry_id: str, *, registered_epoch: int | None = None) -> None:
    """Single writer per entry: sleep out the debounce window, write latest state."""
    state = _save_state(entry_id)
    gen = state.clear_epoch if registered_epoch is None else registered_epoch
    await asyncio.sleep(IMPORT_STATE_SAVE_DEBOUNCE_SECONDS)
    while state.dirty:
        if state.clear_epoch != gen:
            # A checkpoint reset happened after this writer was registered;
            # its payload predates the authoritative empty state.
            state.dirty = False
            return
        state.dirty = False
        data = state.data
        if data is None:
            return
        # Sync up to here (no awaits), so flush never observes a half-set writing flag.
        state.writing = True
        try:
            result = await _write_payload(hass, entry_id, data, critical=False)
        finally:
            state.writing = False
        if result is False:
            # Discarded as stale (store replaced): nothing to persist.
            state.dirty = False
            return
        if result is not True:
            # Deferred behind a parked timed-out write, or the write itself
            # timed out: keep dirty so this writer retries the newer payload
            # once the parked write drains (bounded by the 60s window).
            state.dirty = True


async def async_flush_import_state(
    hass: HomeAssistant,
    entry_id: str,
    *,
    data: ImportStoreData | None = None,
    snapshot: dict[str, Any] | None = None,
    reset_token: tuple[int, bool] | None = None,
) -> bool | None:
    """Persist any pending/coalesced import state to disk immediately.

    Cancels a still-sleeping debounced writer; waits out one that is mid-write,
    then performs an inline durable write (deduped when nothing changed).
    ``snapshot`` carries a critical caller's pre-wait payload so concurrent
    mutations during that wait cannot alter what lands. ``reset_token`` marks
    the reset generation captured at API entry: if a checkpoint reset crossed
    this call, the stale snapshot yields to the authoritative empty state.
    """
    state = _save_state(entry_id)
    if reset_token is None:
        # Direct flush callers (e.g. unload) capture their generation here so
        # a reset queued behind an active writer still supersedes them.
        reset_token = _reset_token(state)
    stale_target = data is not None and (_reset_crossed(state, reset_token) or _stale_object(state, data))
    if data is not None and not stale_target:
        state.data = data
    elif data is not None:
        # A reset crossed this call / this object was replaced: neither cache
        # its stale payload as the next flush target nor clobber a newer one.
        _LOGGER.debug("Skipping flush target cache after reset for %s", entry_id[:8])
    task = state.task
    writer_cancelled = False
    if task is not None and not task.done():
        # Cancel the WRITER task unconditionally — even mid-write. After a
        # non-critical timeout the debounced writer keeps retrying its loop,
        # so awaiting a writing task here would hang unload/critical flushes
        # indefinitely instead of respecting the save window. Cancellation
        # leaves the shielded executor write parked in ``state.inflight``:
        # this flush's inline write then orders behind it with the same
        # bounded wait instead of overlapping on disk.
        task.cancel()
        writer_cancelled = True
        try:
            await task
        except asyncio.CancelledError:
            # Awaiting a child propagates caller cancellation by cancelling the
            # child too, so ``task.cancelled()`` alone cannot tell the two apart.
            # ``cancelling()`` counts requests against THIS task: re-raise for
            # watchdog/shutdown cancellation, suppress only our writer-cancel.
            if not writer_cancelled or asyncio.current_task().cancelling():
                raise
        except Exception:  # noqa: BLE001 - writer already logged its own failure
            pass
    if state.task is task:
        # Only clear when the captured task is still the installed one: a
        # non-critical save that raced this wait may have replaced it, and
        # orphaning that task (or clearing its dirty flag) would lose the
        # newest state entirely.
        state.task = None
        state.dirty = False
    target = state.data
    if target is None:
        if data is None:
            return True
        # Critical caller with no cached coordination target (post-clear):
        # persist its payload instead of silently skipping the write.
        target = data
    result = await _write_payload(
        hass,
        entry_id,
        target,
        critical=True,
        snapshot=snapshot,
        reset_token=reset_token,
        identity_obj=data,
    )
    if snapshot is not None and not _reset_crossed(state, reset_token):
        # A non-critical save that arrived while we awaited the writing debounce
        # task made that task land newer shared state; this flush then wrote the
        # older call-time snapshot over it with no pending writer left. Requeue
        # a debounced save whenever the shared object has moved past the
        # snapshot so freshly updated progress/snapshots are not lost on crash.
        # (Skipped when a reset crossed this call: the empty state is final.)
        current = target.to_dict()
        if _payload_digest(current) != _payload_digest(snapshot):
            state.dirty = True
            if state.task is None or state.task.done():
                state.task = hass.async_create_background_task(
                    _async_debounced_save(hass, entry_id, registered_epoch=state.clear_epoch),
                    name=f"{DOMAIN}_import_state_save_{entry_id[:8]}",
                )
    return result


async def async_discard_pending_import_state(hass: HomeAssistant, entry_id: str) -> None:
    """Drop any coalesced-but-unwritten state without touching disk.

    Used before clearing: persisting the stale payload first would double I/O on
    exactly the slow hosts this module targets, and a timed-out stale write must
    not abort the caller before the empty state lands.
    """
    state = _save_state(entry_id)
    task = state.task
    writer_cancelled = False
    if task is not None and not task.done():
        # Same unbounded-wait fix as async_flush_import_state: cancel the
        # writer even while it is writing so a stuck filesystem write cannot
        # hang the reset path past its window. The shielded executor write
        # stays parked in ``state.inflight`` for the empty-state write to
        # order behind.
        task.cancel()
        writer_cancelled = True
        try:
            await task
        except asyncio.CancelledError:
            # Same distinction as in async_flush_import_state.
            if not writer_cancelled or asyncio.current_task().cancelling():
                raise
        except Exception:  # noqa: BLE001 - writer already logged its own failure
            pass
    if state.task is task:
        # Same guard as flush: a replacement writer installed during the wait
        # must survive discard bookkeeping untouched.
        state.task = None
        state.dirty = False


async def async_load_import_state(hass: HomeAssistant, entry_id: str) -> ImportStoreData:
    # Claim via _save_state (not a bare registry get): the drain callback only
    # releases unclaimed states, so a parked write finishing mid-load cannot
    # drop this coordination while the read below is in flight. Loads with no
    # prior coordination register one and take the same per-entry lock,
    # closing the state-less race as well.
    state = _save_state(entry_id)
    store = _store_for_entry(hass, entry_id)
    async with state.lock:
        # Serialize reconciliation and the read with writers: while this lock
        # is held, no queued save can start a replacement write, so the file
        # hydrated here cannot be stale relative to in-memory state (a reload
        # that later saves would otherwise overwrite newer persisted state).
        prior = state.inflight
        if prior is not None:
            try:
                # Unconditional: retrieves a completed task's exception too.
                await asyncio.wait_for(asyncio.shield(prior), timeout=IMPORT_STATE_SAVE_TIMEOUT)
            except TimeoutError:
                _LOGGER.warning(
                    "PGE import state save still in flight during reload for %s",
                    entry_id[:8],
                )
                raise
            except Exception:  # noqa: BLE001 - a failed parked write left the last good file intact
                _LOGGER.debug("Prior import state save failed before reload for %s", entry_id[:8])
        raw = await store.async_load()
        result = ImportStoreData.from_dict(raw)
        # Bind the returned instance as the canonical object for the new
        # coordinator run: straggler saves from a previous run's captured
        # object (not retained/cancelled on unload) are then rejected instead
        # of overwriting the freshly loaded state.
        state.bound_obj = id(result)
        state.data = result
        state.dirty = False
        return result


async def async_save_import_state(
    hass: HomeAssistant,
    entry_id: str,
    data: ImportStoreData,
    *,
    critical: bool = True,
) -> bool | None:
    """Persist import state with a wall-clock save timeout.

    ``critical=True`` (default) writes inline and re-raises on timeout so
    checkpoint-bearing callers fail closed. ``critical=False`` marks the entry
    dirty and coalesces into one debounced background write — bursts within the
    window collapse into a single disk write of the final shared state.

    Returns False when the save was discarded as stale (canonical object
    replaced by a checkpoint reset/reload); callers that gate recorder
    mutations on durable checkpoints must treat False like a timeout.
    """
    state = _save_state(entry_id)
    # Capture the reset generation at API entry: a checkpoint reset that runs
    # while this call waits must stay authoritative over the pre-reset payload.
    token = _reset_token(state)
    if _stale_object(state, data):
        # This object predates a checkpoint reset that already replaced the
        # canonical store (e.g. billing captured it before the reset). A save
        # from it must never resurrect wiped state, whenever it lands.
        if not critical:
            _LOGGER.debug("Dropping import state save for a replaced store (%s)", entry_id[:8])
            return
        token = (token[0], True)  # force-crossed: discarded at write time, never rewritten
    if not critical:
        # Lightweight registration: this path MUST NOT wait behind slow disk
        # writes (the write lock spans the full Store.async_save wait, so
        # taking it here would stall progress saves — including ones made
        # while holding import_lock — for up to the 60s window). Ordering
        # against checkpoint resets is enforced by the entry token plus the
        # writer-fire epoch abort instead of the lock.
        if _reset_crossed(state, token):
            # This call started before the reset and waited it out: its
            # payload predates the authoritative empty state — drop it.
            _LOGGER.debug("Dropping pre-reset import state save for %s", entry_id[:8])
            return
        state.data = data
        registered_epoch = token[0]
        if state.task is None or state.task.done():
            state.dirty = True
            state.task = hass.async_create_background_task(
                _async_debounced_save(hass, entry_id, registered_epoch=registered_epoch),
                name=f"{DOMAIN}_import_state_save_{entry_id[:8]}",
            )
        else:
            state.dirty = True
        return
    # Snapshot BEFORE the flush writer-wait: backfill/correction tasks mutate
    # the shared object, and the awaited writer may hold writing=True for a
    # long time on slow storage. The checkpoint must persist call-time state.
    snap = data.to_dict()
    return await async_flush_import_state(hass, entry_id, data=data, snapshot=snap, reset_token=token)


async def _restore_prior_payload(
    hass: HomeAssistant,
    entry_id: str,
    prior_obj: ImportStoreData,
    prior_payload: dict[str, Any],
    state: _SaveState,
    expect_epoch: int,
    *,
    assume_lock: bool = False,
) -> None:
    """Re-assert the pre-reset payload behind the parked empty write.

    Carries the ORIGINAL bound object (identity-exempt in the write core). A
    newer completed reset (epoch moved past expect_epoch) owns the file —
    skip rather than resurrect over it. With assume_lock=True the caller
    already holds state.lock (timeout branch inside the clear); otherwise
    the lock is acquired here (scheduled cancellation recovery).
    """
    if state.clear_epoch != expect_epoch:
        _LOGGER.debug("Skipping pre-reset payload restore for %s: newer reset ran", entry_id[:8])
        return
    if assume_lock:
        await _restore_locked(hass, entry_id, prior_obj, prior_payload, state, expect_epoch)
        return
    async with state.lock:
        # Recheck under the lock: since the pre-lock guard ran, a newer reset
        # queued behind another writer may acquire the lock first, bump
        # clear_epoch, and persist empty state — that newer reset owns the
        # file and must stay authoritative over this pre-reset payload.
        # (The locked core re-checks per attempt below as well.)
        await _restore_locked(hass, entry_id, prior_obj, prior_payload, state, expect_epoch)


_IMPORT_STATE_RESTORE_WARN_EVERY = 5


async def _restore_locked(
    hass: HomeAssistant,
    entry_id: str,
    prior_obj: ImportStoreData,
    prior_payload: dict[str, Any],
    state: _SaveState,
    expect_epoch: int,
) -> None:
    """Locked restore core: retry until the pre-reset payload actually lands.

    A single non-critical attempt can defer (parked empty write still in
    flight) or time out without writing anything; abandoning there would let
    that parked EMPTY write land later and permanently erase the checkpoint.
    There is NO fixed attempt cap while this generation still owns the file:
    every deferred attempt reconciles the parked write with one full timeout
    window before writing again, so iterations are serialized bounded waits —
    never a tight spin — and restoration stays attached until the payload
    lands or a newer reset supersedes it (epoch re-checked each attempt).
    Prolonged stalls log periodically instead of failing silently.
    """
    attempt = 0
    while True:
        if state.clear_epoch != expect_epoch:
            _LOGGER.debug("Skipping pre-reset payload restore for %s: newer reset ran", entry_id[:8])
            return
        result = await _write_payload_locked(
            hass,
            entry_id,
            prior_obj,
            critical=False,
            snapshot=prior_payload,
            state=state,
            identity_exempt=True,
        )
        if result is None:
            attempt += 1
            if attempt % _IMPORT_STATE_RESTORE_WARN_EVERY == 0:
                _LOGGER.warning(
                    "Import-state restore still deferred for %s after %s windows; "
                    "keeping retry attached so the parked write cannot erase it",
                    entry_id[:8],
                    attempt,
                )
            continue
        # True: written/dedupe-skipped. False: superseded by a newer binding
        # or crossed reset — either way the restore must not rewrite.
        return


async def async_clear_import_state(hass: HomeAssistant, entry_id: str) -> None:
    """Cancel any pending write WITHOUT persisting it, then write empty state.

    Flushing the stale payload first would double I/O and could abort on the
    slow-host timeout before the empty state lands. The whole reset holds the
    per-entry lock — save registration serializes against it, so a concurrent
    caller cannot queue a stale debounced writer behind the empty payload —
    and bumps ``clear_epoch`` so any pre-reset writer/snapshot that still lands
    is superseded by a follow-up empty write. The empty write goes through the
    bounded path so a storage stall raises after 60s instead of hanging the
    caller forever, and its digest is recorded on success.
    """
    state = _save_state(entry_id)
    async with state.lock:
        task = state.task
        if task is not None and not task.done():
            task.cancel()
        # Snapshot the current in-memory payload: if the empty write times out,
        # its parked executor-side completion would still erase the on-disk
        # checkpoint even though this reset reports failure — re-assert the
        # prior payload after reconciling that parked write.
        prior_obj = state.data
        prior_payload = prior_obj.to_dict() if prior_obj is not None else None
        state.task = None
        state.dirty = False
        state.data = None
        state.last_written_hash = None
        state.clear_epoch += 1
        state.clear_inflight = True
        try:
            await _write_payload_locked(
                hass,
                entry_id,
                ImportStoreData(),
                critical=True,
                state=state,
                identity_exempt=True,
            )
        except asyncio.CancelledError:
            # Cancellation during the shielded empty write bypasses the
            # timeout recovery above, but the parked write can still erase
            # the checkpoint. Schedule a background reconciliation that waits
            # out the parked empty write and re-asserts the prior object
            # before propagating.
            _LOGGER.warning(
                "Checkpoint reset cancelled for %s; scheduling prior-payload restore",
                entry_id[:8],
            )
            if prior_obj is not None:
                hass.async_create_background_task(
                    _restore_prior_payload(
                        hass,
                        entry_id,
                        prior_obj,
                        prior_payload,
                        state,
                        expect_epoch=state.clear_epoch,
                    ),
                    name=f"{DOMAIN}_import_state_restore_{entry_id[:8]}",
                )
            raise
        except TimeoutError:
            # The empty write stays parked behind its shield and may drain
            # much later. Restoration must remain attached until it does,
            # but reset has to respect its bound: schedule the generation-
            # guarded restore in the BACKGROUND (it takes state.lock once
            # this handler exits) instead of awaiting it under the lock,
            # where a never-draining write would hold persistence — and the
            # coordinator's import/job — locks forever. Then re-raise so the
            # caller still sees the advertised timeout.
            _LOGGER.warning(
                "Checkpoint reset empty write timed out for %s; scheduling prior-payload restore",
                entry_id[:8],
            )
            if prior_obj is not None:
                hass.async_create_background_task(
                    _restore_prior_payload(
                        hass,
                        entry_id,
                        prior_obj,
                        prior_payload,
                        state,
                        expect_epoch=state.clear_epoch,
                    ),
                    name=f"{DOMAIN}_import_state_restore_{entry_id[:8]}",
                )
            raise
        finally:
            state.clear_inflight = False
