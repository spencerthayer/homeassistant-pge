"""Bill PDF Store helpers and canonical record selection."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from .bill_pdf_models import (
    BillPdfFileRecord,
    BillPdfForm,
    BillPdfIndexEntry,
    BillPdfParseAttempt,
    BillPdfParseHints,
    BillPdfParseStatus,
    BillPdfRetention,
    NormalizedBillPdf,
)
from .const import BILL_PDF_PARSER_VERSION

if TYPE_CHECKING:
    from .store import ImportStoreData


def upsert_bill_pdf_identity(
    store: ImportStoreData,
    *,
    bill_date: str,
    encrypted_bill_id: str,
    expected_amount_due: str | None = None,
    expected_total_kwh: str | None = None,
    expected_period_start: str | None = None,
    expected_period_end: str | None = None,
) -> BillPdfIndexEntry:
    """Insert or update a bill identity keyed by ``bill_date``."""
    entry = store.bill_pdf_index.get(bill_date)
    if entry is None:
        entry = BillPdfIndexEntry(bill_date=bill_date, encrypted_bill_id=encrypted_bill_id)
        store.bill_pdf_index[bill_date] = entry
    else:
        entry.encrypted_bill_id = encrypted_bill_id
    if expected_amount_due is not None:
        entry.expected_amount_due = expected_amount_due
    if expected_total_kwh is not None:
        entry.expected_total_kwh = expected_total_kwh
    if expected_period_start is not None:
        entry.expected_period_start = expected_period_start
    if expected_period_end is not None:
        entry.expected_period_end = expected_period_end
    return entry


def set_bill_pdf_file(
    entry: BillPdfIndexEntry,
    file_record: BillPdfFileRecord,
) -> None:
    entry.files[file_record.form] = file_record


def set_bill_pdf_parse_attempt(entry: BillPdfIndexEntry, form: str, attempt: BillPdfParseAttempt) -> None:
    entry.parse_attempts_by_form[form] = attempt


def set_safe_normalized_bill_pdf(entry: BillPdfIndexEntry, form: str, record: NormalizedBillPdf) -> None:
    if not record.safe_to_publish:
        raise ValueError("refusing to store unsafe normalized bill PDF")
    entry.normalized_by_form[form] = record.to_dict()
    entry.statistics_imported_at = None
    recompute_canonical_form(entry)


def mark_bill_pdf_statistics_imported(entry: BillPdfIndexEntry, *, when: datetime | None = None) -> None:
    ts = (when or datetime.now(UTC)).isoformat()
    entry.statistics_imported_at = ts


def remove_bill_pdf_file_metadata(entry: BillPdfIndexEntry, form: str) -> None:
    entry.files.pop(form, None)


def hints_from_index_entry(entry: BillPdfIndexEntry) -> BillPdfParseHints:
    return BillPdfParseHints(
        statement_date=date.fromisoformat(entry.bill_date),
        expected_amount_due=_optional_decimal(entry.expected_amount_due),
        expected_total_kwh=_optional_decimal(entry.expected_total_kwh),
        expected_period_start=_optional_date(entry.expected_period_start),
        expected_period_end=_optional_date(entry.expected_period_end),
    )


def normalized_from_entry(entry: BillPdfIndexEntry, form: str | None = None) -> NormalizedBillPdf | None:
    target_form = form or entry.canonical_form
    if not target_form:
        return None
    raw = entry.normalized_by_form.get(target_form)
    if not raw:
        return None
    return NormalizedBillPdf.from_dict(raw)


def canonical_safe_records(store: ImportStoreData) -> list[NormalizedBillPdf]:
    records: list[NormalizedBillPdf] = []
    for entry in store.bill_pdf_index.values():
        record = normalized_from_entry(entry)
        if record is not None and record.safe_to_publish:
            records.append(record)
    return records


def eligible_bill_pdf_entries(
    store: ImportStoreData,
    *,
    retention: BillPdfRetention | str,
    configured_form: BillPdfForm | str,
    rolling_count: int = 12,
    extra_bill_dates: set[str] | None = None,
) -> list[BillPdfIndexEntry]:
    """Return bill index entries eligible for binary retention/download."""
    retention_value = retention.value if isinstance(retention, BillPdfRetention) else str(retention)
    entries = sorted(
        store.bill_pdf_index.values(),
        key=lambda e: e.bill_date,
        reverse=True,
    )
    if not entries:
        return []

    selected: list[BillPdfIndexEntry]
    if retention_value == BillPdfRetention.LATEST.value:
        selected = [entries[0]]
    elif retention_value == BillPdfRetention.ALL_IMPORTED.value:
        selected = list(entries)
    elif retention_value == BillPdfRetention.ROLLING_N.value:
        selected = entries[: max(1, rolling_count)]
    else:
        selected = [entries[0]]

    if extra_bill_dates:
        by_date = {e.bill_date: e for e in entries}
        for bill_date in extra_bill_dates:
            if bill_date in by_date and by_date[bill_date] not in selected:
                selected.append(by_date[bill_date])
        selected.sort(key=lambda e: e.bill_date, reverse=True)
    return selected


def recompute_canonical_form(entry: BillPdfIndexEntry) -> None:
    """Pick canonical form per plan rules."""
    hints = hints_from_index_entry(entry)
    fingerprint = hints.reconciliation_fingerprint
    candidates: list[tuple[str, NormalizedBillPdf]] = []
    for form, raw in entry.normalized_by_form.items():
        record = NormalizedBillPdf.from_dict(raw)
        if not record.safe_to_publish:
            continue
        if record.reconciliation_fingerprint != fingerprint:
            continue
        candidates.append((form, record))

    if not candidates:
        return

    current_parser = [c for c in candidates if c[1].parser_version >= BILL_PDF_PARSER_VERSION]
    pool = current_parser or candidates

    detailed = [c for c in pool if c[0] == BillPdfForm.DETAILED.value]
    if detailed:
        entry.canonical_form = BillPdfForm.DETAILED.value
        return

    pool.sort(key=lambda c: (-len(c[1].metrics), c[0]))
    entry.canonical_form = pool[0][0]


def parse_status_for_entry(
    entry: BillPdfIndexEntry,
    *,
    configured_form: str,
) -> BillPdfParseStatus:
    file_record = entry.files.get(configured_form)
    attempt = entry.parse_attempts_by_form.get(configured_form)
    canonical = normalized_from_entry(entry)

    if file_record is None:
        if attempt and attempt.status == BillPdfParseStatus.NOT_FOUND.value:
            return BillPdfParseStatus.NOT_FOUND
        if attempt and attempt.status == BillPdfParseStatus.DOWNLOAD_FAILED.value:
            return BillPdfParseStatus.DOWNLOAD_FAILED
        return BillPdfParseStatus.NOT_DOWNLOADED

    if canonical is not None and canonical.parser_version < BILL_PDF_PARSER_VERSION:
        return BillPdfParseStatus.PARSER_STALE

    if attempt is None:
        return BillPdfParseStatus.DOWNLOADED

    try:
        return BillPdfParseStatus(attempt.status)
    except ValueError:
        return BillPdfParseStatus.PARSE_FAILED


def _optional_decimal(raw: str | None) -> Decimal | None:
    if raw is None or raw == "":
        return None
    return Decimal(str(raw))


def _optional_date(raw: str | None) -> date | None:
    if not raw:
        return None
    return date.fromisoformat(raw)
