from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.const import DOMAIN as RECORDER_DOMAIN
from homeassistant.components.recorder.models.statistics import StatisticMetaData
from homeassistant.components.recorder.statistics import (
    StatisticMeanType,
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.components.recorder.statistics import (
    async_import_statistics as ha_async_import_statistics,
)
from homeassistant.const import UnitOfEnergy, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    DAILY_LUMP_MIN_COST,
    DAILY_LUMP_MIN_KWH,
    DEFAULT_HISTORY_FLOOR,
    DOMAIN,
    ENTITY_UNIQUE_COST,
    ENTITY_UNIQUE_ENERGY,
    ENTITY_UNIQUE_TEMPERATURE,
    MONTHLY_LUMP_MIN_COST,
    MONTHLY_LUMP_MIN_KWH,
    STATISTIC_ID_SUFFIX_CONSUMPTION,
    STATISTIC_ID_SUFFIX_COST,
    STATISTIC_ID_SUFFIX_TEMPERATURE,
)
from .models import UsageInterval
from .options import pge_display_name
from .time_util import PGE_TZ, local_day_bounds

_LOGGER = logging.getLogger(__name__)


def _get_statistic_id(account_key: str, suffix: str) -> str:
    return f"{DOMAIN}:{account_key}{suffix}"


def async_resolve_sensor_entity_id(
    hass: HomeAssistant,
    account_key: str,
    unique_suffix: str,
) -> str | None:
    """Return entity_id for a PGE sensor unique_id, if registered."""
    return er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{account_key}_{unique_suffix}")


def _statistic_display_name(
    account_id: str | None,
    account_key: str,
    *,
    cost: bool = False,
    temperature: bool = False,
) -> str:
    base = pge_display_name(account_id) if account_id else pge_display_name(account_key[:8])
    if cost:
        return f"{base} cost"
    if temperature:
        return f"{base} temperature"
    return base


def _as_utc_datetime(value: Any) -> datetime | None:
    """Normalize recorder/API starts to aware UTC datetimes."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=UTC)
    if isinstance(value, str):
        parsed = dt_util.parse_datetime(value)
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    return None


def _build_consumption_metadata(account_key: str, account_id: str | None = None) -> StatisticMetaData:
    stat_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_CONSUMPTION)
    return StatisticMetaData(
        has_mean=False,
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=_statistic_display_name(account_id, account_key, cost=False),
        source=DOMAIN,
        statistic_id=stat_id,
        unit_class="energy",
        unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    )


def _build_cost_metadata(account_key: str, account_id: str | None = None) -> StatisticMetaData:
    stat_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_COST)
    return StatisticMetaData(
        has_mean=False,
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=_statistic_display_name(account_id, account_key, cost=True),
        source=DOMAIN,
        statistic_id=stat_id,
        unit_class=None,
        unit_of_measurement="USD",
    )


def _build_temperature_metadata(account_key: str, account_id: str | None = None) -> StatisticMetaData:
    """PGE-reported outdoor temperature (°F) for each usage interval."""
    stat_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_TEMPERATURE)
    return StatisticMetaData(
        has_mean=True,
        mean_type=StatisticMeanType.ARITHMETIC,
        has_sum=False,
        name=_statistic_display_name(account_id, account_key, temperature=True),
        source=DOMAIN,
        statistic_id=stat_id,
        unit_class="temperature",
        unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
    )


def _build_entity_consumption_metadata(entity_id: str, name: str) -> StatisticMetaData:
    """Recorder-linked energy statistics for a sensor entity_id."""
    return StatisticMetaData(
        has_mean=False,
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=name,
        source=RECORDER_DOMAIN,
        statistic_id=entity_id,
        unit_class="energy",
        unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    )


def _build_entity_cost_metadata(entity_id: str, name: str) -> StatisticMetaData:
    return StatisticMetaData(
        has_mean=False,
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=name,
        source=RECORDER_DOMAIN,
        statistic_id=entity_id,
        unit_class=None,
        unit_of_measurement="USD",
    )


def _build_entity_temperature_metadata(entity_id: str, name: str) -> StatisticMetaData:
    return StatisticMetaData(
        has_mean=True,
        mean_type=StatisticMeanType.ARITHMETIC,
        has_sum=False,
        name=name,
        source=RECORDER_DOMAIN,
        statistic_id=entity_id,
        unit_class="temperature",
        unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
    )


def _async_mirror_entity_statistics(
    hass: HomeAssistant,
    *,
    account_key: str,
    unique_suffix: str,
    entity_metadata: StatisticMetaData,
    stats: list[dict],
) -> None:
    """Copy the same hourly rows onto the sensor's recorder statistic_id."""
    if not stats:
        return
    entity_id = async_resolve_sensor_entity_id(hass, account_key, unique_suffix)
    if entity_id is None:
        _LOGGER.debug(
            "Skip entity stats mirror for %s_%s — sensor not registered yet",
            account_key[:8],
            unique_suffix,
        )
        return
    # Ensure statistic_id matches the live entity_id (may differ from suggestion).
    metadata = {**entity_metadata, "statistic_id": entity_id}
    ha_async_import_statistics(hass, metadata, stats)
    _LOGGER.debug("Mirrored %s rows onto entity statistic %s", len(stats), entity_id)


def _stat_row(
    start: datetime,
    state: float,
    running_sum: float,
) -> dict[str, Any]:
    return {
        "start": start,
        "state": state,
        "sum": running_sum,
        "last_reset": None,
        "min": None,
        "max": None,
        "mean": None,
        "mean_weight": None,
    }


def _mean_stat_row(start: datetime, value: float) -> dict[str, Any]:
    """Non-cumulative statistic row (temperature)."""
    return {
        "start": start,
        "state": value,
        "sum": None,
        "last_reset": None,
        "min": value,
        "max": value,
        "mean": value,
        "mean_weight": None,
    }


def _recalculate_sums(stats: list[dict]) -> None:
    running_sum = 0.0
    for stat in stats:
        running_sum += float(stat["state"])
        stat["sum"] = running_sum


def _build_statistics(intervals: list[UsageInterval]) -> list[dict]:
    stats = []
    for iv in sorted(intervals, key=lambda x: x.start):
        stats.append(
            {
                "start": iv.start,
                "state": float(iv.kwh),
                "sum": 0.0,
                "last_reset": None,
                "min": None,
                "max": None,
                "mean": None,
                "mean_weight": None,
            }
        )
    _recalculate_sums(stats)
    return stats


def _build_cost_statistics(intervals: list[UsageInterval]) -> list[dict]:
    stats = []
    for iv in sorted(intervals, key=lambda x: x.start):
        if iv.amount is None:
            continue
        stats.append(
            {
                "start": iv.start,
                "state": float(iv.amount),
                "sum": 0.0,
                "last_reset": None,
                "min": None,
                "max": None,
                "mean": None,
                "mean_weight": None,
            }
        )
    _recalculate_sums(stats)
    return stats


def _build_temperature_statistics(intervals: list[UsageInterval]) -> list[dict]:
    stats = []
    for iv in sorted(intervals, key=lambda x: x.start):
        if iv.temperature is None:
            continue
        stats.append(_mean_stat_row(iv.start, float(iv.temperature)))
    return stats


def _build_incremental_statistics(
    intervals: list[UsageInterval],
    baseline_sum: float,
    use_cost: bool = False,
) -> list[dict]:
    stats = []
    running_sum = baseline_sum

    for iv in sorted(intervals, key=lambda x: x.start):
        if use_cost:
            if iv.amount is None:
                continue
            state = float(iv.amount)
        else:
            state = float(iv.kwh)
        running_sum += state
        stats.append(_stat_row(iv.start, state, running_sum))

    return stats


def _dedupe_intervals(intervals: list[UsageInterval]) -> list[UsageInterval]:
    """Keep last interval for duplicate starts."""
    by_start: dict[datetime, UsageInterval] = {}
    for iv in intervals:
        by_start[iv.start.astimezone(UTC)] = iv
    return [by_start[k] for k in sorted(by_start)]


async def _async_get_last_stats(
    hass: HomeAssistant,
    statistic_id: str,
) -> tuple[float, datetime | None] | None:
    """Return (last_sum_or_value, last_start) for a statistic, or None if no data.

    Cumulative series use ``sum``. Mean-only series (temperature) fall back to
    ``state`` / ``mean`` so callers can still discover the latest start.
    """
    try:
        last_stats = await get_instance(hass).async_add_executor_job(
            get_last_statistics,
            hass,
            1,
            statistic_id,
            True,
            {"sum", "state", "mean"},
        )
    except Exception as exc:
        _LOGGER.error("get_last_statistics failed for %s: %s", statistic_id, exc)
        raise

    if not last_stats or statistic_id not in last_stats:
        return None

    rows = last_stats[statistic_id]
    if not rows:
        return None

    row = rows[0]
    last_start = _as_utc_datetime(row.get("start"))
    if last_start is None:
        return None
    if row.get("sum") is not None:
        return (float(row["sum"]), last_start)
    value = row.get("state")
    if value is None:
        value = row.get("mean")
    if value is None:
        return (0.0, last_start)
    return (float(value), last_start)


async def _async_get_stats_map(
    hass: HomeAssistant,
    statistic_id: str,
    start: datetime,
    end: datetime | None = None,
) -> dict[datetime, dict[str, Any]]:
    """Load hour-period statistic rows into a start→row map."""
    try:
        result = await get_instance(hass).async_add_executor_job(
            statistics_during_period,
            hass,
            start,
            end,
            {statistic_id},
            "hour",
            None,
            {"state", "sum", "mean"},
        )
    except Exception as exc:
        _LOGGER.error("statistics_during_period failed for %s: %s", statistic_id, exc)
        raise

    rows = result.get(statistic_id) or []
    mapped: dict[datetime, dict[str, Any]] = {}
    for row in rows:
        row_start = _as_utc_datetime(row.get("start"))
        if row_start is None:
            continue
        state_raw = row.get("state")
        if state_raw is None:
            state_raw = row.get("mean")
        mapped[row_start] = {
            "start": row_start,
            "state": float(state_raw or 0.0),
            "sum": float(row.get("sum") or 0.0),
            "mean": float(row["mean"]) if row.get("mean") is not None else None,
        }
    return mapped


async def _async_anchor_sum(
    hass: HomeAssistant,
    statistic_id: str,
    changed_from: datetime,
) -> float:
    """Sum of the last recorder row strictly before changed_from."""
    # Prefer last overall row when it is before changed_from (exact, no year math).
    last = await _async_get_last_stats(hass, statistic_id)
    if last is None:
        return 0.0
    last_sum, last_start = last
    if last_start is None:
        return 0.0
    if last_start < changed_from:
        return last_sum

    # Otherwise load [epoch_floor, changed_from) and take the latest predecessor.
    lookback_start = datetime(2019, 1, 1, tzinfo=UTC)
    existing = await _async_get_stats_map(hass, statistic_id, lookback_start, changed_from)
    predecessors = [s for s in existing if s < changed_from]
    if not predecessors:
        return 0.0
    last_pred = max(predecessors)
    return float(existing[last_pred]["sum"])


async def async_wait_recorder_queue(hass: HomeAssistant) -> None:
    """Block until queued recorder tasks (including statistics imports) finish."""
    await hass.async_block_till_done()
    await get_instance(hass).async_block_till_done()
    await hass.async_block_till_done()


async def async_verify_statistic_states(
    hass: HomeAssistant,
    statistic_id: str,
    expected_states: dict[datetime, float],
    *,
    start: datetime,
    end: datetime,
) -> None:
    """Re-read hour rows and require exact state matches for expected starts."""
    if not expected_states:
        return
    mapped = await _async_get_stats_map(hass, statistic_id, start, end)
    for row_start, expected in expected_states.items():
        key = row_start.astimezone(UTC)
        if key not in mapped:
            raise RuntimeError(f"Recorder missing statistic row {statistic_id} @ {key.isoformat()}")
        actual = float(mapped[key]["state"])
        if abs(actual - expected) > 1e-9:
            raise RuntimeError(
                f"Recorder state mismatch {statistic_id} @ {key.isoformat()}: expected={expected} actual={actual}"
            )


async def async_ack_external_statistics(
    hass: HomeAssistant,
    *,
    statistic_id: str,
    expected_states: dict[datetime, float],
    start: datetime,
    end: datetime,
) -> None:
    """Wait for the recorder queue, then verify exact states were committed."""
    last_error: Exception | None = None
    for _ in range(8):
        await async_wait_recorder_queue(hass)
        try:
            await async_verify_statistic_states(
                hass,
                statistic_id,
                expected_states,
                start=start,
                end=end,
            )
            return
        except RuntimeError as exc:
            last_error = exc
            await asyncio.sleep(0.05)
    assert last_error is not None
    raise last_error


async def async_repair_suffix_sums(
    hass: HomeAssistant,
    account_key: str,
    dirty_from: datetime,
    *,
    account_id: str | None = None,
) -> None:
    """Rebuild cumulative sums from dirty_from using stored states only."""
    consumption_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_CONSUMPTION)
    cost_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_COST)
    last = await _async_get_last_stats(hass, consumption_id)
    if last is None or last[1] is None:
        return
    suffix_end = last[1]
    existing = await _async_get_stats_map(hass, consumption_id, dirty_from, suffix_end + timedelta(hours=1))
    if not existing:
        return
    anchor = await _async_anchor_sum(hass, consumption_id, dirty_from)
    running = anchor
    stats: list[dict] = []
    expected: dict[datetime, float] = {}
    for start in sorted(existing):
        if start < dirty_from:
            continue
        state = float(existing[start]["state"])
        running += state
        stats.append(_stat_row(start, state, running))
        expected[start] = state
    if stats:
        async_add_external_statistics(hass, _build_consumption_metadata(account_key, account_id), stats)
        await async_ack_external_statistics(
            hass,
            statistic_id=consumption_id,
            expected_states=expected,
            start=dirty_from,
            end=suffix_end + timedelta(hours=1),
        )
        _async_mirror_entity_statistics(
            hass,
            account_key=account_key,
            unique_suffix=ENTITY_UNIQUE_ENERGY,
            entity_metadata=_build_entity_consumption_metadata(
                "sensor._",
                _statistic_display_name(account_id, account_key),
            ),
            stats=stats,
        )

    cost_last = await _async_get_last_stats(hass, cost_id)
    if cost_last is None or cost_last[1] is None:
        return
    cost_existing = await _async_get_stats_map(hass, cost_id, dirty_from, cost_last[1] + timedelta(hours=1))
    if not cost_existing:
        return
    cost_anchor = await _async_anchor_sum(hass, cost_id, dirty_from)
    cost_running = cost_anchor
    cost_stats: list[dict] = []
    cost_expected: dict[datetime, float] = {}
    for start in sorted(cost_existing):
        if start < dirty_from:
            continue
        state = float(cost_existing[start]["state"])
        cost_running += state
        cost_stats.append(_stat_row(start, state, cost_running))
        cost_expected[start] = state
    if cost_stats:
        async_add_external_statistics(hass, _build_cost_metadata(account_key, account_id), cost_stats)
        await async_ack_external_statistics(
            hass,
            statistic_id=cost_id,
            expected_states=cost_expected,
            start=dirty_from,
            end=cost_last[1] + timedelta(hours=1),
        )
        _async_mirror_entity_statistics(
            hass,
            account_key=account_key,
            unique_suffix=ENTITY_UNIQUE_COST,
            entity_metadata=_build_entity_cost_metadata(
                "sensor._",
                _statistic_display_name(account_id, account_key, cost=True),
            ),
            stats=cost_stats,
        )

    # Temperature is mean-only; rewrite dirty window from stored states (no sum rebuild).
    temp_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_TEMPERATURE)
    temp_last = await _async_get_last_stats(hass, temp_id)
    if temp_last is not None and temp_last[1] is not None:
        temp_existing = await _async_get_stats_map(hass, temp_id, dirty_from, temp_last[1] + timedelta(hours=1))
        temp_stats = [
            _mean_stat_row(start, float(temp_existing[start]["state"]))
            for start in sorted(temp_existing)
            if start >= dirty_from
        ]
        if temp_stats:
            async_add_external_statistics(hass, _build_temperature_metadata(account_key, account_id), temp_stats)
            await async_ack_external_statistics(
                hass,
                statistic_id=temp_id,
                expected_states={row["start"].astimezone(UTC): float(row["state"]) for row in temp_stats},
                start=dirty_from,
                end=temp_last[1] + timedelta(hours=1),
            )
            _async_mirror_entity_statistics(
                hass,
                account_key=account_key,
                unique_suffix=ENTITY_UNIQUE_TEMPERATURE,
                entity_metadata=_build_entity_temperature_metadata(
                    "sensor._",
                    _statistic_display_name(account_id, account_key, temperature=True),
                ),
                stats=temp_stats,
            )


def _scrub_monthly_lumps_for_days(
    existing_map: dict[datetime, dict[str, Any]],
    overlay: dict[datetime, float],
    *,
    lump_min: float,
    daily_lump_min: float | None = None,
) -> int:
    """Zero coarse lumps on Pacific days that are receiving finer overlays.

    MONTHLY backfill parks a billing-period total on month-start; DAILY parks a
    whole day on midnight. When hourly rows later land on that day, keeping the
    lump double-counts (e.g. 28 kWh midnight daily + real hours, or 648 monthly).
    """
    if not existing_map or not overlay:
        return 0
    overlay_hours_by_day: dict[date, int] = defaultdict(int)
    for start in overlay:
        overlay_hours_by_day[start.astimezone(PGE_TZ).date()] += 1
    scrubbed = 0
    for start, row in existing_map.items():
        if start in overlay:
            continue
        try:
            state = float(row["state"])
        except (KeyError, TypeError, ValueError):
            continue
        day = start.astimezone(PGE_TZ).date()
        hours = overlay_hours_by_day.get(day, 0)
        if hours <= 0:
            continue
        # Monthly-sized always; daily-sized when a substantial hourly batch arrives.
        drop = state >= lump_min or (
            daily_lump_min is not None and state >= daily_lump_min and hours >= 12
        )
        if not drop:
            continue
        overlay[start] = 0.0
        scrubbed += 1
    return scrubbed


def _collision_zero_overlays(
    existing_map: dict[datetime, dict[str, Any]],
    *,
    lump_min: float,
) -> dict[datetime, float]:
    """Return start→0 overlays for monthly lumps that share a day with fine rows."""
    by_day: dict[date, list[tuple[datetime, float]]] = defaultdict(list)
    for start, row in existing_map.items():
        try:
            state = float(row["state"])
        except (KeyError, TypeError, ValueError):
            continue
        by_day[start.astimezone(PGE_TZ).date()].append((start, state))

    overlays: dict[datetime, float] = {}
    for rows in by_day.values():
        if len(rows) < 2:
            continue
        lumps = [r for r in rows if r[1] >= lump_min]
        fine = [r for r in rows if r[1] < lump_min]
        if not lumps or not fine:
            continue
        for start, _state in lumps:
            overlays[start] = 0.0
    return overlays


async def async_repair_monthly_hourly_collisions(
    hass: HomeAssistant,
    account_key: str,
    *,
    account_id: str | None = None,
    include_cost: bool = True,
) -> int:
    """Zero monthly lumps that coexist with hourly/daily rows; rebuild sums.

    Safe to run on every startup — no-op when the series is clean.
    """
    consumption_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_CONSUMPTION)
    last = await _async_get_last_stats(hass, consumption_id)
    if last is None or last[1] is None:
        return 0

    floor_start, _ = local_day_bounds(DEFAULT_HISTORY_FLOOR)
    existing = await _async_get_stats_map(
        hass,
        consumption_id,
        floor_start.astimezone(UTC),
        last[1] + timedelta(hours=1),
    )
    if not existing:
        return 0

    kwh_overlays = _collision_zero_overlays(existing, lump_min=MONTHLY_LUMP_MIN_KWH)
    cost_overlays: dict[datetime, float] = {}
    if include_cost:
        cost_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_COST)
        cost_last = await _async_get_last_stats(hass, cost_id)
        if cost_last is not None and cost_last[1] is not None:
            cost_existing = await _async_get_stats_map(
                hass,
                cost_id,
                floor_start.astimezone(UTC),
                cost_last[1] + timedelta(hours=1),
            )
            cost_overlays = _collision_zero_overlays(cost_existing, lump_min=MONTHLY_LUMP_MIN_COST)

    if not kwh_overlays and not cost_overlays:
        return 0

    cleared = len(kwh_overlays) + len(cost_overlays)
    dirty_candidates = list(kwh_overlays) + list(cost_overlays)
    dirty_from = min(dirty_candidates)

    if kwh_overlays:
        running = await _async_anchor_sum(hass, consumption_id, dirty_from)
        stats: list[dict] = []
        expected: dict[datetime, float] = {}
        for start in sorted(existing):
            if start < dirty_from:
                continue
            state = kwh_overlays[start] if start in kwh_overlays else float(existing[start]["state"])
            running += state
            stats.append(_stat_row(start, state, running))
            expected[start] = state
        if stats:
            async_add_external_statistics(hass, _build_consumption_metadata(account_key, account_id), stats)
            await async_ack_external_statistics(
                hass,
                statistic_id=consumption_id,
                expected_states=expected,
                start=dirty_from,
                end=last[1] + timedelta(hours=1),
            )
            _async_mirror_entity_statistics(
                hass,
                account_key=account_key,
                unique_suffix=ENTITY_UNIQUE_ENERGY,
                entity_metadata=_build_entity_consumption_metadata(
                    "sensor._",
                    _statistic_display_name(account_id, account_key),
                ),
                stats=stats,
            )

    if cost_overlays:
        cost_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_COST)
        cost_last = await _async_get_last_stats(hass, cost_id)
        assert cost_last is not None and cost_last[1] is not None
        cost_existing = await _async_get_stats_map(
            hass,
            cost_id,
            floor_start.astimezone(UTC),
            cost_last[1] + timedelta(hours=1),
        )
        cost_running = await _async_anchor_sum(hass, cost_id, dirty_from)
        cost_stats: list[dict] = []
        cost_expected: dict[datetime, float] = {}
        for start in sorted(cost_existing):
            if start < dirty_from:
                continue
            state = cost_overlays[start] if start in cost_overlays else float(cost_existing[start]["state"])
            cost_running += state
            cost_stats.append(_stat_row(start, state, cost_running))
            cost_expected[start] = state
        if cost_stats:
            async_add_external_statistics(hass, _build_cost_metadata(account_key, account_id), cost_stats)
            await async_ack_external_statistics(
                hass,
                statistic_id=cost_id,
                expected_states=cost_expected,
                start=dirty_from,
                end=cost_last[1] + timedelta(hours=1),
            )
            _async_mirror_entity_statistics(
                hass,
                account_key=account_key,
                unique_suffix=ENTITY_UNIQUE_COST,
                entity_metadata=_build_entity_cost_metadata(
                    "sensor._",
                    _statistic_display_name(account_id, account_key, cost=True),
                ),
                stats=cost_stats,
            )

    _LOGGER.warning(
        "Cleared %s monthly/hourly collision row(s) from %s (rebuilt sums from %s)",
        cleared,
        account_key[:8],
        dirty_from.isoformat(),
    )
    return cleared


async def async_import_with_baseline(
    hass: HomeAssistant,
    account_key: str,
    intervals: list[UsageInterval],
    include_cost: bool = True,
    *,
    account_id: str | None = None,
) -> int:
    """Upsert intervals and rebuild the affected cumulative-sum suffix."""
    if not intervals:
        return 0

    intervals = _dedupe_intervals(intervals)
    # Temperature is independent of cumulative kWh/cost sums — import even when
    # consumption/cost ack fails (dirty recorder / monthly vs daily collisions).
    try:
        changed_from = min(iv.start for iv in intervals).astimezone(UTC)
        changed_to = max(iv.start for iv in intervals).astimezone(UTC)

        consumption_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_CONSUMPTION)
        cost_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_COST)

        last = await _async_get_last_stats(hass, consumption_id)
        suffix_end = changed_to
        if last and last[1] is not None and last[1] > suffix_end:
            suffix_end = last[1]

        # Widen the read window to the Pacific day start so a month-start lump
        # earlier the same local day is visible for scrubbing.
        day_floor = min(iv.start.astimezone(PGE_TZ).date() for iv in intervals)
        day_start, _ = local_day_bounds(day_floor)
        read_from = min(changed_from, day_start.astimezone(UTC))

        existing_map = await _async_get_stats_map(hass, consumption_id, read_from, suffix_end + timedelta(hours=1))
        overlay_kwh = {iv.start.astimezone(UTC): float(iv.kwh) for iv in intervals}
        scrubbed = _scrub_monthly_lumps_for_days(
            existing_map,
            overlay_kwh,
            lump_min=MONTHLY_LUMP_MIN_KWH,
            daily_lump_min=DAILY_LUMP_MIN_KWH,
        )
        if scrubbed:
            _LOGGER.info(
                "Scrubbed %s monthly consumption lump(s) on days receiving finer intervals",
                scrubbed,
            )
            changed_from = min([changed_from, *overlay_kwh.keys()])

        # Merge: API overlays, keep existing later rows not in API batch.
        merged_starts = sorted(set(existing_map) | set(overlay_kwh))
        if not merged_starts:
            return 0

        anchor = await _async_anchor_sum(hass, consumption_id, changed_from)
        running = anchor
        consumption_stats: list[dict] = []
        for start in merged_starts:
            if start < changed_from:
                continue
            state = overlay_kwh[start] if start in overlay_kwh else float(existing_map[start]["state"])
            running += state
            consumption_stats.append(_stat_row(start, state, running))

        if consumption_stats:
            async_add_external_statistics(hass, _build_consumption_metadata(account_key, account_id), consumption_stats)
            await async_ack_external_statistics(
                hass,
                statistic_id=consumption_id,
                expected_states={row["start"].astimezone(UTC): float(row["state"]) for row in consumption_stats},
                start=changed_from,
                end=suffix_end + timedelta(hours=1),
            )
            _async_mirror_entity_statistics(
                hass,
                account_key=account_key,
                unique_suffix=ENTITY_UNIQUE_ENERGY,
                entity_metadata=_build_entity_consumption_metadata(
                    "sensor._",
                    _statistic_display_name(account_id, account_key),
                ),
                stats=consumption_stats,
            )

        if include_cost:
            cost_intervals = [iv for iv in intervals if iv.amount is not None]
            if cost_intervals:
                cost_changed_from = min(iv.start for iv in cost_intervals).astimezone(UTC)
                cost_changed_to = max(iv.start for iv in cost_intervals).astimezone(UTC)
                cost_day_floor = min(iv.start.astimezone(PGE_TZ).date() for iv in cost_intervals)
                cost_day_start, _ = local_day_bounds(cost_day_floor)
                cost_read_from = min(cost_changed_from, cost_day_start.astimezone(UTC))
                cost_last = await _async_get_last_stats(hass, cost_id)
                cost_suffix_end = cost_changed_to
                if cost_last and cost_last[1] is not None and cost_last[1] > cost_suffix_end:
                    cost_suffix_end = cost_last[1]

                cost_existing = await _async_get_stats_map(
                    hass,
                    cost_id,
                    cost_read_from,
                    cost_suffix_end + timedelta(hours=1),
                )
                overlay_cost = {
                    iv.start.astimezone(UTC): float(iv.amount) for iv in cost_intervals if iv.amount is not None
                }
                cost_scrubbed = _scrub_monthly_lumps_for_days(
                    cost_existing,
                    overlay_cost,
                    lump_min=MONTHLY_LUMP_MIN_COST,
                    daily_lump_min=DAILY_LUMP_MIN_COST,
                )
                if cost_scrubbed:
                    _LOGGER.info(
                        "Scrubbed %s monthly cost lump(s) on days receiving finer intervals",
                        cost_scrubbed,
                    )
                    cost_changed_from = min([cost_changed_from, *overlay_cost.keys()])
                cost_starts = sorted(set(cost_existing) | set(overlay_cost))
                cost_anchor = await _async_anchor_sum(hass, cost_id, cost_changed_from)
                cost_running = cost_anchor
                cost_stats: list[dict] = []
                for start in cost_starts:
                    if start < cost_changed_from:
                        continue
                    state = overlay_cost[start] if start in overlay_cost else float(cost_existing[start]["state"])
                    cost_running += state
                    cost_stats.append(_stat_row(start, state, cost_running))
                if cost_stats:
                    async_add_external_statistics(hass, _build_cost_metadata(account_key, account_id), cost_stats)
                    await async_ack_external_statistics(
                        hass,
                        statistic_id=cost_id,
                        expected_states={row["start"].astimezone(UTC): float(row["state"]) for row in cost_stats},
                        start=cost_changed_from,
                        end=cost_suffix_end + timedelta(hours=1),
                    )
                    _async_mirror_entity_statistics(
                        hass,
                        account_key=account_key,
                        unique_suffix=ENTITY_UNIQUE_COST,
                        entity_metadata=_build_entity_cost_metadata(
                            "sensor._",
                            _statistic_display_name(account_id, account_key, cost=True),
                        ),
                        stats=cost_stats,
                    )
    finally:
        await _async_import_temperature_overlay(
            hass,
            account_key,
            intervals,
            account_id=account_id,
        )

    return len(intervals)


async def _async_import_temperature_overlay(
    hass: HomeAssistant,
    account_key: str,
    intervals: list[UsageInterval],
    *,
    account_id: str | None = None,
) -> None:
    """Upsert PGE outdoor temperature (°F). Mean-only; no cumulative sum."""
    temp_intervals = [iv for iv in intervals if iv.temperature is not None]
    if not temp_intervals:
        return

    temp_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_TEMPERATURE)
    changed_from = min(iv.start for iv in temp_intervals).astimezone(UTC)
    changed_to = max(iv.start for iv in temp_intervals).astimezone(UTC)
    last = await _async_get_last_stats(hass, temp_id)
    suffix_end = changed_to
    if last and last[1] is not None and last[1] > suffix_end:
        suffix_end = last[1]

    existing = await _async_get_stats_map(
        hass,
        temp_id,
        changed_from,
        suffix_end + timedelta(hours=1),
    )
    overlay = {iv.start.astimezone(UTC): float(iv.temperature) for iv in temp_intervals if iv.temperature is not None}
    starts = sorted(set(existing) | set(overlay))
    stats: list[dict] = []
    for start in starts:
        if start < changed_from:
            continue
        value = overlay[start] if start in overlay else float(existing[start]["state"])
        stats.append(_mean_stat_row(start, value))
    if not stats:
        return
    async_add_external_statistics(hass, _build_temperature_metadata(account_key, account_id), stats)
    await async_ack_external_statistics(
        hass,
        statistic_id=temp_id,
        expected_states={row["start"].astimezone(UTC): float(row["state"]) for row in stats},
        start=changed_from,
        end=suffix_end + timedelta(hours=1),
    )
    _async_mirror_entity_statistics(
        hass,
        account_key=account_key,
        unique_suffix=ENTITY_UNIQUE_TEMPERATURE,
        entity_metadata=_build_entity_temperature_metadata(
            "sensor._",
            _statistic_display_name(account_id, account_key, temperature=True),
        ),
        stats=stats,
    )


async def async_refresh_lifetime_totals(
    hass: HomeAssistant,
    account_key: str,
) -> tuple[float | None, float | None, float | None]:
    """Return (energy_sum_kwh, cost_sum_usd, latest_temperature_f) from recorder."""
    energy = await _async_get_last_stats(hass, _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_CONSUMPTION))
    cost = await _async_get_last_stats(hass, _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_COST))
    temp = await _async_get_last_stats(hass, _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_TEMPERATURE))
    return (
        energy[0] if energy else None,
        cost[0] if cost else None,
        temp[0] if temp else None,
    )


async def async_import_statistics(
    hass: HomeAssistant,
    account_key: str,
    intervals: list[UsageInterval],
    include_cost: bool = True,
    *,
    account_id: str | None = None,
) -> int:
    return await async_import_with_baseline(
        hass, account_key, intervals, include_cost=include_cost, account_id=account_id
    )


def setup_statistics_sensors(
    hass: HomeAssistant,
    account_key: str,
) -> None:
    consumption_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_CONSUMPTION)
    cost_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_COST)
    temperature_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_TEMPERATURE)
    energy_entity = async_resolve_sensor_entity_id(hass, account_key, ENTITY_UNIQUE_ENERGY)
    cost_entity = async_resolve_sensor_entity_id(hass, account_key, ENTITY_UNIQUE_COST)
    temp_entity = async_resolve_sensor_entity_id(hass, account_key, ENTITY_UNIQUE_TEMPERATURE)
    _LOGGER.debug(
        "Statistic IDs: consumption=%s, cost=%s, temperature=%s; entity mirrors: energy=%s, cost=%s, temperature=%s",
        consumption_id,
        cost_id,
        temperature_id,
        energy_entity,
        cost_entity,
        temp_entity,
    )


# Backward-compatible name used by older call sites.
async_setup_statistics_sensors = setup_statistics_sensors
