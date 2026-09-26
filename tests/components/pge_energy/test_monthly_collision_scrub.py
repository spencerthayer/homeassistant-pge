"""Coarse DAILY/MONTHLY totals must not coexist with hourly rows on a day."""

from __future__ import annotations

from datetime import UTC, datetime

from custom_components.pge_energy.const import MONTHLY_LUMP_MIN_KWH
from custom_components.pge_energy.statistics import (
    _collision_zero_overlays,
    _reconcile_coarse_fine_rows,
)


def test_scrub_zeros_month_start_lump_when_hourly_arrives():
    month_start = datetime(2025, 9, 1, 7, tzinfo=UTC)  # Pacific midnight
    hour = datetime(2025, 9, 1, 8, tzinfo=UTC)
    existing = {
        month_start: {"state": 648.0},
        hour: {"state": 0.28},
    }
    overlay = {hour: 0.31}
    adjusted = _reconcile_coarse_fine_rows(existing, overlay, lump_min=MONTHLY_LUMP_MIN_KWH)
    assert adjusted == 1
    assert overlay[month_start] == 0.0
    assert overlay[hour] == 0.31


def test_daily_midnight_lump_owns_an_incomplete_hourly_day():
    """A DAILY total is the whole day, so partial hours must not add to it."""
    from datetime import timedelta

    from custom_components.pge_energy.const import DAILY_LUMP_MIN_KWH

    midnight = datetime(2026, 7, 24, 7, tzinfo=UTC)  # Pacific midnight

    # Complete hourly day replaces the lump outright.
    overlay = {midnight + timedelta(hours=i): 1.0 for i in range(24)}
    adjusted = _reconcile_coarse_fine_rows(
        {midnight: {"state": 28.0}},
        overlay,
        lump_min=MONTHLY_LUMP_MIN_KWH,
        daily_lump_min=DAILY_LUMP_MIN_KWH,
    )
    assert adjusted == 0
    assert overlay[midnight] == 1.0

    # Partial hours cannot replace or add to the lump: the lump stays, hours defer.
    overlay2 = {midnight + timedelta(hours=i): 1.0 for i in range(1, 24)}
    adjusted2 = _reconcile_coarse_fine_rows(
        {midnight: {"state": 28.0}},
        overlay2,
        lump_min=MONTHLY_LUMP_MIN_KWH,
        daily_lump_min=DAILY_LUMP_MIN_KWH,
    )
    assert adjusted2 == 23
    assert midnight not in overlay2
    assert set(overlay2.values()) == {0.0}


def test_partial_hours_at_midnight_defer_to_the_daily_lump():
    from datetime import timedelta

    from custom_components.pge_energy.const import DAILY_LUMP_MIN_KWH

    midnight = datetime(2026, 7, 24, 7, tzinfo=UTC)
    overlay = {midnight + timedelta(hours=i): 1.0 for i in range(4)}
    adjusted = _reconcile_coarse_fine_rows(
        {midnight: {"state": 28.0}},
        overlay,
        lump_min=MONTHLY_LUMP_MIN_KWH,
        daily_lump_min=DAILY_LUMP_MIN_KWH,
    )
    assert adjusted == 3
    assert midnight not in overlay
    assert set(overlay.values()) == {0.0}


def test_scrub_leaves_deep_history_month_only_row():
    """A lone monthly row (no finer siblings that day) must stay — that is deep history."""
    month_start = datetime(2021, 1, 1, 8, tzinfo=UTC)
    existing = {month_start: {"state": 1317.0}}
    overlay = {datetime(2025, 9, 1, 8, tzinfo=UTC): 1.0}
    adjusted = _reconcile_coarse_fine_rows(existing, overlay, lump_min=MONTHLY_LUMP_MIN_KWH)
    assert adjusted == 0
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
