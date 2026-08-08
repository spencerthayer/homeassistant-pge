"""Source-level checks for the frontend Time of Day hub (no Node in CI).

Behavior of the pure schedule/bucket functions is verified manually against
``tod_schedule.py`` during development; here we only lock the contract that
the panel ships the expected exports, anchor, and section.
"""

from __future__ import annotations

from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[3] / "custom_components" / "pge_energy" / "frontend"
DATA_JS = FRONTEND / "data.js"
PANEL_JS = FRONTEND / "pge-panel.js"


def test_data_js_exports_tod_schedule_helpers():
    source = DATA_JS.read_text(encoding="utf-8")
    for export in (
        "export const TOD_PERIODS",
        "export const TOD_PERIOD_LABELS",
        "export function pacificHour",
        "export function pacificParts",
        "export function todHolidays",
        "export function isTodOffPeakDay",
        "export function todPeriodForPacific",
        "export function bucketTodByPeriod",
        "export function todWeekDays",
    ):
        assert export in source


def test_data_js_schedule_boundaries_match_python():
    source = DATA_JS.read_text(encoding="utf-8")
    # Mirrors _WEEKDAY_WINDOWS in tod_schedule.py: off [21:00,07:00) / mid
    # [07:00,17:00) / on [17:00,21:00).
    assert "hour < 7" in source
    assert "hour < 17" in source
    assert "hour < 21" in source
    # Fixed holidays + Dec 31 edge case mirror holiday_calendar().
    assert "new Date(year, 6, 4)" in source
    assert "new Date(year, 11, 25)" in source
    assert "function _asDate" in source


def test_panel_ships_tod_section_and_render():
    source = PANEL_JS.read_text(encoding="utf-8")
    assert '<section class="card" id="tod"></section>' in source
    assert "await this._renderTod();" in source
    assert "async _renderTod()" in source
    assert "async _renderTodBody(" in source
    # Used by share bar / table / legend — must be imported (ReferenceError blanks /pge).
    import_end = source.find('from "./data.js')
    assert import_end > 0
    import_block = source[:import_end]
    assert "TOD_PERIODS" in import_block
    assert "TOD_PERIOD_LABELS" in import_block
    # next_transition_at arrives as an ISO string from WS — must Date()-coerce.
    assert "pacificParts(new Date(nextAt))" in source
    # Imported cost is USD; avg rate column is labeled ¢/kWh.
    assert "(c / kw) * 100" in source
    assert "estimate >= 0" in source
    assert "Math.abs(estimate)" in source
    assert "._todWeekGrid()" in source
    assert 'class="tod-cell' in source
