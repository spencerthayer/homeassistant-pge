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
  RANGE_PRESET_TOD,
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
  pctDelta,
  rollupColumns,
  formatRangeLabel,
  formatSignedUsd,
  invalidateStatsCache,
  minPointsForPreset,
  pacificMidnightUtc,
  pacificParts,
  pacificWeekStartUtc,
  pacificYmd,
  presetProbeEffect,
  PANEL_TAB_ICONS,
  PANEL_TAB_LABELS,
  PANEL_TABS,
  panelTabHash,
  priorPacificYmd,
  syncHasReportableError,
  syncIssueUrl,
  syncPillState,
  resolvePanelTab,
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
} from "./data.js?v=0.12.5";
import {
  baseloadFloor,
  cycleCumulative,
  dayFingerprints,
  histogramBins,
  hourWeekdayMatrix,
  monthRidges,
  monthlyByYear,
  publishedWeekDays,
  spreadBand,
  storySummary,
  typicalDayProfiles,
  gapDailyRows,
  overnightFloorDays,
  baseloadSteps,
  billExplainer,
  counterfactual,
  daypartDays,
  degreePrice,
  shiftCostByStartHour,
  weatherModel,
  forwardRibbon,
  moneyHourPareto,
  periodBox,
  periodMixByMonth,
  sankeyFlows,
  todMinusBasicByMonth,
  billVsImported,
  centsPerKwh,
  degreeDayPoint,
  statementGap,
  statementWindows,
  tempBins,
  billAnatomyRows,
  billFamilies,
  duckHourProfiles,
  duckMonthBars,
  hasExport,
  lineItemShares,
  treemapSlices,
  waterfallSteps,
} from "./chart-series.js?v=0.12.5";
import { FACTORY_RENDERERS, galleryRecordCurrent, openChartDialog, renderInsights, renderLoadShape, renderPdfSolar, renderTodCharts, renderWeatherMoney, rerenderFactoryHosts, resumeChartDialog, runGalleryFactory, suspendChartDialog } from "./chart-gallery.js?v=0.12.5";
import {
  createBarChart,
  createLineChart,
  createMonthCompareChart,
  createScatter,
  createUsageComboChart,
  destroyCharts,
  renderHeatmap,
  seriesColors,
} from "./charts.js?v=0.12.5";
import { sparklineSvg } from "./svg-helpers.js?v=0.12.5";
import { applyPanelTheme, todColors } from "./theme.js?v=0.12.5";

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
  --pge-bill-basic: var(--blue-grey-color, #607d8b);
  --pge-bill-energy: var(--pge-series-kwh);
  --pge-bill-delivery: var(--purple-color, #7b61ff);
  --pge-bill-taxes: var(--amber-color, #ffc107);
  --pge-bill-other: var(--brown-color, #795548);
  --pge-space-1: 4px;
  --pge-space-2: 8px;
  --pge-space-3: 12px;
  --pge-space-4: 16px;
  --pge-space-6: 24px;
  --pge-space-8: 32px;
  --pge-radius: var(--ha-card-border-radius, 12px);
  --pge-surface: var(--card-background-color, var(--ha-card-background, #fff));
  --pge-surface-2: color-mix(in srgb, var(--primary-text-color) 4%, var(--pge-surface));
  --pge-border: var(--divider-color, rgba(0, 0, 0, 0.12));
  --pge-shadow-1: 0 1px 2px rgb(0 0 0 / 0.06), 0 2px 8px rgb(0 0 0 / 0.06);
  --pge-shadow-2: 0 4px 16px rgb(0 0 0 / 0.10);
  --pge-ease: cubic-bezier(0.22, 1, 0.36, 1);
  --pge-dur-fast: 120ms;
  --pge-dur: 220ms;
  --pge-dur-slow: 420ms;
  --pge-text-eyebrow: 600 0.72rem/1.2 var(--ha-font-family-body, Roboto, system-ui);
  --pge-text-headline: 600 1.15rem/1.3 var(--ha-font-family-body, Roboto, system-ui);
  --pge-text-display: 600 2rem/1.1 var(--ha-font-family-body, Roboto, system-ui);
  color-scheme: light;
}
@supports not (color: color-mix(in srgb, red, blue)) {
  :host { --pge-surface-2: var(--secondary-background-color); }
}
:host *, :host *::before, :host *::after { box-sizing: border-box; }
:host([data-dark]) {
  color-scheme: dark;
}
.chart-skeleton { min-height: 160px; }
@media (prefers-reduced-motion: reduce) {
  :host * { transition: none !important; animation: none !important; }
  .chart-skeleton { animation: none; }
}
.toolbar {
  display: flex; align-items: center; gap: 12px;
  padding: 8px 16px; min-height: 56px;
  background: var(--app-header-background-color, var(--primary-color));
  color: var(--app-header-text-color, var(--text-primary-color, #fff));
}
.panel-chrome {
  position: sticky;
  top: 0;
  z-index: 3;
  background: color-mix(in srgb, var(--primary-background-color) 88%, transparent);
  backdrop-filter: saturate(1.4) blur(8px);
}
.pge-header {
  position: static;
  padding: var(--pge-space-2) var(--pge-space-4) 0;
}
.hdr-row { display: flex; align-items: center; gap: var(--pge-space-3); }
.section-tabs { display: flex; align-items: center; gap: var(--pge-space-2); overflow: hidden; }
.section-tab-scroll {
  display: flex;
  flex-wrap: nowrap;
  gap: var(--pge-space-1);
  overflow-x: auto;
  flex: 1;
  min-width: 0;
  scrollbar-width: none;
}
.section-tab-scroll::-webkit-scrollbar { display: none; }
.section-tabs [role="tab"] {
  display: inline-flex; align-items: center; gap: 6px;
  border: 0; background: transparent; color: var(--primary-text-color);
  padding: 8px 10px; cursor: pointer; border-bottom: 2px solid transparent;
  white-space: nowrap;
}
.section-tabs [role="tab"] span { white-space: nowrap; }
.section-tabs [role="tab"][aria-selected="true"] { border-bottom-color: var(--primary-color); }
.sync-pill-wrap { position: relative; margin-left: auto; flex: 0 0 auto; }
.toolbar .sync-pill {
  background: color-mix(in srgb, var(--app-header-text-color, #fff) 16%, transparent);
  color: var(--app-header-text-color, #fff);
  border-color: color-mix(in srgb, var(--app-header-text-color, #fff) 40%, transparent);
}
.sync-pill {
  border: 1px solid var(--pge-border); border-radius: 999px;
  background: var(--pge-surface); color: var(--primary-text-color); padding: 6px 12px; cursor: pointer;
}
.sync-pill-text { display: inline; }
.sync-pill.good { color: var(--pge-status-good); }
.sync-pill.warn { color: var(--pge-status-warn); }
.sync-pill.critical { color: var(--pge-status-critical); }
.sync-pop {
  display: none;
  position: absolute;
  right: 0;
  top: calc(100% + 8px);
  z-index: 6;
  width: min(320px, calc(100vw - 32px));
  padding: 12px;
  border-radius: 12px;
  border: 1px solid var(--pge-border);
  background: var(--pge-surface);
  color: var(--primary-text-color);
  box-shadow: var(--pge-shadow-2);
  font-size: 0.82rem;
}
.sync-pop dl { display: grid; grid-template-columns: auto 1fr; gap: 4px 10px; margin: 0; }
.sync-pop dt { color: var(--secondary-text-color); }
.sync-pop dd { margin: 0; overflow-wrap: anywhere; }
.sync-pop .error { margin: 8px 0 0; }
.sync-pop-actions { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-top: 10px; }
.sync-pop-actions a, .sync-pop-actions button {
  background: none; border: 0; padding: 0; color: var(--primary-color); cursor: pointer;
  font: inherit; text-decoration: underline;
}
@media (hover: hover) and (pointer: fine) {
  .sync-pill-wrap:hover .sync-pop,
  .sync-pill-wrap:focus-within .sync-pop { display: block; }
}
.sync-pill-wrap.open .sync-pop { display: block; }
input[type="number"], input[type="text"], input[type="datetime-local"], select {
  border: 1px solid var(--pge-border);
  border-radius: 8px;
  padding: 6px 10px;
  background: var(--pge-surface);
  color: var(--primary-text-color);
  font: inherit;
  transition: border-color var(--pge-dur-fast) var(--pge-ease);
}
input:focus-visible, select:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 1px; }
.chip, .metric-toggle button {
  border-radius: 999px;
  border: 1px solid var(--pge-border);
  background: var(--pge-surface);
  color: var(--primary-text-color);
  padding: 6px 12px;
}
.chip[aria-pressed="true"], .metric-toggle button[aria-pressed="true"] {
  background: var(--primary-color);
  color: var(--text-primary-color, #fff);
}
dialog.chart-dialog {
  width: min(1200px, 96vw);
  max-height: 92vh;
  overflow: auto;
  border: 0;
  background: var(--pge-surface);
  color: var(--primary-text-color);
}
dialog.drawer {
  margin: 0 0 0 auto; height: 100%; max-height: none; width: min(480px, 100vw);
  border: 0; padding: var(--pge-space-4); background: var(--pge-surface);
  color: var(--primary-text-color); box-shadow: var(--pge-shadow-2);
}
.drawer-head { padding-right: 36px; }
.drawer-head h2 { margin: 4px 0 12px; }
.drawer-close {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 1;
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--primary-text-color);
  font-size: 24px;
  line-height: 1;
  cursor: pointer;
}
.drawer-close:hover { background: var(--pge-surface-2); }
dialog.drawer::backdrop { background: rgb(0 0 0 / 0.35); backdrop-filter: blur(2px); }
dialog.drawer[open] { animation: pge-slide-in var(--pge-dur) var(--pge-ease); }
@keyframes pge-slide-in { from { transform: translateX(24px); opacity: 0; } }
@keyframes pge-fade-up { from { opacity: 0; transform: translateY(6px); } }
.tab-panel:not([hidden]) { animation: pge-fade-up var(--pge-dur) var(--pge-ease); }
details { interpolate-size: allow-keywords; }
.sync-pill.warn::before { content: ""; display: inline-block; width: 8px; height: 8px; margin-right: 6px; border-radius: 50%; background: var(--pge-status-warn); }
.toolbar button.menu {
  background: none; border: 0; color: inherit; cursor: pointer;
  font-size: 22px; width: 40px; height: 40px;
}
.toolbar .brand { display: flex; align-items: center; gap: 10px; font-weight: 600; }
.toolbar img { height: 28px; width: auto; }
.content {
  padding: 16px;
  max-width: 2400px;
  margin: 0 auto;
  container-type: inline-size;
  container-name: pge;
}
.tabs { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.tabs button {
  border: 1px solid var(--divider-color); background: var(--card-background-color);
  color: var(--primary-text-color); border-radius: 8px; padding: 6px 12px; cursor: pointer;
}
.tabs button.active { border-color: var(--primary-color); color: var(--primary-color); font-weight: 600; }
.card {
  background: var(--pge-surface);
  color: var(--primary-text-color);
  border-radius: var(--pge-radius);
  border: 1px solid var(--pge-border);
  box-shadow: var(--pge-shadow-1);
  padding: var(--pge-space-6);
  margin-bottom: var(--pge-space-6);
}
.eyebrow {
  font: var(--pge-text-eyebrow);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--secondary-text-color);
}
.card h2, .card h3 { margin: 0 0 12px; font-size: 1.1rem; font-weight: 600; color: var(--primary-text-color); }
.card.story-band {
  background: none;
  border: 0;
  box-shadow: none;
  /* Beats the phone .card padding so the estimate line stays off the tabs. */
  padding: 24px 16px 12px;
}
.story-line { margin: 0 0 8px; font: var(--pge-text-headline); border-left: 3px solid var(--primary-color); padding-left: 12px; }
#kpis .kpi {
  display: grid;
  grid-template-rows: auto auto auto 1fr;
  min-height: 96px;
}
#kpis .kpi svg { align-self: end; }
.usage-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.usage-head h2 { margin: 0; }
@container pge (max-width: 640px) {
  .view-chips {
    flex-wrap: nowrap;
    overflow-x: auto;
    -webkit-mask-image: linear-gradient(to right, #000 85%, transparent);
    mask-image: linear-gradient(to right, #000 85%, transparent);
  }
}
@container pge (max-width: 640px) {
  #tod .kpi-row { grid-template-columns: 1fr 1fr; }
  #tod .kpi-row .kpi:first-child { grid-column: span 2; }
}
#kpis { container-type: inline-size; }
.kpi-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  grid-auto-flow: row;
  gap: var(--pge-space-3);
}
@media (min-width: 871px) {
  @container (min-width: 600px) {
    .kpi-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .kpi-grid > .kpi:nth-child(13),
    .kpi-grid > .kpi:nth-child(14) { grid-column: span 2; }
  }
  @container (min-width: 1300px) {
    .kpi-grid {
      grid-template-columns: repeat(7, minmax(0, 1fr));
      grid-template-rows: auto auto;
      grid-auto-flow: column;
    }
    .kpi-grid > .kpi:nth-child(13),
    .kpi-grid > .kpi:nth-child(14) { grid-column: auto; }
  }
}
.kpi .label { text-transform: none; letter-spacing: 0; }
.kpi .group {
  display: block;
  font-size: 0.68rem;
  font-weight: 600;
  color: var(--secondary-text-color);
}
.kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 180px), 1fr)); gap: 12px; }
#kpis .kpi { padding: 10px 12px; }
#kpis .kpi .value { font-size: 1.15rem; margin: 2px 0; }
.hint { position: relative; display: inline-flex; flex: 0 0 auto; vertical-align: middle; margin-left: 6px; }
.hint-btn {
  width: 18px; height: 18px; border-radius: 999px; padding: 0;
  border: 1px solid var(--pge-border);
  background: var(--pge-surface-2);
  color: var(--secondary-text-color);
  font: 700 0.72rem/1 var(--ha-font-family-body, Roboto, system-ui);
  cursor: pointer;
}
.hint-pop {
  display: none;
  position: absolute;
  left: 0;
  top: calc(100% + 6px);
  z-index: 6;
  width: min(340px, 72vw);
  max-height: min(60vh, 28rem);
  overflow: auto;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--pge-border);
  background: var(--pge-surface);
  color: var(--primary-text-color);
  box-shadow: var(--pge-shadow-2);
  font: 400 0.8rem/1.45 var(--ha-font-family-body, Roboto, system-ui);
  text-align: left;
  white-space: normal;
}
.hint-pop dl { margin: 0; }
.hint-pop dt {
  margin: 8px 0 0;
  font-weight: 650;
  font-size: 0.72rem;
  color: var(--secondary-text-color);
}
.hint-pop dt:first-child { margin-top: 0; }
.hint-pop dd { margin: 2px 0 0; }
@media (hover: hover) and (pointer: fine) {
  .hint:hover .hint-pop,
  .hint:focus-within .hint-pop { display: block; }
}
.hint.open .hint-pop { display: block; }
.kpi .value.display { font: var(--pge-text-display); }
.delta-chip { display: inline-block; margin-top: 4px; font-size: 0.75rem; }
.delta-chip.warn { color: var(--pge-status-warn); }
.delta-chip.good { color: var(--pge-status-good); }
.est-range { display: flex; align-items: center; gap: 8px; }
.est-range progress { flex: 1; }
.kpi {
  border: 1px solid var(--pge-border); border-radius: var(--pge-radius); padding: var(--pge-space-3);
  background: var(--pge-surface);
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
.kpi .label { font: var(--pge-text-eyebrow); letter-spacing: 0; text-transform: none; color: var(--secondary-text-color); }
.kpi .value, .num {
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.01em;
}
.kpi .value {
  font-size: 1.35rem; font-weight: 650; margin: 4px 0; color: var(--primary-text-color);
  transform: translateZ(0);
  transition: transform 180ms cubic-bezier(0.22, 1, 0.36, 1);
}
.kpi .delta {
  font-size: 0.75rem;
  color: var(--secondary-text-color);
  overflow-wrap: normal;
  word-break: normal;
  hyphens: none;
}
.kpi .delta .date { white-space: nowrap; }
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
  background: var(--pge-surface-2);
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
.filters[hidden] { display: none !important; }
/* Sits in the usage chart card. The tab row stays sticky; this bar does not. */
.hdr-range.filters { margin: 0 0 12px; position: static; min-width: 0; max-width: 100%; }
.usage-range { min-width: 0; max-width: 100%; }
#kpis, #hero, #insights-weather, #tod, #billing, #programs {
  scroll-margin-top: calc(var(--pge-header-h, 72px) + 8px);
}
.filters {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  margin-bottom: 12px;
}
.range-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 12px;
}
.range-tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.seg {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  max-width: 100%;
  padding: 2px;
  border-radius: 999px;
  border: 1px solid var(--pge-border);
  background: var(--pge-surface-2);
  overflow-x: auto;
  scrollbar-width: none;
}
.seg::-webkit-scrollbar { display: none; }
.filters .seg button,
.filters .seg select,
.filters .stepper button,
.filters .ghost,
.filters .range-custom button,
.filters .range-custom input[type="datetime-local"] {
  border: 0;
  background: transparent;
  color: var(--primary-text-color);
  border-radius: 999px;
  min-height: 30px;
  padding: 4px 12px;
  font-size: 0.82rem;
  font-weight: 550;
  white-space: nowrap;
  cursor: pointer;
  color-scheme: inherit;
  transition: background var(--pge-dur-fast) var(--pge-ease), color var(--pge-dur-fast) var(--pge-ease);
}
.filters .seg button:hover:not(:disabled):not(.active),
.filters .stepper button:hover:not(:disabled),
.filters .ghost:hover {
  background: color-mix(in srgb, var(--primary-text-color) 8%, transparent);
}
.filters .seg button.active,
.filters select.range-more.active {
  background: var(--primary-color);
  color: var(--text-primary-color, #fff);
  font-weight: 650;
}
.filters .seg button:disabled { opacity: 0.38; cursor: not-allowed; }
.filters select.range-more {
  min-width: 6.5rem;
  min-height: 34px;
  padding-right: 8px;
  border: 1px solid var(--pge-border);
  background: var(--pge-surface);
  border-radius: 999px;
}
.stepper {
  display: inline-flex;
  align-items: center;
  min-height: 34px;
  max-width: 100%;
  border: 1px solid var(--pge-border);
  border-radius: 999px;
  background: var(--pge-surface);
}
.filters .stepper button {
  width: 32px;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.95rem;
}
.filters .stepper button:disabled { opacity: 0.35; cursor: not-allowed; }
.filters .range-label {
  flex: 1 1 auto;
  min-width: 9rem;
  font-size: 0.8rem;
  color: var(--secondary-text-color);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: min(28rem, 46vw);
  padding: 0 2px;
}
.filters .ghost {
  border: 1px solid var(--pge-border);
  background: var(--pge-surface);
  min-height: 34px;
}
.filters .ghost[aria-pressed="true"] {
  border-color: var(--primary-color);
  color: var(--primary-color);
  font-weight: 650;
}
.filters .range-custom {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 6px 8px 6px 14px;
  border-radius: 999px;
  border: 1px solid var(--pge-border);
  background: var(--pge-surface-2);
}
.filters .range-custom[hidden] { display: none !important; }
.range-custom-label {
  font: var(--pge-text-eyebrow);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--secondary-text-color);
}
.filters .range-custom input[type="datetime-local"] {
  width: 13.5rem;
  max-width: 100%;
  border-radius: 8px;
  background: var(--pge-surface);
  border: 1px solid var(--pge-border);
  cursor: text;
}
.filters .range-custom button {
  background: var(--primary-color);
  color: var(--text-primary-color, #fff);
  font-weight: 650;
}
.chart-host { width: 100%; min-height: 140px; }
#chart-fingerprint { min-height: 280px; }
#chart-ridgelines { min-height: 320px; }
.heatmap-scroll { overflow-x: auto; max-width: 100%; }
.heatmap-pair { min-width: 0; }
.chart-gallery {
  margin-top: 12px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 560px), 1fr));
  gap: var(--pge-space-4, 16px);
}
.chart-gallery figure { margin: 0; }
.fig-wide { grid-column: 1 / -1; }
.fig-head { display: flex; align-items: flex-start; gap: var(--pge-space-2, 8px); }
.fig-titles { flex: 1; min-width: 0; }
.fig-title {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin: 2px 0 0;
  font: var(--pge-text-headline);
}
.fig-title-text { flex: 1; min-width: 0; }
@container pge (max-width: 640px) { .fig-expand { display: none; } }
.fig-head > .hint { margin-left: auto; }
.fig-head > .hint .hint-pop { left: auto; right: 0; }
.fig-expand { border: 0; background: transparent; color: var(--primary-text-color); cursor: pointer; }
.chart-card { margin: 0; }

.chart-gallery h3 { margin: 0 0 4px; font-size: 1rem; }
.chart-host.usage-combo { min-height: 380px; }
.chart-host.scatter-wide { min-height: 300px; }
.usage-stats { margin-top: 16px; }
.usage-stats h3 { margin: 0 0 4px; font-size: 1rem; font-weight: 600; }
.usage-stats .stats-meta { margin: 0 0 10px; }
.usage-summary-wrap {
  width: 100%;
  max-width: 1100px;
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
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
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
details.sync-gaps-panel > summary,
details.chart-gallery > summary,
details.tariff-status-block > summary,
details.diagnostics > summary,
details.tod-holidays > summary,
details.tod-compare-math > summary {
  cursor: pointer;
  display: grid;
  grid-template-columns: 20px 1fr;
  column-gap: 6px;
  align-items: start;
  position: relative;
  list-style: none;
  padding: 10px 12px;
  margin: 0 0 8px;
  color: var(--primary-text-color);
  border-radius: 8px;
}
details.usage-accounting > summary::-webkit-details-marker,
details.usage-rollup > summary::-webkit-details-marker,
details.sync-gaps-panel > summary::-webkit-details-marker,
details.chart-gallery > summary::-webkit-details-marker,
details.tariff-status-block > summary::-webkit-details-marker,
details.diagnostics > summary::-webkit-details-marker,
details.tod-holidays > summary::-webkit-details-marker,
details.tod-compare-math > summary::-webkit-details-marker { display: none; }
details.usage-accounting > summary::marker,
details.usage-rollup > summary::marker,
details.sync-gaps-panel > summary::marker,
details.chart-gallery > summary::marker,
details.tariff-status-block > summary::marker,
details.diagnostics > summary::marker,
details.tod-holidays > summary::marker,
details.tod-compare-math > summary::marker { content: ""; }
details.usage-accounting > summary::before,
details.usage-rollup > summary::before,
details.sync-gaps-panel > summary::before,
details.chart-gallery > summary::before,
details.tariff-status-block > summary::before,
details.diagnostics > summary::before,
details.tod-holidays > summary::before,
details.tod-compare-math > summary::before {
  content: "›";
  position: static;
  font-size: 1.2rem;
  line-height: 1;
  color: var(--secondary-text-color);
  transition: transform var(--pge-dur-fast);
}
details.usage-accounting[open] > summary::before,
details.usage-rollup[open] > summary::before,
details.sync-gaps-panel[open] > summary::before,
details.chart-gallery[open] > summary::before,
details.tariff-status-block[open] > summary::before,
details.diagnostics[open] > summary::before,
details.tod-holidays[open] > summary::before,
details.tod-compare-math[open] > summary::before { content: "›"; transform: rotate(90deg); }
details.usage-accounting > summary:hover,
details.usage-rollup > summary:hover,
details.sync-gaps-panel > summary:hover,
details.chart-gallery > summary:hover,
details.tariff-status-block > summary:hover,
details.diagnostics > summary:hover {
  color: var(--primary-color);
  background: color-mix(
    in srgb,
    var(--primary-color, #2a78d6) 8%,
    var(--card-background-color, var(--primary-background-color, transparent))
  );
}
details.usage-accounting > summary:hover::before,
details.usage-rollup > summary:hover::before,
details.sync-gaps-panel > summary:hover::before,
details.chart-gallery > summary:hover::before,
details.tariff-status-block > summary:hover::before,
details.diagnostics > summary:hover::before { color: var(--primary-color); }
.rollup-title {
  display: block;
  font-weight: 650;
  font-size: 1.05rem;
  line-height: 1.3;
}
details.usage-accounting > summary .rollup-title,
details.chart-gallery > summary .rollup-title,
details.tariff-status-block > summary .rollup-title,
details.diagnostics > summary .rollup-title { font-size: 1.1rem; }
details.tariff-status-block > summary .badge { margin-left: 8px; vertical-align: middle; }
.rollup-caption {
  display: block;
  grid-column: 2;
  margin-top: 4px;
  font-weight: 400;
  font-size: 0.82rem;
  line-height: 1.35;
  color: var(--secondary-text-color);
}
details.usage-accounting .usage-accounting-body { padding: 0 0 4px; }
.insights-cost-grid { display: block; }
#ledger-bill, #ledger-kwh { min-height: 240px; }
.chart-empty { margin: 12px 0; font-size: 0.85rem; }
.data-gaps ul { margin: 0; padding-left: 1.2rem; display: grid; gap: 6px; }
.data-gaps li { font-size: 0.9rem; color: var(--primary-text-color); }
.data-gaps .gap-ok { color: var(--pge-status-good); }
.data-gaps .gap-warn { color: var(--pge-status-warn); }
.data-gaps .muted { margin: 0 0 8px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
#insights-heat { display: grid; gap: 16px; }
@container pge (min-width: 1101px) {
  #insights-heat { grid-template-columns: 1fr 1fr; }
  #insights-heat > .heatmap-chips { grid-column: 1 / -1; }
}
.entities { display: grid; gap: 6px; }
.entity-row { display: flex; justify-content: space-between; gap: 12px; padding: 6px 0;
  border-bottom: 1px solid var(--divider-color); font-size: 0.95rem; }
.programs { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr)); gap: 10px; }
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
.pge-heatmap-title { font-size: 0.9rem; margin-bottom: 8px; color: var(--secondary-text-color); }
.pge-heatmap-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(10px, 1fr)); gap: 2px;
}
.pge-heatmap-cell { aspect-ratio: 1; border-radius: 2px; }
.muted { color: var(--secondary-text-color); font-size: 0.85rem; }
.error { color: var(--error-color, var(--pge-status-critical)); }
.entity-row span { color: var(--secondary-text-color); }
.entity-row strong { color: var(--primary-text-color); }

/* Layout follows the panel width, not the browser window. The sidebar
   changes how wide .content is. */
@container pge (max-width: 1100px) {
  .range-tools { width: 100%; justify-content: flex-start; }
  .stepper { flex: 1 1 16rem; min-width: 0; }
  .filters .range-label { max-width: 100%; }
  .insights-cost-grid,
  .grid-2 { grid-template-columns: 1fr; }
}
@container pge (max-width: 720px) {
  .section-tabs [role="tab"] span { display: none; }
}
@container pge (max-width: 560px) {
  .sync-pill-wrap {
    flex: 0 0 28px;
    width: 28px;
    height: 28px;
    margin-left: 4px;
  }
  .sync-pill {
    display: block;
    width: 28px;
    height: 28px;
    min-width: 28px;
    padding: 0;
    overflow: hidden;
    border-radius: 50%;
  }
  .sync-pill.good {
    background: var(--pge-status-good);
    border-color: var(--pge-status-good);
  }
  .sync-pill.warn {
    background: var(--pge-status-warn);
    border-color: var(--pge-status-warn);
  }
  .sync-pill.critical {
    background: var(--pge-status-critical);
    border-color: var(--pge-status-critical);
  }
  .sync-pill::before { display: none; }
  .sync-pill-text {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
  }
}
@container pge (max-width: 640px) {
  .fig-head { align-items: flex-start; }
  .tod-compare-verdict { font-size: 1.15rem; }
  .tod-grid {
    grid-template-columns: 36px repeat(24, minmax(0, 1fr));
    gap: 1px;
  }
  .tod-cell { min-width: 0; }
  .tod-day-full { display: none; }
  .tod-day-short { display: inline; }
  .tod-hour:not(:nth-child(3n + 2)) { visibility: hidden; }
  .tariff-status-block .tod-table th:last-child,
  .tariff-status-block .tod-table td:last-child { display: none; }
  .tod-usage .tod-table th:nth-child(5),
  .tod-usage .tod-table td:nth-child(5) { display: none; }
  details.tod-compare-math .tod-table thead { display: none; }
  details.tod-compare-math .tod-table,
  details.tod-compare-math .tod-table tbody,
  details.tod-compare-math .tod-table tr,
  details.tod-compare-math .tod-table td {
    display: block;
    width: auto;
  }
  details.tod-compare-math .tod-table tr {
    padding: 8px 0;
    border-bottom: 1px solid var(--divider-color);
  }
  details.tod-compare-math .tod-table td.num {
    display: inline;
    text-align: left;
  }
  details.tod-compare-math .tod-table td.num + td.num::before { content: " · "; }
  .seg.range-presets {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    width: 100%;
    overflow: visible;
    border-radius: 16px;
    gap: 2px;
  }
  .seg.range-presets button {
    width: 100%;
    min-width: 0;
    padding: 4px 6px;
    justify-self: stretch;
  }
  .range-row { width: 100%; min-width: 0; max-width: 100%; }
  .range-tools {
    width: 100%;
    max-width: 100%;
    flex-wrap: wrap;
  }
  .range-tools .stepper {
    flex: 1 1 100%;
    width: 100%;
    min-width: 0;
    max-width: 100%;
  }
  .filters .seg.interval { width: auto; flex: 0 0 auto; }
  .filters .seg.interval button { padding: 4px 8px; }
  .filters .range-custom-toggle {
    flex: 0 0 34px;
    width: 34px;
    height: 34px;
    padding: 0;
  }
  .filters select.range-more {
    min-width: 5.5rem;
    max-width: 100%;
  }
  .filters .range-label { flex: 1 1 auto; min-width: 0; text-align: center; max-width: none; }
  .filters .range-custom {
    display: grid;
    grid-template-columns: 1fr;
    border-radius: 16px;
  }
  .filters .range-custom input[type="datetime-local"],
  .filters .range-custom button { width: 100%; }
  .usage-summary-items { grid-template-columns: 1fr; }
  .usage-summary-item { border-right: 0; }
  .usage-summary-item:nth-child(2n) { border-right: 0; }
  .usage-summary-items > .usage-summary-item:nth-last-child(-n+2) {
    border-bottom: 1px solid var(--divider-color);
  }
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
  .usage-summary-item .note { display: none; }
}

/* Tablet window: tighter page padding. Column counts use the container rules above. */
@media (max-width: 900px) {
  .content { padding: 12px; }
  .card { padding: var(--pge-space-6); margin-bottom: var(--pge-space-6); }
}

/* Phone: larger touch targets. Column counts follow the container rules. */
@media (max-width: 640px) {
  .kpi-grid { gap: var(--pge-space-3); }
  .section-tab-scroll { overflow-x: auto; scrollbar-width: none; }
  .hdr-row { gap: 8px; }
  .toolbar { padding: 6px 10px; gap: 8px; }
  .content { padding: 12px; }
  .card { padding: 16px; border-radius: 10px; }
  .card h2, .card h3 { font-size: 1.05rem; }
  .kpi { padding: 10px; }
  .kpi .value { font-size: 1.15rem; }
  .sync-row { gap: 8px; }
  .sync-row progress { min-width: 0; width: 100%; flex: 1 1 100%; }
  .sync-row .btn { flex: 1 1 calc(50% - 4px); min-height: 44px; }
  .btn { min-height: 40px; padding: 10px 14px; }
  .filters { gap: 6px; }
  .filters .stepper button { flex: 0 0 34px; width: 34px; }
  .usage-table-wrap {
    max-height: min(60vh, 420px);
    -webkit-overflow-scrolling: touch;
  }
  .usage-day-table {
    font-size: 0.8rem;
    table-layout: fixed;
  }
  .usage-day-table th:nth-child(4),
  .usage-day-table td:nth-child(4),
  .usage-day-table th:nth-child(5),
  .usage-day-table td:nth-child(5) { display: none; }
  .usage-day-table th:nth-child(1),
  .usage-day-table td:nth-child(1) { width: 40%; }
  .usage-day-table th:nth-child(2),
  .usage-day-table td:nth-child(2),
  .usage-day-table th:nth-child(3),
  .usage-day-table td:nth-child(3) { width: 30%; }
  .usage-day-table th, .usage-day-table td { padding: 8px 8px; }
  .program { padding: 10px; min-height: 64px; }
  details.usage-accounting > summary,
  details.usage-rollup > summary,
  details.sync-gaps-panel > summary,
  details.chart-gallery > summary,
  details.tariff-status-block > summary,
  details.diagnostics > summary {
    padding: 10px 12px;
    min-height: 44px;
  }
  .rollup-caption { font-size: 0.78rem; }
  .entity-row { flex-wrap: wrap; gap: 4px 12px; }
}

  /* ---- Bill PDF ---- */
  .bill-pdf-header .button {
    display: inline-flex; align-items: center; gap: 5px;
    padding: 6px 14px; border-radius: 8px;
    border: 1px solid var(--primary-color);
    color: var(--primary-color);
    background: transparent;
    font-size: 0.85rem; font-weight: 600;
    text-decoration: none;
    cursor: pointer;
    transition:
      background 180ms ease,
      box-shadow 180ms ease;
  }
  .bill-pdf-header .button::after { content: "↗"; font-size: 0.9em; opacity: 0.75; }
  .bill-pdf-header .button:hover,
  .bill-pdf-header .button:focus-visible {
    background: color-mix(in srgb, var(--primary-color) 12%, transparent);
    box-shadow: 0 2px 8px color-mix(in srgb, var(--primary-text-color) 10%, transparent);
  }
  .bill-pdf-header .button:active {
    background: color-mix(in srgb, var(--primary-color) 22%, transparent);
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
.tod-day-short { display: none; }
@container pge (max-width: 640px) {
  .tod-grid {
    grid-template-columns: 36px repeat(24, minmax(0, 1fr));
    gap: 1px;
  }
  .tod-cell { min-width: 0; }
  .tod-day-full { display: none; }
  .tod-day-short { display: inline; }
  .tod-hour:not(:nth-child(3n + 2)) { visibility: hidden; }
}
  .tod-cell.now {
    outline: 2px solid var(--primary-text-color);
    outline-offset: -2px;
    box-shadow: 0 0 0 1px var(--card-background-color, var(--primary-background-color));
  }
  details.tod-holidays { margin-top: 8px; }
  details.tod-holidays > summary { cursor: pointer; font-size: 0.85rem; color: var(--secondary-text-color); }
  .tod-holidays-body { margin-top: 6px; padding-left: 4px; font-size: 0.82rem; }
  .view-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chapter:not(.card) {
  margin-top: var(--pge-space-8);
  padding-top: var(--pge-space-6);
  border-top: 1px solid var(--pge-border);
}
.chapter-head { margin-bottom: var(--pge-space-4); }
.chapter-head .eyebrow { display: inline-flex; align-items: center; gap: 6px; }
.chapter-headline { font: var(--pge-text-headline); margin: 4px 0 0; }
.chapter-headline, .fig-title { overflow-wrap: break-word; }
.chapter .chart-card + .chart-card,
.chapter-views > * + * { margin-top: var(--pge-space-6); }
section.chapter.explore-more {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 520px), 1fr));
  gap: var(--pge-space-6);
}
section.chapter.explore-more > header.chapter-head,
section.chapter.explore-more > .fig-wide { grid-column: 1 / -1; }
.tod-schedule, .tod-usage { max-width: 100%; min-width: 0; }
.tod-usage { overflow-x: auto; margin-top: 16px; }
.chapter-lead .fig-title { display: none; }
.shift-form {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
  margin: 8px 0 12px;
}
.shift-form label {
  display: grid;
  gap: 4px;
  font-size: 0.78rem;
  color: var(--secondary-text-color);
}
.shift-form input,
.shift-form select { width: 100%; min-width: 0; }
@container pge (min-width: 720px) {
  .shift-form { grid-template-columns: 1.4fr repeat(3, minmax(0, 1fr)); align-items: end; }
}
.tod-compare-math,
.tod-table-wrap { max-width: 100%; overflow-x: auto; }
.tod-table { width: 100%; min-width: 0; }
.tod-compare-verdict { overflow-wrap: anywhere; }
  .tod-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; margin-top: 10px; }
  .tod-table th, .tod-table td { padding: 6px 8px; text-align: left; border-bottom: 1px solid var(--divider-color); }
  .tod-table .num { text-align: right; white-space: nowrap; }
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
  .tod-range .range-row {
    flex-wrap: nowrap;
    align-items: center;
  }
  .tod-range .seg.range-presets {
    display: inline-flex;
    flex: 1 1 auto;
    width: auto;
    min-width: 0;
    overflow-x: auto;
    grid-template-columns: none;
    border-radius: 999px;
  }
  .tod-range .seg.range-presets button {
    width: auto;
    flex: 0 0 auto;
  }
  .tod-range .range-tools {
    width: auto;
    max-width: none;
    flex: 0 0 auto;
    flex-wrap: nowrap;
    min-width: 0;
  }
  .tod-range .range-label { display: none; }
  details.tariff-status-block { margin-top: 20px; }
`;

/** Daily calendars read every retained day, not the Usage chip. */
const HEATMAP_HISTORY_START = new Date(Date.UTC(2000, 0, 1));
/** Above any realistic daily backfill so LTTB cannot drop calendar days. */
const HEATMAP_MAX_DAYS = 20000;

class PgeEnergyPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._accounts = [];
    this._activeEntryId = null;
    this._activeTab = "glance";
    this._rangeRenderGen = 0;
    this._syncByEntry = {};
    this._syncObserved = {};
    this._bootRendering = false;
    this._galleryRefreshAfterBoot = false;
    this._chartFactories = new Map();
    this._pendingMounts = new Map();
    this._lazyObserver = typeof IntersectionObserver === "function"
      ? new IntersectionObserver((entries) => {
          for (const entry of entries) {
            if (!entry.isIntersecting) continue;
            const record = this._pendingMounts.get(entry.target);
            this._lazyObserver.unobserve(entry.target);
            this._pendingMounts.delete(entry.target);
            if (record) void this._mountDeferred(record);
          }
        }, { rootMargin: "200px 0px" })
      : null;
    this._unsubSync = null;
    this._charts = [];
    this._rangeKey = "24h";
    this._usageMetric = "kwh";
    try {
      const stored = localStorage.getItem("pge_usage_metric");
      if (stored === "kwh" || stored === "cost") this._usageMetric = stored;
    } catch (_err) {
      /* storage can be unavailable */
    }
    this._rangeShift = 0;
    this._customRange = null;
    this._rangeCustomOpen = false;
    this._todRangeKey = "last_cycle";
    this._todRangeCustomOpen = false;
    this._todCustomRange = null;
    this._todRangeTouched = false;
    this._todBillReady = false;
    this._todRenderGen = 0;
    this._galleryRenderGen = 0;
    this._availablePresets = null;
    this._period = "hour";
    this._loading = true;
    this._error = null;
    this._narrow = false;
    this._defaultSection = "glance";
    this._landingApplied = false;
    this._presetProbeGen = 0;
    this._presetProbeTimer = null;
    this._presetProbeSkipped = false;
    this._filtersDirty = false;
    this._todDirty = false;
    this._kpiSig = "";
    this._billingSummarySig = "";
    this._billingPdfHeaderSig = "";
    this._billingPdfDetailsSig = "";
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    const themeChanged = applyPanelTheme(this, hass);
    if (first) {
      this._boot();
    } else if (!this._loading && this._account) {
      void this._renderKpis();
      const billingRebuilt = this._renderBillingPrograms();
      this._renderSync();
      this._renderDiagnostics();
      // Bill bounds can arrive after the first paint. Replacing the range
      // selects on every hass push closes an open menu and jumps it to the top.
      const billReady = !!this._billBounds();
      if (billReady !== this._todBillReady) {
        this._todBillReady = billReady;
        if (this._hostFocused("tod")) this._todDirty = true;
        else void this._renderTod();
      }
      this._schedulePresetProbe();
      // Theme / dark-mode switches require chart option rebuild (canvas colors).
      if (themeChanged) {
        void this._rebuildThemeCharts();
      } else if (billingRebuilt) {
        void this._mountAccountGalleries();
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
    if (this._presetProbeTimer) {
      clearTimeout(this._presetProbeTimer);
      this._presetProbeTimer = null;
    }
    if (this._onHintOutside) {
      document.removeEventListener("click", this._onHintOutside);
      this._onHintOutside = null;
    }
    if (this._onSyncPopOutside) {
      document.removeEventListener("click", this._onSyncPopOutside);
      this._onSyncPopOutside = null;
    }
    if (this._unsubSync) {
      this._unsubSync();
      this._unsubSync = null;
    }
    if (this._onPanelHashChange) {
      window.removeEventListener("hashchange", this._onPanelHashChange);
      this._onPanelHashChange = null;
    }
    this._headerObserver?.disconnect();
    this._headerObserver = null;
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
          let refreshGalleries = false;
          for (const entry of msg.entries || []) {
            const prior = this._syncByEntry[entry.entry_id];
            const seen = !!this._syncObserved[entry.entry_id];
            this._syncByEntry[entry.entry_id] = entry;
            this._syncObserved[entry.entry_id] = true;
            const finished =
              entry.status === "complete" &&
              (prior?.status !== "complete" ||
                entry.last_successful_update !== prior?.last_successful_update);
            if (seen && entry.entry_id === this._activeEntryId && finished) {
              refreshGalleries = true;
            }
          }
          invalidateStatsCache();
          this._renderSync();
          this._renderDiagnostics();
          void this._renderDataGaps();
          if (!refreshGalleries) return;
          if (this._bootRendering) {
            this._galleryRefreshAfterBoot = true;
            return;
          }
          void this._refreshGalleriesAfterSync();
        },
        { type: "pge_energy/sync/subscribe" }
      );
      this._loading = false;
      this._error = null;
      this._renderShell();
      this._bootRendering = true;
      try {
        await this._renderAll();
      } finally {
        this._bootRendering = false;
      }
      if (this._galleryRefreshAfterBoot) {
        this._galleryRefreshAfterBoot = false;
        await this._refreshGalleriesAfterSync();
      }
      this._scheduleDefaultLandingScroll();
    } catch (err) {
      this._loading = false;
      this._error = err?.message || String(err);
      this._renderShell();
    }
  }

  _bindPanelNavigation() {
    const nav = this.shadowRoot.querySelector("[role=tablist]");
    if (!nav || nav.dataset.bound === "1") return;
    nav.dataset.bound = "1";
    nav.addEventListener("click", (ev) => {
      const button = ev.target.closest("[role=tab]");
      if (button) this._selectPanelTab(button.dataset.tab, { writeHistory: true });
    });
    nav.addEventListener("keydown", (ev) => {
      const button = ev.target.closest("[role=tab]");
      if (!button) return;
      const index = PANEL_TABS.indexOf(button.dataset.tab);
      const keyIndex = {
        ArrowLeft: (index + PANEL_TABS.length - 1) % PANEL_TABS.length,
        ArrowRight: (index + 1) % PANEL_TABS.length,
        Home: 0,
        End: PANEL_TABS.length - 1,
      }[ev.key];
      if (keyIndex == null) return;
      ev.preventDefault();
      this._selectPanelTab(PANEL_TABS[keyIndex], { writeHistory: true, focus: true });
    });
    if (this._onPanelHashChange) window.removeEventListener("hashchange", this._onPanelHashChange);
    this._onPanelHashChange = () => this._selectPanelTab(resolvePanelTab(location.hash, this._defaultSection));
    window.addEventListener("hashchange", this._onPanelHashChange);
  }

  _selectPanelTab(tab, { writeHistory = false, focus = false } = {}) {
    if (!PANEL_TABS.includes(tab)) return;
    this._activeTab = tab;
    for (const button of this.shadowRoot.querySelectorAll(".section-tabs [role=tab]")) {
      const active = button.dataset.tab === tab;
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
      if (active && focus) button.focus();
    }
    this._attachRangeBar(tab);
    for (const panel of this.shadowRoot.querySelectorAll(".tab-panel")) {
      panel.hidden = panel.dataset.tab !== tab;
    }
    if (writeHistory && location.hash !== panelTabHash(tab)) history.pushState(null, "", panelTabHash(tab));
    const panel = this.shadowRoot.getElementById("panel-" + tab);
    requestAnimationFrame(() => this._resizeChartsUnder(panel));
  }

  _attachRangeBar(tab) {
    const range = this.shadowRoot.querySelector(".hdr-range");
    if (!range) return;
    const slot = this.shadowRoot.getElementById("hero")?.querySelector(":scope > .usage-range");
    if (slot && range.parentElement !== slot) slot.appendChild(range);
    // Usage owns this bar. Overview is a fixed last-complete-24h chart.
    range.hidden = tab !== "usage";
  }

  _resizeChartsUnder(root) {
    for (const wrapper of this._charts || []) {
      const dom = wrapper.chart?.getDom?.();
      if (dom && root?.contains(dom)) wrapper.chart.resize();
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

    const accountControl =
      this._accounts.length > 1
        ? `<label>Account <select id="account-select">${this._accounts
            .map(
              (account) =>
                `<option value="${this._escape(account.entry_id)}" ${
                  account.entry_id === this._activeEntryId ? "selected" : ""
                }>${this._escape(account.title || account.account_id)}</option>`,
            )
            .join("")}</select></label>`
        : "";
    const tabButtons = PANEL_TABS.map(
      (tab) => `<button type="button" role="tab" id="tab-${tab}" data-tab="${tab}" aria-controls="panel-${tab}"
        aria-selected="${tab === this._activeTab}" tabindex="${tab === this._activeTab ? 0 : -1}"
        aria-label="${PANEL_TAB_LABELS[tab]}"><ha-icon icon="${PANEL_TAB_ICONS[tab]}"></ha-icon>
        <span>${PANEL_TAB_LABELS[tab]}</span></button>`,
    ).join("");

    content.innerHTML = `
      <div class="panel-chrome">
      <header class="pge-header">
        ${accountControl ? `<div class="hdr-row">${accountControl}</div>` : ""}
        <div class="section-tabs">
          <nav class="section-tab-scroll" role="tablist" aria-label="PGE sections">${tabButtons}</nav>
          <div class="sync-pill-wrap">
            <button type="button" class="sync-pill" id="sync-pill" aria-haspopup="dialog" aria-controls="sync-pop" aria-expanded="false" aria-label="Sync status"><span class="sync-pill-text">Sync status</span></button>
            <div id="sync-pop" class="sync-pop" role="dialog" aria-label="Last sync"></div>
          </div>
        </div>
      </header>
      </div>
      <div class="tab-panel" id="panel-glance" data-tab="glance" role="tabpanel" aria-labelledby="tab-glance">
        <section class="card story-band" id="story" data-story="overview"></section>
        <section class="card" id="kpis"></section>
        <section class="card panel-usage" id="overview-usage-card">
          <h2>Last 24 hours</h2>
          <div class="chart-host usage-combo" id="chart-overview-usage"></div>
        </section>
      </div>
      <div class="tab-panel" id="panel-usage" data-tab="usage" role="tabpanel" aria-labelledby="tab-usage">
      <section class="card panel-usage" id="hero">
        <div class="usage-head">
        <h2>Usage ${this._hint("A kilowatt-hour is the energy of using 1,000 watts for one hour.")}</h2>
        <div class="metric-toggle" role="group" aria-label="Usage metric">
          <button type="button" data-metric="kwh" aria-pressed="${this._usageMetric === "kwh"}">kWh</button>
          <button type="button" data-metric="cost" aria-pressed="${this._usageMetric === "cost"}">Dollars</button>
        </div>
        </div>
        <div class="usage-range"><div class="hdr-range filters" id="filters"></div></div>
        <div class="chart-host usage-combo" id="chart-usage"></div>
        <div class="usage-stats" id="usage-stats"></div>
      </section>
        ${this._loadShapeGalleryHtml()}
      </div>
      <div class="tab-panel" id="panel-analytics" data-tab="analytics" role="tabpanel" aria-labelledby="tab-analytics">
      <section class="card" id="insights-weather">
        <h3>Weather vs usage ${this._hint("Daily kWh vs outdoor °F, using days that have both samples.")}</h3>
        <div class="chart-host scatter-wide" id="scatter"></div>
        ${this._weatherGalleryHtml()}
      </section>
      <section class="card" id="insights-cost">
        <h3>Cost intelligence ${this._hint("Monthly average rate, and statement billed versus payments, for the last 12 months.")}</h3>
        <div class="insights-cost-grid">
          <div class="chart-host" id="cost-per-kwh"></div>
        </div>
      </section>
      <section class="card" id="insights-heat">
        <div class="heatmap-chips" id="heatmap-chips"></div>
        <div class="heatmap-pair">
          <h4>kWh calendar ${this._hint("Gray cells are days without an imported sample in recorder. They are not a full calendar year of PGE data.")}</h4>
          <div class="heatmap-scroll"><div class="chart-host" id="heatmap-kwh"></div></div>
        </div>
        <div class="heatmap-pair">
          <h4>Temperature calendar</h4>
          <div class="heatmap-scroll"><div class="chart-host" id="heatmap-temp"></div></div>
        </div>
      </section>
      <section class="card chapter explore-more" data-chapter="explore" data-section="more-charts" data-persist="chart_gallery_more"${this._detailsOpenAttr("chart_gallery_more")}>
        <header class="chapter-head"><span class="eyebrow">Explore more</span><h2 class="chapter-headline">More ways to look at your history</h2></header>
        ${this._figure("chart-fingerprint", { eyebrow: "Day fingerprint", title: "Day fingerprint", what: "Each line is a day: energy, peak hour, temperature, on-peak share, and price.", how: "Lines that sit apart from the pack were unusual days.", why: "It shows which days were odd without opening each one.", source: "Imported hourly consumption, cost, and temperature." })}
        ${this._figure("chart-ridgelines", { eyebrow: "Monthly ridgelines", title: "Monthly ridgelines", what: "Average hourly use for each month, stacked.", how: "Each ridge is one month. Higher means more use at that hour.", why: "You can see how the day shifts across the year.", source: "Imported hourly consumption." })}
        ${this._figure("chart-daypart-stream", { eyebrow: "Daypart stream", title: "Daypart stream", what: "How your use splits across parts of the day over time.", how: "The bands are overnight, morning, afternoon, and evening.", why: "A band that grows is a part of the day that is taking more of your energy.", source: "Imported hourly consumption." })}
        ${this._figure("chart-published-week", { eyebrow: "Published week", title: "Published week", what: "Each day of the last full week, hour by hour.", how: "Compare the days side by side.", why: "Last week is the freshest complete week PGE has published.", source: "Imported hourly consumption for the latest closed Pacific week." })}
        ${this._figure("chart-program-savings", { eyebrow: "Program savings", title: "Program savings", what: "Year-to-date savings reported by PGE programs.", how: "The line is the reported year-to-date amount, not a sum of bills.", why: "It is the savings figure PGE publishes, separate from your usage estimate.", source: "YTD program savings mean." })}
        ${this._figure("chart-baseload", { eyebrow: "Baseload band", title: "Baseload band", what: "Weekday average by hour with your overnight minimum as a line.", how: "The line is the lowest overnight hour in the weekday average.", why: "Anything above that line is use that turns on and off.", source: "Imported hourly consumption." })}
        ${this._figure("chart-polar", { eyebrow: "24-hour polar clock", title: "24-hour polar clock", what: "Average weekday use around a 24-hour dial.", how: "Noon is at the top. Longer bars are hours you use more.", why: "A clock makes the daily rhythm easier to see than a list of hours.", source: "Imported hourly consumption." })}
        ${this._figure("chart-treemap", { eyebrow: "Latest statement treemap", title: "Latest statement treemap", what: "Each block's size is that charge's share of the latest bill.", how: "Bigger blocks are a larger share of the latest statement.", why: "You can see what dominated the last bill without reading every line.", source: "Latest PDF statement families." })}
      </section>
      </div>
      <div class="tab-panel" id="panel-billing" data-tab="billing" role="tabpanel" aria-labelledby="tab-billing">
      <div id="billing"></div>
      </div>
      <div class="tab-panel" id="panel-tod" data-tab="tod" role="tabpanel" aria-labelledby="tab-tod">
      <div id="tod"></div>
      </div>
      <div class="tab-panel" id="panel-programs" data-tab="programs" role="tabpanel" aria-labelledby="tab-programs">
      <section class="card" id="programs"></section>
      </div>
      <dialog id="chart-dialog" class="chart-dialog" aria-labelledby="chart-dialog-title">
        <header><h2 id="chart-dialog-title"></h2>
          <button type="button" id="chart-dialog-close" aria-label="Close chart">×</button>
        </header>
        <figure>
          <h3 class="fig-title" id="chart-dialog-figure-title"></h3>
          <div id="chart-dialog-explainer"></div>
          <div class="chart-host" id="chart-dialog-host" data-chart-height="560"></div>
        </figure>
      </dialog>
      <dialog id="sync-drawer" class="drawer" aria-labelledby="sync-drawer-title">
        <div class="drawer-head"><h2 id="sync-drawer-title">Sync and diagnostics</h2>
          <button type="button" class="drawer-close" aria-label="Close">×</button></div>
        <div class="sync-strip" id="sync"></div>
        <div class="data-gaps" id="data-gaps"></div>
        <h3>Diagnostics</h3>
        <div id="diag-body"></div>
      </dialog>
    `;

    content.querySelector("#account-select")?.addEventListener("change", async (ev) => {
      this._activeEntryId = ev.target.value;
      this._renderShell();
      await this._renderAll();
    });
    content.addEventListener("click", (ev) => {
      const view = ev.target.closest?.("[data-view]");
      if (view) {
        this._selectChapterView(view.closest(".chapter"), view.dataset.view);
        return;
      }
      const button = ev.target.closest?.("[data-expand], button.explore-card");
      if (!button || button.disabled) return;
      const id = button.dataset.expand || button.dataset.chart;
      if (!id) return;
      void openChartDialog(this, id, button);
    });
    content.querySelector("#chart-dialog")?.addEventListener("cancel", (ev) => {
      ev.preventDefault();
      suspendChartDialog(this, { keepOpen: false });
    });
    content.querySelector("#chart-dialog-close")?.addEventListener("click", () => {
      suspendChartDialog(this, { keepOpen: false });
    });
    this._bindPanelNavigation();
    this._bindHints();
    this._bindSyncPill();
    this._observeHeaderHeight();
    this._bindFilterInteractionGuard();
    this._bindTodInteractionGuard();
    this._selectPanelTab(resolvePanelTab(location.hash, this._defaultSection));
    content.querySelector(".drawer-close")?.addEventListener("click", () => {
      this.shadowRoot.getElementById("sync-drawer")?.close();
    });
    content.querySelectorAll("[data-metric]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const metric = btn.dataset.metric === "cost" ? "cost" : "kwh";
        this._usageMetric = metric;
        try {
          localStorage.setItem("pge_usage_metric", metric);
        } catch (_err) {
          /* storage can be unavailable */
        }
        content.querySelectorAll("[data-metric]").forEach((peer) => {
          peer.setAttribute("aria-pressed", String(peer === btn));
        });
        await this._renderRangeScope();
      });
    });
    this._bindPersistentDetails(content.querySelector("#hero"));
    this._bindPersistentDetails(content.querySelector("#panel-analytics"));
  }

  async _softGallery(fn) {
    try {
      await fn();
    } catch (err) {
      console.warn("PGE gallery render failed", err);
    }
  }

  async _renderAll() {
    const gen = ++this._galleryRenderGen;
    const entryId = this._activeEntryId;
    const stale = () => this._galleryRenderGen !== gen || this._activeEntryId !== entryId;
    destroyCharts(this._charts);
    this._charts = [];
    this._galleryDays = null;
    this._galleryBillAmount = null;
    const presetsApplied = await this._probeAvailablePresets();
    if (stale()) return;
    this._todBillReady = !!this._billBounds();
    if (presetsApplied || this._availablePresets) this._renderFilters();
    this._renderSync();
    await this._renderKpis();
    if (stale()) return;
    await this._renderDataGaps();
    if (stale()) return;
    await this._renderHero();
    if (stale()) return;
    await this._softGallery(() => this._renderLoadShapeGallery());
    if (stale()) return;
    await this._softGallery(() => this._renderInsights());
    if (stale()) return;
    await this._renderTod();
    if (stale()) return;
    this._renderBillingPrograms(true);
    if (stale()) return;
    await this._softGallery(() => this._renderLedgerCharts());
    if (stale()) return;
    await this._softGallery(() => this._renderWeatherMoney());
    if (stale()) return;
    this._renderDiagnostics();
  }

  async _mountAccountGalleries() {
    const gen = this._galleryRenderGen || 0;
    const entryId = this._activeEntryId;
    const stale = () => this._galleryRenderGen !== gen || this._activeEntryId !== entryId;
    await this._softGallery(() => this._renderLedgerCharts());
    if (stale()) return;
    await this._softGallery(() => this._renderWeatherMoney());
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
    this._todRangeCustomOpen = false;
    this._todRangeTouched = true;
  }

  _observeHeaderHeight() {
    const chrome = this.shadowRoot?.querySelector(".panel-chrome");
    const header = chrome?.querySelector(".pge-header");
    if (!chrome || !header) return;
    this._headerObserver?.disconnect();
    chrome.dataset.heightWatch = "1";
    const apply = () => {
      const narrow = chrome.getBoundingClientRect().width <= 640;
      const box = (narrow ? header : chrome).getBoundingClientRect();
      this.style.setProperty("--pge-header-h", `${Math.ceil(box.height)}px`);
    };
    apply();
    if (typeof ResizeObserver === "function") {
      this._headerObserver = new ResizeObserver(apply);
      this._headerObserver.observe(chrome);
      this._headerObserver.observe(header);
    }
  }

  _hostFocused(id) {
    const active = this.shadowRoot?.activeElement;
    const host = this.shadowRoot?.getElementById(id);
    return !!(active && host && host.contains(active));
  }

  _filterControlFocused() {
    return this._hostFocused("filters");
  }

  _bindTodInteractionGuard() {
    const el = this.shadowRoot?.getElementById("tod");
    if (!el || el.dataset.focusGuard === "1") return;
    el.dataset.focusGuard = "1";
    el.addEventListener("focusout", () => {
      setTimeout(() => {
        if (this._hostFocused("tod") || !this._todDirty) return;
        this._todDirty = false;
        void this._renderTod();
      }, 0);
    });
  }

  _bindFilterInteractionGuard() {
    const el = this.shadowRoot?.getElementById("filters");
    if (!el || el.dataset.focusGuard === "1") return;
    el.dataset.focusGuard = "1";
    el.addEventListener("focusout", () => {
      // Let the click that moved focus finish before replacing the controls.
      setTimeout(() => {
        if (this._filterControlFocused()) return;
        const dirty = this._filtersDirty;
        const skipped = this._presetProbeSkipped;
        this._filtersDirty = false;
        this._presetProbeSkipped = false;
        if (dirty) this._renderFilters();
        if (skipped) this._schedulePresetProbe();
      }, 0);
    });
  }

  _schedulePresetProbe() {
    if (this._filterControlFocused()) {
      this._presetProbeSkipped = true;
      return;
    }
    if (this._presetProbeTimer) clearTimeout(this._presetProbeTimer);
    this._presetProbeTimer = setTimeout(() => {
      this._presetProbeTimer = null;
      void this._refreshPresetFilters();
    }, 300);
  }

  async _refreshPresetFilters() {
    if (this._filterControlFocused()) {
      this._presetProbeSkipped = true;
      return;
    }
    const previousPresets = this._availablePresets ? [...this._availablePresets] : null;
    const previousKey = this._normalizeRangeKey(this._rangeKey);
    const applied = await this._probeAvailablePresets();
    if (!applied) {
      if (this._filterControlFocused()) this._filtersDirty = true;
      return;
    }
    const effect = presetProbeEffect({
      previousPresets,
      nextPresets: this._availablePresets,
      previousKey,
      nextKey: this._normalizeRangeKey(this._rangeKey),
      filterFocused: this._filterControlFocused(),
    });
    if (effect === "defer") {
      this._filtersDirty = true;
      return;
    }
    if (effect === "rebuild") this._renderFilters();
  }

  async _probeAvailablePresets() {
    const gen = ++this._presetProbeGen;
    if (!this._account || !this._hass) {
      if (gen !== this._presetProbeGen) return false;
      this._availablePresets = ["24h"];
      return true;
    }
    const id = this._account.statistic_ids.consumption;
    const available = [];
    const bill = this._billBounds();
    for (const key of RANGE_PRESET_ORDER) {
      if (gen !== this._presetProbeGen) return false;
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
    if (gen !== this._presetProbeGen) return false;
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
    return true;
  }

  _selectRangeKey(key) {
    this._rangeKey = this._normalizeRangeKey(key);
    this._rangeShift = 0;
    this._customRange = null;
    this._rangeCustomOpen = false;
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
    this._filtersDirty = false;
    this._bindFilterInteractionGuard();
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
    const customOpen = !!this._rangeCustomOpen;
    const intervalButtons = ["hour", "day", "month"]
      .map((period) => {
        const on = this._period === period;
        const text = period.charAt(0).toUpperCase() + period.slice(1);
        return `<button type="button" data-period="${period}" class="${on ? "active" : ""}" aria-pressed="${
          on ? "true" : "false"
        }">${text}</button>`;
      })
      .join("");
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
      <div class="range-row">
        <div class="seg range-presets" role="group" aria-label="Range presets">
          ${primaryButtons}
        </div>
        <div class="range-tools">
          <div class="stepper" role="group" aria-label="Move the window">
            <button type="button" id="range-older" title="Older" aria-label="Older window">‹</button>
            <span class="range-label">${this._escape(label)}</span>
            <button type="button" id="range-newer" title="Newer" aria-label="Newer window" ${
              canStepNewer ? "" : "disabled"
            }>›</button>
          </div>
          <div class="seg interval" role="group" aria-label="Chart interval">${intervalButtons}</div>
          <button type="button" class="ghost range-custom-toggle" id="range-custom-toggle" aria-expanded="${
            customOpen ? "true" : "false"
          }" aria-pressed="${customOpen || this._customRange ? "true" : "false"}" aria-controls="range-custom" aria-label="Custom range"><ha-icon icon="mdi:calendar-range"></ha-icon></button>
          <select id="range-more" class="range-more ghost ${moreActive ? "active" : ""}" aria-label="More ranges">
            <option value="" ${moreActive ? "" : "selected"}>More…</option>
            ${moreOptions}
          </select>
        </div>
      </div>
      <div class="range-custom" id="range-custom" ${customOpen ? "" : "hidden"}>
        <span class="range-custom-label">Custom range</span>
        <input type="datetime-local" id="range-start" aria-label="Range start" value="${this._escape(
          this._toLocalInputValue(range.start)
        )}" />
        <input type="datetime-local" id="range-end" aria-label="Range end" value="${this._escape(
          this._toLocalInputValue(new Date(Math.max(range.start.getTime(), range.end.getTime() - 1)))
        )}" />
        <button type="button" id="range-apply">Apply</button>
      </div>
    `;
    el.querySelectorAll("[data-range]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        this._selectRangeKey(btn.dataset.range);
        this._renderFilters();
        await this._renderRangeScope();
      });
    });
    el.querySelector("#range-more").addEventListener("change", async (ev) => {
      const key = ev.target.value;
      if (!key) return;
      this._selectRangeKey(key);
      this._renderFilters();
      await this._renderRangeScope();
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
      await this._renderRangeScope();
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
      await this._renderRangeScope();
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
      this._rangeCustomOpen = true;
      this._renderFilters();
      await this._renderRangeScope();
    });
    el.querySelector("#range-custom-toggle").addEventListener("click", () => {
      this._rangeCustomOpen = !this._rangeCustomOpen;
      this._renderFilters();
    });
    el.querySelectorAll("[data-period]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const period = btn.dataset.period;
        if (!period || period === this._period) return;
        this._period = period;
        el.querySelectorAll("[data-period]").forEach((peer) => {
          const on = peer === btn;
          peer.classList.toggle("active", on);
          peer.setAttribute("aria-pressed", String(on));
        });
        await this._renderRangeScope();
      });
    });
  }

  async _renderRangeScope() {
    const rangeGen = ++this._rangeRenderGen;
    const entryId = this._activeEntryId;
    const gen = this._galleryRenderGen;
    const stale = () =>
      this._rangeRenderGen !== rangeGen || this._galleryRenderGen !== gen || this._activeEntryId !== entryId;
    await this._renderHero();
    if (stale()) return;
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
      <h3>PGE publication gaps ${this._hint("What Portland General Electric has not published, or has not finished publishing, yet. These gaps are upstream of Home Assistant.")}</h3>
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

  _hint(text, options = {}) {
    const asHtml = options.html === true;
    const label = options.label || "More info";
    const body = asHtml ? text : this._escape(text);
    return `<span class="hint"><button type="button" class="hint-btn" aria-label="${this._escape(label)}" aria-expanded="false">?</button><span class="hint-pop" role="tooltip">${body}</span></span>`;
  }

  _bindHints() {
    if (this._hintsBound) return;
    this._hintsBound = true;
    const fine = window.matchMedia("(hover: hover) and (pointer: fine)");
    this.shadowRoot.addEventListener("click", (ev) => {
      const btn = ev.target.closest?.(".hint-btn");
      if (!btn || fine.matches) return;
      ev.preventDefault();
      ev.stopPropagation();
      const hint = btn.closest(".hint");
      const willOpen = !hint.classList.contains("open");
      this.shadowRoot.querySelectorAll(".hint.open").forEach((el) => {
        el.classList.remove("open");
        el.querySelector(".hint-btn")?.setAttribute("aria-expanded", "false");
      });
      hint.classList.toggle("open", willOpen);
      btn.setAttribute("aria-expanded", String(willOpen));
    });
    this._onHintOutside = (ev) => {
      const path = typeof ev.composedPath === "function" ? ev.composedPath() : [];
      for (const open of this.shadowRoot?.querySelectorAll(".hint.open") || []) {
        if (path.includes(open)) continue;
        open.classList.remove("open");
        open.querySelector(".hint-btn")?.setAttribute("aria-expanded", "false");
      }
    };
    document.addEventListener("click", this._onHintOutside);
  }

  _integrationVersion() {
    const match = String(import.meta.url).match(/[?&]v=([^&#]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  _bindSyncPill() {
    const wrap = this.shadowRoot.querySelector(".sync-pill-wrap");
    const pill = wrap?.querySelector("#sync-pill");
    if (!wrap || !pill || wrap.dataset.bound === "1") return;
    wrap.dataset.bound = "1";
    if (this._onSyncPopOutside) document.removeEventListener("click", this._onSyncPopOutside);
    const fine = window.matchMedia("(hover: hover) and (pointer: fine)");
    pill.addEventListener("click", (ev) => {
      if (fine.matches) {
        this.shadowRoot.getElementById("sync-drawer")?.showModal();
        return;
      }
      ev.stopPropagation();
      const open = wrap.classList.toggle("open");
      pill.setAttribute("aria-expanded", String(open));
    });
    wrap.addEventListener("click", (ev) => {
      if (!ev.target.closest("[data-open-sync]")) return;
      ev.preventDefault();
      wrap.classList.remove("open");
      pill.setAttribute("aria-expanded", "false");
      this.shadowRoot.getElementById("sync-drawer")?.showModal();
    });
    this._onSyncPopOutside = (ev) => {
      if (!wrap.classList.contains("open")) return;
      const path = typeof ev.composedPath === "function" ? ev.composedPath() : [];
      if (path.includes(wrap)) return;
      wrap.classList.remove("open");
      pill.setAttribute("aria-expanded", "false");
    };
    document.addEventListener("click", this._onSyncPopOutside);
  }

  _syncPopHtml(sync) {
    const row = (label, value) => {
      const text = value == null || value === "" ? "" : String(value);
      if (!text) return "";
      return `<dt>${this._escape(label)}</dt><dd>${this._escape(text)}</dd>`;
    };
    const lastOk = this._fmtPacificDateTime(sync.last_successful_update);
    const newest = this._fmtPacificDateTime(sync.newest_interval) ||
      this._fmtPacificDateTime(stateDisplay(this._hass, this._account?.entity_ids?.latest_interval, ""));
    const report = syncHasReportableError(sync)
      ? `<a href="${this._escape(
          syncIssueUrl({
            version: this._integrationVersion(),
            haVersion: this._hass?.config?.version || "",
            sync,
          }),
        )}" target="_blank" rel="noopener noreferrer">Report this sync issue</a>`
      : "";
    return `
      <dl>
        ${row("Status", sync.status || "idle")}
        ${row("Phase", sync.phase)}
        ${row("Last success", lastOk || "Not yet")}
        ${row("Latest interval", newest)}
        ${row("Detail", sync.message)}
      </dl>
      ${sync.error ? `<p class="error">${this._escape(sync.error)}</p>` : ""}
      ${
        sync.last_api_error && sync.last_api_error !== sync.error
          ? `<p class="error">${this._escape(sync.last_api_error)}</p>`
          : ""
      }
      <div class="sync-pop-actions">
        <button type="button" data-open-sync>Open diagnostics</button>
        ${report}
      </div>
    `;
  }

  _renderSync() {
    const el = this.shadowRoot.getElementById("sync");
    if (!this._account) return;
    const sync = this._syncByEntry[this._account.entry_id] || {};
    const pill = syncPillState(sync);
    const pillEl = this.shadowRoot.getElementById("sync-pill");
    if (pillEl) {
      pillEl.setAttribute("aria-label", pill.text);
      let text = pillEl.querySelector(".sync-pill-text");
      if (!text) {
        text = document.createElement("span");
        text.className = "sync-pill-text";
        pillEl.replaceChildren(text);
      }
      if (text.textContent !== pill.text) text.textContent = pill.text;
      if (!pillEl.classList.contains(pill.tone)) {
        pillEl.classList.remove("good", "warn", "critical");
        pillEl.classList.add(pill.tone);
      }
    }
    const pop = this.shadowRoot.getElementById("sync-pop");
    if (pop) {
      const popHtml = this._syncPopHtml(sync);
      const sig = `${pill.text}|${sync.status || ""}|${sync.phase || ""}|${sync.message || ""}|${sync.error || ""}|${sync.last_api_error || ""}|${sync.last_successful_update || ""}`;
      if (pop.dataset.sig !== sig) {
        pop.dataset.sig = sig;
        pop.innerHTML = popHtml;
      }
    }
    if (!el) return;
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
          this._fmtPacificDateTime(sync.newest_interval) ||
            this._fmtPacificDateTime(stateDisplay(this._hass, this._account.entity_ids.latest_interval)) ||
            stateDisplay(this._hass, this._account.entity_ids.latest_interval)
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
    const kpiEntry = this._activeEntryId;
    const kpiGen = this._galleryRenderGen || 0;
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
    let usualDelta = null;
    let usualComplete = false;
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
      const sparkStart = new Date(publishedEnd.getTime() - 31 * 24 * 60 * 60 * 1000);
      const yesterdayStart = pacificMidnightUtc(priorPacificYmd(pacificYmd(publishedEnd)));
      const [kwhSeries, costSeries, weekKwhSum, weekCostSum, compensationDaySum, compensationSparkSeries] = await Promise.all([
        fetchStatisticSeries(this._hass, this._account.statistic_ids.consumption, {
          start: sparkStart,
          end: publishedEnd,
          period: "day",
          maxPoints: 40,
        }),
        fetchStatisticSeries(this._hass, this._account.statistic_ids.cost, {
          start: sparkStart,
          end: publishedEnd,
          period: "day",
          maxPoints: 40,
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
      sparkKwh = (kwhSeries.values || []).slice(-30);
      sparkCost = costSeries.values || [];
      weekKwh = weekKwhSum.total;
      weekCost = weekCostSum.total;
      yesterdayCompensationStat = compensationDaySum.count > 0 ? compensationDaySum.total : null;
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
      const yesterdayYmd = pacificYmd(new Date(publishedEnd.getTime() - 1));
      const byDay = new Map();
      (kwhSeries.xs || []).forEach((ts, index) => {
        const value = Number(kwhSeries.values?.[index]);
        if (Number.isFinite(ts) && Number.isFinite(value)) byDay.set(pacificYmd(ts), value);
      });
      const prior = [];
      let cursor = priorPacificYmd(yesterdayYmd);
      for (let day = 0; day < 7; day++) {
        prior.push(byDay.has(cursor) ? byDay.get(cursor) : null);
        cursor = priorPacificYmd(cursor);
      }
      usualComplete = prior.every((value) => value != null) && byDay.has(yesterdayYmd);
      if (usualComplete) {
        const avg = prior.reduce((sum, value) => sum + value, 0) / prior.length;
        usualDelta = pctDelta(byDay.get(yesterdayYmd), avg);
      }
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


    if (this._activeEntryId !== kpiEntry || (this._galleryRenderGen || 0) !== kpiGen) return;
    const spark = (vals, color) => sparklineSvg(vals || [], { stroke: color });
    const usualChip = !usualComplete || usualDelta == null
      ? `<div class="delta">Not enough complete days to compare</div>`
      : Math.abs(usualDelta) <= 5
        ? `<div class="delta-chip">about usual</div>`
        : usualDelta > 0
          ? `<div class="delta-chip warn">▲ ${Math.round(usualDelta)}% vs your usual day</div>`
          : `<div class="delta-chip good">▼ ${Math.round(Math.abs(usualDelta))}% vs your usual day</div>`;
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
    const kpiSig = [
      kpiEntry,
      yesterdayKwh,
      yesterdayReturn,
      yesterdayMoneyValue,
      yesterdayMoneyNote,
      hasYesterdayExport,
      weekKwh,
      weekCost,
      weekRange,
      cycleCost,
      cycleKwh,
      cycleRange,
      usageCycleCost,
      usageCycleKwh,
      kwhDelta,
      costDelta,
      sinceStatementCost,
      sinceStatementKwh,
      sinceStatementRange,
      estCharges,
      estRange,
      cycleProgress,
      dueStatus,
      amountDue,
      dueDate,
      lastPayment,
      lastPaymentDate,
      usualChip,
      estNextMin,
      estNextMax,
      (sparkKwh || []).join(","),
      (moneySpark || []).join(","),
      (sparkWeekKwh || []).join(","),
      (sparkWeekCost || []).join(","),
    ].join("|");
    // Identical glance markup still replaces nodes. That reflow scrolls the page
    // and resets an open header select back to the first item.
    if (this._kpiSig === kpiSig && el.childElementCount) return;
    this._kpiSig = kpiSig;
    const exportNote = hasYesterdayExport
      ? `<div class="delta">Export ${this._fmt(yesterdayReturn, " kWh")}</div>`
      : "";
    el.innerHTML = `
      <h2>At a glance ${this._hint("Yesterday and week use imported intervals through yesterday (Pacific week starts Sunday; no complete today). Statement = PGE billDetails. Usage cycle = imported hourly sum over that period. Since statement = usage after the statement end through yesterday. PGE estimate = PGE's own open-cycle projection, which does not reconcile with the interval sums. Interval net amount is an estimate and does not model PGE monthly/TOD credit buckets or annual true-up.")}</h2>
      <div class="kpi-grid">
        <div class="kpi kpi-usage"><div class="label"><span class="group">Yesterday</span>Import</div><div class="value">${this._fmt(yesterdayKwh, " kWh")}</div>${usualChip}${exportNote}${spark(sparkKwh, "var(--pge-series-kwh)")}</div>
        <div class="kpi kpi-statement"><div class="label"><span class="group">Yesterday</span>Cost</div><div class="value">${yesterdayMoneyValue}</div>${yesterdayMoneyNote ? `<div class="delta">${this._escape(yesterdayMoneyNote)}</div>` : ""}${spark(moneySpark, "var(--pge-series-cost)")}</div>
        <div class="kpi kpi-usage"><div class="label"><span class="group">This week</span>Import</div><div class="value">${this._fmt(weekKwh, " kWh")}</div><div class="delta">${this._fmtRangeDelta(weekRange)}</div>${spark(sparkWeekKwh, "var(--pge-series-kwh)")}</div>
        <div class="kpi kpi-statement"><div class="label"><span class="group">This week</span>Cost</div><div class="value">${this._fmt(weekCost, "", true)}</div><div class="delta">${this._fmtRangeDelta(weekRange)}</div>${spark(sparkWeekCost, "var(--pge-series-cost)")}</div>
        <div class="kpi kpi-usage"><div class="label"><span class="group">Statement</span>kWh</div><div class="value">${this._fmt(cycleKwh, " kWh")}</div><div class="delta">${this._fmtRangeDelta(cycleRange)}</div></div>
        <div class="kpi kpi-statement"><div class="label"><span class="group">Statement</span>Cost</div><div class="value">${this._fmt(cycleCost, "", true)}</div><div class="delta">${this._fmtRangeDelta(cycleRange)}</div></div>
        <div class="kpi kpi-usage"><div class="label"><span class="group">Statement</span>Import</div><div class="value">${this._fmt(usageCycleKwh, " kWh")}</div><div class="delta">${this._escape(fmtDelta(kwhDelta, false))}</div></div>
        <div class="kpi kpi-statement"><div class="label"><span class="group">Statement</span>Import cost</div><div class="value">${this._fmt(usageCycleCost, "", true)}</div><div class="delta">${this._escape(fmtDelta(costDelta, true))}</div></div>
        <div class="kpi kpi-usage"><div class="label"><span class="group">Since statement</span>Import</div><div class="value">${this._fmt(sinceStatementKwh, " kWh")}</div><div class="delta">${this._fmtRangeDelta(sinceStatementRange)}</div></div>
        <div class="kpi kpi-statement"><div class="label"><span class="group">Since statement</span>Cost</div><div class="value">${this._fmt(sinceStatementCost, "", true)}</div><div class="delta">${this._fmtRangeDelta(sinceStatementRange)}</div></div>
        <div class="kpi kpi-estimate"><div class="label"><span class="group">Account</span>Charges so far</div><div class="value">${this._fmt(estCharges, "", true)}</div><div class="delta">${this._escape(cycleProgress)}</div></div>
        <div class="kpi kpi-estimate"><div class="label"><span class="group">Account</span>Next bill</div><div class="value">${this._escape(estRange)}</div><div class="delta">${this._escape(cycleProgress)}</div></div>
        <div class="kpi status-${dueStatus}"><div class="label"><span class="group">Account</span>Amount due</div><div class="value">${this._fmt(amountDue, "", true)}</div><div class="delta">Due ${this._escape(this._fmtDate(dueDate) || "—")}</div></div>
        <div class="kpi status-${dueStatus}"><div class="label"><span class="group">Account</span>Last payment</div><div class="value">${this._fmt(lastPayment, "", true)}</div><div class="delta">${this._escape(this._fmtDate(lastPaymentDate) || "—")}</div></div>
      </div>
    `;
    this._bindGlanceKpiClipboard(el);
    const story = this.shadowRoot.getElementById("story");
    if (story) {
      const rows = storySummary({
        estimate: { low: estNextMin, high: estNextMax },
      });
      story.hidden = rows.length === 0;
      story.innerHTML = rows
        .map((row) => `<p class="story-line tone-${row.tone}">${this._escape(row.text)}</p>`)
        .join("");
    }
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
    const gen = ++this._galleryRenderGen;
    const entryId = this._activeEntryId;
    const stale = () => this._galleryRenderGen !== gen || this._activeEntryId !== entryId;
    this._disposeHostCharts(
      this.shadowRoot.getElementById("chart-overview-usage"),
      this.shadowRoot.getElementById("chart-usage"),
      this.shadowRoot.getElementById("scatter"),
      this.shadowRoot.getElementById("cost-per-kwh"),
      this.shadowRoot.getElementById("heatmap-kwh"),
      this.shadowRoot.getElementById("heatmap-temp"),
      this.shadowRoot.getElementById("ledger-bill"),
      this.shadowRoot.getElementById("ledger-kwh")
    );
    await this._renderHero();
    if (stale()) return;
    await this._softGallery(() => this._renderLoadShapeGallery());
    if (stale()) return;
    await this._softGallery(() => this._renderInsights());
    if (stale()) return;
    await this._softGallery(() => this._renderLedgerCharts());
    if (stale()) return;
    await this._softGallery(() => this._renderTodGallery());
    if (stale()) return;
    await this._softGallery(() => this._renderWeatherMoney());
  }

  /** One gallery pass after the active entry's sync reaches complete. */
  _selectChapterView(chapter, id) {
    if (!chapter) return;
    const target = [...chapter.querySelectorAll("[data-view-panel]")].find((view) => view.dataset.viewPanel === id);
    const chip = [...chapter.querySelectorAll("[data-view]")].find((button) => button.dataset.view === id && !button.disabled);
    if (!target || !chip) return;
    for (const view of chapter.querySelectorAll("[data-view-panel]")) view.hidden = view !== target;
    for (const button of chapter.querySelectorAll("[data-view]")) {
      button.setAttribute("aria-pressed", String(button === chip));
    }
    try { localStorage.setItem("pge_chapter_view_" + chapter.dataset.chapter, id); }
    catch (_err) { /* storage can be unavailable */ }
    this._resizeChartsUnder(target);
  }

  _mountDeferred(record) {
    if (record.promise) return record.promise;
    const host = record.sourceHost;
    record.promise = (async () => {
      try {
        const chart = await runGalleryFactory(this, record, host);
        if (!galleryRecordCurrent(this, record)) return;
        if (chart) this._charts.push(chart);
        else host.closest("figure")?.setAttribute("hidden", "");
      } catch (err) {
        if (galleryRecordCurrent(this, record)) {
          host.textContent = "This chart could not load. Refresh to try again.";
          console.warn("PGE chart initialization failed", err);
        }
      } finally {
        if (galleryRecordCurrent(this, record)) host.classList.remove("chart-skeleton");
      }
    })();
    return record.promise;
  }

  async _refreshGalleriesAfterSync() {
    const gen = ++this._galleryRenderGen;
    const entryId = this._activeEntryId;
    const stale = () => this._galleryRenderGen !== gen || this._activeEntryId !== entryId;
    this._pendingMounts = new Map();
    this._chartFactories = new Map();
    if (await rerenderFactoryHosts(this, stale)) await this._resumeChartDialog?.();
  }

  async _renderHero() {
    const account = this._account;
    if (!account) return;
    const stamp = { entryId: this._activeEntryId, gen: this._galleryRenderGen || 0 };
    const stale = () =>
      stamp.entryId !== this._activeEntryId || stamp.gen !== (this._galleryRenderGen || 0);
    const usageRange = this._resolveChartRange();
    const usagePeriod = this._period || usageRange.period;
    const overviewRange = this._basePresetRange("24h");
    const ids = account.statistic_ids;
    const colors = seriesColors(this);
    // High ceiling so range accounting is not LTTB-downsampled away.
    const maxPoints = 20000;

    const usageRaw = await this._fetchUsageSeries(
      ids,
      usageRange.start,
      usageRange.end,
      usagePeriod,
      maxPoints,
    );
    if (stale()) return;
    const usageChartProjection = projectDirectionalUsage(usageRaw);
    const accountingProjection = projectUsageSeries(usageRaw);
    this._lastSeries = {
      ...usageRaw,
      projection: accountingProjection,
      range: usageRange,
      period: usagePeriod,
    };

    const reuseOverview =
      usageRange.start.getTime() === overviewRange.start.getTime() &&
      usageRange.end.getTime() === overviewRange.end.getTime() &&
      usagePeriod === "hour";
    let overviewRaw = usageRaw;
    let overviewProjection = usageChartProjection;
    if (!reuseOverview) {
      overviewRaw = await this._fetchUsageSeries(
        ids,
        overviewRange.start,
        overviewRange.end,
        "hour",
        maxPoints,
      );
      if (stale()) return;
      overviewProjection = projectDirectionalUsage(overviewRaw);
    }

    const usagePainted = await this._paintUsageCombo(
      "chart-usage",
      usageRaw,
      usageChartProjection,
      usagePeriod,
      this._usageMetric,
      stamp,
      colors,
    );
    if (!usagePainted) return;
    const overviewPainted = await this._paintUsageCombo(
      "chart-overview-usage",
      overviewRaw,
      overviewProjection,
      "hour",
      "kwh",
      stamp,
      colors,
    );
    if (!overviewPainted) return;
    this._setOverviewUsageTitle(overviewRange);
    void this._renderUsageStats();
  }

  _setOverviewUsageTitle(range) {
    const heading = this.shadowRoot.querySelector("#overview-usage-card > h2");
    if (!heading) return;
    heading.textContent = `Last 24 hours · ${formatRangeLabel(range.start, range.end)}`;
  }

  async _paintUsageCombo(hostId, raw, projection, period, metric, stamp, colors) {
    const usageHost = this.shadowRoot.getElementById(hostId);
    if (!usageHost) return true;
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
      projection,
      periodColors: period === "hour" ? todColors(usageHost) : null,
      metric,
    });
    if (stamp.entryId !== this._activeEntryId || stamp.gen !== (this._galleryRenderGen || 0)) {
      try {
        chart?.destroy?.();
      } catch (_err) {
        /* account changed while the usage chart was initializing */
      }
      return false;
    }
    if (chart) this._charts.push(chart);
    return true;
  }

  _plainChart(technical, source) {
    const known = {
      "Usage combo": ["Your energy, hour by hour", "Energy you used, outdoor temperature, and PGE's usage estimate on one chart.", "Bars are energy, colored by Time of Day when the range is hourly. The lines are temperature and the amount PGE estimated.", "You can see busy hours, the weather, and the estimate together."],
      "Typical day": ["A typical weekday vs weekend", "Your average use for each hour, weekdays against weekends, with your overnight floor.", "The higher line is the busier kind of day. The floor line is overnight power.", "It shows when a normal day peaks."],
      "Hour by weekday": ["Your weekly rhythm", "Darker squares are hours when you usually use more.", "Rows are days of the week and columns are hours.", "A dark column is a habit, not a one-off."],
      "Daily kWh histogram": ["How big is a normal day?", "How many days fell into each daily usage range.", "Taller bars are ranges that happen more often.", "You can see what a normal day looks like for this home."],
      "Year over year": ["This year vs past years", "Monthly totals for each year. Months with missing days are left out.", "Each line is a year. A gap means that month was incomplete.", "You can compare seasons without a partial month pretending to be low."],
      "Billing-cycle race": ["This bill vs last bill, day by day", "Running total for the current bill next to the last bill at the same day.", "Day 1 is the first day of each bill. A gap means a missing day.", "You can see whether this bill is ahead of the last one."],
      "Daily spread": ["Unusual days", "Days above the top line or below the bottom line were far from normal for you.", "The middle line is your average. The outer lines are unusually high or low.", "Those days are worth a second look."],
      "Always-on load history": ["Always-on power over time", "Your lowest overnight use each night. A lasting rise often means a device that never turns off.", "Each point is one complete night. Missing nights are gaps.", "A step up that stays up is usually a new always-on device."],
      "Duck curve": ["Solar export vs use by hour", "When you send energy to the grid and when you pull from it.", "Import and export are separate lines across the day.", "You can see the hours solar covers your use."],
      "Duck curve by month": ["Solar export and use by month", "Monthly totals of energy used and exported, with PGE's estimates.", "Each month shows use, export, and PGE's estimate.", "It shows how solar and use change through the year."],
      "Weather vs usage": ["Hotter and colder days vs your use", "Each dot is a day: outdoor temperature against energy used.", "Right is hotter. Up is more energy.", "The slope is how much weather moves your use."],
      "Degree days vs kWh": ["Heating and cooling demand vs your use", "How much heating or cooling the weather called for, next to what you used.", "One line is energy and one is degree days.", "They rise together when weather is driving the bill."],
      "Temperature bins": ["How temperature changes your daily use", "Your average day in each outdoor temperature band.", "Each bar is the average day in that temperature band.", "You can see which temperatures cost the most energy."],
      "Weather-normalized counterfactual": ["Is it the weather, or is it you?", "What the weather alone predicts you would use, next to what you used.", "The top pane is actual and predicted. The lower pane is the running gap.", "A growing gap means your use changed beyond the weather."],
      "Monthly average rate": ["PGE's estimated cost per kWh each month", "Monthly average cost per kWh from PGE's estimate.", "Each bar is that month's average from PGE's hourly estimate.", "It is an estimate, not the billed rate."],
      "kWh calendar": ["Your year in usage", "One square per day, darker means more energy.", "Read across a month and down the years.", "Dark days are the ones that used the most."],
      "Temperature calendar": ["Your year in temperature", "One square per day, colored from cold to hot.", "Read across a month and down the years.", "It sits next to the usage calendar so you can compare."],
      "Why this bill changed": ["Why this bill changed", "How bill length, weather, rates, and your usage each moved the amount due.", "Bars add up to the change from the previous bill.", "The longest bar is the main reason the amount moved."],
      "Statement waterfall": ["From last balance to this bill", "Last amount due, minus your payment, plus new charges.", "Each step moves the running total.", "You can see payment and new charges separately."],
      "Statement vs portal estimate": ["Your bill vs PGE's hourly estimate", "Each statement next to the sum of PGE's hourly estimates for the same days.", "One series is the bill and one is PGE's estimate.", "A gap means the hourly estimate did not match the statement."],
      "Bill kWh vs imported kWh": ["Billed kWh vs recorded kWh", "Energy on each bill next to the hourly data recorded here.", "Compare the two bars for the same statement.", "They should be close when the hourly history is complete."],
      "Balance and amount due": ["What you owe over time", "Account balance and amount due as they changed.", "Each point is a recorded balance or amount due.", "You can see whether the balance is rising."],
      "Stacked bill anatomy": ["What's in each bill", "Each bill split into basic charge, energy, delivery, taxes, and other.", "Switch between dollars and percent. Percent shows the share of the bill.", "You can see which part of the bill grew."],
      "Ledger dollars": ["Billed vs paid", "Each month's bill next to what you paid.", "One series is billed and one is paid.", "A gap means a month you paid more or less than the bill."],
      "Ledger kWh": ["Billed energy by statement", "Energy on each statement.", "Each bar is the energy on that statement.", "It is the billed energy, not the hourly recorder series."],
      "Money-hours Pareto": ["Your most expensive hours", "Hours of the day ranked by estimated cost, with how much of the total they add up to.", "The top bar is the most expensive hour. The label is its share of the total.", "A few hours can hold a large share of the estimated cost."],
      "Stacked area": ["When your energy lands on the Time of Day clock", "Hourly use colored by off-peak, mid-peak, and on-peak.", "The colors are the Time of Day periods.", "You can see how much use lands in the expensive hours."],
      "kWh by period": ["Typical hourly use in each period", "The usual range of hourly use in each Time of Day period.", "The box is the usual range. Dots outside it were unusual hours.", "It shows whether on-peak hours are also high-use hours."],
      "Sankey": ["Where your energy dollars go by period", "Energy in each period flowing into its estimated cost.", "The width is energy. The label on the right is the estimated dollars.", "It is a local estimate, not a billed Time of Day charge."],
      "Monthly period mix": ["Your Time of Day mix by month", "Share of each month's energy in each period.", "The stack always adds to 100 percent.", "A growing on-peak band means more of the month landed in expensive hours."],
      "Local Basic minus local TOD": ["Would Time of Day have saved money?", "Estimated monthly difference between Basic and Time of Day pricing.", "Above zero means the local Time of Day estimate was lower.", "It is a local estimate, not PGE's official comparison."],
      "Forward 48-hour ribbon": ["The next 48 hours on the Time of Day clock", "Your usual use for each coming hour, colored by period.", "Each bar is your historical average for that hour of the week.", "It does not include hours PGE has not published yet."],
      "Load-shift simulator": ["Try moving a big load", "Monthly cost of a load like an EV charge at each start hour.", "Each bar is the local estimate for starting at that hour.", "The line is Schedule 7 base plus Schedule 125, not a full Basic bill."],
      "Day fingerprint": ["Comparing days across five measures", "Each line is a day: energy, peak hour, temperature, on-peak share, and price.", "Lines that stand apart were unusual days.", "You can spot odd days without opening each one."],
      "Monthly ridgelines": ["How your daily pattern shifts by month", "Average hourly use for each month, stacked.", "Each ridge is one month.", "You can see the daily shape change through the year."],
      "Daypart stream": ["Morning, afternoon, evening, overnight", "How your use splits across parts of the day over time.", "The bands are the parts of the day.", "A band that grows is taking more of your energy."],
      "Published week": ["Last week, day by day", "Each day of the last full week, hour by hour.", "Compare the seven days side by side.", "It is the latest complete week PGE has published."],
      "Program savings": ["Program savings this year", "Year-to-date savings reported by PGE programs.", "The value is PGE's reported year-to-date savings.", "It is not calculated from your hourly usage."],
      "Baseload band": ["Your always-on floor across the day", "Weekday average by hour with your overnight minimum as a line.", "The line is the overnight floor.", "Use above the line is the part that turns on and off."],
      "24-hour polar clock": ["Your day as a clock", "Average weekday use around a 24-hour dial.", "Longer bars are hours you usually use more.", "The clock makes the daily rhythm easy to scan."],
      "Latest statement treemap": ["Your latest bill as blocks", "Each block's size is that charge's share of the latest bill.", "Bigger blocks are a larger share.", "You can see what dominated the last bill."],
    };
    const row = known[technical];
    if (!row) {
      return {
        title: technical,
        what: "Your recorded PGE history for this chart.",
        how: "Compare the marks with the axis labels. A gap means a sample was not published.",
        why: "It is your own history, not a comparison with another home.",
        source: source || "PGE history stored in Home Assistant.",
      };
    }
    return { title: row[0], what: row[1], how: row[2], why: row[3], source: source || "PGE history stored in Home Assistant." };
  }

  _figure(id, { eyebrow, title, what, how, why, source, wide = false, extra = "", note = false }) {
    const plain = this._plainChart(eyebrow, source || what);
    const esc = (value) => this._escape(String(value ?? ""));
    const definition = (term, text) => `<dt>${esc(term)}</dt><dd>${esc(text)}</dd>`;
    const shownTitle = plain.title || title;
    const termHint = {
      "chart-baseload": "Always-on power (baseload): energy your home uses every hour, even when you are asleep or away. Fridges, routers, and devices on standby add to it.",
      "chart-baseload-history": "Always-on power (baseload): energy your home uses every hour, even when you are asleep or away. Fridges, routers, and devices on standby add to it.",
      "chart-degree-days": "A degree day measures how much heating or cooling the outdoor temperature called for, using a 65°F base.",
      "chart-spread": "Standard deviation: how far your days sit from your own average. Days beyond two standard deviations were unusual for you.",
      "chart-weather-counterfactual": "Weather-normalized: what the weather alone predicts you would use, next to what you actually used. R² is how much of the variation in your use the weather model explains. It is a fit score, not a promise.",
      "chart-bill-explainer": "A statement window is the set of days from one bill's end to the next.",
      "chart-statement-portal": "A statement window is the set of days from one bill's end to the next.",
      "chart-bill-imported": "A statement window is the set of days from one bill's end to the next.",
    }[id];
    const about = `<dl>${definition("What this shows", plain.what)}${termHint ? definition("Term", termHint) : ""}${definition("How to read it", plain.how)}
            ${definition("Why it matters", plain.why)}${definition("Data source", plain.source)}</dl>`;
    return `<figure class="chart-card ${wide ? "fig-wide" : ""}" data-figure="${esc(id)}" data-chart="${esc(id)}">
      <div class="fig-head">
        <div class="fig-titles">
          <h3 class="fig-title" data-headline-for="${esc(id)}"><span class="fig-title-text">${esc(shownTitle)}</span></h3></div>
        ${this._hint(about, { html: true, label: "About this chart" })}
        <button type="button" class="fig-expand" data-expand="${esc(id)}" aria-label="Expand ${esc(shownTitle)}" disabled>
          <ha-icon icon="mdi:arrow-expand"></ha-icon></button>
      </div>
      ${extra}
      ${note ? `<p class="fig-note muted"></p>` : ""}
      <div class="chart-host" id="${esc(id)}"></div>
    </figure>`;
  }

  _loadShapeGalleryHtml() {
    const wide = new Set(["chart-spread", "chart-baseload-history"]);
    const figure = (id, title, caption) =>
      this._figure(id, {
        eyebrow: title,
        title,
        what: caption,
        how: "Read the horizontal axis as time or category and the vertical axis as the amount. A gap means that sample was not published.",
        why: "The shape of your own history is easier to see than a table of the same numbers.",
        source: caption,
        wide: wide.has(id),
        note: id === "chart-baseload-history",
      });
    return `
      <section class="card chapter" data-chapter="when-you-use" data-persist="chart_gallery_load"${this._detailsOpenAttr("chart_gallery_load")}>
        <header class="chapter-head"><span class="eyebrow"><ha-icon icon="mdi:lightning-bolt-outline"></ha-icon>When you use energy</span>
          <h2 class="chapter-headline" data-chapter-headline="when-you-use">A typical weekday vs weekend</h2></header>
        <div class="chapter-lead">${figure("chart-typical-day", "Typical day", "Horizontal: Pacific hour. Vertical: mean kWh. Source: imported hourly consumption.")}</div>
        <div class="view-chips" role="group" aria-label="More views">
          <button type="button" class="chip" data-view="chart-hour-weekday" aria-pressed="true">Weekly rhythm</button>
          <button type="button" class="chip" data-view="chart-histogram" aria-pressed="false">How big is a normal day?</button>
          <button type="button" class="chip" data-view="chart-yoy" aria-pressed="false">This year vs past years</button>
          <button type="button" class="chip" data-view="chart-cycle-race" aria-pressed="false">This bill vs last bill</button>
          <button type="button" class="chip" data-view="chart-spread" aria-pressed="false">Unusual days</button>
          <button type="button" class="chip" data-view="chart-duck" aria-pressed="false">Solar export</button>
          <button type="button" class="chip" data-view="chart-duck-months" aria-pressed="false">Solar by month</button>
          <button type="button" class="chip" data-view="chart-baseload-history" aria-pressed="false">Always-on power</button>
        </div>
        <div class="chapter-views">
          <div data-view-panel="chart-hour-weekday">${figure("chart-hour-weekday", "Hour by weekday", "Horizontal: Pacific hour. Vertical: weekday. Color: mean kWh. Source: imported hourly consumption.")}</div>
          <div data-view-panel="chart-histogram" hidden>${figure("chart-histogram", "Daily kWh histogram", "Horizontal: daily kWh bin. Vertical: number of days. Source: imported daily consumption.")}</div>
          <div data-view-panel="chart-yoy" hidden>${figure("chart-yoy", "Year over year", "Horizontal: month. Vertical: kWh. Source: imported daily consumption.")}</div>
          <div data-view-panel="chart-cycle-race" hidden>${figure("chart-cycle-race", "Billing-cycle race", "Horizontal: day of statement. Vertical: cumulative kWh. Source: imported hourly consumption.")}</div>
          <div data-view-panel="chart-spread" hidden>${figure("chart-spread", "Daily spread", "Horizontal: date. Vertical: daily kWh. Lines: mean and mean plus or minus two standard deviations. Source: imported daily consumption.")}</div>
          <div data-view-panel="chart-duck" hidden>${figure("chart-duck", "Duck curve", "Horizontal: Pacific hour. Vertical: kWh. Import and export. Shown only when the account has returned energy.")}</div>
          <div data-view-panel="chart-duck-months" hidden>${figure("chart-duck-months", "Duck curve by month", "Horizontal: month. Vertical: kWh and dollars. Import, export, PGE usage estimate, and export compensation.")}</div>
          <div data-view-panel="chart-baseload-history" hidden>${figure("chart-baseload-history", "Always-on load history", "Horizontal: date. Vertical: minimum kWh in Pacific hours 0 through 5. Markers are steps. Yearly cost uses the trailing 365-day PGE usage estimate.")}</div>
        </div>
      </section>`;
  }

  async _renderLoadShapeGallery() {
    await renderLoadShape(this, {
      baseloadFloor,
      cycleCumulative,
      dayFingerprints,
      histogramBins,
      hourWeekdayMatrix,
      monthRidges,
      monthlyByYear,
      publishedWeekDays,
      spreadBand,
      typicalDayProfiles,
      gapDailyRows,
    });
  }

  _todGalleryHtml() {
    const wide = new Set(["chart-tod-stacked"]);
    const figure = (id, title, caption) =>
      this._figure(id, {
        eyebrow: title,
        title,
        what: caption,
        how: "Read the horizontal axis as time or category and the vertical axis as the amount. A gap means that sample was not published.",
        why: "The shape of your own history is easier to see than a table of the same numbers.",
        source: caption,
        wide: wide.has(id),
        note: id === "chart-baseload-history",
      });
    return `
      <section class="card chapter" data-chapter="tod-charts" data-persist="chart_gallery_tod"${this._detailsOpenAttr("chart_gallery_tod")}>
        <header class="chapter-head"><span class="eyebrow"><ha-icon icon="mdi:clock-time-four-outline"></ha-icon>Your Time of Day</span>
          <h2 class="chapter-headline">Shift your usage</h2></header>
        <figure data-chart="chart-shift-sim">
          <h3>Load-shift simulator ${this._hint("What a weekday load costs per month at each start hour. Local TOD imported-energy estimate versus Schedule 7 base plus Schedule 125. That line is not a full Basic bill. Weekends are all off-peak.")}</h3>
          <div class="shift-form">
            <label>Load <select id="chart-shift-preset">
              <option value="ev">EV 7.2 kW for 4 h</option>
              <option value="dryer">Dryer 3 kW for 1 h</option>
              <option value="dishwasher">Dishwasher 1.2 kW for 2 h</option>
              <option value="custom">Custom</option>
            </select></label>
            <label>kW <input id="chart-shift-kw" type="number" min="0" step="0.1" value="7.2"></label>
            <label>Hours <input id="chart-shift-hours" type="number" min="0" step="0.5" value="4"></label>
            <label>Runs per month <input id="chart-shift-runs" type="number" min="0" step="1" value="20"></label>
          </div>
          <div class="chart-host" id="chart-shift-sim"></div>
        </figure>
        ${figure("chart-tod-stacked", "Stacked area", "Horizontal: time. Vertical: kWh. Source: imported hourly consumption classified with the Pacific Time of Day schedule.")}
        ${figure("chart-period-mix", "Monthly period mix", "Horizontal: month. Vertical: share of kWh. Source: imported hourly consumption.")}
        ${figure("chart-money-pareto", "Money-hours Pareto", "Horizontal: dollars. Vertical: Pacific hour. Source: hourly kWh times the local catalog rate. Local TOD imported-energy estimate.")}
        ${figure("chart-period-box", "kWh by period", "Horizontal: period. Vertical: hourly kWh. Source: imported hourly consumption.")}
        ${figure("chart-tod-delta", "Local Basic minus local TOD", "Horizontal: month. Vertical: dollars, positive means the local TOD estimate is lower. Source: local catalog prices on hourly kWh.")}
        ${figure("chart-forward-ribbon", "Forward 48-hour ribbon", "Horizontal: next Pacific hour. Vertical: historical mean kWh. Bars follow the offline schedule. No recorder data past the published end.")}
        ${figure("chart-sankey", "Sankey", "Period kWh into local estimate dollars. Source: hourly consumption and the local catalog. Not portal hourly amount.")}
      </section>`;
  }

  async _renderTodGallery() {
    await renderTodCharts(this, {
      forwardRibbon,
      hourWeekdayMatrix,
      moneyHourPareto,
      periodBox,
      periodMixByMonth,
      sankeyFlows,
      todMinusBasicByMonth,
    });
    if (this.shadowRoot?.getElementById("chart-bill-explainer")) {
      await this._renderInsightCharts();
    }
  }

  _weatherGalleryHtml() {
    const wide = new Set(["chart-degree-days", "chart-weather-counterfactual"]);
    const figure = (id, title, caption) =>
      this._figure(id, {
        eyebrow: title,
        title,
        what: caption,
        how: "Read the horizontal axis as time or category and the vertical axis as the amount. A gap means that sample was not published.",
        why: "The shape of your own history is easier to see than a table of the same numbers.",
        source: caption,
        wide: wide.has(id),
        note: id === "chart-baseload-history",
      });
    return `
      ${figure("chart-degree-days", "Degree days vs kWh", "Horizontal: date. Vertical: kWh and degree days at a 65 °F base. Source: daily imported consumption and mean outdoor temperature.")}
      ${figure("chart-temp-bins", "Temperature bins", "Horizontal: outdoor temperature band. Vertical: mean daily kWh. Source: daily imported consumption and mean outdoor temperature.")}
      ${figure("chart-weather-counterfactual", "Weather-normalized counterfactual", "Actual daily kWh against the weather model fit on an earlier baseline. The cumulative gap is on the right. r2 is the fit quality.")}
      <div id="kpi-degree-price"></div>`;
  }

  _billingGalleryHtml() {
    const wide = new Set(["chart-statement-portal", "chart-bill-imported", "chart-balance-due"]);
    const figure = (id, title, caption) =>
      this._figure(id, {
        eyebrow: title,
        title,
        what: caption,
        how: "Read the horizontal axis as time or category and the vertical axis as the amount. A gap means that sample was not published.",
        why: "The shape of your own history is easier to see than a table of the same numbers.",
        source: caption,
        wide: wide.has(id),
        note: id === "chart-baseload-history",
      });
    return `
      <section class="card chapter" data-chapter="billing-charts" data-persist="chart_gallery_billing"${this._detailsOpenAttr("chart_gallery_billing")}>
        <header class="chapter-head"><span class="eyebrow"><ha-icon icon="mdi:receipt-text-outline"></ha-icon>Why this bill changed</span>
          <h2 class="chapter-headline" data-chapter-headline="billing-charts">Why this bill changed</h2></header>
        <div class="chapter-lead">${figure("chart-bill-explainer", "Why this bill changed", "Approximate statement windows. Bars sum to the change in amount due.")}</div>
        ${figure("chart-statement-portal", "Statement vs portal estimate", "Approximate statement window. Billed amount against summed PGE usage estimate.")}
        ${figure("chart-bill-imported", "Bill kWh vs imported kWh", "Approximate statement window. Billed kWh against summed imported kWh.")}
        ${figure("chart-balance-due", "Balance and amount due", "Horizontal: time. Vertical: dollars. Source: account balance and amount due means. Not a cumulative sum.")}
      </section>
      <div id="chart-pdf-slot"></div>`;
  }

  async _renderWeatherMoney() {
    const stamp = { entryId: this._activeEntryId, gen: this._galleryRenderGen || 0 };
    const stale = () =>
      stamp.entryId !== this._activeEntryId || stamp.gen !== (this._galleryRenderGen || 0);
    await renderWeatherMoney(this, {
      billVsImported,
      degreeDayPoint,
      statementGap,
      statementWindows,
      tempBins,
    });
    if (stale()) return;
    await this._renderPdfSolar();
    if (stale()) return;
    await this._renderInsightCharts();
  }

  async _renderInsightCharts() {
    await renderInsights(this, {
      baseloadSteps,
      billExplainer,
      centsPerKwh,
      counterfactual,
      daypartDays,
      degreePrice,
      shiftCostByStartHour,
      statementWindows,
      weatherModel,
      overnightFloorDays,
    });
  }

  async _renderPdfSolar() {
    await renderPdfSolar(this, {
      billAnatomyRows,
      billFamilies,
      duckHourProfiles,
      duckMonthBars,
      hasExport,
      lineItemShares,
      treemapSlices,
      waterfallSteps,
    });
    const pdf = this.shadowRoot?.querySelector("#chart-pdf-slot details");
    if (pdf) this._bindPersistentDetails(pdf.parentElement);
  }

  _pdfGalleryHtml() {
    const figure = (id, title, caption) =>
      this._figure(id, {
        eyebrow: title,
        title,
        what: caption,
        how: "Read the horizontal axis as time or category and the vertical axis as the amount. A gap means that sample was not published.",
        why: "The shape of your own history is easier to see than a table of the same numbers.",
        source: caption,
      });
    return `
      <section class="card chapter" data-chapter="bill-pdf" data-persist="chart_gallery_pdf"${this._detailsOpenAttr("chart_gallery_pdf")}>
        <header class="chapter-head"><span class="eyebrow"><ha-icon icon="mdi:receipt-text-outline"></ha-icon>What's in your bill</span>
          <h2 class="chapter-headline" data-chapter-headline="bill-pdf">What's in each bill</h2></header>
        <div class="metric-toggle" role="group" aria-label="Bill mix">
          <button type="button" data-bill-mode="dollars" aria-pressed="${this._billAnatomyMode !== "percent"}">$</button>
          <button type="button" data-bill-mode="percent" aria-pressed="${this._billAnatomyMode === "percent"}">%</button>
        </div>
        <div class="chapter-lead">${figure("chart-bill-anatomy", "Stacked bill anatomy", "Horizontal: statement. Vertical: dollars or percent. Basic, energy use, delivery, taxes, and other.")}</div>
        ${figure("chart-waterfall", "Statement waterfall", "Previous amount due, payment, new charges, amount due.")}
      </section>`;
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
        if (!el.open) return;
        const resize = () => this._resizeChartsUnder(el);
        resize();
        requestAnimationFrame(resize);
      });
    });
  }

  /** ECharts inits at zero width while a gallery `<details>` is closed. */
  _resizeChartsUnder(root) {
    if (!root) return;
    for (const wrapped of this._charts || []) {
      const dom = wrapped?.chart?.getDom?.();
      if (!dom || !root.contains(dom)) continue;
      try {
        wrapped.chart.resize();
      } catch (_err) {
        /* disposed */
      }
    }
  }

  _rollupTable(title, caption, rows, keyLabel, persistKey, { signed = false, netAmount = false } = {}) {
    const populated = this._populatedRollupRows(rows);
    if (!populated.length) return "";
    const showBuckets = rollupColumns(populated.map((row) => ({ buckets: row.samples }))).showBuckets;
    const kwhText = (raw) => (raw == null || Number.isNaN(Number(raw)) ? "" : Number(raw).toFixed(2));
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
        const kwh = kwhText(r.kwh);
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
          ${showBuckets ? `<td data-sort="${numAttr(r.samples)}">${r.samples || ""}</td><td data-sort="${numAttr(r.peakKwh)}">${peak || "—"}</td>` : ""}
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
              ${showBuckets ? `<th data-col="5" title="Sort by buckets">Buckets</th><th data-col="6" title="Sort by peak">Peak bucket</th>` : ""}
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
              ${showBuckets ? `<td>${totS || ""}</td><td></td>` : ""}
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
    if (spanDays > 1) {
    addMetric(
      signed ? "Avg net kWh / day" : "Avg import kWh / day",
      acct.avgKwhPerDay,
      "÷ span days",
      { suffix: " kWh" }
    );
    }
    addMetric(
      netAmount ? "Avg net amount / hour" : "Avg import cost / hour",
      acct.avgCostPerHour,
      "",
      { money: true }
    );
    if (spanDays > 1) {
    addMetric(
      netAmount ? "Avg net amount / day" : "Avg import cost / day",
      acct.avgCostPerDay,
      "",
      { money: true }
    );
    }
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
    if (spanDays > 1 && acct.bestDay?.kwh) {
      addMetric(
        signed ? "Highest net day" : "Highest day",
        acct.bestDay.kwh,
        this._fmtRollupKey(acct.bestDay.key),
        { suffix: " kWh" }
      );
    }
    if (spanDays > 1 && acct.worstDay?.kwh != null) {
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
      blocks.push(
        section === "Totals & averages" || section === "Summary"
          ? `
        <div class="usage-summary-section">
          <div class="usage-summary-section-title">${this._escape(section)}</div>
          <div class="usage-summary-items">${items}</div>
        </div>`
          : `
        <details class="usage-accounting usage-summary-section">
          <summary><span class="rollup-title">${this._escape(section)}</span></summary>
          <div class="usage-summary-items">${items}</div>
        </details>`
      );
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
    const stamp = { entryId: this._activeEntryId, gen: this._galleryRenderGen || 0 };
    this._disposeHostCharts(
      this.shadowRoot.getElementById("scatter"),
      this.shadowRoot.getElementById("cost-per-kwh"),
      this.shadowRoot.getElementById("heatmap-kwh"),
      this.shadowRoot.getElementById("heatmap-temp")
    );
    // Weather vs usage and the monthly rate use a fixed year. The header range
    // is hidden on Analytics, and a 24h chip would leave the scatter empty.
    const costRange = rangePresets()["12mo"];
    const historyEnd = publishedDataEnd();
    const ids = account.statistic_ids;
    const colors = seriesColors(this);
    const [kwhDay, tempDay, billAmt, payAmt, costDay, kwhForRate, kwhHistory, tempHistory] =
      await Promise.all([
      fetchStatisticSeries(this._hass, ids.consumption, {
        start: costRange.start,
        end: costRange.end,
        period: "day",
        maxPoints: 400,
      }),
      fetchStatisticSeries(this._hass, ids.temperature, {
        start: costRange.start,
        end: costRange.end,
        period: "day",
        maxPoints: 400,
      }),
      fetchStatisticSeries(this._hass, ids.bill_amount, {
        start: costRange.start,
        end: costRange.end,
        period: "month",
        maxPoints: 48,
      }),
      fetchStatisticSeries(this._hass, ids.payment_amount, {
        start: costRange.start,
        end: costRange.end,
        period: "month",
        maxPoints: 48,
      }),
      fetchStatisticSeries(this._hass, ids.cost, {
        start: costRange.start,
        end: costRange.end,
        period: "day",
        maxPoints: 400,
      }),
      fetchStatisticSeries(this._hass, ids.consumption, {
        start: costRange.start,
        end: costRange.end,
        period: "day",
        maxPoints: 400,
      }),
      fetchStatisticSeries(this._hass, ids.consumption, {
        start: HEATMAP_HISTORY_START,
        end: historyEnd,
        period: "day",
        maxPoints: HEATMAP_MAX_DAYS,
      }),
      fetchStatisticSeries(this._hass, ids.temperature, {
        start: HEATMAP_HISTORY_START,
        end: historyEnd,
        period: "day",
        maxPoints: HEATMAP_MAX_DAYS,
      }),
    ]);
    if (stamp.entryId !== this._activeEntryId || stamp.gen !== (this._galleryRenderGen || 0)) return;

    const scatterHost = this.shadowRoot.getElementById("scatter");
    if (scatterHost) {
      scatterHost.hidden = false;
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
      else scatterHost.hidden = true;
    }

    const cpkHost = this.shadowRoot.getElementById("cost-per-kwh");
    if (cpkHost) {
      const { xs, ys } = this._monthlyRateSeries(kwhForRate, costDay);
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

    const heatWindow = this._heatmapWindowKey(); // 12mo default, or a year, or all
    const kwhWindow = this._sliceHeatmap(kwhHistory.xs, kwhHistory.values, heatWindow);
    const tempWindow = this._sliceHeatmap(tempHistory.xs, tempHistory.means, heatWindow);
    this._renderHeatmapChips(kwhHistory.xs);
    const hmKwh = await renderHeatmap(this.shadowRoot.getElementById("heatmap-kwh"), {
      xs: kwhWindow.xs,
      ys: kwhWindow.ys,
      title: "Daily kWh (imported history)",
      onClick: (ymd) => this._openUsageDay(ymd),
    });
    const hmTemp = await renderHeatmap(this.shadowRoot.getElementById("heatmap-temp"), {
      xs: tempWindow.xs,
      ys: tempWindow.ys,
      diverging: true,
      title: "Daily avg temperature (imported history)",
    });
    if (hmKwh) this._charts.push(hmKwh);
    if (hmTemp) this._charts.push(hmTemp);
  }

  _openUsageDay(ymd) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(ymd || "")) return;
    const published = pacificYmd(new Date(publishedDataEnd().getTime() - 1));
    if (ymd > published) return;
    const [year, month, day] = ymd.split("-").map(Number);
    const next = new Date(Date.UTC(year, month - 1, day + 1));
    const nextYmd = `${next.getUTCFullYear()}-${String(next.getUTCMonth() + 1).padStart(2, "0")}-${String(next.getUTCDate()).padStart(2, "0")}`;
    this._customRange = { start: pacificMidnightUtc(ymd), end: pacificMidnightUtc(nextYmd) };
    this._rangeShift = 0;
    this._period = "hour";
    this._selectPanelTab("usage", { writeHistory: true });
    this._renderFilters();
    void this._renderRangeScope();
  }

  _heatmapWindowKey() {
    try {
      return localStorage.getItem("pge_heatmap_window") || "12mo";
    } catch (_err) {
      return "12mo";
    }
  }

  _sliceHeatmap(xs, ys, windowKey) {
    const pairs = (xs || []).map((ts, index) => ({ ts, value: ys?.[index] }));
    if (!pairs.length || windowKey === "all") return { xs: xs || [], ys: ys || [] };
    const end = publishedDataEnd();
    const endYmd = pacificYmd(new Date(end.getTime() - 1));
    let startYmd = "0000-01-01";
    let stopYmd = "9999-12-31";
    if (windowKey === "12mo") {
      const [year, month] = endYmd.split("-").map(Number);
      const start = new Date(Date.UTC(year, month - 12, 1));
      startYmd = `${start.getUTCFullYear()}-${String(start.getUTCMonth() + 1).padStart(2, "0")}-01`;
      stopYmd = endYmd;
    } else if (/^\d{4}$/.test(windowKey)) {
      startYmd = `${windowKey}-01-01`;
      stopYmd = `${windowKey}-12-31`;
    }
    const kept = pairs.filter((row) => {
      const ymd = pacificYmd(row.ts);
      return ymd >= startYmd && ymd <= stopYmd;
    });
    return { xs: kept.map((row) => row.ts), ys: kept.map((row) => row.value) };
  }

  _renderHeatmapChips(xs) {
    const host = this.shadowRoot.getElementById("heatmap-chips");
    if (!host) return;
    const years = [...new Set((xs || []).map((ts) => pacificYmd(ts).slice(0, 4)))].sort();
    const current = this._heatmapWindowKey();
    const recent = years.slice(-2);
    const older = years.filter((year) => !recent.includes(year));
    const chips = ["12mo", ...recent];
    const olderOptions = older
      .map((year) => `<option value="${year}" ${year === current ? "selected" : ""}>${year}</option>`)
      .join("");
    host.innerHTML = `
      ${chips.map((key) => {
        const label = key === "12mo" ? "12 months" : key;
        return `<button type="button" class="chip" data-heat="${key}" aria-pressed="${key === current}">${label}</button>`;
      }).join("")}
      ${olderOptions ? `<select class="range-more" data-heat-more aria-label="More years"><option value="" ${older.includes(current) ? "" : "selected"}>More years…</option>${olderOptions}</select>` : ""}
      <button type="button" class="chip" data-heat="all" aria-pressed="${current === "all"}">All years</button>
    `;
    const choose = async (key) => {
      if (!key) return;
      try {
        localStorage.setItem("pge_heatmap_window", key);
      } catch (_err) {
        /* storage can be unavailable */
      }
      await this._renderInsights();
    };
    host.querySelectorAll("[data-heat]").forEach((btn) => {
      btn.addEventListener("click", () => choose(btn.dataset.heat));
    });
    host.querySelector("[data-heat-more]")?.addEventListener("change", (ev) => choose(ev.target.value));
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
      <details class="usage-accounting">
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
      html += `<div class="tod-grid-label"><span class="tod-day-full">${this._escape(day.name)}</span><span class="tod-day-short">${this._escape(day.name.slice(0, 3))}</span></div>`;
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
    const available = new Set(this._availablePresets || RANGE_PRESET_TOD);
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
    const primaryButtons = RANGE_PRESET_TOD.map((k) => {
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
    const customOpen = !!this._todRangeCustomOpen || customActive;
    return `
      <div class="filters tod-range" aria-label="TOD estimate range">
        <div class="range-row">
          <div class="seg range-presets" role="group" aria-label="TOD range presets">
            ${primaryButtons}
          </div>
          <div class="range-tools">
            <span class="range-label">${this._escape(label)}</span>
            <button type="button" class="ghost range-custom-toggle" id="tod-range-custom-toggle" aria-expanded="${
              customOpen ? "true" : "false"
            }" aria-pressed="${customOpen ? "true" : "false"}" aria-controls="tod-range-custom" aria-label="Custom range"><ha-icon icon="mdi:calendar-range"></ha-icon></button>
            <select id="tod-range-more" class="range-more ghost ${moreActive ? "active" : ""}" aria-label="More TOD ranges">
              <option value="" ${moreActive ? "" : "selected"}>More…</option>
              ${moreOptions}
            </select>
            ${this._hint("Window for the local savings and cost estimate. Independent of Usage. Custom ranges longer than 60 days are clipped to the newest 60 days so hourly totals stay exact.")}
          </div>
        </div>
        <div class="range-custom" id="tod-range-custom" ${customOpen ? "" : "hidden"}>
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
    host.querySelector("#tod-range-custom-toggle")?.addEventListener("click", async () => {
      this._todRangeCustomOpen = !this._todRangeCustomOpen;
      await this._renderTod();
    });
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
        this._todRangeCustomOpen = true;
        this._todRangeTouched = true;
        await this._renderTod();
      });
    }
    const active = host.querySelector("[data-tod-range].active");
    const scroller = active?.closest(".seg.range-presets");
    if (active && scroller) {
      const left = active.offsetLeft - Math.max(0, (scroller.clientWidth - active.offsetWidth) / 2);
      scroller.scrollLeft = Math.max(0, left);
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
    this._todDirty = false;
    this._disposeHostCharts(el);
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
    let nextValue = "—";
    let nextDelta = "—";
    if (nextAt) {
      const when = new Date(nextAt);
      const parts = pacificParts(new Date(nextAt));
      const nextPeriod = todPeriodForPacific(parts.ymd, parts.hour);
      const clock = new Intl.DateTimeFormat("en-US", {
        timeZone: "America/Los_Angeles",
        hour: "numeric",
        minute: "2-digit",
      }).format(when);
      nextValue = `${TOD_PERIOD_LABELS[nextPeriod] || nextPeriod} at ${clock}`;
      nextDelta = `in ${this._todCountdown(nextAt)}`;
    }
    const dayNote = tod.is_holiday
      ? "Holiday — off-peak all day"
      : tod.is_weekend
        ? "Weekend — off-peak all day"
        : "Weekday schedule";
    const sourceHint = `Live rate: ${sourceLabel}${fetched}`;
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
          <h3>Usage by period ${this._hint("PGE usage estimate: the portal hourly amount. It may ignore Time of Day and is not a billed charge.")}</h3>
          <p class="muted" style="margin:0 0 8px">${windowNote}</p>
          ${this._todShareBar(kwh)}
          <table class="tod-table">
            <thead><tr><th>Period</th><th class="num">Energy</th><th class="num">Cost</th><th class="num">Share</th><th class="num">Avg portal ¢/kWh</th></tr></thead>
            <tbody>${rows}</tbody>
            <tfoot><tr><td>Total</td><td class="num">${this._fmt(totalKwh, " kWh")}</td><td class="num">${this._fmt(importedCost, "", true)}</td><td class="num">100%</td><td class="num">—</td></tr></tfoot>
          </table>
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
      <section class="card">
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
        <div class="kpi"><div class="label">Next transition</div><div class="value">${this._escape(nextValue)}</div><div class="delta">${this._escape(nextDelta)}</div></div>
      </div>
      <div class="tod-schedule">
        <h3>Week schedule (Pacific) ${this._hint("Time of Day periods are off-peak, mid-peak, and on-peak. The hours change by season and are all off-peak on weekends and holidays. Weekday windows (Pacific): off-peak 12am–7am and 9pm–12am, mid-peak 7am–5pm, on-peak 5pm–9pm.")}</h3>
        <div class="tod-legend">
          ${TOD_PERIODS.map((p) => `<span class="legend ${p}"><i></i>${TOD_PERIOD_LABELS[p]}</span>`).join("")}
          <span class="muted" style="margin-left:auto">Highlighted column = now</span>
        </div>
        ${this._todWeekGrid()}
        ${this._todHolidayNote()}
      </div>
      </section>
      <section class="card">
      <div class="usage-accounting tod-usage">
        ${this._todRangeControlsHtml()}
        ${usageHtml}
        ${savingsHtml}
      </div>
      ${this._tariffStatusHtml(tariffStatus, todCatalog, basicCatalog)}
      </section>
      ${this._todGalleryHtml()}
    `;
    if (gen !== this._todRenderGen) return;
    this._bindPersistentDetails(el);
    this._bindTodRange(el);
    await this._softGallery(() => this._renderTodGallery());
  }

  _tariffStatusHtml(status, todCatalog, basicCatalog) {
    const hasData = todCatalog.length > 0 || basicCatalog.length > 0;
    const lastAttempt = status.last_attempt ? this._fmtDate(status.last_attempt) : "never";
    const lastSuccess = status.last_success ? this._fmtDate(status.last_success) : "never";
    const isStale = status.is_stale;
    const hasStatus = status.last_attempt || status.last_success || status.is_stale !== undefined;
    const lastError = status.last_error || null;
    const catalogState = !hasStatus ? "unknown" : isStale ? "stale" : "current";
    const statusBadge = !hasStatus ? `<span class="badge unknown">unknown</span>` : isStale ? `<span class="badge off">stale</span>` : `<span class="badge on">current</span>`;
    const effectiveRow = todCatalog.length > 0 ? todCatalog[todCatalog.length - 1] : null;
    const effectiveFrom = effectiveRow?.effective_from || null;
    const periodLabel = effectiveFrom ? ` effective ${this._escape(effectiveFrom)}` : "";
    const catalogTitle = effectiveFrom
      ? `Catalog: ${catalogState} (effective ${effectiveFrom})`
      : `Catalog: ${catalogState}`;
    return `
      <details class="tariff-status-block" data-persist="tariff_status"${this._detailsOpenAttr("tariff_status")}>
        <summary><span class="rollup-title">${this._escape(catalogTitle)} ${statusBadge}</span></summary>
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

    // Rate-card lines — these are the *current* effective-dated rate cards,
    // not per-hour values.  The totals are computed per-hour using the
    // catalog row effective on each slot's Pacific date (see
    // estimatePlanCostSeries), so the rates shown here may not match the
    // blended per-hour rates when the window crosses a tariff effective date.
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
      const reasonCode = reconciled.diagnostics?.reason || "";
      const reason =
        reasonCode === "no_official_data"
          ? "PGE has no official comparison for this account"
          : "Comparison unavailable";
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
              ${line(`TOD (${this._escape(sourceLabel)})`, money(localTodTotal), this._escape(`${rateList} ¢/kWh`), "Per-hour estimate: period kWh × effective-dated catalog rates. Rate shown is the current card; hourly rates may vary when the window crosses a tariff effective date.")}
              ${line(`Basic (${this._escape(basicSrc)})${basicEffNote}`, money(localBasicTotal), basicCents, `Per-hour estimate: kWh × effective-dated Basic rate. Rate shown is the current card; hourly rates may vary across tariff effective dates.${basisNote}${exclNote}`)}
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

  _renderBillingPrograms(mountGallery = false) {
    const billing = this.shadowRoot.getElementById("billing");
    const programs = this.shadowRoot.getElementById("programs");
    if (!billing || !programs || !this._account) return;
    const e = this._account.entity_ids;
    const includeBilling = this._account.options?.include_billing !== false;

    if (!includeBilling) {
      this._disposeHostCharts(billing);
      billing.innerHTML = `<h2>Billing</h2><p class="muted">Billing import is disabled in Configure → Sync settings.</p>`;
      programs.innerHTML = `<h2>Programs</h2><p class="muted">Enable billing & programs to see enrollment.</p>${this._ptrEventHtml(e)}`;
      return false;
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
    if (!mountGallery && this._patchBillingText(summaryHtml)) {
      this._renderProgramsCard(programs, e);
      return false;
    }
    this._disposeHostCharts(billing);
    const summaryContent =
      summaryHtml ||
      `<p class="muted stats-meta">No billing values yet — wait for a sync or check Configure → Sync settings.</p>`;
    const headerHtml = this._renderBillPdfHeader();
    const detailsHtml = this._renderBillPdfStatementDetails();
    billing.innerHTML = `
      <section class="card">
      <h2>Billing ${this._hint("Account balance, statement, and lifetime totals from PGE billing sync. Ledger charts use external statistic ids, including bill kWh, which has no mirrored entity.")}</h2>
      <div id="billing-pdf-header">${headerHtml}</div>
      <div class="usage-accounting-body">
        <div id="billing-summary">
        ${summaryContent}
        </div>
      </div>
      </section>
      <section class="card">
        <div id="billing-pdf-details">${detailsHtml}</div>
      </section>
      <section class="card">
        <figure class="chart-card">
          <div class="fig-head"><h3 class="fig-title"><span class="fig-title-text">Billed vs paid</span></h3></div>
          <div class="chart-host" id="ledger-bill"></div>
        </figure>
        <figure class="chart-card">
          <div class="fig-head"><h3 class="fig-title"><span class="fig-title-text">Billed kWh</span></h3></div>
          <div class="chart-host" id="ledger-kwh"></div>
        </figure>
      </section>
      ${this._billingGalleryHtml()}
    `;
    this._billingSummarySig = summaryContent;
    this._billingPdfHeaderSig = headerHtml;
    this._billingPdfDetailsSig = detailsHtml;
    this._bindPersistentDetails(billing);
    this._renderProgramsCard(programs, e);
    return true;
  }

  _patchBillingText(summaryHtml) {
    const summary = this.shadowRoot.getElementById("billing-summary");
    const pdfHeader = this.shadowRoot.getElementById("billing-pdf-header");
    const pdfDetails = this.shadowRoot.getElementById("billing-pdf-details");
    if (!summary || !pdfHeader || !pdfDetails) return false;
    const html =
      summaryHtml ||
      `<p class="muted stats-meta">No billing values yet — wait for a sync or check Configure → Sync settings.</p>`;
    // Skip DOM replacement per region when content is unchanged — preserves
    // open <details> state across hass pushes that don't alter that region's values.
    if (html !== this._billingSummarySig) {
      this._billingSummarySig = html;
      summary.innerHTML = html;
    }
    const headerHtml = this._renderBillPdfHeader();
    if (headerHtml !== this._billingPdfHeaderSig) {
      this._billingPdfHeaderSig = headerHtml;
      pdfHeader.innerHTML = headerHtml;
    }
    const detailsHtml = this._renderBillPdfStatementDetails();
    if (detailsHtml !== this._billingPdfDetailsSig) {
      this._billingPdfDetailsSig = detailsHtml;
      pdfDetails.innerHTML = detailsHtml;
    }
    return true;
  }

  _renderProgramsCard(programs, e) {
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
      ${this._ptrEventHtml(e)}
    `;
  }

  _ptrEventHtml(e) {
    const active = stateDisplay(this._hass, e.ptr_event_active, null);
    const detected = stateDisplay(this._hass, e.ptr_event_detected, null);
    const start = stateDisplay(this._hass, e.ptr_event_start, null);
    const end = stateDisplay(this._hass, e.ptr_event_end, null);
    const sections = [];
    if (active === "on") {
      sections.push(`<div class="program on">
        <div class="name">Peak Time Event Active</div>
        <div class="state">${this._escape(start)} – ${this._escape(end)}</div>
      </div>`);
    } else if (start != null) {
      sections.push(`<div class="program">
        <div class="name">Scheduled PTR Event</div>
        <div class="state">${this._escape(start)} – ${this._escape(end)}</div>
      </div>`);
    }
    if (detected === "on") {
      const detDate = stateAttr(this._hass, e.ptr_event_detected, "event_date");
      sections.push(`<div class="program on">
        <div class="name">PTR Event Detected</div>
        <div class="state">${this._escape(detDate || "Unknown date")}</div>
      </div>`);
    }
    if (sections.length === 0) return "";
    return `<div class="programs ptr-events">${sections.join("")}</div>`;
  }

  async _renderLedgerCharts() {
    const account = this._account;
    if (!account) return;
    const stamp = { entryId: this._activeEntryId, gen: this._galleryRenderGen || 0 };
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
      if (stamp.entryId !== this._activeEntryId || stamp.gen !== (this._galleryRenderGen || 0)) return;
      const money = await createMonthCompareChart(billHost, {
        billedXs: bill.xs,
        billedYs: bill.values,
        payXs: pay.xs,
        payYs: pay.values,
        colors,
      });
      if (stamp.entryId !== this._activeEntryId || stamp.gen !== (this._galleryRenderGen || 0)) {
        try {
          money?.destroy?.();
        } catch (_err) {
          /* account changed while the ledger chart was initializing */
        }
        return;
      }
      if (money) this._charts.push(money);
      const kwhChart = await createBarChart(kwhHost, {
        xs: kwh.xs,
        ys: kwh.values,
        labelY: "Bill kWh",
        color: colors.kwh,
        unit: " kWh",
      });
      if (kwhChart && (stamp.entryId !== this._activeEntryId || stamp.gen !== (this._galleryRenderGen || 0))) {
        try {
          kwhChart.destroy?.();
        } catch (_err) {
          /* account changed while the ledger chart was initializing */
        }
      } else if (kwhChart) {
        this._charts.push(kwhChart);
      }
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
          this._fmtPacificDateTime(sync.auth_expiration) ||
            this._fmtPacificDateTime(stateDisplay(this._hass, e.auth_expiration)) ||
            stateDisplay(this._hass, e.auth_expiration)
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
        <div class="entity-row"><span>Last Recorded PTR Event</span><strong>${this._escape(
          this._lastRecordedPtrLabel(e)
        )}</strong></div>
      </div>
    `;
  }

  _lastRecordedPtrLabel(e) {
    const events = stateAttr(this._hass, e?.program_peak_time_rebates, "peak_time_events");
    if (!Array.isArray(events) || events.length === 0) return "—";
    const newest = events[events.length - 1];
    if (!newest || typeof newest !== "object") return "—";
    const date = newest.event_date ? String(newest.event_date) : "";
    const credit =
      newest.event_earned_credit != null && newest.event_earned_credit !== ""
        ? ` · $${newest.event_earned_credit}`
        : "";
    const label = `${date}${credit}`.trim();
    return label || "—";
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

  /** Pacific clock time, for example "Oct 13, 1:00 AM PT". */
  _fmtPacificDateTime(value) {
    if (value == null || value === "" || value === "—" || value === "unknown" || value === "unavailable") {
      return "";
    }
    const d = value instanceof Date ? value : new Date(value);
    if (!Number.isFinite(d.getTime())) return "";
    const formatted = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }).format(d);
    return `${formatted} PT`;
  }

  /** Keep each YYYY-MM-DD intact so a 4-column tile wraps at the arrow, not at a hyphen. */
  _fmtRangeDelta(text) {
    const parts = String(text || "").split(" → ");
    if (parts.length === 2 && parts[0] && parts[1]) {
      return `<span class="date">${this._escape(parts[0])}</span> → <span class="date">${this._escape(parts[1])}</span>`;
    }
    return this._escape(text || "");
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
