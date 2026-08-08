from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

from custom_components.pge_energy.billing_models import TodSnapshot
from custom_components.pge_energy.const import (
    CONF_TOD_RATE_BASIC_SERVICE,
    CONF_TOD_RATE_MID_PEAK,
    CONF_TOD_RATE_OFF_PEAK,
    CONF_TOD_RATE_ON_PEAK,
    RATE_SOURCE_DEFAULT,
    RATE_SOURCE_OVERRIDE,
    RATE_SOURCE_PORTAL,
    TodPeriod,
)
from custom_components.pge_energy.tod_pricing import (
    resolve_tod_rates,
    tod_overrides_from_entry,
    tod_snapshot_from_dict,
    tod_snapshot_to_dict,
)


def _portal(*, partial: bool = False) -> TodSnapshot:
    rates = {"off_peak": 0.09, "mid_peak": 0.16, "on_peak": 0.42}
    if partial:
        rates = {"off_peak": 0.09}
    return TodSnapshot(
        rates=rates,
        basic_rate=0.11,
        savings_total=12.5,
        fetched_at=datetime(2026, 7, 13, 7, tzinfo=UTC),
        attributes={"op": "tod"},
    )


def _entry(**options: Any) -> MagicMock:
    entry = MagicMock()
    entry.options = dict(options)
    entry.data = {}
    return entry


class TestResolveTodRates:
    def test_defaults_when_nothing_configured(self):
        card = resolve_tod_rates(None, None)
        assert card.rates["off_peak"] == 0.0893
        assert card.rates["mid_peak"] == 0.1670
        assert card.rates["on_peak"] == 0.4313
        assert card.sources == {
            "off_peak": RATE_SOURCE_DEFAULT,
            "mid_peak": RATE_SOURCE_DEFAULT,
            "on_peak": RATE_SOURCE_DEFAULT,
        }
        assert card.basic_rate == 0.10
        assert card.basic_source == RATE_SOURCE_DEFAULT

    def test_portal_wins_over_defaults(self):
        card = resolve_tod_rates(None, _portal())
        assert card.rates["off_peak"] == 0.09
        assert card.rates["mid_peak"] == 0.16
        assert card.rates["on_peak"] == 0.42
        assert card.sources["on_peak"] == RATE_SOURCE_PORTAL
        assert card.basic_rate == 0.11
        assert card.basic_source == RATE_SOURCE_PORTAL

    def test_override_beats_portal_beats_default(self):
        overrides = {
            "off_peak": 0.05,
            "mid_peak": None,
            "on_peak": None,
            "basic_service": 0.08,
        }
        card = resolve_tod_rates(overrides, _portal(partial=True))
        assert card.rates["off_peak"] == 0.05
        assert card.sources["off_peak"] == RATE_SOURCE_OVERRIDE
        # mid/on fall back to defaults (partial portal has no mid/on rates).
        assert card.rates["mid_peak"] == 0.1670
        assert card.sources["mid_peak"] == RATE_SOURCE_DEFAULT
        assert card.rates["on_peak"] == 0.4313
        assert card.basic_rate == 0.08
        assert card.basic_source == RATE_SOURCE_OVERRIDE

    def test_non_positive_override_ignored(self):
        overrides = {"off_peak": 0.0, "mid_peak": -3, "basic_service": 0}
        card = resolve_tod_rates(overrides, _portal())
        assert card.rates["off_peak"] == 0.09
        assert card.sources["off_peak"] == RATE_SOURCE_PORTAL
        assert card.rates["mid_peak"] == 0.16
        assert card.basic_rate == 0.11

    def test_non_positive_portal_values_fall_back_to_defaults(self):
        portal = TodSnapshot(
            rates={"off_peak": 0.0, "mid_peak": -1, "on_peak": 0.42},
            basic_rate=0.0,
        )
        card = resolve_tod_rates(None, portal)
        assert card.rates["off_peak"] == 0.0893
        assert card.sources["off_peak"] == RATE_SOURCE_DEFAULT
        assert card.rates["mid_peak"] == 0.1670
        assert card.sources["mid_peak"] == RATE_SOURCE_DEFAULT
        assert card.rates["on_peak"] == 0.42
        assert card.sources["on_peak"] == RATE_SOURCE_PORTAL
        assert card.basic_rate == 0.10
        assert card.basic_source == RATE_SOURCE_DEFAULT


class TestTodOverridesFromEntry:
    def test_unset_options_yield_none(self):
        entry = _entry()
        overrides = tod_overrides_from_entry(entry)
        assert overrides == {
            TodPeriod.OFF_PEAK.value: None,
            TodPeriod.MID_PEAK.value: None,
            TodPeriod.ON_PEAK.value: None,
            "basic_service": None,
        }

    def test_configured_overrides_round_trip(self):
        entry = _entry(
            **{
                CONF_TOD_RATE_OFF_PEAK: 0.05,
                CONF_TOD_RATE_MID_PEAK: 0.14,
                CONF_TOD_RATE_ON_PEAK: 0.4,
                CONF_TOD_RATE_BASIC_SERVICE: 0.08,
            }
        )
        assert tod_overrides_from_entry(entry) == {
            TodPeriod.OFF_PEAK.value: 0.05,
            TodPeriod.MID_PEAK.value: 0.14,
            TodPeriod.ON_PEAK.value: 0.4,
            "basic_service": 0.08,
        }

    def test_invalid_values_yield_none(self):
        entry = _entry(
            **{
                CONF_TOD_RATE_OFF_PEAK: "",
                CONF_TOD_RATE_MID_PEAK: "0.99",
                CONF_TOD_RATE_ON_PEAK: -1,
                CONF_TOD_RATE_BASIC_SERVICE: None,
            }
        )
        overrides = tod_overrides_from_entry(entry)
        assert overrides == {
            TodPeriod.OFF_PEAK.value: None,
            TodPeriod.MID_PEAK.value: None,
            TodPeriod.ON_PEAK.value: None,
            "basic_service": None,
        }


class TestSnapshotSerialization:
    def test_round_trip(self):
        snap = _portal()
        rebuilt = tod_snapshot_from_dict(tod_snapshot_to_dict(snap))
        assert rebuilt == snap

    def test_none_round_trip(self):
        assert tod_snapshot_to_dict(None) is None
        assert tod_snapshot_from_dict(None) is None
        assert tod_snapshot_from_dict({}) is None

    def test_malformed_is_none(self):
        assert tod_snapshot_from_dict({"rates": "nope", "basic_rate": "bogus"}) is None

    def test_zulu_timestamp_accepted(self):
        data = tod_snapshot_to_dict(_portal())
        data["fetched_at"] = "2026-07-13T07:00:00Z"
        rebuilt = tod_snapshot_from_dict(data)
        assert rebuilt is not None
        assert rebuilt.fetched_at == datetime(2026, 7, 13, 7, tzinfo=UTC)

    def test_savings_only_snapshot_persists(self):
        rebuilt = tod_snapshot_from_dict({"savings_total": 12.34})
        assert rebuilt is not None
        assert rebuilt.savings_total == 12.34
        assert rebuilt.rates == {}
        assert rebuilt.basic_rate is None
