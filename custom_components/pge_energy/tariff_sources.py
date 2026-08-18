"""Fetch and parse official PGE tariff sources for TOD and Basic rates.

Public unauthenticated endpoints:
- TOD pricing: ``/page-data/about/info/pricing-plans/time-of-day/page-data.json``
- Tariff catalog: ``/page-data/about/info/rates-and-regulatory/tariff/page-data.json``

The tariff catalog links to Standard Service PDFs whose Schedule 7 and
Schedule 125 rows provide the Basic comparison rate.

No Cognito, Apigee, or portal authentication is used.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .tod_tariff import (
    BasicComparisonRow,
    SourceInfo,
    TodTariffRow,
)

_LOGGER = logging.getLogger(__name__)

# Allowed PDF host for tariff documents.
_PDF_ALLOWED_HOSTS = ("assets.ctfassets.net",)
_PDF_MAX_BYTES = 10 * 1024 * 1024
_PDF_MAX_PAGES = 24
_PARSER_VERSION = 1

# Gatsby page-data URLs
_TOD_PAGE_DATA_URL = "https://portlandgeneral.com/page-data/about/info/pricing-plans/time-of-day/page-data.json"
_TARIFF_PAGE_DATA_URL = "https://portlandgeneral.com/page-data/about/info/rates-and-regulatory/tariff/page-data.json"


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Result of fetching a URL: body bytes, ETag, Last-Modified."""

    body: bytes
    etag: str | None = None
    last_modified: str | None = None
    status_code: int = 200


@dataclass(frozen=True, slots=True)
class TariffFetchError:
    """Typed failure for a source fetch/parse."""

    url: str
    reason: str
    status_code: int | None = None


@dataclass(frozen=True, slots=True)
class TodSourceResult:
    """Parsed TOD candidate from the PGE page-data."""

    rows: list[TodTariffRow]
    errors: list[str]


@dataclass(frozen=True, slots=True)
class BasicSourceResult:
    """Parsed Basic comparison candidates from price-summary PDFs."""

    rows: list[BasicComparisonRow]
    seen_urls: list[str]
    errors: list[str]


@dataclass(frozen=True, slots=True)
class TariffSourceUpdate:
    """Complete result of a tariff source check."""

    tod_result: TodSourceResult | None = None
    basic_result: BasicSourceResult | None = None
    fetch_errors: list[TariffFetchError] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Contentful rich-text / Gatsby JSON helpers
# ---------------------------------------------------------------------------


def _extract_text_nodes(node: Any) -> list[str]:
    """Recursively extract plain text from Contentful rich-text nodes."""
    texts: list[str] = []
    if isinstance(node, dict):
        if "value" in node and isinstance(node["value"], str):
            texts.append(node["value"])
        for child in node.get("content", []):
            texts.extend(_extract_text_nodes(child))
    elif isinstance(node, list):
        for item in node:
            texts.extend(_extract_text_nodes(item))
    return texts


def _find_contentful_modules(data: Any) -> list[dict[str, Any]]:
    """Walk Gatsby page-data JSON to find ContentfulModule entries."""
    modules: list[dict[str, Any]] = []
    if isinstance(data, dict):
        for key, val in data.items():
            if key == "contentful_module" and isinstance(val, dict):
                modules.append(val)
            else:
                modules.extend(_find_contentful_modules(val))
    elif isinstance(data, list):
        for item in data:
            modules.extend(_find_contentful_modules(item))
    return modules


def _find_document_lists(data: Any) -> list[dict[str, Any]]:
    """Find ContentfulModuleDocumentList entries in page-data JSON."""
    lists: list[dict[str, Any]] = []
    if isinstance(data, dict):
        if data.get("contentful_component_type") == "ContentfulModuleDocumentList":
            lists.append(data)
        for val in data.values():
            lists.extend(_find_document_lists(val))
    elif isinstance(data, list):
        for item in data:
            lists.extend(_find_document_lists(item))
    return lists


# ---------------------------------------------------------------------------
# TOD page-data parser
# ---------------------------------------------------------------------------

_RATE_PATTERN = re.compile(
    r"(?:off[\s-]*peak|off)[^$]*?(\d+\.?\d*)\s*(?:¢|cents?)\s*/\s*kWh",
    re.IGNORECASE,
)
_MID_PATTERN = re.compile(
    r"(?:mid[\s-]*peak|mid)[^$]*?(\d+\.?\d*)\s*(?:¢|cents?)\s*/\s*kWh",
    re.IGNORECASE,
)
_ON_PATTERN = re.compile(
    r"(?:on[\s-]*peak|on)[^$]*?(\d+\.?\d*)\s*(?:¢|cents?)\s*/\s*kWh",
    re.IGNORECASE,
)
_AS_OF_PATTERN = re.compile(r"as\s+of\s+(\w+\s+\d{1,2},?\s+\d{4})", re.IGNORECASE)


def parse_tod_page_data(raw_json: dict[str, Any]) -> TodSourceResult:
    """Parse the TOD page-data JSON for effective date and three period rates.

    Returns a :class:`TodSourceResult` with zero or one rows and any errors.
    """
    errors: list[str] = []
    rows: list[TodTariffRow] = []
    now_iso = datetime.now(UTC).isoformat()

    # Extract all text nodes from the page-data
    all_text = "\n".join(_extract_text_nodes(raw_json))

    # Find "As of" date
    date_match = _AS_OF_PATTERN.search(all_text)
    if not date_match:
        errors.append("No 'As of' date found in TOD page-data")
        return TodSourceResult(rows=rows, errors=errors)

    as_of_str = date_match.group(1)
    try:
        effective_date = _parse_as_of_date(as_of_str)
    except ValueError as exc:
        errors.append(f"Cannot parse 'As of' date {as_of_str!r}: {exc}")
        return TodSourceResult(rows=rows, errors=errors)

    # Find cents-per-kWh values
    off_match = _RATE_PATTERN.search(all_text)
    mid_match = _MID_PATTERN.search(all_text)
    on_match = _ON_PATTERN.search(all_text)

    if not (off_match and mid_match and on_match):
        missing = []
        if not off_match:
            missing.append("off-peak")
        if not mid_match:
            missing.append("mid-peak")
        if not on_match:
            missing.append("on-peak")
        errors.append(f"Missing rate values for: {', '.join(missing)}")
        return TodSourceResult(rows=rows, errors=errors)

    off_cents = float(off_match.group(1))
    mid_cents = float(mid_match.group(1))
    on_cents = float(on_match.group(1))

    # Validate on > mid > off
    if not (on_cents > mid_cents > off_cents):
        errors.append(f"Rate order invalid: off={off_cents}, mid={mid_cents}, on={on_cents}")
        return TodSourceResult(rows=rows, errors=errors)

    # Build SHA-256 of the source data for provenance
    sha256 = hashlib.sha256(f"tod:{effective_date}:{off_cents}:{mid_cents}:{on_cents}".encode()).hexdigest()

    source = SourceInfo(
        url=_TOD_PAGE_DATA_URL,
        title="PGE TOD pricing page (Gatsby page-data)",
        effective_date=effective_date,
        observed_at=now_iso,
        sha256=sha256,
        parser_version=_PARSER_VERSION,
    )

    row = TodTariffRow(
        effective_from=effective_date,
        off_peak=round(off_cents / 100, 5),
        mid_peak=round(mid_cents / 100, 5),
        on_peak=round(on_cents / 100, 5),
        source=source,
    )
    rows.append(row)
    return TodSourceResult(rows=rows, errors=errors)


def _parse_as_of_date(text: str) -> str:
    """Parse 'July 8, 2026' or 'July 8 2026' → '2026-07-08'."""
    text = text.strip().rstrip(".")
    # Try common formats
    for fmt in ("%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {text!r}")


# ---------------------------------------------------------------------------
# Tariff page-data / PDF discovery
# ---------------------------------------------------------------------------


def discover_tariff_documents(raw_json: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract unseen Standard Service and tariff-update documents from page-data.

    Returns a list of dicts with keys: url, title, effective_date_str, kind.
    """
    docs: list[dict[str, Any]] = []
    doc_lists = _find_document_lists(raw_json)

    for doc_list in doc_lists:
        header = ""
        header_nodes = _extract_text_nodes(doc_list.get("header", {}))
        if header_nodes:
            header = " ".join(header_nodes).strip().lower()

        documents = doc_list.get("documents") or []
        if not isinstance(documents, list):
            continue

        for doc in documents:
            if not isinstance(doc, dict):
                continue
            title = ""
            title_nodes = _extract_text_nodes(doc.get("title", {}))
            if title_nodes:
                title = " ".join(title_nodes).strip()

            asset = doc.get("asset") or {}
            url = ""
            if isinstance(asset, dict):
                url = asset.get("url", "")

            if not url or not title:
                continue

            # Determine kind from header
            kind = "unknown"
            if "price summaries" in header:
                kind = "price_summary"
            elif "tariff update" in header or "update" in header:
                kind = "tariff_update"

            # Extract effective date from title if possible
            date_match = _AS_OF_PATTERN.search(title) or re.search(
                r"effective\s+(\w+\s+\d{1,2},?\s+\d{4})", title, re.IGNORECASE
            )
            effective_date_str = ""
            if date_match:
                with contextlib.suppress(ValueError):
                    effective_date_str = _parse_as_of_date(date_match.group(1))

            docs.append(
                {
                    "url": url,
                    "title": title,
                    "effective_date_str": effective_date_str,
                    "kind": kind,
                }
            )

    return docs


# ---------------------------------------------------------------------------
# PDF parsing (Schedule 7 Basic + Schedule 125)
# ---------------------------------------------------------------------------


def parse_price_summary_pdf(
    pdf_bytes: bytes,
    doc_url: str,
    doc_title: str,
    doc_effective_date: str,
) -> BasicComparisonRow | TariffFetchError:
    """Extract Basic comparison rate from a Standard Service price-summary PDF.

    Parses the Schedule 7 Residential row and its Schedule 125 column.
    Returns a :class:`BasicComparisonRow` or a typed error.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        return TariffFetchError(
            url=doc_url,
            reason="pypdf not available",
        )

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except Exception as exc:
        return TariffFetchError(url=doc_url, reason=f"PDF read error: {exc}")

    if len(reader.pages) > _PDF_MAX_PAGES:
        return TariffFetchError(
            url=doc_url,
            reason=f"PDF exceeds {_PDF_MAX_PAGES} pages",
        )

    full_text = ""
    for page in reader.pages[:_PDF_MAX_PAGES]:
        try:
            full_text += page.extract_text() or ""
        except Exception:
            continue

    if not full_text.strip():
        return TariffFetchError(url=doc_url, reason="PDF extracted no text")

    # Look for Schedule 7 base rate and Schedule 125 in the text
    # This requires structured parsing of the table layout
    base_rate, schedule_125 = _extract_schedule7_basic(full_text)

    if base_rate is None or schedule_125 is None:
        return TariffFetchError(
            url=doc_url,
            reason="Could not extract Schedule 7 base + Schedule 125 from PDF",
        )

    rate = round(base_rate + schedule_125, 5)
    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    now_iso = datetime.now(UTC).isoformat()

    try:
        return BasicComparisonRow(
            effective_from=doc_effective_date,
            base_rate=base_rate,
            schedule_125=schedule_125,
            rate=rate,
            source=SourceInfo(
                url=doc_url,
                title=doc_title,
                effective_date=doc_effective_date,
                observed_at=now_iso,
                sha256=sha256,
                parser_version=_PARSER_VERSION,
            ),
        )
    except ValueError as exc:
        return TariffFetchError(url=doc_url, reason=f"Invalid Basic row: {exc}")


def _extract_schedule7_basic(text: str) -> tuple[float | None, float | None]:
    """Extract Schedule 7 BASE RATE and Schedule 125 from PDF text.

    Returns (base_rate, schedule_125) in dollars or (None, None).
    """
    # This is a heuristic parser for PGE's price-summary table layout.
    # The exact format varies between documents; we look for patterns.
    lines = text.split("\n")
    base_rate = None
    schedule_125 = None

    # Look for lines containing "Schedule 7" or "BASE RATE" and nearby values
    for _i, line in enumerate(lines):
        lower = line.lower()
        # Schedule 125 typically appears in the same row or nearby
        if "schedule 125" in lower or "sch 125" in lower:
            # Try to extract dollar values from this line
            values = _extract_dollar_values(line)
            if len(values) >= 2:
                # Schedule 125 is usually the last value
                candidate = values[-1]
                if candidate <= 2.0:  # Sanity: must be $/kWh, not ¢/kWh
                    schedule_125 = candidate

        if "base rate" in lower or "basic service" in lower:
            values = _extract_dollar_values(line)
            if values:
                candidate = values[0]
                if candidate <= 2.0:  # Sanity: must be $/kWh, not ¢/kWh
                    base_rate = candidate

        # Also check for the combined effective rate pattern
        if base_rate is not None and schedule_125 is not None:
            break

    # Fallback: look for the pattern "XX.XXX" / "X.XXX" which often appears
    # as base_rate / schedule_125 in the same row
    if base_rate is None or schedule_125 is None:
        for line in lines:
            # Match patterns like "11.289 5.619" or "11.289¢ 5.619¢"
            matches = re.findall(r"(\d{1,2}\.\d{3})\s*(?:¢|%|\s)\s*(\d\.\d{3})", line)
            if matches:
                for m in matches:
                    try:
                        candidate_base = float(m[0]) / 100  # cents to dollars
                        candidate_125 = float(m[1]) / 100
                        if 0.05 < candidate_base < 0.30 and 0.01 < candidate_125 < 0.15:
                            if base_rate is None:
                                base_rate = candidate_base
                            if schedule_125 is None:
                                schedule_125 = candidate_125
                    except ValueError:
                        continue
            if base_rate is not None and schedule_125 is not None:
                break

    # Another fallback: look for raw decimal patterns that match known ranges
    if base_rate is None or schedule_125 is None:
        all_values = _extract_dollar_values(text)
        candidates_base = [v for v in all_values if 0.05 < v < 0.30]
        candidates_125 = [v for v in all_values if 0.01 < v < 0.15]
        if candidates_base and candidates_125 and base_rate is None:
            base_rate = candidates_base[0]
        if candidates_125 and schedule_125 is None:
            schedule_125 = candidates_125[0]

    return base_rate, schedule_125


def _extract_dollar_values(text: str) -> list[float]:
    """Extract decimal dollar values (like 11.289, 5.619, 0.17630) from text."""
    values: list[float] = []
    # Match patterns like $11.289, 11.289, 11.289¢, etc.
    for match in re.finditer(r"\$?(\d{1,3}\.\d{2,5})\s*[¢%]?", text):
        try:
            v = float(match.group(1))
            values.append(v)
        except ValueError:
            continue
    return values


# Avoid circular import of io at module level.
import io  # noqa: E402
