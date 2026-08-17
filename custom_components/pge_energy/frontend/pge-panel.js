/**
 * PGE Energy custom panel — buildless ES module (no lit/npm/bundler).
 * Registered as <pge-energy-panel> at /pge.
 */

// Query suffix must match const.py VERSION so `pge-panel.js?v=` also busts
// these relative ES-module imports (static import specifiers cannot interpolate).
import {
  RANGE_PRESET_LABELS,
  RANGE_PRESET_MORE,
  RANGE_PRESET_ORDER,
  RANGE_PRESET_PRIMARY,
  RATE_EPSILON_KWH,
  TOD_PERIOD_LABELS,
  TOD_PERIODS,
  accountingPlan,
  aggregateEstimatedCostSeries,
  bucketTodByPeriod,
  clampToPublishedEnd,
  computeTodPlanCompare,
  detectFlatPortalRates,
  estimatePlanCostSeries,
  formatSignedKwh,
  todEnrollmentVerdict,
  reconcilePlanComparison,
  computeUsageAccounting,
  countSeriesPoints,
  fetchStatisticSeries,
  formatKpiClipboardText,
  formatRangeLabel,
  formatSignedUsd,
  invalidateStatsCache,
  minPointsForPreset,
  pacificMidnightUtc,
  pacificParts,
  pacificWeekStartUtc,
  pacificYmd,
  priorPacificYmd,
  projectDirectionalUsage,
  projectUsageSeries,
  publishedDataEnd,
  rangePresets,
  seriesCostCoverageComplete,
  shiftChartRange,
  stateAttr,
  stateDisplay,
  stateNumber,
  sumStatisticChange,
  todHolidays,
  todPeriodForPacific,
  todWeekDays,
} from "./data.js?v=0.10.0";
import {
  createBarChart,
  createLineChart,
  createMonthCompareChart,
  createScatter,
  createUsageComboChart,
  destroyCharts,
  renderHeatmap,
  seriesColors,
} from "./charts.js?v=0.10.0";
import { sparklineSvg } from "./svg-helpers.js?v=0.10.0";
import { applyPanelTheme } from "./theme.js?v=0.10.0";

/** @type {Record<string, string>} */
export const PANEL_SECTION_ANCHORS = {
  glance: "#kpis",
  usage: "#hero",
  analytics: "#insights-weather",
  tod: "#tod",
  billing: "#billing",
  programs: "#programs",
};

/**
 * Resolve a panel.config.default_section value to a shadow-root selector.
 * @param {unknown} section
 * @returns {string}
 */
export function resolveLandingSelector(section) {
  const key = typeof section === "string" ? section.trim() : "";
  return PANEL_SECTION_ANCHORS[key] || PANEL_SECTION_ANCHORS.glance;
}

const STYLE = `
:host {
  display: block;
  width: 100%;
  max-width: 100%;
  overflow-x: clip;
  box-sizing: border-box;
  color: var(--primary-text-color);
  background: var(--primary-background-color);
  /* Series/status colors follow HA semantic theme tokens (adapt with any theme). */
  --pge-series-kwh: var(--info-color, var(--primary-color, #2a78d6));
  --pge-series-cost: var(--accent-color, var(--warning-color, #eb6834));
  --pge-series-payment: var(--success-color, #1baf7a);
  --pge-series-savings: var(--success-color, #008300);
  --pge-temp-cold: var(--info-color, var(--primary-color, #2a78d6));
  --pge-temp-hot: var(--error-color, #e34948);
  --pge-status-good: var(--success-color, #1baf7a);
  --pge-status-warn: var(--warning-color, #eb6834);
  --pge-status-critical: var(--error-color, #e34948);
  --pge-tod-off: var(--success-color, #1baf7a);
  --pge-tod-mid: var(--warning-color, #eb6834);
  --pge-tod-on: var(--error-color, #e34948);
  color-scheme: light;
}
:host *, :host *::before, :host *::after { box-sizing: border-box; }
:host([data-dark]) {
  color-scheme: dark;
}
@media (prefers-reduced-motion: reduce) {
  :host * { transition: none !important; animation: none !important; }
}
.toolbar {
  display: flex; align-items: center; gap: 12px;
  padding: 8px 16px; min-height: 56px;
  background: var(--app-header-background-color, var(--primary-color));
  color: var(--app-header-text-color, var(--text-primary-color, #fff));
  position: sticky; top: 0; z-index: 2;
}
.toolbar button.menu {
  background: none; border: 0; color: inherit; cursor: pointer;
  font-size: 22px; width: 40px; height: 40px;
}
.toolbar .brand { display: flex; align-items: center; gap: 10px; font-weight: 600; }
.toolbar img { height: 28px; width: auto; }
.content { padding: 16px; max-width: 1200px; margin: 0 auto; }
.tabs { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.tabs button {
  border: 1px solid var(--divider-color); background: var(--card-background-color);
  color: var(--primary-text-color); border-radius: 8px; padding: 6px 12px; cursor: pointer;
}
.tabs button.active { border-color: var(--primary-color); color: var(--primary-color); font-weight: 600; }
.card {
  background: var(--card-background-color, var(--ha-card-background, var(--primary-background-color)));
  color: var(--primary-text-color);
  border-radius: var(--ha-card-border-radius, 12px);
  border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color));
  box-shadow: var(--ha-card-box-shadow, none);
  padding: 16px; margin-bottom: 16px;
}
.card h2, .card h3 { margin: 0 0 12px; font-size: 1.1rem; font-weight: 600; color: var(--primary-text-color); }
.kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; }
.kpi {
  border: 1px solid var(--divider-color); border-radius: 10px; padding: 12px;
  /* Tint from text+card so nested tiles never stick to a light/dark-specific hex. */
  background: color-mix(
    in srgb,
    var(--primary-text-color) 6%,
    var(--card-background-color, var(--primary-background-color, transparent))
  );
  color: var(--primary-text-color);
  border-left-width: 3px;
  border-left-style: solid;
  border-left-color: transparent;
  transform: translateY(0);
  box-shadow: none;
  transition:
    transform 180ms cubic-bezier(0.22, 1, 0.36, 1),
    box-shadow 180ms cubic-bezier(0.22, 1, 0.36, 1),
    background 180ms ease,
    border-color 180ms ease;
  will-change: transform;
}
#kpis .kpi { cursor: pointer; }
.kpi:focus-visible {
  /* Keep a real outline for keyboard / forced-colors; do not set outline: none. */
  outline: 2px solid var(--primary-color, Highlight);
  outline-offset: 2px;
}
.kpi .label { font-size: 0.75rem; color: var(--secondary-text-color); }
.kpi .value {
  font-size: 1.35rem; font-weight: 650; margin: 4px 0; color: var(--primary-text-color);
  transform: translateZ(0);
  transition: transform 180ms cubic-bezier(0.22, 1, 0.36, 1);
}
.kpi .delta { font-size: 0.75rem; color: var(--secondary-text-color); }
.kpi svg {
  display: block;
  margin-top: 2px;
  transition: opacity 180ms ease, filter 180ms ease;
  opacity: 0.92;
}
.kpi:hover,
.kpi:focus,
.kpi:focus-within {
  transform: translateY(-3px);
  background: color-mix(
    in srgb,
    var(--primary-color, #2a78d6) 10%,
    var(--card-background-color, var(--primary-background-color, transparent))
  );
  border-color: color-mix(in srgb, var(--primary-color, #2a78d6) 35%, var(--divider-color));
  box-shadow:
    0 6px 16px color-mix(in srgb, var(--primary-text-color) 10%, transparent),
    0 1px 0 color-mix(in srgb, var(--primary-text-color) 4%, transparent);
}
.kpi:hover .value,
.kpi:focus .value,
.kpi:focus-within .value { transform: scale(1.03); transform-origin: left center; }
.kpi:hover svg,
.kpi:focus svg,
.kpi:focus-within svg {
  opacity: 1;
  filter: drop-shadow(0 1px 2px color-mix(in srgb, var(--primary-text-color) 18%, transparent));
}
.kpi.copied {
  border-color: var(--primary-color, #2a78d6);
  box-shadow:
    0 0 0 1px color-mix(in srgb, var(--primary-color, #2a78d6) 45%, transparent),
    0 6px 16px color-mix(in srgb, var(--primary-color, #2a78d6) 18%, transparent);
}
.kpi.status-good { border-left-color: var(--pge-status-good); }
.kpi.status-warn { border-left-color: var(--pge-status-warn); }
.kpi.status-critical { border-left-color: var(--pge-status-critical); }
.kpi.kpi-usage { border-left-color: var(--pge-series-kwh); }
.kpi.kpi-statement { border-left-color: var(--pge-series-cost); }
.kpi.kpi-estimate { border-left-color: var(--pge-series-savings); }
/* Min/max dual tip ($a/$b) is longer than a single KPI figure — shrink to fit. */
.kpi.kpi-estimate.kpi-dual .value {
  font-size: 1.15rem !important;
}
.kpi.status-good:hover, .kpi.status-good:focus, .kpi.status-good:focus-within {
  box-shadow:
    0 6px 16px color-mix(in srgb, var(--pge-status-good) 22%, transparent),
    0 0 0 1px color-mix(in srgb, var(--pge-status-good) 28%, transparent);
}
.kpi.status-warn:hover, .kpi.status-warn:focus, .kpi.status-warn:focus-within,
.kpi.kpi-statement:hover, .kpi.kpi-statement:focus, .kpi.kpi-statement:focus-within {
  box-shadow:
    0 6px 16px color-mix(in srgb, var(--pge-series-cost) 22%, transparent),
    0 0 0 1px color-mix(in srgb, var(--pge-series-cost) 28%, transparent);
}
.kpi.status-critical:hover, .kpi.status-critical:focus, .kpi.status-critical:focus-within {
  box-shadow:
    0 6px 16px color-mix(in srgb, var(--pge-status-critical) 22%, transparent),
    0 0 0 1px color-mix(in srgb, var(--pge-status-critical) 28%, transparent);
}
.kpi.kpi-usage:hover, .kpi.kpi-usage:focus, .kpi.kpi-usage:focus-within {
  box-shadow:
    0 6px 16px color-mix(in srgb, var(--pge-series-kwh) 22%, transparent),
    0 0 0 1px color-mix(in srgb, var(--pge-series-kwh) 28%, transparent);
}
.kpi.kpi-estimate:hover, .kpi.kpi-estimate:focus, .kpi.kpi-estimate:focus-within {
  box-shadow:
    0 6px 16px color-mix(in srgb, var(--pge-series-savings) 22%, transparent),
    0 0 0 1px color-mix(in srgb, var(--pge-series-savings) 28%, transparent);
}
.sync-strip { display: grid; gap: 10px; }
.sync-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.sync-row progress {
  flex: 1; min-width: 160px; height: 10px;
  accent-color: var(--primary-color);
}
details.sync-gaps-panel {
  margin: 0;
  width: 100%;
  padding: 0;
}
.sync-gaps-body {
  display: grid;
  gap: 16px;
  padding: 0 0 4px;
}
.sync-gaps-body .data-gaps h3 {
  margin: 0 0 8px;
  font-size: 1rem;
  font-weight: 600;
}
.btn {
  border: 0; border-radius: 8px; padding: 8px 14px; cursor: pointer;
  background: var(--primary-color);
  color: var(--text-primary-color, var(--app-header-text-color, #fff));
  font-weight: 600;
}
.btn.secondary { background: var(--secondary-background-color); color: var(--primary-text-color);
  border: 1px solid var(--divider-color); }
.filters { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; align-items: center; }
.filters button, .filters select, .filters input[type="datetime-local"] {
  border: 1px solid var(--divider-color);
  background: var(--card-background-color, var(--secondary-background-color));
  color: var(--primary-text-color);
  border-radius: 8px; padding: 6px 10px; cursor: pointer;
  color-scheme: inherit;
}
.filters button.active { border-color: var(--primary-color); color: var(--primary-color); font-weight: 600; }
.filters button:disabled { opacity: 0.45; cursor: not-allowed; }
.filters select.range-more {
  min-width: 8.5rem;
  font-weight: 500;
}
.filters select.range-more.active {
  border-color: var(--primary-color);
  color: var(--primary-color);
  font-weight: 600;
}
.filters .range-nav { display: inline-flex; gap: 4px; align-items: center; }
.filters .range-label {
  font-size: 0.8rem; color: var(--secondary-text-color); min-width: 12rem;
}
.filters .range-custom { display: inline-flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.chart-host { width: 100%; min-height: 140px; }
.chart-host.usage-combo { min-height: 380px; }
.chart-host.scatter-wide { min-height: 300px; }
.usage-stats { margin-top: 16px; }
.usage-stats h3 { margin: 0 0 4px; font-size: 1rem; font-weight: 600; }
.usage-stats .stats-meta { margin: 0 0 10px; }
.usage-summary-wrap {
  width: 100%;
  margin-bottom: 14px;
  border: 1px solid var(--divider-color);
  border-radius: 12px;
  overflow: hidden;
  background: var(--card-background-color, var(--primary-background-color));
}
.usage-summary-section + .usage-summary-section {
  border-top: 1px solid var(--divider-color);
}
.usage-summary-section-title {
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--secondary-text-color);
  padding: 8px 12px 6px;
  background: color-mix(
    in srgb,
    var(--primary-text-color) 7%,
    var(--card-background-color, var(--primary-background-color, transparent))
  );
  border-bottom: 1px solid var(--divider-color);
}
.usage-summary-items {
  display: grid;
  grid-template-columns: 1fr 1fr;
}
.usage-summary-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 2px 10px;
  align-items: baseline;
  padding: 8px 12px;
  border-bottom: 1px solid var(--divider-color);
  border-right: 1px solid var(--divider-color);
  min-width: 0;
}
.usage-summary-item:nth-child(2n) { border-right: 0; }
.usage-summary-items > .usage-summary-item:nth-last-child(-n+2) { border-bottom: 0; }
.usage-summary-items > .usage-summary-item:last-child:nth-child(odd) { border-bottom: 0; }
.usage-summary-item:nth-child(4n+1),
.usage-summary-item:nth-child(4n+2) {
  background: color-mix(
    in srgb,
    var(--primary-text-color) 3.5%,
    var(--card-background-color, var(--primary-background-color, transparent))
  );
}
.usage-summary-item:hover {
  background: color-mix(
    in srgb,
    var(--primary-color, #2a78d6) 12%,
    var(--card-background-color, var(--primary-background-color, transparent))
  );
}
.usage-summary-item .metric {
  color: var(--secondary-text-color);
  font-size: 0.82rem;
  min-width: 0;
  overflow-wrap: anywhere;
}
.usage-summary-item .value {
  font-weight: 650;
  text-align: right;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  color: var(--primary-text-color);
}
.usage-summary-item .note {
  grid-column: 1 / -1;
  color: var(--secondary-text-color);
  font-size: 0.75rem;
  line-height: 1.3;
}
.usage-table-wrap {
  width: 100%;
  max-height: min(52vh, 480px);
  overflow: auto;
  -webkit-overflow-scrolling: touch;
  border: 1px solid var(--divider-color);
  border-radius: 12px;
  background: var(--card-background-color, var(--primary-background-color));
}
.usage-day-table {
  width: 100%;
  min-width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 0.95rem;
  table-layout: fixed;
}
.usage-day-table th, .usage-day-table td {
  border-bottom: 1px solid var(--divider-color);
  padding: 10px 14px;
  text-align: right;
  color: var(--primary-text-color);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.usage-day-table th:first-child, .usage-day-table td:first-child { text-align: left; width: 18%; }
.usage-day-table th:nth-child(2), .usage-day-table td:nth-child(2) { width: 12%; }
.usage-day-table th:nth-child(3), .usage-day-table td:nth-child(3) { width: 12%; }
.usage-day-table th:nth-child(4), .usage-day-table td:nth-child(4) { width: 12%; }
.usage-day-table th:nth-child(5), .usage-day-table td:nth-child(5) { width: 12%; }
.usage-day-table th:nth-child(6), .usage-day-table td:nth-child(6) { width: 12%; }
.usage-day-table th:nth-child(7), .usage-day-table td:nth-child(7) { width: 14%; }
.usage-day-table thead th {
  color: var(--secondary-text-color);
  font-weight: 650;
  font-size: 0.8rem;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  position: sticky;
  top: 0;
  z-index: 1;
  background: color-mix(
    in srgb,
    var(--primary-text-color) 6%,
    var(--card-background-color, var(--primary-background-color, transparent))
  );
  border-bottom: 1px solid var(--divider-color);
  cursor: pointer;
  user-select: none;
}
.usage-day-table thead th:hover {
  color: var(--primary-text-color);
  background: color-mix(
    in srgb,
    var(--primary-color, #2a78d6) 12%,
    var(--card-background-color, var(--primary-background-color, transparent))
  );
}
.usage-day-table thead th[data-sort-dir="asc"]::after { content: " ↑"; color: var(--primary-color); }
.usage-day-table thead th[data-sort-dir="desc"]::after { content: " ↓"; color: var(--primary-color); }
.usage-day-table tbody tr:nth-child(even) td {
  background: color-mix(
    in srgb,
    var(--primary-text-color) 4%,
    var(--card-background-color, var(--primary-background-color, transparent))
  );
}
.usage-day-table tbody tr:hover td {
  background: color-mix(
    in srgb,
    var(--primary-color, #2a78d6) 14%,
    var(--card-background-color, var(--primary-background-color, transparent))
  );
}
.usage-day-table tbody tr:focus-within td {
  outline: none;
  background: color-mix(
    in srgb,
    var(--primary-color, #2a78d6) 18%,
    var(--card-background-color, var(--primary-background-color, transparent))
  );
}
.usage-day-table tfoot td {
  font-weight: 700;
  position: sticky;
  bottom: 0;
  z-index: 1;
  background: color-mix(
    in srgb,
    var(--primary-text-color) 8%,
    var(--card-background-color, var(--primary-background-color, transparent))
  );
  border-top: 2px solid var(--divider-color);
  border-bottom: 0;
}
details.usage-accounting,
details.usage-rollup,
details.sync-gaps-panel {
  margin-top: 16px;
  width: 100%;
  padding: 0;
}
.usage-stats details.usage-accounting { margin-top: 0; }
details.sync-gaps-panel { margin-top: 0; }
details.usage-accounting > summary,
details.usage-rollup > summary,
details.sync-gaps-panel > summary {
  cursor: pointer;
  display: block;
  position: relative;
  list-style: none;
  padding: 8px 12px 10px 22px;
  margin: 0 0 8px;
  color: var(--primary-text-color);
  border-radius: 8px;
}
details.usage-accounting > summary::-webkit-details-marker,
details.usage-rollup > summary::-webkit-details-marker,
details.sync-gaps-panel > summary::-webkit-details-marker { display: none; }
details.usage-accounting > summary::marker,
details.usage-rollup > summary::marker,
details.sync-gaps-panel > summary::marker { content: ""; }
details.usage-accounting > summary::before,
details.usage-rollup > summary::before,
details.sync-gaps-panel > summary::before {
  content: "▸";
  position: absolute;
  left: 4px;
  top: 0.55em;
  font-size: 0.85em;
  line-height: 1;
  color: var(--secondary-text-color);
}
details.usage-accounting[open] > summary::before,
details.usage-rollup[open] > summary::before,
details.sync-gaps-panel[open] > summary::before { content: "▾"; }
details.usage-accounting > summary:hover,
details.usage-rollup > summary:hover,
details.sync-gaps-panel > summary:hover {
  color: var(--primary-color);
  background: color-mix(
    in srgb,
    var(--primary-color, #2a78d6) 8%,
    var(--card-background-color, var(--primary-background-color, transparent))
  );
}
details.usage-accounting > summary:hover::before,
details.usage-rollup > summary:hover::before,
details.sync-gaps-panel > summary:hover::before { color: var(--primary-color); }
.rollup-title {
  display: block;
  font-weight: 650;
  font-size: 1.05rem;
  line-height: 1.3;
}
details.usage-accounting > summary .rollup-title { font-size: 1.1rem; }
.rollup-caption {
  display: block;
  margin-top: 4px;
  font-weight: 400;
  font-size: 0.82rem;
  line-height: 1.35;
  color: var(--secondary-text-color);
}
details.usage-accounting .usage-accounting-body { padding: 0 0 4px; }
.insights-cost-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: stretch; }
.insights-cost-grid .chart-host { min-height: 200px; height: 200px; }
.chart-empty { margin: 12px 0; font-size: 0.85rem; }
.data-gaps ul { margin: 0; padding-left: 1.2rem; display: grid; gap: 6px; }
.data-gaps li { font-size: 0.9rem; color: var(--primary-text-color); }
.data-gaps .gap-ok { color: var(--pge-status-good); }
.data-gaps .gap-warn { color: var(--pge-status-warn); }
.data-gaps .muted { margin: 0 0 8px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.entities { display: grid; gap: 6px; }
.entity-row { display: flex; justify-content: space-between; gap: 12px; padding: 6px 0;
  border-bottom: 1px solid var(--divider-color); font-size: 0.95rem; }
.programs { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; }
.program {
  border: 1px solid var(--divider-color); border-radius: 10px; padding: 12px;
  background: color-mix(
    in srgb,
    var(--primary-text-color) 4%,
    var(--card-background-color, var(--primary-background-color, transparent))
  );
  color: var(--primary-text-color);
  border-left-width: 3px;
  border-left-style: solid;
  transform: translateY(0);
  box-shadow: none;
  transition:
    transform 180ms cubic-bezier(0.22, 1, 0.36, 1),
    box-shadow 180ms cubic-bezier(0.22, 1, 0.36, 1),
    background 180ms ease,
    border-color 180ms ease,
    opacity 180ms ease;
}
.program.on { border-left-color: var(--pge-status-good); }
.program.off { border-left-color: var(--divider-color); opacity: 0.85; }
.program .name { font-weight: 600; transition: color 180ms ease; }
.program .state { font-size: 0.85rem; color: var(--secondary-text-color); }
.program:hover,
.program:focus-within {
  transform: translateY(-3px);
  opacity: 1;
  background: color-mix(
    in srgb,
    var(--primary-color, #2a78d6) 10%,
    var(--card-background-color, var(--primary-background-color, transparent))
  );
  border-color: color-mix(in srgb, var(--primary-color, #2a78d6) 35%, var(--divider-color));
  box-shadow:
    0 6px 16px color-mix(in srgb, var(--primary-text-color) 10%, transparent),
    0 1px 0 color-mix(in srgb, var(--primary-text-color) 4%, transparent);
}
.program.on:hover, .program.on:focus-within {
  box-shadow:
    0 6px 16px color-mix(in srgb, var(--pge-status-good) 22%, transparent),
    0 0 0 1px color-mix(in srgb, var(--pge-status-good) 28%, transparent);
}
.program:hover .name, .program:focus-within .name { color: var(--primary-color); }
details.diagnostics summary { cursor: pointer; font-weight: 600; margin-bottom: 8px; }
.pge-heatmap-title { font-size: 0.9rem; margin-bottom: 8px; color: var(--secondary-text-color); }
.pge-heatmap-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(10px, 1fr)); gap: 2px;
}
.pge-heatmap-cell { aspect-ratio: 1; border-radius: 2px; }
.muted { color: var(--secondary-text-color); font-size: 0.85rem; }
.error { color: var(--error-color, var(--pge-status-critical)); }
.entity-row span { color: var(--secondary-text-color); }
.entity-row strong { color: var(--primary-text-color); }

/* Tablet */
@media (max-width: 900px) {
  .content { padding: 12px; }
  .card { padding: 14px; margin-bottom: 12px; }
  .insights-cost-grid,
  .grid-2 { grid-template-columns: 1fr; }
  .usage-summary-item .note { display: none; }
  .filters .range-label { min-width: 0; flex: 1 1 100%; }
  .chart-host.usage-combo { min-height: 300px; }
  .chart-host.scatter-wide { min-height: 260px; }
}

/* Phone */
@media (max-width: 640px) {
  .toolbar { padding: 6px 10px; gap: 8px; }
  .content { padding: 10px; }
  .card { padding: 12px; border-radius: 10px; }
  .card h2, .card h3 { font-size: 1.05rem; }
  .kpi-row { grid-template-columns: 1fr 1fr; gap: 8px; }
  .kpi { padding: 10px; }
  .kpi .value { font-size: 1.15rem; }
  .sync-row { gap: 8px; }
  .sync-row progress { min-width: 0; width: 100%; flex: 1 1 100%; }
  .sync-row .btn { flex: 1 1 calc(50% - 4px); min-height: 44px; }
  .btn { min-height: 40px; padding: 10px 14px; }
  .filters { gap: 6px; }
  .filters button, .filters select, .filters input[type="datetime-local"] {
    min-height: 40px; padding: 8px 10px; font-size: 0.9rem;
  }
  .filters .range-nav { width: 100%; justify-content: space-between; }
  .filters .range-nav button { flex: 0 0 44px; }
  .filters .range-custom {
    width: 100%;
    display: grid;
    grid-template-columns: 1fr;
    gap: 6px;
  }
  .filters .range-custom input[type="datetime-local"] { width: 100%; min-width: 0; }
  .filters .range-custom .btn { width: 100%; }
  .usage-summary-items { grid-template-columns: 1fr; }
  .usage-summary-item { border-right: 0; }
  .usage-summary-item:nth-child(2n) { border-right: 0; }
  .usage-summary-items > .usage-summary-item:nth-last-child(-n+2) { border-bottom: 1px solid var(--divider-color); }
  .usage-summary-items > .usage-summary-item:last-child { border-bottom: 0; }
  .usage-summary-item:nth-child(4n+1),
  .usage-summary-item:nth-child(4n+2) { background: transparent; }
  .usage-summary-item:nth-child(even) {
    background: color-mix(
      in srgb,
      var(--primary-text-color) 3.5%,
      var(--card-background-color, var(--primary-background-color, transparent))
    );
  }
  .tod-compare-pair { grid-template-columns: 1fr; }
  .tod-compare-vs { padding-top: 0; text-align: center; }
  .usage-table-wrap {
    max-height: min(60vh, 420px);
    -webkit-overflow-scrolling: touch;
  }
  .usage-day-table {
    font-size: 0.8rem;
    min-width: 520px;
    table-layout: auto;
  }
  .usage-day-table th, .usage-day-table td { padding: 8px 8px; }
  .chart-host.usage-combo { min-height: 260px; }
  .chart-host.scatter-wide { min-height: 220px; }
  .insights-cost-grid .chart-host { min-height: 180px; height: 180px; }
  .programs { grid-template-columns: 1fr 1fr; gap: 8px; }
  .program { padding: 10px; min-height: 64px; }
  details.usage-accounting > summary,
  details.usage-rollup > summary,
  details.sync-gaps-panel > summary {
    padding: 10px 12px 12px 26px;
    min-height: 44px;
  }
  .rollup-caption { font-size: 0.78rem; }
  .entity-row { flex-wrap: wrap; gap: 4px 12px; }
}

  /* ---- Time of Day hub (#tod) ---- */
  .tod-header { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 12px; }
  .tod-source { font-size: 0.78rem; }
  .badge {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 3px 10px; border-radius: 999px; font-size: 0.78rem; font-weight: 600;
    border: 1px solid var(--divider-color);
  }
  .badge.on { color: var(--pge-status-good); border-color: var(--pge-status-good); }
  .badge.off { color: var(--secondary-text-color); }
  .badge.unknown { color: var(--secondary-text-color); border-style: dashed; }
  .kpi.tod-off_peak { border-left-color: var(--pge-tod-off); }
  .kpi.tod-mid_peak { border-left-color: var(--pge-tod-mid); }
  .kpi.tod-on_peak { border-left-color: var(--pge-tod-on); }
  .tod-schedule { margin-top: 16px; }
  .tod-legend { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin: 0 0 8px; font-size: 0.78rem; }
  .tod-legend .legend { display: inline-flex; align-items: center; gap: 5px; color: var(--secondary-text-color); }
  .tod-legend .legend i { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
  .legend.off_peak i { background: var(--pge-tod-off); }
  .legend.mid_peak i { background: var(--pge-tod-mid); }
  .legend.on_peak i { background: var(--pge-tod-on); }
  .tod-grid {
    display: grid;
    grid-template-columns: 52px repeat(24, 1fr);
    gap: 2px;
    overflow-x: auto;
    padding-bottom: 4px;
  }
  .tod-grid-head { font-size: 0.68rem; color: var(--secondary-text-color); text-align: center; align-self: end; }
  .tod-grid-label { font-size: 0.72rem; color: var(--secondary-text-color); align-self: center; padding-right: 4px; white-space: nowrap; }
  .tod-cell { height: 18px; border-radius: 3px; min-width: 12px; }
  .tod-cell.off_peak { background: var(--pge-tod-off); }
  .tod-cell.mid_peak { background: var(--pge-tod-mid); }
  .tod-cell.on_peak { background: var(--pge-tod-on); }
  .tod-cell.now {
    outline: 2px solid var(--primary-text-color);
    outline-offset: -2px;
    box-shadow: 0 0 0 1px var(--card-background-color, var(--primary-background-color));
  }
  details.tod-holidays { margin-top: 8px; }
  details.tod-holidays > summary { cursor: pointer; font-size: 0.85rem; color: var(--secondary-text-color); }
  .tod-holidays-body { margin-top: 6px; padding-left: 4px; font-size: 0.82rem; }
  .tod-usage { margin-top: 16px; }
  .tod-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; margin-top: 10px; }
  .tod-table th, .tod-table td { padding: 6px 8px; text-align: left; border-bottom: 1px solid var(--divider-color); }
  .tod-table .num { text-align: right; }
  .tod-table thead th { color: var(--secondary-text-color); font-weight: 600; }
  .tod-table tfoot td { font-weight: 600; }
  .tod-share-bar {
    display: flex; width: 100%; height: 14px; border-radius: 7px; overflow: hidden;
    margin-top: 10px; gap: 2px;
  }
  .tod-share-seg { height: 100%; }
  .tod-share-seg.off_peak { background: var(--pge-tod-off); }
  .tod-share-seg.mid_peak { background: var(--pge-tod-mid); }
  .tod-share-seg.on_peak { background: var(--pge-tod-on); }
  .tod-counterfactual {
    margin-top: 12px; padding: 12px; border-radius: 10px;
    border: 1px solid var(--divider-color);
    border-left-width: 3px; border-left-style: solid; border-left-color: var(--pge-series-savings);
    background: color-mix(
      in srgb,
      var(--primary-text-color) 5%,
      var(--card-background-color, var(--primary-background-color, transparent))
    );
  }
  .tod-counterfactual.official { border-left-color: var(--pge-status-good); }
  .tod-counterfactual .label { font-size: 0.75rem; color: var(--secondary-text-color); }
  .tod-counterfactual .value { font-size: 1.3rem; font-weight: 650; margin: 4px 0; }
  .tod-counterfactual .delta { font-size: 0.75rem; color: var(--secondary-text-color); }
  .tod-compare-verdict {
    font-size: 1.45rem;
    font-weight: 700;
    margin: 6px 0 2px;
    line-height: 1.2;
  }
  .tod-compare-verdict.cost-more { color: var(--pge-status-critical); }
  .tod-compare-verdict.save { color: var(--pge-status-good); }
  .tod-compare-pair {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    gap: 8px;
    align-items: start;
    margin: 6px 0 8px;
  }
  .tod-compare-leg .value { font-size: 1.15rem; font-weight: 650; margin: 2px 0 0; }
  .tod-compare-vs {
    align-self: center;
    font-size: 0.75rem;
    color: var(--secondary-text-color);
    padding-top: 1.1rem;
  }
  details.tod-compare-math { margin-top: 8px; }
  details.tod-compare-math > summary {
    cursor: pointer; font-size: 0.85rem; color: var(--secondary-text-color);
  }
  .tod-range { margin: 0 0 12px; }
  .tod-range-caption { margin: 0; flex: 1 1 100%; font-size: 0.85rem; }
  .tod-range .range-label { font-size: 0.82rem; color: var(--secondary-text-color); }
`;

class PgeEnergyPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._accounts = [];
    this._activeEntryId = null;
    this._syncByEntry = {};
    this._unsubSync = null;
    this._charts = [];
    this._rangeKey = "24h";
    this._rangeShift = 0;
    this._customRange = null;
    this._todRangeKey = "last_cycle";
    this._todCustomRange = null;
    this._todRangeTouched = false;
    this._todBillReady = false;
    this._todRenderGen = 0;
    this._availablePresets = null;
    this._period = "hour";
    this._loading = true;
    this._error = null;
    this._narrow = false;
    this._defaultSection = "glance";
    this._landingApplied = false;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    const themeChanged = applyPanelTheme(this, hass);
    if (first) {
      this._boot();
    } else if (!this._loading && this._account) {
      void this._renderKpis();
      this._renderBillingPrograms();
      this._renderSync();
      this._renderDiagnostics();
      // Bill-bound presets (cycle / last_cycle) may appear only after entity states hydrate.
      void this._probeAvailablePresets().then(() => {
        this._renderFilters();
        const billReady = !!this._billBounds();
        if (billReady !== this._todBillReady) {
          this._todBillReady = billReady;
          void this._renderTod();
        }
      });
      // Theme / dark-mode switches require chart option rebuild (canvas colors).
      if (themeChanged) {
        void this._rebuildThemeCharts();
      }
    }
  }
  get hass() {
    return this._hass;
  }

  set narrow(v) {
    this._narrow = !!v;
  }
  set route(_r) {}
  set panel(panel) {
    const section = panel?.config?.default_section;
    this._defaultSection =
      typeof section === "string" && section.trim()
        ? section.trim()
        : "glance";
  }

  disconnectedCallback() {
    if (this._unsubSync) {
      this._unsubSync();
      this._unsubSync = null;
    }
    destroyCharts(this._charts);
    this._charts = [];
  }

  async _boot() {
    this._renderShell();
    try {
      const res = await this._hass.callWS({ type: "pge_energy/accounts" });
      this._accounts = res.accounts || [];
      if (!this._activeEntryId && this._accounts.length) {
        this._activeEntryId = this._accounts[0].entry_id;
      }
      this._unsubSync = await this._hass.connection.subscribeMessage(
        (msg) => {
          for (const entry of msg.entries || []) {
            this._syncByEntry[entry.entry_id] = entry;
          }
          invalidateStatsCache();
          this._renderSync();
          this._renderDiagnostics();
          void this._renderDataGaps();
        },
        { type: "pge_energy/sync/subscribe" }
      );
      this._loading = false;
      this._error = null;
      this._renderShell();
      await this._renderAll();
      this._scheduleDefaultLandingScroll();
    } catch (err) {
      this._loading = false;
      this._error = err?.message || String(err);
      this._renderShell();
    }
  }

  _scheduleDefaultLandingScroll() {
    if (this._landingApplied || this._error || !this._accounts.length) {
      return;
    }
    const root = this.shadowRoot;
    if (!root) {
      return;
    }
    const selector = resolveLandingSelector(this._defaultSection);
    const target =
      root.querySelector(selector) || root.querySelector(PANEL_SECTION_ANCHORS.glance);
    if (!target) {
      return;
    }
    this._landingApplied = true;
    requestAnimationFrame(() => {
      try {
        target.scrollIntoView({ block: "start" });
      } catch (_err) {
        // Ignore scroll failures (detached node / unsupported).
      }
    });
  }

  get _account() {
    return this._accounts.find((a) => a.entry_id === this._activeEntryId) || null;
  }

  _renderShell() {
    applyPanelTheme(this, this._hass);
    const root = this.shadowRoot;
    if (!root.querySelector(".toolbar")) {
      root.innerHTML = `<style>${STYLE}</style>
        <div class="toolbar">
          <button class="menu" type="button" title="Menu" aria-label="Toggle sidebar">☰</button>
          <div class="brand">
            <img src="/pge_energy_brand/logo.png" alt="PGE" />
            <span>PGE</span>
          </div>
        </div>
        <div class="content"></div>`;
      root.querySelector(".menu").addEventListener("click", () => {
        this.dispatchEvent(
          new CustomEvent("hass-toggle-menu", { bubbles: true, composed: true })
        );
      });
    }
    const content = root.querySelector(".content");
    if (this._loading) {
      content.innerHTML = `<div class="card muted">Loading PGE accounts…</div>`;
      return;
    }
    if (this._error) {
      content.innerHTML = `<div class="card error">Failed to load panel: ${this._escape(this._error)}</div>`;
      return;
    }
    if (!this._accounts.length) {
      content.innerHTML = `<div class="card">No PGE Energy accounts configured. Add the integration first.</div>`;
      return;
    }

    const tabs =
      this._accounts.length > 1
        ? `<div class="tabs">${this._accounts
            .map(
              (a) =>
                `<button type="button" data-entry="${a.entry_id}" class="${
                  a.entry_id === this._activeEntryId ? "active" : ""
                }">${this._escape(a.title || a.account_id)}</button>`
            )
            .join("")}</div>`
        : "";

    content.innerHTML = `
      ${tabs}
      <section class="card" id="kpis"></section>
      <section class="card sync-gaps" id="sync-gaps">
        <details class="sync-gaps-panel" data-persist="sync_status"${this._detailsOpenAttr(
          "sync_status"
        )}>
          <summary>
            <span class="rollup-title">Sync status</span>
            <span class="rollup-caption">Import progress and upstream PGE publication gaps</span>
          </summary>
          <div class="sync-gaps-body">
            <div class="sync-strip" id="sync"></div>
            <div class="data-gaps" id="data-gaps"></div>
          </div>
        </details>
      </section>
      <section class="card" id="hero">
        <h2>Usage</h2>
        <div class="filters" id="filters"></div>
        <div class="chart-host usage-combo" id="chart-usage"></div>
        <div class="usage-stats" id="usage-stats"></div>
      </section>
      <section class="card" id="insights-weather">
        <h3>Weather vs usage</h3>
        <p class="muted" style="margin:0 0 8px">Daily kWh vs outdoor °F (days with both samples).</p>
        <div class="chart-host scatter-wide" id="scatter"></div>
      </section>
      <section class="card" id="insights-cost">
        <h3>Cost intelligence</h3>
        <p class="muted" style="margin:0 0 8px">Monthly average rate and statement billed vs payments.</p>
        <div class="insights-cost-grid">
          <div class="chart-host" id="cost-per-kwh"></div>
          <div class="chart-host" id="billed-paid"></div>
        </div>
      </section>
      <section class="card grid-2" id="insights-heat">
        <div id="heatmap-kwh"></div>
        <div id="heatmap-temp"></div>
        <p class="muted" style="grid-column:1/-1;margin:0">Gray cells are days without an imported sample in recorder — not a full calendar year of PGE data.</p>
      </section>
      <section class="card" id="billing"></section>
      <section class="card" id="tod"></section>
      <section class="card" id="programs"></section>
      <section class="card">
        <details class="diagnostics" id="diagnostics"><summary>Diagnostics</summary><div id="diag-body"></div></details>
      </section>
    `;

    content.querySelectorAll(".tabs button").forEach((btn) => {
      btn.addEventListener("click", async () => {
        this._activeEntryId = btn.dataset.entry;
        this._renderShell();
        await this._renderAll();
      });
    });
    this._bindPersistentDetails(content.querySelector("#sync-gaps"));
  }

  async _renderAll() {
    destroyCharts(this._charts);
    this._charts = [];
    await this._probeAvailablePresets();
    this._todBillReady = !!this._billBounds();
    this._renderFilters();
    this._renderSync();
    await this._renderKpis();
    await this._renderDataGaps();
    await this._renderHero();
    await this._renderInsights();
    await this._renderTod();
    this._renderBillingPrograms();
    this._renderDiagnostics();
  }

  _normalizeRangeKey(key) {
    if (key === "yesterday") return "24h";
    return key || "24h";
  }

  _billBounds() {
    if (!this._account || !this._hass) return null;
    const startRaw = stateDisplay(this._hass, this._account.entity_ids.current_bill_start, "");
    const endRaw = stateDisplay(this._hass, this._account.entity_ids.current_bill_end, "");
    if (!startRaw || !endRaw || startRaw === "unknown" || endRaw === "unknown") {
      return null;
    }
    const start = new Date(startRaw);
    const end = new Date(endRaw);
    if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || end <= start) {
      return null;
    }
    return { start, end };
  }

  _basePresetRange(key = this._rangeKey) {
    const presets = rangePresets();
    const normalized = this._normalizeRangeKey(key);
    let range = presets[normalized] || presets["24h"];
    const bill = this._billBounds();
    if (normalized === "cycle" && bill) {
      const end = clampToPublishedEnd(bill.end);
      if (end > bill.start) {
        range = { start: bill.start, end, period: "day", label: "cycle" };
      }
    } else if (normalized === "last_cycle" && bill) {
      // Prior period of equal length ending at the current statement start.
      const duration = bill.end.getTime() - bill.start.getTime();
      const lastEnd = bill.start;
      const lastStart = new Date(lastEnd.getTime() - duration);
      const end = clampToPublishedEnd(lastEnd);
      if (Number.isFinite(lastStart.getTime()) && end > lastStart) {
        range = { start: lastStart, end, period: "day", label: "last_cycle" };
      }
    }
    return { ...range, key: normalized };
  }

  _resolveChartRange() {
    if (this._customRange?.start && this._customRange?.end) {
      const start = new Date(this._customRange.start);
      const end = clampToPublishedEnd(this._customRange.end);
      if (Number.isFinite(start.getTime()) && end > start) {
        return {
          start,
          end,
          period: this._period || "hour",
          key: "custom",
          label: "custom",
        };
      }
    }
    const base = this._basePresetRange();
    const shifted = shiftChartRange(base, -Math.max(0, this._rangeShift || 0));
    return { ...shifted, key: base.key, label: base.label || base.key };
  }

  _ensureTodRangeKey() {
    if (this._todCustomRange?.start && this._todCustomRange?.end) return;
    const available = this._todAvailablePresets();
    // Untouched default prefers Last cycle only when statement dates exist;
    // otherwise fall through to a short exact-window preset (not a fake cycle).
    if (!this._todRangeTouched) {
      const preferred = ["last_cycle", "cycle", "30d", "7d", "24h"].find((k) =>
        available.has(k)
      );
      this._todRangeKey = preferred || "24h";
      return;
    }
    const key = this._normalizeRangeKey(this._todRangeKey);
    if (available.has(key)) {
      this._todRangeKey = key;
      return;
    }
    const fallback = ["last_cycle", "cycle", "30d", "7d", "24h"].find((k) =>
      available.has(k)
    );
    this._todRangeKey = fallback || "24h";
  }

  _resolveTodRange() {
    if (this._todCustomRange?.start && this._todCustomRange?.end) {
      const start = new Date(this._todCustomRange.start);
      const end = clampToPublishedEnd(this._todCustomRange.end);
      if (Number.isFinite(start.getTime()) && end > start) {
        const clamped = this._clampTodExactWindow(start, end);
        // Persist the clamp so the datetime inputs match the analyzed window.
        if (clamped.capped) {
          this._todCustomRange = { start: clamped.start, end: clamped.end };
        }
        return {
          start: clamped.start,
          end: clamped.end,
          period: "hour",
          key: "custom",
          label: "custom",
          capped: clamped.capped,
        };
      }
    }
    this._ensureTodRangeKey();
    const base = this._basePresetRange(this._todRangeKey);
    return { ...base, key: this._todRangeKey, label: base.label || this._todRangeKey };
  }

  _selectTodRangeKey(key) {
    this._todRangeKey = this._normalizeRangeKey(key);
    this._todCustomRange = null;
    this._todRangeTouched = true;
  }

  async _probeAvailablePresets() {
    if (!this._account || !this._hass) {
      this._availablePresets = ["24h"];
      return;
    }
    const id = this._account.statistic_ids.consumption;
    const available = [];
    const bill = this._billBounds();
    for (const key of RANGE_PRESET_ORDER) {
      if (key === "cycle" || key === "last_cycle") {
        // Statement bounds alone make bill-bound presets meaningful.
        if (bill) available.push(key);
        continue;
      }
      try {
        const range = this._basePresetRange(key);
        const series = await fetchStatisticSeries(this._hass, id, {
          start: range.start,
          end: range.end,
          period: range.period,
          maxPoints: 400,
        });
        if (countSeriesPoints(series) >= minPointsForPreset(key)) {
          available.push(key);
        }
      } catch (_err) {
        /* probe optional */
      }
    }
    this._availablePresets = available.length ? available : ["24h"];
    const current = this._normalizeRangeKey(this._rangeKey);
    if (current !== "custom" && !this._availablePresets.includes(current)) {
      this._rangeKey = this._availablePresets.includes("24h")
        ? "24h"
        : this._availablePresets[0];
      this._rangeShift = 0;
      this._customRange = null;
      const preset = this._basePresetRange(this._rangeKey);
      if (preset?.period) this._period = preset.period;
    }
  }

  _selectRangeKey(key) {
    this._rangeKey = this._normalizeRangeKey(key);
    this._rangeShift = 0;
    this._customRange = null;
    const preset = this._basePresetRange(this._rangeKey);
    if (preset?.period) this._period = preset.period;
  }

  _toLocalInputValue(date) {
    const d = date instanceof Date ? date : new Date(date);
    if (!Number.isFinite(d.getTime())) return "";
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(
      d.getMinutes()
    )}`;
  }

  _renderFilters() {
    const el = this.shadowRoot.getElementById("filters");
    if (!el) return;
    this._rangeKey = this._normalizeRangeKey(this._rangeKey);
    const available = new Set(this._availablePresets || RANGE_PRESET_ORDER);
    const moreActive =
      !this._customRange && RANGE_PRESET_MORE.includes(this._rangeKey);
    const range = this._resolveChartRange();
    const published = publishedDataEnd();
    const canStepNewer = this._customRange
      ? range.end.getTime() < published.getTime()
      : (this._rangeShift || 0) > 0;
    const label = formatRangeLabel(range.start, range.end);
    const primaryButtons = RANGE_PRESET_PRIMARY.map((k) => {
      const enabled = available.has(k);
      const active = !this._customRange && this._rangeKey === k;
      const text = RANGE_PRESET_LABELS[k] || k;
      return `<button type="button" data-range="${k}" class="${active ? "active" : ""}" ${
        enabled ? "" : "disabled"
      } title="${this._escape(text)}">${this._escape(text)}</button>`;
    }).join("");
    const moreOptions = RANGE_PRESET_MORE.map((k) => {
      const enabled = available.has(k);
      const text = RANGE_PRESET_LABELS[k] || k;
      return `<option value="${k}" ${moreActive && this._rangeKey === k ? "selected" : ""} ${
        enabled ? "" : "disabled"
      }>${this._escape(text)}</option>`;
    }).join("");
    el.innerHTML = `
      ${primaryButtons}
      <select id="range-more" class="range-more ${moreActive ? "active" : ""}" aria-label="More ranges">
        <option value="" ${moreActive ? "" : "selected"}>More…</option>
        ${moreOptions}
      </select>
      <div class="range-nav">
        <button type="button" class="secondary" id="range-older" title="Older">◀</button>
        <button type="button" class="secondary" id="range-newer" title="Newer" ${
          canStepNewer ? "" : "disabled"
        }>▶</button>
      </div>
      <span class="range-label">${this._escape(label)}</span>
      <div class="range-custom">
        <input type="datetime-local" id="range-start" aria-label="Range start" value="${this._escape(
          this._toLocalInputValue(range.start)
        )}" />
        <input type="datetime-local" id="range-end" aria-label="Range end" value="${this._escape(
          this._toLocalInputValue(new Date(Math.max(range.start.getTime(), range.end.getTime() - 1)))
        )}" />
        <button type="button" class="secondary" id="range-apply">Apply</button>
      </div>
      <select id="period">
        <option value="hour" ${this._period === "hour" ? "selected" : ""}>Hour</option>
        <option value="day" ${this._period === "day" ? "selected" : ""}>Day</option>
        <option value="month" ${this._period === "month" ? "selected" : ""}>Month</option>
      </select>
    `;
    el.querySelectorAll("[data-range]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        this._selectRangeKey(btn.dataset.range);
        this._renderFilters();
        await this._renderHero();
      });
    });
    el.querySelector("#range-more").addEventListener("change", async (ev) => {
      const key = ev.target.value;
      if (!key) return;
      this._selectRangeKey(key);
      this._renderFilters();
      await this._renderHero();
    });
    el.querySelector("#range-older").addEventListener("click", async () => {
      if (this._customRange) {
        const duration = this._customRange.end - this._customRange.start;
        this._customRange = {
          start: new Date(this._customRange.start.getTime() - duration),
          end: new Date(this._customRange.end.getTime() - duration),
        };
      } else {
        this._rangeShift = (this._rangeShift || 0) + 1;
      }
      this._renderFilters();
      await this._renderHero();
    });
    el.querySelector("#range-newer").addEventListener("click", async () => {
      if (this._customRange) {
        const duration = this._customRange.end - this._customRange.start;
        const published = publishedDataEnd();
        let end = new Date(this._customRange.end.getTime() + duration);
        let start = new Date(this._customRange.start.getTime() + duration);
        if (end > published) {
          end = published;
          start = new Date(end.getTime() - duration);
        }
        this._customRange = { start, end };
      } else {
        this._rangeShift = Math.max(0, (this._rangeShift || 0) - 1);
      }
      this._renderFilters();
      await this._renderHero();
    });
    el.querySelector("#range-apply").addEventListener("click", async () => {
      const startRaw = el.querySelector("#range-start").value;
      const endRaw = el.querySelector("#range-end").value;
      const start = startRaw ? new Date(startRaw) : null;
      let end = endRaw ? new Date(endRaw) : null;
      if (!start || !end || !Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime())) {
        return;
      }
      // datetime-local is inclusive; chart ranges use exclusive end.
      end = new Date(end.getTime() + 60 * 1000);
      end = clampToPublishedEnd(end);
      if (end <= start) return;
      this._customRange = { start, end };
      this._rangeShift = 0;
      this._renderFilters();
      await this._renderHero();
    });
    el.querySelector("#period").addEventListener("change", async (ev) => {
      this._period = ev.target.value;
      await this._renderHero();
    });
  }

  async _renderDataGaps() {
    const el = this.shadowRoot.getElementById("data-gaps");
    if (!el || !this._account) return;
    const sync = this._syncByEntry[this._account.entry_id] || {};
    const published = publishedDataEnd();
    const items = [];
    items.push({
      level: "warn",
      text: "Pacific “today” is never charted — PGE only publishes complete days through yesterday.",
    });

    const newestRaw =
      sync.newest_interval ||
      stateDisplay(this._hass, this._account.entity_ids.latest_interval, "");
    if (newestRaw) {
      const tip = new Date(newestRaw);
      if (Number.isFinite(tip.getTime())) {
        const tipLabel = tip.toLocaleString("en-US", {
          timeZone: "America/Los_Angeles",
          month: "short",
          day: "numeric",
          hour: "numeric",
          minute: "2-digit",
        });
        const lagHours = Math.max(0, (published.getTime() - tip.getTime()) / (60 * 60 * 1000));
        if (lagHours > 2) {
          items.push({
            level: "warn",
            text: `Latest published usage interval is ${tipLabel} PT (${Math.round(
              lagHours
            )}h before the closed-day cutoff). Daytime tips near ~1:00 AM Pacific are normal overnight lag.`,
          });
        } else {
          items.push({
            level: "ok",
            text: `Latest published usage interval: ${tipLabel} PT.`,
          });
        }
      }
    }

    try {
      const day = rangePresets()["24h"];
      const ids = this._account.statistic_ids;
      const [kwh, temp] = await Promise.all([
        fetchStatisticSeries(this._hass, ids.consumption, {
          start: day.start,
          end: day.end,
          period: "hour",
          maxPoints: 48,
        }),
        fetchStatisticSeries(this._hass, ids.temperature, {
          start: day.start,
          end: day.end,
          period: "hour",
          maxPoints: 48,
        }),
      ]);
      const kwhN = countSeriesPoints(kwh);
      const tempN = countSeriesPoints(temp, "means");
      if (kwhN > 0 && tempN < kwhN) {
        items.push({
          level: "warn",
          text: `Outdoor temperature missing for ${kwhN - tempN} of ${kwhN} hours in the latest closed day (PGE returned null for those intervals).`,
        });
      } else if (kwhN > 0 && tempN >= kwhN) {
        items.push({
          level: "ok",
          text: `Outdoor temperature present for all ${kwhN} hours of the latest closed day.`,
        });
      }
      if (kwhN > 0 && kwhN < 20) {
        items.push({
          level: "warn",
          text: `Latest closed day has only ${kwhN} hourly usage rows so far — PGE may still be finishing publication.`,
        });
      }
    } catch (_err) {
      /* optional */
    }

    if (sync.error) {
      items.push({
        level: "warn",
        text: `Last sync note: ${sync.error}`,
      });
    }

    el.innerHTML = `
      <h3>PGE publication gaps</h3>
      <p class="muted">What Portland General Electric has not published (or not finished publishing) yet — these gaps are upstream of Home Assistant.</p>
      <ul>
        ${items
          .map(
            (item) =>
              `<li class="gap-${item.level}">${this._escape(item.text)}</li>`
          )
          .join("")}
      </ul>
    `;
  }

  _renderSync() {
    const el = this.shadowRoot.getElementById("sync");
    if (!el || !this._account) return;
    const sync = this._syncByEntry[this._account.entry_id] || {};
    const pct = sync.percent ?? 0;
    const status = sync.status || "idle";
    const eta =
      sync.eta_seconds != null ? `ETA ${Math.round(sync.eta_seconds / 60)} min` : "";
    el.innerHTML = `
      <div class="sync-row">
        <strong>${this._escape(status)}</strong>
        <span class="muted">${this._escape(sync.phase || "")}</span>
        <span class="muted">${eta}</span>
      </div>
      <div class="sync-row">
        <progress max="100" value="${pct}"></progress>
        <span>${pct}%</span>
      </div>
      <div class="muted">${this._escape(sync.message || "")}</div>
      ${sync.error ? `<div class="error">${this._escape(sync.error)}</div>` : ""}
      <div class="sync-row">
        <button class="btn" type="button" id="btn-refresh">Refresh</button>
        <button class="btn secondary" type="button" id="btn-backfill">Backfill</button>
        <span class="muted">Latest interval: ${this._escape(
          sync.newest_interval || stateDisplay(this._hass, this._account.entity_ids.latest_interval)
        )}</span>
      </div>
    `;
    el.querySelector("#btn-refresh").addEventListener("click", () => {
      this._hass.callService("pge_energy", "refresh", { entry_id: this._account.entry_id });
    });
    el.querySelector("#btn-backfill").addEventListener("click", () => {
      const end = publishedDataEnd();
      const start = new Date(end.getTime() - 30 * 24 * 60 * 60 * 1000);
      this._hass.callService("pge_energy", "backfill", {
        entry_id: this._account.entry_id,
        start_date: pacificYmd(start),
        end_date: pacificYmd(new Date(end.getTime() - 1)),
      });
    });
  }

  async _renderKpis() {
    const el = this.shadowRoot.getElementById("kpis");
    if (!el || !this._account) return;
    const e = this._account.entity_ids;
    // PGE publishes overnight (~24h lag) and the tip interval is often incomplete.
    // KPIs use closed days / billing-period totals only — never "today" or tip samples.
    const yesterdayKwh = stateNumber(this._hass, e.yesterday_energy);
    const yesterdayReturn = stateNumber(this._hass, e.yesterday_return);
    const yesterdayCost = stateNumber(this._hass, e.yesterday_cost);
    const yesterdayCompensation = stateNumber(this._hass, e.yesterday_compensation);
    // Same PGE billDetails period as current_bill_kwh (billingPeriodStartDate→EndDate).
    const cycleKwh = stateNumber(this._hass, e.current_bill_kwh);
    const cycleCost = stateNumber(this._hass, e.bill_current_charges);
    // PGE's own open-cycle estimates (getEnergyTrackerData) — not derived from
    // the imported intervals, so they are labelled and grouped separately.
    const estCharges = stateNumber(this._hass, e.est_current_charges);
    const estNextMin = stateNumber(this._hass, e.est_next_bill_min);
    const estNextMax = stateNumber(this._hass, e.est_next_bill_max);
    const cycleDay = stateNumber(this._hass, e.billing_cycle_day);
    const cycleDays = stateNumber(this._hass, e.billing_cycle_total_days);
    const amountDue = stateNumber(this._hass, e.amount_due);
    const lastPayment = stateNumber(this._hass, e.last_payment_amount);
    const lastPaymentDate = stateDisplay(this._hass, e.last_payment_date, "");
    const dueDate = stateDisplay(this._hass, e.due_date, "");
    const cycleStart = stateDisplay(this._hass, e.current_bill_start, "");
    const cycleEnd = stateDisplay(this._hass, e.current_bill_end, "");
    const cycleStartDay = this._fmtDate(cycleStart);
    const cycleEndDay = this._fmtDate(cycleEnd);
    const cycleRange =
      cycleStartDay && cycleEndDay
        ? `${cycleStartDay} → ${cycleEndDay}`
        : "Current PGE billing period";

    let dueStatus = "good";
    if (amountDue != null && amountDue > 0) {
      dueStatus = "warn";
      if (dueDate) {
        const due = Date.parse(dueDate);
        if (Number.isFinite(due)) {
          const days = (due - Date.now()) / (24 * 60 * 60 * 1000);
          if (days < 0) dueStatus = "critical";
          else if (days <= 5) dueStatus = "warn";
          else dueStatus = "good";
        }
      }
    } else if (amountDue === 0) {
      dueStatus = "good";
    }

    let sparkKwh = [];
    let sparkCost = [];
    let weekKwh = null;
    let weekCost = null;
    let weekRange = "Sun → yesterday";
    let sparkWeekKwh = [];
    let sparkWeekCost = [];
    let usageCycleKwh = null;
    let usageCycleCost = null;
    let sinceStatementKwh = null;
    let sinceStatementCost = null;
    let sinceStatementRange = "After statement cycle";
    let yesterdayCompensationStat = null;
    let sparkNetCost = null;
    try {
      const publishedEnd = publishedDataEnd();
      const weekStart = pacificWeekStartUtc();
      const sparkStart = new Date(publishedEnd.getTime() - 14 * 24 * 60 * 60 * 1000);
      const yesterdayStart = pacificMidnightUtc(priorPacificYmd(pacificYmd(publishedEnd)));
      const [kwhSeries, costSeries, weekKwhSum, weekCostSum, compensationDaySum, compensationSparkSeries] = await Promise.all([
        fetchStatisticSeries(this._hass, this._account.statistic_ids.consumption, {
          start: sparkStart,
          end: publishedEnd,
          period: "day",
          maxPoints: 32,
        }),
        fetchStatisticSeries(this._hass, this._account.statistic_ids.cost, {
          start: sparkStart,
          end: publishedEnd,
          period: "day",
          maxPoints: 32,
        }),
        sumStatisticChange(this._hass, this._account.statistic_ids.consumption, {
          start: weekStart,
          end: publishedEnd,
          period: "hour",
        }),
        sumStatisticChange(this._hass, this._account.statistic_ids.cost, {
          start: weekStart,
          end: publishedEnd,
          period: "hour",
        }),
        sumStatisticChange(this._hass, this._account.statistic_ids.compensation, {
          start: yesterdayStart,
          end: publishedEnd,
          period: "hour",
        }),
        fetchStatisticSeries(this._hass, this._account.statistic_ids.compensation, {
          start: sparkStart,
          end: publishedEnd,
          period: "day",
          maxPoints: 32,
        }),
      ]);
      sparkKwh = kwhSeries.values || [];
      sparkCost = costSeries.values || [];
      weekKwh = weekKwhSum.total;
      weekCost = weekCostSum.total;
      yesterdayCompensationStat = compensationDaySum.count > 0 ? compensationDaySum.total : null;
      {
        const compByX = new Map();
        const compXs = compensationSparkSeries.xs || [];
        const compVals = compensationSparkSeries.values || [];
        let observedCompensation = false;
        for (let i = 0; i < compXs.length; i++) {
          const cv = Number(compVals[i]);
          if (compXs[i] == null || !Number.isFinite(cv)) continue;
          compByX.set(Math.round(compXs[i]), cv);
          if (cv > 0) observedCompensation = true;
        }
        if (observedCompensation) {
          const xs = costSeries.xs || [];
          sparkNetCost = sparkCost.map((v, i) => {
            const cost = Number(v);
            if (!Number.isFinite(cost)) return null;
            const comp = compByX.get(Math.round(xs[i]));
            return comp != null ? cost - comp : cost;
          });
        }
      }
      const weekStartDay = pacificYmd(weekStart);
      const weekEndDay = pacificYmd(new Date(publishedEnd.getTime() - 1));
      if (weekStartDay && weekEndDay) {
        weekRange = `${weekStartDay} → ${weekEndDay}`;
      }
      const weekStartSec = Math.floor(weekStart.getTime() / 1000);
      sparkWeekKwh = (kwhSeries.xs || [])
        .map((t, i) => (t >= weekStartSec ? kwhSeries.values[i] : null))
        .filter((v) => v != null);
      sparkWeekCost = (costSeries.xs || [])
        .map((t, i) => (t >= weekStartSec ? costSeries.values[i] : null))
        .filter((v) => v != null);
      // Sum imported hourly intervals over the bill period [start, end).
      // Exclusive end matches PGE billingPeriodEndDate (midnight Pacific).
      if (cycleStart && cycleEnd) {
        const cycleStartDate = new Date(cycleStart);
        const cycleEndDate = new Date(cycleEnd);
        const statementEnd = Number.isFinite(cycleEndDate.getTime())
          ? clampToPublishedEnd(cycleEndDate)
          : null;
        if (
          Number.isFinite(cycleStartDate.getTime()) &&
          statementEnd &&
          statementEnd > cycleStartDate
        ) {
          const [kwhSum, costSum] = await Promise.all([
            sumStatisticChange(this._hass, this._account.statistic_ids.consumption, {
              start: cycleStartDate,
              end: statementEnd,
              period: "hour",
            }),
            sumStatisticChange(this._hass, this._account.statistic_ids.cost, {
              start: cycleStartDate,
              end: statementEnd,
              period: "hour",
            }),
          ]);
          usageCycleKwh = kwhSum.total;
          usageCycleCost = costSum.total;
        }
        // Usage after the closed statement through yesterday (exclusive published end).
        if (
          Number.isFinite(cycleEndDate.getTime()) &&
          publishedEnd > cycleEndDate
        ) {
          const [kwhSum, costSum] = await Promise.all([
            sumStatisticChange(this._hass, this._account.statistic_ids.consumption, {
              start: cycleEndDate,
              end: publishedEnd,
              period: "hour",
            }),
            sumStatisticChange(this._hass, this._account.statistic_ids.cost, {
              start: cycleEndDate,
              end: publishedEnd,
              period: "hour",
            }),
          ]);
          sinceStatementKwh = kwhSum.total;
          sinceStatementCost = costSum.total;
          const sinceStartDay = this._fmtDate(cycleEnd);
          const sinceEndDay = pacificYmd(new Date(publishedEnd.getTime() - 1));
          if (sinceStartDay && sinceEndDay) {
            sinceStatementRange = `${sinceStartDay} → ${sinceEndDay}`;
          }
        }
      }
    } catch (_err) {
      /* sparklines / usage cycle optional */
    }

    const kwhDelta =
      usageCycleKwh != null && cycleKwh != null
        ? usageCycleKwh - cycleKwh
        : null;
    const costDelta =
      usageCycleCost != null && cycleCost != null
        ? usageCycleCost - cycleCost
        : null;
    const fmtDelta = (delta, money = false) => {
      if (delta == null || Number.isNaN(delta)) return "vs statement —";
      const sign = delta > 0 ? "+" : "";
      return money
        ? `vs statement ${sign}${this._fmt(delta, "", true)}`
        : `vs statement ${sign}${this._fmt(delta, " kWh")}`;
    };

    const cycleProgress =
      cycleDay != null && cycleDays
        ? `Day ${this._fmt(cycleDay, "")} of ${this._fmt(cycleDays, "")}`
        : "Open billing cycle";
    // If either estNextMin or estNextMax is null, use an em dash ("—") as a placeholder; otherwise, format as min/max with no spaces and a '/'.
    const estRange =
      estNextMin != null && estNextMax != null
        ? `${this._fmt(estNextMin, "", true)}/${this._fmt(estNextMax, "", true)}`
        : "—";


    const spark = (vals, color) => sparklineSvg(vals || [], { stroke: color });
    const hasYesterdayExport = yesterdayReturn != null && yesterdayReturn > 0;
    // yesterday_compensation is disabled by default; fall back to the imported
    // `_compensation` statistic so export days still show the net interval amount.
    const yesterdayCompensationEffective =
      yesterdayCompensation != null ? yesterdayCompensation : yesterdayCompensationStat;
    const hasYesterdayCredit =
      hasYesterdayExport &&
      Number.isFinite(yesterdayCompensationEffective) &&
      yesterdayCompensationEffective > 0;
    const yesterdayNetAmount = hasYesterdayCredit
      ? (yesterdayCost || 0) - yesterdayCompensationEffective
      : null;
    const yesterdayMoneyLabel = hasYesterdayCredit
      ? "Yesterday net interval amount"
      : "Yesterday import cost";
    const yesterdayMoneyValue = hasYesterdayCredit
      ? formatSignedUsd(yesterdayNetAmount)
      : this._fmt(yesterdayCost, "", true);
    const yesterdayMoneyNote = hasYesterdayCredit
      ? yesterdayNetAmount < 0
        ? "Interval credit (estimate)"
        : "Interval charge (estimate)"
      : "";
    // Pair the money KPI with a matching trend: net interval amount uses the
    // compensation-adjusted series; import cost uses the raw import costs.
    const moneySpark = hasYesterdayCredit && sparkNetCost ? sparkNetCost : sparkCost;
    el.innerHTML = `
      <h2>At a glance</h2>
      <p class="muted" style="margin:0 0 12px">Yesterday and week use imported intervals through yesterday (Pacific week starts Sunday; no complete today). Statement = PGE billDetails. Usage cycle = imported hourly sum over that period. Since statement = usage after the statement end through yesterday. PGE estimate = PGE's own open-cycle projection, which does not reconcile with the interval sums. Interval net amount is an estimate and does not model PGE monthly/TOD credit buckets or annual true-up.</p>
      <div class="kpi-row">
        <div class="kpi"><div class="label">Yesterday import</div><div class="value">${this._fmt(yesterdayKwh, " kWh")}</div>${spark(sparkKwh, "var(--pge-series-kwh)")}</div>
        ${
          hasYesterdayExport
            ? `<div class="kpi"><div class="label">Yesterday export</div><div class="value">${this._fmt(yesterdayReturn, " kWh")}</div></div>`
            : ""
        }
        <div class="kpi"><div class="label">${yesterdayMoneyLabel}</div><div class="value">${yesterdayMoneyValue}</div>${
          yesterdayMoneyNote
            ? `<div class="delta">${this._escape(yesterdayMoneyNote)}</div>`
            : ""
        }${spark(moneySpark, "var(--pge-series-cost)")}</div>
        <div class="kpi"><div class="label">Week import</div><div class="value">${this._fmt(weekKwh, " kWh")}</div><div class="delta">${this._escape(weekRange)}</div>${spark(sparkWeekKwh, "var(--pge-series-kwh)")}</div>
        <div class="kpi"><div class="label">Week import cost</div><div class="value">${this._fmt(weekCost, "", true)}</div><div class="delta">${this._escape(weekRange)}</div>${spark(sparkWeekCost, "var(--pge-series-cost)")}</div>
        <div class="kpi kpi-statement"><div class="label">Statement cycle cost</div><div class="value">${this._fmt(cycleCost, "", true)}</div><div class="delta">${this._escape(cycleRange)}</div></div>
        <div class="kpi kpi-statement"><div class="label">Statement cycle kWh</div><div class="value">${this._fmt(cycleKwh, " kWh")}</div><div class="delta">${this._escape(cycleRange)}</div></div>
        <div class="kpi kpi-usage"><div class="label">Usage cycle import cost</div><div class="value">${this._fmt(usageCycleCost, "", true)}</div><div class="delta">${this._escape(fmtDelta(costDelta, true))}</div></div>
        <div class="kpi kpi-usage"><div class="label">Usage cycle import kWh</div><div class="value">${this._fmt(usageCycleKwh, " kWh")}</div><div class="delta">${this._escape(fmtDelta(kwhDelta, false))}</div></div>
        <div class="kpi kpi-usage"><div class="label">Since statement import cost</div><div class="value">${this._fmt(sinceStatementCost, "", true)}</div><div class="delta">${this._escape(sinceStatementRange)}</div></div>
        <div class="kpi kpi-usage"><div class="label">Since statement import kWh</div><div class="value">${this._fmt(sinceStatementKwh, " kWh")}</div><div class="delta">${this._escape(sinceStatementRange)}</div></div>
        <div class="kpi kpi-estimate"><div class="label">PGE est. charges so far</div><div class="value">${this._fmt(estCharges, "", true)}</div><div class="delta">${this._escape(cycleProgress)}</div></div>
        <div class="kpi kpi-estimate kpi-dual"><div class="label">PGE est. next bill</div><div class="value">${this._escape(estRange)}</div><div class="delta">${this._escape(cycleProgress)}</div></div>
        <div class="kpi status-${dueStatus}"><div class="label">Amount due</div><div class="value">${this._fmt(amountDue, "", true)}</div><div class="delta">Due ${this._escape(this._fmtDate(dueDate) || "—")}</div></div>
        <div class="kpi"><div class="label">Last payment</div><div class="value">${this._fmt(lastPayment, "", true)}</div><div class="delta">${this._escape(this._fmtDate(lastPaymentDate) || "—")}</div></div>
      </div>
    `;
    this._bindGlanceKpiClipboard(el);
  }

  /** Wire At a glance KPI tiles to copy label/value/delta on click or Enter/Space. */
  _bindGlanceKpiClipboard(root) {
    if (!root) return;
    root.querySelectorAll(".kpi").forEach((kpi) => {
      kpi.setAttribute("tabindex", "0");
      kpi.setAttribute("role", "button");
      const labelText = (kpi.querySelector(".label")?.textContent || "").trim();
      kpi.setAttribute(
        "aria-label",
        labelText ? `Copy ${labelText}` : "Copy KPI value"
      );
      kpi.title = "Click to copy";
      const copy = async () => {
        const text = formatKpiClipboardText({
          label: kpi.querySelector(".label")?.textContent,
          value: kpi.querySelector(".value")?.textContent,
          delta: kpi.querySelector(".delta")?.textContent,
        });
        if (!text) return;
        const ok = await this._copyText(text);
        if (!ok) return;
        kpi.classList.add("copied");
        kpi.title = "Copied!";
        window.setTimeout(() => {
          kpi.classList.remove("copied");
          kpi.title = "Click to copy";
        }, 1200);
      };
      kpi.addEventListener("click", () => {
        void copy();
      });
      kpi.addEventListener("keydown", (ev) => {
        if (ev.key !== "Enter" && ev.key !== " ") return;
        ev.preventDefault();
        void copy();
      });
    });
  }

  /** Best-effort clipboard write; falls back to a temporary textarea. */
  async _copyText(text) {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (_err) {
      /* fall through */
    }
    let ta;
    try {
      ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      return document.execCommand("copy");
    } catch (_err) {
      return false;
    } finally {
      ta?.remove();
    }
  }

  /** Drop chart wrappers whose canvas lives under any of the given hosts. */
  _disposeHostCharts(...hosts) {
    const roots = hosts.filter(Boolean);
    if (!roots.length) return;
    this._charts = (this._charts || []).filter((c) => {
      const el = c?.chart?.getDom?.();
      if (!el) return true;
      const hit = roots.some((h) => el === h || h.contains(el));
      if (!hit) return true;
      try {
        c.destroy?.();
      } catch (_e) {
        /* ignore */
      }
      return false;
    });
  }

  async _rebuildThemeCharts() {
    this._disposeHostCharts(
      this.shadowRoot.getElementById("chart-usage"),
      this.shadowRoot.getElementById("scatter"),
      this.shadowRoot.getElementById("cost-per-kwh"),
      this.shadowRoot.getElementById("billed-paid"),
      this.shadowRoot.getElementById("heatmap-kwh"),
      this.shadowRoot.getElementById("heatmap-temp"),
      this.shadowRoot.getElementById("ledger-bill"),
      this.shadowRoot.getElementById("ledger-kwh")
    );
    await this._renderHero();
    await this._renderInsights();
    await this._renderLedgerCharts();
  }

  async _renderHero() {
    const account = this._account;
    if (!account) return;
    const range = this._resolveChartRange();
    const period = this._period || range.period;
    const ids = account.statistic_ids;
    const colors = seriesColors(this);
    // High ceiling so range accounting is not LTTB-downsampled away.
    const maxPoints = 20000;

    const raw = await this._fetchUsageSeries(ids, range.start, range.end, period, maxPoints);
    // Chart view uses projectDirectionalUsage shape; accounting uses projectUsageSeries.
    const chartProjection = projectDirectionalUsage(raw);
    const accountingProjection = projectUsageSeries(raw);
    this._lastSeries = { ...raw, projection: accountingProjection, range, period };

    const usageHost = this.shadowRoot.getElementById("chart-usage");
    if (usageHost) {
      this._disposeHostCharts(usageHost);
      const chart = await createUsageComboChart(usageHost, {
        kwh: { xs: raw.kwh?.xs || [], ys: raw.kwh?.values || [] },
        returned: { xs: raw.returned?.xs || [], ys: raw.returned?.values || [] },
        cost: { xs: raw.cost?.xs || [], ys: raw.cost?.values || [] },
        compensation: {
          xs: raw.compensation?.xs || [],
          ys: raw.compensation?.values || [],
        },
        temp: { xs: raw.temp?.xs || [], ys: raw.temp?.means || [] },
        colors,
        projection: chartProjection,
      });
      if (chart) this._charts.push(chart);
    }
    void this._renderUsageStats();
  }

  _fmtWhen(unixSec) {
    if (unixSec == null) return "—";
    const d = new Date(unixSec * 1000);
    if (!Number.isFinite(d.getTime())) return "—";
    return new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }).format(d);
  }

  /**
   * Human labels for Range accounting rollup keys (Pacific wall-clock parts).
   * Keys stay machine-sortable (`YYYY-MM-DDTHH`, `YYYY-MM-DD`, `YYYY-MM`, `YYYY`).
   */
  _fmtRollupKey(key) {
    if (key == null || key === "") return "—";
    const s = String(key);
    const months = [
      "Jan",
      "Feb",
      "Mar",
      "Apr",
      "May",
      "Jun",
      "Jul",
      "Aug",
      "Sep",
      "Oct",
      "Nov",
      "Dec",
    ];
    const hour = s.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2})(?::\d{2})?$/);
    if (hour) {
      const mo = Number(hour[2]);
      const day = Number(hour[3]);
      const h = Number(hour[4]);
      if (mo >= 1 && mo <= 12 && day >= 1 && day <= 31 && h >= 0 && h <= 23) {
        const h12 = h % 12 || 12;
        const ampm = h < 12 ? "AM" : "PM";
        return `${months[mo - 1]} ${day}, ${h12}:00 ${ampm}`;
      }
    }
    const day = s.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (day) {
      const y = Number(day[1]);
      const mo = Number(day[2]);
      const d = Number(day[3]);
      if (mo >= 1 && mo <= 12 && d >= 1 && d <= 31) {
        return `${months[mo - 1]} ${d}, ${y}`;
      }
    }
    const month = s.match(/^(\d{4})-(\d{2})$/);
    if (month) {
      const y = Number(month[1]);
      const mo = Number(month[2]);
      if (mo >= 1 && mo <= 12) {
        return `${months[mo - 1]} ${y}`;
      }
    }
    return s;
  }

  async _fetchUsageSeries(ids, start, end, period, maxPoints) {
    const [kwh, returned, cost, compensation, temp] = await Promise.all([
      fetchStatisticSeries(this._hass, ids.consumption, { start, end, period, maxPoints }),
      ids.return
        ? fetchStatisticSeries(this._hass, ids.return, { start, end, period, maxPoints })
        : Promise.resolve({ xs: [], values: [] }),
      fetchStatisticSeries(this._hass, ids.cost, { start, end, period, maxPoints }),
      ids.compensation
        ? fetchStatisticSeries(this._hass, ids.compensation, { start, end, period, maxPoints })
        : Promise.resolve({ xs: [], values: [] }),
      fetchStatisticSeries(this._hass, ids.temperature, { start, end, period, maxPoints }),
    ]);
    return { kwh, returned, cost, compensation, temp };
  }

  /**
   * Drop empty rollup rows (missing data only). Retain true signed/net zeros when
   * samples, cost, or temperature prove the bucket exists.
   */
  _populatedRollupRows(rows) {
    return (rows || []).filter((r) => {
      if (r.samples > 0) return true;
      if (r.avgTemp != null && Number.isFinite(Number(r.avgTemp))) return true;
      if (r.cost != null && Number.isFinite(Number(r.cost)) && Number(r.cost) !== 0) return true;
      if (r.kwh != null && Number.isFinite(Number(r.kwh)) && Number(r.kwh) !== 0) return true;
      return false;
    });
  }

  /** localStorage map of Usage `<details data-persist>` open state. */
  _readDetailsOpenMap() {
    try {
      const raw = window.localStorage?.getItem("pge_energy.panel.details");
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (_err) {
      return {};
    }
  }

  _detailsIsOpen(key) {
    if (!key) return false;
    return !!this._readDetailsOpenMap()[key];
  }

  _detailsOpenAttr(key) {
    return this._detailsIsOpen(key) ? " open" : "";
  }

  _setDetailsOpen(key, open) {
    if (!key) return;
    try {
      const map = this._readDetailsOpenMap();
      map[key] = !!open;
      window.localStorage?.setItem("pge_energy.panel.details", JSON.stringify(map));
    } catch (_err) {
      /* private mode / quota */
    }
  }

  /** Restore + remember open/closed for panel `<details data-persist>` accordions. */
  _bindPersistentDetails(host) {
    if (!host) return;
    host.querySelectorAll("details[data-persist]").forEach((el) => {
      const key = el.dataset.persist;
      if (!key) return;
      el.addEventListener("toggle", () => {
        this._setDetailsOpen(key, el.open);
      });
    });
  }

  _rollupTable(title, caption, rows, keyLabel, persistKey, { signed = false, netAmount = false } = {}) {
    const populated = this._populatedRollupRows(rows);
    if (!populated.length) return "";
    const kwhHead = signed ? "Net kWh" : "Import kWh";
    const costHead = netAmount ? "Net interval amount" : "Import cost";
    const rateHead = netAmount ? "Net $/kWh (est.)" : "$/kWh";
    const cell = (raw, money = false, { allowZero = false } = {}) => {
      if (raw == null || Number.isNaN(Number(raw))) return "";
      const n = Number(raw);
      if (n === 0 && !allowZero) return "";
      if (money && (netAmount || n < 0)) return formatSignedUsd(n);
      return this._fmt(n, "", money);
    };
    const numAttr = (raw) =>
      raw == null || Number.isNaN(Number(raw)) ? "" : String(Number(raw));
    const body = populated
      .map((r) => {
        const kwh = cell(r.kwh, false, { allowZero: signed });
        const cost = cell(r.cost, true, { allowZero: netAmount });
        const rate = cell(r.rate, true);
        const temp = cell(r.avgTemp);
        const peak = cell(r.peakKwh, false, { allowZero: signed });
        return `<tr>
          <td data-sort="${this._escape(r.key)}">${this._escape(this._fmtRollupKey(r.key))}</td>
          <td data-sort="${numAttr(r.kwh)}">${kwh || "—"}</td>
          <td data-sort="${numAttr(r.cost)}">${cost || "—"}</td>
          <td data-sort="${numAttr(r.rate)}">${rate || "—"}</td>
          <td data-sort="${numAttr(r.avgTemp)}">${temp || "—"}</td>
          <td data-sort="${numAttr(r.samples)}">${r.samples || ""}</td>
          <td data-sort="${numAttr(r.peakKwh)}">${peak || "—"}</td>
        </tr>`;
      })
      .join("");
    const totK = populated.reduce((a, r) => a + (Number(r.kwh) || 0), 0);
    const totC = populated.reduce((a, r) => a + (Number(r.cost) || 0), 0);
    const totS = populated.reduce((a, r) => a + (r.samples || 0), 0);
    // Footer rate must match the row semantics: net-amount mode uses net flow,
    // while signed import-cost mode divides by gross import (net + return) so an
    // export-heavy range doesn't skew the $/kWh.
    const totG = populated.reduce((a, r) => {
      const g = Number(r.grossImport);
      return a + (Number.isFinite(g) ? g : 0);
    }, 0);
    const hasGross = populated.some((r) => Number.isFinite(Number(r.grossImport)));
    let rate;
    if (netAmount) {
      rate = Math.abs(totK) > RATE_EPSILON_KWH ? totC / totK : null;
    } else if (signed && hasGross) {
      rate = totG > RATE_EPSILON_KWH ? totC / totG : null;
    } else {
      rate = totK > RATE_EPSILON_KWH ? totC / totK : null;
    }
    const captionText = `${caption} Click a column header to sort.`;
    const persist = persistKey
      ? ` data-persist="${this._escape(persistKey)}"${this._detailsOpenAttr(persistKey)}`
      : "";
    return `
      <details class="usage-rollup"${persist}>
        <summary>
          <span class="rollup-title">${this._escape(title)} (${populated.length})</span>
          <span class="rollup-caption">${this._escape(captionText)}</span>
        </summary>
        <div class="usage-table-wrap">
          <table class="usage-day-table">
            <thead><tr>
              <th data-col="0" title="Sort by ${this._escape(keyLabel)}">${this._escape(keyLabel)}</th>
              <th data-col="1" title="Sort by ${this._escape(kwhHead)}">${this._escape(kwhHead)}</th>
              <th data-col="2" title="Sort by ${this._escape(costHead)}">${this._escape(costHead)}</th>
              <th data-col="3" title="Sort by ${this._escape(rateHead)}">${this._escape(rateHead)}</th>
              <th data-col="4" title="Sort by temperature">Avg °F</th>
              <th data-col="5" title="Sort by buckets">Buckets</th>
              <th data-col="6" title="Sort by peak">Peak bucket</th>
            </tr></thead>
            <tbody>${body}</tbody>
            <tfoot><tr>
              <td>Total</td>
              <td>${totK || (signed && populated.length) ? this._fmt(totK, "") : ""}</td>
              <td>${
                totC || (netAmount && populated.length)
                  ? netAmount || totC < 0
                    ? formatSignedUsd(totC)
                    : this._fmt(totC, "", true)
                  : ""
              }</td>
              <td>${
                rate != null && rate !== 0
                  ? netAmount || rate < 0
                    ? formatSignedUsd(rate)
                    : this._fmt(rate, "", true)
                  : ""
              }</td>
              <td></td>
              <td>${totS || ""}</td>
              <td></td>
            </tr></tfoot>
          </table>
        </div>
      </details>`;
  }

  _bindUsageTableSorting(host) {
    if (!host) return;
    host.querySelectorAll(".usage-day-table").forEach((table) => {
      const head = table.querySelector("thead");
      const body = table.querySelector("tbody");
      if (!head || !body) return;
      head.querySelectorAll("th[data-col]").forEach((th) => {
        th.addEventListener("click", () => {
          const col = Number(th.dataset.col);
          const prev = th.getAttribute("data-sort-dir");
          const dir = prev === "asc" ? "desc" : "asc";
          head.querySelectorAll("th").forEach((h) => h.removeAttribute("data-sort-dir"));
          th.setAttribute("data-sort-dir", dir);
          const rows = [...body.querySelectorAll("tr")];
          rows.sort((a, b) => {
            const av = a.children[col]?.getAttribute("data-sort") ?? "";
            const bv = b.children[col]?.getAttribute("data-sort") ?? "";
            const an = Number(av);
            const bn = Number(bv);
            let cmp;
            if (av !== "" && bv !== "" && Number.isFinite(an) && Number.isFinite(bn)) {
              cmp = an - bn;
            } else {
              cmp = String(av).localeCompare(String(bv), undefined, { numeric: true });
            }
            return dir === "asc" ? cmp : -cmp;
          });
          rows.forEach((r) => body.appendChild(r));
        });
      });
    });
  }

  async _renderUsageStats() {
    const host = this.shadowRoot.getElementById("usage-stats");
    const account = this._account;
    if (!host || !this._lastSeries || !account) return;
    const { range, period, projection: chartProjection } = this._lastSeries;
    if (!range?.start || !range?.end) {
      host.innerHTML = "";
      return;
    }

    const spanDays =
      Math.max(0, range.end.getTime() - range.start.getTime()) / (24 * 60 * 60 * 1000);
    const plan = accountingPlan(spanDays, period);
    host.innerHTML = `
      <details class="usage-accounting" data-persist="range_accounting"${this._detailsOpenAttr(
        "range_accounting"
      )}>
        <summary>
          <span class="rollup-title">Range accounting</span>
          <span class="rollup-caption">Loading multi-scale totals…</span>
        </summary>
      </details>`;
    this._bindPersistentDetails(host);

    const ids = account.statistic_ids;
    const maxPoints = 25000;
    const chart =
      chartProjection ||
      projectUsageSeries({
        kwh: this._lastSeries.kwh,
        returned: this._lastSeries.returned,
        cost: this._lastSeries.cost,
        compensation: this._lastSeries.compensation,
        temp: this._lastSeries.temp,
      });
    let hourly = period === "hour" ? chart : null;
    let daily = period === "day" ? chart : null;
    let monthly = period === "month" ? chart : null;

    try {
      const jobs = [];
      if (plan.needHour && !hourly) {
        jobs.push(
          this._fetchUsageSeries(ids, range.start, range.end, "hour", maxPoints).then((t) => {
            hourly = projectUsageSeries(t);
          })
        );
      }
      if (plan.needDay && !daily) {
        jobs.push(
          this._fetchUsageSeries(ids, range.start, range.end, "day", maxPoints).then((t) => {
            daily = projectUsageSeries(t);
          })
        );
      }
      if (plan.needMonth && !monthly) {
        jobs.push(
          this._fetchUsageSeries(ids, range.start, range.end, "month", maxPoints).then((t) => {
            monthly = projectUsageSeries(t);
          })
        );
      }
      await Promise.all(jobs);
    } catch (_err) {
      /* fall back to chart series only */
    }

    const acct = computeUsageAccounting(chart, {
      start: range.start,
      end: range.end,
      period,
      hourly,
      daily,
      monthly,
    });
    if (!acct.kwh.count && !acct.cost.count && !acct.days.length && !acct.months.length) {
      host.innerHTML = `
        <details class="usage-accounting" data-persist="range_accounting"${this._detailsOpenAttr(
          "range_accounting"
        )}>
          <summary>
            <span class="rollup-title">Range accounting</span>
            <span class="rollup-caption">No samples in this range yet.</span>
          </summary>
        </details>`;
      this._bindPersistentDetails(host);
      return;
    }

    const signed = acct.flowMode === "signed";
    const netAmount = acct.amountMode === "net";
    const kwhLabel = signed ? "Net kWh" : "Import kWh";
    const amountLabel = netAmount ? "Net interval amount" : "Import cost";
    const spanLabel = formatRangeLabel(range.start, range.end);
    const periodLabel = period === "month" ? "month" : period === "day" ? "day" : "hour";
    const scaleNote =
      acct.plan.scale === "years"
        ? "year/month rollups"
        : acct.plan.scale === "months"
          ? "month/day rollups"
          : acct.plan.scale === "days"
            ? "day + hour detail"
            : "hour detail";
    const yearsPop = this._populatedRollupRows(acct.years);
    const monthsPop = this._populatedRollupRows(acct.months);
    const daysPop = this._populatedRollupRows(acct.days);
    const hoursPop = this._populatedRollupRows(acct.hours);
    const coverBits = [];
    if (acct.plan.showYears && yearsPop.length) coverBits.push(`${yearsPop.length} years`);
    if (acct.plan.showMonths && monthsPop.length) coverBits.push(`${monthsPop.length} months`);
    if (acct.plan.showDays && daysPop.length) coverBits.push(`${daysPop.length} days`);
    if (acct.plan.showHours && hoursPop.length) coverBits.push(`${hoursPop.length} hours`);
    else if (acct.hour?.count) coverBits.push(`${acct.hour.count} hour samples`);
    const modeNote = signed
      ? " · signed grid flow + interval estimate"
      : " · import series";
    const meta = `${spanLabel} · chart ${periodLabel} · ${scaleNote}${
      coverBits.length ? ` · ${coverBits.join(" · ")}` : ""
    } · span ${acct.spanDays.toFixed(1)} days${modeNote}`;

    const bucketLabel = periodLabel;
    /** @type {{section?: string, label?: string, value?: string, note?: string}[]} */
    const metrics = [];
    const addSection = (name) => metrics.push({ section: name });
    const addMetric = (label, raw, note = "", { money = false, suffix = "", allowZero = false } = {}) => {
      if (raw == null || Number.isNaN(Number(raw))) return;
      const n = Number(raw);
      if (n === 0 && !allowZero) return;
      const value = money
        ? netAmount || n < 0
          ? formatSignedUsd(n)
          : this._fmt(n, "", true)
        : this._fmt(n, suffix);
      if (!value || value === "—") return;
      metrics.push({ label, value, note: note || "" });
    };

    addSection("Totals & averages");
    addMetric(
      signed ? "Total net kWh" : "Total import kWh",
      acct.totalKwh,
      signed ? "consumption − return" : "imported series",
      { suffix: " kWh", allowZero: signed }
    );
    addMetric(amountLabel, acct.totalCost, netAmount ? "cost − compensation (estimate)" : "", {
      money: true,
      allowZero: netAmount,
    });
    addMetric(
      netAmount ? "Net amount / net kWh (estimate)" : "Avg import $/kWh",
      acct.avgRate,
      "not the TOD tariff",
      { money: true }
    );
    addMetric(
      signed ? "Avg net kWh / hour" : "Avg import kWh / hour",
      acct.avgKwhPerHour,
      "÷ span hours",
      { suffix: " kWh" }
    );
    addMetric(
      signed ? "Avg net kWh / day" : "Avg import kWh / day",
      acct.avgKwhPerDay,
      "÷ span days",
      { suffix: " kWh" }
    );
    addMetric(
      netAmount ? "Avg net amount / hour" : "Avg import cost / hour",
      acct.avgCostPerHour,
      "",
      { money: true }
    );
    addMetric(
      netAmount ? "Avg net amount / day" : "Avg import cost / day",
      acct.avgCostPerDay,
      "",
      { money: true }
    );
    if (acct.spanMonths >= 1.5) {
      addMetric(
        signed ? "Avg net kWh / month" : "Avg import kWh / month",
        acct.avgKwhPerMonth,
        "÷ span months",
        { suffix: " kWh" }
      );
      addMetric(
        netAmount ? "Avg net amount / month" : "Avg import cost / month",
        acct.avgCostPerMonth,
        "",
        { money: true }
      );
    }
    if (acct.spanYears >= 0.9) {
      addMetric(
        signed ? "Avg net kWh / year" : "Avg import kWh / year",
        acct.avgKwhPerYear,
        "÷ span years",
        { suffix: " kWh" }
      );
      addMetric(
        netAmount ? "Avg net amount / year" : "Avg import cost / year",
        acct.avgCostPerYear,
        "",
        { money: true }
      );
    }

    addSection(`Distribution (${bucketLabel})`);
    addMetric("Avg temperature", acct.temp.mean, `${acct.temp.count} samples`, { suffix: " °F" });
    addMetric(`Median ${kwhLabel}`, acct.kwh.median, `per ${bucketLabel}`, { suffix: " kWh" });
    addMetric(`Median ${amountLabel}`, acct.cost.median, `per ${bucketLabel}`, { money: true });
    addMetric("Median temperature", acct.temp.median, "", { suffix: " °F" });
    addMetric(`${kwhLabel} stdev`, acct.kwh.stdev, `per ${bucketLabel}`, { suffix: " kWh" });
    addMetric(`${amountLabel} stdev`, acct.cost.stdev, `per ${bucketLabel}`, { money: true });
    addMetric("Temp stdev", acct.temp.stdev, `per ${bucketLabel}`, { suffix: " °F" });

    addSection("Extremes");
    if (signed) {
      addMetric("Peak export", acct.kwh.min != null && acct.kwh.min < 0 ? acct.kwh.min : null, this._fmtWhen(acct.kwh.lowAt), {
        suffix: " kWh",
      });
      addMetric("Peak import", acct.kwh.max != null && acct.kwh.max > 0 ? acct.kwh.max : null, this._fmtWhen(acct.kwh.peakAt), {
        suffix: " kWh",
      });
    } else {
      addMetric("Min import kWh", acct.kwh.min, this._fmtWhen(acct.kwh.lowAt), { suffix: " kWh" });
      addMetric("Max import kWh", acct.kwh.max, this._fmtWhen(acct.kwh.peakAt), { suffix: " kWh" });
    }
    addMetric(
      netAmount ? "Lowest net amount" : "Min import cost",
      acct.cost.min,
      this._fmtWhen(acct.cost.lowAt),
      { money: true }
    );
    addMetric(
      netAmount ? "Highest net amount" : "Max import cost",
      acct.cost.max,
      this._fmtWhen(acct.cost.peakAt),
      { money: true }
    );
    addMetric("Min temperature", acct.temp.min, this._fmtWhen(acct.temp.lowAt), { suffix: " °F" });
    addMetric("Max temperature", acct.temp.max, this._fmtWhen(acct.temp.peakAt), { suffix: " °F" });
    if (acct.hour?.count) {
      addMetric(
        signed ? "Peak hour import" : "Peak hour kWh",
        signed
          ? acct.hour.max != null && acct.hour.max > 0
            ? acct.hour.max
            : null
          : acct.hour.max,
        this._fmtWhen(acct.hour.peakAt),
        { suffix: " kWh" }
      );
      addMetric(
        signed ? "Peak hour export / quiet" : "Quiet hour kWh",
        signed
          ? acct.hour.min != null && acct.hour.min < 0
            ? acct.hour.min
            : null
          : acct.hour.min,
        this._fmtWhen(acct.hour.lowAt),
        { suffix: " kWh" }
      );
      addMetric("Median hour flow", acct.hour.median, `${acct.hour.count} hours`, { suffix: " kWh" });
    }
    if (acct.bestDay?.kwh) {
      addMetric(
        signed ? "Highest net day" : "Highest day",
        acct.bestDay.kwh,
        this._fmtRollupKey(acct.bestDay.key),
        { suffix: " kWh" }
      );
    }
    if (acct.worstDay?.kwh != null) {
      addMetric(
        signed ? "Lowest net day" : "Lowest day",
        acct.worstDay.kwh,
        this._fmtRollupKey(acct.worstDay.key),
        { suffix: " kWh", allowZero: signed }
      );
    }
    if (acct.plan.showMonths && acct.bestMonth?.kwh) {
      addMetric(
        signed ? "Highest net month" : "Highest month",
        acct.bestMonth.kwh,
        this._fmtRollupKey(acct.bestMonth.key),
        { suffix: " kWh" }
      );
    }
    if (acct.plan.showMonths && acct.worstMonth?.kwh != null) {
      addMetric(
        signed ? "Lowest net month" : "Lowest month",
        acct.worstMonth.kwh,
        this._fmtRollupKey(acct.worstMonth.key),
        { suffix: " kWh", allowZero: signed }
      );
    }
    if (acct.plan.showYears && acct.bestYear?.kwh) {
      addMetric(
        signed ? "Highest net year" : "Highest year",
        acct.bestYear.kwh,
        this._fmtRollupKey(acct.bestYear.key),
        { suffix: " kWh" }
      );
    }
    if (acct.plan.showYears && acct.worstYear?.kwh != null) {
      addMetric(
        signed ? "Lowest net year" : "Lowest year",
        acct.worstYear.kwh,
        this._fmtRollupKey(acct.worstYear.key),
        { suffix: " kWh", allowZero: signed }
      );
    }

    const summaryHtml = this._renderSummaryPairs(metrics);
    const tableCaption = signed
      ? "Signed grid flow (import − export) and interval amount estimate — not PGE statement credit buckets."
      : "Imported usage in range.";
    const tables = [];
    if (acct.plan.showYears) {
      tables.push(
        this._rollupTable(
          "Yearly breakdown",
          `Pacific calendar years. ${tableCaption}`,
          yearsPop,
          "Year",
          "rollup_yearly",
          { signed, netAmount }
        )
      );
    }
    if (acct.plan.showMonths) {
      tables.push(
        this._rollupTable(
          "Monthly breakdown",
          `Pacific calendar months. ${tableCaption}`,
          monthsPop,
          "Month",
          "rollup_monthly",
          { signed, netAmount }
        )
      );
    }
    if (acct.plan.showDays) {
      tables.push(
        this._rollupTable(
          "Daily breakdown",
          `Pacific calendar days. ${tableCaption}`,
          daysPop,
          "Date",
          "rollup_daily",
          { signed, netAmount }
        )
      );
    }
    if (acct.plan.showHours) {
      tables.push(
        this._rollupTable(
          "Hourly breakdown",
          `Pacific hours (short windows). ${tableCaption}`,
          hoursPop,
          "Hour",
          "rollup_hourly",
          { signed, netAmount }
        )
      );
    } else if (acct.hour?.count) {
      tables.push(
        `<p class="muted stats-meta">Hour-level peaks are in the summary (${acct.hour.count} hours). Use a shorter range for a full hourly table.</p>`
      );
    }

    host.innerHTML = `
      <details class="usage-accounting" data-persist="range_accounting"${this._detailsOpenAttr(
        "range_accounting"
      )}>
        <summary>
          <span class="rollup-title">Range accounting</span>
          <span class="rollup-caption">${this._escape(meta)}</span>
        </summary>
        <div class="usage-accounting-body">
          ${summaryHtml}
        </div>
      </details>
      ${tables.filter(Boolean).join("")}
    `;
    this._bindPersistentDetails(host);
    this._bindUsageTableSorting(host);
  }

  /**
   * Compact metric grid: two columns on tablet/desktop, one on phone.
   * @param {{section?: string, label?: string, value?: string, note?: string}[]} metrics
   */
  _renderSummaryPairs(metrics) {
    const blocks = [];
    let current = [];
    const flush = (section) => {
      if (!current.length) return;
      const items = current
        .map(
          (m) => `<div class="usage-summary-item">
          <span class="metric">${this._escape(m.label)}</span>
          <span class="value">${m.value}</span>
          ${m.note ? `<span class="note">${this._escape(m.note)}</span>` : ""}
        </div>`
        )
        .join("");
      blocks.push(`
        <div class="usage-summary-section">
          <div class="usage-summary-section-title">${this._escape(section)}</div>
          <div class="usage-summary-items">${items}</div>
        </div>
      `);
      current = [];
    };
    let sectionName = "Summary";
    for (const m of metrics) {
      if (m.section) {
        flush(sectionName);
        sectionName = m.section;
        continue;
      }
      current.push(m);
    }
    flush(sectionName);
    if (!blocks.length) return "";
    return `<div class="usage-summary-wrap">${blocks.join("")}</div>`;
  }

  _monthKeyPacific(unixSec) {
    const d = new Date(unixSec * 1000);
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/Los_Angeles",
      year: "numeric",
      month: "2-digit",
    }).format(d); // YYYY-MM
  }

  /** Monthly $/kWh from daily series — skips incomplete/zero months. */
  _monthlyRateSeries(kwhDay, costDay) {
    const costMap = new Map((costDay?.xs || []).map((t, i) => [t, costDay.values[i]]));
    const buckets = new Map();
    for (let i = 0; i < (kwhDay?.xs || []).length; i++) {
      const t = kwhDay.xs[i];
      const k = kwhDay.values[i];
      const c = costMap.get(t);
      if (k == null || c == null || !(k > 0) || !(c > 0)) continue;
      const key = this._monthKeyPacific(t);
      const bucket = buckets.get(key) || { kwh: 0, cost: 0, start: t };
      bucket.kwh += Number(k);
      bucket.cost += Number(c);
      if (t < bucket.start) bucket.start = t;
      buckets.set(key, bucket);
    }
    const xs = [];
    const ys = [];
    for (const key of [...buckets.keys()].sort()) {
      const b = buckets.get(key);
      if (!b || b.kwh < 5) continue; // ignore stub months
      const rate = b.cost / b.kwh;
      if (!(rate >= 0.05) || !(rate <= 1.5)) continue; // drop nonsense ratios
      xs.push(b.start);
      ys.push(rate);
    }
    return { xs, ys };
  }

  async _renderInsights() {
    const account = this._account;
    if (!account) return;
    this._disposeHostCharts(
      this.shadowRoot.getElementById("scatter"),
      this.shadowRoot.getElementById("cost-per-kwh"),
      this.shadowRoot.getElementById("billed-paid"),
      this.shadowRoot.getElementById("heatmap-kwh"),
      this.shadowRoot.getElementById("heatmap-temp")
    );
    const range = rangePresets()["12mo"];
    const ids = account.statistic_ids;
    const colors = seriesColors(this);
    const [kwhDay, tempDay, billAmt, payAmt, costDay] = await Promise.all([
      fetchStatisticSeries(this._hass, ids.consumption, {
        start: range.start,
        end: range.end,
        period: "day",
        maxPoints: 400,
      }),
      fetchStatisticSeries(this._hass, ids.temperature, {
        start: range.start,
        end: range.end,
        period: "day",
        maxPoints: 400,
      }),
      fetchStatisticSeries(this._hass, ids.bill_amount, {
        start: range.start,
        end: range.end,
        period: "month",
        maxPoints: 48,
      }),
      fetchStatisticSeries(this._hass, ids.payment_amount, {
        start: range.start,
        end: range.end,
        period: "month",
        maxPoints: 48,
      }),
      fetchStatisticSeries(this._hass, ids.cost, {
        start: range.start,
        end: range.end,
        period: "day",
        maxPoints: 400,
      }),
    ]);

    const scatterHost = this.shadowRoot.getElementById("scatter");
    if (scatterHost) {
      const tempMap = new Map((tempDay.xs || []).map((t, i) => [t, tempDay.means[i]]));
      const sx = [];
      const sy = [];
      const sDates = [];
      for (let i = 0; i < (kwhDay.xs || []).length; i++) {
        const dayStart = kwhDay.xs[i];
        const temp = tempMap.get(dayStart);
        const usage = kwhDay.values[i];
        if (temp != null && usage != null && usage > 0) {
          sx.push(temp);
          sy.push(usage);
          sDates.push(dayStart);
        }
      }
      const chart = await createScatter(scatterHost, {
        xs: sx,
        ys: sy,
        dates: sDates,
        color: colors.kwh,
      });
      if (chart) this._charts.push(chart);
    }

    const cpkHost = this.shadowRoot.getElementById("cost-per-kwh");
    if (cpkHost) {
      const { xs, ys } = this._monthlyRateSeries(kwhDay, costDay);
      const chart = await createLineChart(cpkHost, {
        xs,
        ys,
        labelY: "$/kWh",
        color: colors.cost,
        unit: "",
        monthly: true,
      });
      if (chart) this._charts.push(chart);
    }

    const bpHost = this.shadowRoot.getElementById("billed-paid");
    if (bpHost) {
      bpHost.replaceChildren();
      const chart = await createMonthCompareChart(bpHost, {
        billedXs: billAmt.xs,
        billedYs: billAmt.values,
        payXs: payAmt.xs,
        payYs: payAmt.values,
        colors,
      });
      if (chart) this._charts.push(chart);
    }

    const hmKwh = await renderHeatmap(this.shadowRoot.getElementById("heatmap-kwh"), {
      xs: kwhDay.xs,
      ys: kwhDay.values,
      title: "Daily kWh (imported history)",
    });
    const hmTemp = await renderHeatmap(this.shadowRoot.getElementById("heatmap-temp"), {
      xs: tempDay.xs,
      ys: tempDay.means,
      diverging: true,
      title: "Daily avg temperature (imported history)",
    });
    if (hmKwh) this._charts.push(hmKwh);
    if (hmTemp) this._charts.push(hmTemp);
  }

  _renderBillPdfHeader() {
    const pdf = this._account?.bill_pdf;
    if (!pdf?.url) return "";
    const status = pdf.parse_status || "not_downloaded";
    const badge = this._billPdfStatusLabel(status);
    const advisories = (pdf.advisories || []).map((a) => this._escape(String(a))).join(", ");
    const warnings = (pdf.warnings || []).map((w) => this._escape(String(w))).join(", ");
    return `
      <div class="bill-pdf-header" style="margin:0 0 12px;display:flex;flex-wrap:wrap;gap:8px;align-items:center">
        <a class="button" href="${this._escape(pdf.url)}" target="_blank" rel="noopener">View bill PDF</a>
        <span class="badge">${this._escape(badge)}</span>
        ${advisories ? `<span class="muted stats-meta">Advisories: ${advisories}</span>` : ""}
        ${warnings ? `<span class="muted stats-meta">Warnings: ${warnings}</span>` : ""}
      </div>
    `;
  }

  _billPdfStatusLabel(status) {
    const labels = {
      parsed: "Parsed",
      reconciliation_failed: "Reconciliation failed",
      parse_failed: "Not parsed",
      text_unavailable: "Not parsed",
      download_failed: "Download failed",
      not_found: "Not found",
      downloaded: "Downloaded",
      parser_stale: "Parser update pending",
      statistics_pending: "Statistics pending",
      not_downloaded: "PDF not downloaded",
    };
    return labels[status] || status;
  }

  _renderBillPdfStatementDetails() {
    const pdf = this._account?.bill_pdf;
    const metrics = pdf?.metrics;
    if (!metrics || !Object.keys(metrics).length) return "";
    const groups = [
      {
        title: "Account & payment",
        keys: ["amount_due", "payment_received", "balance_forward", "previous_amount_due"],
      },
      {
        title: "Energy & delivery",
        keys: [
          "total_kwh",
          "energy_delivery_charges",
          "basic_charge",
          "energy_use_charge",
          "transmission_charge",
          "distribution_charge",
          "power_cost_adjustment",
        ],
      },
      {
        title: "Programs & adjustments",
        keys: [
          "regulatory_adjustments",
          "state_pass_throughs",
          "program_charges",
          "green_future_charge",
        ],
      },
      {
        title: "Taxes",
        keys: ["taxes_and_investments", "local_tax", "public_purpose_charge"],
      },
    ];
    const rows = [];
    for (const group of groups) {
      const items = [];
      for (const key of group.keys) {
        const metric = metrics[key];
        if (!metric?.value) continue;
        const unit = metric.unit === "kWh" ? " kWh" : "";
        const money = metric.unit === "USD";
        const num = Number(metric.value);
        const value = money ? this._fmt(num, "", true) : this._fmt(num, unit);
        items.push({ label: metric.label || key, value });
      }
      if (!items.length) continue;
      rows.push({ section: group.title });
      for (const item of items) rows.push(item);
    }
    if (!rows.length) return "";
    return `
      <details class="usage-accounting" open>
        <summary>Statement details (PDF)</summary>
        <div class="usage-accounting-body">${this._renderSummaryPairs(rows)}</div>
      </details>
    `;
  }

  // -------------------------------------------------------------------------
  // Time of Day hub (#tod)
  // -------------------------------------------------------------------------

  _todCountdown(iso) {
    if (!iso) return "—";
    const t = Date.parse(iso);
    if (!Number.isFinite(t)) return "—";
    const diff = t - Date.now();
    if (diff <= 0) return "now";
    const mins = Math.round(diff / 60000);
    if (mins < 60) return `${mins}m`;
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    if (h < 24) return `${h}h ${m}m`;
    return `${Math.floor(h / 24)}d ${h % 24}h`;
  }

  _todWeekGrid() {
    const now = new Date();
    const days = todWeekDays(now);
    const nowParts = pacificParts(now);
    let html = '<div class="tod-grid">';
    html += '<div class="tod-grid-head tod-corner"></div>';
    for (let h = 0; h < 24; h++) {
      html += `<div class="tod-grid-head tod-hour">${h}</div>`;
    }
    for (const day of days) {
      html += `<div class="tod-grid-label">${this._escape(day.name)}</div>`;
      for (let h = 0; h < 24; h++) {
        const period = todPeriodForPacific(day.ymd, h);
        const isNow = day.ymd === nowParts.ymd && h === nowParts.hour;
        html += `<div class="tod-cell ${period}${isNow ? " now" : ""}" title="${this._escape(
          day.name
        )} ${String(h).padStart(2, "0")}:00 Pacific — ${TOD_PERIOD_LABELS[period]}"></div>`;
      }
    }
    html += "</div>";
    return html;
  }

  _todHolidayNote() {
    const year = Number(pacificYmd().slice(0, 4));
    const holidays = [...todHolidays(year)].sort();
    const fmt = new Intl.DateTimeFormat("en-US", {
      timeZone: "UTC",
      month: "short",
      day: "numeric",
    });
    const labels = holidays.map((ymd) => {
      const [y, m, d] = ymd.split("-").map(Number);
      return fmt.format(new Date(Date.UTC(y, m - 1, d)));
    });
    return `
      <details class="tod-holidays" data-persist="tod_holidays"${this._detailsOpenAttr("tod_holidays")}>
        <summary>Off-peak days & holidays ${year}</summary>
        <div class="tod-holidays-body">
          <p class="muted">Off-peak all day on Saturdays, Sundays, and observed holidays. Weekday windows (Pacific): off-peak 12am–7am and 9pm–12am, mid-peak 7am–5pm, on-peak 5pm–9pm.</p>
          <p>${labels.join(" · ")}</p>
        </div>
      </details>
    `;
  }

  /** Hourly analysis window for by-period totals — capped so huge custom ranges stay light. */
  _todExactCapMs() {
    return 60 * 24 * 60 * 60 * 1000; // 60 days of hourly = 1440 pts, no downsampling.
  }

  _clampTodExactWindow(start, end) {
    const capMs = this._todExactCapMs();
    const span = end.getTime() - start.getTime();
    if (span <= capMs) return { start, end, capped: false };
    return { start: new Date(end.getTime() - capMs), end, capped: true };
  }

  _todPresetFitsExactWindow(key) {
    const range = this._basePresetRange(key);
    if (
      (key === "cycle" || key === "last_cycle") &&
      !this._billBounds()
    ) {
      return false;
    }
    return range.end.getTime() - range.start.getTime() <= this._todExactCapMs();
  }

  _todAvailablePresets() {
    const available = new Set(this._availablePresets || RANGE_PRESET_PRIMARY);
    if (this._billBounds()) {
      available.add("cycle");
      available.add("last_cycle");
    } else {
      available.delete("cycle");
      available.delete("last_cycle");
    }
    for (const key of [...available]) {
      if (!this._todPresetFitsExactWindow(key)) available.delete(key);
    }
    return available;
  }

  _todAnalysisWindow(range) {
    // Custom ranges are clamped in `_resolveTodRange` so controls match analysis.
    const clamped = this._clampTodExactWindow(range.start, range.end);
    return {
      ...range,
      start: clamped.start,
      end: clamped.end,
      capped: !!(range.capped || clamped.capped),
    };
  }

  async _todUsageByPeriod() {
    const ids = this._account.statistic_ids;
    const range = this._resolveTodRange();
    const window = this._todAnalysisWindow(range);
    const [kwhSeries, costSeries] = await Promise.all([
      fetchStatisticSeries(this._hass, ids.consumption, {
        start: window.start,
        end: window.end,
        period: "hour",
        maxPoints: 2000,
      }),
      fetchStatisticSeries(this._hass, ids.cost, {
        start: window.start,
        end: window.end,
        period: "hour",
        maxPoints: 2000,
      }),
    ]);
    return {
      kwh: bucketTodByPeriod(kwhSeries),
      cost: bucketTodByPeriod(costSeries),
      kwhSeries,
      costSeries,
      hasCost: seriesCostCoverageComplete(kwhSeries, costSeries),
      window,
    };
  }

  _todRangeControlsHtml() {
    this._ensureTodRangeKey();
    const available = this._todAvailablePresets();
    const range = this._resolveTodRange();
    const customActive = !!this._todCustomRange;
    const moreActive = !customActive && RANGE_PRESET_MORE.includes(this._todRangeKey);
    const presetLabel = customActive
      ? "Custom"
      : RANGE_PRESET_LABELS[this._todRangeKey] || this._todRangeKey;
    const label = `${presetLabel} · ${formatRangeLabel(range.start, range.end)}`;
    const primaryButtons = RANGE_PRESET_PRIMARY.map((k) => {
      const enabled = available.has(k);
      const active = !customActive && this._todRangeKey === k;
      const text = RANGE_PRESET_LABELS[k] || k;
      return `<button type="button" data-tod-range="${k}" class="${active ? "active" : ""}" ${
        enabled ? "" : "disabled"
      } aria-pressed="${active ? "true" : "false"}" title="${this._escape(text)}">${this._escape(text)}</button>`;
    }).join("");
    const moreOptions = RANGE_PRESET_MORE.map((k) => {
      const enabled = available.has(k);
      const text = RANGE_PRESET_LABELS[k] || k;
      return `<option value="${k}" ${moreActive && this._todRangeKey === k ? "selected" : ""} ${
        enabled ? "" : "disabled"
      }>${this._escape(text)}</option>`;
    }).join("");
    const endInclusive = new Date(Math.max(range.start.getTime(), range.end.getTime() - 1));
    return `
      <div class="filters tod-range" aria-label="TOD estimate range">
        <p class="muted tod-range-caption">Window for the local savings / cost estimate — independent of Usage. Custom ranges longer than 60 days are clipped to the newest 60 days so hourly totals stay exact.</p>
        ${primaryButtons}
        <select id="tod-range-more" class="range-more ${moreActive ? "active" : ""}" aria-label="More TOD ranges">
          <option value="" ${moreActive ? "" : "selected"}>More…</option>
          ${moreOptions}
        </select>
        <span class="range-label">${this._escape(label)}</span>
        <div class="range-custom">
          <input type="datetime-local" id="tod-range-start" aria-label="TOD range start" value="${this._escape(
            this._toLocalInputValue(range.start)
          )}" />
          <input type="datetime-local" id="tod-range-end" aria-label="TOD range end" value="${this._escape(
            this._toLocalInputValue(endInclusive)
          )}" />
          <button type="button" class="secondary" id="tod-range-apply">Apply</button>
        </div>
      </div>
    `;
  }

  _bindTodRange(host) {
    if (!host) return;
    host.querySelectorAll("[data-tod-range]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        this._selectTodRangeKey(btn.dataset.todRange);
        await this._renderTod();
      });
    });
    const more = host.querySelector("#tod-range-more");
    if (more) {
      more.addEventListener("change", async (ev) => {
        const key = ev.target.value;
        if (!key) return;
        this._selectTodRangeKey(key);
        await this._renderTod();
      });
    }
    const apply = host.querySelector("#tod-range-apply");
    if (apply) {
      apply.addEventListener("click", async () => {
        const startRaw = host.querySelector("#tod-range-start")?.value;
        const endRaw = host.querySelector("#tod-range-end")?.value;
        const start = startRaw ? new Date(startRaw) : null;
        let end = endRaw ? new Date(endRaw) : null;
        if (!start || !end || !Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime())) {
          return;
        }
        end = new Date(end.getTime() + 60 * 1000);
        end = clampToPublishedEnd(end);
        if (end <= start) return;
        const clamped = this._clampTodExactWindow(start, end);
        this._todCustomRange = { start: clamped.start, end: clamped.end };
        this._todRangeTouched = true;
        await this._renderTod();
      });
    }
  }

  _todShareBar(totals) {
    const sum = TOD_PERIODS.reduce((acc, p) => acc + (totals[p] || 0), 0);
    if (!sum || sum <= 0) return "";
    return `<div class="tod-share-bar" aria-label="Share of kWh by period">
      ${TOD_PERIODS.map((p) => {
        const share = ((totals[p] || 0) / sum) * 100;
        if (share <= 0) return "";
        return `<div class="tod-share-seg ${p}" style="width:${share.toFixed(2)}%" title="${TOD_PERIOD_LABELS[p]}: ${share.toFixed(0)}%"></div>`;
      }).join("")}
    </div>`;
  }

  async _renderTod() {
    const el = this.shadowRoot.getElementById("tod");
    if (!el) return;
    const gen = ++this._todRenderGen;
    try {
      await this._renderTodBody(el, gen);
    } catch (err) {
      if (gen !== this._todRenderGen) return;
      el.innerHTML = `<h2>Time of Day</h2><p class="error">Failed to render Time of Day: ${this._escape(
        String(err?.message || err)
      )}</p>`;
    }
  }

  async _renderTodBody(el, gen) {
    const account = this._account;
    if (!account || !account.tod) {
      if (gen !== this._todRenderGen) return;
      el.innerHTML = `<h2>Time of Day</h2><p class="muted">TOD data not available yet — wait for a sync.</p>`;
      return;
    }
    const tod = account.tod;
    const e = account.entity_ids;
    const enrolled = tod.enrolled ?? null;
    const period = tod.period || "off_peak";
    const rateUsd = Number(tod.rates?.[period]);
    const rateCents = Number.isFinite(rateUsd) ? rateUsd * 100 : null;
    const sourceLabels = {
      override: "manual override",
      portal: "PGE",
      default: "offline defaults",
    };
    const sourceLabel = sourceLabels[tod.rate_source] || tod.rate_source || "—";
    const fetched = tod.portal_fetched_at
      ? ` · updated ${this._fmtDate(tod.portal_fetched_at)}`
      : "";
    const nextAt = tod.next_transition_at;
    let nextLabel = "—";
    if (nextAt) {
      const parts = pacificParts(new Date(nextAt));
      const nextPeriod = todPeriodForPacific(parts.ymd, parts.hour);
      nextLabel = `${this._todCountdown(nextAt)} → ${TOD_PERIOD_LABELS[nextPeriod] || nextPeriod}`;
    }
    const dayNote = tod.is_holiday
      ? "Holiday — off-peak all day"
      : tod.is_weekend
        ? "Weekend — off-peak all day"
        : "Weekday schedule";
    const sourceHint = `Rates: ${sourceLabel}${fetched}`;
    this._ensureTodRangeKey();

    // Catalog data from the domain tariff updater (effective-dated).
    const catalogs = tod.catalogs || {};
    const todCatalog = catalogs.tod || [];
    const basicCatalog = catalogs.basic || [];
    const tariffStatus = tod.tariff_status || {};
    const hasCatalog = todCatalog.length > 0 && basicCatalog.length > 0;

    let usageHtml = "";
    let savingsHtml = "";
    let windowNote = "";
    try {
      const { kwh, cost, kwhSeries, costSeries, hasCost, window } = await this._todUsageByPeriod();
      if (gen !== this._todRenderGen) return;
      const totalKwh = kwh.off_peak + kwh.mid_peak + kwh.on_peak;
      const importedCost = cost.off_peak + cost.mid_peak + cost.on_peak;

      windowNote = window.capped
        ? `Newest 60 days of ${this._escape(formatRangeLabel(window.start, window.end))} — long ranges stay capped so hourly totals stay exact.`
        : `Imported hourly intervals, ${this._escape(formatRangeLabel(window.start, window.end))}.`;

      if (totalKwh > 0) {
        // Usage-by-period table (unchanged).
        const rows = TOD_PERIODS.map((p) => {
          const kw = kwh[p] || 0;
          const c = cost[p] || 0;
          const share = (kw / totalKwh) * 100;
          return `<tr>
            <td>${TOD_PERIOD_LABELS[p]}</td>
            <td class="num">${this._fmt(kw, " kWh")}</td>
            <td class="num">${this._fmt(c, "", true)}</td>
            <td class="num">${this._fmt(share, "%")}</td>
            <td class="num">${Number.isFinite(kw) && kw > 0 ? this._fmt((c / kw) * 100, " ¢/kWh") : "—"}</td>
          </tr>`;
        }).join("");
        usageHtml = `
          <h3>Usage by period</h3>
          <p class="muted" style="margin:0 0 8px">${windowNote}</p>
          ${this._todShareBar(kwh)}
          <table class="tod-table">
            <thead><tr><th>Period</th><th class="num">Energy</th><th class="num">Cost</th><th class="num">Share</th><th class="num">Avg billed</th></tr></thead>
            <tbody>${rows}</tbody>
            <tfoot><tr><td>Total</td><td class="num">${this._fmt(totalKwh, " kWh")}</td><td class="num">${this._fmt(importedCost, "", true)}</td><td class="num">100%</td><td class="num">—</td></tr></tfoot>
          </table>
          <p class="muted" style="margin:8px 0 0">Cost and avg billed are imported hourly amounts; share uses energy.</p>
        `;

        // Dual-source plan comparison using effective-dated catalogs.
        if (hasCatalog) {
          const overrideRates = tod.override_rates || null;
          const estimate = estimatePlanCostSeries({
            hourlyKwh: kwhSeries,
            todCatalog,
            basicCatalog,
            overrideRates,
            start: window.start,
            end: window.end,
          });
          if (gen !== this._todRenderGen) return;

          if (estimate.coverage.complete) {
            const localTodTotal = estimate.todValues.reduce((s, v) => s + (v ?? 0), 0);
            const localBasicTotal = estimate.basicValues.reduce((s, v) => s + (v ?? 0), 0);
            const localSavings = localBasicTotal - localTodTotal;

            const reconciled = reconcilePlanComparison({
              local: {
                todTotal: localTodTotal,
                basicTotal: localBasicTotal,
                savings: localSavings,
                start: window.start,
                end: window.end,
                complete: true,
              },
              rateCompare: tod.rate_compare || null,
              selectedRange: { start: window.start, end: window.end },
            });

            if (gen !== this._todRenderGen) return;

            // Flat-rate detection (diagnostic only).
            let flatRateDiag = null;
            try {
              flatRateDiag = detectFlatPortalRates({
                hourlyKwh: kwhSeries,
                hourlyCost: costSeries,
                todCatalog,
              });
            } catch (_) {
              /* ignore */
            }

            savingsHtml = this._todCompareHtmlDual({
              enrolled,
              localTodTotal,
              localBasicTotal,
              localSavings,
              reconciled,
              flatRateDiag,
              tod,
              sourceLabel,
              windowLabel: formatRangeLabel(window.start, window.end),
              todCatalog,
              basicCatalog,
              tariffStatus,
              overrideRates: tod.override_rates || null,
              overrideScope: tod.override_scope || null,
              basicComparisonRate: tod.basic_comparison_rate,
              basicComparisonSource: tod.basic_comparison_source,
              basicComparisonEffectiveFrom: tod.basic_comparison_effective_from,
              basicComparisonComponentBasis: tod.basic_comparison_component_basis,
              basicComparisonExclusions: tod.basic_comparison_exclusions,
            });
          } else {
            savingsHtml = this._todCompareHtmlCoverage(estimate.coverage, hasCost);
          }
        } else if (hasCost) {
          // Fallback: no catalogs, fall back to legacy computeTodPlanCompare.
          const compare = computeTodPlanCompare({
            kwh,
            cost,
            rates: tod.rates || {},
            basicRate: tod.basic_rate,
            enrolled,
            hasCost,
          });
          savingsHtml = compare
            ? this._todCompareHtml(compare, tod, sourceLabel, formatRangeLabel(window.start, window.end))
            : "";
        } else {
          savingsHtml = `<div class="tod-counterfactual"><p class="muted" style="margin:0">Local estimate unavailable — imported cost must cover every consumption hour in this window (enable Include cost / wait for a full cost sync).</p></div>`;
        }
      } else {
        usageHtml = `<p class="muted">No imported hourly usage in this window yet.</p>`;
      }
    } catch (_err) {
      if (gen !== this._todRenderGen) return;
      usageHtml = `<p class="muted">Usage-by-period unavailable for this range.</p>`;
    }

    if (gen !== this._todRenderGen) return;

    // PGE portal official savings override.
    if (tod.savings_total != null) {
      const rateCompare = tod.rate_compare || null;
      const officialPeriod =
        tod.savings_source === "rate_compare" && rateCompare && rateCompare.comparison_period
          ? ` for ${this._escape(rateCompare.comparison_period)}`
          : "";
      const savingsSourceLabels = {
        pricing_plan: "PGE pricing plan",
        rate_compare: "PGE rate comparison",
      };
      const savingsSourceLabel = savingsSourceLabels[tod.savings_source] || "PGE portal";
      savingsHtml = `
        <div class="tod-counterfactual official">
          <div class="label">PGE TOD vs Basic savings</div>
          <div class="value">${this._fmt(tod.savings_total, "", true)}</div>
          <div class="delta">Official total from PGE portal${officialPeriod} (${this._escape(savingsSourceLabel)}).</div>
        </div>
        ${savingsHtml}
      `;
    }

    el.innerHTML = `
      <h2>Time of Day</h2>
      <div class="tod-header">
        <span class="badge ${
          enrolled === true ? "on" : enrolled === false ? "off" : ""
        }">${
          enrolled === true
            ? "Enrolled in Time of Day"
            : enrolled === false
              ? "Not enrolled in Time of Day"
              : "Time of Day enrollment unknown"
        }</span>
        <span class="muted tod-source">${this._escape(sourceHint)}</span>
      </div>
      <div class="kpi-row">
        <div class="kpi tod-${period}"><div class="label">Period now</div><div class="value">${TOD_PERIOD_LABELS[period]}</div><div class="delta">${this._escape(dayNote)}</div></div>
        <div class="kpi"><div class="label">Current rate</div><div class="value">${rateCents != null ? this._fmt(rateCents, " ¢/kWh") : "—"}</div><div class="delta">${this._escape(sourceLabel)}</div></div>
        <div class="kpi"><div class="label">Next transition</div><div class="value">${this._escape(this._todCountdown(nextAt))}</div><div class="delta">${this._escape(nextLabel)}</div></div>
      </div>
      <div class="tod-schedule">
        <h3>Week schedule (Pacific)</h3>
        <div class="tod-legend">
          ${TOD_PERIODS.map((p) => `<span class="legend ${p}"><i></i>${TOD_PERIOD_LABELS[p]}</span>`).join("")}
          <span class="muted" style="margin-left:auto">Highlighted column = now</span>
        </div>
        ${this._todWeekGrid()}
        ${this._todHolidayNote()}
      </div>
      <div class="usage-accounting tod-usage">
        ${this._todRangeControlsHtml()}
        ${usageHtml}
        ${savingsHtml}
      </div>
      ${this._tariffStatusHtml(tariffStatus, todCatalog, basicCatalog)}
    `;
    if (gen !== this._todRenderGen) return;
    this._bindPersistentDetails(el);
    this._bindTodRange(el);
  }

  _tariffStatusHtml(status, todCatalog, basicCatalog) {
    const hasData = todCatalog.length > 0 || basicCatalog.length > 0;
    const lastAttempt = status.last_attempt ? this._fmtDate(status.last_attempt) : "never";
    const lastSuccess = status.last_success ? this._fmtDate(status.last_success) : "never";
    const isStale = status.is_stale;
    const hasStatus = status.last_attempt || status.last_success || status.is_stale !== undefined;
    const lastError = status.last_error || null;
    const statusBadge = !hasStatus ? `<span class="badge unknown">unknown</span>` : isStale ? `<span class="badge off">stale</span>` : `<span class="badge on">current</span>`;
    const effectiveRow = todCatalog.length > 0 ? todCatalog[todCatalog.length - 1] : null;
    const effectiveFrom = effectiveRow?.effective_from || null;
    const periodLabel = effectiveFrom ? ` effective ${this._escape(effectiveFrom)}` : "";
    return `
      <details class="tariff-status-block"${this._detailsOpenAttr("tariff_status")}>
        <summary>Tariff sources ${statusBadge}</summary>
        <div class="tod-table-wrap">
          <table class="tod-table">
            <thead><tr><th>Source</th><th>Last check</th><th>Last success</th><th>TOD rows</th><th>Basic rows</th><th>Note</th></tr></thead>
            <tbody>
              <tr>
                <td>PGE public sources</td>
                <td>${this._escape(lastAttempt)}</td>
                <td>${this._escape(lastSuccess)}</td>
                <td class="num">${todCatalog.length}</td>
                <td class="num">${basicCatalog.length}</td>
                <td>${lastError ? this._escape(lastError) : hasData ? `Catalog${periodLabel}` : "No catalog yet"}</td>
              </tr>
            </tbody>
          </table>
        </div>
        ${!hasData ? `<p class="muted" style="margin:8px 0 0">Waiting for first tariff discovery. Rates fall back to portal defaults or manual overrides.</p>` : ""}
      </details>
    `;
  }

  _todCompareHtmlCoverage(coverage, hasCost) {
    if (!hasCost) {
      return `<div class="tod-counterfactual"><p class="muted" style="margin:0">Local estimate unavailable — imported cost must cover every consumption hour in this window (enable Include cost / wait for a full cost sync).</p></div>`;
    }
    const note = coverage.missingRates > 0
      ? `Missing rates for ${coverage.missingRates} hour slot${coverage.missingRates > 1 ? "s" : ""}.`
      : coverage.missingSamples > 0
        ? `Missing kWh samples for ${coverage.missingSamples} hour slot${coverage.missingSamples > 1 ? "s" : ""}.`
        : "";
    return `<div class="tod-counterfactual"><div class="label">Local plan estimate</div><p class="muted" style="margin:6px 0 0">Incomplete range — ${coverage.observedSlots} of ${coverage.expectedSlots} slots priced. ${this._escape(note)}</p></div>`;
  }

  _todCompareHtmlDual({
    enrolled,
    localTodTotal,
    localBasicTotal,
    localSavings,
    reconciled,
    flatRateDiag,
    tod,
    sourceLabel,
    windowLabel,
    todCatalog,
    basicCatalog,
    tariffStatus,
    overrideRates,
    overrideScope,
    basicComparisonRate,
    basicComparisonSource,
    basicComparisonEffectiveFrom,
    basicComparisonComponentBasis,
    basicComparisonExclusions,
  }) {
    if (enrolled == null) {
      return `
      <div class="tod-counterfactual">
        <div class="label">Local plan estimate</div>
        <p class="muted" style="margin:6px 0 0">Enrollment unknown — wait for programs sync before comparing TOD vs Basic.</p>
      </div>`;
    }

    const title = enrolled
      ? "On Time of Day vs Basic"
      : "If enrolled in Time of Day";
    const subtitle = "Local estimate from on-device catalog";

    // Verdict: is TOD saving or costing more vs Basic.
    let verdictClass = "tod-compare-verdict";
    let verdictText;
    const absMoney = localSavings == null ? "—" : this._fmt(Math.abs(localSavings), "", true);
    if (localSavings == null || !Number.isFinite(localSavings)) {
      verdictText = enrolled
        ? "Cannot tell yet — rates missing."
        : "Cannot tell yet — rates missing.";
    } else if (Math.abs(localSavings) < 0.01) {
      verdictText = enrolled
        ? "About the same as the Basic rate card"
        : "About the same as billed energy";
    } else if ((enrolled && localSavings < 0) || (!enrolled && localSavings > 0)) {
      // Enrolled: negative savings = costing more. Not enrolled: positive savings = would save.
      verdictClass += enrolled ? " cost-more" : " save";
      verdictText = enrolled
        ? `Costing about ${absMoney} more than Basic`
        : `Would save about ${absMoney}`;
    } else {
      verdictClass += enrolled ? " save" : " cost-more";
      verdictText = enrolled
        ? `Saving about ${absMoney} versus Basic`
        : `Would cost about ${absMoney} more`;
    }

    const hasOverride = overrideRates && overrideScope;
    const overrideNote = hasOverride
      ? ` <span class="muted">(manual override for entire range)</span>`
      : "";

    // Rate-card lines.
    const rates = tod.rates || {};
    const rateList = TOD_PERIODS.map((p) => {
      const n = Number(rates[p]);
      return Number.isFinite(n) ? this._fmt(n * 100, "") : "—";
    }).join(" / ");

    const basicSrc = basicComparisonSource || "offline defaults";
    const basicCents = basicComparisonRate != null ? this._fmt(basicComparisonRate * 100, " ¢/kWh") : "—";
    const basicEffNote = basicComparisonEffectiveFrom ? ` (eff. ${basicComparisonEffectiveFrom})` : "";
    const basisNote = basicComparisonComponentBasis
      ? ` Basis: ${this._escape(basicComparisonComponentBasis)}.`
      : "";
    const exclNote = basicComparisonExclusions
      ? ` Exclusions: ${this._escape(basicComparisonExclusions)}.`
      : "";

    // Reconciliation block.
    let reconHtml = "";
    if (reconciled && reconciled.status !== "not_comparable") {
      const statusLabel = reconciled.status === "matched" ? "Matches" : "Mismatch";
      const statusClass = reconciled.status === "matched" ? "on" : "off";
      const diffText = reconciled.diff != null ? this._fmt(reconciled.diff, "", true) : "—";
      const pctText = reconciled.pctDiff != null ? ` (${(reconciled.pctDiff * 100).toFixed(1)}%)` : "";
      reconHtml = `
        <div class="reconciliation">
          <span class="badge ${statusClass}">${statusLabel}</span>
          <span class="muted">Local savings ${this._fmt(localSavings, "", true)} vs PGE official ${this._fmt(reconciled.officialSavings, "", true)} — diff ${diffText}${pctText}</span>
        </div>
      `;
    } else if (reconciled && reconciled.status === "not_comparable") {
      const reason = reconciled.diagnostics?.reason || "unavailable";
      reconHtml = `<div class="reconciliation"><span class="badge">Not comparable</span> <span class="muted">${this._escape(reason)}</span></div>`;
    }

    // Flat-rate warning.
    let flatHtml = "";
    if (flatRateDiag?.status === "flat") {
      flatHtml = `
        <div class="tod-flat-warning">
          <span class="badge off">Flat rates</span>
          <span class="muted">PGE hourly portal cost looks flat across TOD periods — cost may not vary by period despite rate differences.</span>
        </div>
      `;
    }

    const mathNote = enrolled
      ? `Versus the Basic rate card${windowLabel ? ` (${windowLabel})` : ""}, not a full bill.`
      : `Versus billed energy${windowLabel ? ` (${windowLabel})` : ""}, not a full bill.`;
    const money = (n) => (n == null ? "—" : this._fmt(n, "", true));
    const line = (label, amount, rate, note) => `<tr>
      <td>${label}</td>
      <td class="num">${amount}</td>
      <td class="num">${rate}</td>
      <td>${note}</td>
    </tr>`;
    const persist = ` data-persist="tod_compare"${this._detailsOpenAttr("tod_compare")}`;
    return `
      <div class="tod-counterfactual dual-source">
        <div class="label">${this._escape(title)}</div>
        <div class="${verdictClass}">${this._escape(verdictText)}</div>
        <div class="tod-compare-pair">
          <div class="tod-compare-leg">
            <div class="label">TOD estimate</div>
            <div class="value">${localTodTotal != null ? this._fmt(localTodTotal, "", true) : "—"}</div>
          </div>
          <div class="tod-compare-vs">vs</div>
          <div class="tod-compare-leg">
            <div class="label">Basic estimate</div>
            <div class="value">${localBasicTotal != null ? this._fmt(localBasicTotal, "", true) : "—"}</div>
          </div>
        </div>
        <div class="delta">${this._escape(mathNote)} Estimate only — energy charges for imported kWh.${overrideNote}</div>
        ${reconHtml}
        ${flatHtml}
        <details class="tod-compare-math"${persist}>
          <summary>How this was calculated</summary>
          <table class="tod-table">
            <thead><tr><th>Line</th><th class="num">Amount</th><th class="num">Rate</th><th>What this is</th></tr></thead>
            <tbody>
              ${line(`TOD (${this._escape(sourceLabel)})`, money(localTodTotal), this._escape(`${rateList} ¢/kWh`), "Local estimate: period kWh × effective TOD rates.")}
              ${line(`Basic (${this._escape(basicSrc)})${basicEffNote}`, money(localBasicTotal), basicCents, `Source-backed estimate: kWh × Basic rate. ${basisNote}${exclNote}`)}
            </tbody>
          </table>
        </details>
      </div>
    `;
  }

  /**
   * Hero: would cost more / would save vs billed energy. Details: inferred ¢/kWh
   * plus the offline/portal rate-card TOD vs Basic model.
   */
  _todCompareHtml(compare, tod, sourceLabel, windowLabel) {
    if (!compare) return "";
    const enrolled = compare.enrolled;
    if (enrolled == null) {
      return `
      <div class="tod-counterfactual">
        <div class="label">Local plan estimate</div>
        <p class="muted" style="margin:6px 0 0">Enrollment unknown — wait for programs sync before comparing TOD vs Basic.</p>
      </div>`;
    }
    const title = enrolled
      ? "On Time of Day vs Basic (local estimate)"
      : "If enrolled in Time of Day (local estimate)";
    const left = enrolled
      ? { label: "Billed energy (TOD)", value: compare.billed }
      : { label: "TOD estimate", value: compare.todPriced };
    const right = enrolled
      ? { label: "If on Basic (rate card)", value: compare.rateCardBasic }
      : { label: "Billed energy", value: compare.billed };
    const verdict = todEnrollmentVerdict(compare);
    const absMoney =
      verdict.amount == null ? "—" : this._fmt(verdict.amount, "", true);
    let verdictText;
    let verdictClass = "tod-compare-verdict";
    if (verdict.kind === "unknown") {
      verdictText = enrolled
        ? "Cannot tell yet — Basic rate card missing."
        : "Cannot tell yet — TOD rates missing.";
    } else if (verdict.kind === "same") {
      verdictText = enrolled
        ? "About the same as the Basic rate card"
        : "About the same as billed energy";
    } else if (verdict.kind === "cost_more") {
      verdictClass += " cost-more";
      verdictText = enrolled
        ? `Costing about ${absMoney} more than Basic`
        : `Would cost about ${absMoney} more`;
    } else {
      verdictClass += " save";
      verdictText = enrolled
        ? `Saving about ${absMoney} versus Basic`
        : `Would save about ${absMoney}`;
    }
    const mathNote = enrolled
      ? `Versus the Basic rate card${windowLabel ? ` (${windowLabel})` : ""}, not a full bill.`
      : `Versus billed energy${windowLabel ? ` (${windowLabel})` : ""}, not a full bill.`;
    const eff =
      compare.effectiveUsdPerKwh != null
        ? ` Billed energy averaged ${this._fmt(compare.effectiveUsdPerKwh * 100, " ¢/kWh")} (imported cost ÷ kWh).`
        : "";
    const rates = tod.rates || {};
    const rateList = TOD_PERIODS.map((p) => {
      const n = Number(rates[p]);
      return Number.isFinite(n) ? this._fmt(n * 100, "") : "—";
    }).join(" / ");
    const basicRaw = tod.basic_rate;
    const basic = basicRaw == null ? NaN : Number(basicRaw);
    const basicCentsLabel = Number.isFinite(basic) ? this._fmt(basic * 100, " ¢/kWh") : "—";
    const sourceLabels = {
      override: "manual override",
      portal: "PGE",
      default: "offline defaults",
    };
    const basicSrc =
      sourceLabels[tod.basic_rate_source] || tod.basic_rate_source || sourceLabel;
    const persist = ` data-persist="tod_compare"${this._detailsOpenAttr("tod_compare")}`;
    let rateCardAmount = "—";
    let rateCardNote = "Unavailable.";
    if (compare.rateCardDelta != null) {
      const absCard = this._fmt(Math.abs(compare.rateCardDelta), "", true);
      if (compare.rateCardDelta >= 0) {
        rateCardAmount = `${absCard} cheaper`;
        rateCardNote = "TOD cheaper than the ¢/kWh Basic model — not billed energy.";
      } else {
        rateCardAmount = `${absCard} more`;
        rateCardNote = "TOD more than the ¢/kWh Basic model — not billed energy.";
      }
    }
    const line = (label, amount, rate, note) => `<tr>
      <td>${label}</td>
      <td class="num">${amount}</td>
      <td class="num">${rate}</td>
      <td>${note}</td>
    </tr>`;
    const money = (n) => (n == null ? "—" : this._fmt(n, "", true));
    return `
      <div class="tod-counterfactual">
        <div class="label">${this._escape(title)}</div>
        <div class="${verdictClass}">${this._escape(verdictText)}</div>
        <div class="tod-compare-pair">
          <div class="tod-compare-leg">
            <div class="label">${this._escape(left.label)}</div>
            <div class="value">${left.value == null ? "—" : this._fmt(left.value, "", true)}</div>
          </div>
          <div class="tod-compare-vs">vs</div>
          <div class="tod-compare-leg">
            <div class="label">${this._escape(right.label)}</div>
            <div class="value">${right.value == null ? "—" : this._fmt(right.value, "", true)}</div>
          </div>
        </div>
        <div class="delta">${this._escape(mathNote)}${this._escape(eff)} Estimate only — energy charges for imported kWh.</div>
        <details class="tod-compare-math"${persist}>
          <summary>How this was calculated</summary>
          <table class="tod-table">
            <thead><tr><th>Line</th><th class="num">Amount</th><th class="num">Rate</th><th>What this is</th></tr></thead>
            <tbody>
              ${line("Billed energy", money(compare.billed), compare.effectiveUsdPerKwh != null ? this._fmt(compare.effectiveUsdPerKwh * 100, " ¢/kWh") : "—", "Imported hourly cost in this window.")}
              ${line(`TOD (${this._escape(sourceLabel)})`, money(compare.todPriced), this._escape(`${rateList} ¢/kWh`), "Period kWh × effective TOD rates.")}
              ${line(`Basic (${this._escape(basicSrc)})`, money(compare.rateCardBasic), basicCentsLabel, "Rate-card model (kWh × Basic ¢) — not billed energy.")}
              ${line("Rate-card TOD vs Basic", this._escape(rateCardAmount), "—", this._escape(rateCardNote))}
            </tbody>
          </table>
        </details>
      </div>
    `;
  }

  _renderBillingPrograms() {
    const billing = this.shadowRoot.getElementById("billing");
    const programs = this.shadowRoot.getElementById("programs");
    if (!billing || !programs || !this._account) return;
    const e = this._account.entity_ids;
    const includeBilling = this._account.options?.include_billing !== false;

    if (!includeBilling) {
      billing.innerHTML = `<h2>Billing</h2><p class="muted">Billing import is disabled in Configure → Sync settings.</p>`;
      programs.innerHTML = `<h2>Programs</h2><p class="muted">Enable billing & programs to see enrollment.</p>`;
      return;
    }

    const billingGroups = [
      {
        section: "Balance & due",
        fields: [
          ["Account balance", e.account_balance, "money"],
          ["Amount due", e.amount_due, "money"],
          ["Due date", e.due_date, "date"],
          ["Last payment", e.last_payment_amount, "money"],
          ["Last payment date", e.last_payment_date, "date"],
        ],
      },
      {
        section: "Current statement",
        fields: [
          ["Current bill", e.current_bill_amount, "money"],
          ["Current bill energy", e.current_bill_kwh, "kwh"],
          ["Bill start", e.current_bill_start, "date"],
          ["Bill end", e.current_bill_end, "date"],
          ["Previous balance", e.bill_previous_balance, "money"],
          ["Current charges", e.bill_current_charges, "money"],
          ["Bill avg temperature", e.bill_avg_temperature, "temp"],
        ],
      },
      {
        section: "Lifetime & sync",
        fields: [
          ["YTD program savings", e.ytd_program_savings, "money"],
          ["Lifetime payments", e.lifetime_payments, "money"],
          ["Lifetime billed", e.lifetime_billed, "money"],
          ["Billing last sync", e.billing_last_sync, "date"],
        ],
      },
    ];
    const metrics = [];
    for (const group of billingGroups) {
      metrics.push({ section: group.section });
      for (const [label, id, kind] of group.fields) {
        const raw = stateDisplay(this._hass, id);
        const num = stateNumber(this._hass, id);
        let value;
        let note = "";
        if (kind === "money") {
          if (num == null) continue;
          value = this._fmt(num, "", true);
        } else if (kind === "date") {
          const d = this._fmtDate(raw);
          if (!d) continue;
          value = d;
        } else if (kind === "kwh") {
          if (num == null) continue;
          value = this._fmt(num, " kWh");
        } else if (kind === "temp") {
          if (num == null) continue;
          value = this._fmt(num, " °F");
        } else {
          if (raw == null || raw === "" || raw === "—" || raw === "unavailable" || raw === "unknown") {
            continue;
          }
          value = this._escape(String(raw));
        }
        if (!value || value === "—") continue;
        metrics.push({ label, value, note });
      }
    }
    const summaryHtml = this._renderSummaryPairs(metrics);
    this._disposeHostCharts(
      this.shadowRoot.getElementById("ledger-bill"),
      this.shadowRoot.getElementById("ledger-kwh")
    );
    billing.innerHTML = `
      <h2>Billing</h2>
      <p class="muted" style="margin:0 0 12px">Account balance, statement, and lifetime totals from PGE billing sync.</p>
      ${this._renderBillPdfHeader()}
      <div class="usage-accounting-body">
        ${
          summaryHtml ||
          `<p class="muted stats-meta">No billing values yet — wait for a sync or check Configure → Sync settings.</p>`
        }
        ${this._renderBillPdfStatementDetails()}
        <p class="muted stats-meta" style="margin-top:12px">Ledger charts use external statistic ids (including bill_kwh, which has no mirrored entity).</p>
        <div class="chart-host" id="ledger-bill"></div>
        <div class="chart-host" id="ledger-kwh" style="margin-top:8px"></div>
      </div>
    `;
    void this._renderLedgerCharts();

    const prog = [
      ["Auto Pay", e.autopay],
      ["Paperless bill", e.paperless_bill],
      ["Peak Time Rebates", e.program_peak_time_rebates],
      ["Green Future", e.program_green_future],
      ["Time of Day", e.program_time_of_day],
      ["Smart Thermostat", e.program_smart_thermostat],
      ["Habitat Support", e.program_habitat_support],
      ["EV Smart Charging", e.program_smart_charging],
      ["Smart Battery Pilot", e.program_smart_battery],
    ];
    const nextPtr = stateDisplay(this._hass, e.next_ptr_event_date, null);
    const ptrFootnote = nextPtr
      ? `<p class="muted stats-meta" style="margin-top:8px">Next Peak Time Rebates event: ${this._escape(nextPtr)}</p>`
      : "";
    programs.innerHTML = `
      <h2>Programs</h2>
      <div class="programs">
        ${prog
          .map(([name, id]) => {
            const raw = stateDisplay(this._hass, id, null);
            const on = raw === "on";
            const isEligible = stateAttr(this._hass, id, "is_eligible");
            const pct = stateAttr(this._hass, id, "green_future_pct");
            let stateText;
            if (raw == null) {
              stateText = "Unknown";
            } else if (on) {
              stateText = "Enrolled";
            } else if (isEligible === true) {
              stateText = "Eligible";
            } else {
              stateText = "Not enrolled";
            }
            const extra = pct != null ? ` · ${pct}%` : "";
            const cls = on ? "on" : "off";
            return `<div class="program ${cls}">
              <div class="name">${this._escape(name)}</div>
              <div class="state">${this._escape(stateText)}${this._escape(String(extra))}</div>
            </div>`;
          })
          .join("")}
      </div>
      ${ptrFootnote}
    `;
  }

  async _renderLedgerCharts() {
    const account = this._account;
    if (!account) return;
    const colors = seriesColors(this);
    const range = rangePresets()["12mo"];
    const billHost = this.shadowRoot.getElementById("ledger-bill");
    const kwhHost = this.shadowRoot.getElementById("ledger-kwh");
    if (!billHost || !kwhHost) return;
    this._disposeHostCharts(billHost, kwhHost);
    billHost.replaceChildren();
    kwhHost.replaceChildren();
    try {
      const [bill, pay, kwh] = await Promise.all([
        fetchStatisticSeries(this._hass, account.statistic_ids.bill_amount, {
          start: range.start,
          end: range.end,
          period: "month",
        }),
        fetchStatisticSeries(this._hass, account.statistic_ids.payment_amount, {
          start: range.start,
          end: range.end,
          period: "month",
        }),
        fetchStatisticSeries(this._hass, account.statistic_ids.bill_kwh, {
          start: range.start,
          end: range.end,
          period: "month",
        }),
      ]);
      const money = await createMonthCompareChart(billHost, {
        billedXs: bill.xs,
        billedYs: bill.values,
        payXs: pay.xs,
        payYs: pay.values,
        colors,
      });
      if (money) this._charts.push(money);
      const kwhChart = await createBarChart(kwhHost, {
        xs: kwh.xs,
        ys: kwh.values,
        labelY: "Bill kWh",
        color: colors.kwh,
        unit: " kWh",
      });
      if (kwhChart) this._charts.push(kwhChart);
    } catch (_err) {
      billHost.innerHTML = `<p class="muted">Ledger statistics not available yet.</p>`;
    }
  }

  _renderDiagnostics() {
    const body = this.shadowRoot.getElementById("diag-body");
    if (!body || !this._account) return;
    const sync = this._syncByEntry[this._account.entry_id] || {};
    const e = this._account.entity_ids;
    body.innerHTML = `
      <div class="entities">
        <div class="entity-row"><span>Auth expiration</span><strong>${this._escape(
          sync.auth_expiration || stateDisplay(this._hass, e.auth_expiration)
        )}</strong></div>
        <div class="entity-row"><span>Last API error</span><strong>${this._escape(
          sync.last_api_error || stateDisplay(this._hass, e.last_api_error)
        )}</strong></div>
        <div class="entity-row"><span>Sync phase</span><strong>${this._escape(sync.phase || "—")}</strong></div>
        <div class="entity-row"><span>Sync detail</span><strong>${this._escape(sync.message || "—")}</strong></div>
        <div class="entity-row"><span>Sync error</span><strong>${this._escape(sync.error || "—")}</strong></div>
        <div class="entity-row"><span>Account key</span><strong>${this._escape(
          (this._account.account_key || "").slice(0, 8) + "…"
        )}</strong></div>
        <div class="entity-row"><span>Consumption statistic</span><strong>${this._escape(
          this._account.statistic_ids.consumption
        )}</strong></div>
      </div>
    `;
  }

  _fmt(value, suffix = "", money = false) {
    if (value == null || Number.isNaN(value)) return "—";
    if (money) {
      return new Intl.NumberFormat(undefined, {
        style: "currency",
        currency: "USD",
      }).format(value);
    }
    return `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}${suffix}`;
  }

  /** PGE calendar day as YYYY-MM-DD. */
  _fmtDate(value) {
    if (value == null || value === "" || value === "—" || value === "unknown" || value === "unavailable") {
      return "";
    }
    const raw = String(value);
    const d = value instanceof Date ? value : new Date(raw);
    if (!Number.isFinite(d.getTime())) {
      const m = raw.match(/^(\d{4}-\d{2}-\d{2})/);
      return m ? m[1] : "";
    }
    // Date-only portal fields (MM/DD/YYYY) land as UTC midnight — keep that
    // calendar day. Pacific midnights arrive as 07:00Z/08:00Z — use LA date.
    if (d.getUTCHours() === 0 && d.getUTCMinutes() === 0 && d.getUTCSeconds() === 0) {
      return d.toISOString().slice(0, 10);
    }
    // en-CA yields YYYY-MM-DD.
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "America/Los_Angeles",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(d);
  }

  _escape(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }
}

// HA may reload this module when ?v= bumps; redefine throws and can abort boot.
if (!customElements.get("pge-energy-panel")) {
  customElements.define("pge-energy-panel", PgeEnergyPanel);
}
