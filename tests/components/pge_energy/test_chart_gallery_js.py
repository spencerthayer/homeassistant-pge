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


def test_plain_copy_and_glossary():
    source = PANEL_JS.read_text(encoding="utf-8")
    for gloss in (
        "gloss-kwh",
        "gloss-baseload",
        "gloss-degree-day",
        "gloss-tod",
        "gloss-estimate",
        "gloss-sd",
        "gloss-r2",
        "gloss-normalized",
        "gloss-statement-window",
    ):
        assert f'popovertarget="{gloss}"' in source
    assert "Your energy, hour by hour" in source
    assert "A typical weekday vs weekend" in source
    assert "Why this bill changed" in source


def test_figures_have_explainer_and_expand():
    source = PANEL_JS.read_text(encoding="utf-8")
    assert "data-headline-for" in source
    assert "What this shows" in source
    assert 'class="fig-expand"' in source
    charts = CHARTS_JS.read_text(encoding="utf-8")
    assert ".fig-title, h3" in charts


def test_more_charts_hold_load_shape_overlaps():
    source = PANEL_JS.read_text(encoding="utf-8")
    start = source.index('data-section="more-charts"')
    body = source[start : source.index("</details>", start)]
    for host_id in ("chart-baseload", "chart-polar", "chart-treemap"):
        assert host_id in body
    gallery = (FRONTEND / "chart-gallery.js").read_text(encoding="utf-8")
    assert "Overnight floor" in gallery


def test_more_charts_hold_the_cut_hosts():
    source = PANEL_JS.read_text(encoding="utf-8")
    start = source.index('data-section="more-charts"')
    body = source[start : source.index("</details>", start)]
    for host_id in (
        "chart-fingerprint",
        "chart-ridgelines",
        "chart-daypart-stream",
        "chart-published-week",
        "chart-program-savings",
    ):
        assert host_id in body


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


def test_cost_intelligence_uses_twelve_month_window():
    source = PANEL_JS.read_text(encoding="utf-8")
    start = source.index("async _renderInsights()")
    end = source.index("_renderBillPdfHeader", start)
    body = source[start:end]
    assert 'const costRange = rangePresets()["12mo"]' in body
    assert "start: costRange.start" in body
    assert "_monthlyRateSeries(kwhForRate, costDay)" in body
    charts = CHARTS_JS.read_text(encoding="utf-8")
    assert "barMaxWidth: 28" in charts


def test_counterfactual_uses_two_panes():
    charts = CHARTS_JS.read_text(encoding="utf-8")
    gallery = (FRONTEND / "chart-gallery.js").read_text(encoding="utf-8")
    assert "panes = false" in charts
    assert "pane: 1" in gallery
    assert "R²" in gallery


def test_waterfalls_show_signed_dollar_labels():
    charts = CHARTS_JS.read_text(encoding="utf-8")
    gallery = (FRONTEND / "chart-gallery.js").read_text(encoding="utf-8")
    start = charts.index("export async function createWaterfall")
    body = charts[start : charts.index("export async function createThemeRiver", start)]
    assert "label: {" in body
    assert "show: true" in body
    assert gallery.count('unit: "$"') >= 2


def test_heatmap_legend_and_day_click():
    charts = CHARTS_JS.read_text(encoding="utf-8")
    panel = PANEL_JS.read_text(encoding="utf-8")
    start = charts.index("export async function renderHeatmap")
    body = charts[start : charts.index("function countFinite", start)]
    assert "show: true" in body
    assert "_openUsageDay" in panel


def test_heatmaps_default_to_trailing_year_with_picker():
    source = PANEL_JS.read_text(encoding="utf-8")
    start = source.index("async _renderInsights()")
    end = source.index("_renderBillPdfHeader", start)
    body = source[start:end]
    assert "pge_heatmap_window" in source
    assert '"12mo"' in body or "12mo" in body
    assert '"all"' in source or "all" in body
    assert "HEATMAP_HISTORY_START" in body
    charts = CHARTS_JS.read_text(encoding="utf-8")
    assert "function heatmapYears" in charts
    assert "calendarIndex: index" in charts
    assert "heatmap-scroll" not in source


def test_usage_temp_strip():
    source = CHARTS_JS.read_text(encoding="utf-8")
    start = source.index("export async function createUsageComboChart")
    body = source[start : source.index("export async function", start + 10)]
    assert "gridIndex: 1" in body


def test_usage_metric_toggle():
    charts = CHARTS_JS.read_text(encoding="utf-8")
    panel = PANEL_JS.read_text(encoding="utf-8")
    assert "pge_usage_metric" in panel
    assert "metric = \"kwh\"" in charts or 'metric = "kwh"' in charts


def test_usage_combo_accepts_period_colors():
    charts = CHARTS_JS.read_text(encoding="utf-8")
    panel = PANEL_JS.read_text(encoding="utf-8")
    assert "periodColors" in charts
    assert "periodColors" in panel


def test_gallery_bars_are_rounded_and_focus_series():
    source = CHARTS_JS.read_text(encoding="utf-8")
    assert "borderRadius: [4, 4, 0, 0]" in source
    assert 'focus: "series"' in source


def test_bill_charts_use_family_colors():
    gallery = (FRONTEND / "chart-gallery.js").read_text(encoding="utf-8")
    charts = CHARTS_JS.read_text(encoding="utf-8")
    assert "billFamilyColors(" in gallery
    start = charts.index("export async function createTreemap")
    body = charts[start : charts.index("export async function createParallel", start)]
    assert "color: [colors.kwh" not in body


def test_tod_charts_use_period_colors():
    gallery = (FRONTEND / "chart-gallery.js").read_text(encoding="utf-8")
    assert "todColors(" in gallery
    start = gallery.index('mount( "chart-period-mix"')
    body = gallery[start : gallery.index("chart-money-pareto", start)]
    assert "color:" in body


def test_percent_charts_cap_at_one_hundred():
    charts = CHARTS_JS.read_text(encoding="utf-8")
    assert "percent = false" in charts
    gallery = (FRONTEND / "chart-gallery.js").read_text(encoding="utf-8")
    start = gallery.index('mount( "chart-period-mix"')
    body = gallery[start : gallery.index("chart-money-pareto", start)]
    assert "percent: true" in body


def test_weather_empty_message_is_range_aware():
    source = CHARTS_JS.read_text(encoding="utf-8")
    assert "Need more days with both usage and temperature." not in source
    assert "Pick 7 days or longer" in source


def test_mount_contains_axis_labels():
    source = CHARTS_JS.read_text(encoding="utf-8")
    start = source.index("async function mount(")
    body = source[start : source.index("const applyHeight", start)]
    assert "containLabel" in body
    assert 'position: "insideEndTop"' in source


def test_readme_names_every_panel_chart():
    readme = README.read_text(encoding="utf-8")
    assert "## Panel charts" in readme
    for name in CHART_NAMES:
        assert f"#### {name}" in readme
