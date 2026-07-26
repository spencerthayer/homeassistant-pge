"""Websocket API for the PGE Energy panel."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    BINARY_UNIQUE_AUTOPAY,
    BINARY_UNIQUE_PAPERLESS_BILL,
    BINARY_UNIQUE_PROGRAM_GREEN_FUTURE,
    BINARY_UNIQUE_PROGRAM_HABITAT_SUPPORT,
    BINARY_UNIQUE_PROGRAM_PEAK_TIME_REBATES,
    BINARY_UNIQUE_PROGRAM_SMART_THERMOSTAT,
    BINARY_UNIQUE_PROGRAM_TIME_OF_DAY,
    CONF_ACCOUNT_ID,
    CONF_ACCOUNT_KEY,
    CONF_AUTO_BACKFILL,
    CONF_HISTORY_MODE,
    CONF_HISTORY_START_DATE,
    CONF_HOURLY_BACKFILL_DAYS,
    CONF_INCLUDE_BILLING,
    CONF_INCLUDE_COST,
    CONF_INCLUDE_DIAGNOSTICS,
    CONF_POLLING_INTERVAL,
    CONF_POLLING_INTERVAL_UNIT,
    CONF_SYNC_LOCAL_TIME,
    DEFAULT_AUTO_BACKFILL,
    DEFAULT_HISTORY_MODE,
    DEFAULT_HOURLY_BACKFILL_DAYS,
    DEFAULT_INCLUDE_BILLING,
    DEFAULT_INCLUDE_COST,
    DEFAULT_INCLUDE_DIAGNOSTICS,
    DEFAULT_POLLING_INTERVAL,
    DEFAULT_POLLING_INTERVAL_UNIT,
    DEFAULT_SYNC_LOCAL_TIME,
    DOMAIN,
    ENTITY_UNIQUE_ACCOUNT_BALANCE,
    ENTITY_UNIQUE_AMOUNT_DUE,
    ENTITY_UNIQUE_BILL_AVG_TEMPERATURE,
    ENTITY_UNIQUE_BILL_CURRENT_CHARGES,
    ENTITY_UNIQUE_BILL_PREVIOUS_BALANCE,
    ENTITY_UNIQUE_BILLING_CYCLE_DAY,
    ENTITY_UNIQUE_BILLING_CYCLE_TOTAL_DAYS,
    ENTITY_UNIQUE_BILLING_LAST_SYNC,
    ENTITY_UNIQUE_COST,
    ENTITY_UNIQUE_CURRENT_BILL_AMOUNT,
    ENTITY_UNIQUE_CURRENT_BILL_END,
    ENTITY_UNIQUE_CURRENT_BILL_KWH,
    ENTITY_UNIQUE_CURRENT_BILL_START,
    ENTITY_UNIQUE_DUE_DATE,
    ENTITY_UNIQUE_ENERGY,
    ENTITY_UNIQUE_EST_CURRENT_CHARGES,
    ENTITY_UNIQUE_EST_NEXT_BILL_MAX,
    ENTITY_UNIQUE_EST_NEXT_BILL_MIN,
    ENTITY_UNIQUE_HOURLY_COST,
    ENTITY_UNIQUE_HOURLY_ENERGY,
    ENTITY_UNIQUE_LAST_PAYMENT_AMOUNT,
    ENTITY_UNIQUE_LAST_PAYMENT_DATE,
    ENTITY_UNIQUE_LIFETIME_BILLED,
    ENTITY_UNIQUE_LIFETIME_PAYMENTS,
    ENTITY_UNIQUE_SYNC_DETAIL,
    ENTITY_UNIQUE_SYNC_ERROR,
    ENTITY_UNIQUE_SYNC_ETA,
    ENTITY_UNIQUE_SYNC_PHASE,
    ENTITY_UNIQUE_SYNC_PROGRESS,
    ENTITY_UNIQUE_SYNC_STATUS,
    ENTITY_UNIQUE_TEMPERATURE,
    ENTITY_UNIQUE_YESTERDAY_COST,
    ENTITY_UNIQUE_YESTERDAY_ENERGY,
    ENTITY_UNIQUE_YTD_PROGRAM_SAVINGS,
    STATISTIC_ID_SUFFIX_ACCOUNT_BALANCE,
    STATISTIC_ID_SUFFIX_AMOUNT_DUE,
    STATISTIC_ID_SUFFIX_BILL_AMOUNT,
    STATISTIC_ID_SUFFIX_BILL_AVG_TEMPERATURE,
    STATISTIC_ID_SUFFIX_BILL_KWH,
    STATISTIC_ID_SUFFIX_CONSUMPTION,
    STATISTIC_ID_SUFFIX_COST,
    STATISTIC_ID_SUFFIX_LAST_PAYMENT_AMOUNT,
    STATISTIC_ID_SUFFIX_PAYMENT_AMOUNT,
    STATISTIC_ID_SUFFIX_TEMPERATURE,
    STATISTIC_ID_SUFFIX_YTD_PROGRAM_SAVINGS,
    WS_SETUP_KEY,
)
from .coordinator import PGECoordinator
from .options import get_entry_option

_LOGGER = logging.getLogger(__name__)

_SENSOR_ROLES: dict[str, str] = {
    "energy": ENTITY_UNIQUE_ENERGY,
    "cost": ENTITY_UNIQUE_COST,
    "temperature": ENTITY_UNIQUE_TEMPERATURE,
    "hourly_energy": ENTITY_UNIQUE_HOURLY_ENERGY,
    "hourly_cost": ENTITY_UNIQUE_HOURLY_COST,
    "current_day_energy": "current_day_energy",
    "current_day_cost": "current_day_cost",
    "yesterday_energy": ENTITY_UNIQUE_YESTERDAY_ENERGY,
    "yesterday_cost": ENTITY_UNIQUE_YESTERDAY_COST,
    "last_update": "last_update",
    "latest_interval": "latest_interval",
    "data_age": "data_age",
    "auth_expiration": "auth_expiration",
    "last_api_error": "last_api_error",
    "sync_status": ENTITY_UNIQUE_SYNC_STATUS,
    "sync_phase": ENTITY_UNIQUE_SYNC_PHASE,
    "sync_progress": ENTITY_UNIQUE_SYNC_PROGRESS,
    "sync_eta": ENTITY_UNIQUE_SYNC_ETA,
    "sync_detail": ENTITY_UNIQUE_SYNC_DETAIL,
    "sync_error": ENTITY_UNIQUE_SYNC_ERROR,
    "account_balance": ENTITY_UNIQUE_ACCOUNT_BALANCE,
    "amount_due": ENTITY_UNIQUE_AMOUNT_DUE,
    "due_date": ENTITY_UNIQUE_DUE_DATE,
    "last_payment_amount": ENTITY_UNIQUE_LAST_PAYMENT_AMOUNT,
    "last_payment_date": ENTITY_UNIQUE_LAST_PAYMENT_DATE,
    "current_bill_amount": ENTITY_UNIQUE_CURRENT_BILL_AMOUNT,
    "current_bill_kwh": ENTITY_UNIQUE_CURRENT_BILL_KWH,
    "current_bill_start": ENTITY_UNIQUE_CURRENT_BILL_START,
    "current_bill_end": ENTITY_UNIQUE_CURRENT_BILL_END,
    "bill_previous_balance": ENTITY_UNIQUE_BILL_PREVIOUS_BALANCE,
    "bill_current_charges": ENTITY_UNIQUE_BILL_CURRENT_CHARGES,
    "bill_avg_temperature": ENTITY_UNIQUE_BILL_AVG_TEMPERATURE,
    "ytd_program_savings": ENTITY_UNIQUE_YTD_PROGRAM_SAVINGS,
    "lifetime_payments": ENTITY_UNIQUE_LIFETIME_PAYMENTS,
    "lifetime_billed": ENTITY_UNIQUE_LIFETIME_BILLED,
    "billing_last_sync": ENTITY_UNIQUE_BILLING_LAST_SYNC,
    "est_current_charges": ENTITY_UNIQUE_EST_CURRENT_CHARGES,
    "est_next_bill_min": ENTITY_UNIQUE_EST_NEXT_BILL_MIN,
    "est_next_bill_max": ENTITY_UNIQUE_EST_NEXT_BILL_MAX,
    "billing_cycle_day": ENTITY_UNIQUE_BILLING_CYCLE_DAY,
    "billing_cycle_total_days": ENTITY_UNIQUE_BILLING_CYCLE_TOTAL_DAYS,
}

_BINARY_ROLES: dict[str, str] = {
    "autopay": BINARY_UNIQUE_AUTOPAY,
    "paperless_bill": BINARY_UNIQUE_PAPERLESS_BILL,
    "program_peak_time_rebates": BINARY_UNIQUE_PROGRAM_PEAK_TIME_REBATES,
    "program_green_future": BINARY_UNIQUE_PROGRAM_GREEN_FUTURE,
    "program_time_of_day": BINARY_UNIQUE_PROGRAM_TIME_OF_DAY,
    "program_smart_thermostat": BINARY_UNIQUE_PROGRAM_SMART_THERMOSTAT,
    "program_habitat_support": BINARY_UNIQUE_PROGRAM_HABITAT_SUPPORT,
}

_STAT_SUFFIXES: dict[str, str] = {
    "consumption": STATISTIC_ID_SUFFIX_CONSUMPTION,
    "cost": STATISTIC_ID_SUFFIX_COST,
    "temperature": STATISTIC_ID_SUFFIX_TEMPERATURE,
    "account_balance": STATISTIC_ID_SUFFIX_ACCOUNT_BALANCE,
    "amount_due": STATISTIC_ID_SUFFIX_AMOUNT_DUE,
    "last_payment_amount": STATISTIC_ID_SUFFIX_LAST_PAYMENT_AMOUNT,
    "bill_avg_temperature": STATISTIC_ID_SUFFIX_BILL_AVG_TEMPERATURE,
    "ytd_program_savings": STATISTIC_ID_SUFFIX_YTD_PROGRAM_SAVINGS,
    "bill_amount": STATISTIC_ID_SUFFIX_BILL_AMOUNT,
    "bill_kwh": STATISTIC_ID_SUFFIX_BILL_KWH,
    "payment_amount": STATISTIC_ID_SUFFIX_PAYMENT_AMOUNT,
}


def async_setup_websocket(hass: HomeAssistant) -> None:
    """Register panel websocket commands once per HA instance."""
    if hass.data.get(WS_SETUP_KEY):
        return
    websocket_api.async_register_command(hass, websocket_accounts)
    websocket_api.async_register_command(hass, websocket_sync_subscribe)
    hass.data[WS_SETUP_KEY] = True
    _LOGGER.debug("Registered PGE Energy websocket commands")


@callback
def _resolve_entity_id(
    hass: HomeAssistant,
    platform: str,
    account_key: str,
    unique_suffix: str,
) -> str | None:
    return er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{account_key}_{unique_suffix}")


@callback
def _statistic_ids(account_key: str) -> dict[str, str]:
    return {role: f"{DOMAIN}:{account_key}{suffix}" for role, suffix in _STAT_SUFFIXES.items()}


@callback
def _entity_ids(hass: HomeAssistant, account_key: str) -> dict[str, str | None]:
    entities: dict[str, str | None] = {
        role: _resolve_entity_id(hass, "sensor", account_key, suffix) for role, suffix in _SENSOR_ROLES.items()
    }
    for role, suffix in _BINARY_ROLES.items():
        entities[role] = _resolve_entity_id(hass, "binary_sensor", account_key, suffix)
    return entities


@callback
def _account_payload(hass: HomeAssistant, entry_id: str, coordinator: PGECoordinator) -> dict[str, Any]:
    entry = coordinator.entry
    account_key = entry.data.get(CONF_ACCOUNT_KEY) or coordinator.account_key
    account_id = entry.data.get(CONF_ACCOUNT_ID) or coordinator.account_id
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, account_key)})
    return {
        "entry_id": entry_id,
        "title": entry.title,
        "account_id": account_id,
        "account_key": account_key,
        "device_id": device.id if device is not None else None,
        "options": {
            "include_billing": bool(get_entry_option(entry, CONF_INCLUDE_BILLING, DEFAULT_INCLUDE_BILLING)),
            "include_cost": bool(get_entry_option(entry, CONF_INCLUDE_COST, DEFAULT_INCLUDE_COST)),
            "include_diagnostics": bool(get_entry_option(entry, CONF_INCLUDE_DIAGNOSTICS, DEFAULT_INCLUDE_DIAGNOSTICS)),
            "auto_backfill": bool(get_entry_option(entry, CONF_AUTO_BACKFILL, DEFAULT_AUTO_BACKFILL)),
            "polling_interval": get_entry_option(entry, CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL),
            "polling_interval_unit": str(
                get_entry_option(entry, CONF_POLLING_INTERVAL_UNIT, DEFAULT_POLLING_INTERVAL_UNIT)
            ),
            "sync_local_time": get_entry_option(entry, CONF_SYNC_LOCAL_TIME, DEFAULT_SYNC_LOCAL_TIME),
            "history_mode": str(get_entry_option(entry, CONF_HISTORY_MODE, DEFAULT_HISTORY_MODE)),
            "history_start_date": get_entry_option(entry, CONF_HISTORY_START_DATE, None),
            "hourly_backfill_days": get_entry_option(entry, CONF_HOURLY_BACKFILL_DAYS, DEFAULT_HOURLY_BACKFILL_DAYS),
        },
        "statistic_ids": _statistic_ids(account_key),
        "entity_ids": _entity_ids(hass, account_key),
    }


@callback
def _sync_payload(entry_id: str, coordinator: PGECoordinator) -> dict[str, Any]:
    snap = coordinator.sync_progress
    freshness = coordinator.freshness
    auth = coordinator.auth_manager
    return {
        "entry_id": entry_id,
        "status": snap.status,
        "phase": snap.phase,
        "done": snap.done,
        "total": snap.total,
        "percent": snap.percent,
        "eta_seconds": snap.eta_seconds,
        "message": snap.message,
        "error": snap.error,
        "last_successful_update": (
            freshness.last_successful_update.isoformat() if freshness.last_successful_update else None
        ),
        "newest_interval": (freshness.newest_interval.isoformat() if freshness.newest_interval else None),
        "data_age_seconds": freshness.data_age_seconds,
        "last_api_error": freshness.last_api_error,
        "auth_expiration": (auth.token_expires_at.isoformat() if auth.token_expires_at else None),
    }


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/accounts"})
@websocket_api.require_admin
@callback
def websocket_accounts(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return credential-free account metadata for every loaded entry."""
    domain_data = hass.data.get(DOMAIN, {})
    accounts = [
        _account_payload(hass, entry_id, coordinator)
        for entry_id, coordinator in domain_data.items()
        if isinstance(coordinator, PGECoordinator)
    ]
    connection.send_result(msg["id"], {"accounts": accounts})


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/sync/subscribe"})
@websocket_api.require_admin
@callback
def websocket_sync_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Push sync progress for all entries; tears down on connection close."""
    domain_data = hass.data.get(DOMAIN, {})
    unsubs: list[Any] = []

    def _push_all() -> None:
        payload = {
            "entries": [
                _sync_payload(entry_id, coordinator)
                for entry_id, coordinator in hass.data.get(DOMAIN, {}).items()
                if isinstance(coordinator, PGECoordinator)
            ]
        }
        connection.send_message(websocket_api.event_message(msg["id"], payload))

    for entry_id, coordinator in domain_data.items():
        if not isinstance(coordinator, PGECoordinator):
            continue
        # Capture entry_id for the closure even though we push all entries.
        _ = entry_id
        unsubs.append(coordinator.async_add_listener(_push_all))

    @callback
    def _unsubscribe() -> None:
        for unsub in unsubs:
            unsub()

    connection.subscriptions[msg["id"]] = _unsubscribe
    connection.send_result(msg["id"])
    _push_all()
