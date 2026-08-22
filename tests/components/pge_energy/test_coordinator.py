from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.pge_energy.coordinator import PGECoordinator
from custom_components.pge_energy.exceptions import (
    PGEAuthenticationError,
    PGEConnectionError,
    PGESchemaError,
)
from custom_components.pge_energy.models import UsageInterval, UsageResolution, UsageResponse
from custom_components.pge_energy.statistics import ImportBaselineResult
from custom_components.pge_energy.store import ImportStoreData
from custom_components.pge_energy.time_util import local_day_bounds, today_local


def _full_day_intervals(day: date, account_key: str = "key") -> list[UsageInterval]:
    day_start, day_end = local_day_bounds(day)
    intervals: list[UsageInterval] = []
    cursor = day_start
    while cursor < day_end:
        intervals.append(
            UsageInterval(
                account_key=account_key,
                resolution=UsageResolution.HOURLY,
                start=cursor,
                end=cursor + timedelta(hours=1),
                kwh=Decimal("1.0"),
                amount=Decimal("0.1"),
                temperature=None,
                usage_status=None,
                interval_size=None,
                source_timestamp=None,
            )
        )
        cursor += timedelta(hours=1)
    return intervals


def _make_coordinator(*, auth_mode: str = "credential") -> PGECoordinator:
    hass = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()
    entry = MagicMock()
    entry.entry_id = "entry1"
    entry.data = {
        "account_id": "acct",
        "account_key": "keykeykeykeykeyk",
        "correction_window": 2,
    }
    auth = MagicMock()
    auth.account_key = "keykeykeykeykeyk"
    auth.auth_mode = auth_mode
    auth.ensure_valid_token = AsyncMock(return_value="tok")
    auth.force_renew = AsyncMock(return_value="tok2")
    auth.persistable_auth_data = MagicMock(return_value={"bearer_token": "tok"})
    auth.cognito_rate_limit_remaining_seconds = MagicMock(return_value=0.0)
    client = MagicMock()
    coord = PGECoordinator(hass, entry, auth, client)
    coord._import_store = ImportStoreData(account_key="keykeykeykeykeyk")
    return coord


@pytest.mark.asyncio
async def test_correction_window_refetches_completed_days():
    coord = _make_coordinator()
    completed = (today_local() - timedelta(days=1)).isoformat()
    coord._import_store.completed_local_dates = [completed]

    async def fake_usage(start, end, resolution=UsageResolution.HOURLY):
        day = start.astimezone(local_day_bounds(today_local())[0].tzinfo).date()
        return UsageResponse(
            resolution=UsageResolution.HOURLY,
            intervals=_full_day_intervals(day) if day != today_local() else [],
            total_kwh=None,
            total_cost=None,
            is_tod=None,
            acct_type=None,
        )

    coord.async_get_usage_with_auth_retry = AsyncMock(side_effect=fake_usage)

    with (
        patch(
            "custom_components.pge_energy.coordinator.async_import_with_baseline",
            AsyncMock(return_value=ImportBaselineResult(1)),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_save_import_state",
            AsyncMock(),
        ),
    ):
        data = await coord._async_update_data()

    # Window is 2 days → at least yesterday + today (+ maybe day before)
    assert coord.async_get_usage_with_auth_retry.await_count >= 2
    # Completed yesterday must still be requested
    requested_starts = [call.args[0] for call in coord.async_get_usage_with_auth_retry.await_args_list]
    assert any(
        s.astimezone(local_day_bounds(today_local())[0].tzinfo).date().isoformat() == completed
        for s in requested_starts
    )
    assert "intervals" in data


@pytest.mark.asyncio
async def test_401_renew_retry_once():
    coord = _make_coordinator(auth_mode="credential")
    coord.client.get_usage = AsyncMock(
        side_effect=[
            PGEAuthenticationError("401"),
            UsageResponse(
                resolution=UsageResolution.HOURLY,
                intervals=[],
                total_kwh=None,
                total_cost=None,
                is_tod=None,
                acct_type=None,
            ),
        ]
    )
    resp = await coord.async_get_usage_with_auth_retry(
        datetime.now(UTC) - timedelta(hours=1),
        datetime.now(UTC),
    )
    assert resp.intervals == []
    coord.auth_manager.force_renew.assert_awaited_once()


@pytest.mark.asyncio
async def test_all_days_failed_raises_update_failed_without_retained_state():
    coord = _make_coordinator()
    coord.async_get_usage_with_auth_retry = AsyncMock(side_effect=PGESchemaError("bad"))
    with (
        patch(
            "custom_components.pge_energy.coordinator.async_save_import_state",
            AsyncMock(),
        ),
        pytest.raises(UpdateFailed),
    ):
        await coord._async_update_data()
    assert coord._last_successful_update is None


@pytest.mark.asyncio
async def test_all_days_failed_keeps_recent_intervals():
    """A failed correction poll must not wipe tip intervals already downloaded."""
    coord = _make_coordinator()
    yesterday = today_local() - timedelta(days=1)
    prior = _full_day_intervals(yesterday)
    coord._recent_intervals = list(prior)
    coord.data = {"intervals": list(prior), "failed_days": []}
    coord.async_get_usage_with_auth_retry = AsyncMock(side_effect=PGESchemaError("bad"))
    with patch(
        "custom_components.pge_energy.coordinator.async_save_import_state",
        AsyncMock(),
    ):
        data = await coord._async_update_data()
    assert data["stale"] is True
    assert coord.recent_intervals == prior
    assert coord._last_api_error


@pytest.mark.asyncio
async def test_partial_correction_merges_tip_intervals():
    """Successful older days must not drop retained tip hours for a failed newer day."""
    coord = _make_coordinator()
    entry = coord.entry
    entry.data = {**entry.data, "correction_window": 2}
    older = today_local() - timedelta(days=2)
    newer = today_local() - timedelta(days=1)
    older_iv = _full_day_intervals(older)
    newer_iv = _full_day_intervals(newer)
    # Retained tip is the newer day (what sensors currently show).
    coord._recent_intervals = list(newer_iv)
    coord._import_store.completed_local_dates = [older.isoformat(), newer.isoformat()]
    coord.data = {"intervals": list(newer_iv), "failed_days": []}

    async def fake_usage(start, end, resolution=UsageResolution.HOURLY):
        day = start.astimezone(local_day_bounds(today_local())[0].tzinfo).date()
        if day == newer:
            raise PGESchemaError("newer day boom")
        return UsageResponse(
            resolution=UsageResolution.HOURLY,
            intervals=_full_day_intervals(day) if day != today_local() else [],
            total_kwh=None,
            total_cost=None,
            is_tod=None,
            acct_type=None,
        )

    coord.async_get_usage_with_auth_retry = AsyncMock(side_effect=fake_usage)
    with (
        patch(
            "custom_components.pge_energy.coordinator.async_import_with_baseline",
            AsyncMock(return_value=ImportBaselineResult(imported=24, cost_failed_days=())),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_save_import_state",
            AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_run_billing_sync",
            AsyncMock(),
        ),
        patch.object(coord, "async_refresh_lifetime_totals", AsyncMock()),
    ):
        await coord._async_update_data()

    tip_starts = {iv.start for iv in coord.recent_intervals}
    assert any(iv.start in tip_starts for iv in newer_iv)
    assert any(iv.start in tip_starts for iv in older_iv)
    assert max(iv.end for iv in coord.recent_intervals) == max(iv.end for iv in newer_iv)


@pytest.mark.asyncio
async def test_auth_fail_keeps_retained_data_and_requests_reauth():
    coord = _make_coordinator(auth_mode="credential")
    yesterday = today_local() - timedelta(days=1)
    prior = _full_day_intervals(yesterday)
    coord._recent_intervals = list(prior)
    coord._lifetime_energy_kwh = 123.0
    coord.data = {"intervals": list(prior), "failed_days": []}
    coord.auth_manager.ensure_valid_token = AsyncMock(side_effect=PGEAuthenticationError("bad pw"))
    coord.hass.async_create_task = MagicMock()
    coord.hass.config_entries.flow.async_init = AsyncMock()

    data = await coord._async_update_data()
    assert data["stale"] is True
    assert coord.recent_intervals == prior
    assert coord.lifetime_energy_kwh == 123.0
    assert coord._reauth_requested is True
    coord.hass.async_create_task.assert_called_once()


@pytest.mark.asyncio
async def test_auth_fail_without_retained_state_raises():
    from homeassistant.exceptions import ConfigEntryAuthFailed

    empty = _make_coordinator(auth_mode="credential")
    empty.auth_manager.ensure_valid_token = AsyncMock(side_effect=PGEAuthenticationError("bad pw"))
    empty.hass.async_create_task = MagicMock()
    empty.hass.config_entries.flow.async_init = AsyncMock()
    with pytest.raises(ConfigEntryAuthFailed):
        await empty._async_update_data()


@pytest.mark.asyncio
async def test_auth_connection_error_keeps_retained_data():
    coord = _make_coordinator(auth_mode="credential")
    yesterday = today_local() - timedelta(days=1)
    prior = _full_day_intervals(yesterday)
    coord._recent_intervals = list(prior)
    coord._lifetime_energy_kwh = 99.0
    coord.data = {"intervals": list(prior), "failed_days": []}
    coord.auth_manager.ensure_valid_token = AsyncMock(side_effect=PGEConnectionError("DNS timeout contacting Apigee"))

    data = await coord._async_update_data()
    assert data["stale"] is True
    assert coord.recent_intervals == prior
    assert coord.lifetime_energy_kwh == 99.0
    assert "DNS timeout" in (coord._last_api_error or "")


@pytest.mark.asyncio
async def test_cold_boot_connection_error_restores_sensor_snapshots():
    """Store tip/billing snapshots must keep sensors warm after a failed first poll."""
    from custom_components.pge_energy.billing_models import AccountSnapshot, BillDetails
    from custom_components.pge_energy.models import tip_intervals_to_store

    yesterday = today_local() - timedelta(days=1)
    prior = _full_day_intervals(yesterday)
    bill = BillDetails(
        amount_due=194.07,
        kwh=864.0,
        period_start=datetime(2026, 7, 6, tzinfo=UTC),
        period_end=datetime(2026, 8, 5, tzinfo=UTC),
    )
    account = AccountSnapshot(
        account_number="0000000000",
        amount_due=194.07,
        due_date=datetime(2026, 8, 31, tzinfo=UTC),
        last_payment_amount=300.13,
        last_payment_date=datetime(2026, 7, 30, tzinfo=UTC),
        bill=bill,
    )
    store = ImportStoreData(
        account_key="keykeykeykeykeyk",
        completed_local_dates=[yesterday.isoformat()],
        tip_intervals=tip_intervals_to_store(prior),
        account_snapshot=account.to_dict(),
        last_successful_update=datetime(2026, 8, 10, 8, 0, tzinfo=UTC).isoformat(),
        newest_interval=prior[-1].end.isoformat(),
        billing_last_success=datetime(2026, 8, 10, 8, 0, tzinfo=UTC).isoformat(),
    )
    coord = _make_coordinator(auth_mode="credential")
    # Cold boot: memory empty; only Store has tip/billing.
    coord.data = None
    coord._recent_intervals = []
    coord.account_snapshot = None
    coord._lifetime_energy_kwh = None
    with (
        patch(
            "custom_components.pge_energy.coordinator.async_load_import_state",
            AsyncMock(return_value=store),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_refresh_lifetime_totals",
            AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_refresh_billing_lifetime_totals",
            AsyncMock(return_value=(100.0, 200.0)),
        ),
    ):
        await coord.async_load_store()

    assert len(coord.recent_intervals) == 24
    assert coord.account_snapshot is not None
    assert coord.account_snapshot.amount_due == 194.07
    assert coord.lifetime_payments_usd == 100.0
    assert coord.lifetime_billed_usd == 200.0
    assert coord.data is not None

    coord.auth_manager.ensure_valid_token = AsyncMock(side_effect=PGEConnectionError("DNS timeout contacting Apigee"))
    data = await coord._async_update_data()
    assert data["stale"] is True
    assert len(coord.recent_intervals) == 24
    assert coord.account_snapshot.amount_due == 194.07
    assert "DNS timeout" in (coord._last_api_error or "")


@pytest.mark.asyncio
async def test_import_soft_fail_persists_tip_intervals():
    """Recorder import failure must still leave tip intervals on the Store."""
    coord = _make_coordinator()
    saved_tip_lengths: list[int] = []

    async def fake_usage(start, end, resolution=UsageResolution.HOURLY):
        day = start.astimezone(local_day_bounds(today_local())[0].tzinfo).date()
        return UsageResponse(
            resolution=UsageResolution.HOURLY,
            intervals=_full_day_intervals(day) if day != today_local() else [],
            total_kwh=None,
            total_cost=None,
            is_tod=None,
            acct_type=None,
        )

    async def capture_save(hass, entry_id, store, critical=False):
        saved_tip_lengths.append(len(store.tip_intervals or []))

    coord.async_get_usage_with_auth_retry = AsyncMock(side_effect=fake_usage)
    with (
        patch(
            "custom_components.pge_energy.coordinator.async_import_with_baseline",
            AsyncMock(side_effect=RuntimeError("recorder import failed")),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_save_import_state",
            AsyncMock(side_effect=capture_save),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_run_billing_sync",
            AsyncMock(),
        ),
    ):
        data = await coord._async_update_data()

    assert data.get("stale") is True
    assert len(coord.recent_intervals) > 0
    assert any(n > 0 for n in saved_tip_lengths)
    assert coord._last_api_error


@pytest.mark.asyncio
async def test_correction_import_failure_retains_marker_and_repairs():
    """A hard import failure keeps the recovery boundary and repairs best-effort."""
    coord = _make_coordinator()
    repair = AsyncMock()
    coord.async_repair_dirty_if_needed = repair

    async def fake_usage(start, end, resolution=UsageResolution.HOURLY):
        day = start.astimezone(local_day_bounds(today_local())[0].tzinfo).date()
        return UsageResponse(
            resolution=UsageResolution.HOURLY,
            intervals=_full_day_intervals(day) if day != today_local() else [],
            total_kwh=None,
            total_cost=None,
            is_tod=None,
            acct_type=None,
        )

    coord.async_get_usage_with_auth_retry = AsyncMock(side_effect=fake_usage)

    with (
        patch(
            "custom_components.pge_energy.coordinator.async_import_with_baseline",
            AsyncMock(side_effect=RuntimeError("recorder exploded mid-import")),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_save_import_state",
            AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_run_billing_sync",
            AsyncMock(),
        ),
    ):
        data = await coord._async_update_data()

    # The retained marker survives the failed poll (repair stub simulated
    # failure by not clearing it) so boot/correction repair keeps its boundary.
    assert coord._import_store.dirty_from is not None
    # Runtime repair was attempted after the lock released.
    repair.assert_awaited_once()
    assert data.get("stale") is True


@pytest.mark.asyncio
async def test_correction_skips_import_when_recovery_marker_pending():
    """Correction polls never import over another importer's pending boundary."""
    coord = _make_coordinator()
    pending_boundary = "2023-12-01T00:00:00+00:00"
    coord._import_store.dirty_from = pending_boundary
    repair = AsyncMock()
    coord.async_repair_dirty_if_needed = repair

    async def fake_usage(start, end, resolution=UsageResolution.HOURLY):
        day = start.astimezone(local_day_bounds(today_local())[0].tzinfo).date()
        return UsageResponse(
            resolution=UsageResolution.HOURLY,
            intervals=_full_day_intervals(day) if day != today_local() else [],
            total_kwh=None,
            total_cost=None,
            is_tod=None,
            acct_type=None,
        )

    coord.async_get_usage_with_auth_retry = AsyncMock(side_effect=fake_usage)
    record_import = AsyncMock(return_value=ImportBaselineResult(1))

    with (
        patch(
            "custom_components.pge_energy.coordinator.async_import_with_baseline",
            record_import,
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_save_import_state",
            AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_run_billing_sync",
            AsyncMock(),
        ),
    ):
        data = await coord._async_update_data()

    record_import.assert_not_awaited()
    # The pending boundary was left untouched for its owner's repair.
    assert coord._import_store.dirty_from == pending_boundary
    repair.assert_awaited_once()
    assert data.get("stale") is True


@pytest.mark.asyncio
async def test_cognito_rate_limit_keeps_retained_data_without_reauth():
    from custom_components.pge_energy.exceptions import PGERateLimitError

    coord = _make_coordinator(auth_mode="credential")
    yesterday = today_local() - timedelta(days=1)
    prior = _full_day_intervals(yesterday)
    coord._recent_intervals = list(prior)
    coord._lifetime_energy_kwh = 50.0
    coord.data = {"intervals": list(prior), "failed_days": []}
    coord.auth_manager.ensure_valid_token = AsyncMock(side_effect=PGERateLimitError("rate limited", retry_after=60))
    # Longer than any sync-clock-stretched polling interval so Cognito cooldown wins.
    coord.auth_manager.cognito_rate_limit_remaining_seconds = MagicMock(return_value=50_000.0)
    coord.hass.async_create_task = MagicMock()

    data = await coord._async_update_data()
    assert data["stale"] is True
    assert coord.recent_intervals == prior
    assert coord._reauth_requested is False
    coord.hass.async_create_task.assert_not_called()
    assert coord.update_interval == timedelta(seconds=50_000)


@pytest.mark.asyncio
async def test_try_reserve_backfill_rejects_overlap():
    coord = _make_coordinator()
    assert coord.try_reserve_backfill() is True
    assert coord.try_reserve_backfill() is False
    coord.release_backfill_reservation()
    assert coord.try_reserve_backfill() is True


@pytest.mark.asyncio
async def test_try_reserve_backfill_blocked_during_refresh_job():
    coord = _make_coordinator()

    def _fake_create_background_task(coro, name="", eager_start=False):
        coro.close()
        return MagicMock()

    coord.hass.async_create_background_task = MagicMock(side_effect=_fake_create_background_task)
    with patch(
        "custom_components.pge_energy.coordinator.async_save_import_state",
        AsyncMock(),
    ):
        await coord.async_start_refresh_job()
    assert coord.sync_job_in_progress is True
    assert coord.sync_progress.status == "refreshing"
    assert coord.try_reserve_backfill() is False
    coord.hass.async_create_background_task.assert_called_once()


@pytest.mark.asyncio
async def test_poll_invokes_billing_sync_after_usage_import():
    coord = _make_coordinator()

    async def fake_usage(start, end, resolution=UsageResolution.HOURLY):
        day = start.astimezone(local_day_bounds(today_local())[0].tzinfo).date()
        return UsageResponse(
            resolution=UsageResolution.HOURLY,
            intervals=_full_day_intervals(day) if day != today_local() else [],
            total_kwh=None,
            total_cost=None,
            is_tod=None,
            acct_type=None,
        )

    coord.async_get_usage_with_auth_retry = AsyncMock(side_effect=fake_usage)
    with (
        patch(
            "custom_components.pge_energy.coordinator.async_import_with_baseline",
            AsyncMock(return_value=ImportBaselineResult(1)),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_save_import_state",
            AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_run_billing_sync",
            AsyncMock(),
        ) as billing,
    ):
        data = await coord._async_update_data()

    billing.assert_awaited_once()
    assert "intervals" in data


@pytest.mark.asyncio
async def test_billing_skipped_when_usage_hard_fails():
    coord = _make_coordinator()
    coord.async_get_usage_with_auth_retry = AsyncMock(side_effect=PGESchemaError("bad"))
    with (
        patch(
            "custom_components.pge_energy.coordinator.async_save_import_state",
            AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_run_billing_sync",
            AsyncMock(),
        ) as billing,
        pytest.raises(UpdateFailed),
    ):
        await coord._async_update_data()
    billing.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_refresh_tracks_progress_and_completes():
    coord = _make_coordinator()
    coord._refresh_job_active = True
    coord.begin_sync_job(
        status="refreshing",
        phase="correction",
        total=2,
        message="Correction 0/2",
    )

    async def fake_usage(start, end, resolution=UsageResolution.HOURLY):
        day = start.astimezone(local_day_bounds(today_local())[0].tzinfo).date()
        return UsageResponse(
            resolution=UsageResolution.HOURLY,
            intervals=_full_day_intervals(day) if day != today_local() else [],
            total_kwh=None,
            total_cost=None,
            is_tod=None,
            acct_type=None,
        )

    coord.async_get_usage_with_auth_retry = AsyncMock(side_effect=fake_usage)
    with (
        patch(
            "custom_components.pge_energy.coordinator.async_import_with_baseline",
            AsyncMock(return_value=ImportBaselineResult(1)),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_save_import_state",
            AsyncMock(),
        ),
    ):
        await coord._async_update_data()

    assert coord.sync_progress.status == "complete"
    assert coord.sync_progress.percent == 100
    assert coord.sync_job_in_progress is False


@pytest.mark.asyncio
async def test_incomplete_yesterday_still_imports_and_demotes_completed():
    """Regression: 02:00 poll must not skip import when hourly is still gappy."""
    coord = _make_coordinator()
    yesterday = today_local() - timedelta(days=1)
    coord._import_store.completed_local_dates = [yesterday.isoformat()]
    imported: list[UsageInterval] = []

    async def fake_usage(start, end, resolution=UsageResolution.HOURLY):
        day = start.astimezone(local_day_bounds(today_local())[0].tzinfo).date()
        if day == yesterday:
            # Only 3 hours — validates as gap / incomplete closed day.
            day_start, _ = local_day_bounds(day)
            return UsageResponse(
                resolution=UsageResolution.HOURLY,
                intervals=_full_day_intervals(day)[:3],
                total_kwh=None,
                total_cost=None,
                is_tod=None,
                acct_type=None,
            )
        return UsageResponse(
            resolution=UsageResolution.HOURLY,
            intervals=[],
            total_kwh=None,
            total_cost=None,
            is_tod=None,
            acct_type=None,
        )

    async def capture_import(hass, account_key, intervals, include_cost=True, account_id=None):
        imported.extend(intervals)
        return ImportBaselineResult(len(intervals))

    coord.async_get_usage_with_auth_retry = AsyncMock(side_effect=fake_usage)
    with (
        patch(
            "custom_components.pge_energy.coordinator.async_import_with_baseline",
            AsyncMock(side_effect=capture_import),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_save_import_state",
            AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_run_billing_sync",
            AsyncMock(),
        ),
    ):
        await coord._async_update_data()

    assert len(imported) == 3
    assert yesterday.isoformat() not in coord._import_store.completed_local_dates
    assert yesterday.isoformat() in coord._import_store.failed_local_dates
    assert coord._catchup_retry is True
    assert coord.update_interval == timedelta(hours=2)


@pytest.mark.asyncio
async def test_complete_yesterday_clears_catchup_retry():
    coord = _make_coordinator()
    coord._catchup_retry = True

    async def fake_usage(start, end, resolution=UsageResolution.HOURLY):
        day = start.astimezone(local_day_bounds(today_local())[0].tzinfo).date()
        return UsageResponse(
            resolution=UsageResolution.HOURLY,
            intervals=_full_day_intervals(day) if day != today_local() else [],
            total_kwh=None,
            total_cost=None,
            is_tod=None,
            acct_type=None,
        )

    coord.async_get_usage_with_auth_retry = AsyncMock(side_effect=fake_usage)
    with (
        patch(
            "custom_components.pge_energy.coordinator.async_import_with_baseline",
            AsyncMock(return_value=ImportBaselineResult(1)),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_save_import_state",
            AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_run_billing_sync",
            AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.coordinator.resolve_polling_timedelta",
            return_value=timedelta(hours=22),
        ),
    ):
        await coord._async_update_data()

    assert coord._catchup_retry is False
    assert coord.update_interval == timedelta(hours=22)


@pytest.mark.asyncio
async def test_soft_fail_poll_contains_terminal_save_timeout():
    """A timed-out terminal write must not defeat the retained-data soft-fail."""
    coord = _make_coordinator()
    coord._import_store.completed_local_dates = ["2024-01-01"]

    async def _timeout_persist():
        raise TimeoutError

    coord.async_persist_sync_progress = _timeout_persist

    payload = await coord._async_soft_fail_poll("api down", tracking=True)
    assert payload["stale"] is True
    assert coord._last_api_error == "api down"


@pytest.mark.asyncio
async def test_correction_checkpoint_saves_hold_import_lock():
    """Marker save, import, and clear-save all run inside the import_lock."""
    coord = _make_coordinator()
    completed = (today_local() - timedelta(days=1)).isoformat()
    coord._import_store.completed_local_dates = [completed]

    async def fake_usage(start, end, resolution=UsageResolution.HOURLY):
        day = start.astimezone(local_day_bounds(today_local())[0].tzinfo).date()
        return UsageResponse(
            resolution=UsageResolution.HOURLY,
            intervals=_full_day_intervals(day) if day != today_local() else [],
            total_kwh=None,
            total_cost=None,
            is_tod=None,
            acct_type=None,
        )

    coord.async_get_usage_with_auth_retry = AsyncMock(side_effect=fake_usage)

    class _PriorOwnerClearsLock(asyncio.Lock):
        """A prior import_lock owner whose transaction cleared dirty_from."""

        def __init__(self, store: ImportStoreData) -> None:
            super().__init__()
            self._store = store

        async def acquire(self) -> None:
            await super().acquire()
            # Anything assigned BEFORE acquire is erased by the prior owner —
            # only a marker assigned INSIDE the locked section can survive.
            self._store.dirty_from = None

    coord.import_lock = _PriorOwnerClearsLock(coord._import_store)

    records: list[tuple[bool, bool, str | None]] = []  # (critical, locked, dirty_from)

    async def _rec_save(hass, entry_id, data, *, critical=True):  # noqa: ARG001
        records.append((critical, coord.import_lock.locked(), data.dirty_from))

    async def _rec_import(*args, **kwargs):  # noqa: ARG002, ARG001
        records.append((True, coord.import_lock.locked(), "import"))
        return ImportBaselineResult(1)

    with (
        patch(
            "custom_components.pge_energy.coordinator.async_import_with_baseline",
            AsyncMock(side_effect=_rec_import),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_save_import_state",
            AsyncMock(side_effect=_rec_save),
        ),
    ):
        await coord._async_update_data()

    durable = [(locked, marker) for critical, locked, marker in records if critical]
    assert len(durable) >= 3  # pre-import marker + post-import clear (+ import)
    assert all(locked for locked, _ in durable), records
    # The pre-import durable save must observe the call-time marker even
    # though the simulated prior lock owner cleared anything set pre-lock.
    # Its value is the earliest corrected-interval start, which the import
    # records as last_imported_start.
    assert durable[0] == (True, coord._import_store.last_imported_start)
    assert durable[0][1] is not None
    assert durable[-1][1] is None  # clear-save lands the emptied marker


@pytest.mark.asyncio
async def test_reset_checkpoint_waits_for_import_transaction():
    """Reset synchronizes on import_lock so it cannot erase a mid-import marker."""
    coord = _make_coordinator()
    clear_calls: list[bool] = []

    async def _rec_clear(hass, entry_id):  # noqa: ARG001
        clear_calls.append(coord.import_lock.locked())

    with patch(
        "custom_components.pge_energy.coordinator.async_clear_import_state",
        AsyncMock(side_effect=_rec_clear),
    ):
        await coord.import_lock.acquire()  # an import transaction is active
        reset_task = asyncio.create_task(coord.async_reset_checkpoint())
        await asyncio.sleep(0.02)
        assert not reset_task.done()  # blocked behind the transaction
        coord.import_lock.release()
        await asyncio.wait_for(reset_task, 1)

    assert clear_calls == [True]  # the clear ran while holding import_lock


@pytest.mark.asyncio
async def test_reset_checkpoint_holds_backfill_reservation():
    """A new backfill cannot reserve the slot while a reset is in flight."""
    coord = _make_coordinator()

    async def _rec_clear(hass, entry_id):  # noqa: ARG001
        # Mid-reset (slow empty write): the slot must stay reserved.
        assert coord.try_reserve_backfill() is False

    with patch(
        "custom_components.pge_energy.coordinator.async_clear_import_state",
        AsyncMock(side_effect=_rec_clear),
    ):
        await coord.async_reset_checkpoint()

    assert coord.backfill_in_progress is False  # released afterwards
    assert coord.try_reserve_backfill() is True


@pytest.mark.asyncio
async def test_repair_holds_import_lock_across_clear_and_save():
    """Repair, marker clear, and the durable clear-save share one import_lock."""
    coord = _make_coordinator()
    coord._import_store.dirty_from = "2024-05-01T00:00:00+00:00"
    events: list[tuple[str, bool]] = []
    marker_seen_by_save: list[str | None] = []

    async def fake_suffix_repair(hass, account_key, dirty, *, account_id=None):  # noqa: ARG001
        events.append(("repair", coord.import_lock.locked()))
        return None

    async def capture_save(hass, entry_id, store, critical=True):  # noqa: ARG001
        events.append(("save", coord.import_lock.locked()))
        marker_seen_by_save.append(store.dirty_from)
        return True

    with (
        patch(
            "custom_components.pge_energy.coordinator.async_repair_suffix_sums",
            side_effect=fake_suffix_repair,
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_save_import_state",
            side_effect=capture_save,
        ),
    ):
        await coord.async_repair_dirty_if_needed()

    assert events == [("repair", True), ("save", True)]
    # The clear happens before the save while still holding the lock.
    assert marker_seen_by_save == [None]
    assert coord._import_store.dirty_from is None


@pytest.mark.asyncio
async def test_repair_contains_clear_save_timeout_and_restores_marker():
    """A timed-out clear-save never raises; the boundary stays in memory+disk."""
    coord = _make_coordinator()
    original_marker = "2024-06-01T00:00:00+00:00"
    coord._import_store.dirty_from = original_marker

    async def fail_save(hass, entry_id, store, critical=True):  # noqa: ARG001
        raise TimeoutError("storage stalled")

    with (
        patch(
            "custom_components.pge_energy.coordinator.async_repair_suffix_sums",
            AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_save_import_state",
            side_effect=fail_save,
        ),
    ):
        # Must not propagate TimeoutError into poll/unload callers.
        await coord.async_repair_dirty_if_needed()

    # Memory matches the (stale) on-disk boundary so boot re-repairs harmlessly.
    assert coord._import_store.dirty_from == original_marker


@pytest.mark.asyncio
async def test_repair_rereads_marker_under_lock_and_clears_exactly_it():
    """A marker replaced while waiting on import_lock is repaired, not erased."""
    coord = _make_coordinator()
    stale_boundary = "2024-06-01T00:00:00+00:00"
    newer_boundary = "2024-07-01T00:00:00+00:00"
    coord._import_store.dirty_from = stale_boundary

    class _MutatingLock:
        """Simulates a newer boundary appearing before lock acquisition."""

        def __init__(self, inner, store):
            self._inner = inner
            self._store = store
            self.mutated = False

        async def __aenter__(self):
            if not self.mutated:
                self.mutated = True
                self._store.dirty_from = newer_boundary
            return await self._inner.__aenter__()

        async def __aexit__(self, *args):
            return await self._inner.__aexit__(*args)

    coord.import_lock = _MutatingLock(coord.import_lock, coord._import_store)

    repaired: list[str] = []

    async def fake_suffix_repair(hass, account_key, dirty, *, account_id=None):  # noqa: ARG001
        repaired.append(dirty.isoformat())
        return None

    with (
        patch(
            "custom_components.pge_energy.coordinator.async_repair_suffix_sums",
            side_effect=fake_suffix_repair,
        ),
        patch(
            "custom_components.pge_energy.coordinator.async_save_import_state",
            AsyncMock(return_value=True),
        ),
    ):
        await coord.async_repair_dirty_if_needed()

    # The NEWER boundary is what got repaired and cleared — not the stale one.
    assert repaired == [newer_boundary]
    assert coord._import_store.dirty_from is None
