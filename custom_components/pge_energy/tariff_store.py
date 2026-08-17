"""Domain-global HA Store for tariff catalogs.

Shared by all PGE config entries so a multi-account installation performs one
public-source refresh and uses one residential catalog.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .tod_tariff import (
    BasicComparisonRow,
    TodTariffRow,
    bundled_basic_rows,
    bundled_tod_rows,
    deserialize_row_from_store,
    merge_validated_catalog,
    serialize_row_for_store,
    validate_basic_catalog,
    validate_tod_catalog,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.tariffs"

# Maximum audit entries retained per catalog.
_MAX_AUDIT_ENTRIES = 20


class TariffStore(Store):
    """HA Store with versioned schema for tariff catalogs."""

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        if old_major_version < STORAGE_VERSION:
            migrated = dict(old_data)
            migrated.setdefault("tod_rows", [])
            migrated.setdefault("basic_rows", [])
            migrated.setdefault("tod_audit", [])
            migrated.setdefault("basic_audit", [])
            migrated.setdefault("etag_map", {})
            migrated.setdefault("last_modified_map", {})
            migrated.setdefault("last_attempt", None)
            migrated.setdefault("last_success", None)
            migrated.setdefault("last_error", None)
            migrated.setdefault("next_retry", None)
            migrated.setdefault("parser_version", 1)
            migrated["schema_version"] = STORAGE_VERSION
            return migrated
        return old_data


@dataclass
class TariffStoreData:
    """Versioned domain-global tariff catalog state."""

    schema_version: int = STORAGE_VERSION
    # Active validated rows (chronologically sorted).
    tod_rows: list[dict[str, Any]] = field(default_factory=list)
    basic_rows: list[dict[str, Any]] = field(default_factory=list)
    # Bounded supersession audit trail.
    tod_audit: list[dict[str, Any]] = field(default_factory=list)
    basic_audit: list[dict[str, Any]] = field(default_factory=list)
    # HTTP freshness per URL.
    etag_map: dict[str, str] = field(default_factory=dict)
    last_modified_map: dict[str, str] = field(default_factory=dict)
    # Coordinator state.
    last_attempt: str | None = None
    last_success: str | None = None
    last_error: str | None = None
    next_retry: str | None = None
    parser_version: int = 1


_store_instance: TariffStore | None = None


def _get_store(hass: HomeAssistant) -> TariffStore:
    global _store_instance
    if _store_instance is not None and _store_instance.hass is not hass:
        _store_instance = None
    if _store_instance is None:
        _store_instance = TariffStore(hass, STORAGE_VERSION, STORAGE_KEY)
    return _store_instance


async def async_load_tariff_catalogs(
    hass: HomeAssistant,
) -> tuple[list[TodTariffRow], list[BasicComparisonRow], TariffStoreData]:
    """Load tariff catalogs from Store, merged with bundled seeds.

    Returns (tod_rows, basic_rows, store_data).
    """
    store = _get_store(hass)
    raw = await store.async_load()
    data = TariffStoreData()

    if isinstance(raw, dict):
        data.tod_rows = raw.get("tod_rows") or []
        data.basic_rows = raw.get("basic_rows") or []
        data.tod_audit = raw.get("tod_audit") or []
        data.basic_audit = raw.get("basic_audit") or []
        data.etag_map = raw.get("etag_map") or {}
        data.last_modified_map = raw.get("last_modified_map") or {}
        data.last_attempt = raw.get("last_attempt")
        data.last_success = raw.get("last_success")
        data.last_error = raw.get("last_error")
        data.next_retry = raw.get("next_retry")
        data.parser_version = raw.get("parser_version", 1)

    # Deserialize stored rows
    stored_tod: list[TodTariffRow] = []
    stored_basic: list[BasicComparisonRow] = []
    for rd in data.tod_rows:
        row = deserialize_row_from_store(rd)
        if isinstance(row, TodTariffRow):
            stored_tod.append(row)
    for rd in data.basic_rows:
        row = deserialize_row_from_store(rd)
        if isinstance(row, BasicComparisonRow):
            stored_basic.append(row)

    # Merge with bundled seeds
    merged_tod = merge_validated_catalog(bundled_tod_rows(), stored_tod, [])
    merged_basic = merge_validated_catalog(bundled_basic_rows(), stored_basic, [])

    return merged_tod, merged_basic, data


async def async_save_tariff_catalogs(
    hass: HomeAssistant,
    tod_rows: list[TodTariffRow],
    basic_rows: list[BasicComparisonRow],
    store_data: TariffStoreData,
) -> None:
    """Validate and persist tariff catalogs atomically."""
    # Validate before saving
    tod_errors = validate_tod_catalog(tod_rows)
    basic_errors = validate_basic_catalog(basic_rows)
    if tod_errors:
        _LOGGER.warning("TOD catalog validation errors, not saving: %s", tod_errors)
        return
    if basic_errors:
        _LOGGER.warning("Basic catalog validation errors, not saving: %s", basic_errors)
        return

    store_data.tod_rows = [serialize_row_for_store(r) for r in tod_rows]
    store_data.basic_rows = [serialize_row_for_store(r) for r in basic_rows]
    store_data.parser_version = 1

    # Trim audit
    if len(store_data.tod_audit) > _MAX_AUDIT_ENTRIES:
        store_data.tod_audit = store_data.tod_audit[-_MAX_AUDIT_ENTRIES:]
    if len(store_data.basic_audit) > _MAX_AUDIT_ENTRIES:
        store_data.basic_audit = store_data.basic_audit[-_MAX_AUDIT_ENTRIES:]

    store = _get_store(hass)
    payload = {
        "tod_rows": store_data.tod_rows,
        "basic_rows": store_data.basic_rows,
        "tod_audit": store_data.tod_audit,
        "basic_audit": store_data.basic_audit,
        "etag_map": store_data.etag_map,
        "last_modified_map": store_data.last_modified_map,
        "last_attempt": store_data.last_attempt,
        "last_success": store_data.last_success,
        "last_error": store_data.last_error,
        "next_retry": store_data.next_retry,
        "parser_version": store_data.parser_version,
    }
    await store.async_save(payload)


def add_supersession_audit(
    audit_log: list[dict[str, Any]],
    old_row: TodTariffRow | BasicComparisonRow | None,
    new_row: TodTariffRow | BasicComparisonRow,
    reason: str,
) -> None:
    """Append a bounded audit entry for a same-date official correction."""
    entry: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "effective_from": new_row.effective_from,
        "reason": reason,
    }
    if old_row is not None:
        entry["old_sha256"] = old_row.source.sha256[:16]
        entry["old_source_url"] = old_row.source.url
    entry["new_sha256"] = new_row.source.sha256[:16]
    entry["new_source_url"] = new_row.source.url
    audit_log.append(entry)
