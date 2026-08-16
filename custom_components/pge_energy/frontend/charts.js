/**
 * Apache ECharts loaders for the PGE panel.
 * Usage hero is one combined chart (kWh + cost + °F). Insight plots stay single-series.
 * Colors resolve from the panel host / HA theme — never assume light-mode hex.
 * @see https://echarts.apache.org/examples/en/index.html
 */

import {
  formatSignedUsd,
  projectDirectionalUsage,
  symmetricExtent,
} from "./data.js?v=0.9.13";
import {
  chromeColors,
  seriesColors,
  tooltipTheme,
  withAlpha,
} from "./theme.js?v=0.9.13";

export { seriesColors };

/** Shared height for Cost intelligence pair ($/kWh + billed/payments). */
const COST_PAIR_HEIGHT = 200;

/** Round float-noise from recorder deltas for human-facing labels (chart data stays raw). */
function formatDisplayNumber(value, digits = 2) {
  if (value == null || value === "" || value === "-") return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return Number(n.toFixed(digits));
}

function formatKwhLabel(value) {
  const n = formatDisplayNumber(value, 2);
  return n == null ? "—" : `${n} kWh`;
}

function formatCostLabel(value) {
  return formatSignedUsd(value, 2);
}

function formatTempLabel(value) {
  const n = formatDisplayNumber(value, 1);
  return n == null ? "—" : `${n} °F`;
}

let _echartsPromise = null;

export async function ensureEcharts() {
  if (window.echarts) return window.echarts;
  if (!_echartsPromise) {
    _echartsPromise = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "/pge_energy_frontend/vendor/echarts.min.js";
      s.onload = () => {
        if (window.echarts) resolve(window.echarts);
        else reject(new Error("ECharts loaded but window.echarts missing"));
      };
      s.onerror = () => reject(new Error("Failed to load Apache ECharts"));
      document.head.appendChild(s);
    });
  }
  return _echartsPromise;
}

function themeColors(el) {
  return chromeColors(el);
}

/** Prefer the panel custom element so `:host` PGE tokens resolve. */
function resolveRoot(host) {
  return host?.getRootNode?.()?.host || host || document.documentElement;
}

function prefersReducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Shared enter/update motion — disabled when the user prefers reduced motion. */
function chartMotion() {
  if (prefersReducedMotion()) {
    return {
      animation: false,
      animationDuration: 0,
      animationDurationUpdate: 0,
    };
  }
  return {
    animation: true,
    animationDuration: 420,
    animationEasing: "cubicOut",
    animationDurationUpdate: 280,
    animationEasingUpdate: "cubicOut",
  };
}

function ringBorder(theme) {
  return theme.surface || theme.page || "#fff";
}

/** Axis-hover emphasis for line points — grow + ring + glow. */
function linePointEmphasis(color, theme) {
  return {
    focus: "none",
    scale: true,
    symbolSize: 14,
    itemStyle: {
      color,
      borderColor: ringBorder(theme),
      borderWidth: 2.5,
      shadowBlur: 14,
      shadowColor: withAlpha(color, 0.65),
    },
    lineStyle: {
      width: 4,
      shadowBlur: 8,
      shadowColor: withAlpha(color, 0.35),
    },
  };
}

/** Bar hover — lift glow without dimming sibling series. */
function barEmphasis(color) {
  return {
    focus: "none",
    itemStyle: {
      shadowBlur: 14,
      shadowColor: withAlpha(color, 0.5),
      borderColor: withAlpha(color, 0.95),
      borderWidth: 1,
    },
  };
}

/** Scatter hover — pop the point; soft-blur the rest of the cloud. */
function scatterPointEmphasis(color, theme) {
  return {
    focus: "self",
    scale: true,
    itemStyle: {
      color,
      opacity: 1,
      borderColor: ringBorder(theme),
      borderWidth: 2.5,
      shadowBlur: 18,
      shadowColor: withAlpha(color, 0.7),
    },
  };
}

function scatterPointBlur() {
  return {
    itemStyle: { opacity: 0.22 },
  };
}

/** Calendar heatmap cell hover. */
function heatmapCellEmphasis(theme) {
  return {
    itemStyle: {
      borderColor: theme.text,
      borderWidth: 1.5,
      shadowBlur: 10,
      shadowColor: withAlpha(theme.text, 0.35),
    },
  };
}

function toMsPairs(xs, ys) {
  const out = [];
  for (let i = 0; i < xs.length; i++) {
    const y = ys[i];
    if (y == null || Number.isNaN(Number(y))) continue;
    const t = xs[i];
    // xs are unix seconds from the data layer.
    out.push([typeof t === "number" && t < 1e12 ? t * 1000 : t, Number(y)]);
  }
  return out;
}

function wrapChart(chart) {
  return {
    chart,
    destroy() {
      try {
        chart.dispose();
      } catch (_e) {
        /* ignore */
      }
    },
  };
}

function baseTimeOption({ labelY, color, unit, height, root }) {
  const theme = themeColors(root);
  const tip = tooltipTheme(root);
  return {
    ...chartMotion(),
    backgroundColor: theme.bg,
    color: [color],
    grid: { left: 48, right: 16, top: 28, bottom: 28 },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross", link: [{ xAxisIndex: "all" }], snap: true },
      backgroundColor: tip.backgroundColor,
      borderColor: tip.borderColor,
      textStyle: tip.textStyle,
      valueFormatter: (v) =>
        v == null || Number.isNaN(Number(v))
          ? "—"
          : `${Number(v).toFixed(2)}${unit || ""}`,
    },
    legend: {
      show: true,
      top: 0,
      textStyle: { color: theme.text },
    },
    xAxis: {
      type: "time",
      axisLabel: { color: theme.muted },
      axisLine: { lineStyle: { color: theme.grid } },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      name: labelY || "",
      nameTextStyle: { color: theme.muted },
      axisLabel: {
        color: theme.muted,
        formatter: (v) => `${v}${unit || ""}`,
      },
      splitLine: { lineStyle: { color: theme.grid } },
    },
    // Keep chart height stable for stacked multiples.
    // (container height is set by the host element)
    _height: height,
  };
}

/** Scale chart host height down on tablet/phone so canvases fit narrow viewports. */
function responsiveChartHeight(base) {
  const w = window.innerWidth || base;
  if (w <= 640) return Math.max(160, Math.round(base * 0.68));
  if (w <= 900) return Math.max(180, Math.round(base * 0.82));
  return base;
}

async function mount(host, option, { height = 160, group = null, onLayout = null } = {}) {
  const echarts = await ensureEcharts();
  host.replaceChildren();
  host.style.width = "100%";
  host.style.maxWidth = "100%";
  const applyHeight = () => {
    host.style.height = `${responsiveChartHeight(height)}px`;
  };
  applyHeight();
  const chart = echarts.init(host, null, { renderer: "canvas" });
  chart.setOption(option);
  if (group) {
    chart.group = group;
    echarts.connect(group);
  }
  const applyLayout = () => {
    try {
      applyHeight();
      if (typeof onLayout === "function") onLayout(chart, host);
      chart.resize();
    } catch (_e) {
      /* ignore */
    }
  };
  // Host width is often 0 during the first paint inside the shadow tree.
  requestAnimationFrame(() => requestAnimationFrame(applyLayout));
  window.addEventListener("resize", applyLayout);
  const wrapped = wrapChart(chart);
  const origDestroy = wrapped.destroy;
  wrapped.destroy = () => {
    window.removeEventListener("resize", applyLayout);
    origDestroy();
  };
  return wrapped;
}

/** Muted empty-state placeholder inside a chart host. */
export function showChartEmpty(host, message) {
  if (!host) return null;
  host.replaceChildren();
  host.style.height = "auto";
  host.style.minHeight = "0";
  const p = document.createElement("p");
  p.className = "muted chart-empty";
  p.textContent = message || "No data in this range yet.";
  host.appendChild(p);
  return null;
}

function _finitePairs(xs, ys) {
  const out = [];
  for (let i = 0; i < (xs || []).length; i++) {
    const x = xs[i];
    const y = ys[i];
    if (x == null || y == null || Number.isNaN(Number(y))) continue;
    out.push([x, Number(y)]);
  }
  return out;
}

/** Pad a [min,max] span so scatter/line axes don't hug the data. */
function _paddedExtent(values, padRatio = 0.08, hardMin = null) {
  const nums = values.filter((v) => v != null && Number.isFinite(Number(v))).map(Number);
  if (!nums.length) return null;
  let min = Math.min(...nums);
  let max = Math.max(...nums);
  if (min === max) {
    min -= Math.abs(min) * 0.05 || 1;
    max += Math.abs(max) * 0.05 || 1;
  }
  const pad = (max - min) * padRatio;
  min -= pad;
  max += pad;
  if (hardMin != null) min = Math.max(hardMin, min);
  return [min, max];
}

export async function createBarChart(host, { xs, ys, labelY, color, unit }) {
  const root = resolveRoot(host);
  const pairs = _finitePairs(xs, ys).filter(([, y]) => y !== 0);
  if (pairs.length < 1) return showChartEmpty(host, `No ${labelY || "values"} yet.`);
  const useCategory = pairs.length <= 36;
  const categories = useCategory
    ? pairs.map(([t]) =>
        new Intl.DateTimeFormat("en-US", {
          timeZone: "America/Los_Angeles",
          month: "short",
          year: "2-digit",
        }).format(new Date(typeof t === "number" && t < 1e12 ? t * 1000 : t))
      )
    : null;
  const data = useCategory
    ? pairs.map(([, y]) => y)
    : pairs.map(([t, y]) => [typeof t === "number" && t < 1e12 ? t * 1000 : t, y]);
  const theme = themeColors(root);
  const tip = tooltipTheme(root);
  const option = {
    ...baseTimeOption({ labelY, color, unit, height: 160, root }),
    ...chartMotion(),
    tooltip: {
      trigger: "axis",
      axisPointer: {
        type: "shadow",
        snap: true,
        shadowStyle: { color: withAlpha(color, 0.14) },
      },
      backgroundColor: tip.backgroundColor,
      borderColor: tip.borderColor,
      textStyle: tip.textStyle,
    },
    xAxis: useCategory
      ? {
          type: "category",
          data: categories,
          axisLabel: { color: theme.muted, hideOverlap: true },
          axisLine: { lineStyle: { color: theme.grid } },
        }
      : {
          type: "time",
          axisLabel: { color: theme.muted },
          axisLine: { lineStyle: { color: theme.grid } },
          splitLine: { show: false },
        },
    series: [
      {
        name: labelY || "Value",
        type: "bar",
        data,
        barWidth: useCategory ? "55%" : undefined,
        barMaxWidth: useCategory ? 48 : 28,
        barCategoryGap: "18%",
        itemStyle: { color, borderRadius: [3, 3, 0, 0] },
        emphasis: barEmphasis(color),
      },
    ],
  };
  return mount(host, option, { height: 160, group: "pge-insights" });
}

/** Side-by-side monthly billed vs payments — only months with either value. */
export async function createMonthCompareChart(host, { billedXs, billedYs, payXs, payYs, colors }) {
  const root = resolveRoot(host);
  const theme = themeColors(root);
  const tip = tooltipTheme(root);
  const c = colors || seriesColors(root);
  const billMap = _pairMap(billedXs, billedYs);
  const payMap = _pairMap(payXs, payYs);
  const months = [...new Set([...billMap.keys(), ...payMap.keys()])]
    .filter((ms) => {
      const b = billMap.get(ms);
      const p = payMap.get(ms);
      return (b != null && b !== 0) || (p != null && p !== 0);
    })
    .sort((a, b) => a - b);
  if (months.length < 1) {
    return showChartEmpty(host, "No billed or payment history in range yet.");
  }
  const categories = months.map((ms) =>
    new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      month: "short",
      year: "2-digit",
    }).format(new Date(ms))
  );
  const billed = months.map((ms) => billMap.get(ms) ?? null);
  const paid = months.map((ms) => payMap.get(ms) ?? null);
  const option = {
    ...chartMotion(),
    backgroundColor: theme.bg,
    grid: { left: 52, right: 16, top: 28, bottom: 28 },
    legend: {
      show: true,
      top: 0,
      data: ["Billed", "Payments"],
      textStyle: { color: theme.text },
    },
    tooltip: {
      trigger: "axis",
      axisPointer: {
        type: "shadow",
        snap: true,
        shadowStyle: { color: withAlpha(c.cost, 0.12) },
      },
      backgroundColor: tip.backgroundColor,
      borderColor: tip.borderColor,
      textStyle: tip.textStyle,
      valueFormatter: (v) => (v == null ? "—" : `$${Number(v).toFixed(2)}`),
    },
    xAxis: {
      type: "category",
      data: categories,
      axisLabel: { color: theme.muted, hideOverlap: true },
      axisLine: { lineStyle: { color: theme.grid } },
    },
    yAxis: {
      type: "value",
      min: 0,
      nameTextStyle: { color: theme.muted },
      axisLabel: {
        color: theme.muted,
        formatter: (v) => `$${v}`,
      },
      splitLine: { lineStyle: { color: theme.grid } },
    },
    series: [
      {
        name: "Billed",
        type: "bar",
        data: billed,
        barWidth: "40%",
        barGap: "12%",
        barCategoryGap: "20%",
        itemStyle: { color: c.cost, borderRadius: [3, 3, 0, 0] },
        emphasis: barEmphasis(c.cost),
      },
      {
        name: "Payments",
        type: "bar",
        data: paid,
        barWidth: "40%",
        itemStyle: { color: c.payment, borderRadius: [3, 3, 0, 0] },
        emphasis: barEmphasis(c.payment),
      },
    ],
  };
  return mount(host, option, { height: COST_PAIR_HEIGHT });
}

export async function createLineChart(host, { xs, ys, labelY, color, unit, breakGaps = true, monthly = false }) {
  const root = resolveRoot(host);
  const theme = themeColors(root);
  const tip = tooltipTheme(root);
  const pairs = _finitePairs(xs, ys).filter(([, y]) => Number.isFinite(y));
  if (pairs.length < 2) return showChartEmpty(host, `Not enough ${labelY || "samples"} yet.`);
  const yExtent = _paddedExtent(
    pairs.map(([, y]) => y),
    0.15,
    null
  );
  const yMin = yExtent ? Number(yExtent[0].toFixed(4)) : undefined;
  const yMax = yExtent ? Number(yExtent[1].toFixed(4)) : undefined;

  // Monthly rates: category axis so sparse months don't stretch like a time series.
  if (monthly || pairs.length <= 18) {
    const categories = pairs.map(([t]) =>
      new Intl.DateTimeFormat("en-US", {
        timeZone: "America/Los_Angeles",
        month: "short",
        year: "2-digit",
      }).format(new Date(typeof t === "number" && t < 1e12 ? t * 1000 : t))
    );
    const option = {
      ...chartMotion(),
      backgroundColor: theme.bg,
      grid: { left: 52, right: 16, top: 28, bottom: 28 },
      legend: {
        show: true,
        top: 0,
        textStyle: { color: theme.text },
      },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "line", snap: true },
        backgroundColor: tip.backgroundColor,
        borderColor: tip.borderColor,
        textStyle: tip.textStyle,
        valueFormatter: (v) =>
          v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(3),
      },
      xAxis: {
        type: "category",
        data: categories,
        boundaryGap: false,
        axisLabel: { color: theme.muted, hideOverlap: true },
        axisLine: { lineStyle: { color: theme.grid } },
      },
      yAxis: {
        type: "value",
        name: labelY || "",
        min: yMin,
        max: yMax,
        scale: true,
        nameTextStyle: { color: theme.muted },
        axisLabel: {
          color: theme.muted,
          formatter: (v) => Number(v).toFixed(3),
        },
        splitLine: { lineStyle: { color: theme.grid } },
      },
      series: [
        {
          name: labelY || "Value",
          type: "line",
          data: pairs.map(([, y]) => y),
          symbol: "circle",
          showSymbol: true,
          symbolSize: 7,
          connectNulls: true,
          smooth: 0.2,
          lineStyle: { width: 2.5, color },
          itemStyle: { color },
          areaStyle: { color: withAlpha(color, 0.12) },
          emphasis: linePointEmphasis(color, theme),
        },
      ],
    };
    return mount(host, option, { height: COST_PAIR_HEIGHT });
  }

  // Null markers break the stroke across multi-day holes (no fake diagonals).
  const data = [];
  const gapMs = 3 * 24 * 60 * 60 * 1000;
  for (let i = 0; i < pairs.length; i++) {
    const [t, y] = pairs[i];
    const ms = typeof t === "number" && t < 1e12 ? t * 1000 : Number(t);
    if (breakGaps && i > 0) {
      const prev = pairs[i - 1][0];
      const prevMs = typeof prev === "number" && prev < 1e12 ? prev * 1000 : Number(prev);
      if (ms - prevMs > gapMs) data.push([prevMs + 1, null]);
    }
    data.push([ms, y]);
  }
  const base = baseTimeOption({ labelY, color, unit, height: COST_PAIR_HEIGHT, root });
  const option = {
    ...base,
    ...chartMotion(),
    yAxis: {
      ...base.yAxis,
      min: yMin,
      max: yMax,
      scale: true,
      splitLine: { lineStyle: { color: theme.grid } },
    },
    series: [
      {
        name: labelY || "Value",
        type: "line",
        data,
        symbol: "circle",
        showSymbol: true,
        symbolSize: pairs.length <= 24 ? 6 : 4,
        connectNulls: false,
        smooth: 0.15,
        lineStyle: { width: 2.5, color },
        itemStyle: { color },
        areaStyle: { color: withAlpha(color, 0.12) },
        emphasis: linePointEmphasis(color, theme),
      },
    ],
  };
  return mount(host, option, { height: COST_PAIR_HEIGHT });
}

function _pairMap(xs, ys) {
  const map = new Map();
  for (let i = 0; i < (xs || []).length; i++) {
    const y = ys?.[i];
    if (y == null || Number.isNaN(Number(y))) continue;
    const t = xs[i];
    const ms = typeof t === "number" && t < 1e12 ? t * 1000 : Number(t);
    if (!Number.isFinite(ms)) continue;
    map.set(ms, Number(y));
  }
  return map;
}

function _categoryLabel(ms) {
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Los_Angeles",
    month: "short",
    day: "numeric",
    hour: "numeric",
  }).format(new Date(ms));
}

/** Single Usage chart: signed grid-flow bars + amount + outdoor temperature. */
export async function createUsageComboChart(
  host,
  { kwh, returned, cost, compensation, temp, colors, projection = null }
) {
  const root = resolveRoot(host);
  const theme = themeColors(root);
  const tip = tooltipTheme(root);
  const c = colors || seriesColors(root);
  const projected = (() => {
    if (projection?.flow && projection?.amount) return projection;
    // Accept projectUsageSeries-shaped views (kwh/cost aliases).
    if (projection?.kwh && projection?.cost) {
      return {
        flow: projection.kwh,
        amount: projection.cost,
        flowMode: projection.flowMode || "import",
        amountMode: projection.amountMode || "import",
        hasReturn: !!projection.hasReturn,
        hasCompensation: !!projection.hasCompensation,
      };
    }
    return projectDirectionalUsage({
      kwh: { xs: kwh?.xs || [], values: kwh?.ys ?? kwh?.values ?? [] },
      returned: { xs: returned?.xs || [], values: returned?.ys ?? returned?.values ?? [] },
      cost: { xs: cost?.xs || [], values: cost?.ys ?? cost?.values ?? [] },
      compensation: {
        xs: compensation?.xs || [],
        values: compensation?.ys ?? compensation?.values ?? [],
      },
    });
  })();
  const flowMap = _pairMap(projected.flow?.xs || [], projected.flow?.values || []);
  const amountMap = _pairMap(projected.amount?.xs || [], projected.amount?.values || []);
  const tempMap = _pairMap(temp?.xs || [], temp?.ys ?? temp?.values ?? temp?.means ?? []);
  const signedFlow = projected.flowMode === "signed";
  const netAmount = projected.amountMode === "net";
  const starts = [
    ...new Set([...flowMap.keys(), ...amountMap.keys(), ...tempMap.keys()]),
  ].sort((a, b) => a - b);
  // Category axis fills each slot; time axis leaves sparse hairline bars.
  const useCategory = starts.length > 0 && starts.length <= 96;
  const categories = useCategory ? starts.map(_categoryLabel) : null;
  const flowVals = useCategory
    ? starts.map((t) => (flowMap.has(t) ? flowMap.get(t) : null))
    : toMsPairs(projected.flow.xs, projected.flow.values);
  const amountVals = useCategory
    ? starts.map((t) => (amountMap.has(t) ? amountMap.get(t) : null))
    : toMsPairs(projected.amount.xs, projected.amount.values);
  // ECharts breaks category lines on '-' (null can render as a zero dip).
  const tempVals = useCategory
    ? starts.map((t) => (tempMap.has(t) ? tempMap.get(t) : "-"))
    : toMsPairs(temp?.xs || [], temp?.ys ?? temp?.values ?? temp?.means ?? []);

  const flowName = signedFlow ? "Grid flow" : "kWh";
  const amountName = netAmount ? "Net interval amount" : "Import cost";
  const legendData = [flowName, amountName, "°F"];
  const flowExtent = signedFlow ? symmetricExtent(projected.flow.values) : null;
  const amountNums = projected.amount.values.filter((v) => v != null && Number.isFinite(Number(v)));
  const amountHasNegative = amountNums.some((v) => Number(v) < 0);
  // Credits-only windows still need a zero baseline so direction stays readable.
  const amountExtent = amountHasNegative ? _paddedExtent([...amountNums, 0]) : null;

  const barData = useCategory
    ? flowVals.map((v) => {
        if (v == null || !Number.isFinite(Number(v))) return null;
        const n = Number(v);
        const exportBar = signedFlow && n < 0;
        const barColor = exportBar ? c.export : c.kwh;
        return {
          value: n,
          itemStyle: {
            color: barColor,
            borderRadius: exportBar ? [0, 0, 5, 5] : [5, 5, 0, 0],
          },
          // Per-bar emphasis so export hover glow matches export color.
          emphasis: barEmphasis(barColor),
        };
      })
    : flowVals.map(([t, v]) => {
        if (v == null || !Number.isFinite(Number(v))) return [t, null];
        const n = Number(v);
        const exportBar = signedFlow && n < 0;
        const barColor = exportBar ? c.export : c.kwh;
        return {
          value: [t, n],
          itemStyle: {
            color: barColor,
            borderRadius: exportBar ? [0, 0, 5, 5] : [5, 5, 0, 0],
          },
          emphasis: barEmphasis(barColor),
        };
      });

  const option = {
    ...chartMotion(),
    backgroundColor: theme.bg,
    grid: { left: 56, right: 88, top: 40, bottom: 56 },
    legend: {
      show: true,
      top: 0,
      data: legendData,
      textStyle: { color: theme.text },
    },
    tooltip: {
      trigger: "axis",
      axisPointer: {
        type: "shadow",
        snap: true,
        shadowStyle: { color: withAlpha(c.kwh, 0.14) },
      },
      backgroundColor: tip.backgroundColor,
      borderColor: tip.borderColor,
      textStyle: tip.textStyle,
      // Keep series data at full precision for geometry; round only for display.
      formatter: (params) => {
        const items = Array.isArray(params) ? params : [params];
        const title = items[0]?.axisValueLabel || items[0]?.name || "";
        const lines = items.map((p) => {
          const raw = Array.isArray(p.value) ? p.value[1] : p.value;
          let seriesLabel = p.seriesName;
          let label = "—";
          if (p.seriesName === amountName || p.seriesName === "Import cost" || p.seriesName === "Net interval amount") {
            const n = Number(raw);
            if (Number.isFinite(n) && netAmount) {
              seriesLabel = n < 0 ? "Interval credit" : "Interval charge";
            }
            label = formatCostLabel(raw);
          } else if (p.seriesName === "°F") {
            label = formatTempLabel(raw);
          } else if (p.seriesName === flowName || p.seriesName === "kWh" || p.seriesName === "Grid flow") {
            const n = Number(raw);
            if (signedFlow && Number.isFinite(n) && n < 0) {
              seriesLabel = "Grid export";
              label = formatKwhLabel(Math.abs(n));
            } else if (signedFlow && Number.isFinite(n) && n > 0) {
              seriesLabel = "Grid import";
              label = formatKwhLabel(n);
            } else {
              label = formatKwhLabel(raw);
            }
          } else if (raw != null && raw !== "-") {
            label = String(raw);
          }
          return `${p.marker}${seriesLabel}&nbsp;&nbsp;<b>${label}</b>`;
        });
        return `${title}<br/>${lines.join("<br/>")}`;
      },
    },
    dataZoom: [
      { type: "inside", xAxisIndex: 0, filterMode: "none" },
      {
        type: "slider",
        xAxisIndex: 0,
        height: 18,
        bottom: 8,
        borderColor: theme.grid,
        fillerColor: withAlpha(c.kwh, 0.18),
        handleStyle: { color: c.kwh },
        dataBackground: {
          lineStyle: { color: theme.grid },
          areaStyle: { color: withAlpha(theme.muted, 0.12) },
        },
        selectedDataBackground: {
          lineStyle: { color: c.kwh },
          areaStyle: { color: withAlpha(c.kwh, 0.2) },
        },
        textStyle: { color: theme.muted, fontSize: 10 },
      },
    ],
    xAxis: useCategory
      ? {
          type: "category",
          data: categories,
          axisLabel: {
            color: theme.muted,
            hideOverlap: true,
            rotate: starts.length > 36 ? 35 : 0,
          },
          axisLine: { lineStyle: { color: theme.grid } },
          splitLine: { show: false },
          axisPointer: { type: "shadow", snap: true },
        }
      : {
          type: "time",
          axisLabel: { color: theme.muted },
          axisLine: { lineStyle: { color: theme.grid } },
          splitLine: { show: false },
        },
    yAxis: [
      {
        type: "value",
        name: "kWh",
        position: "left",
        ...(flowExtent ? { min: flowExtent[0], max: flowExtent[1] } : { min: 0 }),
        nameTextStyle: { color: theme.muted },
        axisLabel: { color: theme.muted },
        splitLine: { lineStyle: { color: theme.grid } },
      },
      {
        type: "value",
        name: "$",
        position: "right",
        ...(amountExtent
          ? { min: amountExtent[0], max: amountExtent[1] }
          : { min: 0 }),
        nameTextStyle: { color: theme.muted },
        axisLabel: {
          color: theme.muted,
          formatter: (v) => formatSignedUsd(v, Math.abs(Number(v)) >= 10 ? 0 : 2),
        },
        splitLine: { show: false },
      },
      {
        type: "value",
        name: "°F",
        position: "right",
        offset: 52,
        scale: true,
        nameTextStyle: { color: theme.muted },
        axisLabel: { color: theme.muted, formatter: (v) => `${v}°` },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: flowName,
        type: "bar",
        yAxisIndex: 0,
        data: barData,
        barWidth: useCategory ? "70%" : undefined,
        barMaxWidth: useCategory ? 120 : 40,
        barCategoryGap: useCategory ? "10%" : "25%",
        emphasis: barEmphasis(c.kwh),
      },
      {
        // Line (not a second bar series) so kWh columns can fill each slot.
        name: amountName,
        type: "line",
        yAxisIndex: 1,
        data: amountVals,
        symbol: "circle",
        showSymbol: true,
        symbolSize: starts.length <= 48 ? 7 : 4,
        connectNulls: false,
        smooth: false,
        lineStyle: { width: 3, color: c.cost },
        itemStyle: { color: c.cost },
        areaStyle: { color: withAlpha(c.cost, 0.14) },
        emphasis: linePointEmphasis(c.cost, theme),
        z: 4,
      },
      {
        name: "°F",
        type: "line",
        yAxisIndex: 2,
        data: tempVals,
        symbol: "circle",
        showSymbol: true,
        symbolSize: starts.length <= 48 ? 6 : 4,
        connectNulls: false,
        smooth: 0.4,
        lineStyle: { width: 2.5, color: c.tempHot },
        itemStyle: { color: c.tempHot },
        emphasis: linePointEmphasis(c.tempHot, theme),
        z: 5,
      },
    ],
  };
  return mount(host, option, { height: 380 });
}

function _scatterDayLabel(ts) {
  if (ts == null) return null;
  const ms = typeof ts === "number" && ts < 1e12 ? ts * 1000 : Number(ts);
  if (!Number.isFinite(ms)) return null;
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Los_Angeles",
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(ms));
}

function _formatScatterDates(dates) {
  if (!dates?.length) return "";
  const unique = [...new Set(dates.filter(Boolean))];
  if (!unique.length) return "";
  if (unique.length === 1) return unique[0];
  if (unique.length <= 3) return unique.join(", ");
  return `${unique.slice(0, 3).join(", ")} (+${unique.length - 3} more)`;
}

/** Daily kWh vs outdoor °F scatter. ``dates`` is optional unix starts parallel to xs/ys. */
export async function createScatter(host, { xs, ys, dates = null, color }) {
  const root = resolveRoot(host);
  const theme = themeColors(root);
  const tip = tooltipTheme(root);
  // Group identical coordinates so a stacked hover can list every Pacific day.
  const byCoord = new Map();
  for (let i = 0; i < xs.length; i++) {
    if (ys[i] == null || xs[i] == null) continue;
    const x = Number(xs[i]);
    const y = Number(ys[i]);
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    // Drop obvious non-weather / non-usage placeholders.
    if (x < -20 || x > 130 || y < 0) continue;
    const key = `${x}\0${y}`;
    let point = byCoord.get(key);
    if (!point) {
      point = { value: [x, y], dates: [] };
      byCoord.set(key, point);
    }
    const label = _scatterDayLabel(dates?.[i]);
    if (label && !point.dates.includes(label)) point.dates.push(label);
  }
  const data = [...byCoord.values()];
  if (data.length < 5) {
    return showChartEmpty(host, "Need more days with both usage and temperature.");
  }
  // Drop rare monthly-aggregate / bad-import outliers so axes stay readable.
  const sortedY = data.map((d) => d.value[1]).sort((a, b) => a - b);
  const p95 = sortedY[Math.min(sortedY.length - 1, Math.floor(sortedY.length * 0.95))];
  const yCap = Math.max(80, p95 * 2.5);
  const cleaned = data.filter((d) => d.value[1] <= yCap);
  if (cleaned.length >= 5) data.splice(0, data.length, ...cleaned);
  const xExtent = _paddedExtent(
    data.map((d) => d.value[0]),
    0.1,
    null
  );
  const yExtent = _paddedExtent(
    data.map((d) => d.value[1]),
    0.1,
    0
  );
  // Integer extents avoid float tick labels (e.g. …00000447) colliding with the axis name.
  const xMin = xExtent ? Math.floor(xExtent[0]) : undefined;
  const xMax = xExtent ? Math.ceil(xExtent[1]) : undefined;
  const yMin = 0;
  const yMax = yExtent ? Math.ceil(yExtent[1]) : undefined;
  const option = {
    ...chartMotion(),
    backgroundColor: theme.bg,
    // Title carries axis meaning so ECharts axis `name` cannot collide with max ticks.
    title: {
      text: "kWh / day vs Avg °F",
      left: 0,
      top: 0,
      textStyle: { color: theme.muted, fontSize: 12, fontWeight: 500 },
    },
    grid: { left: 44, right: 16, top: 32, bottom: 36 },
    tooltip: {
      trigger: "item",
      backgroundColor: tip.backgroundColor,
      borderColor: tip.borderColor,
      textStyle: tip.textStyle,
      formatter: (p) => {
        const x = Number(p.value[0]);
        const y = Number(p.value[1]);
        const dateLine = _formatScatterDates(p.data?.dates);
        const head = dateLine ? `<b>${dateLine}</b><br/>` : "";
        return `${head}${formatTempLabel(x)}<br/>${formatKwhLabel(y)}`;
      },
    },
    xAxis: {
      type: "value",
      min: xMin,
      max: xMax,
      scale: true,
      axisLabel: { color: theme.muted, formatter: (v) => `${Math.round(Number(v))}` },
      splitLine: { lineStyle: { color: theme.grid } },
    },
    yAxis: {
      type: "value",
      min: yMin,
      max: yMax,
      scale: true,
      axisLabel: { color: theme.muted, formatter: (v) => `${Math.round(Number(v))}` },
      splitLine: { lineStyle: { color: theme.grid } },
    },
    series: [
      {
        name: "Daily usage",
        type: "scatter",
        symbol: "circle",
        symbolSize: 8,
        itemStyle: { color, opacity: 0.78 },
        data,
        emphasis: scatterPointEmphasis(color, theme),
        blur: scatterPointBlur(),
        // Larger hit area so dense clouds are easier to hover.
        select: { disabled: true },
      },
    ],
  };
  return mount(host, option, { height: 300 });
}

function dayKeyFromUnix(sec) {
  const d = new Date(sec * 1000);
  // Calendar heatmaps use Pacific calendar days for PGE.
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Los_Angeles",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
}

/** Calendar heatmap for daily values (ECharts calendar + heatmap). */
export async function renderHeatmap(host, { xs, ys, diverging = false, title = "" }) {
  host.replaceChildren();
  const root = resolveRoot(host);
  const theme = themeColors(root);
  if (!xs.length) return showChartEmpty(host, "No daily history yet.");
  const colors = seriesColors(root);
  const tip = tooltipTheme(root);
  const data = [];
  for (let i = 0; i < xs.length; i++) {
    if (ys[i] == null || Number.isNaN(Number(ys[i]))) continue;
    data.push([dayKeyFromUnix(xs[i]), Number(ys[i])]);
  }
  if (data.length < 7) {
    return showChartEmpty(host, "Not enough daily samples for a heatmap yet.");
  }
  data.sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  // Only span first→last populated day so empty months don't dominate.
  const range = [data[0][0], data[data.length - 1][0]];
  const yearStart = data[0][0].slice(0, 4);
  const yearEnd = data[data.length - 1][0].slice(0, 4);
  const yearText = yearStart === yearEnd ? yearStart : `${yearStart}–${yearEnd}`;
  const heading = title ? `${title} · ${yearText}` : yearText;
  const values = data.map((d) => d[1]);
  const vmin = Math.min(...values);
  const vmax = Math.max(...values);
  const option = {
    ...chartMotion(),
    backgroundColor: theme.bg,
    // Year range lives in the title (left yearLabel was clipped by the card).
    title: {
      text: heading,
      left: 0,
      top: 0,
      textStyle: { color: theme.muted, fontSize: 13, fontWeight: 500 },
    },
    tooltip: {
      backgroundColor: tip.backgroundColor,
      borderColor: tip.borderColor,
      textStyle: tip.textStyle,
      formatter: (p) => `${p.value[0]}: ${Number(p.value[1]).toFixed(diverging ? 0 : 1)}`,
    },
    visualMap: {
      min: vmin,
      max: vmax === vmin ? vmin + 1 : vmax,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      textStyle: { color: theme.muted },
      inRange: diverging
        ? // Mid stop: muted ink (not card surface) so mild days ≠ empty cells.
          { color: [colors.tempCold, withAlpha(theme.text, 0.4), colors.tempHot] }
        : { color: [withAlpha(colors.kwh, 0.25), colors.kwh] },
      outOfRange: { color: withAlpha(theme.muted, 0.12) },
    },
    calendar: {
      top: 36,
      left: 28,
      right: 12,
      bottom: 44,
      range,
      cellSize: ["auto", 13],
      itemStyle: {
        // Empty days: faint hatch-like wash, distinct from mid-scale temperatures.
        color: withAlpha(theme.muted, 0.06),
        borderWidth: 2,
        borderColor: withAlpha(theme.muted, 0.22),
      },
      splitLine: { show: false },
      dayLabel: { color: theme.muted, nameMap: "en", firstDay: 0 },
      monthLabel: { color: theme.muted },
      yearLabel: { show: false },
    },
    series: [
      {
        type: "heatmap",
        coordinateSystem: "calendar",
        data,
        emphasis: heatmapCellEmphasis(theme),
      },
    ],
  };
  return mount(host, option, { height: 210 });
}

export function destroyCharts(list) {
  for (const c of list || []) {
    try {
      c?.destroy?.();
    } catch (_e) {
      /* ignore */
    }
  }
}
