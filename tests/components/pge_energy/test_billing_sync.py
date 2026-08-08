"""Unit tests for billing_sync orchestration (soft-fail + checkpoint)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.pge_energy.billing_models import (
    AccountSnapshot,
    BillingFreshness,
    EnergyTrackerEstimates,
    LedgerEvent,
    LedgerEventType,
    ProgramsSnapshot,
    TodSnapshot,
)
from custom_components.pge_energy.billing_sync import async_run_billing_sync
from custom_components.pge_energy.const import CONF_INCLUDE_BILLING
from custom_components.pge_energy.exceptions import PGEGraphQLError
from custom_components.pge_energy.store import ImportStoreData


def _coordinator(*, include_billing: bool = True) -> MagicMock:
    coord = MagicMock()
    entry = MagicMock()
    entry.entry_id = "entry1"
    entry.options = {CONF_INCLUDE_BILLING: include_billing}
    entry.data = {}
    coord.entry = entry
    coord.account_key = "keykeykeykeykeyk"
    coord.account_id = "0000000000"
    auth = MagicMock()
    auth.ensure_valid_token = AsyncMock(return_value="tok")
    auth.encrypted_account_number = "enc-a"
    auth.encrypted_person_id = "enc-p"
    auth.encrypted_premise_id = "enc-prem"
    auth.encrypted_sa_id = "enc-sa"
    auth.update_identity = MagicMock()
    coord.auth_manager = auth
    coord.import_store = ImportStoreData(account_key="keykeykeykeykeyk")
    coord.persist_auth_to_entry = MagicMock()
    coord.sync_job_in_progress = False
    coord.update_sync_progress = MagicMock()
    coord.billing_freshness = BillingFreshness()
    coord.account_snapshot = None
    coord.programs_snapshot = None
    coord.tracker_estimates = None
    coord.tod_snapshot = None
    coord.async_set_tod_snapshot = AsyncMock()
    coord.lifetime_payments_usd = None
    coord.lifetime_billed_usd = None
    return coord


@pytest.mark.asyncio
async def test_include_billing_false_skips():
    coord = _coordinator(include_billing=False)
    hass = MagicMock()
    with patch("custom_components.pge_energy.billing_sync.PGEBillingApiClient") as client_cls:
        await async_run_billing_sync(hass, coord)
        client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_happy_path_persists_ids_and_checkpoints():
    coord = _coordinator()
    hass = MagicMock()
    snap = AccountSnapshot(
        account_number="0000000000",
        amount_due=300.13,
        encrypted_account_number="enc-a",
        encrypted_person_id="enc-p",
        encrypted_premise_id="enc-prem",
        encrypted_sa_id="enc-sa",
    )
    events = [
        LedgerEvent(
            event_type=LedgerEventType.BILL,
            date=datetime(2026, 7, 13, 7, tzinfo=UTC),
            amount_due=300.13,
        )
    ]
    programs = ProgramsSnapshot(
        peak_time_rebates_enrolled=True,
        green_future_enrolled=True,
        ytd_flex_load_earnings=3.7,
    )
    estimates = EnergyTrackerEstimates(
        details_available=True,
        billing_cycle_day=17,
        billing_cycle_total_days=30,
        bill_to_date_amount=124.0,
        projected_min_amount=186.3,
        projected_max_amount=227.7,
    )
    tod = TodSnapshot(
        rates={"off_peak": 0.0893, "mid_peak": 0.1670, "on_peak": 0.4313},
        basic_rate=0.10,
        fetched_at=datetime(2026, 7, 13, 7, tzinfo=UTC),
    )
    client = MagicMock()
    client.get_account_detail = AsyncMock(return_value=snap)
    client.get_payment_history_page = AsyncMock(return_value=(events, 1))
    client.get_programs = AsyncMock(return_value=programs)
    client.get_energy_tracker_estimates = AsyncMock(return_value=estimates)
    client.get_tod_pricing = AsyncMock(return_value=tod)

    with (
        patch(
            "custom_components.pge_energy.billing_sync.aiohttp_client.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.pge_energy.billing_sync.PGEBillingApiClient",
            return_value=client,
        ),
        patch(
            "custom_components.pge_energy.billing_sync.async_import_billing_snapshot",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.billing_sync.async_import_ledger_events",
            new=AsyncMock(),
        ) as import_ledger,
        patch(
            "custom_components.pge_energy.billing_sync.async_import_programs_metrics",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.billing_sync.async_refresh_billing_lifetime_totals",
            new=AsyncMock(return_value=(100.0, 200.0)),
        ),
        patch(
            "custom_components.pge_energy.billing_sync.async_save_import_state",
            new=AsyncMock(),
        ),
    ):
        await async_run_billing_sync(hass, coord)

    coord.auth_manager.update_identity.assert_called()
    coord.persist_auth_to_entry.assert_called()
    assert coord.account_snapshot is snap
    assert coord.programs_snapshot is programs
    assert coord.tracker_estimates is estimates
    assert coord.lifetime_payments_usd == 100.0
    assert coord.import_store.billing_history_complete is True
    assert coord.billing_freshness.last_error is None
    assert coord.billing_freshness.last_success is not None
    client.get_tod_pricing.assert_awaited_once()
    coord.async_set_tod_snapshot.assert_awaited_once_with(tod)
    client.get_payment_history_page.assert_awaited()
    assert client.get_payment_history_page.await_args.kwargs["account_number"] == "0000000000"
    import_ledger.assert_awaited_once()
    assert import_ledger.await_args.args[3] == events


@pytest.mark.asyncio
async def test_tracker_failure_keeps_previous_and_continues():
    coord = _coordinator()
    hass = MagicMock()
    previous = EnergyTrackerEstimates(details_available=True, billing_cycle_day=16)
    coord.tracker_estimates = previous
    previous_tod = TodSnapshot(
        rates={"off_peak": 0.09, "mid_peak": 0.16, "on_peak": 0.42},
        basic_rate=0.10,
    )
    coord.tod_snapshot = previous_tod
    snap = AccountSnapshot(
        account_number="0000000000",
        encrypted_account_number="enc-a",
        encrypted_person_id="enc-p",
        encrypted_premise_id="enc-prem",
        encrypted_sa_id="enc-sa",
    )
    client = MagicMock()
    client.get_account_detail = AsyncMock(return_value=snap)
    client.get_payment_history_page = AsyncMock(return_value=([], 0))
    client.get_programs = AsyncMock(return_value=ProgramsSnapshot())
    client.get_energy_tracker_estimates = AsyncMock(side_effect=PGEGraphQLError("nope"))
    client.get_tod_pricing = AsyncMock(side_effect=PGEGraphQLError("nope"))

    with (
        patch(
            "custom_components.pge_energy.billing_sync.aiohttp_client.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.pge_energy.billing_sync.PGEBillingApiClient",
            return_value=client,
        ),
        patch(
            "custom_components.pge_energy.billing_sync.async_import_billing_snapshot",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.billing_sync.async_import_programs_metrics",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.billing_sync.async_refresh_billing_lifetime_totals",
            new=AsyncMock(return_value=(1.0, 2.0)),
        ),
        patch(
            "custom_components.pge_energy.billing_sync.async_save_import_state",
            new=AsyncMock(),
        ),
    ):
        await async_run_billing_sync(hass, coord)

    assert coord.tracker_estimates is previous
    assert coord.billing_freshness.last_error is None
    client.get_programs.assert_awaited()
    client.get_tod_pricing.assert_awaited_once()
    coord.async_set_tod_snapshot.assert_awaited_once_with(previous_tod)


@pytest.mark.asyncio
async def test_empty_tod_snapshot_keeps_previous():
    coord = _coordinator()
    hass = MagicMock()
    previous_tod = TodSnapshot(rates={"off_peak": 0.09}, basic_rate=0.10)
    coord.tod_snapshot = previous_tod
    snap = AccountSnapshot(
        account_number="0000000000",
        encrypted_account_number="enc-a",
        encrypted_person_id="enc-p",
        encrypted_premise_id="enc-prem",
        encrypted_sa_id="enc-sa",
    )
    client = MagicMock()
    client.get_account_detail = AsyncMock(return_value=snap)
    client.get_payment_history_page = AsyncMock(return_value=([], 0))
    client.get_programs = AsyncMock(return_value=ProgramsSnapshot())
    client.get_energy_tracker_estimates = AsyncMock(return_value=EnergyTrackerEstimates())
    client.get_tod_pricing = AsyncMock(return_value=TodSnapshot())

    with (
        patch(
            "custom_components.pge_energy.billing_sync.aiohttp_client.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.pge_energy.billing_sync.PGEBillingApiClient",
            return_value=client,
        ),
        patch(
            "custom_components.pge_energy.billing_sync.async_import_billing_snapshot",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.billing_sync.async_import_programs_metrics",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.billing_sync.async_refresh_billing_lifetime_totals",
            new=AsyncMock(return_value=(1.0, 2.0)),
        ),
        patch(
            "custom_components.pge_energy.billing_sync.async_save_import_state",
            new=AsyncMock(),
        ),
    ):
        await async_run_billing_sync(hass, coord)

    client.get_tod_pricing.assert_awaited_once()
    coord.async_set_tod_snapshot.assert_awaited_once_with(previous_tod)


@pytest.mark.asyncio
async def test_soft_fail_does_not_raise():
    coord = _coordinator()
    hass = MagicMock()
    with (
        patch(
            "custom_components.pge_energy.billing_sync.aiohttp_client.async_get_clientsession",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.pge_energy.billing_sync.PGEBillingApiClient",
            side_effect=RuntimeError("boom"),
        ),
        patch(
            "custom_components.pge_energy.billing_sync.async_save_import_state",
            new=AsyncMock(),
        ),
    ):
        await async_run_billing_sync(hass, coord)
    assert coord.billing_freshness.last_error == "boom"
    assert coord.import_store.billing_last_error == "boom"
