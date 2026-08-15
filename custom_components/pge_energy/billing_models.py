from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


def _parse_iso_dt(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _dt_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _float_or_none(raw: object) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _int_or_none(raw: object) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _bool_or_none(raw: object) -> bool | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    return None


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

    def to_dict(self, *, persist_ids: bool = False) -> dict[str, Any]:
        """Serialize for Store. Encrypted bill id omitted unless ``persist_ids``."""
        return {
            "amount_due": self.amount_due,
            "kwh": self.kwh,
            "bill_date": _dt_iso(self.bill_date),
            "due_date": _dt_iso(self.due_date),
            "previous_balance": self.previous_balance,
            "total_adjustments": self.total_adjustments,
            "total_current_charges": self.total_current_charges,
            "total_balance_after_bill": self.total_balance_after_bill,
            "period_start": _dt_iso(self.period_start),
            "period_end": _dt_iso(self.period_end),
            "encrypted_bill_id": self.encrypted_bill_id if persist_ids else None,
            "avg_temperature_f": self.avg_temperature_f,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> BillDetails | None:
        if not data or not isinstance(data, dict):
            return None
        return cls(
            amount_due=_float_or_none(data.get("amount_due")),
            kwh=_float_or_none(data.get("kwh")),
            bill_date=_parse_iso_dt(data.get("bill_date")),
            due_date=_parse_iso_dt(data.get("due_date")),
            previous_balance=_float_or_none(data.get("previous_balance")),
            total_adjustments=_float_or_none(data.get("total_adjustments")),
            total_current_charges=_float_or_none(data.get("total_current_charges")),
            total_balance_after_bill=_float_or_none(data.get("total_balance_after_bill")),
            period_start=_parse_iso_dt(data.get("period_start")),
            period_end=_parse_iso_dt(data.get("period_end")),
            encrypted_bill_id=str(data["encrypted_bill_id"]) if data.get("encrypted_bill_id") else None,
            avg_temperature_f=_float_or_none(data.get("avg_temperature_f")),
        )


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

    def to_dict(self) -> dict[str, Any]:
        """Store-safe sensor snapshot — encrypted identity stays on the config entry."""
        return {
            "account_number": self.account_number,
            "amount_due": self.amount_due,
            "due_date": _dt_iso(self.due_date),
            "last_payment_amount": self.last_payment_amount,
            "last_payment_date": _dt_iso(self.last_payment_date),
            "autopay_enrolled": self.autopay_enrolled,
            "paperless_enrolled": self.paperless_enrolled,
            "bill": self.bill.to_dict() if self.bill is not None else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AccountSnapshot | None:
        if not data or not isinstance(data, dict):
            return None
        account_number = data.get("account_number")
        if not isinstance(account_number, str) or not account_number:
            return None
        bill_raw = data.get("bill")
        return cls(
            account_number=account_number,
            amount_due=_float_or_none(data.get("amount_due")),
            due_date=_parse_iso_dt(data.get("due_date")),
            last_payment_amount=_float_or_none(data.get("last_payment_amount")),
            last_payment_date=_parse_iso_dt(data.get("last_payment_date")),
            autopay_enrolled=_bool_or_none(data.get("autopay_enrolled")),
            paperless_enrolled=_bool_or_none(data.get("paperless_enrolled")),
            bill=BillDetails.from_dict(bill_raw if isinstance(bill_raw, dict) else None),
        )


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "details_available": self.details_available,
            "has_more_than_15_days": self.has_more_than_15_days,
            "billing_cycle_day": self.billing_cycle_day,
            "billing_cycle_total_days": self.billing_cycle_total_days,
            "bill_to_date_amount": self.bill_to_date_amount,
            "projected_min_amount": self.projected_min_amount,
            "projected_max_amount": self.projected_max_amount,
            "current_period_kwh": self.current_period_kwh,
            "previous_period_kwh": self.previous_period_kwh,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> EnergyTrackerEstimates | None:
        if not data or not isinstance(data, dict):
            return None
        return cls(
            details_available=bool(data.get("details_available", False)),
            has_more_than_15_days=_bool_or_none(data.get("has_more_than_15_days")),
            billing_cycle_day=_int_or_none(data.get("billing_cycle_day")),
            billing_cycle_total_days=_int_or_none(data.get("billing_cycle_total_days")),
            bill_to_date_amount=_float_or_none(data.get("bill_to_date_amount")),
            projected_min_amount=_float_or_none(data.get("projected_min_amount")),
            projected_max_amount=_float_or_none(data.get("projected_max_amount")),
            current_period_kwh=_float_or_none(data.get("current_period_kwh")),
            previous_period_kwh=_float_or_none(data.get("previous_period_kwh")),
        )


@dataclass(frozen=True, slots=True)
class ProgramEnrollment:
    """One program's enrollment state plus any program-specific attributes."""

    program_name: str
    is_enrolled: bool | None
    is_eligible: bool | None = None
    attributes: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_name": self.program_name,
            "is_enrolled": self.is_enrolled,
            "is_eligible": self.is_eligible,
            "attributes": dict(self.attributes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ProgramEnrollment | None:
        if not data or not isinstance(data, dict):
            return None
        name = data.get("program_name")
        if not isinstance(name, str) or not name:
            return None
        enrolled = data.get("is_enrolled")
        if enrolled is not None and not isinstance(enrolled, bool):
            return None
        attrs = data.get("attributes")
        return cls(
            program_name=name,
            is_enrolled=enrolled if isinstance(enrolled, bool) else None,
            is_eligible=_bool_or_none(data.get("is_eligible")),
            attributes=dict(attrs) if isinstance(attrs, dict) else {},
        )


@dataclass(frozen=True, slots=True)
class ProgramsSnapshot:
    """Aggregated program enrollment across the portal ``programs`` ops."""

    energy_shifting: list[ProgramEnrollment] = field(default_factory=list)
    renewables: list[ProgramEnrollment] = field(default_factory=list)
    ytd_flex_load_earnings: float | None = None
    on_bill_flex_load_earnings: float | None = None
    peak_time_rebates_enrolled: bool | None = None
    peak_time_rebates_eligible: bool | None = None
    green_future_enrolled: bool | None = None
    green_future_eligible: bool | None = None
    time_of_day_enrolled: bool | None = None
    time_of_day_eligible: bool | None = None
    smart_thermostat_enrolled: bool | None = None
    smart_thermostat_eligible: bool | None = None
    habitat_support_enrolled: bool | None = None
    habitat_support_eligible: bool | None = None
    smart_charging_enrolled: bool | None = None
    smart_charging_eligible: bool | None = None
    smart_battery_enrolled: bool | None = None
    smart_battery_eligible: bool | None = None
    green_future_pct: float | None = None
    attributes: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "energy_shifting": [p.to_dict() for p in self.energy_shifting],
            "renewables": [p.to_dict() for p in self.renewables],
            "ytd_flex_load_earnings": self.ytd_flex_load_earnings,
            "on_bill_flex_load_earnings": self.on_bill_flex_load_earnings,
            "peak_time_rebates_enrolled": self.peak_time_rebates_enrolled,
            "peak_time_rebates_eligible": self.peak_time_rebates_eligible,
            "green_future_enrolled": self.green_future_enrolled,
            "green_future_eligible": self.green_future_eligible,
            "time_of_day_enrolled": self.time_of_day_enrolled,
            "time_of_day_eligible": self.time_of_day_eligible,
            "smart_thermostat_enrolled": self.smart_thermostat_enrolled,
            "smart_thermostat_eligible": self.smart_thermostat_eligible,
            "habitat_support_enrolled": self.habitat_support_enrolled,
            "habitat_support_eligible": self.habitat_support_eligible,
            "smart_charging_enrolled": self.smart_charging_enrolled,
            "smart_charging_eligible": self.smart_charging_eligible,
            "smart_battery_enrolled": self.smart_battery_enrolled,
            "smart_battery_eligible": self.smart_battery_eligible,
            "green_future_pct": self.green_future_pct,
            "attributes": dict(self.attributes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ProgramsSnapshot | None:
        if not data or not isinstance(data, dict):
            return None

        def _programs(raw: object) -> list[ProgramEnrollment]:
            if not isinstance(raw, list):
                return []
            out: list[ProgramEnrollment] = []
            for item in raw:
                prog = ProgramEnrollment.from_dict(item if isinstance(item, dict) else None)
                if prog is not None:
                    out.append(prog)
            return out

        attrs = data.get("attributes")
        return cls(
            energy_shifting=_programs(data.get("energy_shifting")),
            renewables=_programs(data.get("renewables")),
            ytd_flex_load_earnings=_float_or_none(data.get("ytd_flex_load_earnings")),
            on_bill_flex_load_earnings=_float_or_none(data.get("on_bill_flex_load_earnings")),
            peak_time_rebates_enrolled=_bool_or_none(data.get("peak_time_rebates_enrolled")),
            peak_time_rebates_eligible=_bool_or_none(data.get("peak_time_rebates_eligible")),
            green_future_enrolled=_bool_or_none(data.get("green_future_enrolled")),
            green_future_eligible=_bool_or_none(data.get("green_future_eligible")),
            time_of_day_enrolled=_bool_or_none(data.get("time_of_day_enrolled")),
            time_of_day_eligible=_bool_or_none(data.get("time_of_day_eligible")),
            smart_thermostat_enrolled=_bool_or_none(data.get("smart_thermostat_enrolled")),
            smart_thermostat_eligible=_bool_or_none(data.get("smart_thermostat_eligible")),
            habitat_support_enrolled=_bool_or_none(data.get("habitat_support_enrolled")),
            habitat_support_eligible=_bool_or_none(data.get("habitat_support_eligible")),
            smart_charging_enrolled=_bool_or_none(data.get("smart_charging_enrolled")),
            smart_charging_eligible=_bool_or_none(data.get("smart_charging_eligible")),
            smart_battery_enrolled=_bool_or_none(data.get("smart_battery_enrolled")),
            smart_battery_eligible=_bool_or_none(data.get("smart_battery_eligible")),
            green_future_pct=_float_or_none(data.get("green_future_pct")),
            attributes=dict(attrs) if isinstance(attrs, dict) else {},
        )


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
class NetMeteringSnapshot:
    """Portal net-metering details (diagnostic, gated on solar return history).

    All fields are raw strings until UAT validates units/types — prefer
    diagnostic attributes over guessing device_class.
    """

    fetched_at: datetime | None = None
    attributes: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "attributes": dict(self.attributes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object] | None) -> NetMeteringSnapshot | None:
        if not data or not isinstance(data, dict):
            return None
        fetched_raw = data.get("fetched_at")
        fetched_at: datetime | None = None
        if isinstance(fetched_raw, str) and fetched_raw:
            try:
                fetched_at = datetime.fromisoformat(fetched_raw)
            except ValueError:
                fetched_at = None
        attrs = data.get("attributes")
        return cls(
            fetched_at=fetched_at,
            attributes=dict(attrs) if isinstance(attrs, dict) else {},
        )


_RATE_COMPARE_REDACT_KEYS = frozenset(
    {
        "accountnumber",
        "account_number",
        "encryptedpersonid",
        "encrypted_person_id",
        "personid",
        "person_id",
        "encryptedserviceagreementid",
        "encryptedaccountnumber",
        "encryptedpremiseid",
        "encryptedaccountid",
    }
)


def sanitize_rate_compare_attrs(attrs: dict[str, object]) -> dict[str, object]:
    """Drop identifier-shaped keys before Store/diagnostics persistence."""
    out: dict[str, object] = {}
    for key, value in attrs.items():
        if str(key).lower().replace("-", "_") in _RATE_COMPARE_REDACT_KEYS:
            continue
        if "encrypted" in str(key).lower():
            continue
        out[key] = value
    return out


def _rate_compare_float(attrs: dict[str, object], *keys: str) -> float | None:
    """First finite numeric value across alternate attribute spellings."""
    for key in keys:
        number = _float_or_none(attrs.get(key))
        if number is not None and math.isfinite(number):
            return number
    return None


@dataclass(frozen=True, slots=True)
class RateCompareSnapshot:
    """Portal rate-compare data (TOD vs Basic aggregate comparison).

    Persisted last-good; used for diagnostic attributes, never for deriving
    per-period rates (offline defaults handle that).
    """

    fetched_at: datetime | None = None
    attributes: dict[str, object] = field(default_factory=dict)

    @property
    def savings(self) -> float | None:
        return _rate_compare_float(self.attributes, "savings")

    @property
    def tou_total(self) -> float | None:
        return _rate_compare_float(self.attributes, "touTotal", "tou_total")

    @property
    def basic_total(self) -> float | None:
        return _rate_compare_float(self.attributes, "basicTotal", "basic_total")

    @property
    def comparison_period(self) -> str | None:
        value = self.attributes.get("comparisonPeriod", self.attributes.get("comparison_period"))
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    @property
    def has_data(self) -> bool:
        return bool(self.attributes)

    def to_dict(self) -> dict[str, object]:
        return {
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "attributes": sanitize_rate_compare_attrs(dict(self.attributes)),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object] | None) -> RateCompareSnapshot | None:
        if not data or not isinstance(data, dict):
            return None
        fetched_raw = data.get("fetched_at")
        fetched_at: datetime | None = None
        if isinstance(fetched_raw, str) and fetched_raw:
            try:
                fetched_at = datetime.fromisoformat(fetched_raw)
            except ValueError:
                fetched_at = None
        attrs = data.get("attributes")
        return cls(
            fetched_at=fetched_at,
            attributes=sanitize_rate_compare_attrs(dict(attrs)) if isinstance(attrs, dict) else {},
        )


@dataclass(frozen=True, slots=True)
class BillingFreshness:
    """Coordinator-facing freshness marker for the billing sync."""

    last_success: datetime | None = None
    last_error: str | None = None
