from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class UsageResolution(StrEnum):
    HOURLY = "HOURLY"
    DAILY = "DAILY"
    MONTHLY = "MONTHLY"


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
