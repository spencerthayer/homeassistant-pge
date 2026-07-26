from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.import_state"


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
    sync_started_at: float | None = None
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ImportStoreData:
        if not data:
            return cls()
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
            sync_started_at=(float(data["sync_started_at"]) if data.get("sync_started_at") is not None else None),
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
        )


def _store_for_entry(hass: HomeAssistant, entry_id: str) -> Store:
    return Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry_id}")


async def async_load_import_state(hass: HomeAssistant, entry_id: str) -> ImportStoreData:
    store = _store_for_entry(hass, entry_id)
    raw = await store.async_load()
    return ImportStoreData.from_dict(raw)


async def async_save_import_state(hass: HomeAssistant, entry_id: str, data: ImportStoreData) -> None:
    store = _store_for_entry(hass, entry_id)
    data.last_commit = datetime.now(UTC).isoformat()
    await store.async_save(data.to_dict())


async def async_clear_import_state(hass: HomeAssistant, entry_id: str) -> None:
    store = _store_for_entry(hass, entry_id)
    await store.async_save(ImportStoreData().to_dict())
