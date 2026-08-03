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
  accountingPlan,
  clampToPublishedEnd,
  computeUsageAccounting,
  countSeriesPoints,
  fetchStatisticSeries,
  formatRangeLabel,
  invalidateStatsCache,
  minPointsForPreset,
  pacificWeekStartUtc,
  pacificYmd,
  publishedDataEnd,
  rangePresets,
  shiftChartRange,
  stateAttr,
  stateDisplay,
  stateNumber,
  sumStatisticChange,
} from "./data.js?v=0.7.4";
import {
  createBarChart,
  createLineChart,
  createMonthCompareChart,
  createScatter,
  createUsageComboChart,
  destroyCharts,
  renderHeatmap,
  seriesColors,
} from "./charts.js?v=0.7.4";
import { sparklineSvg } from "./svg-helpers.js?v=0.7.4";
import { applyPanelTheme } from "./theme.js?v=0.7.4";

/** @type {Record<string, string>} */
export const PANEL_SECTION_ANCHORS = {
  glance: "#kpis",
  usage: "#hero",
  analytics: "#insights-weather",
  billing: "#billing",
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
.kpi:focus-within .value { transform: scale(1.03); transform-origin: left center; }
.kpi:hover svg,
.kpi:focus-within svg {
  opacity: 1;
  filter: drop-shadow(0 1px 2px color-mix(in srgb, var(--primary-text-color) 18%, transparent));
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
.kpi.status-good:hover, .kpi.status-good:focus-within {
  box-shadow:
    0 6px 16px color-mix(in srgb, var(--pge-status-good) 22%, transparent),
    0 0 0 1px color-mix(in srgb, var(--pge-status-good) 28%, transparent);
}
.kpi.status-warn:hover, .kpi.status-warn:focus-within,
.kpi.kpi-statement:hover, .kpi.kpi-statement:focus-within {
  box-shadow:
    0 6px 16px color-mix(in srgb, var(--pge-series-cost) 22%, transparent),
    0 0 0 1px color-mix(in srgb, var(--pge-series-cost) 28%, transparent);
}
.kpi.status-critical:hover, .kpi.status-critical:focus-within {
  box-shadow:
    0 6px 16px color-mix(in srgb, var(--pge-status-critical) 22%, transparent),
    0 0 0 1px color-mix(in srgb, var(--pge-status-critical) 28%, transparent);
}
.kpi.kpi-usage:hover, .kpi.kpi-usage:focus-within {
  box-shadow:
    0 6px 16px color-mix(in srgb, var(--pge-series-kwh) 22%, transparent),
    0 0 0 1px color-mix(in srgb, var(--pge-series-kwh) 28%, transparent);
}
.kpi.kpi-estimate:hover, .kpi.kpi-estimate:focus-within {
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
      // Bill-bound presets (cycle) may appear only after entity states hydrate.
      void this._probeAvailablePresets().then(() => this._renderFilters());
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
    this._renderFilters();
    this._renderSync();
    await this._renderKpis();
    await this._renderDataGaps();
    await this._renderHero();
    await this._renderInsights();
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
    const yesterdayCost = stateNumber(this._hass, e.yesterday_cost);
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
    try {
      const publishedEnd = publishedDataEnd();
      const weekStart = pacificWeekStartUtc();
      const sparkStart = new Date(publishedEnd.getTime() - 14 * 24 * 60 * 60 * 1000);
      const [kwhSeries, costSeries, weekKwhSum, weekCostSum] = await Promise.all([
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
      ]);
      sparkKwh = kwhSeries.values || [];
      sparkCost = costSeries.values || [];
      weekKwh = weekKwhSum.total;
      weekCost = weekCostSum.total;
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
    el.innerHTML = `
      <h2>At a glance</h2>
      <p class="muted" style="margin:0 0 12px">Yesterday and week use imported intervals through yesterday (Pacific week starts Sunday; no complete today). Statement = PGE billDetails. Usage cycle = imported hourly sum over that period. Since statement = usage after the statement end through yesterday. PGE estimate = PGE's own open-cycle projection, which does not reconcile with the interval sums.</p>
      <div class="kpi-row">
        <div class="kpi"><div class="label">Yesterday kWh</div><div class="value">${this._fmt(yesterdayKwh, " kWh")}</div>${spark(sparkKwh, "var(--pge-series-kwh)")}</div>
        <div class="kpi"><div class="label">Yesterday cost</div><div class="value">${this._fmt(yesterdayCost, "", true)}</div>${spark(sparkCost, "var(--pge-series-cost)")}</div>
        <div class="kpi"><div class="label">Week kWh</div><div class="value">${this._fmt(weekKwh, " kWh")}</div><div class="delta">${this._escape(weekRange)}</div>${spark(sparkWeekKwh, "var(--pge-series-kwh)")}</div>
        <div class="kpi"><div class="label">Week cost</div><div class="value">${this._fmt(weekCost, "", true)}</div><div class="delta">${this._escape(weekRange)}</div>${spark(sparkWeekCost, "var(--pge-series-cost)")}</div>
        <div class="kpi kpi-statement"><div class="label">Statement cycle cost</div><div class="value">${this._fmt(cycleCost, "", true)}</div><div class="delta">${this._escape(cycleRange)}</div></div>
        <div class="kpi kpi-statement"><div class="label">Statement cycle kWh</div><div class="value">${this._fmt(cycleKwh, " kWh")}</div><div class="delta">${this._escape(cycleRange)}</div></div>
        <div class="kpi kpi-usage"><div class="label">Usage cycle cost</div><div class="value">${this._fmt(usageCycleCost, "", true)}</div><div class="delta">${this._escape(fmtDelta(costDelta, true))}</div></div>
        <div class="kpi kpi-usage"><div class="label">Usage cycle kWh</div><div class="value">${this._fmt(usageCycleKwh, " kWh")}</div><div class="delta">${this._escape(fmtDelta(kwhDelta, false))}</div></div>
        <div class="kpi kpi-usage"><div class="label">Since statement cost</div><div class="value">${this._fmt(sinceStatementCost, "", true)}</div><div class="delta">${this._escape(sinceStatementRange)}</div></div>
        <div class="kpi kpi-usage"><div class="label">Since statement kWh</div><div class="value">${this._fmt(sinceStatementKwh, " kWh")}</div><div class="delta">${this._escape(sinceStatementRange)}</div></div>
        <div class="kpi kpi-estimate"><div class="label">PGE est. charges so far</div><div class="value">${this._fmt(estCharges, "", true)}</div><div class="delta">${this._escape(cycleProgress)}</div></div>
        <div class="kpi kpi-estimate kpi-dual"><div class="label">PGE est. next bill</div><div class="value">${this._escape(estRange)}</div><div class="delta">${this._escape(cycleProgress)}</div></div>
        <div class="kpi status-${dueStatus}"><div class="label">Amount due</div><div class="value">${this._fmt(amountDue, "", true)}</div><div class="delta">Due ${this._escape(this._fmtDate(dueDate) || "—")}</div></div>
        <div class="kpi"><div class="label">Last payment</div><div class="value">${this._fmt(lastPayment, "", true)}</div><div class="delta">${this._escape(this._fmtDate(lastPaymentDate) || "—")}</div></div>
      </div>
    `;
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

    const [kwh, cost, temp] = await Promise.all([
      fetchStatisticSeries(this._hass, ids.consumption, {
        start: range.start,
        end: range.end,
        period,
        maxPoints,
      }),
      fetchStatisticSeries(this._hass, ids.cost, {
        start: range.start,
        end: range.end,
        period,
        maxPoints,
      }),
      fetchStatisticSeries(this._hass, ids.temperature, {
        start: range.start,
        end: range.end,
        period,
        maxPoints,
      }),
    ]);
    this._lastSeries = { kwh, cost, temp, range, period };

    const usageHost = this.shadowRoot.getElementById("chart-usage");
    if (usageHost) {
      this._disposeHostCharts(usageHost);
      const chart = await createUsageComboChart(usageHost, {
        kwh: { xs: kwh.xs, ys: kwh.values },
        cost: { xs: cost.xs, ys: cost.values },
        temp: { xs: temp.xs, ys: temp.means },
        colors,
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

  async _fetchTriple(ids, start, end, period, maxPoints) {
    const [kwh, cost, temp] = await Promise.all([
      fetchStatisticSeries(this._hass, ids.consumption, { start, end, period, maxPoints }),
      fetchStatisticSeries(this._hass, ids.cost, { start, end, period, maxPoints }),
      fetchStatisticSeries(this._hass, ids.temperature, { start, end, period, maxPoints }),
    ]);
    return { kwh, cost, temp };
  }

  /** Drop empty rollup rows (no kWh/cost/temp — lack of data, not a real zero day). */
  _populatedRollupRows(rows) {
    return (rows || []).filter(
      (r) =>
        (r.kwh != null && Number(r.kwh) !== 0) ||
        (r.cost != null && Number(r.cost) !== 0) ||
        (r.avgTemp != null && Number.isFinite(Number(r.avgTemp)))
    );
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

  _rollupTable(title, caption, rows, keyLabel, persistKey) {
    const populated = this._populatedRollupRows(rows);
    if (!populated.length) return "";
    const cell = (raw, money = false) => {
      if (raw == null || Number.isNaN(Number(raw))) return "";
      if (Number(raw) === 0) return "";
      return this._fmt(raw, "", money);
    };
    const numAttr = (raw) =>
      raw == null || Number.isNaN(Number(raw)) ? "" : String(Number(raw));
    const body = populated
      .map((r) => {
        const kwh = cell(r.kwh);
        const cost = cell(r.cost, true);
        const rate = cell(r.rate, true);
        const temp = cell(r.avgTemp);
        const peak = cell(r.peakKwh);
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
    const rate = totK > 0 ? totC / totK : null;
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
              <th data-col="1" title="Sort by kWh">kWh</th>
              <th data-col="2" title="Sort by cost">Cost</th>
              <th data-col="3" title="Sort by rate">$/kWh</th>
              <th data-col="4" title="Sort by temperature">Avg °F</th>
              <th data-col="5" title="Sort by buckets">Buckets</th>
              <th data-col="6" title="Sort by peak">Peak bucket</th>
            </tr></thead>
            <tbody>${body}</tbody>
            <tfoot><tr>
              <td>Total</td>
              <td>${totK ? this._fmt(totK, "") : ""}</td>
              <td>${totC ? this._fmt(totC, "", true) : ""}</td>
              <td>${rate != null && rate !== 0 ? this._fmt(rate, "", true) : ""}</td>
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
    const { kwh, cost, temp, range, period } = this._lastSeries;
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
    const chart = { kwh, cost, temp };
    let hourly = period === "hour" ? chart : null;
    let daily = period === "day" ? chart : null;
    let monthly = period === "month" ? chart : null;

    try {
      const jobs = [];
      if (plan.needHour && !hourly) {
        jobs.push(
          this._fetchTriple(ids, range.start, range.end, "hour", maxPoints).then((t) => {
            hourly = t;
          })
        );
      }
      if (plan.needDay && !daily) {
        jobs.push(
          this._fetchTriple(ids, range.start, range.end, "day", maxPoints).then((t) => {
            daily = t;
          })
        );
      }
      if (plan.needMonth && !monthly) {
        jobs.push(
          this._fetchTriple(ids, range.start, range.end, "month", maxPoints).then((t) => {
            monthly = t;
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
    const meta = `${spanLabel} · chart ${periodLabel} · ${scaleNote}${
      coverBits.length ? ` · ${coverBits.join(" · ")}` : ""
    } · span ${acct.spanDays.toFixed(1)} days`;

    const bucketLabel = periodLabel;
    /** @type {{section?: string, label?: string, value?: string, note?: string}[]} */
    const metrics = [];
    const addSection = (name) => metrics.push({ section: name });
    const addMetric = (label, raw, note = "", { money = false, suffix = "" } = {}) => {
      if (raw == null || Number.isNaN(Number(raw))) return;
      const n = Number(raw);
      if (n === 0) return;
      const value = money ? this._fmt(n, "", true) : this._fmt(n, suffix);
      if (!value || value === "—") return;
      metrics.push({ label, value, note: note || "" });
    };

    addSection("Totals & averages");
    addMetric("Total kWh", acct.totalKwh, "imported series", { suffix: " kWh" });
    addMetric("Total cost", acct.totalCost, "", { money: true });
    addMetric("Avg $/kWh", acct.avgRate, "", { money: true });
    addMetric("Avg kWh / hour", acct.avgKwhPerHour, "÷ span hours", { suffix: " kWh" });
    addMetric("Avg kWh / day", acct.avgKwhPerDay, "÷ span days", { suffix: " kWh" });
    addMetric("Avg cost / hour", acct.avgCostPerHour, "", { money: true });
    addMetric("Avg cost / day", acct.avgCostPerDay, "", { money: true });
    if (acct.spanMonths >= 1.5) {
      addMetric("Avg kWh / month", acct.avgKwhPerMonth, "÷ span months", { suffix: " kWh" });
      addMetric("Avg cost / month", acct.avgCostPerMonth, "", { money: true });
    }
    if (acct.spanYears >= 0.9) {
      addMetric("Avg kWh / year", acct.avgKwhPerYear, "÷ span years", { suffix: " kWh" });
      addMetric("Avg cost / year", acct.avgCostPerYear, "", { money: true });
    }

    addSection(`Distribution (${bucketLabel})`);
    addMetric("Avg temperature", acct.temp.mean, `${acct.temp.count} samples`, { suffix: " °F" });
    addMetric(`Median kWh`, acct.kwh.median, `per ${bucketLabel}`, { suffix: " kWh" });
    addMetric(`Median cost`, acct.cost.median, `per ${bucketLabel}`, { money: true });
    addMetric("Median temperature", acct.temp.median, "", { suffix: " °F" });
    addMetric("kWh stdev", acct.kwh.stdev, `per ${bucketLabel}`, { suffix: " kWh" });
    addMetric("Cost stdev", acct.cost.stdev, `per ${bucketLabel}`, { money: true });
    addMetric("Temp stdev", acct.temp.stdev, `per ${bucketLabel}`, { suffix: " °F" });

    addSection("Extremes");
    addMetric("Min kWh", acct.kwh.min, this._fmtWhen(acct.kwh.lowAt), { suffix: " kWh" });
    addMetric("Max kWh", acct.kwh.max, this._fmtWhen(acct.kwh.peakAt), { suffix: " kWh" });
    addMetric("Min cost", acct.cost.min, this._fmtWhen(acct.cost.lowAt), { money: true });
    addMetric("Max cost", acct.cost.max, this._fmtWhen(acct.cost.peakAt), { money: true });
    addMetric("Min temperature", acct.temp.min, this._fmtWhen(acct.temp.lowAt), { suffix: " °F" });
    addMetric("Max temperature", acct.temp.max, this._fmtWhen(acct.temp.peakAt), { suffix: " °F" });
    if (acct.hour?.count) {
      addMetric("Peak hour kWh", acct.hour.max, this._fmtWhen(acct.hour.peakAt), { suffix: " kWh" });
      addMetric("Quiet hour kWh", acct.hour.min, this._fmtWhen(acct.hour.lowAt), { suffix: " kWh" });
      addMetric("Median hour kWh", acct.hour.median, `${acct.hour.count} hours`, { suffix: " kWh" });
    }
    if (acct.bestDay?.kwh) {
      addMetric("Highest day", acct.bestDay.kwh, this._fmtRollupKey(acct.bestDay.key), {
        suffix: " kWh",
      });
    }
    if (acct.worstDay?.kwh) {
      addMetric("Lowest day", acct.worstDay.kwh, this._fmtRollupKey(acct.worstDay.key), {
        suffix: " kWh",
      });
    }
    if (acct.plan.showMonths && acct.bestMonth?.kwh) {
      addMetric("Highest month", acct.bestMonth.kwh, this._fmtRollupKey(acct.bestMonth.key), {
        suffix: " kWh",
      });
    }
    if (acct.plan.showMonths && acct.worstMonth?.kwh) {
      addMetric("Lowest month", acct.worstMonth.kwh, this._fmtRollupKey(acct.worstMonth.key), {
        suffix: " kWh",
      });
    }
    if (acct.plan.showYears && acct.bestYear?.kwh) {
      addMetric("Highest year", acct.bestYear.kwh, this._fmtRollupKey(acct.bestYear.key), {
        suffix: " kWh",
      });
    }
    if (acct.plan.showYears && acct.worstYear?.kwh) {
      addMetric("Lowest year", acct.worstYear.kwh, this._fmtRollupKey(acct.worstYear.key), {
        suffix: " kWh",
      });
    }

    const summaryHtml = this._renderSummaryPairs(metrics);
    const tables = [];
    if (acct.plan.showYears) {
      tables.push(
        this._rollupTable(
          "Yearly breakdown",
          "Pacific calendar years with imported usage in range.",
          yearsPop,
          "Year",
          "rollup_yearly"
        )
      );
    }
    if (acct.plan.showMonths) {
      tables.push(
        this._rollupTable(
          "Monthly breakdown",
          "Pacific calendar months with imported usage in range.",
          monthsPop,
          "Month",
          "rollup_monthly"
        )
      );
    }
    if (acct.plan.showDays) {
      tables.push(
        this._rollupTable(
          "Daily breakdown",
          "Pacific calendar days with imported usage in range.",
          daysPop,
          "Date",
          "rollup_daily"
        )
      );
    }
    if (acct.plan.showHours) {
      tables.push(
        this._rollupTable(
          "Hourly breakdown",
          "Pacific hours with imported usage (short windows).",
          hoursPop,
          "Hour",
          "rollup_hourly"
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
    ];
    programs.innerHTML = `
      <h2>Programs</h2>
      <div class="programs">
        ${prog
          .map(([name, id]) => {
            const on = stateDisplay(this._hass, id) === "on";
            const pct = stateAttr(this._hass, id, "green_future_pct");
            const extra =
              pct != null ? ` · ${pct}%` : "";
            return `<div class="program ${on ? "on" : "off"}">
              <div class="name">${this._escape(name)}</div>
              <div class="state">${on ? "Enrolled" : "Not enrolled"}${this._escape(String(extra))}</div>
            </div>`;
          })
          .join("")}
      </div>
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
