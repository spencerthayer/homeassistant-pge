"""Recorder-backed import tests.

Run:
  .venv/bin/python -m pytest tests/recorder -p homeassistant -o addopts= -q
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.setup import async_setup_component

from custom_components.pge_energy.const import (
    STATISTIC_ID_SUFFIX_CONSUMPTION,
    STATISTIC_ID_SUFFIX_COST,
)
from custom_components.pge_energy.models import UsageInterval, UsageResolution
from custom_components.pge_energy.statistics import (
    _as_utc_datetime,
    _build_consumption_metadata,
    _get_statistic_id,
    _stat_row,
    async_import_with_baseline,
    async_repair_coarse_fine_collisions,
    async_repair_suffix_sums,
)
from custom_components.pge_energy.time_util import local_day_bounds


def _interval(
    hour: int,
    kwh: float,
    amount: float | None = 0.1,
    *,
    day: int = 1,
    account_key: str = "recorderkey1234",
) -> UsageInterval:
    start = datetime(2025, 7, day, hour, 0, 0, tzinfo=UTC)
    return UsageInterval(
        account_key=account_key,
        resolution=UsageResolution.HOURLY,
        start=start,
        end=start + timedelta(hours=1),
        kwh=Decimal(str(kwh)),
        amount=Decimal(str(amount)) if amount is not None else None,
        temperature=None,
        usage_status="kWh-Delivered",
        interval_size=900,
        source_timestamp=None,
    )


def _row(
    account_key: str,
    start: datetime,
    kwh: float,
    *,
    resolution: UsageResolution = UsageResolution.HOURLY,
    end: datetime | None = None,
) -> UsageInterval:
    return UsageInterval(
        account_key=account_key,
        resolution=resolution,
        start=start,
        end=end or start + timedelta(hours=1),
        kwh=Decimal(str(kwh)),
        amount=None,
        temperature=None,
        usage_status=None,
        interval_size=None,
        source_timestamp=None,
    )


async def _read_rows(hass, statistic_id: str, start: datetime, end: datetime):
    return await hass.async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        end,
        {statistic_id},
        "hour",
        None,
        {"state", "sum"},
    )


@pytest.mark.asyncio
async def test_as_utc_datetime_from_unix_float():
    dt = _as_utc_datetime(1751328000.0)
    assert dt is not None
    assert dt.tzinfo is not None


@pytest.mark.asyncio
async def test_import_correction_exact_states_and_sums(recorder_mock, hass):
    assert await async_setup_component(hass, "homeassistant", {})
    await hass.async_block_till_done()

    account_key = "recorderkey1234"
    intervals = [_interval(0, 1.0), _interval(1, 2.0)]
    assert await async_import_with_baseline(hass, account_key, intervals) == 2
    await hass.async_block_till_done()

    corrected = [_interval(0, 1.5), _interval(1, 2.0), _interval(2, 3.0)]
    assert await async_import_with_baseline(hass, account_key, corrected) == 3
    await hass.async_block_till_done()

    sid = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_CONSUMPTION)
    rows = await _read_rows(
        hass,
        sid,
        datetime(2025, 7, 1, tzinfo=UTC),
        datetime(2025, 7, 2, tzinfo=UTC),
    )
    assert sid in rows
    states = [float(r["state"]) for r in rows[sid]]
    sums = [float(r["sum"]) for r in rows[sid]]
    assert states == pytest.approx([1.5, 2.0, 3.0])
    assert sums == pytest.approx([1.5, 3.5, 6.5])

    cost_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_COST)
    cost_rows = await _read_rows(
        hass,
        cost_id,
        datetime(2025, 7, 1, tzinfo=UTC),
        datetime(2025, 7, 2, tzinfo=UTC),
    )
    assert cost_id in cost_rows
    assert len(cost_rows[cost_id]) == 3
    assert float(cost_rows[cost_id][-1]["sum"]) == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_historical_insert_rebases_later_sums(recorder_mock, hass):
    assert await async_setup_component(hass, "homeassistant", {})
    await hass.async_block_till_done()

    account_key = "recorderkeyhist1"
    later = [_interval(2, 2.0), _interval(3, 3.0)]
    assert await async_import_with_baseline(hass, account_key, later) == 2
    await hass.async_block_till_done()

    earlier = [_interval(0, 1.0), _interval(1, 1.0)]
    assert await async_import_with_baseline(hass, account_key, earlier) == 2
    await hass.async_block_till_done()

    sid = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_CONSUMPTION)
    rows = await _read_rows(
        hass,
        sid,
        datetime(2025, 7, 1, tzinfo=UTC),
        datetime(2025, 7, 2, tzinfo=UTC),
    )
    states = [float(r["state"]) for r in rows[sid]]
    sums = [float(r["sum"]) for r in rows[sid]]
    assert states == pytest.approx([1.0, 1.0, 2.0, 3.0])
    assert sums == pytest.approx([1.0, 2.0, 4.0, 7.0])


@pytest.mark.asyncio
async def test_repair_suffix_sums_after_dirty_marker(recorder_mock, hass):
    assert await async_setup_component(hass, "homeassistant", {})
    await hass.async_block_till_done()

    account_key = "recorderkeyrepair"
    intervals = [_interval(0, 1.0), _interval(1, 2.0), _interval(2, 3.0)]
    assert await async_import_with_baseline(hass, account_key, intervals) == 3
    await hass.async_block_till_done()

    dirty_from = datetime(2025, 7, 1, 1, 0, 0, tzinfo=UTC)
    await async_repair_suffix_sums(hass, account_key, dirty_from)
    await hass.async_block_till_done()

    sid = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_CONSUMPTION)
    rows = await _read_rows(
        hass,
        sid,
        datetime(2025, 7, 1, tzinfo=UTC),
        datetime(2025, 7, 2, tzinfo=UTC),
    )
    sums = [float(r["sum"]) for r in rows[sid]]
    assert sums == pytest.approx([1.0, 3.0, 6.0])


@pytest.mark.parametrize("frontier_day", [date(2025, 7, 2), date(2025, 11, 2), date(2026, 3, 8)])
@pytest.mark.asyncio
async def test_coarse_frontier_rows_never_double_count(recorder_mock, hass, frontier_day):
    """Coarse totals and partial hours must never add up twice or lower the cumulative sum."""
    assert await async_setup_component(hass, "homeassistant", {})
    await hass.async_block_till_done()

    day_start, day_end = local_day_bounds(frontier_day)
    prior_start, _ = local_day_bounds(frontier_day - timedelta(days=1))
    day_hours = int((day_end - day_start).total_seconds() // 3600)

    cases = {
        "partial_then_daily": (("hourly:3", "daily"), 175.0),
        "daily_then_partial": (("daily", "hourly:3"), 175.0),
        "partial_daily_partial": (("hourly:3", "daily", "hourly:4"), 175.0),
        "partial_daily_full": (("hourly:3", "daily", "hourly:full"), float(day_hours)),
        "daily_full": (("daily", "hourly:full"), float(day_hours)),
    }

    violations: list[str] = []
    for index, (name, (steps, expected_total)) in enumerate(cases.items()):
        account_key = f"recorderfrontier{index:02d}"
        sid = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_CONSUMPTION)

        await async_import_with_baseline(
            hass,
            account_key,
            [_row(account_key, prior_start + timedelta(hours=hour), 1.0) for hour in range(2)],
        )
        await hass.async_block_till_done()
        prior_rows = await _read_rows(hass, sid, prior_start, day_start)
        baseline = float(prior_rows[sid][-1]["sum"])

        for step in steps:
            if step == "daily":
                batch = [_row(account_key, day_start, 175.0, resolution=UsageResolution.DAILY, end=day_end)]
            else:
                count = day_hours if step == "hourly:full" else int(step.rsplit(":", 1)[1])
                batch = [_row(account_key, day_start + timedelta(hours=hour), 1.0) for hour in range(count)]
            await async_import_with_baseline(hass, account_key, batch)
            await hass.async_block_till_done()

        rows = (await _read_rows(hass, sid, day_start, day_end))[sid]
        states = [float(row["state"]) for row in rows]
        sums = [float(row["sum"]) for row in rows]
        if any(state < 0 for state in states):
            violations.append(f"{name} ({frontier_day}): negative state {states}")
        if any(later < earlier for earlier, later in zip(sums, sums[1:], strict=False)):
            violations.append(f"{name} ({frontier_day}): sum decreased {sums}")
        total = sums[-1] - baseline
        if total < 0 or total != pytest.approx(expected_total):
            violations.append(f"{name} ({frontier_day}): day total {total} != {expected_total}")

    assert not violations, "\n".join(violations)


@pytest.mark.asyncio
async def test_startup_repair_resolves_stale_daily_lump(recorder_mock, hass):
    """A stored DAILY total beside a few partial hours must not count both."""
    assert await async_setup_component(hass, "homeassistant", {})
    await hass.async_block_till_done()

    account_key = "recorderrepaircoarse"
    day_start, day_end = local_day_bounds(date(2025, 7, 2))
    states = [175.0, 1.0, 1.0, 1.0]
    rows = []
    running = 0.0
    for hour, state in enumerate(states):
        running += state
        rows.append(_stat_row(day_start + timedelta(hours=hour), state, running))
    async_add_external_statistics(hass, _build_consumption_metadata(account_key), rows)
    await hass.async_block_till_done()

    sid = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_CONSUMPTION)
    assert await async_repair_coarse_fine_collisions(hass, account_key) == 3
    await hass.async_block_till_done()
    assert await async_repair_coarse_fine_collisions(hass, account_key) == 0
    await hass.async_block_till_done()

    repaired = (await _read_rows(hass, sid, day_start, day_end))[sid]
    assert [float(row["state"]) for row in repaired] == [175.0, 0.0, 0.0, 0.0]
    assert float(repaired[-1]["sum"]) == pytest.approx(175.0)
