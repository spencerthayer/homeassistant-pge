from __future__ import annotations

import re
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
    assert "export function resolveLandingSelector" in source
    assert "_scheduleDefaultLandingScroll" in source
    assert "this._landingApplied" in source
    # One-shot: landing flag is set before scrollIntoView scheduling.
    assert re.search(
        r"_landingApplied = true;\s*requestAnimationFrame",
        source,
        re.MULTILINE,
    )
