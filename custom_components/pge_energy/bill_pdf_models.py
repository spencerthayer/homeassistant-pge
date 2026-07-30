"""Typed models for PGE bill PDF download, parsing, and normalized storage."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Literal

from .const import BILL_PDF_PARSER_VERSION


class BillPdfForm(StrEnum):
    """Portal REST PDF form selection."""

    DETAILED = "detailed"
    SIMPLIFIED = "simplified"


class BillPdfRetention(StrEnum):
    """Binary file retention policy (normalized records are independent)."""

    LATEST = "latest"
    ALL_IMPORTED = "all_imported"
    ROLLING_N = "rolling_n"


class BillPdfParseStatus(StrEnum):
    """Sanitized parse/download lifecycle for sensors and Store."""

    NOT_DOWNLOADED = "not_downloaded"
    NOT_FOUND = "not_found"
    DOWNLOAD_FAILED = "download_failed"
    DOWNLOADED = "downloaded"
    PARSER_STALE = "parser_stale"
    TEXT_UNAVAILABLE = "text_unavailable"
    PARSE_FAILED = "parse_failed"
    RECONCILIATION_FAILED = "reconciliation_failed"
    STATISTICS_PENDING = "statistics_pending"
    PARSED = "parsed"


@dataclass(frozen=True, slots=True)
class BillPdfParseHints:
    """GraphQL values used to identify and reconcile a bill."""

    statement_date: date
    expected_amount_due: Decimal | None = None
    expected_total_kwh: Decimal | None = None
    expected_period_start: date | None = None
    expected_period_end: date | None = None

    @property
    def reconciliation_fingerprint(self) -> str:
        """Deterministic hash of non-secret GraphQL hint tuple."""
        parts = (
            self.statement_date.isoformat(),
            _decimal_str(self.expected_amount_due),
            _decimal_str(self.expected_total_kwh),
            self.expected_period_start.isoformat() if self.expected_period_start else "",
            self.expected_period_end.isoformat() if self.expected_period_end else "",
        )
        return hashlib.sha256("|".join(parts).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class BillPdfMetric:
    """One normalized, statement-scoped numeric value."""

    key: str
    value: Decimal
    unit: Literal["USD"]
    label: str

    def to_dict(self) -> dict[str, str]:
        return {
            "key": self.key,
            "value": str(self.value),
            "unit": self.unit,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BillPdfMetric:
        return cls(
            key=str(data["key"]),
            value=Decimal(str(data["value"])),
            unit="USD",
            label=str(data["label"]),
        )


@dataclass(frozen=True, slots=True)
class ExtractedBillPdfText:
    """In-memory extraction result; text is never serialized to Store."""

    text: str
    page_count: int
    source_sha256: str


@dataclass(frozen=True, slots=True)
class NormalizedBillPdf:
    """PII-free normalized data suitable for Store and statistics."""

    statement_date: date
    source_form: BillPdfForm
    due_date: date | None
    period_start: date | None
    period_end: date | None
    amount_due: Decimal | None
    total_kwh: Decimal | None
    multiple_service_locations: bool
    metrics: Mapping[str, BillPdfMetric]
    source_sha256: str
    reconciliation_fingerprint: str
    parser_version: int
    confidence: float
    warnings: tuple[str, ...] = ()
    advisories: tuple[str, ...] = ()

    @property
    def safe_to_publish(self) -> bool:
        return not self.warnings

    def to_dict(self) -> dict[str, Any]:
        return {
            "statement_date": self.statement_date.isoformat(),
            "source_form": self.source_form.value,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "amount_due": _decimal_str(self.amount_due),
            "total_kwh": _decimal_str(self.total_kwh),
            "multiple_service_locations": self.multiple_service_locations,
            "metrics": {key: metric.to_dict() for key, metric in sorted(self.metrics.items())},
            "source_sha256": self.source_sha256,
            "reconciliation_fingerprint": self.reconciliation_fingerprint,
            "parser_version": self.parser_version,
            "confidence": self.confidence,
            "warnings": list(self.warnings),
            "advisories": list(self.advisories),
            "safe_to_publish": self.safe_to_publish,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NormalizedBillPdf:
        metrics_raw = data.get("metrics") or {}
        metrics = {str(k): BillPdfMetric.from_dict(v) for k, v in metrics_raw.items()}
        return cls(
            statement_date=date.fromisoformat(str(data["statement_date"])),
            source_form=BillPdfForm(str(data.get("source_form", BillPdfForm.DETAILED.value))),
            due_date=_optional_date(data.get("due_date")),
            period_start=_optional_date(data.get("period_start")),
            period_end=_optional_date(data.get("period_end")),
            amount_due=_optional_decimal(data.get("amount_due")),
            total_kwh=_optional_decimal(data.get("total_kwh")),
            multiple_service_locations=bool(data.get("multiple_service_locations", False)),
            metrics=metrics,
            source_sha256=str(data.get("source_sha256", "")),
            reconciliation_fingerprint=str(data.get("reconciliation_fingerprint", "")),
            parser_version=int(data.get("parser_version", BILL_PDF_PARSER_VERSION)),
            confidence=float(data.get("confidence", 0.0)),
            warnings=tuple(str(w) for w in (data.get("warnings") or [])),
            advisories=tuple(str(a) for a in (data.get("advisories") or [])),
        )


@dataclass(frozen=True, slots=True)
class BillPdfStatementSample:
    """One statement-dated statistic sample derived from a safe normalized bill."""

    metric_key: str
    start: date
    value: Decimal
    unit: str


@dataclass
class BillPdfFileRecord:
    """Retained binary metadata for one form of a bill."""

    form: str
    relpath: str
    source_sha256: str
    byte_size: int
    page_count: int | None
    fetched_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "form": self.form,
            "relpath": self.relpath,
            "source_sha256": self.source_sha256,
            "byte_size": self.byte_size,
            "page_count": self.page_count,
            "fetched_at": self.fetched_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BillPdfFileRecord:
        page_count = data.get("page_count")
        return cls(
            form=str(data["form"]),
            relpath=str(data["relpath"]),
            source_sha256=str(data["source_sha256"]),
            byte_size=int(data["byte_size"]),
            page_count=int(page_count) if page_count is not None else None,
            fetched_at=str(data["fetched_at"]),
        )


@dataclass
class BillPdfParseAttempt:
    """Latest parse attempt for one form (may be unsafe)."""

    status: str
    attempted_at: str
    source_sha256: str | None
    parser_version: int
    warnings: list[str] = field(default_factory=list)
    advisories: list[str] = field(default_factory=list)
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "attempted_at": self.attempted_at,
            "source_sha256": self.source_sha256,
            "parser_version": self.parser_version,
            "warnings": list(self.warnings),
            "advisories": list(self.advisories),
            "error_code": self.error_code,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BillPdfParseAttempt:
        return cls(
            status=str(data.get("status", BillPdfParseStatus.PARSE_FAILED.value)),
            attempted_at=str(data.get("attempted_at", "")),
            source_sha256=data.get("source_sha256"),
            parser_version=int(data.get("parser_version", BILL_PDF_PARSER_VERSION)),
            warnings=[str(w) for w in (data.get("warnings") or [])],
            advisories=[str(a) for a in (data.get("advisories") or [])],
            error_code=data.get("error_code"),
        )


@dataclass
class BillPdfIndexEntry:
    """One bill identity plus per-form files, normalized records, and parse status."""

    bill_date: str
    encrypted_bill_id: str
    expected_amount_due: str | None = None
    expected_total_kwh: str | None = None
    expected_period_start: str | None = None
    expected_period_end: str | None = None
    files: dict[str, BillPdfFileRecord] = field(default_factory=dict)
    normalized_by_form: dict[str, dict[str, Any]] = field(default_factory=dict)
    parse_attempts_by_form: dict[str, BillPdfParseAttempt] = field(default_factory=dict)
    canonical_form: str | None = None
    statistics_imported_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "bill_date": self.bill_date,
            "encrypted_bill_id": self.encrypted_bill_id,
            "expected_amount_due": self.expected_amount_due,
            "expected_total_kwh": self.expected_total_kwh,
            "expected_period_start": self.expected_period_start,
            "expected_period_end": self.expected_period_end,
            "files": {k: v.to_dict() for k, v in self.files.items()},
            "normalized_by_form": dict(self.normalized_by_form),
            "parse_attempts_by_form": {k: v.to_dict() for k, v in self.parse_attempts_by_form.items()},
            "canonical_form": self.canonical_form,
            "statistics_imported_at": self.statistics_imported_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BillPdfIndexEntry:
        files_raw = data.get("files") or {}
        attempts_raw = data.get("parse_attempts_by_form") or {}
        return cls(
            bill_date=str(data["bill_date"]),
            encrypted_bill_id=str(data["encrypted_bill_id"]),
            expected_amount_due=data.get("expected_amount_due"),
            expected_total_kwh=data.get("expected_total_kwh"),
            expected_period_start=data.get("expected_period_start"),
            expected_period_end=data.get("expected_period_end"),
            files={str(k): BillPdfFileRecord.from_dict(v) for k, v in files_raw.items()},
            normalized_by_form={str(k): dict(v) for k, v in (data.get("normalized_by_form") or {}).items()},
            parse_attempts_by_form={str(k): BillPdfParseAttempt.from_dict(v) for k, v in attempts_raw.items()},
            canonical_form=data.get("canonical_form"),
            statistics_imported_at=data.get("statistics_imported_at"),
        )


def _decimal_str(value: Decimal | None) -> str:
    return str(value) if value is not None else ""


def _optional_decimal(raw: Any) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw))
    except InvalidOperation:
        return None


def _optional_date(raw: Any) -> date | None:
    if not raw:
        return None
    return date.fromisoformat(str(raw))
