from __future__ import annotations

import asyncio
import contextvars
import logging
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PGEApiClient
from .auth import PGEAuthManager
from .billing_models import (
    AccountSnapshot,
    BillingFreshness,
    EnergyTrackerEstimates,
    ProgramsSnapshot,
)
from .billing_sync import async_run_billing_sync
from .const import (
    BACKFILL_CANCEL_GRACE,
    CATCHUP_RETRY_HOURS,
    CONF_ACCOUNT_ID,
    CONF_ACCOUNT_KEY,
    CONF_CORRECTION_WINDOW,
    CONF_INCLUDE_COST,
    DEFAULT_CORRECTION_WINDOW,
    DEFAULT_INCLUDE_COST,
    DOMAIN,
    SYNC_PHASE_CORRECTION,
    SYNC_PHASE_IDLE,
    SYNC_STATUS_BACKFILLING,
    SYNC_STATUS_COMPLETE,
    SYNC_STATUS_FAILED,
    SYNC_STATUS_REFRESHING,
)
from .day_validation import clip_hourly_to_local_day, is_invalid_closed_day, validate_hourly_day
from .exceptions import (
    PGEAuthenticationError,
    PGEConnectionError,
    PGEDiscoveryIncompleteError,
    PGEGraphQLError,
    PGEMfaUnsupportedError,
    PGERateLimitError,
    PGESchemaError,
)
from .models import (
    DataFreshness,
    ImportCheckpoint,
    SyncProgressSnapshot,
    UsageInterval,
    UsageResolution,
)
from .options import get_entry_option, resolve_polling_timedelta
from .statistics import (
    async_import_with_baseline,
    async_refresh_lifetime_totals,
    async_repair_monthly_hourly_collisions,
    async_repair_suffix_sums,
)
from .store import (
    ImportStoreData,
    async_clear_import_state,
    async_load_import_state,
    async_save_import_state,
)
from .sync_progress import (
    apply_progress_math,
    idle_snapshot,
    snapshot_from_store_fields,
    snapshot_to_store_fields,
)
from .time_util import iter_local_days, local_day_bounds, today_local

_LOGGER = logging.getLogger(__name__)

# Bound to the running backfill coroutine so orphaned tasks cannot mutate a newer job.
_backfill_run_generation: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "pge_backfill_run_generation", default=None
)


def _format_statistics_import_error(hass: HomeAssistant, exc: BaseException) -> str:
    """Map recorder/executor failures to a sync message operators can act on."""
    raw = str(exc)
    if hass.is_stopping or "cannot schedule new futures after shutdown" in raw:
        return (
            "Statistics import interrupted — Home Assistant (or the recorder) was "
            "shutting down. Wait until HA is fully up, then Refresh again."
        )
    return f"Statistics import failed: {exc}"


class PGECoordinator(DataUpdateCoordinator[dict[str, Any]]):
    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        auth_manager: PGEAuthManager,
        client: PGEApiClient,
    ) -> None:
        self.entry = entry
        self.auth_manager = auth_manager
        self.client = client
        self.account_key = entry.data.get(CONF_ACCOUNT_KEY) or auth_manager.account_key
        self.account_id = entry.data[CONF_ACCOUNT_ID]
        self.import_lock = asyncio.Lock()
        self.job_lock = asyncio.Lock()
        self._backfill_task: asyncio.Task | None = None
        self._backfill_reserved = False
        self._backfill_generation = 0
        self._last_progress_monotonic: float | None = None
        self._backfill_abort_reason: str | None = None
        self._backfill_abort_clears_targets = False
        self._backfill_abort_generation: int | None = None
        self._orphaned_tasks: set[asyncio.Task] = set()
        self._catchup_retry = False
        self._import_store = ImportStoreData(account_key=self.account_key)

        correction_window = int(get_entry_option(entry, CONF_CORRECTION_WINDOW, DEFAULT_CORRECTION_WINDOW))
        self.correction_window_days = correction_window
        self.include_cost = bool(get_entry_option(entry, CONF_INCLUDE_COST, DEFAULT_INCLUDE_COST))

        self._checkpoint: ImportCheckpoint = ImportCheckpoint(
            last_imported_start=None,
            last_imported_end=None,
            last_imported_timestamp=datetime.now(UTC),
            correction_window_start=None,
            failed_ranges=[],
        )

        self._newest_interval: datetime | None = None
        self._last_successful_update: datetime | None = None
        self._last_api_error: str | None = None
        self._failed_days_this_poll: list[str] = []
        self._recent_intervals: list[UsageInterval] = []
        self._lifetime_energy_kwh: float | None = None
        self._lifetime_cost_usd: float | None = None
        self._latest_temperature_f: float | None = None
        self._backfill_in_progress = False
        self._backfill_oldest: datetime | None = None
        self._backfill_newest: datetime | None = None
        self._refresh_job_active = False
        self._sync_progress = idle_snapshot()
        # Billing / programs state (populated by billing_sync; soft-fail).
        self.account_snapshot: AccountSnapshot | None = None
        self.programs_snapshot: ProgramsSnapshot | None = None
        self.tracker_estimates: EnergyTrackerEstimates | None = None
        self.billing_freshness: BillingFreshness = BillingFreshness()
        self.lifetime_payments_usd: float | None = None
        self.lifetime_billed_usd: float | None = None
        # async_update_entry for token persistence must not trigger options reload.
        self._skip_reload_on_next_update = False
        # Debounce reauth flows so a flapping Cognito blip does not spam the UI.
        self._reauth_requested = False

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=resolve_polling_timedelta(entry),
        )

    @property
    def has_retained_state(self) -> bool:
        """True when sensors can keep showing values after a failed poll."""
        return bool(
            self.data is not None
            or self._recent_intervals
            or self._lifetime_energy_kwh is not None
            or self._lifetime_cost_usd is not None
            or self.account_snapshot is not None
            or self.programs_snapshot is not None
            or self.lifetime_payments_usd is not None
            or self.lifetime_billed_usd is not None
            or self._import_store.last_imported_end
            or self._import_store.completed_local_dates
        )

    @property
    def import_store(self) -> ImportStoreData:
        return self._import_store

    @property
    def checkpoint(self) -> ImportCheckpoint:
        return self._checkpoint

    @property
    def freshness(self) -> DataFreshness:
        data_age: float | None = None
        if self._last_successful_update:
            data_age = (datetime.now(UTC) - self._last_successful_update).total_seconds()
        return DataFreshness(
            newest_interval=self._newest_interval,
            last_successful_update=self._last_successful_update,
            last_api_error=self._last_api_error,
            data_age_seconds=data_age,
        )

    @property
    def recent_intervals(self) -> list[UsageInterval]:
        return list(self._recent_intervals)

    @property
    def lifetime_energy_kwh(self) -> float | None:
        return self._lifetime_energy_kwh

    @property
    def lifetime_cost_usd(self) -> float | None:
        return self._lifetime_cost_usd

    @property
    def latest_temperature_f(self) -> float | None:
        return self._latest_temperature_f

    @property
    def backfill_in_progress(self) -> bool:
        return self._backfill_in_progress or self._backfill_reserved

    @property
    def sync_progress(self) -> SyncProgressSnapshot:
        return self._sync_progress

    @property
    def sync_job_in_progress(self) -> bool:
        """True while a manual refresh or history backfill is running."""
        return self._refresh_job_active or self.backfill_in_progress

    @property
    def failed_ranges(self) -> list[tuple[datetime, datetime]]:
        ranges: list[tuple[datetime, datetime]] = []
        for iso in self._import_store.failed_local_dates:
            day = date.fromisoformat(iso)
            day_start, day_end = local_day_bounds(day)
            ranges.append((day_start, day_end))
        return ranges

    def try_reserve_backfill(self) -> bool:
        """Synchronously reserve the backfill job slot (check-and-set)."""
        if self._refresh_job_active or self._backfill_in_progress or self._backfill_reserved:
            return False
        self._backfill_reserved = True
        return True

    def release_backfill_reservation(self) -> None:
        self._backfill_reserved = False

    def note_backfill_activity(self) -> None:
        """Heartbeat used by the stall watchdog (any progress mutation)."""
        self._last_progress_monotonic = time.monotonic()

    def progress_stalled(self, timeout: timedelta) -> bool:
        """True when no progress heartbeat has fired within ``timeout``."""
        if self._last_progress_monotonic is None:
            return False
        return (time.monotonic() - self._last_progress_monotonic) > timeout.total_seconds()

    @property
    def backfill_generation(self) -> int:
        """Monotonic generation for the current backfill ownership token."""
        return self._backfill_generation

    def set_backfill_task(self, task: asyncio.Task | None, *, generation: int | None = None) -> int | None:
        """Attach or clear the backfill task.

        Setting a non-None task bumps the generation and returns it. Clearing is a
        no-op when ``generation`` is stale (orphaned task after hard release).
        """
        if task is not None:
            self._backfill_generation += 1
            self._backfill_task = task
            return self._backfill_generation
        if generation is not None and generation != self._backfill_generation:
            return None
        self._backfill_task = None
        return None

    def bind_backfill_run_generation(self, generation: int) -> contextvars.Token[int | None]:
        """Bind ``generation`` to the current task context for orphan guards."""
        return _backfill_run_generation.set(generation)

    def reset_backfill_run_generation(self, token: contextvars.Token[int | None]) -> None:
        _backfill_run_generation.reset(token)

    def _is_stale_backfill_generation(self) -> bool:
        run_gen = _backfill_run_generation.get()
        return run_gen is not None and run_gen != self._backfill_generation

    def owns_backfill_generation(self, generation: int) -> bool:
        """True while ``generation`` is still the live backfill owner.

        Callers that mutate shared state outside the coordinator (notably the
        ``import_store`` target_* fields) must check this — an orphaned task shares
        the same ``ImportStoreData`` instance as its successor.
        """
        return generation == self._backfill_generation

    def request_backfill_abort(self, reason: str, *, clear_targets: bool) -> None:
        """Cancel the backfill task without awaiting (stall watchdog)."""
        self._backfill_abort_reason = reason
        self._backfill_abort_clears_targets = clear_targets
        # Stamp the owner so an orphan's abort can never be consumed by its successor.
        self._backfill_abort_generation = self._backfill_generation
        task = self._backfill_task
        if task is not None and not task.done():
            task.cancel()

    def consume_backfill_abort(self, generation: int | None = None) -> tuple[str | None, bool]:
        """Take the pending abort reason, but only for the generation it targeted."""
        stale = generation is not None and generation != self._backfill_abort_generation
        reason = None if stale else self._backfill_abort_reason
        clear_targets = False if stale else self._backfill_abort_clears_targets
        self._clear_backfill_abort()
        return reason, clear_targets

    def _clear_backfill_abort(self) -> None:
        self._backfill_abort_reason = None
        self._backfill_abort_clears_targets = False
        self._backfill_abort_generation = None

    def _track_orphan(self, orphan: asyncio.Task | None) -> None:
        """Keep a handle on tasks we gave up on so unload can still cancel them."""
        self._orphaned_tasks = {t for t in self._orphaned_tasks if not t.done()}
        if orphan is not None and not orphan.done():
            self._orphaned_tasks.add(orphan)

    async def force_release_backfill(self, reason: str) -> None:
        """Orphan a non-responsive backfill task and unblock sync_job_in_progress."""
        orphan = self._backfill_task
        self._backfill_generation += 1
        self._backfill_task = None
        self._backfill_in_progress = False
        self._backfill_reserved = False
        # The orphan can no longer act on this abort; do not let a successor see it.
        self._clear_backfill_abort()
        if orphan is not None and not orphan.done():
            _LOGGER.error(
                "Orphaning PGE backfill task that ignored cancellation: %r",
                orphan,
            )
            self._track_orphan(orphan)
        self.fail_sync_job(reason)
        if not self.hass.is_stopping:
            await self.async_persist_sync_progress()

    async def async_cancel_backfill(self) -> None:
        task = self._backfill_task
        if task is not None and not task.done():
            task.cancel()
            done, _pending = await asyncio.wait({task}, timeout=BACKFILL_CANCEL_GRACE)
            if not done:
                _LOGGER.error("Backfill task ignored cancellation; orphaning it")
                self._backfill_generation += 1
                self._track_orphan(task)
        # Orphans from earlier hard releases keep hitting the PGE API and the
        # recorder; unload is the last chance to stop them.
        for orphan in list(self._orphaned_tasks):
            if not orphan.done():
                orphan.cancel()
        self._orphaned_tasks.clear()
        self._clear_backfill_abort()
        self._backfill_task = None
        self._backfill_in_progress = False
        self._backfill_reserved = False
        if self._sync_progress.status == SYNC_STATUS_BACKFILLING:
            self.fail_sync_job("Cancelled")
            if not self.hass.is_stopping:
                await self.async_persist_sync_progress()

    async def async_load_store(self) -> None:
        """Load import checkpoint. Do not repair here — that blocks HA bootstrap."""
        self._import_store = await async_load_import_state(self.hass, self.entry.entry_id)
        if not self._import_store.account_key:
            self._import_store.account_key = self.account_key
        if self._import_store.sync_status:
            self._sync_progress = snapshot_from_store_fields(self._import_store)
        # Never restore a live-looking status with no task behind it. Resume re-enters
        # `backfilling` when it actually starts a task; an interrupted manual refresh
        # is never resumed at all, so both would otherwise show as running forever.
        if self._sync_progress.status in (SYNC_STATUS_BACKFILLING, SYNC_STATUS_REFRESHING):
            self.fail_sync_job("Interrupted by restart")
            self._apply_sync_progress_to_store()
        await self.async_refresh_lifetime_totals()

    def update_sync_progress(
        self,
        *,
        persist: bool = False,
        notify: bool = True,
        **fields: Any,
    ) -> None:
        """Mutate the sync snapshot, recompute percent/ETA, optionally persist."""
        if self._is_stale_backfill_generation():
            return
        for key, value in fields.items():
            if not hasattr(self._sync_progress, key):
                raise AttributeError(f"Unknown sync progress field: {key}")
            setattr(self._sync_progress, key, value)
        apply_progress_math(self._sync_progress, now_monotonic=time.monotonic())
        self.note_backfill_activity()
        if persist:
            self._apply_sync_progress_to_store()
        if notify:
            self.async_update_listeners()

    def _apply_sync_progress_to_store(self) -> None:
        for key, value in snapshot_to_store_fields(self._sync_progress).items():
            setattr(self._import_store, key, value)
        # Persist wall-clock ISO; keep monotonic only in the in-memory snapshot.
        if self._sync_progress.started_at is None:
            self._import_store.sync_started_at = None
        elif isinstance(self._import_store.sync_started_at, str) and self._import_store.sync_started_at:
            pass  # preserve first stamp for this job
        else:
            self._import_store.sync_started_at = datetime.now(UTC).isoformat()

    async def async_persist_sync_progress(self) -> None:
        if self._is_stale_backfill_generation():
            return
        self._apply_sync_progress_to_store()
        await async_save_import_state(
            self.hass,
            self.entry.entry_id,
            self._import_store,
            critical=False,
        )

    def begin_sync_job(
        self,
        *,
        status: str,
        phase: str,
        total: int,
        message: str = "",
    ) -> None:
        """Initialize snapshot for a new manual refresh or backfill job."""
        self._import_store.sync_started_at = None
        self.note_backfill_activity()
        self.update_sync_progress(
            status=status,
            phase=phase,
            done=0,
            total=max(0, int(total)),
            percent=0,
            started_at=time.monotonic(),
            eta_seconds=None,
            message=message,
            error=None,
            persist=True,
            notify=True,
        )

    def complete_sync_job(self, *, message: str = "Done") -> None:
        self._refresh_job_active = False
        self.update_sync_progress(
            status=SYNC_STATUS_COMPLETE,
            phase=SYNC_PHASE_IDLE,
            done=self._sync_progress.total,
            percent=100,
            eta_seconds=0.0,
            message=message,
            error=None,
            persist=True,
        )

    def fail_sync_job(self, error: str) -> None:
        self._refresh_job_active = False
        self.update_sync_progress(
            status=SYNC_STATUS_FAILED,
            phase=SYNC_PHASE_IDLE,
            error=error,
            message=self._sync_progress.message or "Failed",
            persist=True,
        )

    def reset_sync_job_idle(self) -> None:
        self._refresh_job_active = False
        self._sync_progress = idle_snapshot()
        self._apply_sync_progress_to_store()
        self.async_update_listeners()

    async def async_start_refresh_job(self) -> None:
        """Start a manual correction-window refresh with progress tracking."""
        if self.sync_job_in_progress:
            raise UpdateFailed("A sync job is already in progress")
        now = datetime.now(UTC)
        window_start = now - timedelta(days=self.correction_window_days)
        days = list(iter_local_days(window_start, now))
        self._refresh_job_active = True
        self.begin_sync_job(
            status=SYNC_STATUS_REFRESHING,
            phase=SYNC_PHASE_CORRECTION,
            total=len(days),
            message=f"Correction 0/{len(days)}",
        )
        await self.async_persist_sync_progress()
        # Background task so import paths waiting on the recorder never deadlock on it.
        self.hass.async_create_background_task(
            self.async_request_refresh(),
            name=f"{DOMAIN}_manual_refresh_{self.entry.entry_id[:8]}",
            eager_start=False,
        )

    async def async_refresh_lifetime_totals(self) -> None:
        """Refresh cumulative energy/cost/temperature from recorder for sensors."""
        try:
            energy, cost, temp = await async_refresh_lifetime_totals(self.hass, self.account_key)
        except Exception as exc:
            _LOGGER.debug("Lifetime totals refresh skipped: %s", exc)
            return
        self._lifetime_energy_kwh = energy
        self._lifetime_cost_usd = cost
        self._latest_temperature_f = temp

    async def async_repair_dirty_if_needed(self) -> None:
        """Rebuild statistic sums after an interrupted import.

        Must run *after* config-entry setup completes. Awaiting recorder
        ``async_block_till_done`` during ``async_setup_entry`` deadlocks bootstrap
        (HA waits for the entry; the entry waits for the recorder queue).
        """
        if not self._import_store.dirty_from:
            return
        dirty = datetime.fromisoformat(self._import_store.dirty_from)
        _LOGGER.warning(
            "Repairing dirty_from=%s after interrupted import",
            self._import_store.dirty_from,
        )
        try:
            async with self.import_lock:
                await async_repair_suffix_sums(
                    self.hass,
                    self.account_key,
                    dirty,
                    account_id=self.account_id,
                )
        except Exception as exc:
            _LOGGER.error("dirty_from repair failed: %s", exc)
            return
        self._import_store.dirty_from = None
        await async_save_import_state(self.hass, self.entry.entry_id, self._import_store)

    async def async_repair_monthly_collisions_if_needed(self) -> None:
        """Clear monthly billing-period lumps that share a day with hourly rows."""
        try:
            async with self.import_lock:
                cleared = await async_repair_monthly_hourly_collisions(
                    self.hass,
                    self.account_key,
                    account_id=self.account_id,
                    include_cost=self.include_cost,
                )
        except Exception as exc:
            _LOGGER.error("Monthly/hourly collision repair failed: %s", exc)
            return
        if cleared:
            await self.async_refresh_lifetime_totals()

    async def async_reset_checkpoint(self) -> None:
        async with self.job_lock:
            if self.backfill_in_progress:
                raise UpdateFailed("Cannot reset checkpoint while backfill is running")
            await async_clear_import_state(self.hass, self.entry.entry_id)
            self._import_store = ImportStoreData(account_key=self.account_key)
            self._checkpoint = ImportCheckpoint(
                last_imported_start=None,
                last_imported_end=None,
                last_imported_timestamp=datetime.now(UTC),
                correction_window_start=None,
                failed_ranges=[],
            )

    def persist_auth_to_entry(self) -> None:
        if self.auth_manager.auth_mode != "credential":
            return
        merged = {**self.entry.data, **self.auth_manager.persistable_auth_data()}
        if merged == dict(self.entry.data):
            return
        # Token writes must not bounce the integration via the update listener.
        self._skip_reload_on_next_update = True
        self.hass.config_entries.async_update_entry(self.entry, data=merged)

    def consume_skip_reload(self) -> bool:
        """Return True once when the next update-listener should not reload."""
        if self._skip_reload_on_next_update:
            self._skip_reload_on_next_update = False
            return True
        return False

    async def async_get_usage_with_auth_retry(
        self,
        start: datetime,
        end: datetime,
        *,
        resolution: UsageResolution = UsageResolution.HOURLY,
    ):
        """Fetch usage with proactive renewal and one forced 401 renew+retry.

        Keeps the surrounding sync/backfill job running across mid-request
        token expiry by renewing under the auth lock and retrying once.
        """
        await self.auth_manager.ensure_valid_token()
        self.persist_auth_to_entry()
        try:
            return await self.client.get_usage(resolution, start, end, self.account_key)
        except PGEAuthenticationError:
            if self.auth_manager.auth_mode != "credential":
                raise
            await self.auth_manager.force_renew()
            self.persist_auth_to_entry()
            return await self.client.get_usage(resolution, start, end, self.account_key)

    async def async_get_monthly_usage_with_auth_retry(
        self,
        start: datetime,
        end: datetime,
    ):
        """Monthly paged fetch with the same renew+retry semantics as hourly."""
        await self.auth_manager.ensure_valid_token()
        self.persist_auth_to_entry()
        try:
            return await self.client.get_monthly_usage_paged(start, end, self.account_key)
        except PGEAuthenticationError:
            if self.auth_manager.auth_mode != "credential":
                raise
            await self.auth_manager.force_renew()
            self.persist_auth_to_entry()
            return await self.client.get_monthly_usage_paged(start, end, self.account_key)

    # Backward-compatible private name used by older tests/callers.
    async def _async_get_usage_with_auth_retry(self, start: datetime, end: datetime):
        return await self.async_get_usage_with_auth_retry(start, end)

    def _refresh_update_interval(self) -> None:
        """Recompute next poll delay (hour/day units realign to sync_local_time)."""
        self.update_interval = resolve_polling_timedelta(self.entry)

    def _retained_poll_payload(self) -> dict[str, Any]:
        """Coordinator payload that keeps listeners on last-known values."""
        if isinstance(self.data, dict):
            retained = dict(self.data)
            retained["intervals"] = list(self._recent_intervals)
            retained["failed_days"] = list(self._failed_days_this_poll)
            retained["stale"] = True
            return retained
        return {
            "intervals": list(self._recent_intervals),
            "total_kwh": None,
            "total_cost": None,
            "is_tod": None,
            "acct_type": None,
            "failed_days": list(self._failed_days_this_poll),
            "stale": True,
        }

    def _request_reauth(self) -> None:
        """Ask HA to show Update credentials once; never wipe downloaded history."""
        if self._reauth_requested:
            return
        self._reauth_requested = True
        self.hass.async_create_task(
            self.hass.config_entries.flow.async_init(
                DOMAIN,
                context={
                    "source": SOURCE_REAUTH,
                    "entry_id": self.entry.entry_id,
                },
                data=dict(self.entry.data),
            )
        )

    async def _async_soft_fail_poll(
        self,
        message: str,
        *,
        tracking: bool,
        auth_failed: bool = False,
        hard_exc: BaseException | None = None,
    ) -> dict[str, Any]:
        """Record a poll error without destroying already-downloaded state.

        When retained usage/billing/history exists, return the previous payload
        so entities stay available. Only raise when there is nothing to show yet
        (first setup) or MFA permanently blocks the account.
        """
        self._last_api_error = message
        if tracking:
            self.fail_sync_job(message)
            await self.async_persist_sync_progress()
        if auth_failed:
            self._request_reauth()
        if self.has_retained_state:
            _LOGGER.error(
                "PGE poll failed (%s) — keeping previously downloaded data; will retry",
                message,
            )
            return self._retained_poll_payload()
        if auth_failed:
            raise ConfigEntryAuthFailed(message) from hard_exc
        raise UpdateFailed(message) from hard_exc

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._async_poll_usage()
        finally:
            # Prefer the configured schedule — unless yesterday's hourly is still
            # incomplete; then catch up every CATCHUP_RETRY_HOURS.
            if self._catchup_retry and not self._refresh_job_active:
                self.update_interval = timedelta(hours=CATCHUP_RETRY_HOURS)
                _LOGGER.info(
                    "Yesterday hourly incomplete after scheduled poll — next catch-up in %s hour(s)",
                    CATCHUP_RETRY_HOURS,
                )
            else:
                self._refresh_update_interval()

    async def _async_poll_usage(self) -> dict[str, Any]:
        # Recover from a backfill task that died without clearing flags.
        if (
            self._backfill_task is not None
            and self._backfill_task.done()
            and (self._backfill_in_progress or self._sync_progress.status == SYNC_STATUS_BACKFILLING)
        ):
            _LOGGER.warning("PGE backfill task finished outside the normal path; releasing stuck state")
            await self.force_release_backfill("Backfill task terminated unexpectedly")
            return self._retained_poll_payload()

        # Do not contend for import_lock while a backfill is importing the same days.
        if self._backfill_in_progress or self._backfill_reserved:
            _LOGGER.debug("Skipping scheduled poll while backfill is in progress")
            return self._retained_poll_payload()

        tracking = self._refresh_job_active
        try:
            # Short-lived bearer: force a fresh login at the start of each poll.
            await self.auth_manager.ensure_valid_token(force=self.auth_manager.auth_mode == "credential")
            self.persist_auth_to_entry()
            self._reauth_requested = False
        except PGEMfaUnsupportedError as exc:
            # MFA is unsupported permanently — surface reauth/setup failure.
            if tracking:
                self.fail_sync_job(str(exc))
                await self.async_persist_sync_progress()
            raise ConfigEntryAuthFailed(str(exc)) from exc
        except PGEDiscoveryIncompleteError as exc:
            return await self._async_soft_fail_poll(
                str(exc),
                tracking=tracking,
                auth_failed=self.auth_manager.auth_mode != "credential",
                hard_exc=exc,
            )
        except PGEAuthenticationError as exc:
            return await self._async_soft_fail_poll(
                "Authentication failed",
                tracking=tracking,
                auth_failed=True,
                hard_exc=exc,
            )
        except PGEConnectionError as exc:
            # DNS/TLS blips during Cognito/Apigee renew must not blank the panel.
            return await self._async_soft_fail_poll(
                str(exc),
                tracking=tracking,
                hard_exc=exc,
            )

        now = datetime.now(UTC)
        window_start = now - timedelta(days=self.correction_window_days)
        # Always re-fetch the full correction window so backfilled days still
        # receive estimated→actual / cost corrections (DoD #7).
        days = list(iter_local_days(window_start, now))
        if tracking:
            self.update_sync_progress(
                phase=SYNC_PHASE_CORRECTION,
                total=len(days),
                done=0,
                message=f"Correction 0/{len(days)}",
            )
            await self.async_persist_sync_progress()

        all_intervals: list[UsageInterval] = []
        total_kwh = None
        total_cost = None
        is_tod = None
        acct_type = None
        failed_days: list[str] = []
        verified_days: list[str] = []
        days_finished = 0

        for day in days:
            day_start, day_end = local_day_bounds(day)
            request_end = day_end - timedelta(milliseconds=1)
            iso = day.isoformat()
            try:
                response = await self.async_get_usage_with_auth_retry(day_start, request_end)
            except PGEAuthenticationError as exc:
                return await self._async_soft_fail_poll(
                    "Authentication failed",
                    tracking=tracking,
                    auth_failed=True,
                    hard_exc=exc,
                )
            except PGERateLimitError as exc:
                return await self._async_soft_fail_poll(
                    f"Rate limited: {exc}",
                    tracking=tracking,
                    hard_exc=exc,
                )
            except (PGEConnectionError, PGEGraphQLError, PGESchemaError) as exc:
                self._last_api_error = str(exc)
                failed_days.append(iso)
                if iso not in self._import_store.failed_local_dates:
                    self._import_store.failed_local_dates.append(iso)
                await async_save_import_state(
                    self.hass,
                    self.entry.entry_id,
                    self._import_store,
                    critical=False,
                )
                days_finished += 1
                if tracking:
                    self.update_sync_progress(
                        done=days_finished,
                        message=f"Correction {days_finished}/{len(days)}",
                        error=str(exc),
                    )
                    await self.async_persist_sync_progress()
                continue

            clipped = clip_hourly_to_local_day(day, response.intervals)
            ok_complete, reason = validate_hourly_day(day, clipped, clip_boundary=False)
            if is_invalid_closed_day(ok_complete, reason):
                # Do NOT skip import: overnight polls often see gap/empty before PGE
                # finishes publishing. Skipping left stale daily midnight lumps and
                # blocked repair because the day stayed in completed_local_dates.
                self._last_api_error = f"{iso}:{reason}"
                failed_days.append(iso)
                if iso not in self._import_store.failed_local_dates:
                    self._import_store.failed_local_dates.append(iso)
                if iso in self._import_store.completed_local_dates:
                    self._import_store.completed_local_dates.remove(iso)
                if clipped:
                    all_intervals.extend(clipped)
                await async_save_import_state(
                    self.hass,
                    self.entry.entry_id,
                    self._import_store,
                    critical=False,
                )
                days_finished += 1
                if tracking:
                    self.update_sync_progress(
                        done=days_finished,
                        message=f"Correction {days_finished}/{len(days)}",
                        error=f"{iso}:{reason}",
                    )
                    await self.async_persist_sync_progress()
                continue

            if clipped:
                all_intervals.extend(clipped)
            if ok_complete:
                verified_days.append(iso)
            if response.total_kwh is not None:
                total_kwh = response.total_kwh
            if response.total_cost is not None:
                total_cost = response.total_cost
            if response.is_tod is not None:
                is_tod = response.is_tod
            if response.acct_type is not None:
                acct_type = response.acct_type

            days_finished += 1
            if tracking:
                self.update_sync_progress(
                    done=days_finished,
                    message=f"Correction {days_finished}/{len(days)}",
                )
                await self.async_persist_sync_progress()

        self._failed_days_this_poll = list(failed_days)
        # Never wipe last-known tip intervals on an empty/failed poll — history in
        # recorder is untouched, and sensors keep showing the prior tip sample.
        if all_intervals:
            self._recent_intervals = all_intervals

        if all_intervals:
            newest = max(iv.end for iv in all_intervals)
            if self._newest_interval is None or newest > self._newest_interval:
                self._newest_interval = newest

            dirty_from = min(iv.start for iv in all_intervals).isoformat()
            self._import_store.dirty_from = dirty_from
            await async_save_import_state(self.hass, self.entry.entry_id, self._import_store)
            try:
                async with self.import_lock:
                    await async_import_with_baseline(
                        self.hass,
                        self.account_key,
                        all_intervals,
                        include_cost=self.include_cost,
                        account_id=self.account_id,
                    )
                await self.async_refresh_lifetime_totals()
            except Exception as exc:
                err = _format_statistics_import_error(self.hass, exc)
                # Import merge failed — keep prior tip/lifetime; do not mark the
                # whole entry unavailable or clear already-imported history.
                return await self._async_soft_fail_poll(
                    err,
                    tracking=tracking,
                    hard_exc=exc,
                )

            self._import_store.dirty_from = None
            self._import_store.last_imported_start = min(iv.start for iv in all_intervals).isoformat()
            self._import_store.last_imported_end = max(iv.end for iv in all_intervals).isoformat()
            for iso in verified_days:
                if iso not in self._import_store.completed_local_dates:
                    self._import_store.completed_local_dates.append(iso)
                if iso in self._import_store.failed_local_dates:
                    self._import_store.failed_local_dates.remove(iso)
            await async_save_import_state(self.hass, self.entry.entry_id, self._import_store)
            self.update_checkpoint(
                min(iv.start for iv in all_intervals),
                max(iv.end for iv in all_intervals),
            )

        # Billing / programs after a usable usage result (soft-fail; never
        # breaks the usage poll). Skip when every correction day failed so an
        # outage does not waste billing GraphQL calls.
        if all_intervals or not failed_days:
            await async_run_billing_sync(self.hass, self)

        if failed_days and not all_intervals:
            return await self._async_soft_fail_poll(
                f"API error on {failed_days[0]}: {self._last_api_error}",
                tracking=tracking,
            )

        if failed_days:
            # Partial success: keep structured failures, do not claim clean poll.
            self._last_api_error = f"failed_days={','.join(failed_days)}"
            if tracking:
                self.fail_sync_job(self._last_api_error)
                await self.async_persist_sync_progress()
        else:
            self._last_api_error = None
            self._last_successful_update = now
            if tracking:
                self.complete_sync_job(message="Refresh done")
                await self.async_persist_sync_progress()

        # Scheduled catch-up: keep polling until yesterday's hourly validates.
        yesterday_iso = (today_local() - timedelta(days=1)).isoformat()
        self._catchup_retry = yesterday_iso in failed_days or (
            yesterday_iso in {d.isoformat() for d in days} and yesterday_iso not in verified_days
        )

        return {
            "intervals": all_intervals,
            "total_kwh": total_kwh,
            "total_cost": total_cost,
            "is_tod": is_tod,
            "acct_type": acct_type,
            "failed_days": failed_days,
        }

    def update_checkpoint(
        self,
        imported_start: datetime,
        imported_end: datetime,
    ) -> None:
        self._checkpoint = ImportCheckpoint(
            last_imported_start=imported_start,
            last_imported_end=imported_end,
            last_imported_timestamp=datetime.now(UTC),
            correction_window_start=imported_start,
            failed_ranges=list(self._checkpoint.failed_ranges),
        )

    def add_failed_range(self, start: datetime, end: datetime) -> None:
        iso = start.astimezone(UTC).date().isoformat()
        if iso not in self._import_store.failed_local_dates:
            self._import_store.failed_local_dates.append(iso)

    def set_backfill_state(
        self,
        in_progress: bool,
        oldest: datetime | None = None,
        newest: datetime | None = None,
        *,
        generation: int | None = None,
    ) -> None:
        if generation is not None:
            if generation != self._backfill_generation:
                return
        elif self._is_stale_backfill_generation():
            return
        self._backfill_in_progress = in_progress
        if not in_progress:
            self._backfill_reserved = False
        self._backfill_oldest = oldest
        self._backfill_newest = newest
