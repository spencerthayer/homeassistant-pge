"""Tests for the domain-global tariff updater.

PGE stopped publishing an "As of <date>" sentence on the TOD page (Oct 2026).
A TOD row must then be dated by the newest effective date published on the
tariff page, and an unchanged rate triple must not mint a catalog row at all,
otherwise the catalog grows one observation-dated duplicate per daily check.
"""

from __future__ import annotations

import json

import pytest

from custom_components.pge_energy.tariff_sources import BasicSourceResult, TodSourceResult
from custom_components.pge_energy.tariff_store import TariffStoreData
from custom_components.pge_energy.tariff_updater import (
    TariffUpdaterCoordinator,
    _rates_match_latest,
    discover_latest_effective_date,
)
from custom_components.pge_energy.tod_tariff import (
    SourceInfo,
    TodTariffRow,
    prune_redundant_tod_rows,
)

_LIVE_RATES = {"off_peak": 0.0893, "mid_peak": 0.167, "on_peak": 0.4313}


def _row(effective_from: str, **rates: float) -> TodTariffRow:
    return TodTariffRow(
        effective_from=effective_from,
        **{**_LIVE_RATES, **rates},
        source=SourceInfo(
            url="https://example.test/time-of-day",
            title="TOD",
            effective_date=effective_from,
            observed_at="2026-10-31T00:00:00+00:00",
            sha256=f"sha-{effective_from}",
        ),
    )


def _rich_text(value: str) -> dict:
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


def _tod_page_data(off: str = "8.93", mid: str = "16.70", on: str = "43.13") -> dict:
    """Current TOD page shape: no "As of" sentence anywhere in the page-data."""
    return {
        "result": {
            "data": {
                "allContentfulPageBasic": {
                    "nodes": [
                        {
                            "contentEntries": [
                                {
                                    "__typename": "ContentfulModuleAccordion",
                                    "accordionItems": [
                                        {
                                            "tabBody": {
                                                "raw": json.dumps(
                                                    _rich_text(
                                                        f"Off-Peak: {off}¢ per kWh\n"
                                                        f"Mid-Peak: {mid}¢ per kWh\n"
                                                        f"On-Peak: {on}¢ per kWh"
                                                    )
                                                )
                                            }
                                        }
                                    ],
                                }
                            ]
                        }
                    ]
                }
            }
        }
    }


class _FakeResponse:
    def __init__(self, payload: dict | None = None, status: int = 200) -> None:
        self._payload = payload or {}
        self.status = status
        self.headers: dict[str, str] = {}

    async def json(self) -> dict:
        return self._payload


class _FakeGet:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def get(self, *args: object, **kwargs: object) -> _FakeGet:
        return _FakeGet(self._response)


def _coordinator(tod_rows: list[TodTariffRow] | None = None) -> TariffUpdaterCoordinator:
    """Coordinator with only the state the fetch path touches."""
    coordinator = object.__new__(TariffUpdaterCoordinator)
    coordinator._store_data = TariffStoreData()
    coordinator._tod_rows = list(tod_rows or [])
    coordinator._basic_rows = []
    coordinator._processed_pdf_urls = set()
    return coordinator


# -- _rates_match_latest --


def test_rates_match_latest_identical():
    assert _rates_match_latest([_row("2026-07-08")], _row("2026-10-15")) is True


def test_rates_match_latest_real_change():
    fetched = _row("2026-10-15", on_peak=0.4512)
    assert _rates_match_latest([_row("2026-07-08")], fetched) is False


def test_rates_match_latest_empty_catalog():
    assert _rates_match_latest([], _row("2026-10-15")) is False


def test_rates_match_latest_compares_last_row():
    """Callers keep the catalog sorted, so the newest row is last."""
    existing = [
        _row("2026-07-08", off_peak=0.0834, mid_peak=0.1561, on_peak=0.4021),
        _row("2026-10-15"),
    ]
    assert _rates_match_latest(existing, _row("2027-01-01")) is True
    # An unsorted list is not reordered; the last element is the target.
    assert _rates_match_latest(list(reversed(existing)), _row("2027-01-01")) is False


# -- discover_latest_effective_date --


def test_discover_latest_effective_date_picks_newest():
    docs = [
        {"effective_date_str": "2026-07-08"},
        {"effective_date_str": ""},
        {"effective_date_str": "2026-10-15"},
    ]
    assert discover_latest_effective_date(docs) == "2026-10-15"


def test_discover_latest_effective_date_none():
    assert discover_latest_effective_date(None) is None
    assert discover_latest_effective_date([{"title": "no date"}]) is None


# -- prune_redundant_tod_rows --


def test_prune_redundant_rows_keeps_first_of_identical_run():
    rows = [
        _row("2026-07-08"),
        _row("2026-10-20"),
        _row("2026-10-21"),
        _row("2026-10-22"),
        _row("2026-11-01", on_peak=0.4512),
    ]
    pruned = prune_redundant_tod_rows(rows)
    assert [r.effective_from for r in pruned] == ["2026-07-08", "2026-11-01"]


def test_prune_redundant_rows_keeps_distinct_rates():
    rows = [
        _row("2026-07-08"),
        _row("2026-10-15", off_peak=0.0912, mid_peak=0.1701, on_peak=0.4400),
    ]
    assert prune_redundant_tod_rows(rows) == rows


# -- _fetch_tod_page_data --


async def test_fetch_tod_page_data_unchanged_rates_mint_no_row(caplog: pytest.LogCaptureFixture):
    coordinator = _coordinator([_row("2026-07-08")])
    session = _FakeSession(_FakeResponse(_tod_page_data()))

    with caplog.at_level("DEBUG", logger="custom_components.pge_energy.tariff_updater"):
        result, error = await coordinator._fetch_tod_page_data(session, fallback_effective_date="2026-10-15")
    assert [r for r in caplog.records if r.levelno >= 30] == []

    assert error is None
    assert result is not None
    assert result.rows == []
    assert result.errors == []

    again, again_error = await coordinator._fetch_tod_page_data(session, fallback_effective_date="2026-10-16")
    assert again_error is None
    assert again is not None and again.rows == []
    assert coordinator._tod_rows == [_row("2026-07-08")]


async def test_fetch_tod_page_data_changed_rates_use_fallback_date(caplog: pytest.LogCaptureFixture):
    coordinator = _coordinator([_row("2026-07-08")])
    session = _FakeSession(_FakeResponse(_tod_page_data(on="45.12")))

    with caplog.at_level("WARNING", logger="custom_components.pge_energy.tariff_updater"):
        result, error = await coordinator._fetch_tod_page_data(session, fallback_effective_date="2026-10-15")

    assert error is None
    assert result is not None
    assert len(result.rows) == 1
    assert result.rows[0].effective_from == "2026-10-15"
    assert result.rows[0].on_peak == 0.4512
    warnings = [r for r in caplog.records if r.levelno >= 30]
    assert len(warnings) == 1
    assert "2026-10-15" in warnings[0].message


async def test_fetch_tod_page_data_parse_failure_still_errors():
    coordinator = _coordinator([_row("2026-07-08")])
    session = _FakeSession(_FakeResponse({"result": {"data": {}}}))

    result, error = await coordinator._fetch_tod_page_data(session, fallback_effective_date="2026-10-15")

    assert result is None
    assert error is not None
    assert "Parse errors" in error.reason


# -- _fetch_and_validate --


async def _no_basic(
    self: TariffUpdaterCoordinator,
    session: object,
    docs: list[dict],
    errors: list,
) -> BasicSourceResult:
    return BasicSourceResult(rows=[], seen_urls=[], errors=[])


async def test_fetch_and_validate_passes_newest_published_date(monkeypatch: pytest.MonkeyPatch):
    coordinator = _coordinator([_row("2026-07-08")])
    monkeypatch.setattr(
        "custom_components.pge_energy.tariff_updater.aiohttp_client.async_get_clientsession",
        lambda hass: _FakeSession(_FakeResponse()),
    )
    coordinator.hass = object()

    async def _tariff_documents(session: object):
        return [{"effective_date_str": "2026-07-08"}, {"effective_date_str": "2026-10-15"}], None

    captured: dict[str, object] = {}

    async def _tod_page_data(session: object, *, fallback_effective_date: str | None = None):
        captured["fallback"] = fallback_effective_date
        return TodSourceResult(rows=[_row(fallback_effective_date or "today")], errors=[]), None

    monkeypatch.setattr(coordinator, "_fetch_tariff_documents", _tariff_documents)
    monkeypatch.setattr(coordinator, "_fetch_tod_page_data", _tod_page_data)
    monkeypatch.setattr(coordinator, "_process_tariff_documents", _no_basic.__get__(coordinator))

    update = await coordinator._fetch_and_validate()

    assert captured["fallback"] == "2026-10-15"
    assert update.fetch_errors == []
    assert coordinator._store_data.latest_tariff_effective_date == "2026-10-15"


async def test_fetch_and_validate_reuses_published_date_after_304(monkeypatch: pytest.MonkeyPatch):
    coordinator = _coordinator([_row("2026-07-08")])
    coordinator._store_data.latest_tariff_effective_date = "2026-10-15"
    monkeypatch.setattr(
        "custom_components.pge_energy.tariff_updater.aiohttp_client.async_get_clientsession",
        lambda hass: _FakeSession(_FakeResponse()),
    )
    coordinator.hass = object()

    async def _tariff_documents_304(session: object):
        return None, None

    captured: dict[str, object] = {}

    async def _tod_page_data(session: object, *, fallback_effective_date: str | None = None):
        captured["fallback"] = fallback_effective_date
        return TodSourceResult(rows=[], errors=[]), None

    monkeypatch.setattr(coordinator, "_fetch_tariff_documents", _tariff_documents_304)
    monkeypatch.setattr(coordinator, "_fetch_tod_page_data", _tod_page_data)

    update = await coordinator._fetch_and_validate()

    assert captured["fallback"] == "2026-10-15"
    # Zero rows on both sources with no fetch errors is a successful no-op
    # check, so _async_update_data must not raise UpdateFailed.
    assert update.tod_result is not None and update.tod_result.rows == []
    assert update.basic_result is None
    assert update.fetch_errors == []
