"""Orchestrate bill PDF download, parse, statistics import, and retention."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant

from .bill_pdf import (
    async_download_bill_pdf,
    async_gc_bill_pdf_files,
    async_read_bill_pdf,
    async_write_bill_pdf,
    bill_pdf_local_url,
)
from .bill_pdf_models import BillPdfForm, BillPdfParseAttempt, BillPdfParseStatus
from .bill_pdf_parser import BillPdfParseError, BillPdfTextExtractionError, parse_bill_pdf_bytes
from .bill_pdf_statistics import async_import_bill_pdf_statistics
from .bill_pdf_store import (
    canonical_safe_records,
    eligible_bill_pdf_entries,
    hints_from_index_entry,
    mark_bill_pdf_statistics_imported,
    normalized_from_entry,
    parse_status_for_entry,
    recompute_canonical_form,
    set_bill_pdf_file,
    set_bill_pdf_parse_attempt,
    set_safe_normalized_bill_pdf,
    upsert_bill_pdf_identity,
)
from .billing_models import AccountSnapshot, LedgerEvent, LedgerEventType
from .const import (
    BILL_PDF_PARSER_VERSION,
    CONF_BILL_PDF_FORM,
    CONF_BILL_PDF_RETENTION,
    CONF_BILL_PDF_ROLLING_COUNT,
    CONF_DOWNLOAD_BILL_PDFS,
    CONF_INCLUDE_BILLING,
    DEFAULT_BILL_PDF_FORM,
    DEFAULT_BILL_PDF_RETENTION,
    DEFAULT_BILL_PDF_ROLLING_COUNT,
    DEFAULT_DOWNLOAD_BILL_PDFS,
    DEFAULT_INCLUDE_BILLING,
    SYNC_PHASE_DOWNLOADING_PDFS,
    SYNC_PHASE_IMPORTING_PDF_STATISTICS,
    SYNC_PHASE_PARSING_PDFS,
)
from .options import get_entry_option
from .store import async_save_import_state

if TYPE_CHECKING:
    from .coordinator import PGECoordinator

_LOGGER = logging.getLogger(__name__)


def index_bill_from_snapshot(store, snapshot: AccountSnapshot | None) -> None:
    """Upsert current bill identity from structured snapshot."""
    if snapshot is None or snapshot.bill is None:
        return
    bill = snapshot.bill
    if not bill.encrypted_bill_id or bill.bill_date is None:
        return
    upsert_bill_pdf_identity(
        store,
        bill_date=bill.bill_date.date().isoformat(),
        encrypted_bill_id=bill.encrypted_bill_id,
        expected_amount_due=_float_str(bill.amount_due),
        expected_total_kwh=_float_str(bill.kwh),
        expected_period_start=_dt_date_str(bill.period_start),
        expected_period_end=_dt_date_str(bill.period_end),
    )


def index_bill_from_ledger_event(store, event: LedgerEvent) -> None:
    """Upsert BILL ledger rows; ignore PAYMENT events."""
    if event.event_type != LedgerEventType.BILL:
        return
    if not event.encrypted_bill_id:
        return
    upsert_bill_pdf_identity(
        store,
        bill_date=event.date.date().isoformat(),
        encrypted_bill_id=event.encrypted_bill_id,
        expected_amount_due=_float_str(event.amount_due),
        expected_total_kwh=_float_str(event.kwh),
        expected_period_start=_dt_date_str(event.period_start),
        expected_period_end=_dt_date_str(event.period_end),
    )


async def async_sync_bill_pdfs(
    hass: HomeAssistant,
    coordinator: PGECoordinator,
    *,
    extra_bill_dates: set[str] | None = None,
    force_bill_dates: set[str] | None = None,
) -> dict[str, Any]:
    """Download, parse, import, and GC bill PDFs after structured billing."""
    entry = coordinator.entry
    store = coordinator.import_store
    if not bool(get_entry_option(entry, CONF_INCLUDE_BILLING, DEFAULT_INCLUDE_BILLING)):
        return {"skipped": True}
    if not bool(get_entry_option(entry, CONF_DOWNLOAD_BILL_PDFS, DEFAULT_DOWNLOAD_BILL_PDFS)):
        return {"skipped": True}

    account_key = coordinator.account_key
    account_id = coordinator.account_id
    auth = coordinator.auth_manager
    form_value = str(get_entry_option(entry, CONF_BILL_PDF_FORM, DEFAULT_BILL_PDF_FORM))
    retention_value = str(get_entry_option(entry, CONF_BILL_PDF_RETENTION, DEFAULT_BILL_PDF_RETENTION))
    rolling_count = int(get_entry_option(entry, CONF_BILL_PDF_ROLLING_COUNT, DEFAULT_BILL_PDF_ROLLING_COUNT))
    configured_form = BillPdfForm(form_value)

    eligible = eligible_bill_pdf_entries(
        store,
        retention=retention_value,
        configured_form=configured_form,
        rolling_count=rolling_count,
        extra_bill_dates=extra_bill_dates,
    )
    total = len(eligible)
    stats = {
        "total": total,
        "downloaded": 0,
        "reused": 0,
        "parsed": 0,
        "safe": 0,
        "advisory": 0,
        "failed": 0,
        "statistics_imported": 0,
    }
    keep_relpaths: set[str] = set()
    now = datetime.now(UTC)

    for index, bill_entry in enumerate(eligible, start=1):
        bill_date = bill_entry.bill_date
        _set_phase(coordinator, SYNC_PHASE_DOWNLOADING_PDFS, f"PDFs {index}/{total} — downloading statement")

        force = force_bill_dates is not None and bill_date in force_bill_dates
        existing_file = bill_entry.files.get(configured_form.value)
        pdf_bytes: bytes | None = None

        if existing_file is not None and not force:
            try:
                pdf_bytes = await async_read_bill_pdf(hass, account_key, existing_file.relpath)
                stats["reused"] += 1
            except FileNotFoundError:
                pdf_bytes = None

        if pdf_bytes is None:
            try:
                await auth.ensure_valid_token()
                pdf_bytes = await async_download_bill_pdf(
                    hass,
                    auth,
                    bill_entry.encrypted_bill_id,
                    configured_form,
                )
            except Exception as exc:  # noqa: BLE001
                _LOGGER.debug("Bill PDF download failed for %s: %s", bill_date, exc.__class__.__name__)
                set_bill_pdf_parse_attempt(
                    bill_entry,
                    configured_form.value,
                    BillPdfParseAttempt(
                        status=BillPdfParseStatus.DOWNLOAD_FAILED.value,
                        attempted_at=now.isoformat(),
                        source_sha256=None,
                        parser_version=BILL_PDF_PARSER_VERSION,
                        error_code="download_failed",
                    ),
                )
                stats["failed"] += 1
                continue

            if pdf_bytes is None:
                set_bill_pdf_parse_attempt(
                    bill_entry,
                    configured_form.value,
                    BillPdfParseAttempt(
                        status=BillPdfParseStatus.NOT_FOUND.value,
                        attempted_at=now.isoformat(),
                        source_sha256=None,
                        parser_version=BILL_PDF_PARSER_VERSION,
                        error_code="not_found",
                    ),
                )
                stats["failed"] += 1
                continue

            try:
                file_record = await async_write_bill_pdf(
                    hass,
                    account_key,
                    bill_date,
                    configured_form,
                    pdf_bytes,
                )
                set_bill_pdf_file(bill_entry, file_record)
                keep_relpaths.add(file_record.relpath)
                stats["downloaded"] += 1
            except Exception as exc:  # noqa: BLE001
                _LOGGER.debug("Bill PDF write failed for %s: %s", bill_date, exc.__class__.__name__)
                set_bill_pdf_parse_attempt(
                    bill_entry,
                    configured_form.value,
                    BillPdfParseAttempt(
                        status=BillPdfParseStatus.DOWNLOAD_FAILED.value,
                        attempted_at=now.isoformat(),
                        source_sha256=None,
                        parser_version=BILL_PDF_PARSER_VERSION,
                        error_code="write_failed",
                    ),
                )
                stats["failed"] += 1
                continue
        elif existing_file is not None:
            keep_relpaths.add(existing_file.relpath)

        current_file = bill_entry.files.get(configured_form.value)

        needs_parse = _needs_parse(bill_entry, configured_form.value, current_file)
        if needs_parse and pdf_bytes is not None:
            _set_phase(coordinator, SYNC_PHASE_PARSING_PDFS, f"PDFs {index}/{total} — extracting and reconciling")
            hints = hints_from_index_entry(bill_entry)
            try:
                normalized = await hass.async_add_executor_job(
                    partial(
                        parse_bill_pdf_bytes,
                        pdf_bytes,
                        hints=hints,
                        source_form=configured_form,
                    )
                )
            except BillPdfTextExtractionError:
                set_bill_pdf_parse_attempt(
                    bill_entry,
                    configured_form.value,
                    BillPdfParseAttempt(
                        status=BillPdfParseStatus.TEXT_UNAVAILABLE.value,
                        attempted_at=now.isoformat(),
                        source_sha256=current_file.source_sha256 if current_file else None,
                        parser_version=BILL_PDF_PARSER_VERSION,
                        error_code="text_unavailable",
                    ),
                )
                stats["failed"] += 1
            except (BillPdfParseError, Exception):  # noqa: BLE001
                set_bill_pdf_parse_attempt(
                    bill_entry,
                    configured_form.value,
                    BillPdfParseAttempt(
                        status=BillPdfParseStatus.PARSE_FAILED.value,
                        attempted_at=now.isoformat(),
                        source_sha256=current_file.source_sha256 if current_file else None,
                        parser_version=BILL_PDF_PARSER_VERSION,
                        error_code="parse_failed",
                    ),
                )
                stats["failed"] += 1
            else:
                stats["parsed"] += 1
                if normalized.safe_to_publish:
                    set_safe_normalized_bill_pdf(bill_entry, configured_form.value, normalized)
                    set_bill_pdf_parse_attempt(
                        bill_entry,
                        configured_form.value,
                        BillPdfParseAttempt(
                            status=BillPdfParseStatus.PARSED.value,
                            attempted_at=now.isoformat(),
                            source_sha256=normalized.source_sha256,
                            parser_version=normalized.parser_version,
                            advisories=list(normalized.advisories),
                        ),
                    )
                    stats["safe"] += 1
                    if normalized.advisories:
                        stats["advisory"] += 1
                else:
                    set_bill_pdf_parse_attempt(
                        bill_entry,
                        configured_form.value,
                        BillPdfParseAttempt(
                            status=BillPdfParseStatus.RECONCILIATION_FAILED.value,
                            attempted_at=now.isoformat(),
                            source_sha256=normalized.source_sha256,
                            parser_version=normalized.parser_version,
                            warnings=list(normalized.warnings),
                            advisories=list(normalized.advisories),
                            error_code="reconciliation_failed",
                        ),
                    )
                    stats["failed"] += 1

        recompute_canonical_form(bill_entry)

    _set_phase(coordinator, SYNC_PHASE_IMPORTING_PDF_STATISTICS, "PDFs — importing statement metrics")
    safe_records = canonical_safe_records(store)
    pending = any(
        bill_row.canonical_form
        and normalized_from_entry(bill_row) is not None
        and bill_row.statistics_imported_at is None
        for bill_row in store.bill_pdf_index.values()
    )
    if safe_records and pending:
        try:
            await async_import_bill_pdf_statistics(hass, account_key, account_id, safe_records)
            for bill_row in store.bill_pdf_index.values():
                if bill_row.canonical_form and normalized_from_entry(bill_row) is not None:
                    mark_bill_pdf_statistics_imported(bill_row, when=now)
            stats["statistics_imported"] = len(safe_records)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Bill PDF statistics import soft-failed: %s", exc.__class__.__name__)
            store.bill_pdf_last_error = "statistics_import_failed"
    else:
        stats["statistics_imported"] = 0

    try:
        await async_gc_bill_pdf_files(hass, account_key, keep_relpaths)
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Bill PDF GC failed", exc_info=True)

    store.bill_pdf_last_success = now.isoformat()
    if stats["failed"] == 0:
        store.bill_pdf_last_error = None
    await async_save_import_state(hass, entry.entry_id, store)

    coordinator.bill_pdf_summary = build_bill_pdf_summary(store, configured_form.value)
    return stats


async def async_reparse_bill_pdfs(
    hass: HomeAssistant,
    coordinator: PGECoordinator,
    *,
    bill_date: str | None = None,
) -> dict[str, Any]:
    """Reparse retained PDFs without network calls."""
    entry = coordinator.entry
    store = coordinator.import_store
    account_key = coordinator.account_key
    form_value = str(get_entry_option(entry, CONF_BILL_PDF_FORM, DEFAULT_BILL_PDF_FORM))
    configured_form = BillPdfForm(form_value)
    targets = []
    for entry_row in store.bill_pdf_index.values():
        if bill_date is not None and entry_row.bill_date != bill_date:
            continue
        if entry_row.files.get(configured_form.value):
            targets.append(entry_row)
    if bill_date is not None and not targets:
        raise ValueError("bill_date_not_found_or_not_retained")

    reparsed = 0
    for bill_entry in targets:
        file_record = bill_entry.files[configured_form.value]
        pdf_bytes = await async_read_bill_pdf(hass, account_key, file_record.relpath)
        hints = hints_from_index_entry(bill_entry)
        normalized = await hass.async_add_executor_job(
            partial(
                parse_bill_pdf_bytes,
                pdf_bytes,
                hints=hints,
                source_form=configured_form,
            )
        )
        if normalized.safe_to_publish:
            set_safe_normalized_bill_pdf(bill_entry, configured_form.value, normalized)
        reparsed += 1
        recompute_canonical_form(bill_entry)

    safe_records = canonical_safe_records(store)
    if safe_records:
        await async_import_bill_pdf_statistics(hass, account_key, coordinator.account_id, safe_records)
        now = datetime.now(UTC)
        for entry_row in store.bill_pdf_index.values():
            if entry_row.canonical_form and normalized_from_entry(entry_row) is not None:
                mark_bill_pdf_statistics_imported(entry_row, when=now)
    await async_save_import_state(hass, entry.entry_id, store)
    coordinator.bill_pdf_summary = build_bill_pdf_summary(store, configured_form.value)
    return {"reparsed": reparsed}


def build_bill_pdf_summary(store, configured_form: str) -> dict[str, Any]:
    """Sanitized coordinator/WS payload for the current bill PDF surface."""
    if not store.bill_pdf_index:
        return {}
    latest = max(store.bill_pdf_index.values(), key=lambda e: e.bill_date)
    file_record = latest.files.get(configured_form)
    canonical = normalized_from_entry(latest)
    status = parse_status_for_entry(latest, configured_form=configured_form)
    summary: dict[str, Any] = {
        "bill_date": latest.bill_date,
        "form": configured_form,
        "parse_status": status.value,
        "parser_version": BILL_PDF_PARSER_VERSION,
        "warnings": [],
        "advisories": [],
    }
    if file_record is not None:
        summary["path"] = file_record.relpath
        summary["url"] = bill_pdf_local_url(file_record.relpath)
        summary["source_sha256_prefix"] = file_record.source_sha256[:12]
    attempt = latest.parse_attempts_by_form.get(configured_form)
    if attempt is not None:
        summary["warnings"] = list(attempt.warnings)
        summary["advisories"] = list(attempt.advisories)
    if canonical is not None and canonical.safe_to_publish:
        summary["metrics"] = {
            key: {"value": str(metric.value), "unit": metric.unit, "label": metric.label}
            for key, metric in sorted(canonical.metrics.items())
        }
        if canonical.amount_due is not None:
            summary.setdefault("metrics", {})["amount_due"] = {
                "value": str(canonical.amount_due),
                "unit": "USD",
                "label": "Amount due",
            }
        if canonical.total_kwh is not None:
            summary.setdefault("metrics", {})["total_kwh"] = {
                "value": str(canonical.total_kwh),
                "unit": "kWh",
                "label": "Total kWh",
            }
    return summary


def _needs_parse(bill_entry, form: str, file_record) -> bool:
    if file_record is None:
        return False
    existing = bill_entry.normalized_by_form.get(form)
    if existing is None:
        return True
    record = normalized_from_entry(bill_entry, form)
    if record is None:
        return True
    if record.source_sha256 != file_record.source_sha256:
        return True
    if record.parser_version < BILL_PDF_PARSER_VERSION:
        return True
    hints = hints_from_index_entry(bill_entry)
    return record.reconciliation_fingerprint != hints.reconciliation_fingerprint


def _set_phase(coordinator: PGECoordinator, phase: str, message: str) -> None:
    if not coordinator.sync_job_in_progress:
        return
    coordinator.update_sync_progress(phase=phase, message=message)


def _float_str(value: float | None) -> str | None:
    if value is None:
        return None
    return str(Decimal(str(value)).quantize(Decimal("0.01")))


def _dt_date_str(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.date().isoformat()
