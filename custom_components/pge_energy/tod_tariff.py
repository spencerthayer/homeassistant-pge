"""Effective-dated tariff catalogs for local TOD and Basic comparison estimates.

Pure functions and immutable models — no Home Assistant imports.

Each catalog is a chronologically sorted list of rows with an ``effective_from``
date (Pacific local).  Lookup selects the newest row whose effective date is
on or before the queried timestamp's Pacific date.

Public API:
    - :class:`TodTariffRow` / :class:`BasicComparisonRow`
    - :func:`tod_rate_card_at` / :func:`basic_comparison_rate_at`
    - :func:`merge_validated_catalog`
    - :func:`serialize_tariff_catalogs`
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from .time_util import PGE_TZ

# ---------------------------------------------------------------------------
# Immutable row models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceInfo:
    """Provenance for a single tariff row."""

    url: str
    title: str
    effective_date: str
    observed_at: str
    sha256: str
    parser_version: int = 1


@dataclass(frozen=True, slots=True)
class TodTariffRow:
    """One effective-dated set of bundled TOD variable rates (USD/kWh).

    Rates include transmission + distribution + energy + Schedule 125.
    """

    effective_from: str  # YYYY-MM-DD (Pacific local)
    off_peak: float
    mid_peak: float
    on_peak: float
    source: SourceInfo
    component_basis: str = "Schedule 7 base + Schedule 125"
    exclusions: str = (
        "Excludes taxes, fixed charges, discounts, Income-Qualified Bill Discount, "
        "outdoor area lighting, and other non-modeled items."
    )

    def __post_init__(self) -> None:
        for attr in ("off_peak", "mid_peak", "on_peak"):
            v = getattr(self, attr)
            if not isinstance(v, (int, float)) or not (0 < v < 10):
                raise ValueError(f"{attr} must be a positive finite rate < $10/kWh, got {v!r}")


@dataclass(frozen=True, slots=True)
class BasicComparisonRow:
    """One effective-dated Basic comparison rate (USD/kWh).

    ``rate`` = Schedule 7 BASE RATE + Schedule 125, matching the published
    TOD basis.  Not a full effective Schedule 7 rate.
    """

    effective_from: str  # YYYY-MM-DD (Pacific local)
    base_rate: float
    schedule_125: float
    rate: float  # base_rate + schedule_125
    source: SourceInfo
    component_basis: str = "Schedule 7 base + Schedule 125"
    exclusions: str = (
        "Excludes Schedule 102 BPA credit tiers, taxes, fixed charges, discounts, "
        "Income-Qualified Bill Discount, and other common adjustments."
    )

    def __post_init__(self) -> None:
        if not isinstance(self.base_rate, (int, float)) or self.base_rate < 0:
            raise ValueError(f"base_rate must be non-negative, got {self.base_rate!r}")
        if not isinstance(self.schedule_125, (int, float)) or self.schedule_125 < 0:
            raise ValueError(f"schedule_125 must be non-negative, got {self.schedule_125!r}")
        if self.base_rate > 2.0:
            raise ValueError(f"base_rate exceeds sanity limit (>2.0 $/kWh), got {self.base_rate!r}")
        if self.schedule_125 > 2.0:
            raise ValueError(f"schedule_125 exceeds sanity limit (>2.0 $/kWh), got {self.schedule_125!r}")
        expected = round(self.base_rate + self.schedule_125, 6)
        if abs(self.rate - expected) > 0.0001:
            raise ValueError(
                f"rate ({self.rate}) must equal base_rate ({self.base_rate}) "
                f"+ schedule_125 ({self.schedule_125}) = {expected}"
            )


# ---------------------------------------------------------------------------
# Bundled seed rows (verified 2026-08-16)
# ---------------------------------------------------------------------------

_TOD_SEED_ROWS: list[TodTariffRow] = [
    TodTariffRow(
        effective_from="2026-04-01",
        off_peak=0.0901,
        mid_peak=0.1689,
        on_peak=0.4365,
        source=SourceInfo(
            url="https://assets.ctfassets.net/416ywc1laqmd/5dwmGyRIAextaJClWmn80k/c0e3dae29b0f163e2227e0125a03d4fe/Update_04_01_26.pdf",
            title="PGE April 1 tariff update",
            effective_date="2026-04-01",
            observed_at="2026-08-16T00:00:00Z",
            sha256=hashlib.sha256(b"bundled-tod-2026-04-01").hexdigest(),
            parser_version=1,
        ),
    ),
    TodTariffRow(
        effective_from="2026-07-08",
        off_peak=0.0893,
        mid_peak=0.1670,
        on_peak=0.4313,
        source=SourceInfo(
            url="https://portlandgeneral.com/about/info/pricing-plans/time-of-day",
            title="PGE Time of Day pricing page (July 8)",
            effective_date="2026-07-08",
            observed_at="2026-08-16T00:00:00Z",
            sha256=hashlib.sha256(b"bundled-tod-2026-07-08").hexdigest(),
            parser_version=1,
        ),
    ),
]

_BASIC_SEED_ROWS: list[BasicComparisonRow] = [
    BasicComparisonRow(
        effective_from="2026-04-01",
        base_rate=0.11945,
        schedule_125=0.05685,
        rate=0.17630,
        source=SourceInfo(
            url="https://assets.ctfassets.net/416ywc1laqmd/7qcBwObijoHCwzn4woPRvQ/890abbe871e9e4f10dfec61fd2722585/2026-4-1-standard-service-schedules.pdf",
            title="April standard-service price summary",
            effective_date="2026-04-01",
            observed_at="2026-08-16T00:00:00Z",
            sha256=hashlib.sha256(b"bundled-basic-2026-04-01").hexdigest(),
            parser_version=1,
        ),
    ),
    BasicComparisonRow(
        effective_from="2026-07-08",
        base_rate=0.11289,
        schedule_125=0.05619,
        rate=0.16908,
        source=SourceInfo(
            url="https://assets.ctfassets.net/416ywc1laqmd/7oUUePrMAWx7dPNnCl9P02/97d19f2529b0cbf5ad2906d16d990106/2026-7-8-standard-service-schedules.pdf",
            title="July standard-service price summary",
            effective_date="2026-07-08",
            observed_at="2026-08-16T00:00:00Z",
            sha256=hashlib.sha256(b"bundled-basic-2026-07-08").hexdigest(),
            parser_version=1,
        ),
    ),
]


def bundled_tod_rows() -> list[TodTariffRow]:
    """Return the immutable bundled seed TOD rows."""
    return list(_TOD_SEED_ROWS)


def bundled_basic_rows() -> list[BasicComparisonRow]:
    """Return the immutable bundled seed Basic comparison rows."""
    return list(_BASIC_SEED_ROWS)


# ---------------------------------------------------------------------------
# Effective-date lookup
# ---------------------------------------------------------------------------


def _parse_ymd(ymd: str) -> date:
    """Parse YYYY-MM-DD string to date; raise on malformed input."""
    parts = ymd.split("-")
    if len(parts) != 3:
        raise ValueError(f"Invalid date format: {ymd!r}")
    return date(int(parts[0]), int(parts[1]), int(parts[2]))


def _safe_ymd_date(ymd: str | None) -> date | None:
    """Parse YYYY-MM-DD string to date; return ``None`` on any failure.

    Defensive helper for paths where a corrupted Store row, parser
    regression, or unexpected JSON type should never crash the caller.
    """
    if not isinstance(ymd, str):
        return None
    try:
        return _parse_ymd(ymd)
    except (ValueError, TypeError):
        return None


def _date_of(dt: datetime | date) -> date:
    if isinstance(dt, date) and not isinstance(dt, datetime):
        return dt
    # datetime → Pacific-local date (caller must ensure tz-aware or UTC for
    # panel-only use; the catalog date is the *Pacific* date).
    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            return dt.astimezone(PGE_TZ).date()
        return dt.date()
    return dt


def tod_rate_card_at(
    timestamp: datetime | date,
    rows: list[TodTariffRow] | None,
) -> TodTariffRow | None:
    """Select the newest TOD row effective on *timestamp*'s Pacific date.

    Returns ``None`` when no row covers the date (fail-closed).
    """
    if not rows:
        return None
    qdate = _date_of(timestamp)
    best: TodTariffRow | None = None
    for row in rows:
        try:
            eff = _parse_ymd(row.effective_from)
        except (ValueError, TypeError):
            continue
        if eff <= qdate and (best is None or eff > _parse_ymd(best.effective_from)):
            best = row
    return best


def basic_comparison_rate_at(
    timestamp: datetime | date,
    rows: list[BasicComparisonRow] | None,
) -> BasicComparisonRow | None:
    """Select the newest Basic comparison row effective on *timestamp*'s date.

    Returns ``None`` when no row covers the date (fail-closed).
    """
    if not rows:
        return None
    qdate = _date_of(timestamp)
    best: BasicComparisonRow | None = None
    for row in rows:
        try:
            eff = _parse_ymd(row.effective_from)
        except (ValueError, TypeError):
            continue
        if eff <= qdate and (best is None or eff > _parse_ymd(best.effective_from)):
            best = row
    return best


# ---------------------------------------------------------------------------
# Catalog merge
# ---------------------------------------------------------------------------


def _row_effective_date(row: TodTariffRow | BasicComparisonRow) -> date:
    """Sort key for merge: return the effective date, or ``date.min`` for malformed rows.

    Malformed rows are ordered deterministically at the start instead of
    crashing the sort (see :func:`_safe_ymd_date`).
    """
    result = _safe_ymd_date(row.effective_from)
    return result if result is not None else date.min


def merge_validated_catalog(
    bundled: list[TodTariffRow] | list[BasicComparisonRow],
    stored: list[TodTariffRow] | list[BasicComparisonRow],
    fetched: list[TodTariffRow] | list[BasicComparisonRow],
) -> list[TodTariffRow] | list[BasicComparisonRow]:
    """Deterministic merge of bundled + stored + fetched catalog rows.

    Priority for same effective date: fetched > stored > bundled.
    Same-date corrections from the *same* official source (same sha256) keep
    the existing row (no-op).  Different sources at the same date in fetched
    rows supersede the previous row (official correction).

    Returns a chronologically sorted deduplicated list.
    """
    by_date: dict[str, Any] = {}

    for row in bundled:
        d = row.effective_from
        key = d
        if key not in by_date:
            by_date[key] = row

    for row in stored:
        d = row.effective_from
        key = d
        existing = by_date.get(key)
        if existing is None:
            by_date[key] = row
        elif existing.source.sha256 == row.source.sha256:
            # Same source re-fetched — keep the stored version.
            pass
        else:
            # Stored correction supersedes bundled seed at same effective date.
            by_date[key] = row

    for row in fetched:
        d = row.effective_from
        key = d
        existing = by_date.get(key)
        if existing is None:
            by_date[key] = row
        elif existing.source.sha256 != row.source.sha256:
            # Official same-date correction: new source supersedes old.
            by_date[key] = row
        # else same source, keep existing

    return sorted(by_date.values(), key=lambda r: _row_effective_date(r))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_tod_catalog(rows: list[TodTariffRow]) -> list[str]:
    """Return a list of validation errors (empty = valid).

    Checks: strictly increasing dates, positive rates, on > mid > off,
    effective_from format.
    """
    errors: list[str] = []
    dates_seen: list[date] = []
    for i, row in enumerate(rows):
        try:
            d = _parse_ymd(row.effective_from)
        except (ValueError, TypeError) as exc:
            errors.append(f"Row {i}: invalid effective_from {row.effective_from!r}: {exc}")
            continue
        if dates_seen and d <= dates_seen[-1]:
            errors.append(
                f"Row {i}: effective_from {row.effective_from} is not after previous {dates_seen[-1].isoformat()}"
            )
        dates_seen.append(d)
        if not (0 < row.off_peak < 10):
            errors.append(f"Row {i}: off_peak {row.off_peak} out of range")
        if not (0 < row.mid_peak < 10):
            errors.append(f"Row {i}: mid_peak {row.mid_peak} out of range")
        if not (0 < row.on_peak < 10):
            errors.append(f"Row {i}: on_peak {row.on_peak} out of range")
        if row.on_peak <= row.mid_peak:
            errors.append(f"Row {i}: on_peak ({row.on_peak}) must exceed mid_peak ({row.mid_peak})")
        if row.mid_peak <= row.off_peak:
            errors.append(f"Row {i}: mid_peak ({row.mid_peak}) must exceed off_peak ({row.off_peak})")
        if not row.source.url.startswith("https://"):
            errors.append(f"Row {i}: source URL must be HTTPS, got {row.source.url[:40]}")
    return errors


def validate_basic_catalog(rows: list[BasicComparisonRow]) -> list[str]:
    """Return a list of validation errors (empty = valid)."""
    errors: list[str] = []
    dates_seen: list[date] = []
    for i, row in enumerate(rows):
        try:
            d = _parse_ymd(row.effective_from)
        except (ValueError, TypeError) as exc:
            errors.append(f"Row {i}: invalid effective_from {row.effective_from!r}: {exc}")
            continue
        if dates_seen and d <= dates_seen[-1]:
            errors.append(
                f"Row {i}: effective_from {row.effective_from} is not after previous {dates_seen[-1].isoformat()}"
            )
        dates_seen.append(d)
        if row.rate <= 0:
            errors.append(f"Row {i}: rate must be positive, got {row.rate}")
        if not row.source.url.startswith("https://"):
            errors.append(f"Row {i}: source URL must be HTTPS, got {row.source.url[:40]}")
    return errors


# ---------------------------------------------------------------------------
# Serialization (credential-free JSON for the panel)
# ---------------------------------------------------------------------------


def _source_to_dict(src: SourceInfo) -> dict[str, Any]:
    return {
        "url": src.url,
        "title": src.title,
        "effective_date": src.effective_date,
        "observed_at": src.observed_at,
        "sha256": src.sha256[:16] + "...",
        "parser_version": src.parser_version,
    }


def _tod_row_to_dict(row: TodTariffRow) -> dict[str, Any]:
    return {
        "effective_from": row.effective_from,
        "off_peak": row.off_peak,
        "mid_peak": row.mid_peak,
        "on_peak": row.on_peak,
        "source": _source_to_dict(row.source),
        "component_basis": row.component_basis,
        "exclusions": row.exclusions,
    }


def _basic_row_to_dict(row: BasicComparisonRow) -> dict[str, Any]:
    return {
        "effective_from": row.effective_from,
        "base_rate": row.base_rate,
        "schedule_125": row.schedule_125,
        "rate": row.rate,
        "source": _source_to_dict(row.source),
        "component_basis": row.component_basis,
        "exclusions": row.exclusions,
    }


def serialize_tariff_catalogs(
    tod_rows: list[TodTariffRow],
    basic_rows: list[BasicComparisonRow],
) -> dict[str, Any]:
    """Credential-free JSON-serializable snapshot of both catalogs."""
    return {
        "tod": [_tod_row_to_dict(r) for r in tod_rows],
        "basic": [_basic_row_to_dict(r) for r in basic_rows],
    }


def serialize_row_for_store(row: TodTariffRow | BasicComparisonRow) -> dict[str, Any]:
    """Serialize a single row for domain Store persistence (full source hash)."""
    src = {
        "url": row.source.url,
        "title": row.source.title,
        "effective_date": row.source.effective_date,
        "observed_at": row.source.observed_at,
        "sha256": row.source.sha256,
        "parser_version": row.source.parser_version,
    }
    if isinstance(row, TodTariffRow):
        return {
            "type": "tod",
            "effective_from": row.effective_from,
            "off_peak": row.off_peak,
            "mid_peak": row.mid_peak,
            "on_peak": row.on_peak,
            "source": src,
        }
    else:
        return {
            "type": "basic",
            "effective_from": row.effective_from,
            "base_rate": row.base_rate,
            "schedule_125": row.schedule_125,
            "rate": row.rate,
            "source": src,
        }


def deserialize_row_from_store(data: dict[str, Any]) -> TodTariffRow | BasicComparisonRow | None:
    """Rebuild a row from Store dict; malformed data → None."""
    if not isinstance(data, dict):
        return None
    row_type = data.get("type")
    src_data = data.get("source")
    if not isinstance(src_data, dict):
        return None
    try:
        source = SourceInfo(
            url=src_data["url"],
            title=src_data["title"],
            effective_date=src_data["effective_date"],
            observed_at=src_data["observed_at"],
            sha256=src_data["sha256"],
            parser_version=src_data.get("parser_version", 1),
        )
    except (KeyError, TypeError):
        return None
    try:
        if row_type == "tod":
            return TodTariffRow(
                effective_from=data["effective_from"],
                off_peak=float(data["off_peak"]),
                mid_peak=float(data["mid_peak"]),
                on_peak=float(data["on_peak"]),
                source=source,
            )
        elif row_type == "basic":
            return BasicComparisonRow(
                effective_from=data["effective_from"],
                base_rate=float(data["base_rate"]),
                schedule_125=float(data["schedule_125"]),
                rate=float(data["rate"]),
                source=source,
            )
    except (KeyError, TypeError, ValueError):
        return None
    return None
