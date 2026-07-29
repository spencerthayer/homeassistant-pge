"""Feasibility contract for extracting normalized history from PGE bill PDFs.

This is deliberately separate from the bill-download shipping plan. It proves
the pure extraction/normalization seam without network calls, real bills, or
Home Assistant recorder writes.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.bill_pdf_extract import (
    BillParseHints,
    PDFTextExtractionError,
    as_history_samples,
    extract_pdf_text,
    normalize_bill_text,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "billing"


def _build_text_pdf(lines: list[str]) -> bytes:
    """Build a tiny text-backed PDF without a fixture-generation dependency."""
    escaped = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines]
    text_ops = ["BT", "/F1 10 Tf", "48 748 Td"]
    for index, line in enumerate(escaped):
        if index:
            text_ops.append("0 -14 Td")
        text_ops.append(f"({line}) Tj")
    text_ops.append("ET")
    stream = "\n".join(text_ops).encode("ascii")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for object_number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{object_number} 0 obj\n".encode())
        pdf.extend(body)
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend((f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n").encode())
    return bytes(pdf)


def _sample_text() -> str:
    return (FIXTURES / "sample_bill_extracted.txt").read_text()


def _hints(
    *,
    amount_due: str = "169.50",
    total_kwh: str = "790",
) -> BillParseHints:
    return BillParseHints(
        statement_date=date(2025, 2, 13),
        expected_amount_due=Decimal(amount_due),
        expected_total_kwh=Decimal(total_kwh),
        expected_period_start=date(2025, 1, 11),
        expected_period_end=date(2025, 2, 11),
    )


class TestPDFTextExtraction:
    def test_extracts_text_from_pdf_bytes_without_writing_to_disk(self):
        data = _build_text_pdf(
            [
                "Portland General Electric",
                "Service period 1/11/25 to 2/11/25",
                "Amount due $169.50",
            ]
        )

        extracted = extract_pdf_text(data)

        assert extracted.page_count == 1
        assert extracted.source_sha256
        assert "Portland General Electric" in extracted.text
        assert "Amount due $169.50" in extracted.text

    def test_rejects_non_pdf_bytes(self):
        with pytest.raises(PDFTextExtractionError, match="not a PDF"):
            extract_pdf_text(b"<html>portal error</html>")

    def test_marks_image_only_or_blank_pdf_as_not_extractable(self):
        with pytest.raises(PDFTextExtractionError, match="no extractable text"):
            extract_pdf_text(_build_text_pdf([]))


class TestBillNormalization:
    def test_normalizes_public_sample_layout_into_typed_data(self):
        bill = normalize_bill_text(_sample_text(), hints=_hints(), source_sha256="fixture-sha")

        assert bill.statement_date == date(2025, 2, 13)
        assert bill.due_date == date(2025, 3, 5)
        assert bill.period_start == date(2025, 1, 11)
        assert bill.period_end == date(2025, 2, 11)
        assert bill.amount_due == Decimal("169.50")
        assert bill.total_kwh == Decimal("790")
        assert bill.metrics["payment_received"].value == Decimal("-167.89")
        assert bill.metrics["energy_delivery_charges"].value == Decimal("148.92")
        assert bill.metrics["basic_charge"].value == Decimal("13.00")
        assert bill.metrics["energy_use_charge"].value == Decimal("27.97")
        assert bill.metrics["transmission_charge"].value == Decimal("6.81")
        assert bill.metrics["distribution_charge"].value == Decimal("55.41")
        assert bill.metrics["power_cost_adjustment"].value == Decimal("45.73")
        assert bill.metrics["regulatory_adjustments"].value == Decimal("2.56")
        assert bill.metrics["state_pass_throughs"].value == Decimal("11.36")
        assert bill.metrics["program_charges"].value == Decimal("1.88")
        assert bill.metrics["green_future_block"].value == Decimal("1.88")
        assert bill.metrics["taxes_and_investments"].value == Decimal("4.78")
        assert bill.metrics["public_purpose_charge"].value == Decimal("2.39")
        assert bill.warnings == ()
        assert bill.confidence == 1.0

    def test_handles_wrapped_labels_and_value_on_next_line(self):
        text = (
            _sample_text()
            .replace(
                "State required pass-throughs and adjustments 11.36",
                "State required pass-throughs\nand adjustments\n11.36",
            )
            .replace(
                "Payments through 2/5/25 167.89 (CR)",
                "Payments through 2/5/25\n167.89 (CR)",
            )
        )

        bill = normalize_bill_text(text, hints=_hints())

        assert bill.metrics["state_pass_throughs"].value == Decimal("11.36")
        assert bill.metrics["payment_received"].value == Decimal("-167.89")

    def test_does_not_confuse_per_kwh_rate_with_line_total(self):
        bill = normalize_bill_text(_sample_text(), hints=_hints())

        assert bill.metrics["energy_use_charge"].value == Decimal("27.97")
        assert bill.metrics["distribution_charge"].value == Decimal("55.41")

    def test_graphql_mismatch_lowers_confidence_and_blocks_publish(self):
        bill = normalize_bill_text(
            _sample_text(),
            hints=_hints(amount_due="999.99", total_kwh="999"),
        )

        assert "amount_due_mismatch" in bill.warnings
        assert "total_kwh_mismatch" in bill.warnings
        assert bill.confidence < 1.0
        assert bill.safe_to_publish is False

    def test_serialized_data_omits_raw_text_and_personal_identifiers(self):
        bill = normalize_bill_text(_sample_text(), hints=_hints())

        serialized = str(bill.to_dict())

        assert "0000000000" not in serialized
        assert "100 Test Street" not in serialized
        assert "Sample Customer" not in serialized
        assert "raw_text" not in serialized

    def test_history_samples_are_statement_dated_and_unit_normalized(self):
        bill = normalize_bill_text(_sample_text(), hints=_hints())

        samples = {sample.key: sample for sample in as_history_samples(bill)}

        assert samples["pdf_amount_due"].start == date(2025, 2, 13)
        assert samples["pdf_amount_due"].value == Decimal("169.50")
        assert samples["pdf_amount_due"].unit == "USD"
        assert samples["pdf_total_kwh"].unit == "kWh"
        assert samples["pdf_basic_charge"].value == Decimal("13.00")
