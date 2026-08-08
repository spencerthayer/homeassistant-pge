from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

# Amounts and kWh are kept as ``float`` (not Decimal) throughout the billing
# models: Home Assistant sensor states and long-term statistics are floats, so
# keeping a single representation avoids repeated conversions at the sensor /
# statistics boundary. Parsing helpers in ``billing_api`` coerce raw GraphQL
# scalars into these floats defensively.


class LedgerEventType(StrEnum):
    """Kind of billing/payment history row."""

    BILL = "BILL"
    PAYMENT = "PAYMENT"


@dataclass(frozen=True, slots=True)
class LedgerEvent:
    """A single row from the billing & payment history feed.

    ``BILL`` rows carry ``amount_due`` / ``kwh`` for a billing period;
    ``PAYMENT`` rows carry ``amount_paid``. The other numeric fields are left
    as ``None`` when not applicable to the row type.
    """

    event_type: LedgerEventType
    date: datetime
    amount_due: float | None = None
    amount_paid: float | None = None
    kwh: float | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    encrypted_bill_id: str | None = None


@dataclass(frozen=True, slots=True)
class BillDetails:
    """Structured view-bill details for the current/most-recent bill."""

    amount_due: float | None = None
    kwh: float | None = None
    bill_date: datetime | None = None
    due_date: datetime | None = None
    previous_balance: float | None = None
    total_adjustments: float | None = None
    total_current_charges: float | None = None
    total_balance_after_bill: float | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    encrypted_bill_id: str | None = None
    avg_temperature_f: float | None = None


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    """Account summary + latest bill, resolved from ``getAccountDetailList``."""

    account_number: str
    amount_due: float | None = None
    due_date: datetime | None = None
    last_payment_amount: float | None = None
    last_payment_date: datetime | None = None
    autopay_enrolled: bool | None = None
    paperless_enrolled: bool | None = None
    bill: BillDetails | None = None
    encrypted_account_number: str | None = None
    encrypted_person_id: str | None = None
    encrypted_premise_id: str | None = None
    encrypted_sa_id: str | None = None


@dataclass(frozen=True, slots=True)
class EnergyTrackerEstimates:
    """Open-cycle estimates from ``getEnergyTrackerData`` (portal Current Use).

    PGE computes these itself: they are not a sum of the imported hourly
    intervals and will not reconcile with them (see ``DATA_CONTRACT.md``).
    """

    details_available: bool = False
    has_more_than_15_days: bool | None = None
    billing_cycle_day: int | None = None
    billing_cycle_total_days: int | None = None
    bill_to_date_amount: float | None = None
    projected_min_amount: float | None = None
    projected_max_amount: float | None = None
    current_period_kwh: float | None = None
    previous_period_kwh: float | None = None


@dataclass(frozen=True, slots=True)
class ProgramEnrollment:
    """One program's enrollment state plus any program-specific attributes."""

    program_name: str
    is_enrolled: bool
    is_eligible: bool | None = None
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProgramsSnapshot:
    """Aggregated program enrollment across the portal ``programs`` ops."""

    energy_shifting: list[ProgramEnrollment] = field(default_factory=list)
    renewables: list[ProgramEnrollment] = field(default_factory=list)
    ytd_flex_load_earnings: float | None = None
    on_bill_flex_load_earnings: float | None = None
    peak_time_rebates_enrolled: bool | None = None
    green_future_enrolled: bool | None = None
    time_of_day_enrolled: bool | None = None
    smart_thermostat_enrolled: bool | None = None
    habitat_support_enrolled: bool | None = None
    green_future_pct: float | None = None
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TodSnapshot:
    """Portal-sourced Time of Day pricing + savings (best-effort, may be partial).

    Discovered from pricing-plan GraphQL ops; every field is optional so a
    partial/empty payload still soft-fails into the offline defaults. The
    coordinator caches the last-good snapshot across reloads (never blanking
    rates on a renew/sync failure).
    """

    rates: dict[str, float] = field(default_factory=dict)
    basic_rate: float | None = None
    savings_total: float | None = None
    fetched_at: datetime | None = None
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BillingFreshness:
    """Coordinator-facing freshness marker for the billing sync."""

    last_success: datetime | None = None
    last_error: str | None = None
