"""Dual-publish billing / programs series into Home Assistant statistics.

Every graphable billing numeric series is written both as an external
``pge_energy:<account_key>_*`` statistic (source ``pge_energy``) and mirrored
onto the matching ``sensor.pge_*`` recorder statistic_id, reusing the helpers
from :mod:`.statistics` so the History / Statistics / Energy pickers behave the
same as consumption / cost / temperature.

Two shapes are used:

* **mean** series (account balance, amount due, last payment amount, bill
  period average temperature, YTD program savings) — one non-cumulative row per
  billing snapshot timestamp. Mean series are **external-only** (no entity
  mirror): a recorder-tracked sensor (``state_class=MEASUREMENT``) must not
  receive snapshot-stamped entity rows because HA Core's ``compile_statistics``
  does a plain INSERT for that hour and logs
  ``UNIQUE constraint failed: statistics.metadata_id, statistics.start_ts``
  ("Blocked attempt to insert duplicated statistic rows") against the
  pre-seeded slot. Monetary mean sensors additionally use ``state_class=None``
  and HA raises ``STATE_CLASS_REMOVED_ISSUE`` whenever entity recorder metadata
  exists.
* **sum** series (bill amount, bill kWh, payment amount) — one cumulative row
  per ledger event, upserted by hour so re-syncing the paged feed is
  idempotent.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
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
from homeassistant.const import UnitOfEnergy, UnitOfTemperature
from homeassistant.core import HomeAssistant

from .billing_models import AccountSnapshot, LedgerEvent, LedgerEventType, ProgramsSnapshot
from .const import (
    DOMAIN,
    ENTITY_UNIQUE_ACCOUNT_BALANCE,
    ENTITY_UNIQUE_AMOUNT_DUE,
    ENTITY_UNIQUE_BILL_AVG_TEMPERATURE,
    ENTITY_UNIQUE_LAST_PAYMENT_AMOUNT,
    ENTITY_UNIQUE_LIFETIME_BILLED,
    ENTITY_UNIQUE_LIFETIME_PAYMENTS,
    ENTITY_UNIQUE_YTD_PROGRAM_SAVINGS,
    STATISTIC_ID_SUFFIX_ACCOUNT_BALANCE,
    STATISTIC_ID_SUFFIX_AMOUNT_DUE,
    STATISTIC_ID_SUFFIX_BILL_AMOUNT,
    STATISTIC_ID_SUFFIX_BILL_AVG_TEMPERATURE,
    STATISTIC_ID_SUFFIX_BILL_KWH,
    STATISTIC_ID_SUFFIX_LAST_PAYMENT_AMOUNT,
    STATISTIC_ID_SUFFIX_PAYMENT_AMOUNT,
    STATISTIC_ID_SUFFIX_YTD_PROGRAM_SAVINGS,
)
from .options import pge_display_name

# Reuse the module-private helpers from statistics.py rather than re-deriving
# statistic ids / row shapes. They are underscore-prefixed but stable, and the
# plan explicitly calls for importing them here.
from .statistics import (  # noqa: PLC2701
    _as_utc_datetime,
    _async_mirror_entity_statistics,
    _get_statistic_id,
    _mean_stat_row,
    _stat_row,
    async_resolve_sensor_entity_id,
)
from .store import ImportStoreData, async_save_import_state

# Monetary mean sensors use state_class=None; entity mirrors recreate
# STATE_CLASS_REMOVED_ISSUE until their recorder metadata is cleared once.
_MONETARY_MEAN_ENTITY_SUFFIXES = (
    ENTITY_UNIQUE_ACCOUNT_BALANCE,
    ENTITY_UNIQUE_AMOUNT_DUE,
    ENTITY_UNIQUE_LAST_PAYMENT_AMOUNT,
    ENTITY_UNIQUE_YTD_PROGRAM_SAVINGS,
)

_LOGGER = logging.getLogger(__name__)

# Matches the lookback floor used by statistics.py (_async_anchor_sum).
_STATS_FLOOR = datetime(2019, 1, 1, tzinfo=UTC)

_USD = "USD"


def _billing_base_name(account_id: str | None, account_key: str) -> str:
    return pge_display_name(account_id) if account_id else pge_display_name(account_key[:8])


def _floor_hour(value: datetime) -> datetime:
    """External statistics require whole-hour starts in UTC."""
    aware = _as_utc_datetime(value) or datetime.now(UTC)
    return aware.replace(minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# Metadata builders
# ---------------------------------------------------------------------------


def _external_mean_metadata(stat_id: str, name: str, *, unit: str | None, unit_class: str | None) -> StatisticMetaData:
    return StatisticMetaData(
        has_mean=True,
        mean_type=StatisticMeanType.ARITHMETIC,
        has_sum=False,
        name=name,
        source=DOMAIN,
        statistic_id=stat_id,
        unit_class=unit_class,
        unit_of_measurement=unit,
    )


def _external_sum_metadata(stat_id: str, name: str, *, unit: str | None, unit_class: str | None) -> StatisticMetaData:
    return StatisticMetaData(
        has_mean=False,
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=name,
        source=DOMAIN,
        statistic_id=stat_id,
        unit_class=unit_class,
        unit_of_measurement=unit,
    )


def _entity_sum_metadata(entity_id: str, name: str, *, unit: str | None, unit_class: str | None) -> StatisticMetaData:
    return StatisticMetaData(
        has_mean=False,
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=name,
        source=RECORDER_DOMAIN,
        statistic_id=entity_id,
        unit_class=unit_class,
        unit_of_measurement=unit,
    )


# ---------------------------------------------------------------------------
# Recorder read helpers (mirror statistics.py patterns, kept local)
# ---------------------------------------------------------------------------


async def _async_load_sum_states(hass: HomeAssistant, statistic_id: str) -> dict[datetime, float]:
    """Load existing hourly rows into a start→state map for a sum series."""
    try:
        result = await get_instance(hass).async_add_executor_job(
            statistics_during_period,
            hass,
            _STATS_FLOOR,
            None,
            {statistic_id},
            "hour",
            None,
            {"state", "sum"},
        )
    except Exception as exc:  # pragma: no cover - recorder failure is soft
        _LOGGER.debug("statistics_during_period failed for %s: %s", statistic_id, exc)
        return {}
    rows = result.get(statistic_id) or []
    out: dict[datetime, float] = {}
    for row in rows:
        start = _as_utc_datetime(row.get("start"))
        if start is None:
            continue
        state = row.get("state")
        if state is None:
            state = row.get("sum")
        out[start] = float(state or 0.0)
    return out


async def _async_last_sum(hass: HomeAssistant, statistic_id: str) -> float | None:
    """Return the most recent cumulative ``sum`` for a series, or None."""
    try:
        last = await get_instance(hass).async_add_executor_job(
            get_last_statistics,
            hass,
            1,
            statistic_id,
            True,
            {"sum"},
        )
    except Exception as exc:  # pragma: no cover - recorder failure is soft
        _LOGGER.debug("get_last_statistics failed for %s: %s", statistic_id, exc)
        return None
    if not last or statistic_id not in last:
        return None
    rows = last[statistic_id]
    if not rows:
        return None
    value = rows[0].get("sum")
    return float(value) if value is not None else None


# ---------------------------------------------------------------------------
# Import primitives
# ---------------------------------------------------------------------------


def _import_mean_point(
    hass: HomeAssistant,
    account_key: str,
    account_id: str | None,
    *,
    suffix: str,
    value: float | None,
    when: datetime,
    unit: str | None,
    unit_class: str | None,
    label: str,
) -> None:
    """Write one external-only mean row (never mirrored to an entity statistic).

    Mean series must stay external-only: snapshot-stamped rows pre-seed the
    current-hour slot of a recorder-tracked sensor, and HA Core's
    ``compile_statistics`` plain INSERT for that hour then logs
    ``UNIQUE constraint failed: statistics.metadata_id, statistics.start_ts``
    ("Blocked attempt to insert duplicated statistic rows").
    """
    if value is None:
        return
    stat_id = _get_statistic_id(account_key, suffix)
    row = _mean_stat_row(_floor_hour(when), float(value))
    name = f"{_billing_base_name(account_id, account_key)} {label}"
    async_add_external_statistics(
        hass,
        _external_mean_metadata(stat_id, name, unit=unit, unit_class=unit_class),
        [row],
    )


async def _async_import_sum_series(
    hass: HomeAssistant,
    account_key: str,
    account_id: str | None,
    *,
    suffix: str,
    entity_suffix: str | None,
    points: dict[datetime, float],
    unit: str | None,
    unit_class: str | None,
    label: str,
) -> None:
    """Upsert cumulative sum rows (by hour) and rebuild running totals."""
    if not points:
        return
    stat_id = _get_statistic_id(account_key, suffix)
    existing = await _async_load_sum_states(hass, stat_id)
    merged = dict(existing)
    for start, state in points.items():
        merged[_floor_hour(start)] = float(state)

    running = 0.0
    rows: list[dict[str, Any]] = []
    for start in sorted(merged):
        running += merged[start]
        rows.append(_stat_row(start, merged[start], running))
    if not rows:
        return

    name = f"{_billing_base_name(account_id, account_key)} {label}"
    async_add_external_statistics(
        hass,
        _external_sum_metadata(stat_id, name, unit=unit, unit_class=unit_class),
        rows,
    )
    if entity_suffix is not None:
        _async_mirror_entity_statistics(
            hass,
            account_key=account_key,
            unique_suffix=entity_suffix,
            entity_metadata=_entity_sum_metadata("sensor._", name, unit=unit, unit_class=unit_class),
            stats=rows,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def async_import_billing_snapshot(
    hass: HomeAssistant,
    account_key: str,
    account_id: str | None,
    snapshot: AccountSnapshot,
    when: datetime,
) -> None:
    """Write mean rows for the account summary + latest-bill sample.

    Current-bill amount / kWh are surfaced directly on their sensors from the
    snapshot rather than written here, because the ``_bill_amount`` /
    ``_bill_kwh`` statistic ids are cumulative *sum* series owned by
    :func:`async_import_ledger_events` and cannot double as mean series.
    """
    # Both series currently use billInfo.amountDue — the portal balance banner
    # is not a separate GraphQL field yet. Keep both entity/stat IDs stable so a
    # distinct balance source can land later without breaking History graphs.
    _import_mean_point(
        hass,
        account_key,
        account_id,
        suffix=STATISTIC_ID_SUFFIX_ACCOUNT_BALANCE,
        value=snapshot.amount_due,
        when=when,
        unit=_USD,
        unit_class=None,
        label="account balance",
    )
    _import_mean_point(
        hass,
        account_key,
        account_id,
        suffix=STATISTIC_ID_SUFFIX_AMOUNT_DUE,
        value=snapshot.amount_due,
        when=when,
        unit=_USD,
        unit_class=None,
        label="amount due",
    )
    _import_mean_point(
        hass,
        account_key,
        account_id,
        suffix=STATISTIC_ID_SUFFIX_LAST_PAYMENT_AMOUNT,
        value=snapshot.last_payment_amount,
        when=when,
        unit=_USD,
        unit_class=None,
        label="last payment amount",
    )
    if snapshot.bill is not None:
        # External-only: the sensor is recorder-tracked (state_class=MEASUREMENT)
        # and HA Core compiles its hourly rows natively. Mirroring the current
        # sync-hour slot here collides with the next compile INSERT (recorder
        # logs "Blocked attempt to insert duplicated statistic rows").
        _import_mean_point(
            hass,
            account_key,
            account_id,
            suffix=STATISTIC_ID_SUFFIX_BILL_AVG_TEMPERATURE,
            value=snapshot.bill.avg_temperature_f,
            when=when,
            unit=UnitOfTemperature.FAHRENHEIT,
            unit_class="temperature",
            label="bill average temperature",
        )


async def async_import_ledger_events(
    hass: HomeAssistant,
    account_key: str,
    account_id: str | None,
    events: list[LedgerEvent],
) -> None:
    """Import BILL / PAYMENT ledger rows into cumulative sum series.

    BILL rows contribute ``amount_due`` → ``_bill_amount`` and ``kwh`` →
    ``_bill_kwh``; PAYMENT rows contribute ``abs(amount_paid)`` →
    ``_payment_amount``. Rows are aggregated by hour so multiple same-hour
    events in a page combine rather than clobber each other.
    """
    if not events:
        return

    bill_amount: dict[datetime, float] = {}
    bill_kwh: dict[datetime, float] = {}
    payment_amount: dict[datetime, float] = {}

    for event in events:
        start = _floor_hour(event.date)
        if event.event_type is LedgerEventType.BILL:
            if event.amount_due is not None:
                bill_amount[start] = bill_amount.get(start, 0.0) + float(event.amount_due)
            if event.kwh is not None:
                bill_kwh[start] = bill_kwh.get(start, 0.0) + float(event.kwh)
        elif event.event_type is LedgerEventType.PAYMENT:
            if event.amount_paid is not None:
                payment_amount[start] = payment_amount.get(start, 0.0) + abs(float(event.amount_paid))

    await _async_import_sum_series(
        hass,
        account_key,
        account_id,
        suffix=STATISTIC_ID_SUFFIX_BILL_AMOUNT,
        entity_suffix=ENTITY_UNIQUE_LIFETIME_BILLED,
        points=bill_amount,
        unit=_USD,
        unit_class=None,
        label="lifetime billed",
    )
    await _async_import_sum_series(
        hass,
        account_key,
        account_id,
        suffix=STATISTIC_ID_SUFFIX_BILL_KWH,
        entity_suffix=None,
        points=bill_kwh,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        unit_class="energy",
        label="billed energy",
    )
    await _async_import_sum_series(
        hass,
        account_key,
        account_id,
        suffix=STATISTIC_ID_SUFFIX_PAYMENT_AMOUNT,
        entity_suffix=ENTITY_UNIQUE_LIFETIME_PAYMENTS,
        points=payment_amount,
        unit=_USD,
        unit_class=None,
        label="lifetime payments",
    )


async def async_import_programs_metrics(
    hass: HomeAssistant,
    account_key: str,
    account_id: str | None,
    programs: ProgramsSnapshot,
    when: datetime,
) -> None:
    """Write a mean YTD program-savings sample from flex-load earnings."""
    _import_mean_point(
        hass,
        account_key,
        account_id,
        suffix=STATISTIC_ID_SUFFIX_YTD_PROGRAM_SAVINGS,
        value=programs.ytd_flex_load_earnings,
        when=when,
        unit=_USD,
        unit_class=None,
        label="YTD program savings",
    )


async def async_refresh_billing_lifetime_totals(
    hass: HomeAssistant,
    account_key: str,
) -> tuple[float | None, float | None]:
    """Return (lifetime_payments_usd, lifetime_billed_usd) from the recorder."""
    payments = await _async_last_sum(hass, _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_PAYMENT_AMOUNT))
    billed = await _async_last_sum(hass, _get_statistic_id(account_key, STATISTIC_ID_SUFFIX_BILL_AMOUNT))
    return payments, billed


async def async_cleanup_orphaned_billing_entity_mirrors(
    hass: HomeAssistant,
    *,
    entry_id: str,
    account_key: str,
    store: ImportStoreData,
) -> bool:
    """Clear entity statistics for the four monetary mean sensors once per entry.

    HA raises ``STATE_CLASS_REMOVED_ISSUE`` whenever recorder metadata exists for
    an entity whose live state is numeric with ``state_class=None``. Dropping
    ``entity_suffix`` stops new mirrors; this clears existing metadata so repairs
    actually resolve. Returns True when cleanup ran (or was already done).
    """
    if store.billing_mirror_cleanup_done:
        return True

    entity_ids = [
        eid
        for suffix in _MONETARY_MEAN_ENTITY_SUFFIXES
        if (eid := async_resolve_sensor_entity_id(hass, account_key, suffix)) is not None
    ]
    if entity_ids:
        done = asyncio.Event()

        def _on_done() -> None:
            done.set()

        try:
            get_instance(hass).async_clear_statistics(entity_ids, on_done=_on_done)
            try:
                await asyncio.wait_for(done.wait(), timeout=60.0)
            except TimeoutError:
                _LOGGER.warning(
                    "Timed out waiting for billing mirror statistics clear for %s",
                    account_key[:8],
                )
                # Still mark done so a stuck recorder does not retry forever.
        except Exception as exc:  # noqa: BLE001 — soft-fail; do not block setup
            _LOGGER.warning(
                "Failed to clear orphaned billing entity statistics for %s: %s",
                account_key[:8],
                exc,
            )
            return False
        _LOGGER.info(
            "Cleared orphaned monetary mean entity statistics for %s: %s",
            account_key[:8],
            ", ".join(entity_ids),
        )
    else:
        _LOGGER.debug(
            "No monetary mean entity ids to clear for %s (entities not registered yet)",
            account_key[:8],
        )

    store.billing_mirror_cleanup_done = True
    await async_save_import_state(hass, entry_id, store)
    return True


async def async_clear_bill_avg_temp_entity_statistics(
    hass: HomeAssistant,
    *,
    entry_id: str,
    account_key: str,
    store: ImportStoreData,
) -> bool:
    """Clear the bill-period average temperature entity statistics once.

    The bill avg temperature mean series is external-only; HA Core compiles the
    sensor's own hourly rows natively. Old mirror rows written at billing-sync
    hours pre-seeded the not-yet-compiled slot and triggered the recorder
    ``UNIQUE constraint failed: statistics.metadata_id, statistics.start_ts``
    traceback every compile cycle. This clears those stale rows once (so a
    purge/repack recompile cannot re-trigger the collision) and lets HA rebuild
    native rows. Returns True when cleanup ran (or was already done).
    """
    if store.bill_avg_temp_mirror_cleanup_done:
        return True

    entity_id = async_resolve_sensor_entity_id(hass, account_key, ENTITY_UNIQUE_BILL_AVG_TEMPERATURE)
    if entity_id is None:
        store.bill_avg_temp_mirror_cleanup_done = True
        await async_save_import_state(hass, entry_id, store)
        return True

    done = asyncio.Event()

    def _on_done() -> None:
        done.set()

    cleared = False
    try:
        get_instance(hass).async_clear_statistics([entity_id], on_done=_on_done)
        try:
            await asyncio.wait_for(done.wait(), timeout=60.0)
            cleared = True
        except TimeoutError:
            _LOGGER.warning(
                "Timed out waiting for bill avg temperature statistics clear for %s",
                account_key[:8],
            )
            # Still mark done so a stuck recorder does not retry forever.
    except Exception as exc:  # noqa: BLE001 — soft-fail; do not block setup
        _LOGGER.warning(
            "Failed to clear bill avg temperature entity statistics for %s: %s",
            account_key[:8],
            exc,
        )
        return False
    if cleared:
        _LOGGER.info(
            "Cleared bill-period average temperature entity statistics for %s: %s",
            account_key[:8],
            entity_id,
        )

    store.bill_avg_temp_mirror_cleanup_done = True
    await async_save_import_state(hass, entry_id, store)
    return True
