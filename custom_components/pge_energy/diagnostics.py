from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ACCOUNT_ID,
    CONF_AUTH_MODE,
    CONF_BEARER_TOKEN,
    CONF_DOWNLOAD_BILL_PDFS,
    CONF_EMAIL,
    CONF_ENCRYPTED_PERSON_ID,
    CONF_PASSWORD,
    CONF_REFRESH_CREDENTIAL,
    CONF_SYNC_LOCAL_TIME,
    DEFAULT_SYNC_LOCAL_TIME,
    DOMAIN,
    ENTITY_UNIQUE_COST,
    ENTITY_UNIQUE_ENERGY,
    ENTITY_UNIQUE_TEMPERATURE,
    STATISTIC_ID_SUFFIX_CONSUMPTION,
    STATISTIC_ID_SUFFIX_COST,
    STATISTIC_ID_SUFFIX_TEMPERATURE,
)
from .options import get_entry_option
from .statistics import _get_statistic_id, async_resolve_sensor_entity_id

_LOGGER = logging.getLogger(__name__)

TO_REDACT = {
    CONF_BEARER_TOKEN,
    CONF_ENCRYPTED_PERSON_ID,
    CONF_ACCOUNT_ID,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_REFRESH_CREDENTIAL,
    CONF_TOKEN,
    "token",
    "access_token",
    "bearer_token",
    "encrypted_person_id",
    "encrypted_account_number",
    "encrypted_premise_id",
    "encrypted_sa_id",
    "account_id",
    "email",
    "password",
    "refresh_credential",
    "encrypted_bill_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    freshness = coordinator.freshness

    data = {
        "integration_version": "0.2.0",
        "ha_version": hass.version,
        "auth_mode": entry.data.get(CONF_AUTH_MODE),
        "token_expires_at": str(coordinator.auth_manager.token_expires_at)
        if coordinator.auth_manager.token_expires_at
        else None,
        "account_key": coordinator.account_key,
        "last_successful_update": str(freshness.last_successful_update) if freshness.last_successful_update else None,
        "last_imported_interval": str(coordinator.checkpoint.last_imported_end)
        if coordinator.checkpoint.last_imported_end
        else None,
        "newest_interval": str(freshness.newest_interval) if freshness.newest_interval else None,
        "polling_interval_minutes": coordinator.update_interval.total_seconds() / 60
        if coordinator.update_interval
        else None,
        "sync_local_time": get_entry_option(entry, CONF_SYNC_LOCAL_TIME, DEFAULT_SYNC_LOCAL_TIME),
        "correction_window_days": coordinator.correction_window_days,
        "recent_intervals_count": len(coordinator.recent_intervals),
        "failed_ranges_count": len(coordinator.failed_ranges),
        "last_api_error": freshness.last_api_error,
        "data_age_seconds": freshness.data_age_seconds,
        "lifetime_energy_kwh": coordinator.lifetime_energy_kwh,
        "lifetime_cost_usd": coordinator.lifetime_cost_usd,
        "external_statistics": {
            "consumption": _get_statistic_id(coordinator.account_key, STATISTIC_ID_SUFFIX_CONSUMPTION),
            "cost": _get_statistic_id(coordinator.account_key, STATISTIC_ID_SUFFIX_COST),
            "temperature": _get_statistic_id(coordinator.account_key, STATISTIC_ID_SUFFIX_TEMPERATURE),
        },
        "entity_statistics": {
            "energy": async_resolve_sensor_entity_id(hass, coordinator.account_key, ENTITY_UNIQUE_ENERGY),
            "cost": async_resolve_sensor_entity_id(hass, coordinator.account_key, ENTITY_UNIQUE_COST),
            "temperature": async_resolve_sensor_entity_id(hass, coordinator.account_key, ENTITY_UNIQUE_TEMPERATURE),
        },
        "bill_pdf": {
            "download_enabled": bool(get_entry_option(entry, CONF_DOWNLOAD_BILL_PDFS, False)),
            "indexed_bills": len(coordinator.import_store.bill_pdf_index),
            "last_success": coordinator.import_store.bill_pdf_last_success,
            "last_error": coordinator.import_store.bill_pdf_last_error,
            "parse_status": (coordinator.bill_pdf_summary or {}).get("parse_status"),
        },
    }

    redacted = async_redact_data(dict(entry.data), TO_REDACT | {"encrypted_bill_id"})
    return {"config_entry_data": redacted, "diagnostics": data}
