"""Store schema v2 migration and bill PDF index helpers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from custom_components.pge_energy.bill_pdf_models import BillPdfForm, NormalizedBillPdf
from custom_components.pge_energy.bill_pdf_store import (
    eligible_bill_pdf_entries,
    recompute_canonical_form,
    set_safe_normalized_bill_pdf,
    upsert_bill_pdf_identity,
)
from custom_components.pge_energy.store import ImportStoreData


def test_store_v1_payload_migrates_with_empty_bill_pdf_index():
    legacy = {
        "schema_version": 1,
        "account_key": "acct1234",
        "billing_history_offset": 15,
        "billing_history_complete": True,
        "completed_local_dates": ["2025-01-01"],
    }
    loaded = ImportStoreData.from_dict(legacy)
    assert loaded.schema_version == 1
    assert loaded.billing_history_offset == 15
    assert loaded.completed_local_dates == ["2025-01-01"]
    assert loaded.bill_pdf_index == {}


def test_bill_pdf_identity_upsert_and_canonical_selection():
    store = ImportStoreData(account_key="acct1234")
    entry = upsert_bill_pdf_identity(
        store,
        bill_date="2025-02-13",
        encrypted_bill_id="enc-id",
        expected_amount_due="169.50",
        expected_total_kwh="790",
        expected_period_start="2025-01-11",
        expected_period_end="2025-02-11",
    )
    record = NormalizedBillPdf(
        statement_date=date(2025, 2, 13),
        source_form=BillPdfForm.DETAILED,
        due_date=date(2025, 3, 5),
        period_start=date(2025, 1, 11),
        period_end=date(2025, 2, 11),
        amount_due=Decimal("169.50"),
        total_kwh=Decimal("790"),
        multiple_service_locations=False,
        metrics={},
        source_sha256="abc",
        reconciliation_fingerprint=entry.expected_amount_due and "x" or "",
        parser_version=1,
        confidence=1.0,
    )
    # Use hints fingerprint from store helper path
    from custom_components.pge_energy.bill_pdf_store import hints_from_index_entry

    hints = hints_from_index_entry(entry)
    record = NormalizedBillPdf(
        statement_date=date(2025, 2, 13),
        source_form=BillPdfForm.DETAILED,
        due_date=date(2025, 3, 5),
        period_start=date(2025, 1, 11),
        period_end=date(2025, 2, 11),
        amount_due=Decimal("169.50"),
        total_kwh=Decimal("790"),
        multiple_service_locations=False,
        metrics={},
        source_sha256="abc",
        reconciliation_fingerprint=hints.reconciliation_fingerprint,
        parser_version=1,
        confidence=1.0,
    )
    set_safe_normalized_bill_pdf(entry, BillPdfForm.DETAILED.value, record)
    recompute_canonical_form(entry)
    assert entry.canonical_form == BillPdfForm.DETAILED.value

    eligible = eligible_bill_pdf_entries(store, retention="latest", configured_form=BillPdfForm.DETAILED)
    assert len(eligible) == 1
    assert eligible[0].bill_date == "2025-02-13"
