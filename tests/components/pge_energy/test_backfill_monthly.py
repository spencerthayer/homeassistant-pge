"""Monthly backfill coverage — billing periods, before-service, fetch end."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.pge_energy.backfill import (
    _async_backfill_monthly,
    _calendar_month_has_completed,
    _merge_by_month_start,
)
from custom_components.pge_energy.models import UsageInterval, UsageResolution, UsageResponse
from custom_components.pge_energy.store import ImportStoreData


def _period(start: datetime, end: datetime, kwh: str = "100") -> UsageInterval:
    return UsageInterval(
        account_key="key",
        resolution=UsageResolution.MONTHLY,
        start=start,
        end=end,
        kwh=Decimal(kwh),
        amount=Decimal("20"),
        temperature=None,
        usage_status=None,
        interval_size=None,
        source_timestamp=None,
    )


def _coordinator(store: ImportStoreData) -> MagicMock:
    coord = MagicMock()
    coord.import_store = store
    coord.auth_manager.auth_mode = "credential"
    coord.auth_manager.ensure_valid_token = AsyncMock()
    coord.persist_auth_to_entry = MagicMock()
    coord.sync_progress.done = 0
    coord.sync_progress.total = 100
    coord.update_sync_progress = MagicMock()
    coord.async_persist_sync_progress = AsyncMock()
    return coord


@pytest.mark.asyncio
async def test_monthly_fetches_through_yesterday_not_last_incomplete():
    """Regression: end=last-incomplete omitted the covering billing period."""
    store = ImportStoreData(account_key="key")
    # Gap: July 2021 only (matches live stuck state shape).
    incomplete_start = date(2021, 7, 1)
    incomplete_end = date(2021, 7, 31)
    coord = _coordinator(store)

    # Billing period that covers July 8–Aug 5 — only returned when fetch end
    # reaches into August (i.e. paging from "yesterday", not 2021-07-31).
    july_period = _period(
        datetime(2021, 7, 8, 7, tzinfo=UTC),
        datetime(2021, 8, 6, 7, tzinfo=UTC),
        "688",
    )
    june_period = _period(
        datetime(2021, 6, 8, 7, tzinfo=UTC),
        datetime(2021, 7, 8, 7, tzinfo=UTC),
        "778",
    )

    captured: dict[str, datetime] = {}

    async def fake_monthly(start: datetime, end: datetime) -> UsageResponse:
        captured["start"] = start
        captured["end"] = end
        return UsageResponse(
            resolution=UsageResolution.MONTHLY,
            intervals=[june_period, july_period],
            total_kwh=None,
            total_cost=None,
            is_tod=False,
            acct_type="RES",
        )

    coord.async_get_monthly_usage_with_auth_retry = AsyncMock(side_effect=fake_monthly)

    with (
        patch(
            "custom_components.pge_energy.backfill.today_local",
            return_value=date(2026, 7, 24),
        ),
        patch(
            "custom_components.pge_energy.backfill._async_import_batch",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "custom_components.pge_energy.backfill.async_save_import_state",
            new=AsyncMock(),
        ),
    ):
        await _async_backfill_monthly(MagicMock(), "entry1", coord, incomplete_start, incomplete_end)

    # Fetch end must be yesterday (2026-07-23), not 2021-07-31.
    assert captured["end"].date() >= date(2026, 7, 23)
    completed = set(store.completed_local_dates)
    assert date(2021, 7, 1).isoformat() in completed
    assert date(2021, 7, 15).isoformat() in completed
    assert date(2021, 7, 31).isoformat() in completed
    assert not store.failed_local_dates


@pytest.mark.asyncio
async def test_monthly_marks_days_before_oldest_period_complete():
    store = ImportStoreData(account_key="key")
    coord = _coordinator(store)
    oldest = _period(
        datetime(2019, 11, 1, 7, tzinfo=UTC),
        datetime(2019, 11, 6, 8, tzinfo=UTC),
        "183",
    )

    async def fake_monthly(start: datetime, end: datetime) -> UsageResponse:
        return UsageResponse(
            resolution=UsageResolution.MONTHLY,
            intervals=[oldest],
            total_kwh=None,
            total_cost=None,
            is_tod=False,
            acct_type="RES",
        )

    coord.async_get_monthly_usage_with_auth_retry = AsyncMock(side_effect=fake_monthly)

    with (
        patch(
            "custom_components.pge_energy.backfill.today_local",
            return_value=date(2026, 7, 24),
        ),
        patch(
            "custom_components.pge_energy.backfill._async_import_batch",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "custom_components.pge_energy.backfill.async_save_import_state",
            new=AsyncMock(),
        ),
    ):
        await _async_backfill_monthly(MagicMock(), "entry1", coord, date(2019, 1, 1), date(2019, 11, 5))

    completed = set(store.completed_local_dates)
    assert date(2019, 1, 1).isoformat() in completed
    assert date(2019, 10, 31).isoformat() in completed
    assert date(2019, 11, 1).isoformat() in completed
    assert date(2019, 11, 5).isoformat() in completed
    assert not store.failed_local_dates


@pytest.mark.asyncio
async def test_monthly_completes_covered_days_even_when_stats_import_conflicts():
    store = ImportStoreData(account_key="key")
    coord = _coordinator(store)
    period = _period(
        datetime(2021, 7, 8, 7, tzinfo=UTC),
        datetime(2021, 8, 6, 7, tzinfo=UTC),
    )
    coord.async_get_monthly_usage_with_auth_retry = AsyncMock(
        return_value=UsageResponse(
            resolution=UsageResolution.MONTHLY,
            intervals=[period],
            total_kwh=None,
            total_cost=None,
            is_tod=False,
            acct_type="RES",
        )
    )

    with (
        patch(
            "custom_components.pge_energy.backfill.today_local",
            return_value=date(2026, 7, 24),
        ),
        patch(
            "custom_components.pge_energy.backfill._async_import_batch",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "custom_components.pge_energy.backfill.async_save_import_state",
            new=AsyncMock(),
        ),
    ):
        await _async_backfill_monthly(MagicMock(), "entry1", coord, date(2021, 7, 8), date(2021, 7, 20))

    assert date(2021, 7, 8).isoformat() in store.completed_local_dates
    assert date(2021, 7, 20).isoformat() in store.completed_local_dates
    assert not store.failed_local_dates


def test_merge_by_month_start_sums_same_month_cycles():
    """Two cycles starting in one calendar month must sum, not clobber."""
    from custom_components.pge_energy.backfill import _normalize_monthly_interval

    short = _normalize_monthly_interval(
        _period(datetime(2021, 7, 2, 7, tzinfo=UTC), datetime(2021, 7, 31, 7, tzinfo=UTC), "300")
    )
    rest = _normalize_monthly_interval(
        _period(datetime(2021, 7, 31, 7, tzinfo=UTC), datetime(2021, 8, 30, 7, tzinfo=UTC), "400")
    )
    assert short.start == rest.start  # both normalize onto 2021-07-01

    merged = _merge_by_month_start([short, rest])
    assert len(merged) == 1
    assert merged[0].kwh == Decimal("700")
    assert merged[0].amount == Decimal("40")


def test_calendar_month_has_completed_detects_finer_days():
    store = ImportStoreData(account_key="key")
    store.completed_local_dates = ["2025-09-15"]
    assert _calendar_month_has_completed(store, date(2025, 9, 1))
    assert not _calendar_month_has_completed(store, date(2025, 8, 1))


@pytest.mark.asyncio
async def test_monthly_skips_stats_when_calendar_month_has_finer_data():
    """Regression: full-period lump on month-start must not land atop hourly days."""
    store = ImportStoreData(account_key="key")
    # September already has hourly history; only a late gap day remains.
    store.completed_local_dates = ["2025-09-01", "2025-09-15"]
    coord = _coordinator(store)
    period = _period(
        datetime(2025, 9, 5, 7, tzinfo=UTC),
        datetime(2025, 10, 6, 7, tzinfo=UTC),
        "648",
    )
    coord.async_get_monthly_usage_with_auth_retry = AsyncMock(
        return_value=UsageResponse(
            resolution=UsageResolution.MONTHLY,
            intervals=[period],
            total_kwh=None,
            total_cost=None,
            is_tod=False,
            acct_type="RES",
        )
    )
    import_batch = AsyncMock(return_value=True)

    with (
        patch(
            "custom_components.pge_energy.backfill.today_local",
            return_value=date(2026, 7, 24),
        ),
        patch(
            "custom_components.pge_energy.backfill._async_import_batch",
            new=import_batch,
        ),
        patch(
            "custom_components.pge_energy.backfill.async_save_import_state",
            new=AsyncMock(),
        ),
    ):
        await _async_backfill_monthly(MagicMock(), "entry1", coord, date(2025, 10, 1), date(2025, 10, 5))

    import_batch.assert_not_called()
    assert date(2025, 10, 1).isoformat() in store.completed_local_dates
    assert date(2025, 10, 5).isoformat() in store.completed_local_dates


@pytest.mark.asyncio
async def test_backfill_range_keeps_failures_outside_job_range():
    """A narrow job must not erase failure records the retry service depends on."""
    from custom_components.pge_energy.backfill import async_backfill_range

    store = ImportStoreData(account_key="key")
    store.failed_local_dates = ["2019-03-04"]  # older failure, outside this job
    coord = _coordinator(store)
    coord.sync_progress.status = "idle"
    coord.begin_sync_job = MagicMock()
    coord.complete_sync_job = MagicMock()
    coord.fail_sync_job = MagicMock()

    with (
        patch(
            "custom_components.pge_energy.backfill.today_local",
            return_value=date(2026, 7, 24),
        ),
        patch(
            "custom_components.pge_energy.backfill.async_save_import_state",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.backfill._async_backfill_hourly",
            new=AsyncMock(side_effect=lambda *a, **k: store.completed_local_dates.append("2026-07-23")),
        ),
    ):
        await async_backfill_range(
            MagicMock(),
            "entry1",
            coord,
            datetime(2026, 7, 23, 7, tzinfo=UTC),
            datetime(2026, 7, 24, 6, tzinfo=UTC),
        )

    assert store.failed_local_dates == ["2019-03-04"]
    coord.complete_sync_job.assert_called_once()
