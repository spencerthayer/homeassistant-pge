"""Orchestrate the billing / programs sync (soft-fail alongside usage).

Runs after a successful usage import on every poll and during Manual sync. It
never re-raises: any failure is recorded as ``billing_last_error`` so a billing
hiccup can never fail the usage poll.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client

from .bill_pdf_sync import async_sync_bill_pdfs, index_bill_from_ledger_event, index_bill_from_snapshot
from .billing_api import PGEBillingApiClient
from .billing_models import BillingFreshness, EnergyTrackerEstimates, LedgerEvent, TodSnapshot
from .billing_statistics import (
    async_import_billing_snapshot,
    async_import_ledger_events,
    async_import_programs_metrics,
    async_refresh_billing_lifetime_totals,
)
from .const import (
    CONF_INCLUDE_BILLING,
    DEFAULT_INCLUDE_BILLING,
    SYNC_PHASE_BILLING_HISTORY,
    SYNC_PHASE_BILLING_SNAPSHOT,
    SYNC_PHASE_PROGRAMS,
)
from .exceptions import (
    PGEAuthorizationError,
    PGEConnectionError,
    PGEGraphQLError,
    PGERateLimitError,
    PGESchemaError,
)
from .options import get_entry_option
from .store import async_save_import_state

if TYPE_CHECKING:
    from .coordinator import PGECoordinator

_LOGGER = logging.getLogger(__name__)


def _set_phase(coordinator: PGECoordinator, phase: str, message: str) -> None:
    """Update the live sync snapshot phase/message when a job is tracked."""
    if not coordinator.sync_job_in_progress:
        return
    coordinator.update_sync_progress(phase=phase, message=message)


async def async_run_billing_sync(
    hass: HomeAssistant,
    coordinator: PGECoordinator,
    *,
    page_limit: int = 15,
    max_pages: int = 50,
) -> None:
    """Fetch account snapshot, ledger history, and programs; dual-publish stats."""
    entry = coordinator.entry
    if not bool(get_entry_option(entry, CONF_INCLUDE_BILLING, DEFAULT_INCLUDE_BILLING)):
        return

    account_key = coordinator.account_key
    account_id = coordinator.account_id
    auth = coordinator.auth_manager
    store = coordinator.import_store

    try:
        await auth.ensure_valid_token()
        session = aiohttp_client.async_get_clientsession(hass)
        client = PGEBillingApiClient(session, auth)

        # 1) Account snapshot + encrypted identity persistence -------------
        _set_phase(coordinator, SYNC_PHASE_BILLING_SNAPSHOT, "Billing snapshot")
        snapshot = await client.get_account_detail(account_id)
        auth.update_identity(
            encrypted_person_id=snapshot.encrypted_person_id,
            encrypted_account_number=snapshot.encrypted_account_number,
            encrypted_premise_id=snapshot.encrypted_premise_id,
            encrypted_sa_id=snapshot.encrypted_sa_id,
        )
        coordinator.persist_auth_to_entry()
        coordinator.account_snapshot = snapshot
        index_bill_from_snapshot(store, snapshot)

        now = datetime.now(UTC)
        await async_import_billing_snapshot(hass, account_key, account_id, snapshot, now)

        # 2) Paged payment / bill ledger ----------------------------------
        encrypted_account_number = auth.encrypted_account_number
        encrypted_person_id = auth.encrypted_person_id
        if encrypted_account_number and encrypted_person_id:
            await _async_page_ledger(
                hass,
                coordinator,
                client,
                account_number=account_id,
                encrypted_account_number=encrypted_account_number,
                encrypted_person_id=encrypted_person_id,
                page_limit=page_limit,
                max_pages=max_pages,
            )
        else:
            _LOGGER.debug("Skipping ledger paging — encrypted account/person id missing")

        # 3) Open-cycle estimates (portal Current Use) ---------------------
        if encrypted_account_number and encrypted_person_id:
            coordinator.tracker_estimates = await _async_fetch_tracker_estimates(
                client,
                encrypted_account_number=encrypted_account_number,
                encrypted_person_id=encrypted_person_id,
                previous=coordinator.tracker_estimates,
            )
        else:
            _LOGGER.debug("Skipping open-cycle estimates — encrypted account/person id missing")

        # 4) Programs ------------------------------------------------------
        encrypted_premise_id = auth.encrypted_premise_id
        encrypted_sa_id = auth.encrypted_sa_id
        if encrypted_account_number and encrypted_premise_id and encrypted_sa_id:
            _set_phase(coordinator, SYNC_PHASE_PROGRAMS, "Programs")
            programs = await client.get_programs(
                encrypted_account_number,
                encrypted_premise_id,
                encrypted_sa_id,
            )
            coordinator.programs_snapshot = programs
            await async_import_programs_metrics(hass, account_key, account_id, programs, datetime.now(UTC))
        else:
            _LOGGER.debug("Skipping programs — encrypted premise/SA id missing")

        # 5) Time of Day pricing snapshot (soft-fail; keeps last good) -------
        if encrypted_account_number and encrypted_sa_id:
            tod_snapshot = await _async_fetch_tod_snapshot(
                client,
                encrypted_account_number=encrypted_account_number,
                encrypted_premise_id=encrypted_premise_id or "",
                encrypted_sa_id=encrypted_sa_id,
                previous=coordinator.tod_snapshot,
            )
            if tod_snapshot is not None:
                await coordinator.async_set_tod_snapshot(tod_snapshot)
        else:
            _LOGGER.debug("Skipping TOD pricing — encrypted account/SA id missing")

        # 6) Lifetime totals + freshness ----------------------------------
        payments, billed = await async_refresh_billing_lifetime_totals(hass, account_key)
        coordinator.lifetime_payments_usd = payments
        coordinator.lifetime_billed_usd = billed

        # 7) Optional bill PDF download / parse / statistics ---------------
        await async_sync_bill_pdfs(hass, coordinator)

        success = datetime.now(UTC)
        coordinator.billing_freshness = BillingFreshness(last_success=success, last_error=None)
        store.billing_last_success = success.isoformat()
        store.billing_last_error = None
        await async_save_import_state(hass, entry.entry_id, store)
    except Exception as exc:  # noqa: BLE001 - billing is soft-fail by design
        message = str(exc)
        _LOGGER.warning("Billing sync soft-failed for %s: %s", account_key[:8], message)
        store.billing_last_error = message
        coordinator.billing_freshness = BillingFreshness(
            last_success=coordinator.billing_freshness.last_success,
            last_error=message,
        )
        try:
            await async_save_import_state(hass, entry.entry_id, store)
        except Exception:  # pragma: no cover - store failure is non-fatal
            _LOGGER.debug("Failed to persist billing_last_error", exc_info=True)


async def _async_fetch_tracker_estimates(
    client: PGEBillingApiClient,
    *,
    encrypted_account_number: str,
    encrypted_person_id: str,
    previous: EnergyTrackerEstimates | None,
) -> EnergyTrackerEstimates | None:
    """Fetch Current Use estimates, keeping the last good value on failure.

    These estimates are cosmetic next to usage/ledger data, so a failure here
    must not abort the rest of the billing sync.
    """
    try:
        return await client.get_energy_tracker_estimates(
            encrypted_account_number,
            encrypted_person_id,
        )
    except (
        PGEGraphQLError,
        PGESchemaError,
        PGEConnectionError,
        PGERateLimitError,
        PGEAuthorizationError,
    ) as exc:
        _LOGGER.debug("Open-cycle estimates unavailable: %s", exc)
        return previous


async def _async_fetch_tod_snapshot(
    client: PGEBillingApiClient,
    *,
    encrypted_account_number: str,
    encrypted_premise_id: str,
    encrypted_sa_id: str,
    previous: TodSnapshot | None,
) -> TodSnapshot | None:
    """Best-effort portal TOD rates; keep the last-good snapshot on failure.

    The op is speculative (discovery), so any failure here must never abort the
    rest of billing sync nor blank already-cached rates.
    """
    try:
        fetched = await client.get_tod_pricing(
            encrypted_account_number,
            encrypted_premise_id,
            encrypted_sa_id,
        )
    except (
        PGEGraphQLError,
        PGESchemaError,
        PGEConnectionError,
        PGERateLimitError,
        PGEAuthorizationError,
    ) as exc:
        _LOGGER.debug("TOD pricing unavailable: %s", exc)
        return previous
    except Exception as exc:  # noqa: BLE001 - speculative op must never abort billing sync
        _LOGGER.debug("TOD pricing fetch failed unexpectedly: %s", exc)
        return previous
    if not fetched.rates and fetched.basic_rate is None and fetched.savings_total is None:
        return previous
    return fetched


async def _async_page_ledger(
    hass: HomeAssistant,
    coordinator: PGECoordinator,
    client: PGEBillingApiClient,
    *,
    account_number: str,
    encrypted_account_number: str,
    encrypted_person_id: str,
    page_limit: int,
    max_pages: int,
) -> None:
    """Walk the ledger feed, checkpointing progress, then import once.

    Events are accumulated across pages before ``async_import_ledger_events`` so
    same-hour payments that land on different pages combine instead of
    overwriting each other. After ``billing_history_complete``, only the newest
    page is re-read (old bill/payment corrections are not re-fetched — ledger
    rows are treated as immutable; reset the import Store to re-page history).
    """
    store = coordinator.import_store
    entry = coordinator.entry
    account_key = coordinator.account_key
    account_id = coordinator.account_id

    already_complete = store.billing_history_complete
    offset = 0 if already_complete else max(0, store.billing_history_offset)
    pages_walked = 0
    collected: list[LedgerEvent] = []

    while pages_walked < max_pages:
        events, total = await client.get_payment_history_page(
            encrypted_account_number,
            encrypted_person_id,
            account_number=account_number,
            limit=page_limit,
            offset=offset,
        )
        store.billing_history_total = total
        _set_phase(
            coordinator,
            SYNC_PHASE_BILLING_HISTORY,
            f"Billing history {min(offset + page_limit, total)}/{total}",
        )
        if events:
            collected.extend(events)
            for event in events:
                index_bill_from_ledger_event(store, event)

        pages_walked += 1
        offset += page_limit
        reached_end = (not events) or offset >= total

        if not already_complete:
            store.billing_history_offset = min(offset, total)
            store.billing_history_complete = reached_end
            await async_save_import_state(hass, entry.entry_id, store)

        if reached_end or already_complete:
            break

    if collected:
        await async_import_ledger_events(hass, account_key, account_id, collected)
