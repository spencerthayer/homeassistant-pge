"""Monthly billing-period lumps must not coexist with hourly rows on a day."""

from __future__ import annotations

from datetime import UTC, datetime

from custom_components.pge_energy.const import MONTHLY_LUMP_MIN_KWH
from custom_components.pge_energy.statistics import (
    _collision_zero_overlays,
    _scrub_monthly_lumps_for_days,
)


def test_scrub_zeros_month_start_lump_when_hourly_arrives():
    month_start = datetime(2025, 9, 1, 7, tzinfo=UTC)  # Pacific midnight
    hour = datetime(2025, 9, 1, 8, tzinfo=UTC)
    existing = {
        month_start: {"state": 648.0},
        hour: {"state": 0.28},
    }
    overlay = {hour: 0.31}
    scrubbed = _scrub_monthly_lumps_for_days(existing, overlay, lump_min=MONTHLY_LUMP_MIN_KWH)
    assert scrubbed == 1
    assert overlay[month_start] == 0.0
    assert overlay[hour] == 0.31


def test_scrub_zeros_daily_midnight_lump_when_full_hourly_arrives():
    """A 28 kWh daily row at midnight must yield to a full hourly day."""
    from datetime import timedelta

    from custom_components.pge_energy.const import DAILY_LUMP_MIN_KWH

    midnight = datetime(2026, 7, 24, 7, tzinfo=UTC)
    existing = {midnight: {"state": 28.0}}
    overlay = {midnight + timedelta(hours=i): 1.0 for i in range(24)}
    scrubbed = _scrub_monthly_lumps_for_days(
        existing,
        overlay,
        lump_min=MONTHLY_LUMP_MIN_KWH,
        daily_lump_min=DAILY_LUMP_MIN_KWH,
    )
    # Midnight is in overlay so it is replaced by hourly, not scrubbed-as-zero.
    assert scrubbed == 0
    assert overlay[midnight] == 1.0

    # Stale daily at midnight while hourly starts at 01:00 — scrub the 28 kWh row.
    overlay2 = {midnight + timedelta(hours=i): 1.0 for i in range(1, 24)}
    existing2 = {midnight: {"state": 28.0}}
    scrubbed2 = _scrub_monthly_lumps_for_days(
        existing2,
        overlay2,
        lump_min=MONTHLY_LUMP_MIN_KWH,
        daily_lump_min=DAILY_LUMP_MIN_KWH,
    )
    assert scrubbed2 == 1
    assert overlay2[midnight] == 0.0


def test_scrub_leaves_deep_history_month_only_row():
    """A lone monthly row (no finer siblings that day) must stay — that is deep history."""
    month_start = datetime(2021, 1, 1, 8, tzinfo=UTC)
    existing = {month_start: {"state": 1317.0}}
    overlay = {datetime(2025, 9, 1, 8, tzinfo=UTC): 1.0}
    scrubbed = _scrub_monthly_lumps_for_days(existing, overlay, lump_min=MONTHLY_LUMP_MIN_KWH)
    assert scrubbed == 0
    assert month_start not in overlay


def test_collision_zero_overlays_finds_shared_day_lumps():
    month_start = datetime(2025, 9, 1, 7, tzinfo=UTC)
    hour = datetime(2025, 9, 1, 10, tzinfo=UTC)
    deep = datetime(2021, 1, 1, 8, tzinfo=UTC)
    existing = {
        month_start: {"state": 648.0},
        hour: {"state": 2.0},
        deep: {"state": 1317.0},
    }
    overlays = _collision_zero_overlays(existing, lump_min=MONTHLY_LUMP_MIN_KWH)
    assert overlays == {month_start: 0.0}
