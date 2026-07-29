"""Offline feasibility prototype for PGE bill PDF normalization.

This module is intentionally outside ``custom_components``. It lets tests and
maintainers evaluate text-backed bill PDFs before PDF parsing becomes a shipped
Home Assistant feature. Raw extracted text can contain personal information and
is therefore never included in serialized output.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import Any

MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_PDF_PAGES = 24

_DATE = r"\d{1,2}/\d{1,2}/(?:\d{2}|\d{4})"
_AMOUNT = r"-?\$?\s*\(?\d[\d,]*\.\d{2}\)?"
_NUMBER = r"\d[\d,]*(?:\.\d+)?"
_FOR_DAYS = r"(?:\s*for\s*\d+\s*days)?"
_TEXT_VARIANT_SEPARATOR = "\n<<<PGE_PLAIN_TEXT_FALLBACK>>>\n"


class PDFTextExtractionError(ValueError):
    """The PDF cannot safely provide plaintext for normalization."""


@dataclass(frozen=True, slots=True)
class ExtractedPDFText:
    """Plaintext plus non-sensitive source metadata."""

    text: str
    page_count: int
    source_sha256: str


@dataclass(frozen=True, slots=True)
class BillParseHints:
    """Structured GraphQL values used to identify and reconcile a bill."""

    statement_date: date
    expected_amount_due: Decimal | None = None
    expected_total_kwh: Decimal | None = None
    expected_period_start: date | None = None
    expected_period_end: date | None = None


@dataclass(frozen=True, slots=True)
class BillMetric:
    """One normalized, statement-scoped numeric value."""

    key: str
    value: Decimal
    unit: str
    label: str

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "value": str(self.value),
            "unit": self.unit,
            "label": self.label,
        }


@dataclass(frozen=True, slots=True)
class NormalizedBill:
    """PII-free normalized data suitable for later Store/statistics mapping."""

    statement_date: date
    due_date: date | None
    period_start: date | None
    period_end: date | None
    amount_due: Decimal | None
    total_kwh: Decimal | None
    multiple_service_locations: bool = False
    metrics: dict[str, BillMetric] = field(default_factory=dict)
    source_sha256: str | None = None
    confidence: float = 0.0
    warnings: tuple[str, ...] = ()
    advisories: tuple[str, ...] = ()

    @property
    def safe_to_publish(self) -> bool:
        """Whether core identity fields reconciled; advisories remain non-blocking."""
        return not self.warnings

    def to_dict(self) -> dict[str, Any]:
        """Serialize normalized values only; never retain raw PDF text or PII."""
        return {
            "statement_date": self.statement_date.isoformat(),
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "amount_due": str(self.amount_due) if self.amount_due is not None else None,
            "total_kwh": str(self.total_kwh) if self.total_kwh is not None else None,
            "multiple_service_locations": self.multiple_service_locations,
            "metrics": {key: metric.to_dict() for key, metric in sorted(self.metrics.items())},
            "source_sha256": self.source_sha256,
            "confidence": self.confidence,
            "warnings": list(self.warnings),
            "advisories": list(self.advisories),
            "safe_to_publish": self.safe_to_publish,
        }


@dataclass(frozen=True, slots=True)
class HistorySample:
    """A future HA statistic sample, independent of recorder implementation."""

    key: str
    start: date
    value: Decimal
    unit: str


def extract_pdf_text(data: bytes) -> ExtractedPDFText:
    """Extract layout-preserving plaintext from an in-memory, text-backed PDF."""
    if not data.startswith(b"%PDF-"):
        raise PDFTextExtractionError("response is not a PDF")
    if len(data) > MAX_PDF_BYTES:
        raise PDFTextExtractionError(f"PDF exceeds {MAX_PDF_BYTES} byte safety limit")

    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency failure is environment-specific
        raise PDFTextExtractionError("pypdf is required for PDF text extraction") from exc

    try:
        reader = PdfReader(BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise PDFTextExtractionError("encrypted PDFs are not supported")
        page_count = len(reader.pages)
        if page_count > MAX_PDF_PAGES:
            raise PDFTextExtractionError(f"PDF exceeds {MAX_PDF_PAGES} page safety limit")
        layout_pages: list[str] = []
        plain_pages: list[str] = []
        for page in reader.pages:
            try:
                layout_text = page.extract_text(
                    extraction_mode="layout",
                    layout_mode_space_vertically=False,
                )
            except TypeError:  # pragma: no cover - compatibility with older pypdf
                layout_text = page.extract_text()
            plain_text = page.extract_text() or ""
            layout_pages.append(layout_text or "")
            plain_pages.append(plain_text)
    except PDFTextExtractionError:
        raise
    except Exception as exc:
        raise PDFTextExtractionError(f"unable to read PDF: {exc}") from exc

    layout_document = "\n\f\n".join(layout_pages)
    plain_document = "\n\f\n".join(plain_pages)
    if plain_document.strip() and plain_document != layout_document:
        text = f"{layout_document}{_TEXT_VARIANT_SEPARATOR}{plain_document}"
    else:
        text = layout_document
    text = text.replace("\x00", "")
    if len(re.sub(r"\W", "", text)) < 12:
        raise PDFTextExtractionError("PDF contains no extractable text; OCR would be required")
    return ExtractedPDFText(
        text=text,
        page_count=page_count,
        source_sha256=hashlib.sha256(data).hexdigest(),
    )


def _flat_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", normalized).strip()


def _parse_decimal(raw: str) -> Decimal | None:
    cleaned = raw.strip().replace("$", "").replace(",", "").replace(" ", "")
    is_credit = cleaned.upper().endswith("(CR)")
    cleaned = re.sub(r"\(CR\)$", "", cleaned, flags=re.IGNORECASE)
    accounting_negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.strip("()")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -abs(value) if is_credit or accounting_negative else value


def _parse_date(raw: str) -> date | None:
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _search_decimal(text: str, pattern: str, *, credit: bool = False) -> Decimal | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match is None:
        return None
    value = _parse_decimal(match.group("amount"))
    if value is not None and credit:
        return -abs(value)
    return value


def _search_date(text: str, pattern: str) -> date | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return _parse_date(match.group("date")) if match else None


def _current_amount_due(text: str, expected: Decimal | None) -> Decimal | None:
    """Find current amount due without accepting the previous-bill label."""
    patterns = (
        rf"(?<!Previous )\bAmount due:?\s*(?:(?:date\s+)?{_DATE})?\s*(?P<amount>{_AMOUNT})",
        rf"\bPlease pay\s+(?P<amount>{_AMOUNT})\s+by\s+{_DATE}",
    )
    candidates: list[Decimal] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = _parse_decimal(match.group("amount"))
            if value is not None:
                candidates.append(value)
    if expected is not None:
        for candidate in candidates:
            if abs(candidate - expected) <= Decimal("0.01"):
                return candidate
    return candidates[0] if candidates else None


def _current_due_date(text: str) -> date | None:
    patterns = (
        rf"\bDue date:?\s*(?P<date>{_DATE})",
        rf"\bPlease pay\s+{_AMOUNT}\s+by\s+(?P<date>{_DATE})",
        rf"(?<!Previous )\bAmount due:?\s*(?P<date>{_DATE})\s*{_AMOUNT}",
    )
    for pattern in patterns:
        if value := _search_date(text, pattern):
            return value
    return None


def _total_kwh(text: str, expected: Decimal | None) -> Decimal | None:
    """Resolve one account total or a sum of distinct meter totals."""
    meter_row_pattern = (
        rf"{_DATE}\s*to\s*{_DATE}\s+\S+\s+{_NUMBER}\s+{_NUMBER}\s+"
        rf"(?P<amount>{_NUMBER})\s*kWh\b"
    )
    meter_totals = [
        value
        for match in re.finditer(meter_row_pattern, text, flags=re.IGNORECASE)
        if (value := _parse_decimal(match.group("amount"))) is not None
    ]
    if expected is not None and len(meter_totals) > 1:
        meter_sum = sum(meter_totals, Decimal())
        if abs(meter_sum - expected) <= Decimal("0.01"):
            return meter_sum

    prioritized_patterns = (
        rf"(?P<amount>{_NUMBER})\s*kWh\s*this month\b",
        rf"\bTotal use.{{0,240}}?(?P<amount>{_NUMBER})\s*kWh\b",
    )
    candidates: list[Decimal] = []
    for pattern in (*prioritized_patterns, rf"(?P<amount>{_NUMBER})\s*kWh\b"):
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            value = _parse_decimal(match.group("amount"))
            if value is not None and value not in candidates:
                candidates.append(value)
    if expected is not None:
        for candidate in candidates:
            if abs(candidate - expected) <= Decimal("0.01"):
                return candidate
        # Move/multi-meter bills may expose only individual meter totals. The
        # fallback uses distinct values to avoid repeated rate formulas.
        positive = [candidate for candidate in candidates if candidate > 0]
        for size in range(2, min(4, len(positive)) + 1):
            for subset in itertools.combinations(positive, size):
                total = sum(subset, Decimal())
                if abs(total - expected) <= Decimal("0.01"):
                    return total
    return candidates[0] if candidates else None


def _service_period(text: str, hints: BillParseHints) -> tuple[date | None, date | None]:
    """Select the service period closest to the bound GraphQL ledger row."""
    matches = re.finditer(
        rf"\bService period\s*(?P<start>{_DATE})\s*to\s*(?P<end>{_DATE})",
        text,
        flags=re.IGNORECASE,
    )
    candidates = [
        (start, end)
        for match in matches
        if (start := _parse_date(match.group("start"))) is not None
        and (end := _parse_date(match.group("end"))) is not None
    ]
    if not candidates:
        return None, None

    def score(candidate: tuple[date, date]) -> int:
        start, end = candidate
        start_distance = (
            abs((start - hints.expected_period_start).days) if hints.expected_period_start is not None else 0
        )
        end_distance = abs((end - hints.expected_period_end).days) if hints.expected_period_end is not None else 0
        return start_distance + end_distance

    return min(candidates, key=score)


_METRIC_PATTERNS: tuple[tuple[str, str, str], ...] = (
    (
        "balance_forward",
        rf"\bBalance forward\s*(?P<amount>{_AMOUNT})",
        "Balance forward",
    ),
    (
        "previous_amount_due",
        rf"\bPrevious amount due\s*{_DATE}\s*(?P<amount>{_AMOUNT})",
        "Previous amount due",
    ),
    (
        "energy_delivery_charges",
        rf"\bMy energy use and delivery\s*charges\s*(?P<amount>{_AMOUNT})",
        "Energy use and delivery charges",
    ),
    (
        "basic_charge",
        rf"\bBasic Charge{_FOR_DAYS}\s*(?P<amount>{_AMOUNT})",
        "Basic charge",
    ),
    (
        "energy_use_charge",
        rf"\bEnergy Use Charge\s*\([^)]{{1,180}}\){_FOR_DAYS}\s*(?P<amount>{_AMOUNT})",
        "Energy use charge",
    ),
    (
        "transmission_charge",
        rf"\bTransmission Charge\s*\([^)]{{1,180}}\){_FOR_DAYS}\s*(?P<amount>{_AMOUNT})",
        "Transmission charge",
    ),
    (
        "distribution_charge",
        rf"\bDistribution Charge\s*\([^)]{{1,180}}\){_FOR_DAYS}\s*(?P<amount>{_AMOUNT})",
        "Distribution charge",
    ),
    (
        "power_cost_adjustment",
        rf"\bPower Cost Adjustment\s*\([^)]{{1,180}}\){_FOR_DAYS}\s*(?P<amount>{_AMOUNT})",
        "Power cost adjustment",
    ),
    (
        "regulatory_adjustments",
        rf"\bRegulatory and utility operations\s*adjustments\s*(?P<amount>{_AMOUNT})",
        "Regulatory and utility operations adjustments",
    ),
    (
        "state_pass_throughs",
        rf"\bState required pass-throughs\s*and adjustments\s*(?P<amount>{_AMOUNT})",
        "State required pass-throughs and adjustments",
    ),
    (
        "program_charges",
        rf"\bMy selected program charges\s*and discounts\s*(?P<amount>{_AMOUNT})",
        "Selected program charges and discounts",
    ),
    (
        "green_future_charge",
        rf"\bGreen Future (?:Block|Choice)(?:\s*\([^)]{{1,180}}\))?{_FOR_DAYS}\s*(?P<amount>{_AMOUNT})",
        "Green Future charge",
    ),
    (
        "taxes_and_investments",
        rf"\bCity, county and state taxes and\s*investments\s*(?P<amount>{_AMOUNT})",
        "City, county and state taxes and investments",
    ),
    (
        "local_tax",
        rf"\bCity of .{{1,80}}? Tax\s*\([^)]{{1,40}}\){_FOR_DAYS}\s*(?P<amount>{_AMOUNT})",
        "Local tax",
    ),
    (
        "public_purpose_charge",
        rf"\bPublic Purpose Charge(?:\s*\([^)]{{1,40}}\))?{_FOR_DAYS}\s*(?P<amount>{_AMOUNT})",
        "Public Purpose charge",
    ),
)


def _build_metrics(text: str) -> dict[str, BillMetric]:
    metrics: dict[str, BillMetric] = {}
    payment = _search_decimal(
        text,
        rf"\bPayments through\s*{_DATE}\s*(?P<amount>{_AMOUNT})(?:\s*\(CR\))?",
        credit=True,
    )
    if payment is None:
        payment = _search_decimal(
            text,
            rf"\bpayments totaling\s+(?P<amount>{_AMOUNT})",
            credit=True,
        )
    if payment is not None:
        metrics["payment_received"] = BillMetric(
            key="payment_received",
            value=payment,
            unit="USD",
            label="Payment received",
        )
    for key, pattern, label in _METRIC_PATTERNS:
        values = [
            value
            for match in re.finditer(pattern, text, flags=re.IGNORECASE)
            if (value := _parse_decimal(match.group("amount"))) is not None
        ]
        if values:
            metrics[key] = BillMetric(
                key=key,
                value=sum(values, Decimal()),
                unit="USD",
                label=label,
            )
    return metrics


def _append_reconciliation_warnings(
    warnings: list[str],
    advisories: list[str],
    *,
    hints: BillParseHints,
    amount_due: Decimal | None,
    total_kwh: Decimal | None,
    period_start: date | None,
    period_end: date | None,
    multiple_service_locations: bool,
    metrics: dict[str, BillMetric],
) -> None:
    if (
        hints.expected_amount_due is not None
        and amount_due is not None
        and abs(hints.expected_amount_due - amount_due) > Decimal("0.01")
    ):
        warnings.append("amount_due_mismatch")
    if (
        hints.expected_total_kwh is not None
        and total_kwh is not None
        and abs(hints.expected_total_kwh - total_kwh) > Decimal("0.01")
    ):
        warnings.append("total_kwh_mismatch")
    if hints.expected_period_start is not None and period_start is not None:
        start_difference = abs((period_start - hints.expected_period_start).days)
        if start_difference > 1:
            if (
                multiple_service_locations
                and period_end is not None
                and period_start <= hints.expected_period_start <= period_end
            ):
                advisories.append("graphql_period_start_within_multi_service_range")
            else:
                warnings.append("period_start_mismatch")
    if (
        hints.expected_period_end is not None
        and period_end is not None
        and abs((period_end - hints.expected_period_end).days) > 1
    ):
        warnings.append("period_end_mismatch")

    energy_keys = (
        "basic_charge",
        "energy_use_charge",
        "transmission_charge",
        "distribution_charge",
        "power_cost_adjustment",
    )
    if "energy_delivery_charges" in metrics and all(key in metrics for key in energy_keys):
        component_total = sum((metrics[key].value for key in energy_keys), Decimal())
        section_total = metrics["energy_delivery_charges"].value
        if abs(component_total - section_total) > Decimal("0.02"):
            advisories.append("energy_charge_sum_mismatch")

    section_keys = (
        "energy_delivery_charges",
        "regulatory_adjustments",
        "state_pass_throughs",
        "program_charges",
        "taxes_and_investments",
    )
    if amount_due is not None and all(key in metrics for key in section_keys):
        section_total = sum((metrics[key].value for key in section_keys), Decimal())
        balance_forward = metrics.get("balance_forward")
        expected_total = amount_due - (balance_forward.value if balance_forward else Decimal())
        if abs(section_total - expected_total) > Decimal("0.02"):
            advisories.append("current_charge_sum_mismatch")


def normalize_bill_text(
    text: str,
    *,
    hints: BillParseHints,
    source_sha256: str | None = None,
) -> NormalizedBill:
    """Normalize PGE labels and reconcile the result with GraphQL bill values."""
    variants = [_flat_text(variant) for variant in text.split(_TEXT_VARIANT_SEPARATOR)]
    variants = [variant for variant in variants if variant]
    flat = " ".join(variants)
    multiple_service_locations = any(
        variant.lower().count("service address") > 1 or "your new address" in variant.lower() for variant in variants
    )
    due_date = _current_due_date(flat)
    period_start, period_end = _service_period(flat, hints)
    amount_due = _current_amount_due(flat, hints.expected_amount_due)
    total_kwh = _total_kwh(flat, hints.expected_total_kwh)
    metrics_by_variant = [_build_metrics(variant) for variant in variants]
    primary_metrics = max(metrics_by_variant, key=len, default={})
    metrics = dict(primary_metrics)
    for variant_metrics in metrics_by_variant:
        for key, metric in variant_metrics.items():
            metrics.setdefault(key, metric)

    warnings: list[str] = []
    advisories: list[str] = []
    for key, value in (
        ("due_date", due_date),
        ("period_start", period_start),
        ("period_end", period_end),
        ("amount_due", amount_due),
        ("total_kwh", total_kwh),
    ):
        if value is None:
            warnings.append(f"missing_{key}")
    _append_reconciliation_warnings(
        warnings,
        advisories,
        hints=hints,
        amount_due=amount_due,
        total_kwh=total_kwh,
        period_start=period_start,
        period_end=period_end,
        multiple_service_locations=multiple_service_locations,
        metrics=metrics,
    )
    unique_warnings = tuple(dict.fromkeys(warnings))
    unique_advisories = tuple(dict.fromkeys(advisories))
    confidence = round(
        max(0.0, 1.0 - 0.15 * len(unique_warnings) - 0.03 * len(unique_advisories)),
        2,
    )
    return NormalizedBill(
        statement_date=hints.statement_date,
        due_date=due_date,
        period_start=period_start,
        period_end=period_end,
        amount_due=amount_due,
        total_kwh=total_kwh,
        multiple_service_locations=multiple_service_locations,
        metrics=metrics,
        source_sha256=source_sha256,
        confidence=confidence,
        warnings=unique_warnings,
        advisories=unique_advisories,
    )


def as_history_samples(bill: NormalizedBill) -> list[HistorySample]:
    """Map a core-reconciled bill to samples, retaining advisories on the bill."""
    if not bill.safe_to_publish:
        raise ValueError("bill failed reconciliation and is unsafe to publish")
    samples: list[HistorySample] = []
    if bill.amount_due is not None:
        samples.append(HistorySample("pdf_amount_due", bill.statement_date, bill.amount_due, "USD"))
    if bill.total_kwh is not None:
        samples.append(HistorySample("pdf_total_kwh", bill.statement_date, bill.total_kwh, "kWh"))
    samples.extend(
        HistorySample(f"pdf_{metric.key}", bill.statement_date, metric.value, metric.unit)
        for metric in bill.metrics.values()
    )
    return samples


def _decimal_arg(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None


def _date_arg(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract normalized, PII-free values from a PGE bill PDF")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--bill-date", required=True, help="GraphQL bill date (YYYY-MM-DD)")
    parser.add_argument("--expected-amount-due")
    parser.add_argument("--expected-kwh")
    parser.add_argument("--expected-period-start")
    parser.add_argument("--expected-period-end")
    args = parser.parse_args()

    extracted = extract_pdf_text(args.pdf.read_bytes())
    bill = normalize_bill_text(
        extracted.text,
        hints=BillParseHints(
            statement_date=date.fromisoformat(args.bill_date),
            expected_amount_due=_decimal_arg(args.expected_amount_due),
            expected_total_kwh=_decimal_arg(args.expected_kwh),
            expected_period_start=_date_arg(args.expected_period_start),
            expected_period_end=_date_arg(args.expected_period_end),
        ),
        source_sha256=extracted.source_sha256,
    )
    print(json.dumps(bill.to_dict(), indent=2, sort_keys=True))
    return 0 if bill.safe_to_publish else 2


if __name__ == "__main__":
    raise SystemExit(main())
