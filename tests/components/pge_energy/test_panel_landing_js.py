from __future__ import annotations

from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[3] / "custom_components" / "pge_energy" / "frontend" / "pge-panel.js"


def test_panel_section_anchors_and_resolver_present():
    source = FRONTEND.read_text(encoding="utf-8")
    assert "export const PANEL_SECTION_ANCHORS" in source
    assert 'glance: "#kpis"' in source
    assert 'usage: "#hero"' in source
    assert 'analytics: "#insights-weather"' in source
    assert 'tod: "#tod"' in source
    assert 'billing: "#billing"' in source
    assert 'programs: "#programs"' in source
    assert "export function resolveLandingSelector" in source
    assert "resolvePanelTab" in source
    assert "hashchange" in source
    assert "this._landingApplied" in source


def test_motion_keyframes_present():
    source = FRONTEND.read_text(encoding="utf-8")
    assert "@keyframes pge-fade-up" in source
    assert "interpolate-size: allow-keywords" in source


def test_story_band_is_wired():
    source = FRONTEND.read_text(encoding="utf-8")
    assert 'id="story"' in source
    assert "storySummary" in source


def test_range_bar_hidden_attribute_wins():
    source = FRONTEND.read_text(encoding="utf-8")
    assert ".filters[hidden]" in source
    assert 'range.hidden = tab !== "usage"' in source
    chrome = source[source.index('<div class="panel-chrome">') : source.index('id="panel-glance"')]
    assert "hdr-range" not in chrome
    assert source.count('class="usage-range"') == 1
    assert source.count('class="card panel-usage"') == 2
    assert "position: static" in source[source.index(".hdr-range.filters") : source.index(".hdr-range.filters") + 180]


def test_native_controls_match_panel_chips():
    source = FRONTEND.read_text(encoding="utf-8")
    assert 'input[type="datetime-local"]' in source
    assert "aria-pressed" in source


def test_content_is_full_width_with_wide_figures():
    source = FRONTEND.read_text(encoding="utf-8")
    assert "max-width: 1200px" not in source
    assert "max-width: 2400px" in source
    assert ".fig-wide" in source


def test_tab_panels_exist():
    source = FRONTEND.read_text(encoding="utf-8")
    for tab in ("glance", "usage", "analytics", "billing", "tod", "programs"):
        assert f'data-tab="{tab}"' in source
        assert 'class="tab-panel"' in source


def test_hass_updates_do_not_rebuild_open_range_selects():
    source = FRONTEND.read_text(encoding="utf-8")
    assert "presetProbeEffect" in source
    assert "_schedulePresetProbe" in source
    assert "_filterControlFocused" in source
    setter = source[source.index("set hass(hass)") : source.index("get hass()")]
    assert "this._renderFilters()" not in setter
    assert "this._schedulePresetProbe()" in setter


def test_range_handlers_use_scoped_render():
    source = FRONTEND.read_text(encoding="utf-8")
    start = source.index("_renderFilters() {")
    body = source[start : source.index("async _renderDataGaps", start)]
    assert "this._renderRangeScope()" in body
    assert "this._renderAll()" not in body
    assert "this._rangeRenderGen" in source


def test_heatmap_day_click_rebuilds_usage_range_bar():
    source = FRONTEND.read_text(encoding="utf-8")
    start = source.index("_openUsageDay(")
    body = source[start : source.index("_heatmapWindowKey()", start)]
    assert 'this._selectPanelTab("usage", { writeHistory: true })' in body
    assert "this._renderFilters();" in body
    assert "this._renderRangeScope()" in body
    assert body.index("this._renderFilters();") < body.index("this._renderRangeScope()")


def test_disconnected_callback_releases_hashchange_and_header_observer():
    source = FRONTEND.read_text(encoding="utf-8")
    start = source.index("disconnectedCallback() {")
    body = source[start : source.index("async _boot()", start)]
    assert 'window.removeEventListener("hashchange", this._onPanelHashChange)' in body
    assert "this._onPanelHashChange = null" in body
    assert "this._headerObserver?.disconnect()" in body
    assert "this._headerObserver = null" in body


def test_design_tokens_present():
    source = FRONTEND.read_text(encoding="utf-8")
    assert "--pge-space-4" in source
    assert "--pge-surface-2" in source
    assert "--pge-ease" in source
    assert "font-variant-numeric: tabular-nums" in source


def test_glance_kpi_clipboard_wiring_present():
    source = FRONTEND.read_text(encoding="utf-8")
    assert "formatKpiClipboardText" in source
    assert "_bindGlanceKpiClipboard" in source
    assert "this._bindGlanceKpiClipboard(el)" in source
    assert "Click to copy" in source
    assert "navigator.clipboard" in source
