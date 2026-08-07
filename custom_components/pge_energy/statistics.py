from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.const import DOMAIN as RECORDER_DOMAIN
from homeassistant.components.recorder.models.statistics import StatisticMetaData
from homeassistant.components.recorder.statistics import (
    StatisticMeanType,
    async_add_external_statistics,
    get_last_statistics,
    get_metadata,
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
    ENTITY_UNIQUE_COMPENSATION,
    ENTITY_UNIQUE_COST,
    ENTITY_UNIQUE_ENERGY,
    ENTITY_UNIQUE_RETURN,
    ENTITY_UNIQUE_TEMPERATURE,
    MONTHLY_LUMP_MIN_COST,
    MONTHLY_LUMP_MIN_KWH,
    STATISTIC_ID_SUFFIX_COMPENSATION,
    STATISTIC_ID_SUFFIX_CONSUMPTION,
    STATISTIC_ID_SUFFIX_COST,
    STATISTIC_ID_SUFFIX_RETURN,
    STATISTIC_ID_SUFFIX_TEMPERATURE,
    STATISTICS_ACK_WRITE_ATTEMPTS,
)
from .models import UsageInterval, UsageResolution
from .options import pge_display_name
from .store import ImportStoreData, async_save_import_state
from .time_util import PGE_TZ, local_day_bounds
from .usage_direction import split_signed_usage

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImportBaselineResult:
    """Result of ``async_import_with_baseline``.

    Compares equal to ``imported`` (int) so existing call sites/tests that check
    ``== N`` keep working. ``cost_failed_days`` lists Pacific local dates whose
    cost ack failed after consumption succeeded (non-fatal).
    """

    imported: int
    cost_failed_days: tuple[str, ...] = field(default_factory=tuple)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, int):
            return self.imported == other
        if isinstance(other, ImportBaselineResult):
            return self.imported == other.imported and self.cost_failed_days == other.cost_failed_days
        return NotImplemented

    def __int__(self) -> int:
        return self.imported


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
    return_energy: bool = False,
    compensation: bool = False,
) -> str:
    base = pge_display_name(account_id) if account_id else pge_display_name(account_key[:8])
    if cost:
        return f"{base} cost"
    if compensation:
        return f"{base} compensation"
    if return_energy:
        return f"{base} return"
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


def _build_return_metadata(account_key: str, account_id: str | None = None) -> StatisticMetaData:
    stat_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_RETURN)
    return StatisticMetaData(
        has_mean=False,
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=_statistic_display_name(account_id, account_key, return_energy=True),
        source=DOMAIN,
        statistic_id=stat_id,
        unit_class="energy",
        unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    )


def _build_compensation_metadata(account_key: str, account_id: str | None = None) -> StatisticMetaData:
    stat_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_COMPENSATION)
    return StatisticMetaData(
        has_mean=False,
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=_statistic_display_name(account_id, account_key, compensation=True),
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


def _build_entity_return_metadata(entity_id: str, name: str) -> StatisticMetaData:
    return _build_entity_consumption_metadata(entity_id, name)


def _build_entity_compensation_metadata(entity_id: str, name: str) -> StatisticMetaData:
    return _build_entity_cost_metadata(entity_id, name)


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
    """Copy the same hourly rows onto the sensor's recorder statistic_id.

    Only mirror rows HA Core has already compiled. ``compile_statistics``
    finalizes hour H ~5-10 min after it closes (the 5-min slot at H+55), and a
    mirror row written before that plain-INSERTs collides on
    ``UNIQUE(statistics.metadata_id, statistics.start_ts)``, which HA logs as
    "Blocked attempt to insert duplicated statistic rows". Exclude the current
    hour and the last two closed hours; the row is picked up on the next cycle
    once it ages past the cutoff. The newest compiled slot at any poll time is
    the last-closed hour, so the cutoff leaves >=~1h of margin for recorder
    backlog.
    """
    if not stats:
        return
    cutoff = dt_util.utcnow().replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
    stats = [s for s in stats if _as_utc_datetime(s["start"]) < cutoff]
    if not stats:
        _LOGGER.info(
            "Skip entity stats mirror for %s_%s — newest rows not yet finalized by compile_statistics",
            account_key[:8],
            unique_suffix,
        )
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
    """Build non-negative grid-import statistics from signed PGE intervals."""
    stats = []
    for iv in sorted(intervals, key=lambda x: x.start):
        if iv.kwh is None:
            continue
        split = split_signed_usage(iv.kwh, iv.amount, resolution=iv.resolution)
        stats.append(
            {
                "start": iv.start,
                "state": float(split.consumption),
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


def _build_return_statistics(intervals: list[UsageInterval]) -> list[dict]:
    """Build non-negative grid-export statistics from signed hourly intervals."""
    stats = []
    for iv in sorted(intervals, key=lambda x: x.start):
        if iv.kwh is None or iv.resolution != UsageResolution.HOURLY:
            continue
        split = split_signed_usage(iv.kwh, iv.amount, resolution=iv.resolution)
        if split.return_kwh <= 0:
            continue
        stats.append(
            {
                "start": iv.start,
                "state": float(split.return_kwh),
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
        if iv.kwh is None or iv.amount is None:
            continue
        split = split_signed_usage(iv.kwh, iv.amount, resolution=iv.resolution)
        if split.cost is None:
            continue
        stats.append(
            {
                "start": iv.start,
                "state": float(split.cost),
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


def _build_compensation_statistics(intervals: list[UsageInterval]) -> list[dict]:
    stats = []
    for iv in sorted(intervals, key=lambda x: x.start):
        if iv.kwh is None or iv.amount is None or iv.resolution != UsageResolution.HOURLY:
            continue
        split = split_signed_usage(iv.kwh, iv.amount, resolution=iv.resolution)
        if split.compensation is None or split.compensation <= 0:
            continue
        stats.append(
            {
                "start": iv.start,
                "state": float(split.compensation),
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
        if iv.kwh is None:
            continue
        split = split_signed_usage(iv.kwh, iv.amount, resolution=iv.resolution)
        if use_cost:
            if split.cost is None:
                continue
            state = float(split.cost)
        else:
            state = float(split.consumption)
        running_sum += state
        stats.append(_stat_row(iv.start, state, running_sum))

    return stats


def _directional_overlays(
    intervals: list[UsageInterval],
) -> tuple[dict[datetime, float], dict[datetime, float], dict[datetime, float], dict[datetime, float]]:
    """Map UTC starts to non-negative consumption/return/cost/compensation states."""
    consumption: dict[datetime, float] = {}
    returns: dict[datetime, float] = {}
    costs: dict[datetime, float] = {}
    comps: dict[datetime, float] = {}
    for iv in intervals:
        if iv.kwh is None:
            continue
        start = iv.start.astimezone(UTC)
        split = split_signed_usage(iv.kwh, iv.amount, resolution=iv.resolution)
        consumption[start] = float(split.consumption)
        if iv.resolution == UsageResolution.HOURLY:
            returns[start] = float(split.return_kwh)
            if split.compensation is not None:
                comps[start] = float(split.compensation)
        if split.cost is not None:
            costs[start] = float(split.cost)
    return consumption, returns, costs, comps


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
    """Block until queued recorder tasks (including statistics imports) finish.

    Only wait on the recorder instance — never ``hass.async_block_till_done()``.
    That helper waits for every tracked HA task and deadlocks when a scheduled
    poll holds ``import_lock`` while a long-lived backfill task is also tracked
    and waiting on the same lock.
    """
    await get_instance(hass).async_block_till_done()


async def async_verify_statistic_states(
    hass: HomeAssistant,
    statistic_id: str,
    expected_states: dict[datetime, float],
    *,
    start: datetime,
    end: datetime,
) -> None:
    """Re-read hour rows and require exact state matches for expected starts.

    Distinguishes a missing row (write never landed) from a present row with a
    stale ``state`` (dropped/partial update or infrastructure fault).
    """
    if not expected_states:
        return
    mapped = await _async_get_stats_map(hass, statistic_id, start, end)
    for row_start, expected in expected_states.items():
        key = row_start.astimezone(UTC)
        if key not in mapped:
            raise RuntimeError(
                f"Recorder row absent {statistic_id} @ {key.isoformat()} "
                f"(expected state={expected}; write did not land)"
            )
        raw_state = mapped[key].get("state")
        if raw_state is None:
            raise RuntimeError(
                f"Recorder row present but state is None {statistic_id} @ {key.isoformat()} (expected state={expected})"
            )
        actual = float(raw_state)
        if abs(actual - expected) > 1e-9:
            raise RuntimeError(
                f"Recorder state stale {statistic_id} @ {key.isoformat()}: expected={expected} actual={actual}"
            )


async def _async_log_ack_failure_diagnostics(
    hass: HomeAssistant,
    statistic_id: str,
    expected_states: Mapping[datetime, float],
    last_error: BaseException,
) -> None:
    """Log mismatch samples + recorder metadata after the final failed ack."""
    samples: list[str] = []
    for start, expected in list(expected_states.items())[:5]:
        samples.append(f"{start.astimezone(UTC).isoformat()} expected={expected}")
    meta_summary = "unavailable"
    try:
        meta_map = await get_instance(hass).async_add_executor_job(
            partial(get_metadata, hass, statistic_ids={statistic_id})
        )
        entry = meta_map.get(statistic_id) if isinstance(meta_map, dict) else None
        # get_metadata returns {statistic_id: (id, StatisticMetaData-like)}
        meta = entry[1] if isinstance(entry, tuple) and len(entry) > 1 else entry
        if isinstance(meta, dict):
            meta_summary = (
                f"unit={meta.get('unit_of_measurement')!r} "
                f"unit_class={meta.get('unit_class')!r} "
                f"has_sum={meta.get('has_sum')!r} "
                f"mean_type={meta.get('mean_type')!r}"
            )
        elif meta is not None:
            meta_summary = repr(meta)
    except Exception as meta_exc:  # noqa: BLE001 — diagnostics must not mask the ack error
        meta_summary = f"lookup failed: {meta_exc}"
    _LOGGER.error(
        "Statistics ack failed for %s after %s write attempt(s): %s; "
        "samples=%s; recorder_metadata=%s. "
        "Persistent mismatch usually means the recorder dropped the import "
        "(check for 'Cannot operate on a closed database' / 'Unexpected exception "
        "when updating statistics' and consider recorder.purge with repack).",
        statistic_id,
        STATISTICS_ACK_WRITE_ATTEMPTS,
        last_error,
        samples,
        meta_summary,
    )


async def async_ack_external_statistics(
    hass: HomeAssistant,
    *,
    statistic_id: str,
    metadata: StatisticMetaData | dict[str, Any],
    stats: list[dict],
    expected_states: dict[datetime, float],
    start: datetime,
    end: datetime,
) -> None:
    """Wait for the recorder queue, verify states, and re-issue the write on mismatch.

    Re-reading alone cannot converge when ``import_statistics`` dropped the job
    (HA swallows SQLAlchemyError inside ``_update_statistics`` and still returns
    success). Each failed verify re-queues ``async_add_external_statistics``.
    """
    if not expected_states:
        return
    last_error: Exception | None = None
    for attempt in range(STATISTICS_ACK_WRITE_ATTEMPTS):
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
            if attempt + 1 < STATISTICS_ACK_WRITE_ATTEMPTS:
                async_add_external_statistics(hass, metadata, stats)
                await asyncio.sleep(0.05)
    assert last_error is not None
    await _async_log_ack_failure_diagnostics(hass, statistic_id, expected_states, last_error)
    raise last_error


def _expected_from_stats(stats: list[dict]) -> dict[datetime, float]:
    return {row["start"].astimezone(UTC): float(row["state"]) for row in stats}


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
        cons_meta = _build_consumption_metadata(account_key, account_id)
        async_add_external_statistics(hass, cons_meta, stats)
        await async_ack_external_statistics(
            hass,
            statistic_id=consumption_id,
            metadata=cons_meta,
            stats=stats,
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
        cost_meta = _build_cost_metadata(account_key, account_id)
        async_add_external_statistics(hass, cost_meta, cost_stats)
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
        await async_ack_external_statistics(
            hass,
            statistic_id=cost_id,
            metadata=cost_meta,
            stats=cost_stats,
            expected_states=cost_expected,
            start=dirty_from,
            end=cost_last[1] + timedelta(hours=1),
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
            temp_meta = _build_temperature_metadata(account_key, account_id)
            async_add_external_statistics(hass, temp_meta, temp_stats)
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
            await async_ack_external_statistics(
                hass,
                statistic_id=temp_id,
                metadata=temp_meta,
                stats=temp_stats,
                expected_states=_expected_from_stats(temp_stats),
                start=dirty_from,
                end=temp_last[1] + timedelta(hours=1),
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
        drop = state >= lump_min or (daily_lump_min is not None and state >= daily_lump_min and hours >= 12)
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
            cons_meta = _build_consumption_metadata(account_key, account_id)
            async_add_external_statistics(hass, cons_meta, stats)
            await async_ack_external_statistics(
                hass,
                statistic_id=consumption_id,
                metadata=cons_meta,
                stats=stats,
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
            cost_meta = _build_cost_metadata(account_key, account_id)
            async_add_external_statistics(hass, cost_meta, cost_stats)
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
            await async_ack_external_statistics(
                hass,
                statistic_id=cost_id,
                metadata=cost_meta,
                stats=cost_stats,
                expected_states=cost_expected,
                start=dirty_from,
                end=cost_last[1] + timedelta(hours=1),
            )

    _LOGGER.warning(
        "Cleared %s monthly/hourly collision row(s) from %s (rebuilt sums from %s)",
        cleared,
        account_key[:8],
        dirty_from.isoformat(),
    )
    return cleared


def _local_dates_from_starts(starts: list[datetime] | set[datetime]) -> tuple[str, ...]:
    return tuple(sorted({start.astimezone(PGE_TZ).date().isoformat() for start in starts}))


async def _async_upsert_cumulative_overlay(
    hass: HomeAssistant,
    *,
    account_key: str,
    account_id: str | None,
    statistic_suffix: str,
    entity_unique_suffix: str,
    overlay: dict[datetime, float],
    metadata_builder,
    entity_metadata_builder,
    display_name: str,
    lump_min: float | None,
    daily_lump_min: float | None,
    hard_ack: bool,
) -> tuple[str, ...]:
    """Merge ``overlay`` into a cumulative external (+ mirrored) series.

    Returns local dates whose ack failed (empty when ``hard_ack`` raises).
    """
    if not overlay:
        return ()

    statistic_id = _get_statistic_id(account_key, statistic_suffix)
    changed_from = min(overlay)
    changed_to = max(overlay)
    last = await _async_get_last_stats(hass, statistic_id)
    suffix_end = changed_to
    if last and last[1] is not None and last[1] > suffix_end:
        suffix_end = last[1]

    day_floor = min(start.astimezone(PGE_TZ).date() for start in overlay)
    day_start, _ = local_day_bounds(day_floor)
    read_from = min(changed_from, day_start.astimezone(UTC))
    existing_map = await _async_get_stats_map(hass, statistic_id, read_from, suffix_end + timedelta(hours=1))

    if lump_min is not None and daily_lump_min is not None:
        scrubbed = _scrub_monthly_lumps_for_days(
            existing_map,
            overlay,
            lump_min=lump_min,
            daily_lump_min=daily_lump_min,
        )
        if scrubbed:
            _LOGGER.info(
                "Scrubbed %s monthly %s lump(s) on days receiving finer intervals",
                scrubbed,
                statistic_suffix.lstrip("_"),
            )
            changed_from = min([changed_from, *overlay.keys()])

    merged_starts = sorted(set(existing_map) | set(overlay))
    if not merged_starts:
        return ()

    anchor = await _async_anchor_sum(hass, statistic_id, changed_from)
    running = anchor
    stats: list[dict] = []
    for start in merged_starts:
        if start < changed_from:
            continue
        # Clamp legacy negative states when replaying through an existing series.
        if start in overlay:
            state = max(0.0, float(overlay[start]))
        else:
            state = max(0.0, float(existing_map[start]["state"]))
        running += state
        stats.append(_stat_row(start, state, running))

    if not stats:
        return ()

    meta = metadata_builder(account_key, account_id)
    async_add_external_statistics(hass, meta, stats)
    _async_mirror_entity_statistics(
        hass,
        account_key=account_key,
        unique_suffix=entity_unique_suffix,
        entity_metadata=entity_metadata_builder("sensor._", display_name),
        stats=stats,
    )
    try:
        await async_ack_external_statistics(
            hass,
            statistic_id=statistic_id,
            metadata=meta,
            stats=stats,
            expected_states=_expected_from_stats(stats),
            start=changed_from,
            end=suffix_end + timedelta(hours=1),
        )
    except RuntimeError:
        if hard_ack:
            raise
        return _local_dates_from_starts(list(overlay))
    return ()


async def async_import_with_baseline(
    hass: HomeAssistant,
    account_key: str,
    intervals: list[UsageInterval],
    include_cost: bool = True,
    *,
    account_id: str | None = None,
) -> ImportBaselineResult:
    """Upsert intervals and rebuild the affected cumulative-sum suffix.

    Consumption ack failure propagates. Cost/return/compensation/temperature ack
    failures are soft: days are listed in ``cost_failed_days`` for retry, and the
    poll can clear ``dirty_from``. Coarse DAILY/MONTHLY rows never invent return
    or compensation — only HOURLY signed rows populate those series.
    """
    if not intervals:
        return ImportBaselineResult(0)

    intervals = _dedupe_intervals(intervals)
    soft_failed: set[str] = set()
    overlay_kwh, overlay_return, overlay_cost, overlay_comp = _directional_overlays(intervals)

    # Temperature is independent of cumulative kWh/cost sums — import even when
    # consumption/cost ack fails (dirty recorder / monthly vs daily collisions).
    try:
        if overlay_kwh:
            await _async_upsert_cumulative_overlay(
                hass,
                account_key=account_key,
                account_id=account_id,
                statistic_suffix=STATISTIC_ID_SUFFIX_CONSUMPTION,
                entity_unique_suffix=ENTITY_UNIQUE_ENERGY,
                overlay=overlay_kwh,
                metadata_builder=_build_consumption_metadata,
                entity_metadata_builder=_build_entity_consumption_metadata,
                display_name=_statistic_display_name(account_id, account_key),
                lump_min=MONTHLY_LUMP_MIN_KWH,
                daily_lump_min=DAILY_LUMP_MIN_KWH,
                hard_ack=True,
            )

        if overlay_return:
            failed = await _async_upsert_cumulative_overlay(
                hass,
                account_key=account_key,
                account_id=account_id,
                statistic_suffix=STATISTIC_ID_SUFFIX_RETURN,
                entity_unique_suffix=ENTITY_UNIQUE_RETURN,
                overlay=overlay_return,
                metadata_builder=_build_return_metadata,
                entity_metadata_builder=_build_entity_return_metadata,
                display_name=_statistic_display_name(account_id, account_key, return_energy=True),
                lump_min=None,
                daily_lump_min=None,
                hard_ack=False,
            )
            if failed:
                soft_failed.update(failed)
                _LOGGER.error(
                    "Return statistics ack failed (non-fatal); marking days failed: %s",
                    ", ".join(failed) or "(none)",
                )

        if include_cost and overlay_cost:
            failed = await _async_upsert_cumulative_overlay(
                hass,
                account_key=account_key,
                account_id=account_id,
                statistic_suffix=STATISTIC_ID_SUFFIX_COST,
                entity_unique_suffix=ENTITY_UNIQUE_COST,
                overlay=overlay_cost,
                metadata_builder=_build_cost_metadata,
                entity_metadata_builder=_build_entity_cost_metadata,
                display_name=_statistic_display_name(account_id, account_key, cost=True),
                lump_min=MONTHLY_LUMP_MIN_COST,
                daily_lump_min=DAILY_LUMP_MIN_COST,
                hard_ack=False,
            )
            if failed:
                soft_failed.update(failed)
                _LOGGER.error(
                    "Cost statistics ack failed (non-fatal); marking days failed: %s",
                    ", ".join(failed) or "(none)",
                )

        if include_cost and overlay_comp:
            failed = await _async_upsert_cumulative_overlay(
                hass,
                account_key=account_key,
                account_id=account_id,
                statistic_suffix=STATISTIC_ID_SUFFIX_COMPENSATION,
                entity_unique_suffix=ENTITY_UNIQUE_COMPENSATION,
                overlay=overlay_comp,
                metadata_builder=_build_compensation_metadata,
                entity_metadata_builder=_build_entity_compensation_metadata,
                display_name=_statistic_display_name(account_id, account_key, compensation=True),
                lump_min=None,
                daily_lump_min=None,
                hard_ack=False,
            )
            if failed:
                soft_failed.update(failed)
                _LOGGER.error(
                    "Compensation statistics ack failed (non-fatal); marking days failed: %s",
                    ", ".join(failed) or "(none)",
                )
    finally:
        soft_failed.update(
            await _async_import_temperature_overlay(
                hass,
                account_key,
                intervals,
                account_id=account_id,
            )
        )

    return ImportBaselineResult(len(intervals), tuple(sorted(soft_failed)))


async def _async_import_temperature_overlay(
    hass: HomeAssistant,
    account_key: str,
    intervals: list[UsageInterval],
    *,
    account_id: str | None = None,
) -> set[str]:
    """Upsert PGE outdoor temperature (°F). Mean-only; no cumulative sum.

    Returns Pacific local dates whose ack failed (empty on success / no data).
    """
    temp_intervals = [iv for iv in intervals if iv.temperature is not None]
    if not temp_intervals:
        return set()

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
        return set()
    temp_meta = _build_temperature_metadata(account_key, account_id)
    async_add_external_statistics(hass, temp_meta, stats)
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
    try:
        await async_ack_external_statistics(
            hass,
            statistic_id=temp_id,
            metadata=temp_meta,
            stats=stats,
            expected_states=_expected_from_stats(stats),
            start=changed_from,
            end=suffix_end + timedelta(hours=1),
        )
    except RuntimeError as exc:
        failed = set(_local_dates_from_starts(list(overlay)))
        _LOGGER.error(
            "Temperature statistics ack failed (non-fatal); marking days failed: %s (%s)",
            ", ".join(sorted(failed)) or "(none)",
            exc,
        )
        return failed
    return set()


async def async_refresh_lifetime_totals(
    hass: HomeAssistant,
    account_key: str,
) -> tuple[float | None, float | None, float | None, float | None, float | None]:
    """Return (energy, cost, temp, return_kwh, compensation_usd) from recorder."""
    energy = await _async_get_last_stats(hass, _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_CONSUMPTION))
    cost = await _async_get_last_stats(hass, _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_COST))
    temp = await _async_get_last_stats(hass, _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_TEMPERATURE))
    returned = await _async_get_last_stats(hass, _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_RETURN))
    compensation = await _async_get_last_stats(
        hass, _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_COMPENSATION)
    )
    return (
        energy[0] if energy else None,
        cost[0] if cost else None,
        temp[0] if temp else None,
        returned[0] if returned else None,
        compensation[0] if compensation else None,
    )


def _looks_fine_grained(state: float) -> bool:
    """Heuristic: monthly lumps are huge; signed hourly export stays well below."""
    return abs(state) < MONTHLY_LUMP_MIN_KWH


async def async_migrate_signed_usage_split(
    hass: HomeAssistant,
    account_key: str,
    store: ImportStoreData,
    *,
    account_id: str | None = None,
    entry_id: str | None = None,
) -> bool:
    """One-time split of negative fine-grained consumption/cost into return/compensation.

    Returns True when migration is complete (or already done). False means retry later.
    """
    if store.signed_usage_split_migration_done:
        return True

    floor_start, _ = local_day_bounds(DEFAULT_HISTORY_FLOOR)
    consumption_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_CONSUMPTION)
    cost_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_COST)
    try:
        consumption_map = await _async_get_stats_map(hass, consumption_id, floor_start.astimezone(UTC))
        cost_map = await _async_get_stats_map(hass, cost_id, floor_start.astimezone(UTC))
    except Exception as exc:
        _LOGGER.warning("Signed-usage migration read failed for %s: %s", account_key[:8], exc)
        return False

    cons_overlay: dict[datetime, float] = {}
    return_overlay: dict[datetime, float] = {}
    for start, row in consumption_map.items():
        state = float(row["state"])
        if state >= 0 or not _looks_fine_grained(state):
            continue
        cons_overlay[start] = 0.0
        return_overlay[start] = abs(state)

    cost_overlay: dict[datetime, float] = {}
    comp_overlay: dict[datetime, float] = {}
    for start, row in cost_map.items():
        state = float(row["state"])
        if state >= 0 or not _looks_fine_grained(state):
            continue
        cost_overlay[start] = 0.0
        comp_overlay[start] = abs(state)

    if not cons_overlay and not cost_overlay:
        store.signed_usage_split_migration_done = True
        if entry_id:
            await async_save_import_state(hass, entry_id, store, critical=False)
        return True

    try:
        if cons_overlay:
            await _async_upsert_cumulative_overlay(
                hass,
                account_key=account_key,
                account_id=account_id,
                statistic_suffix=STATISTIC_ID_SUFFIX_CONSUMPTION,
                entity_unique_suffix=ENTITY_UNIQUE_ENERGY,
                overlay=cons_overlay,
                metadata_builder=_build_consumption_metadata,
                entity_metadata_builder=_build_entity_consumption_metadata,
                display_name=_statistic_display_name(account_id, account_key),
                lump_min=None,
                daily_lump_min=None,
                hard_ack=True,
            )
        if return_overlay:
            failed = await _async_upsert_cumulative_overlay(
                hass,
                account_key=account_key,
                account_id=account_id,
                statistic_suffix=STATISTIC_ID_SUFFIX_RETURN,
                entity_unique_suffix=ENTITY_UNIQUE_RETURN,
                overlay=return_overlay,
                metadata_builder=_build_return_metadata,
                entity_metadata_builder=_build_entity_return_metadata,
                display_name=_statistic_display_name(account_id, account_key, return_energy=True),
                lump_min=None,
                daily_lump_min=None,
                hard_ack=False,
            )
            if failed:
                _LOGGER.error("Signed-usage return migration ack failed for %s", account_key[:8])
                return False
        if cost_overlay:
            failed = await _async_upsert_cumulative_overlay(
                hass,
                account_key=account_key,
                account_id=account_id,
                statistic_suffix=STATISTIC_ID_SUFFIX_COST,
                entity_unique_suffix=ENTITY_UNIQUE_COST,
                overlay=cost_overlay,
                metadata_builder=_build_cost_metadata,
                entity_metadata_builder=_build_entity_cost_metadata,
                display_name=_statistic_display_name(account_id, account_key, cost=True),
                lump_min=None,
                daily_lump_min=None,
                hard_ack=False,
            )
            if failed:
                _LOGGER.error("Signed-usage cost migration ack failed for %s", account_key[:8])
                return False
        if comp_overlay:
            failed = await _async_upsert_cumulative_overlay(
                hass,
                account_key=account_key,
                account_id=account_id,
                statistic_suffix=STATISTIC_ID_SUFFIX_COMPENSATION,
                entity_unique_suffix=ENTITY_UNIQUE_COMPENSATION,
                overlay=comp_overlay,
                metadata_builder=_build_compensation_metadata,
                entity_metadata_builder=_build_entity_compensation_metadata,
                display_name=_statistic_display_name(account_id, account_key, compensation=True),
                lump_min=None,
                daily_lump_min=None,
                hard_ack=False,
            )
            if failed:
                _LOGGER.error("Signed-usage compensation migration ack failed for %s", account_key[:8])
                return False
    except Exception as exc:
        _LOGGER.warning("Signed-usage migration write failed for %s: %s", account_key[:8], exc)
        return False

    store.signed_usage_split_migration_done = True
    if entry_id:
        await async_save_import_state(hass, entry_id, store, critical=False)
    _LOGGER.info(
        "Signed-usage migration complete for %s (%s consumption, %s cost rows)",
        account_key[:8],
        len(cons_overlay),
        len(cost_overlay),
    )
    return True


async def async_import_statistics(
    hass: HomeAssistant,
    account_key: str,
    intervals: list[UsageInterval],
    include_cost: bool = True,
    *,
    account_id: str | None = None,
) -> ImportBaselineResult:
    return await async_import_with_baseline(
        hass, account_key, intervals, include_cost=include_cost, account_id=account_id
    )


def setup_statistics_sensors(
    hass: HomeAssistant,
    account_key: str,
) -> None:
    consumption_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_CONSUMPTION)
    return_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_RETURN)
    cost_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_COST)
    compensation_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_COMPENSATION)
    temperature_id = _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_TEMPERATURE)
    energy_entity = async_resolve_sensor_entity_id(hass, account_key, ENTITY_UNIQUE_ENERGY)
    return_entity = async_resolve_sensor_entity_id(hass, account_key, ENTITY_UNIQUE_RETURN)
    cost_entity = async_resolve_sensor_entity_id(hass, account_key, ENTITY_UNIQUE_COST)
    compensation_entity = async_resolve_sensor_entity_id(hass, account_key, ENTITY_UNIQUE_COMPENSATION)
    temp_entity = async_resolve_sensor_entity_id(hass, account_key, ENTITY_UNIQUE_TEMPERATURE)
    _LOGGER.debug(
        "Statistic IDs: consumption=%s, return=%s, cost=%s, compensation=%s, temperature=%s; "
        "entity mirrors: energy=%s, return=%s, cost=%s, compensation=%s, temperature=%s",
        consumption_id,
        return_id,
        cost_id,
        compensation_id,
        temperature_id,
        energy_entity,
        return_entity,
        cost_entity,
        compensation_entity,
        temp_entity,
    )


# Backward-compatible name used by older call sites.
async_setup_statistics_sensors = setup_statistics_sensors
