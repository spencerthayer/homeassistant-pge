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
