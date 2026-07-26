from __future__ import annotations

import logging
from datetime import date, datetime

import voluptuous as vol
from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .api import PGEApiClient
from .auth import PGEAuthManager
from .backfill import async_backfill_range, async_fetch_hourly_day
from .billing_sync import async_run_billing_sync
from .const import (
    AUTH_MODE_CREDENTIAL,
    CONF_ACCOUNT_ID,
    CONF_ACCOUNT_KEY,
    CONF_AUTH_MODE,
    CONF_AUTO_BACKFILL,
    CONF_BEARER_TOKEN,
    CONF_EMAIL,
    CONF_ENCRYPTED_ACCOUNT_NUMBER,
    CONF_ENCRYPTED_PERSON_ID,
    CONF_ENCRYPTED_PREMISE_ID,
    CONF_ENCRYPTED_SA_ID,
    CONF_INCLUDE_COST,
    CONF_PASSWORD,
    CONF_REFRESH_CREDENTIAL,
    CONF_TOKEN_EXPIRES_AT,
    DEFAULT_AUTO_BACKFILL,
    DEFAULT_INCLUDE_COST,
    DOMAIN,
    PLATFORMS,
    SYNC_PHASE_HOURLY,
    SYNC_STATUS_BACKFILLING,
)
from .coordinator import PGECoordinator
from .day_validation import clip_hourly_to_local_day, is_invalid_closed_day, validate_hourly_day
from .options import (
    get_entry_option,
    history_incomplete,
    history_window_datetimes,
    pge_display_name,
    resolve_history_bounds,
)
from .panel import async_setup_panel, async_teardown_panel
from .statistics import async_import_with_baseline, setup_statistics_sensors
from .store import async_save_import_state
from .time_util import iter_local_days, today_local
from .websocket import async_setup_websocket

_LOGGER = logging.getLogger(__name__)

type PGEConfigEntry = ConfigEntry[PGECoordinator]

BACKFILL_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
        vol.Required("start_date"): str,
        vol.Required("end_date"): str,
    }
)

ENTRY_SCHEMA = vol.Schema(
    {
        vol.Required("entry_id"): cv.string,
    }
)


def _parse_expires_at(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


async def async_setup_entry(hass: HomeAssistant, entry: PGEConfigEntry) -> bool:
    token = entry.data.get(CONF_BEARER_TOKEN, "")
    encrypted_person_id = entry.data[CONF_ENCRYPTED_PERSON_ID]
    account_id = entry.data[CONF_ACCOUNT_ID]
    account_key = entry.data.get(CONF_ACCOUNT_KEY)
    auth_mode = entry.data.get(CONF_AUTH_MODE, AUTH_MODE_CREDENTIAL)

    auth_manager = PGEAuthManager(
        token=token,
        encrypted_person_id=encrypted_person_id,
        account_id=account_id,
        account_key=account_key,
        email=entry.data.get(CONF_EMAIL),
        password=entry.data.get(CONF_PASSWORD),
        refresh_credential=entry.data.get(CONF_REFRESH_CREDENTIAL),
        auth_mode=auth_mode,
        token_expires_at=_parse_expires_at(entry.data.get(CONF_TOKEN_EXPIRES_AT)),
        encrypted_account_number=entry.data.get(CONF_ENCRYPTED_ACCOUNT_NUMBER),
        encrypted_premise_id=entry.data.get(CONF_ENCRYPTED_PREMISE_ID),
        encrypted_sa_id=entry.data.get(CONF_ENCRYPTED_SA_ID),
    )

    # Persist immutable account_key on first run / migration.
    if CONF_ACCOUNT_KEY not in entry.data:
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_ACCOUNT_KEY: auth_manager.account_key},
        )

    desired_title = pge_display_name(account_id)
    if entry.title != desired_title:
        hass.config_entries.async_update_entry(entry, title=desired_title)

    session = aiohttp_client.async_get_clientsession(hass)
    client = PGEApiClient(session, auth_manager=auth_manager)

    coordinator = PGECoordinator(hass, entry, auth_manager, client)
    await coordinator.async_load_store()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    setup_statistics_sensors(hass, coordinator.account_key)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(identifiers={(DOMAIN, coordinator.account_key)})
    if device is not None and device.name_by_user is None and device.name != desired_title:
        device_registry.async_update_device(device.id, name=desired_title)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    if not hass.services.has_service(DOMAIN, "refresh"):
        _async_setup_services(hass)

    async_setup_websocket(hass)
    await async_setup_panel(hass)

    # Never await PGE network / recorder drains inside async_setup_entry —
    # that deadlocks HA bootstrap (entry waits on I/O; bootstrap waits on entry).
    async def _async_post_setup() -> None:
        try:
            await coordinator.async_config_entry_first_refresh()
        except ConfigEntryAuthFailed:
            _LOGGER.error("PGE authentication failed during initial refresh — update credentials")
            return
        except Exception as exc:
            _LOGGER.error("Failed initial PGE data refresh: %s", exc)
            # Continue to repair/backfill attempts only after a successful refresh.

        await coordinator.async_repair_dirty_if_needed()
        await coordinator.async_repair_monthly_collisions_if_needed()
        if (
            coordinator.import_store.target_start
            and coordinator.import_store.target_end
            and coordinator.try_reserve_backfill()
        ):
            task = hass.async_create_task(_async_resume_backfill(hass, entry.entry_id, coordinator))
            coordinator.set_backfill_task(task)
            return
        await _async_maybe_start_auto_backfill(hass, entry, coordinator)

    # Background task so bootstrap does not wait on PGE login / first refresh.
    hass.async_create_background_task(
        _async_post_setup(),
        name=f"{DOMAIN}_post_setup_{entry.entry_id[:8]}",
    )

    return True


async def _async_maybe_start_auto_backfill(
    hass: HomeAssistant,
    entry: PGEConfigEntry,
    coordinator: PGECoordinator,
) -> None:
    """Kick tiered history sync when auto_backfill is on and history is incomplete."""
    if not bool(get_entry_option(entry, CONF_AUTO_BACKFILL, DEFAULT_AUTO_BACKFILL)):
        return
    start_day, end_day = resolve_history_bounds(entry)
    if not history_incomplete(start_day, end_day, coordinator.import_store.completed_local_dates):
        return
    if not coordinator.try_reserve_backfill():
        return
    start, end = history_window_datetimes(start_day, end_day)
    _LOGGER.info(
        "Auto backfill starting for %s (%s .. %s)",
        coordinator.account_key[:8],
        start_day.isoformat(),
        end_day.isoformat(),
    )
    task = hass.async_create_task(_async_run_backfill(hass, entry.entry_id, coordinator, start, end))
    coordinator.set_backfill_task(task)


def _coordinator_for_entry(hass: HomeAssistant, entry_id: str) -> PGECoordinator | None:
    return hass.data.get(DOMAIN, {}).get(entry_id)


def async_device_progress_path(hass: HomeAssistant, account_key: str) -> str | None:
    """Return `/config/devices/device/<id>` for the PGE device, if registered."""
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(identifiers={(DOMAIN, account_key)})
    if device is None:
        return None
    return f"/config/devices/device/{device.id}"


async def async_notify_sync_started(
    hass: HomeAssistant,
    *,
    account_id: str,
    account_key: str,
    kind: str,
) -> str | None:
    """Create a persistent notification with a device deep link. Return the path."""
    path = async_device_progress_path(hass, account_key)
    link = f"[View progress]({path})" if path else "Open the PGE device to view progress."
    persistent_notification.async_create(
        hass,
        f"A {kind} job is running. {link}",
        title=f"PGE {account_id} sync started",
        notification_id=f"{DOMAIN}_sync_{account_key}",
    )
    return path


async def async_start_manual_refresh(hass: HomeAssistant, entry_id: str) -> str | None:
    """Start a tracked correction-window refresh. Return error reason or None."""
    coordinator = _coordinator_for_entry(hass, entry_id)
    if coordinator is None:
        return "unknown_entry"
    if coordinator.sync_job_in_progress:
        return "busy"
    await coordinator.async_start_refresh_job()
    await async_notify_sync_started(
        hass,
        account_id=coordinator.account_id,
        account_key=coordinator.account_key,
        kind="refresh",
    )
    return None


async def async_start_history_backfill(hass: HomeAssistant, entry_id: str) -> str | None:
    """Start tiered backfill using Sync settings history bounds. Return error or None."""
    coordinator = _coordinator_for_entry(hass, entry_id)
    if coordinator is None:
        return "unknown_entry"
    if coordinator.sync_job_in_progress:
        return "busy"
    if not coordinator.try_reserve_backfill():
        return "busy"

    entry = coordinator.entry
    start_day, end_day = resolve_history_bounds(entry)
    start, end = history_window_datetimes(start_day, end_day)
    incomplete = [
        d
        for d in iter_local_days(start, end)
        if d != today_local() and d.isoformat() not in coordinator.import_store.completed_local_dates
    ]
    coordinator.begin_sync_job(
        status=SYNC_STATUS_BACKFILLING,
        phase=SYNC_PHASE_HOURLY,
        total=len(incomplete),
        message=f"Hourly 0/{len(incomplete)}",
    )
    await coordinator.async_persist_sync_progress()
    task = hass.async_create_task(_async_run_backfill(hass, entry_id, coordinator, start, end))
    coordinator.set_backfill_task(task)
    await async_notify_sync_started(
        hass,
        account_id=coordinator.account_id,
        account_key=coordinator.account_key,
        kind="backfill",
    )
    return None


def _async_setup_services(hass: HomeAssistant) -> None:
    async def async_refresh(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")
        if entry_id:
            err = await async_start_manual_refresh(hass, entry_id)
            if err == "busy":
                _LOGGER.error("Refresh already in progress for %s", entry_id)
            elif err == "unknown_entry":
                _LOGGER.error("Unknown entry_id for refresh: %s", entry_id)
            return
        for eid, coordinator in list(hass.data.get(DOMAIN, {}).items()):
            if coordinator.sync_job_in_progress:
                continue
            await async_start_manual_refresh(hass, eid)

    async def async_backfill(call: ServiceCall) -> None:
        entry_id = call.data["entry_id"]
        coordinator = _coordinator_for_entry(hass, entry_id)
        if coordinator is None:
            _LOGGER.error("Unknown entry_id for backfill: %s", entry_id)
            return
        if coordinator.sync_job_in_progress or not coordinator.try_reserve_backfill():
            _LOGGER.error("Backfill already in progress for %s", entry_id)
            return

        start = datetime.fromisoformat(call.data["start_date"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(call.data["end_date"].replace("Z", "+00:00"))
        if start >= end:
            coordinator.release_backfill_reservation()
            _LOGGER.error("backfill: start_date must be before end_date")
            return

        incomplete = [
            d
            for d in iter_local_days(start, end)
            if d != today_local() and d.isoformat() not in coordinator.import_store.completed_local_dates
        ]
        coordinator.begin_sync_job(
            status=SYNC_STATUS_BACKFILLING,
            phase=SYNC_PHASE_HOURLY,
            total=len(incomplete),
            message=f"Hourly 0/{len(incomplete)}",
        )
        await coordinator.async_persist_sync_progress()
        task = hass.async_create_task(_async_run_backfill(hass, entry_id, coordinator, start, end))
        coordinator.set_backfill_task(task)
        await async_notify_sync_started(
            hass,
            account_id=coordinator.account_id,
            account_key=coordinator.account_key,
            kind="backfill",
        )

    async def async_retry_failed(call: ServiceCall) -> None:
        entry_id = call.data["entry_id"]
        coordinator = _coordinator_for_entry(hass, entry_id)
        if coordinator is None:
            return
        if coordinator.backfill_in_progress:
            _LOGGER.error("Cannot retry while backfill is running for %s", entry_id)
            return
        await _async_retry_failed_ranges(hass, coordinator)

    async def async_reset_checkpoint(call: ServiceCall) -> None:
        entry_id = call.data["entry_id"]
        coordinator = _coordinator_for_entry(hass, entry_id)
        if coordinator is None:
            return
        try:
            await coordinator.async_reset_checkpoint()
        except Exception as exc:
            _LOGGER.error("reset_import_checkpoint failed: %s", exc)
            return
        _LOGGER.info("Import checkpoint reset for %s", coordinator.account_key)

    hass.services.async_register(DOMAIN, "refresh", async_refresh)
    hass.services.async_register(DOMAIN, "backfill", async_backfill, BACKFILL_SCHEMA)
    hass.services.async_register(DOMAIN, "retry_failed_ranges", async_retry_failed, ENTRY_SCHEMA)
    hass.services.async_register(DOMAIN, "reset_import_checkpoint", async_reset_checkpoint, ENTRY_SCHEMA)


async def _async_resume_backfill(
    hass: HomeAssistant,
    entry_id: str,
    coordinator: PGECoordinator,
) -> None:
    store = coordinator.import_store
    if not store.target_start or not store.target_end:
        return
    start = datetime.fromisoformat(store.target_start)
    end = datetime.fromisoformat(store.target_end)
    await _async_run_backfill(hass, entry_id, coordinator, start, end)


async def _async_run_backfill(
    hass: HomeAssistant,
    entry_id: str,
    coordinator: PGECoordinator,
    start: datetime,
    end: datetime,
) -> None:
    coordinator.set_backfill_state(True, start, end)
    store = coordinator.import_store
    store.target_start = start.isoformat()
    store.target_end = end.isoformat()
    await async_save_import_state(hass, entry_id, store)

    try:
        await async_backfill_range(hass, entry_id, coordinator, start, end)
        # Finish the billing ledger + programs alongside history backfill.
        await async_run_billing_sync(hass, coordinator)
    except Exception as exc:
        _LOGGER.error("Backfill job failed for %s: %s", entry_id[:8], exc)
        coordinator.fail_sync_job(str(exc))
        await coordinator.async_persist_sync_progress()
    finally:
        coordinator.set_backfill_state(False)
        coordinator.set_backfill_task(None)


async def _async_retry_failed_ranges(
    hass: HomeAssistant,
    coordinator: PGECoordinator,
) -> None:
    store = coordinator.import_store
    failed = list(store.failed_local_dates)
    if not failed:
        _LOGGER.info("No failed ranges to retry")
        return

    include_cost = bool(get_entry_option(coordinator.entry, CONF_INCLUDE_COST, DEFAULT_INCLUDE_COST))
    for iso in failed:
        day = date.fromisoformat(iso)
        try:
            _, intervals = await async_fetch_hourly_day(coordinator, day)
            clipped = clip_hourly_to_local_day(day, intervals or [])
            ok_complete, reason = validate_hourly_day(day, clipped, clip_boundary=False)
            if is_invalid_closed_day(ok_complete, reason):
                _LOGGER.warning("Retry day %s still invalid (%s)", iso, reason)
                continue
            if clipped:
                store.dirty_from = min(iv.start for iv in clipped).isoformat()
                await async_save_import_state(hass, coordinator.entry.entry_id, store)
                async with coordinator.import_lock:
                    await async_import_with_baseline(
                        hass,
                        coordinator.account_key,
                        clipped,
                        include_cost=include_cost,
                        account_id=coordinator.account_id,
                    )
                store.dirty_from = None
            if ok_complete:
                if iso in store.failed_local_dates:
                    store.failed_local_dates.remove(iso)
                if iso not in store.completed_local_dates:
                    store.completed_local_dates.append(iso)
            await async_save_import_state(hass, coordinator.entry.entry_id, store)
        except Exception as exc:
            _LOGGER.warning("Retry failed for %s: %s", iso, exc)


async def async_unload_entry(hass: HomeAssistant, entry: PGEConfigEntry) -> bool:
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is not None:
        await coordinator.async_cancel_backfill()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        remaining = [key for key, value in hass.data.get(DOMAIN, {}).items() if isinstance(value, PGECoordinator)]
        if not remaining:
            hass.data.pop(DOMAIN, None)
            async_teardown_panel(hass)
            if hass.services.has_service(DOMAIN, "refresh"):
                hass.services.async_remove(DOMAIN, "refresh")
                hass.services.async_remove(DOMAIN, "backfill")
                hass.services.async_remove(DOMAIN, "retry_failed_ranges")
                hass.services.async_remove(DOMAIN, "reset_import_checkpoint")
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: PGEConfigEntry) -> None:
    """Reload on options/settings changes — not on routine token persistence."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is not None and coordinator.consume_skip_reload():
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entry to add immutable account_key."""
    if entry.version > 2:
        return False

    data = dict(entry.data)
    if CONF_ACCOUNT_KEY not in data:
        auth = PGEAuthManager(
            token=data.get(CONF_BEARER_TOKEN, ""),
            encrypted_person_id=data[CONF_ENCRYPTED_PERSON_ID],
            account_id=data[CONF_ACCOUNT_ID],
        )
        data[CONF_ACCOUNT_KEY] = auth.account_key

    hass.config_entries.async_update_entry(entry, data=data, version=2)
    return True
