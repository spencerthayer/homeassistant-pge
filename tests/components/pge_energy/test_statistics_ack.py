"""Unit tests for recorder statistics ack / verify (no live recorder required)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.pge_energy.const import (
    MONTHLY_LUMP_MIN_COST,
    MONTHLY_LUMP_MIN_KWH,
    STATISTICS_ACK_WRITE_ATTEMPTS,
)
from custom_components.pge_energy.models import UsageInterval, UsageResolution
from custom_components.pge_energy.statistics import (
    ImportBaselineResult,
    _scrub_monthly_lumps_for_days,
    async_ack_external_statistics,
    async_import_with_baseline,
    async_verify_statistic_states,
)
from custom_components.pge_energy.time_util import PGE_TZ


def _meta(statistic_id: str = "pge_energy:key_consumption") -> dict:
    return {
        "has_mean": False,
        "has_sum": True,
        "name": "test",
        "source": "pge_energy",
        "statistic_id": statistic_id,
        "unit_of_measurement": "kWh",
    }


@pytest.mark.asyncio
async def test_verify_distinguishes_absent_from_stale():
    hass = MagicMock()
    start = datetime(2025, 7, 1, 8, tzinfo=UTC)
    with (
        patch(
            "custom_components.pge_energy.statistics._async_get_stats_map",
            new=AsyncMock(return_value={}),
        ),
        pytest.raises(RuntimeError, match="row absent"),
    ):
        await async_verify_statistic_states(
            hass,
            "pge_energy:key_cost",
            {start: 0.04},
            start=start,
            end=start + timedelta(hours=1),
        )

    with (
        patch(
            "custom_components.pge_energy.statistics._async_get_stats_map",
            new=AsyncMock(return_value={start: {"state": 0.01}}),
        ),
        pytest.raises(RuntimeError, match="state stale"),
    ):
        await async_verify_statistic_states(
            hass,
            "pge_energy:key_cost",
            {start: 0.04},
            start=start,
            end=start + timedelta(hours=1),
        )


@pytest.mark.asyncio
async def test_dropped_write_is_still_caught():
    """Ack must fail when writes are no-ops — do not weaken verify for overwrites."""
    hass = MagicMock()
    start = datetime(2025, 7, 1, 8, tzinfo=UTC)
    stats = [{"start": start, "state": 0.04, "sum": 0.04}]
    with (
        patch(
            "custom_components.pge_energy.statistics.async_wait_recorder_queue",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.statistics.async_add_external_statistics",
        ) as add,
        patch(
            "custom_components.pge_energy.statistics._async_get_stats_map",
            new=AsyncMock(return_value={start: {"state": 0.01}}),
        ),
        patch(
            "custom_components.pge_energy.statistics._async_log_ack_failure_diagnostics",
            new=AsyncMock(),
        ),
        pytest.raises(RuntimeError, match="state stale"),
    ):
        await async_ack_external_statistics(
            hass,
            statistic_id="pge_energy:key_cost",
            metadata=_meta("pge_energy:key_cost"),
            stats=stats,
            expected_states={start: 0.04},
            start=start,
            end=start + timedelta(hours=1),
        )
    # Initial write is outside ack; ack re-issues on each failed verify except last.
    assert add.call_count == STATISTICS_ACK_WRITE_ATTEMPTS - 1


@pytest.mark.asyncio
async def test_ack_retries_the_write():
    hass = MagicMock()
    start = datetime(2025, 7, 1, 8, tzinfo=UTC)
    stats = [{"start": start, "state": 1.0, "sum": 1.0}]
    verify = AsyncMock(side_effect=[RuntimeError("stale"), None])
    with (
        patch(
            "custom_components.pge_energy.statistics.async_wait_recorder_queue",
            new=AsyncMock(),
        ),
        patch(
            "custom_components.pge_energy.statistics.async_add_external_statistics",
        ) as add,
        patch(
            "custom_components.pge_energy.statistics.async_verify_statistic_states",
            verify,
        ),
    ):
        await async_ack_external_statistics(
            hass,
            statistic_id="pge_energy:key_consumption",
            metadata=_meta(),
            stats=stats,
            expected_states={start: 1.0},
            start=start,
            end=start + timedelta(hours=1),
        )
    assert verify.await_count == 2
    assert add.call_count == 1


def test_scrub_zero_starts_stay_in_expected_states_path():
    """Scrub injects overlay[start]=0.0; that value must remain in expected_states."""
    month_start = datetime(2025, 9, 1, 7, tzinfo=UTC)
    hour = datetime(2025, 9, 1, 8, tzinfo=UTC)
    existing = {month_start: {"state": 648.0}, hour: {"state": 0.28}}
    overlay = {hour: 0.31}
    scrubbed = _scrub_monthly_lumps_for_days(existing, overlay, lump_min=MONTHLY_LUMP_MIN_KWH)
    assert scrubbed == 1
    assert overlay[month_start] == 0.0
    # Simulate expected_states construction used by import/repair paths.
    expected = {start: float(state) for start, state in overlay.items()}
    assert expected[month_start] == 0.0


def test_scrub_zero_cost_lump_also_in_overlay():
    month_start = datetime(2025, 9, 1, 7, tzinfo=UTC)
    hour = datetime(2025, 9, 1, 8, tzinfo=UTC)
    existing = {month_start: {"state": 120.0}, hour: {"state": 0.04}}
    overlay = {hour: 0.05}
    scrubbed = _scrub_monthly_lumps_for_days(existing, overlay, lump_min=MONTHLY_LUMP_MIN_COST)
    assert scrubbed == 1
    assert overlay[month_start] == 0.0


def _interval(hour: int, kwh: float, amount: float, *, day: int = 1) -> UsageInterval:
    start = datetime(2025, 7, day, hour, tzinfo=UTC)
    return UsageInterval(
        account_key="key",
        resolution=UsageResolution.HOURLY,
        start=start,
        end=start + timedelta(hours=1),
        kwh=Decimal(str(kwh)),
        amount=Decimal(str(amount)),
        temperature=None,
        usage_status="kWh-Delivered",
        interval_size=900,
        source_timestamp=None,
    )


@pytest.mark.asyncio
async def test_cost_ack_failure_is_nonfatal_and_mirrors():
    intervals = [_interval(8, 1.0, 0.04)]
    cost_day = intervals[0].start.astimezone(PGE_TZ).date().isoformat()
    mirror_calls: list[str] = []

    async def ack_side_effect(hass, *, statistic_id, metadata, stats, expected_states, start, end):
        if statistic_id.endswith("_cost"):
            raise RuntimeError("Recorder state stale … expected=0.04 actual=0.01")
        return None

    def mirror(hass, *, account_key, unique_suffix, entity_metadata, stats):
        mirror_calls.append(unique_suffix)

    with (
        patch(
            "custom_components.pge_energy.statistics._async_get_last_stats",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.pge_energy.statistics._async_get_stats_map",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "custom_components.pge_energy.statistics._async_anchor_sum",
            new=AsyncMock(return_value=0.0),
        ),
        patch("custom_components.pge_energy.statistics.async_add_external_statistics"),
        patch(
            "custom_components.pge_energy.statistics.async_ack_external_statistics",
            new=AsyncMock(side_effect=ack_side_effect),
        ),
        patch(
            "custom_components.pge_energy.statistics._async_mirror_entity_statistics",
            side_effect=mirror,
        ),
        patch(
            "custom_components.pge_energy.statistics._async_import_temperature_overlay",
            new=AsyncMock(return_value=set()),
        ),
    ):
        result = await async_import_with_baseline(MagicMock(), "key", intervals, include_cost=True)

    assert isinstance(result, ImportBaselineResult)
    assert result == 1
    assert cost_day in result.cost_failed_days
    assert "cost" in mirror_calls
    assert "energy" in mirror_calls


@pytest.mark.asyncio
async def test_consumption_ack_failure_still_propagates():
    intervals = [_interval(8, 1.0, 0.04)]

    async def ack_side_effect(hass, *, statistic_id, metadata, stats, expected_states, start, end):
        if statistic_id.endswith("_consumption"):
            raise RuntimeError("Recorder row absent …")
        return None

    with (
        patch(
            "custom_components.pge_energy.statistics._async_get_last_stats",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.pge_energy.statistics._async_get_stats_map",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "custom_components.pge_energy.statistics._async_anchor_sum",
            new=AsyncMock(return_value=0.0),
        ),
        patch("custom_components.pge_energy.statistics.async_add_external_statistics"),
        patch(
            "custom_components.pge_energy.statistics.async_ack_external_statistics",
            new=AsyncMock(side_effect=ack_side_effect),
        ),
        patch("custom_components.pge_energy.statistics._async_mirror_entity_statistics"),
        patch(
            "custom_components.pge_energy.statistics._async_import_temperature_overlay",
            new=AsyncMock(return_value=set()),
        ),
        pytest.raises(RuntimeError, match="row absent"),
    ):
        await async_import_with_baseline(MagicMock(), "key", intervals, include_cost=True)
