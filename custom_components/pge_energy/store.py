from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .bill_pdf_models import BillPdfIndexEntry
from .const import DOMAIN, IMPORT_STATE_SAVE_TIMEOUT

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 2
STORAGE_KEY = f"{DOMAIN}.import_state"

# One Store per entry so Store._write_lock serializes concurrent saves.
_STORES: dict[str, ImportStateStore] = {}


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
    """Drop the cached Store on unload so removed entries do not pin a hass ref."""
    _STORES.pop(entry_id, None)


async def async_load_import_state(hass: HomeAssistant, entry_id: str) -> ImportStoreData:
    store = _store_for_entry(hass, entry_id)
    raw = await store.async_load()
    return ImportStoreData.from_dict(raw)


async def async_save_import_state(
    hass: HomeAssistant,
    entry_id: str,
    data: ImportStoreData,
    *,
    critical: bool = True,
) -> None:
    """Persist import state with a wall-clock save timeout.

    ``critical=True`` (default) re-raises on timeout so checkpoint-bearing callers
    fail closed. ``critical=False`` logs and returns for cosmetic progress writes.
    """
    store = _store_for_entry(hass, entry_id)
    data.last_commit = datetime.now(UTC).isoformat()
    try:
        await asyncio.wait_for(store.async_save(data.to_dict()), timeout=IMPORT_STATE_SAVE_TIMEOUT)
    except TimeoutError:
        _LOGGER.warning("PGE import state save timed out for %s", entry_id[:8])
        if critical:
            raise


async def async_clear_import_state(hass: HomeAssistant, entry_id: str) -> None:
    store = _store_for_entry(hass, entry_id)
    await store.async_save(ImportStoreData().to_dict())
