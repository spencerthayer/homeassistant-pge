"""Production PGE bill PDF text extraction and normalization."""

from __future__ import annotations

import hashlib
import itertools
import re
import unicodedata
import warnings
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO

from .bill_pdf_models import (
    BillPdfForm,
    BillPdfMetric,
    BillPdfParseHints,
    BillPdfStatementSample,
    ExtractedBillPdfText,
    NormalizedBillPdf,
)
from .const import BILL_PDF_MAX_BYTES, BILL_PDF_MAX_PAGES, BILL_PDF_PARSER_VERSION

_DATE = r"\d{1,2}/\d{1,2}/(?:\d{2}|\d{4})"
_AMOUNT = r"-?\$?\s*\(?\d[\d,]*\.\d{2}\)?"
_NUMBER = r"\d[\d,]*(?:\.\d+)?"
_FOR_DAYS = r"(?:\s*for\s*\d+\s*days)?"
_TEXT_VARIANT_SEPARATOR = "\n<<<PGE_PLAIN_TEXT_FALLBACK>>>\n"


class BillPdfTextExtractionError(ValueError):
    """The PDF cannot safely provide plaintext for normalization."""


class BillPdfParseError(ValueError):
    """Bounded parse failure without embedding extracted text."""


def validate_pdf_bytes(data: bytes) -> None:
    """Reject invalid, oversized, or encrypted PDFs before extraction."""
    if not data.startswith(b"%PDF-"):
        raise BillPdfTextExtractionError("response is not a PDF")
    if len(data) > BILL_PDF_MAX_BYTES:
        raise BillPdfTextExtractionError(f"PDF exceeds {BILL_PDF_MAX_BYTES} byte safety limit")


def sha256_pdf(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extract_pdf_text(data: bytes) -> ExtractedBillPdfText:
    """Extract layout and plain variants from an in-memory, text-backed PDF."""
    validate_pdf_bytes(data)

    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise BillPdfTextExtractionError("pypdf is required for PDF text extraction") from exc

    try:
        reader = PdfReader(BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise BillPdfTextExtractionError("encrypted PDFs are not supported")
        page_count = len(reader.pages)
        if page_count > BILL_PDF_MAX_PAGES:
            raise BillPdfTextExtractionError(f"PDF exceeds {BILL_PDF_MAX_PAGES} page safety limit")
        layout_pages: list[str] = []
        plain_pages: list[str] = []
        for page in reader.pages:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="Rotated text discovered. Output will be incomplete.",
                    category=UserWarning,
                )
                try:
                    layout_text = page.extract_text(
                        extraction_mode="layout",
                        layout_mode_space_vertically=False,
                    )
                except TypeError:  # pragma: no cover
                    layout_text = page.extract_text()
            plain_text = page.extract_text() or ""
            layout_pages.append(layout_text or "")
            plain_pages.append(plain_text)
    except BillPdfTextExtractionError:
        raise
    except Exception as exc:
        raise BillPdfTextExtractionError("unable to read PDF") from exc

    layout_document = "\n\f\n".join(layout_pages)
    plain_document = "\n\f\n".join(plain_pages)
    if plain_document.strip() and plain_document != layout_document:
        text = f"{layout_document}{_TEXT_VARIANT_SEPARATOR}{plain_document}"
    else:
        text = layout_document
    text = text.replace("\x00", "")
    if len(re.sub(r"\W", "", text)) < 12:
        raise BillPdfTextExtractionError("PDF contains no extractable text; OCR would be required")
    return ExtractedBillPdfText(
        text=text,
        page_count=page_count,
        source_sha256=sha256_pdf(data),
    )


def normalize_bill_text(
    text: str,
    *,
    hints: BillPdfParseHints,
    source_form: BillPdfForm = BillPdfForm.DETAILED,
    source_sha256: str | None = None,
) -> NormalizedBillPdf:
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

    warning_list: list[str] = []
    advisories: list[str] = []
    for key, value in (
        ("due_date", due_date),
        ("period_start", period_start),
        ("period_end", period_end),
        ("amount_due", amount_due),
        ("total_kwh", total_kwh),
    ):
        if value is None:
            warning_list.append(f"missing_{key}")
    _append_reconciliation_warnings(
        warning_list,
        advisories,
        hints=hints,
        amount_due=amount_due,
        total_kwh=total_kwh,
        period_start=period_start,
        period_end=period_end,
        multiple_service_locations=multiple_service_locations,
        metrics=metrics,
    )
    unique_warnings = tuple(dict.fromkeys(warning_list))
    unique_advisories = tuple(dict.fromkeys(advisories))
    confidence = round(
        max(0.0, 1.0 - 0.15 * len(unique_warnings) - 0.03 * len(unique_advisories)),
        2,
    )
    digest = source_sha256 or ""
    return NormalizedBillPdf(
        statement_date=hints.statement_date,
        source_form=source_form,
        due_date=due_date,
        period_start=period_start,
        period_end=period_end,
        amount_due=amount_due,
        total_kwh=total_kwh,
        multiple_service_locations=multiple_service_locations,
        metrics=metrics,
        source_sha256=digest,
        reconciliation_fingerprint=hints.reconciliation_fingerprint,
        parser_version=BILL_PDF_PARSER_VERSION,
        confidence=confidence,
        warnings=unique_warnings,
        advisories=unique_advisories,
    )


def parse_bill_pdf_bytes(
    data: bytes,
    *,
    hints: BillPdfParseHints,
    source_form: BillPdfForm,
) -> NormalizedBillPdf:
    """Extract and normalize a PDF from bytes."""
    extracted = extract_pdf_text(data)
    return normalize_bill_text(
        extracted.text,
        hints=hints,
        source_form=source_form,
        source_sha256=extracted.source_sha256,
    )


def as_statement_samples(bill: NormalizedBillPdf) -> list[BillPdfStatementSample]:
    """Map a core-reconciled bill to statement samples."""
    if not bill.safe_to_publish:
        raise ValueError("bill failed reconciliation and is unsafe to publish")
    samples: list[BillPdfStatementSample] = []
    if bill.amount_due is not None:
        samples.append(
            BillPdfStatementSample("amount_due", bill.statement_date, bill.amount_due, "USD"),
        )
    if bill.total_kwh is not None:
        samples.append(
            BillPdfStatementSample("total_kwh", bill.statement_date, bill.total_kwh, "kWh"),
        )
    samples.extend(
        BillPdfStatementSample(metric.key, bill.statement_date, metric.value, metric.unit)
        for metric in bill.metrics.values()
    )
    return samples


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
        positive = [candidate for candidate in candidates if candidate > 0]
        for size in range(2, min(4, len(positive)) + 1):
            for subset in itertools.combinations(positive, size):
                total = sum(subset, Decimal())
                if abs(total - expected) <= Decimal("0.01"):
                    return total
    return candidates[0] if candidates else None


def _service_period(text: str, hints: BillPdfParseHints) -> tuple[date | None, date | None]:
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
    ("balance_forward", rf"\bBalance forward\s*(?P<amount>{_AMOUNT})", "Balance forward"),
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
    ("basic_charge", rf"\bBasic Charge{_FOR_DAYS}\s*(?P<amount>{_AMOUNT})", "Basic charge"),
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


def _build_metrics(text: str) -> dict[str, BillPdfMetric]:
    metrics: dict[str, BillPdfMetric] = {}
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
        metrics["payment_received"] = BillPdfMetric(
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
            metrics[key] = BillPdfMetric(
                key=key,
                value=sum(values, Decimal()),
                unit="USD",
                label=label,
            )
    return metrics


def _append_reconciliation_warnings(
    warnings_out: list[str],
    advisories: list[str],
    *,
    hints: BillPdfParseHints,
    amount_due: Decimal | None,
    total_kwh: Decimal | None,
    period_start: date | None,
    period_end: date | None,
    multiple_service_locations: bool,
    metrics: dict[str, BillPdfMetric],
) -> None:
    if (
        hints.expected_amount_due is not None
        and amount_due is not None
        and abs(hints.expected_amount_due - amount_due) > Decimal("0.01")
    ):
        warnings_out.append("amount_due_mismatch")
    if (
        hints.expected_total_kwh is not None
        and total_kwh is not None
        and abs(hints.expected_total_kwh - total_kwh) > Decimal("0.01")
    ):
        warnings_out.append("total_kwh_mismatch")
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
                warnings_out.append("period_start_mismatch")
    if (
        hints.expected_period_end is not None
        and period_end is not None
        and abs((period_end - hints.expected_period_end).days) > 1
    ):
        warnings_out.append("period_end_mismatch")

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
