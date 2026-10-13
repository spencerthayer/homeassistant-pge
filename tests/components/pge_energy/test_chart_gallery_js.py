"""Source contract for the recorder chart gallery. CI runs pytest, not node."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FRONTEND = ROOT / "custom_components" / "pge_energy" / "frontend"
CHARTS_JS = FRONTEND / "charts.js"
PANEL_JS = FRONTEND / "pge-panel.js"

HOST_IDS = (
    "chart-typical-day",
    "chart-hour-weekday",
    "chart-ridgelines",
    "chart-polar",
    "chart-histogram",
    "chart-yoy",
    "chart-cycle-race",
    "chart-baseload",
    "chart-spread",
    "chart-published-week",
    "chart-fingerprint",
    "chart-duck",
    "chart-duck-months",
    "chart-tod-stacked",
    "chart-period-mix",
    "chart-money-pareto",
    "chart-period-box",
    "chart-tod-delta",
    "chart-forward-ribbon",
    "chart-sankey",
    "chart-degree-days",
    "chart-temp-bins",
    "chart-statement-portal",
    "chart-bill-imported",
    "chart-program-savings",
    "chart-balance-due",
    "chart-bill-anatomy",
    "chart-treemap",
    "chart-waterfall",
    "chart-fixed-variable",
    "chart-line-mix",
    "chart-bill-explainer",
    "chart-weather-counterfactual",
    "chart-baseload-history",
    "chart-shift-sim",
    "chart-daypart-stream",
    "kpi-degree-price",
)

PANEL_SERIES_IMPORTS = (
    "baseloadFloor",
    "baseloadSteps",
    "billAnatomyRows",
    "billExplainer",
    "billFamilies",
    "billVsImported",
    "centsPerKwh",
    "counterfactual",
    "cycleCumulative",
    "dayFingerprints",
    "daypartDays",
    "degreeDayPoint",
    "degreePrice",
    "duckHourProfiles",
    "duckMonthBars",
    "forwardRibbon",
    "hasExport",
    "histogramBins",
    "hourWeekdayMatrix",
    "lineItemShares",
    "moneyHourPareto",
    "monthRidges",
    "monthlyByYear",
    "periodBox",
    "periodMixByMonth",
    "publishedWeekDays",
    "sankeyFlows",
    "shiftCostByStartHour",
    "spreadBand",
    "statementGap",
    "statementWindows",
    "tempBins",
    "todMinusBasicByMonth",
    "treemapSlices",
    "typicalDayProfiles",
    "waterfallSteps",
    "weatherModel",
)

WRAPPERS = (
    "createPolarBar",
    "createPolarScatter",
    "createBoxPlot",
    "createSankey",
    "createTreemap",
    "createParallel",
    "createRidgeline",
    "createWaterfall",
    "createThemeRiver",
    "createHourWeekdayHeatmap",
)

README = ROOT / "README.md"

CHART_NAMES = (
    "Usage combo",
    "Weather vs usage",
    "Monthly average rate",
    "Billed vs payments",
    "kWh calendar",
    "Temperature calendar",
    "Ledger dollars",
    "Ledger kWh",
    "Glance sparklines",
    "Week schedule",
    "Period share bar",
    "Typical day",
    "Hour by weekday heatmap",
    "Monthly ridgelines",
    "24-hour polar clock",
    "Daily kWh histogram",
    "Year over year",
    "Billing-cycle race",
    "Baseload band",
    "Daily spread band",
    "Published week",
    "Day fingerprint",
    "Duck curve",
    "Stacked area",
    "Monthly period mix",
    "Money-hours Pareto",
    "kWh by period",
    "Local Basic minus local TOD",
    "Forward 48-hour ribbon",
    "Sankey",
    "Degree days vs kWh",
    "Temperature bins",
    "Statement vs portal estimate",
    "Bill kWh vs imported kWh",
    "Program savings",
    "Balance and amount due",
    "Stacked bill anatomy",
    "Latest statement treemap",
    "Statement waterfall",
    "Fixed vs variable",
    "Line-item mix",
    "Why this bill changed",
    "Weather-normalized counterfactual",
    "Always-on load history",
    "Load-shift simulator",
    "Daypart stream",
    "Price of a degree",
)


def _series_import(panel: str) -> str:
    marker = 'from "./chart-series.js'
    end = panel.index(marker)
    start = panel.rindex("import {", 0, end)
    return panel[start:end]


def test_charts_js_exports_gallery_wrappers():
    source = CHARTS_JS.read_text(encoding="utf-8")
    for name in WRAPPERS:
        assert f"export async function {name}" in source


def test_panel_hosts_and_gallery_persist_keys():
    source = PANEL_JS.read_text(encoding="utf-8")
    for host_id in HOST_IDS:
        assert f'"{host_id}"' in source
    for key in (
        "chart_gallery_load",
        "chart_gallery_tod",
        "chart_gallery_billing",
        "chart_gallery_pdf",
    ):
        assert f'data-persist="{key}"' in source


def test_panel_imports_chart_series_exports_it_calls():
    source = PANEL_JS.read_text(encoding="utf-8")
    imported = _series_import(source)
    for name in PANEL_SERIES_IMPORTS:
        assert name in imported


def test_readme_names_every_panel_chart():
    readme = README.read_text(encoding="utf-8")
    assert "## Panel charts" in readme
    for name in CHART_NAMES:
        assert f"#### {name}" in readme
