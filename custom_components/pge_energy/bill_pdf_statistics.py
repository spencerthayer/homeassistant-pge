"""Import PDF-derived bill statement metrics into Home Assistant statistics.

Each safe, reconciled bill contributes one statement-dated point per present
metric into external ``pge_energy:<account_key>_bill_pdf_*`` sum series. These
ids are distinct from GraphQL billing statistics and are rebuilt idempotently
from the canonical normalized Store records.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models.statistics import StatisticMetaData
from homeassistant.components.recorder.statistics import (
    StatisticMeanType,
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant

from .bill_pdf_models import NormalizedBillPdf
from .const import (
    DOMAIN,
    STATISTIC_ID_SUFFIX_BILL_PDF_AMOUNT_DUE,
    STATISTIC_ID_SUFFIX_BILL_PDF_BALANCE_FORWARD,
    STATISTIC_ID_SUFFIX_BILL_PDF_BASIC_CHARGE,
    STATISTIC_ID_SUFFIX_BILL_PDF_DISTRIBUTION_CHARGE,
    STATISTIC_ID_SUFFIX_BILL_PDF_ENERGY_DELIVERY_CHARGES,
    STATISTIC_ID_SUFFIX_BILL_PDF_ENERGY_USE_CHARGE,
    STATISTIC_ID_SUFFIX_BILL_PDF_GREEN_FUTURE_CHARGE,
    STATISTIC_ID_SUFFIX_BILL_PDF_LOCAL_TAX,
    STATISTIC_ID_SUFFIX_BILL_PDF_PAYMENT_RECEIVED,
    STATISTIC_ID_SUFFIX_BILL_PDF_POWER_COST_ADJUSTMENT,
    STATISTIC_ID_SUFFIX_BILL_PDF_PREVIOUS_AMOUNT_DUE,
    STATISTIC_ID_SUFFIX_BILL_PDF_PROGRAM_CHARGES,
    STATISTIC_ID_SUFFIX_BILL_PDF_PUBLIC_PURPOSE_CHARGE,
    STATISTIC_ID_SUFFIX_BILL_PDF_REGULATORY_ADJUSTMENTS,
    STATISTIC_ID_SUFFIX_BILL_PDF_STATE_PASS_THROUGHS,
    STATISTIC_ID_SUFFIX_BILL_PDF_TAXES_AND_INVESTMENTS,
    STATISTIC_ID_SUFFIX_BILL_PDF_TOTAL_KWH,
    STATISTIC_ID_SUFFIX_BILL_PDF_TRANSMISSION_CHARGE,
)
from .options import pge_display_name
from .statistics import (  # noqa: PLC2701
    _as_utc_datetime,
    _get_statistic_id,
    _stat_row,
    async_ack_external_statistics,
)
from .time_util import local_day_bounds

_LOGGER = logging.getLogger(__name__)

_USD = "USD"
_STATS_FLOOR = datetime(2019, 1, 1, tzinfo=UTC)

BILL_PDF_METRIC_SUFFIXES: dict[str, str] = {
    "amount_due": STATISTIC_ID_SUFFIX_BILL_PDF_AMOUNT_DUE,
    "total_kwh": STATISTIC_ID_SUFFIX_BILL_PDF_TOTAL_KWH,
    "payment_received": STATISTIC_ID_SUFFIX_BILL_PDF_PAYMENT_RECEIVED,
    "balance_forward": STATISTIC_ID_SUFFIX_BILL_PDF_BALANCE_FORWARD,
    "previous_amount_due": STATISTIC_ID_SUFFIX_BILL_PDF_PREVIOUS_AMOUNT_DUE,
    "energy_delivery_charges": STATISTIC_ID_SUFFIX_BILL_PDF_ENERGY_DELIVERY_CHARGES,
    "basic_charge": STATISTIC_ID_SUFFIX_BILL_PDF_BASIC_CHARGE,
    "energy_use_charge": STATISTIC_ID_SUFFIX_BILL_PDF_ENERGY_USE_CHARGE,
    "transmission_charge": STATISTIC_ID_SUFFIX_BILL_PDF_TRANSMISSION_CHARGE,
    "distribution_charge": STATISTIC_ID_SUFFIX_BILL_PDF_DISTRIBUTION_CHARGE,
    "power_cost_adjustment": STATISTIC_ID_SUFFIX_BILL_PDF_POWER_COST_ADJUSTMENT,
    "regulatory_adjustments": STATISTIC_ID_SUFFIX_BILL_PDF_REGULATORY_ADJUSTMENTS,
    "state_pass_throughs": STATISTIC_ID_SUFFIX_BILL_PDF_STATE_PASS_THROUGHS,
    "program_charges": STATISTIC_ID_SUFFIX_BILL_PDF_PROGRAM_CHARGES,
    "green_future_charge": STATISTIC_ID_SUFFIX_BILL_PDF_GREEN_FUTURE_CHARGE,
    "taxes_and_investments": STATISTIC_ID_SUFFIX_BILL_PDF_TAXES_AND_INVESTMENTS,
    "local_tax": STATISTIC_ID_SUFFIX_BILL_PDF_LOCAL_TAX,
    "public_purpose_charge": STATISTIC_ID_SUFFIX_BILL_PDF_PUBLIC_PURPOSE_CHARGE,
}

_BILL_PDF_METRIC_LABELS: dict[str, str] = {
    "amount_due": "bill PDF amount due",
    "total_kwh": "bill PDF total kWh",
    "payment_received": "bill PDF payment received",
    "balance_forward": "bill PDF balance forward",
    "previous_amount_due": "bill PDF previous amount due",
    "energy_delivery_charges": "bill PDF energy delivery charges",
    "basic_charge": "bill PDF basic charge",
    "energy_use_charge": "bill PDF energy use charge",
    "transmission_charge": "bill PDF transmission charge",
    "distribution_charge": "bill PDF distribution charge",
    "power_cost_adjustment": "bill PDF power cost adjustment",
    "regulatory_adjustments": "bill PDF regulatory adjustments",
    "state_pass_throughs": "bill PDF state pass-throughs",
    "program_charges": "bill PDF program charges",
    "green_future_charge": "bill PDF Green Future charge",
    "taxes_and_investments": "bill PDF taxes and investments",
    "local_tax": "bill PDF local tax",
    "public_purpose_charge": "bill PDF public purpose charge",
}


def get_bill_pdf_statistic_suffix(metric_key: str) -> str | None:
    """Return the external statistic suffix for a PDF metric key, if mapped."""
    return BILL_PDF_METRIC_SUFFIXES.get(metric_key)


def statement_timestamp(statement_date: date) -> datetime:
    """Pacific midnight on ``statement_date`` as a whole UTC hour."""
    start_utc, _ = local_day_bounds(statement_date)
    return _floor_hour(start_utc)


def _floor_hour(value: datetime) -> datetime:
    """External statistics require whole-hour starts in UTC."""
    aware = _as_utc_datetime(value) or datetime.now(UTC)
    return aware.replace(minute=0, second=0, microsecond=0)


def _bill_pdf_base_name(account_id: str | None, account_key: str) -> str:
    return pge_display_name(account_id) if account_id else pge_display_name(account_key[:8])


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


def _metric_value(record: NormalizedBillPdf, metric_key: str) -> Decimal | None:
    if metric_key == "amount_due":
        return record.amount_due
    if metric_key == "total_kwh":
        return record.total_kwh
    metric = record.metrics.get(metric_key)
    return metric.value if metric is not None else None


def _collect_metric_points(
    records: list[NormalizedBillPdf],
    metric_key: str,
) -> dict[datetime, float]:
    """Build statement-hour → value points for one metric from safe records."""
    points: dict[datetime, float] = {}
    for record in records:
        if not record.safe_to_publish:
            continue
        value = _metric_value(record, metric_key)
        if value is None:
            continue
        points[statement_timestamp(record.statement_date)] = float(value)
    return points


async def _async_import_bill_pdf_sum_series(
    hass: HomeAssistant,
    account_key: str,
    account_id: str | None,
    *,
    metric_key: str,
    suffix: str,
    points: dict[datetime, float],
    unit: str | None,
    unit_class: str | None,
) -> None:
    """Rebuild one cumulative PDF sum series and acknowledge recorder writes."""
    if not points:
        return

    stat_id = _get_statistic_id(account_key, suffix)
    existing = await _async_load_sum_states(hass, stat_id)
    merged = dict(existing)
    desired: dict[datetime, float] = {}
    for start, state in points.items():
        hour = _floor_hour(start)
        desired[hour] = float(state)
        merged[hour] = float(state)

    for stale_start in set(existing) - set(desired):
        merged.pop(stale_start, None)

    running = 0.0
    rows: list[dict[str, Any]] = []
    expected: dict[datetime, float] = {}
    for start in sorted(merged):
        running += merged[start]
        rows.append(_stat_row(start, merged[start], running))
        expected[start] = merged[start]
    if not rows:
        return

    label = _BILL_PDF_METRIC_LABELS.get(metric_key, metric_key.replace("_", " "))
    name = f"{_bill_pdf_base_name(account_id, account_key)} {label}"
    metadata = _external_sum_metadata(stat_id, name, unit=unit, unit_class=unit_class)
    async_add_external_statistics(hass, metadata, rows)
    await async_ack_external_statistics(
        hass,
        statistic_id=stat_id,
        metadata=metadata,
        stats=rows,
        expected_states=expected,
        start=min(expected),
        end=max(expected) + timedelta(hours=1),
    )


async def async_import_bill_pdf_statistics(
    hass: HomeAssistant,
    account_key: str,
    account_id: str | None,
    records: list[NormalizedBillPdf],
) -> None:
    """Rebuild all present PDF-derived external statistic series from Store records."""
    safe_records = [record for record in records if record.safe_to_publish]
    if not safe_records:
        return

    for metric_key, suffix in BILL_PDF_METRIC_SUFFIXES.items():
        points = _collect_metric_points(safe_records, metric_key)
        if not points:
            continue
        if metric_key == "total_kwh":
            unit = UnitOfEnergy.KILO_WATT_HOUR
            unit_class = "energy"
        else:
            unit = _USD
            unit_class = None
        await _async_import_bill_pdf_sum_series(
            hass,
            account_key,
            account_id,
            metric_key=metric_key,
            suffix=suffix,
            points=points,
            unit=unit,
            unit_class=unit_class,
        )
