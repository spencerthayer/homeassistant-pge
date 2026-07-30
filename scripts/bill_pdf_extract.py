"""Offline developer CLI for PGE bill PDF normalization.

Production parsing lives in ``custom_components.pge_energy.bill_pdf_parser``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from custom_components.pge_energy.bill_pdf_models import BillPdfForm, BillPdfParseHints
from custom_components.pge_energy.bill_pdf_parser import extract_pdf_text, normalize_bill_text


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
    parser.add_argument("--form", default="detailed", choices=("detailed", "simplified"))
    args = parser.parse_args()

    extracted = extract_pdf_text(args.pdf.read_bytes())
    hints = BillPdfParseHints(
        statement_date=date.fromisoformat(args.bill_date),
        expected_amount_due=_decimal_arg(args.expected_amount_due),
        expected_total_kwh=_decimal_arg(args.expected_kwh),
        expected_period_start=_date_arg(args.expected_period_start),
        expected_period_end=_date_arg(args.expected_period_end),
    )
    bill = normalize_bill_text(
        extracted.text,
        hints=hints,
        source_form=BillPdfForm(args.form),
        source_sha256=extracted.source_sha256,
    )
    print(json.dumps(bill.to_dict(), indent=2, sort_keys=True))
    return 0 if bill.safe_to_publish else 2


if __name__ == "__main__":
    sys.exit(main())
