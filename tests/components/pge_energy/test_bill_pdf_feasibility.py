"""Feasibility contract for extracting normalized history from PGE bill PDFs.

This is deliberately separate from the bill-download shipping plan. It proves
the pure extraction/normalization seam without network calls, real bills, or
Home Assistant recorder writes.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from custom_components.pge_energy.bill_pdf_models import BillPdfParseHints
from custom_components.pge_energy.bill_pdf_parser import (
    BillPdfTextExtractionError,
    as_statement_samples,
    extract_pdf_text,
    normalize_bill_text,
)

_TEXT_VARIANT_SEPARATOR = "\n<<<PGE_PLAIN_TEXT_FALLBACK>>>\n"
_PYPDF_FIXED_WIDTH_LOGGER = "pypdf._text_extraction._layout_mode._fixed_width_page"

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "billing"


def _build_text_pdf(lines: list[str], *, rotated_lines: list[str] | None = None) -> bytes:
    """Build a tiny text-backed PDF without a fixture-generation dependency."""
    escaped = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines]
    text_ops = ["BT", "/F1 10 Tf", "48 748 Td"]
    for index, line in enumerate(escaped):
        if index:
            text_ops.append("0 -14 Td")
        text_ops.append(f"({line}) Tj")
    text_ops.append("ET")
    for index, line in enumerate(rotated_lines or []):
        escaped_line = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        text_ops.extend(
            [
                "BT",
                "/F1 10 Tf",
                f"0 1 -1 0 {560 - (index * 14)} 120 Tm",
                f"({escaped_line}) Tj",
                "ET",
            ]
        )
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


def _build_pdf_with_form_xobject(*, page_lines: list[str], form_lines: list[str]) -> bytes:
    """Build a PDF whose Form XObject text is invisible to layout mode."""

    def _text_stream(lines: list[str], *, start_y: int = 748) -> bytes:
        escaped = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines]
        ops = ["BT", "/F1 10 Tf", f"48 {start_y} Td"]
        for index, line in enumerate(escaped):
            if index:
                ops.append("0 -14 Td")
            ops.append(f"({line}) Tj")
        ops.append("ET")
        return "\n".join(ops).encode("ascii")

    page_stream = _text_stream(page_lines)
    form_stream = _text_stream(form_lines, start_y=700)
    # Page paints the Form XObject after its own text.
    page_contents = page_stream + b"\n/Fm1 Do\n"

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> /XObject << /Fm1 6 0 R >> >> "
            b"/Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(page_contents)).encode("ascii") + b" >>\nstream\n" + page_contents + b"\nendstream",
        (
            b"<< /Type /XObject /Subtype /Form /FormType 1 /BBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Length "
            + str(len(form_stream)).encode("ascii")
            + b" >>\nstream\n"
            + form_stream
            + b"\nendstream"
        ),
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


def _hydrate_masked_fixture(name: str) -> str:
    text = (FIXTURES / name).read_text()
    return re.sub(r"<D(\d+)>", lambda match: "1" * int(match.group(1)), text)


def _hints(
    *,
    amount_due: str = "169.50",
    total_kwh: str = "790",
) -> BillPdfParseHints:
    return BillPdfParseHints(
        statement_date=date(2025, 2, 13),
        expected_amount_due=Decimal(amount_due),
        expected_total_kwh=Decimal(total_kwh),
        expected_period_start=date(2025, 1, 11),
        expected_period_end=date(2025, 2, 11),
    )


def test_real_layout_fixtures_are_tokenized_and_contain_no_raw_digits():
    for name in (
        "real_single_service_layout_masked.txt",
        "real_multi_service_layout_masked.txt",
    ):
        text = (FIXTURES / name).read_text()
        without_digit_tokens = re.sub(r"<D\d+>", "", text)

        assert "<CUSTOMER_NAME>" in text
        assert "<ACCOUNT_ID>" in text
        assert "<SERVICE_ADDRESS>" in text or "<OLD_SERVICE_ADDRESS>" in text
        assert not re.search(r"\d", without_digit_tokens)
        assert "@" not in text


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
        with pytest.raises(BillPdfTextExtractionError, match="not a PDF"):
            extract_pdf_text(b"<html>portal error</html>")

    def test_marks_image_only_or_blank_pdf_as_not_extractable(self):
        with pytest.raises(BillPdfTextExtractionError, match="no extractable text"):
            extract_pdf_text(_build_text_pdf([]))

    def test_keeps_rotated_text_that_layout_mode_omits(self):
        data = _build_text_pdf(
            ["Portland General Electric", "Amount due $169.50"],
            rotated_lines=["Due date 3/5/25", "790 kWh this month"],
        )

        extracted = extract_pdf_text(data)

        assert "Due date 3/5/25" in extracted.text
        assert "790 kWh this month" in extracted.text

    def test_layout_variant_retains_rotated_stub_text(self):
        data = _build_text_pdf(
            ["Portland General Electric", "Amount due $169.50"],
            rotated_lines=["STUB Due date 3/5/25", "STUB 790 kWh"],
        )

        extracted = extract_pdf_text(data)
        layout_part = extracted.text.split(_TEXT_VARIANT_SEPARATOR)[0]

        assert "STUB Due date 3/5/25" in layout_part
        assert "STUB 790 kWh" in layout_part

    def test_rotated_text_discovery_warnings_are_silenced(self, caplog: pytest.LogCaptureFixture):
        data = _build_text_pdf(
            ["Portland General Electric", "Amount due $169.50"],
            rotated_lines=["STUB Due date 3/5/25"],
        )

        with caplog.at_level(logging.WARNING, logger=_PYPDF_FIXED_WIDTH_LOGGER):
            extract_pdf_text(data)

        rotated_messages = [record.getMessage() for record in caplog.records if "Rotated text discovered" in record.getMessage()]
        assert rotated_messages == []

    def test_plain_variant_carries_form_xobject_text(self):
        data = _build_pdf_with_form_xobject(
            page_lines=["Portland General Electric", "Amount due $169.50"],
            form_lines=["FORM XObject total use 790 kWh"],
        )

        extracted = extract_pdf_text(data)
        parts = extracted.text.split(_TEXT_VARIANT_SEPARATOR)
        layout_part = parts[0]
        plain_part = parts[1] if len(parts) > 1 else ""

        assert "Portland General Electric" in extracted.text
        assert "FORM XObject total use 790 kWh" in extracted.text
        # Layout mode does not recurse Form XObjects; plain fallback must.
        assert "FORM XObject total use 790 kWh" not in layout_part
        assert "FORM XObject total use 790 kWh" in plain_part


class TestBillNormalization:
    def test_real_single_service_golden_layout_reconciles(self):
        bill = normalize_bill_text(
            _hydrate_masked_fixture("real_single_service_layout_masked.txt"),
            hints=BillPdfParseHints(
                statement_date=date(2011, 1, 15),
                expected_amount_due=Decimal("111.11"),
                expected_total_kwh=Decimal("1111"),
                expected_period_start=date(2011, 1, 1),
                expected_period_end=date(2011, 1, 1),
            ),
        )

        assert bill.safe_to_publish is True
        assert bill.warnings == ()
        assert {
            "basic_charge",
            "energy_use_charge",
            "transmission_charge",
            "distribution_charge",
            "power_cost_adjustment",
            "regulatory_adjustments",
            "state_pass_throughs",
            "program_charges",
            "green_future_charge",
            "local_tax",
            "public_purpose_charge",
        } <= bill.metrics.keys()

    def test_real_multi_service_golden_layout_reconciles(self):
        bill = normalize_bill_text(
            _hydrate_masked_fixture("real_multi_service_layout_masked.txt"),
            hints=BillPdfParseHints(
                statement_date=date(2011, 1, 15),
                expected_amount_due=Decimal("111.11"),
                expected_total_kwh=Decimal("122"),
                expected_period_start=date(2011, 1, 1),
                expected_period_end=date(2011, 1, 1),
            ),
        )

        assert bill.multiple_service_locations is True
        assert bill.total_kwh == Decimal("122")
        assert bill.safe_to_publish is True
        assert bill.warnings == ()
        assert {
            "energy_delivery_charges",
            "basic_charge",
            "energy_use_charge",
            "power_cost_adjustment",
            "regulatory_adjustments",
            "state_pass_throughs",
            "program_charges",
            "green_future_charge",
            "taxes_and_investments",
            "local_tax",
            "public_purpose_charge",
        } <= bill.metrics.keys()

    def test_merges_complementary_metrics_across_extraction_variants(self):
        layout_variant = _sample_text().replace(
            "Regulatory and utility operations adjustments 2.56",
            "",
        )
        plain_variant = _sample_text().replace(
            "Basic Charge 13.00",
            "",
        )

        bill = normalize_bill_text(
            f"{layout_variant}\n<<<PGE_PLAIN_TEXT_FALLBACK>>>\n{plain_variant}",
            hints=_hints(),
        )

        assert bill.metrics["basic_charge"].value == Decimal("13.00")
        assert bill.metrics["regulatory_adjustments"].value == Decimal("2.56")
        assert bill.metrics["energy_delivery_charges"].value == Decimal("148.92")
        assert bill.safe_to_publish is True

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
        assert bill.metrics["green_future_charge"].value == Decimal("1.88")
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

    def test_does_not_parse_previous_amount_due_as_current_amount_due(self):
        text = _sample_text().replace(
            "Amount due\n$169.50\nDue date\n3/5/25\n",
            "",
        )

        bill = normalize_bill_text(text, hints=_hints())

        assert bill.amount_due == Decimal("169.50")
        assert bill.warnings == ()

    def test_understands_pay_amount_by_date_wording(self):
        text = (
            _sample_text()
            .replace(
                "Amount due\n$169.50\nDue date\n3/5/25",
                "Please pay $169.50 by 3/5/25",
            )
            .replace(
                "Amount due 3/5/25 $169.50",
                "",
            )
        )

        bill = normalize_bill_text(text, hints=_hints())

        assert bill.amount_due == Decimal("169.50")
        assert bill.due_date == date(2025, 3, 5)
        assert bill.warnings == ()

    def test_handles_glued_plain_text_from_real_pge_layout(self):
        text = (
            _sample_text()
            .replace("790 kWh this month", "790kWhthis month")
            .replace("delivery charges", "deliverycharges")
            .replace("operations adjustments", "operationsadjustments")
            .replace("pass-throughs and", "pass-throughsand")
            .replace("taxes and investments", "taxes andinvestments")
        )

        bill = normalize_bill_text(text, hints=_hints())

        assert bill.total_kwh == Decimal("790")
        assert bill.metrics["energy_delivery_charges"].value == Decimal("148.92")
        assert bill.metrics["regulatory_adjustments"].value == Decimal("2.56")
        assert bill.metrics["state_pass_throughs"].value == Decimal("11.36")
        assert bill.metrics["taxes_and_investments"].value == Decimal("4.78")
        assert bill.warnings == ()

    def test_handles_for_days_between_charge_label_formula_and_total(self):
        text = (
            _sample_text()
            .replace("Basic Charge 13.00", "Basic Charge for 11 days 13.00")
            .replace(
                "Energy Use Charge (790.000 kWh x $0.0354) 27.97",
                "Energy Use Charge (790.000 kWh x $0.0354) for 11 days 27.97",
            )
            .replace(
                "City of Sample City Tax (1.5%) 2.39",
                "City of Sample City Tax (1.5%) for 11 days 2.39",
            )
        )

        bill = normalize_bill_text(text, hints=_hints())

        assert bill.metrics["basic_charge"].value == Decimal("13.00")
        assert bill.metrics["energy_use_charge"].value == Decimal("27.97")
        assert bill.metrics["local_tax"].value == Decimal("2.39")
        assert bill.warnings == ()

    def test_normalizes_green_future_block_and_choice_to_one_metric(self):
        block = normalize_bill_text(_sample_text(), hints=_hints())
        choice = normalize_bill_text(
            _sample_text().replace("Green Future Block", "Green Future Choice"),
            hints=_hints(),
        )

        assert block.metrics["green_future_charge"].value == Decimal("1.88")
        assert choice.metrics["green_future_charge"].value == Decimal("1.88")

    def test_sums_multiple_meter_totals_when_pdf_has_no_account_total(self):
        text = _sample_text().replace(
            "790 kWh this month",
            "Meter number Service period Schedule Current read - Previous read = Total use "
            "METER-A 1/11/25 to 1/20/25 7 1000 647 353 kWh "
            "METER-B 1/21/25 to 2/11/25 7 2000 1563 437 kWh",
        )

        bill = normalize_bill_text(text, hints=_hints())

        assert bill.total_kwh == Decimal("790")
        assert bill.warnings == ()

    def test_sums_equal_meter_totals_without_deduplicating_real_meters(self):
        text = _sample_text().replace(
            "790 kWh this month",
            "Meter number Service period Schedule Current read - Previous read = Total use "
            "METER-A 1/11/25 to 1/20/25 7 1000 605 395 kWh "
            "METER-B 1/21/25 to 2/11/25 7 2000 1605 395 kWh",
        )

        bill = normalize_bill_text(text, hints=_hints())

        assert bill.total_kwh == Decimal("790")
        assert bill.warnings == ()

    def test_allows_glued_service_period_and_one_day_api_start_offset(self):
        text = _sample_text().replace(
            "Service period 1/11/25 to 2/11/25",
            "Service period 1/12/25 to2/11/25",
        )
        hints = BillPdfParseHints(
            statement_date=date(2025, 2, 13),
            expected_amount_due=Decimal("169.50"),
            expected_total_kwh=Decimal("790"),
            expected_period_start=date(2025, 1, 11),
            expected_period_end=date(2025, 2, 11),
        )

        bill = normalize_bill_text(text, hints=hints)

        assert bill.period_start == date(2025, 1, 12)
        assert bill.period_end == date(2025, 2, 11)
        assert "period_start_mismatch" not in bill.warnings
        assert bill.safe_to_publish is True

    def test_selects_matching_service_period_from_multi_service_bill(self):
        text = _sample_text().replace(
            "Service period 1/11/25 to 2/11/25",
            "Service period 12/20/24 to1/10/25 Service period 1/11/25 to2/11/25",
        )

        bill = normalize_bill_text(text, hints=_hints())

        assert bill.period_start == date(2025, 1, 11)
        assert bill.period_end == date(2025, 2, 11)
        assert bill.warnings == ()
        assert bill.safe_to_publish is True

    def test_optional_line_item_sum_difference_is_advisory_not_blocking(self):
        text = _sample_text().replace("Basic Charge 13.00", "Basic Charge 14.00")

        bill = normalize_bill_text(text, hints=_hints())

        assert bill.warnings == ()
        assert "energy_charge_sum_mismatch" in bill.advisories
        assert bill.safe_to_publish is True
        assert as_statement_samples(bill)

    def test_multi_service_overall_period_can_contain_graphql_segment(self):
        text = (
            _sample_text()
            .replace(
                "Service address 100 Test Street",
                "Service address 100 Old Street Service address 200 New Street",
            )
            .replace(
                "Service period 1/11/25 to 2/11/25",
                "Service period 1/2/25 to 2/11/25",
            )
        )

        bill = normalize_bill_text(text, hints=_hints())

        assert bill.multiple_service_locations is True
        assert bill.period_start == date(2025, 1, 2)
        assert bill.period_end == date(2025, 2, 11)
        assert bill.warnings == ()
        assert "graphql_period_start_within_multi_service_range" in bill.advisories
        assert bill.safe_to_publish is True

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

        samples = {sample.metric_key: sample for sample in as_statement_samples(bill)}

        assert samples["amount_due"].start == date(2025, 2, 13)
        assert samples["amount_due"].value == Decimal("169.50")
        assert samples["amount_due"].unit == "USD"
        assert samples["total_kwh"].unit == "kWh"
        assert samples["basic_charge"].value == Decimal("13.00")
