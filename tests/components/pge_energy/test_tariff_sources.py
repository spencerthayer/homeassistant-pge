"""Tests for tariff_sources page-data / document discovery parsing.

The PGE Gatsby page-data endpoints migrated to a new schema (``__typename``
discriminator, JSON-encoded rich text under ``raw``, ``documentListHeader`` /
``file.url`` fields, and ``"per kWh"`` instead of ``"/kWh"``).  These tests
lock the parser against that schema plus the legacy inline-rich-text format.
"""

from __future__ import annotations

import json

from custom_components.pge_energy.tariff_sources import (
    _extract_text_nodes,
    _find_document_lists,
    discover_tariff_documents,
    parse_tod_page_data,
)


def _rich_text(value: str) -> dict:
    """Build a Contentful rich-text document node containing one text value."""
    return {
        "nodeType": "document",
        "data": {},
        "content": [
            {
                "nodeType": "paragraph",
                "data": {},
                "content": [{"nodeType": "text", "value": value, "marks": [], "data": {}}],
            }
        ],
    }


def _tod_page_data() -> dict:
    return {
        "result": {
            "data": {
                "allContentfulPageBasic": {
                    "nodes": [
                        {
                            "contentEntries": [
                                {
                                    "__typename": "ContentfulElementCta",
                                    "shortDescription": {
                                        "raw": json.dumps(
                                            _rich_text(
                                                "As of July 8, 2026: Time of Day prices decreased "
                                                "due to recent rate adjustments."
                                            )
                                        )
                                    },
                                },
                                {
                                    "__typename": "ContentfulModuleAccordion",
                                    "accordionItems": [
                                        {
                                            "tabBody": {
                                                "raw": json.dumps(
                                                    {
                                                        "nodeType": "document",
                                                        "data": {},
                                                        "content": [
                                                            {
                                                                "nodeType": "paragraph",
                                                                "data": {},
                                                                "content": [
                                                                    {
                                                                        "nodeType": "text",
                                                                        "value": "Off-Peak: 8.93¢ per kWh",
                                                                        "marks": [],
                                                                        "data": {},
                                                                    }
                                                                ],
                                                            },
                                                            {
                                                                "nodeType": "paragraph",
                                                                "data": {},
                                                                "content": [
                                                                    {
                                                                        "nodeType": "text",
                                                                        "value": "Mid-Peak: 16.70¢ per kWh",
                                                                        "marks": [],
                                                                        "data": {},
                                                                    }
                                                                ],
                                                            },
                                                            {
                                                                "nodeType": "paragraph",
                                                                "data": {},
                                                                "content": [
                                                                    {
                                                                        "nodeType": "text",
                                                                        "value": "On-Peak: 43.13¢ per kWh",
                                                                        "marks": [],
                                                                        "data": {},
                                                                    }
                                                                ],
                                                            },
                                                        ],
                                                    }
                                                )
                                            }
                                        }
                                    ],
                                },
                            ]
                        }
                    ]
                }
            }
        }
    }


def _tariff_page_data() -> dict:
    return {
        "result": {
            "data": {
                "allContentfulPageList": {
                    "nodes": [
                        {
                            "contentEntries": [
                                {
                                    "__typename": "ContentfulModuleDocumentList",
                                    "documentListHeader": "Price summaries",
                                    "documents": [
                                        {
                                            "title": "Standard Service Schedules - Effective July 8, 2026",
                                            "file": {
                                                "url": "//assets.ctfassets.net/416ywc1laqmd/abc/standard-service.pdf"
                                            },
                                        }
                                    ],
                                },
                                {
                                    "__typename": "ContentfulModuleDocumentList",
                                    "documentListHeader": "Tariff update announcements",
                                    "documents": [
                                        {
                                            "title": "07/08/26 - Advice No. 26-24",
                                            "file": {"url": "//assets.ctfassets.net/416ywc1laqmd/abc/update.pdf"},
                                        }
                                    ],
                                },
                            ]
                        }
                    ]
                }
            }
        }
    }


def test_extract_text_nodes_reaches_raw_rich_text():
    data = _tod_page_data()
    texts = _extract_text_nodes(data)
    joined = "\n".join(texts)
    assert "As of July 8, 2026" in joined
    assert "8.93¢ per kWh" in joined
    assert "16.70¢ per kWh" in joined
    assert "43.13¢ per kWh" in joined


def test_extract_text_nodes_legacy_inline_content():
    legacy = {
        "header": {
            "content": [
                {"nodeType": "text", "value": "Price summaries"},
            ]
        }
    }
    assert "Price summaries" in _extract_text_nodes(legacy)


def test_parse_tod_page_data_new_schema():
    result = parse_tod_page_data(_tod_page_data())
    assert result.errors == []
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.effective_from == "2026-07-08"
    assert row.off_peak == 0.0893
    assert row.mid_peak == 0.167
    assert row.on_peak == 0.4313


def test_parse_tod_page_data_rejects_wrong_rate_order():
    data = _tod_page_data()
    # Replace on-peak with a value lower than mid-peak.
    data["result"]["data"]["allContentfulPageBasic"]["nodes"][0]["contentEntries"][1]["accordionItems"][0]["tabBody"][
        "raw"
    ] = json.dumps(_rich_text("Off-Peak: 8.93¢ per kWh\nMid-Peak: 16.70¢ per kWh\nOn-Peak: 5.00¢ per kWh"))
    result = parse_tod_page_data(data)
    assert result.rows == []
    assert result.errors


def test_find_document_lists_new_typename():
    data = _tariff_page_data()
    lists = _find_document_lists(data)
    assert len(lists) == 2
    assert {lst.get("documentListHeader") for lst in lists} == {
        "Price summaries",
        "Tariff update announcements",
    }


def test_find_document_lists_legacy_key():
    legacy = {"contentful_component_type": "ContentfulModuleDocumentList", "documents": []}
    assert _find_document_lists(legacy) == [legacy]


def test_discover_tariff_documents_new_schema():
    docs = discover_tariff_documents(_tariff_page_data())
    by_kind: dict[str, list[dict]] = {}
    for doc in docs:
        by_kind.setdefault(doc["kind"], []).append(doc)

    price = by_kind["price_summary"][0]
    assert price["url"] == "https://assets.ctfassets.net/416ywc1laqmd/abc/standard-service.pdf"
    assert "Standard Service" in price["title"]
    assert price["effective_date_str"] == "2026-07-08"

    update = by_kind["tariff_update"][0]
    assert update["url"].startswith("https://assets.ctfassets.net")
    assert "Advice No. 26-24" in update["title"]
