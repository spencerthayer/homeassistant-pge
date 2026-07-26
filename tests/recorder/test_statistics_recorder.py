"""Recorder-backed import tests.

Run:
  .venv/bin/python -m pytest tests/recorder -p homeassistant -o addopts= -q
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.setup import async_setup_component

from custom_components.pge_energy.const import (
    STATISTIC_ID_SUFFIX_CONSUMPTION,
    STATISTIC_ID_SUFFIX_COST,
)
from custom_components.pge_energy.models import UsageInterval, UsageResolution
from custom_components.pge_energy.statistics import (
    _as_utc_datetime,
    _get_statistic_id,
    async_import_with_baseline,
    async_repair_suffix_sums,
)


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
