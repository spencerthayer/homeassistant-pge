"""Release refuses to run when manifest.json and const.py disagree."""

from __future__ import annotations

import json
import re
from pathlib import Path

from custom_components.pge_energy.const import VERSION

ROOT = Path(__file__).resolve().parents[3]
COMPONENT = ROOT / "custom_components" / "pge_energy"
FRONTEND_MODULES = (
    COMPONENT / "frontend" / "pge-panel.js",
    COMPONENT / "frontend" / "chart-gallery.js",
    COMPONENT / "frontend" / "chart-series.js",
    COMPONENT / "frontend" / "charts.js",
)


def test_manifest_version_matches_const() -> None:
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == VERSION


def test_frontend_cache_query_matches_const() -> None:
    """panel.py loads pge-panel.js?v=VERSION, so imported modules must use the same query."""
    found = False
    for path in FRONTEND_MODULES:
        versions = re.findall(r"\?v=([0-9]+\.[0-9]+\.[0-9]+)", path.read_text(encoding="utf-8"))
        assert versions, path.name
        assert set(versions) == {VERSION}
        found = True
    assert found
