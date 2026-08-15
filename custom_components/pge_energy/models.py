from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any


class UsageResolution(StrEnum):
    HOURLY = "HOURLY"
    DAILY = "DAILY"
    MONTHLY = "MONTHLY"


# Bound tip-interval Store payload (correction polls are typically a few days).
TIP_INTERVALS_STORE_CAP = 240


@dataclass(frozen=True, slots=True)
class UsageInterval:
    account_key: str
    resolution: UsageResolution
    start: datetime
    end: datetime
    # None means PGE returned an explicit null kWh sample for this start
    # (unavailable energy — not zero and not a missing timestamp).
    kwh: Decimal | None
    amount: Decimal | None
    temperature: Decimal | None
    usage_status: str | None
    interval_size: int | None
    source_timestamp: datetime | None


def _decimal_or_none(raw: object) -> Decimal | None:
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _parse_iso_dt(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def usage_interval_to_dict(interval: UsageInterval) -> dict[str, Any]:
    """JSON-safe tip interval for Store soft-fail restore."""
    return {
        "account_key": interval.account_key,
        "resolution": interval.resolution.value,
        "start": interval.start.isoformat(),
        "end": interval.end.isoformat(),
        "kwh": str(interval.kwh) if interval.kwh is not None else None,
        "amount": str(interval.amount) if interval.amount is not None else None,
        "temperature": str(interval.temperature) if interval.temperature is not None else None,
        "usage_status": interval.usage_status,
        "interval_size": interval.interval_size,
        "source_timestamp": (interval.source_timestamp.isoformat() if interval.source_timestamp is not None else None),
    }


def usage_interval_from_dict(data: dict[str, Any] | None) -> UsageInterval | None:
    """Rebuild a tip interval from Store dict; malformed → None."""
    if not data or not isinstance(data, dict):
        return None
    account_key = data.get("account_key")
    if not isinstance(account_key, str) or not account_key:
        return None
    try:
        resolution = UsageResolution(str(data.get("resolution") or UsageResolution.HOURLY.value))
    except ValueError:
        return None
    start = _parse_iso_dt(data.get("start"))
    end = _parse_iso_dt(data.get("end"))
    if start is None or end is None:
        return None
    interval_size: int | None
    if data.get("interval_size") is None:
        interval_size = None
    else:
        try:
            interval_size = int(data["interval_size"])
        except (TypeError, ValueError):
            return None
    return UsageInterval(
        account_key=account_key,
        resolution=resolution,
        start=start,
        end=end,
        kwh=_decimal_or_none(data.get("kwh")),
        amount=_decimal_or_none(data.get("amount")),
        temperature=_decimal_or_none(data.get("temperature")),
        usage_status=str(data["usage_status"]) if data.get("usage_status") is not None else None,
        interval_size=interval_size,
        source_timestamp=_parse_iso_dt(data.get("source_timestamp")),
    )


def tip_intervals_to_store(intervals: list[UsageInterval]) -> list[dict[str, Any]]:
    """Serialize tip intervals, keeping the newest ``TIP_INTERVALS_STORE_CAP`` rows."""
    ordered = sorted(intervals, key=lambda iv: iv.end)
    if len(ordered) > TIP_INTERVALS_STORE_CAP:
        ordered = ordered[-TIP_INTERVALS_STORE_CAP:]
    return [usage_interval_to_dict(iv) for iv in ordered]


def merge_tip_intervals(
    retained: list[UsageInterval],
    incoming: list[UsageInterval],
    *,
    cap: int = TIP_INTERVALS_STORE_CAP,
) -> list[UsageInterval]:
    """Merge successful intervals into the retained tip by ``start`` timestamp.

    Partial correction windows must not drop newer retained hours that were not
    re-fetched (failed days). Incoming rows replace matching starts; the result
    is capped to the newest ``cap`` intervals.
    """
    by_start: dict[datetime, UsageInterval] = {iv.start: iv for iv in retained}
    for iv in incoming:
        by_start[iv.start] = iv
    ordered = sorted(by_start.values(), key=lambda iv: iv.end)
    if len(ordered) > cap:
        ordered = ordered[-cap:]
    return ordered


def tip_intervals_from_store(raw: object) -> list[UsageInterval]:
    """Deserialize tip intervals from Store; drop malformed rows."""
    if not isinstance(raw, list):
        return []
    out: list[UsageInterval] = []
    for item in raw:
        iv = usage_interval_from_dict(item if isinstance(item, dict) else None)
        if iv is not None:
            out.append(iv)
    return out


@dataclass(frozen=True, slots=True)
class PGEAccount:
    account_id: str
    encrypted_person_id: str
    account_type: str | None
    is_tod: bool | None


@dataclass(frozen=True, slots=True)
class PGEIdentity:
    portal_identity: str
    account_id: str
    encrypted_person_id: str


@dataclass(frozen=True, slots=True)
class PGEToken:
    access_token: str
    expires_at: datetime | None


@dataclass(slots=True)
class UsageResponse:
    resolution: UsageResolution
    intervals: list[UsageInterval]
    total_kwh: Decimal | None
    total_cost: Decimal | None
    is_tod: bool | None
    acct_type: str | None


@dataclass(frozen=True, slots=True)
class ImportCheckpoint:
    last_imported_start: datetime | None
    last_imported_end: datetime | None
    last_imported_timestamp: datetime
    correction_window_start: datetime | None
    failed_ranges: list[tuple[datetime, datetime]]


@dataclass(frozen=True, slots=True)
class DataFreshness:
    newest_interval: datetime | None
    last_successful_update: datetime | None
    last_api_error: str | None
    data_age_seconds: float | None


@dataclass(slots=True)
class SyncProgressSnapshot:
    """Live manual-sync / backfill progress for device sensors."""

    status: str = "idle"  # idle | refreshing | backfilling | complete | failed
    phase: str = "idle"  # idle | correction | hourly | daily | monthly
    done: int = 0
    total: int = 0
    percent: int = 0
    started_at: float | None = None  # time.monotonic() at job start
    eta_seconds: float | None = None
    message: str = ""
    error: str | None = None
