"""Websocket API for the PGE Energy panel."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .bill_pdf_statistics import BILL_PDF_METRIC_SUFFIXES
from .const import (
    BINARY_UNIQUE_AUTOPAY,
    BINARY_UNIQUE_PAPERLESS_BILL,
    BINARY_UNIQUE_PROGRAM_GREEN_FUTURE,
    BINARY_UNIQUE_PROGRAM_HABITAT_SUPPORT,
    BINARY_UNIQUE_PROGRAM_PEAK_TIME_REBATES,
    BINARY_UNIQUE_PROGRAM_SMART_BATTERY,
    BINARY_UNIQUE_PROGRAM_SMART_CHARGING,
    BINARY_UNIQUE_PROGRAM_SMART_THERMOSTAT,
    BINARY_UNIQUE_PROGRAM_TIME_OF_DAY,
    CONF_ACCOUNT_ID,
    CONF_ACCOUNT_KEY,
    CONF_AUTO_BACKFILL,
    CONF_BILL_PDF_FORM,
    CONF_BILL_PDF_RETENTION,
    CONF_BILL_PDF_ROLLING_COUNT,
    CONF_DOWNLOAD_BILL_PDFS,
    CONF_HISTORY_MODE,
    CONF_HISTORY_START_DATE,
    CONF_HOURLY_BACKFILL_DAYS,
    CONF_INCLUDE_BILLING,
    CONF_INCLUDE_COST,
    CONF_INCLUDE_DIAGNOSTICS,
    CONF_POLLING_INTERVAL,
    CONF_POLLING_INTERVAL_UNIT,
    CONF_SYNC_LOCAL_TIME,
    CONF_TOD_RATE_BASIC_SERVICE,
    CONF_TOD_RATE_MID_PEAK,
    CONF_TOD_RATE_OFF_PEAK,
    CONF_TOD_RATE_ON_PEAK,
    DEFAULT_AUTO_BACKFILL,
    DEFAULT_BILL_PDF_FORM,
    DEFAULT_BILL_PDF_RETENTION,
    DEFAULT_BILL_PDF_ROLLING_COUNT,
    DEFAULT_DOWNLOAD_BILL_PDFS,
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
    ENTITY_UNIQUE_COMPENSATION,
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
    ENTITY_UNIQUE_HOURLY_COMPENSATION,
    ENTITY_UNIQUE_HOURLY_COST,
    ENTITY_UNIQUE_HOURLY_ENERGY,
    ENTITY_UNIQUE_HOURLY_RETURN,
    ENTITY_UNIQUE_LAST_PAYMENT_AMOUNT,
    ENTITY_UNIQUE_LAST_PAYMENT_DATE,
    ENTITY_UNIQUE_LIFETIME_BILLED,
    ENTITY_UNIQUE_LIFETIME_PAYMENTS,
    ENTITY_UNIQUE_NET_METERING,
    ENTITY_UNIQUE_NEXT_PTR_EVENT_DATE,
    ENTITY_UNIQUE_RETURN,
    ENTITY_UNIQUE_SYNC_DETAIL,
    ENTITY_UNIQUE_SYNC_ERROR,
    ENTITY_UNIQUE_SYNC_ETA,
    ENTITY_UNIQUE_SYNC_PHASE,
    ENTITY_UNIQUE_SYNC_PROGRESS,
    ENTITY_UNIQUE_SYNC_STATUS,
    ENTITY_UNIQUE_TEMPERATURE,
    ENTITY_UNIQUE_TOD_PERIOD,
    ENTITY_UNIQUE_TOD_PRICE,
    ENTITY_UNIQUE_TOD_VS_BASIC_SAVINGS,
    ENTITY_UNIQUE_YESTERDAY_COMPENSATION,
    ENTITY_UNIQUE_YESTERDAY_COST,
    ENTITY_UNIQUE_YESTERDAY_ENERGY,
    ENTITY_UNIQUE_YESTERDAY_RETURN,
    ENTITY_UNIQUE_YTD_PROGRAM_SAVINGS,
    STATISTIC_ID_SUFFIX_ACCOUNT_BALANCE,
    STATISTIC_ID_SUFFIX_AMOUNT_DUE,
    STATISTIC_ID_SUFFIX_BILL_AMOUNT,
    STATISTIC_ID_SUFFIX_BILL_AVG_TEMPERATURE,
    STATISTIC_ID_SUFFIX_BILL_KWH,
    STATISTIC_ID_SUFFIX_COMPENSATION,
    STATISTIC_ID_SUFFIX_CONSUMPTION,
    STATISTIC_ID_SUFFIX_COST,
    STATISTIC_ID_SUFFIX_LAST_PAYMENT_AMOUNT,
    STATISTIC_ID_SUFFIX_PAYMENT_AMOUNT,
    STATISTIC_ID_SUFFIX_RETURN,
    STATISTIC_ID_SUFFIX_TEMPERATURE,
    STATISTIC_ID_SUFFIX_YTD_PROGRAM_SAVINGS,
    WS_SETUP_KEY,
)
from .coordinator import PGECoordinator
from .options import get_entry_option
from .tod_pricing import (
    resolve_basic_from_catalog,
    tod_overrides_from_entry,
)
from .tod_tariff import serialize_tariff_catalogs

_LOGGER = logging.getLogger(__name__)

_SENSOR_ROLES: dict[str, str] = {
    "energy": ENTITY_UNIQUE_ENERGY,
    "return": ENTITY_UNIQUE_RETURN,
    "cost": ENTITY_UNIQUE_COST,
    "compensation": ENTITY_UNIQUE_COMPENSATION,
    "temperature": ENTITY_UNIQUE_TEMPERATURE,
    "hourly_energy": ENTITY_UNIQUE_HOURLY_ENERGY,
    "hourly_return": ENTITY_UNIQUE_HOURLY_RETURN,
    "hourly_cost": ENTITY_UNIQUE_HOURLY_COST,
    "hourly_compensation": ENTITY_UNIQUE_HOURLY_COMPENSATION,
    "current_day_energy": "current_day_energy",
    "current_day_cost": "current_day_cost",
    "yesterday_energy": ENTITY_UNIQUE_YESTERDAY_ENERGY,
    "yesterday_return": ENTITY_UNIQUE_YESTERDAY_RETURN,
    "yesterday_cost": ENTITY_UNIQUE_YESTERDAY_COST,
    "yesterday_compensation": ENTITY_UNIQUE_YESTERDAY_COMPENSATION,
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
    "tod_period": ENTITY_UNIQUE_TOD_PERIOD,
    "tod_price": ENTITY_UNIQUE_TOD_PRICE,
    "tod_vs_basic_savings": ENTITY_UNIQUE_TOD_VS_BASIC_SAVINGS,
    "next_ptr_event_date": ENTITY_UNIQUE_NEXT_PTR_EVENT_DATE,
    "net_metering": ENTITY_UNIQUE_NET_METERING,
}

_BINARY_ROLES: dict[str, str] = {
    "autopay": BINARY_UNIQUE_AUTOPAY,
    "paperless_bill": BINARY_UNIQUE_PAPERLESS_BILL,
    "program_peak_time_rebates": BINARY_UNIQUE_PROGRAM_PEAK_TIME_REBATES,
    "program_green_future": BINARY_UNIQUE_PROGRAM_GREEN_FUTURE,
    "program_time_of_day": BINARY_UNIQUE_PROGRAM_TIME_OF_DAY,
    "program_smart_thermostat": BINARY_UNIQUE_PROGRAM_SMART_THERMOSTAT,
    "program_habitat_support": BINARY_UNIQUE_PROGRAM_HABITAT_SUPPORT,
    "program_smart_charging": BINARY_UNIQUE_PROGRAM_SMART_CHARGING,
    "program_smart_battery": BINARY_UNIQUE_PROGRAM_SMART_BATTERY,
}

_STAT_SUFFIXES: dict[str, str] = {
    "consumption": STATISTIC_ID_SUFFIX_CONSUMPTION,
    "return": STATISTIC_ID_SUFFIX_RETURN,
    "cost": STATISTIC_ID_SUFFIX_COST,
    "compensation": STATISTIC_ID_SUFFIX_COMPENSATION,
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


def _bill_pdf_statistic_ids(account_key: str) -> dict[str, str]:
    return {key: f"{DOMAIN}:{account_key}{suffix}" for key, suffix in BILL_PDF_METRIC_SUFFIXES.items()}


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
            "download_bill_pdfs": bool(get_entry_option(entry, CONF_DOWNLOAD_BILL_PDFS, DEFAULT_DOWNLOAD_BILL_PDFS)),
            "bill_pdf_form": str(get_entry_option(entry, CONF_BILL_PDF_FORM, DEFAULT_BILL_PDF_FORM)),
            "bill_pdf_retention": str(get_entry_option(entry, CONF_BILL_PDF_RETENTION, DEFAULT_BILL_PDF_RETENTION)),
            "bill_pdf_rolling_count": int(
                get_entry_option(entry, CONF_BILL_PDF_ROLLING_COUNT, DEFAULT_BILL_PDF_ROLLING_COUNT)
            ),
            "tod_rate_off_peak": get_entry_option(entry, CONF_TOD_RATE_OFF_PEAK, None),
            "tod_rate_mid_peak": get_entry_option(entry, CONF_TOD_RATE_MID_PEAK, None),
            "tod_rate_on_peak": get_entry_option(entry, CONF_TOD_RATE_ON_PEAK, None),
            "tod_rate_basic_service": get_entry_option(entry, CONF_TOD_RATE_BASIC_SERVICE, None),
        },
        "statistic_ids": _statistic_ids(account_key),
        "bill_pdf_statistic_ids": _bill_pdf_statistic_ids(account_key),
        "bill_pdf": dict(coordinator.bill_pdf_summary or {}),
        "tod": _tod_payload(coordinator),
        "entity_ids": _entity_ids(hass, account_key),
    }


def _tod_enrolled_from_programs(programs_snap: object | None) -> bool | None:
    """Read TOD enrollment from ``ProgramsSnapshot`` (dataclass, not a mapping)."""
    if programs_snap is None:
        return None
    enrolled = getattr(programs_snap, "time_of_day_enrolled", None)
    return enrolled if isinstance(enrolled, bool) else None


@callback
def _tod_payload(coordinator: PGECoordinator) -> dict[str, Any]:
    """Effective E-TOU period/rates/sources + portal snapshot + catalog data for the panel."""
    tod = coordinator.tod
    rate_card = tod.rate_card
    snapshot = coordinator.tod_snapshot
    savings_total = snapshot.savings_total if snapshot is not None else None
    savings_source: str | None = "pricing_plan" if savings_total is not None else None
    rate_compare = coordinator.rate_compare_snapshot
    rate_compare_payload: dict[str, Any] | None = None
    if rate_compare is not None and rate_compare.has_data:
        rate_compare_payload = {
            "savings": rate_compare.savings,
            "tou_total": rate_compare.tou_total,
            "basic_total": rate_compare.basic_total,
            "comparison_period": rate_compare.comparison_period,
            "fetched_at": rate_compare.fetched_at.isoformat() if rate_compare.fetched_at else None,
        }
        if savings_total is None and rate_compare.savings is not None:
            savings_total = rate_compare.savings
            savings_source = "rate_compare"

    enrolled = _tod_enrolled_from_programs(coordinator.programs_snapshot)

    # Effective-dated catalog data from the domain tariff updater.
    hass = coordinator.hass
    tariff_key = f"{DOMAIN}_tariff_updater"
    tariff_coord = hass.data.get(DOMAIN, {}).get(tariff_key)
    tod_rows = tariff_coord.tod_rows if tariff_coord else []
    basic_rows = tariff_coord.basic_rows if tariff_coord else []

    # Serialize catalogs for the panel.
    catalogs_payload = serialize_tariff_catalogs(tod_rows, basic_rows)

    # Tariff updater status.
    tariff_status: dict[str, Any] = {}
    if tariff_coord is not None:
        sd = tariff_coord.store_data
        tariff_status = {
            "last_attempt": sd.last_attempt,
            "last_success": sd.last_success,
            "next_check": sd.next_retry,
            "is_stale": tariff_coord.is_stale,
            "last_error": sd.last_error,
        }

    # Manual override validity check — "entire_range" only when all three TOD
    # periods and basic_service have overrides (estimator requires all four).
    overrides = tod_overrides_from_entry(coordinator.entry)
    override_valid = {k: v for k, v in overrides.items() if isinstance(v, (int, float)) and v > 0}
    has_all_tod_overrides = all(p in override_valid for p in ("off_peak", "mid_peak", "on_peak"))
    has_all_overrides = has_all_tod_overrides and "basic_service" in override_valid

    # Resolve basic comparison rate from catalog.
    basic_rate_val, basic_src, basic_eff, basic_basis, basic_exc = resolve_basic_from_catalog(overrides, basic_rows)

    return {
        "period": tod.period.value,
        "is_holiday": tod.is_holiday,
        "is_weekend": tod.is_weekend,
        "next_transition_at": (tod.next_transition_at.isoformat() if tod.next_transition_at is not None else None),
        "rate_source": tod.current_rate_source,
        "rates": dict(rate_card.rates),
        "sources": dict(rate_card.sources),
        "basic_rate": rate_card.basic_rate,
        "basic_rate_source": rate_card.basic_source,
        "savings_total": savings_total,
        "savings_source": savings_source,
        "rate_compare": rate_compare_payload,
        "portal_fetched_at": (
            snapshot.fetched_at.isoformat() if snapshot is not None and snapshot.fetched_at else None
        ),
        # New fields for v0.10.0
        "enrolled": enrolled,
        "catalogs": catalogs_payload,
        "tariff_status": tariff_status,
        "basic_comparison_rate": basic_rate_val,
        "basic_comparison_source": basic_src,
        "basic_comparison_effective_from": basic_eff,
        "basic_comparison_component_basis": basic_basis,
        "basic_comparison_exclusions": basic_exc,
        "override_rates": override_valid,
        "override_scope": "entire_range" if has_all_overrides else None,
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
