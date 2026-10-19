/**
 * Apache ECharts loaders for the PGE panel.
 * Usage hero is one combined chart (kWh + cost + °F). Insight plots stay single-series.
 * Colors resolve from the panel host / HA theme — never assume light-mode hex.
 * @see https://echarts.apache.org/examples/en/index.html
 */

import {
  formatSignedUsd,
  formatTooltipRow,
  pacificParts,
  projectDirectionalUsage,
  symmetricExtent,
  todPeriodForPacific,
} from "./data.js?v=0.12.1";
import {
  chromeColors,
  galleryPalette,
  seriesColors,
  tooltipTheme,
  withAlpha,
} from "./theme.js?v=0.12.1";

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
    animationDelay: (idx) => Math.min(idx * 12, 360),
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

/** Narrow cards get taller charts so the plot keeps a usable aspect ratio. */
export function responsiveChartHeight(base, hostWidth) {
  const w = hostWidth || base;
  if (w <= 420) return Math.min(Math.round(base * 1.3), 420);
  if (w <= 720) return Math.min(Math.round(base * 1.15), 440);
  return base;
}

/** Extra axisLabel.margin so a negative waterfall label sits above the category text. */
export function waterfallNegativeLabelGap(steps) {
  return (steps || []).some((step) => Number(step?.value) < 0) ? 16 : 0;
}

/** Bar label for a waterfall step. Negatives sit under the bar and keep a minus. */
export function waterfallBarLabel(value, { unit = "", textColor = "" } = {}) {
  const n = Number(value);
  if (!Number.isFinite(n)) return { position: "top", color: textColor, text: "" };
  const negative = n < 0;
  const text = unit === "$"
    ? (negative ? formatSignedUsd(n) : `$${Math.abs(n).toFixed(2)}`)
    : (negative ? String(n) : String(Math.abs(n)));
  return { position: negative ? "bottom" : "top", color: textColor, text };
}

const CATEGORY_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const CATEGORY_WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** Turn ISO category labels into short dates. Other labels stay as written. */
export function formatCategoryAxis(value) {
  const text = String(value ?? "");
  const stamp = text.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?$/);
  if (!stamp) return text;
  const year = Number(stamp[1]);
  const month = Number(stamp[2]);
  const day = Number(stamp[3]);
  if (month < 1 || month > 12 || day < 1 || day > 31) return text;
  if (stamp[4] == null) return `${CATEGORY_MONTHS[month - 1]} '${String(year).slice(2)}`;
  const hour = Number(stamp[4]);
  const weekday = CATEGORY_WEEKDAYS[new Date(Date.UTC(year, month - 1, day)).getUTCDay()];
  const hour12 = hour % 12 || 12;
  const suffix = hour < 12 ? "AM" : "PM";
  return `${weekday} ${hour12} ${suffix}`;
}

function chartDescription(host) {
  const figure = host.closest?.("figure");
  const title = figure?.querySelector(".fig-title, h3")?.textContent?.trim();
  const caption = figure?.querySelector("dd, p")?.textContent?.trim();
  return [title, caption].filter(Boolean).join(". ") || host.id || "PGE chart";
}

/** Reserve space for tick labels on every grid. Does not mutate the input. */
export function containAxisLabels(option) {
  if (!option?.grid) return option;
  const fix = (grid) => ({ ...grid, containLabel: true });
  return {
    ...option,
    grid: Array.isArray(option.grid) ? option.grid.map(fix) : fix(option.grid),
  };
}

/**
 * Fit legend and axes to the chart's own width.
 * A wrapping legend overlaps the plot, and a hyphen in "On-peak" breaks the swatch off the word.
 */
export function chartLayoutPatch(option, width) {
  const narrow = width > 0 && width < 560;
  const compact = width > 0 && width < 900;
  const patch = {};
  if (option.legend && !Array.isArray(option.legend) && option.legend.show !== false) {
    const legendCount = Array.isArray(option.legend.data) ? option.legend.data.length : 0;
    patch.legend = {
      ...option.legend,
      type: compact && legendCount > 4 ? "scroll" : "plain",
      orient: "horizontal",
      top: 0,
      left: 0,
      right: 0,
      itemGap: narrow ? 8 : 14,
      itemWidth: narrow ? 12 : 18,
      itemHeight: 8,
      pageIconSize: 10,
      formatter: (name) => String(name).replace(/-/g, "\u2011"),
      textStyle: { ...(option.legend.textStyle || {}), fontSize: narrow ? 10 : 12 },
    };
  }
  const axes = option.yAxis
    ? (Array.isArray(option.yAxis) ? option.yAxis : [option.yAxis])
    : [];
  if (axes.length) {
    const nextAxes = axes.map((axis, index) => {
      const hideExtra = narrow && index > 0;
      return {
        ...axis,
        name: hideExtra ? "" : axis.name,
        nameLocation: "middle",
        nameRotate: 90,
        nameGap: narrow ? 52 : 40,
        offset: narrow && axis.offset ? Math.round(axis.offset * 0.6) : axis.offset,
        axisLabel: {
          ...(axis.axisLabel || {}),
          fontSize: narrow ? 10 : 11,
          hideOverlap: true,
          ...(hideExtra ? { show: false } : {}),
        },
        ...(hideExtra ? { axisLine: { ...(axis.axisLine || {}), show: false } } : {}),
      };
    });
    patch.yAxis = Array.isArray(option.yAxis) ? nextAxes : nextAxes[0];
  }
  if (option.grid) {
    const grids = Array.isArray(option.grid) ? option.grid : [option.grid];
    const legendOn = option.legend && option.legend.show !== false;
    const nextGrids = grids.map((grid, index) => ({
      ...grid,
      top: index === 0 && legendOn ? Math.max(grid.top || 0, narrow ? 32 : 36) : grid.top,
      right: narrow && typeof grid.right === "number" ? Math.min(grid.right, 48) : grid.right,
      containLabel: true,
    }));
    patch.grid = Array.isArray(option.grid) ? nextGrids : nextGrids[0];
  }
  if (option.xAxis) {
    const xs = Array.isArray(option.xAxis) ? option.xAxis : [option.xAxis];
    const nextXs = xs.map((axis) => {
      const axisLabel = {
        ...(axis.axisLabel || {}),
        fontSize: narrow ? 10 : 11,
        hideOverlap: true,
      };
      if (axis.type === "category") {
        const previous = axis.axisLabel?.formatter;
        axisLabel.formatter = (value, index) => {
          const raw = typeof previous === "function" ? previous(value, index) : value;
          return formatCategoryAxis(raw);
        };
      }
      return { ...axis, axisLabel };
    });
    patch.xAxis = Array.isArray(option.xAxis) ? nextXs : nextXs[0];
  }
  if (option.visualMap && !Array.isArray(option.visualMap)) {
    patch.visualMap = {
      ...option.visualMap,
      itemWidth: narrow ? 8 : option.visualMap.itemWidth,
      itemHeight: narrow ? Math.min(110, Math.max(72, Math.round(width - 100))) : option.visualMap.itemHeight,
      textStyle: { ...(option.visualMap.textStyle || {}), fontSize: narrow ? 10 : 12 },
    };
  }
  if (option.calendar) {
    const calendars = Array.isArray(option.calendar) ? option.calendar : [option.calendar];
    const nextCalendars = calendars.map((calendar) => (
      narrow
        ? {
            ...calendar,
            dayLabel: calendar.dayLabel
              ? { ...calendar.dayLabel, fontSize: 10, margin: 6 }
              : calendar.dayLabel,
            monthLabel: {
              ...(calendar.monthLabel || {}),
              show: true,
              fontSize: 10,
              margin: 4,
            },
          }
        : calendar
    ));
    patch.calendar = Array.isArray(option.calendar) ? nextCalendars : nextCalendars[0];
  }
  if (Array.isArray(option.dataZoom)) {
    patch.dataZoom = option.dataZoom.map((zoom) =>
      zoom?.type === "slider"
        ? { ...zoom, height: narrow ? 12 : zoom.height, bottom: narrow ? 2 : zoom.bottom }
        : zoom,
    );
  }
  return patch;
}

async function prepareChartMount(host) {
  const mountToken = host._pgeMountToken;
  const echarts = await ensureEcharts();
  if (!host.isConnected || host._pgeMountToken !== mountToken) return null;
  return echarts;
}

async function mount(host, option, { height = 160, group = null, onLayout = null, scale = true, width = null } = {}) {
  const echarts = await prepareChartMount(host);
  if (!echarts) return null;
  host.replaceChildren();
  if (width) {
    host.style.width = `${Math.round(width)}px`;
    host.style.maxWidth = "none";
  } else {
    host.style.width = "100%";
    host.style.maxWidth = "100%";
  }
  const description = chartDescription(host);
  host.setAttribute("role", "img");
  host.setAttribute("aria-label", description);
  option = {
    ...option,
    aria: {
      enabled: true,
      decal: { show: false },
      ...option.aria,
      label: {
        description,
        ...(option.aria?.label || {}),
      },
    },
  };
  option = containAxisLabels(option); // containLabel: true on every grid
  const applyHeight = (hostWidth) => {
    const next = scale ? responsiveChartHeight(height, hostWidth || host.clientWidth) : height;
    host.style.height = `${next}px`;
    host.style.minHeight = `${next}px`;
  };
  applyHeight();
  const chart = echarts.init(host, null, { renderer: "canvas" });
  chart.setOption(option);
  if (group) {
    chart.group = group;
    echarts.connect(group);
  }
  let widthBucket = null;
  const applyLayout = () => {
    try {
      const width = host.clientWidth || 0;
      applyHeight(width);
      const bucket = width < 560 ? "narrow" : width < 900 ? "compact" : "wide";
      if (width > 0 && bucket !== widthBucket) {
        widthBucket = bucket;
        const patch = chartLayoutPatch(option, width);
        chart.setOption(patch, { replaceMerge: Object.keys(patch) });
      }
      if (typeof onLayout === "function") onLayout(chart, host);
      chart.resize();
    } catch (_e) {
      /* ignore */
    }
  };
  // Host width is often 0 during the first paint inside the shadow tree.
  requestAnimationFrame(() => requestAnimationFrame(applyLayout));
  window.addEventListener("resize", applyLayout);
  const resizeObserver = typeof ResizeObserver === "function" ? new ResizeObserver(() => applyLayout()) : null;
  resizeObserver?.observe(host);
  const wrapped = wrapChart(chart);
  const origDestroy = wrapped.destroy;
  wrapped.destroy = () => {
    window.removeEventListener("resize", applyLayout);
    resizeObserver?.disconnect();
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
        barMaxWidth: 28,
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
        barMaxWidth: 28,
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
  { kwh, returned, cost, compensation, temp, colors, projection = null, periodColors = null, metric = "kwh" }
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
    ? starts.map((t) => (tempMap.has(t) ? tempMap.get(t) : null))
    : toMsPairs(temp?.xs || [], temp?.ys ?? temp?.values ?? temp?.means ?? []);

  const flowName = signedFlow ? "Grid flow" : "kWh";
  const amountName = netAmount ? "Net interval amount" : "Import cost";
  const legendData = (
    periodColors
      ? [flowName, amountName, "°F", "Off-peak", "Mid-peak", "On-peak"]
      : [flowName, amountName, "°F"]
  ).filter((name) => !(periodColors && name === "kWh"));
  const flowExtent = signedFlow ? symmetricExtent(projected.flow.values) : null;
  const amountNums = projected.amount.values.filter((v) => v != null && Number.isFinite(Number(v)));
  const amountHasNegative = amountNums.some((v) => Number(v) < 0);
  // Credits-only windows still need a zero baseline so direction stays readable.
  const amountExtent = amountHasNegative ? _paddedExtent([...amountNums, 0]) : null;

  const colorForHour = (ts, n) => {
    if (signedFlow && n < 0) return c.export;
    if (!periodColors || ts == null) return c.kwh;
    const parts = pacificParts(ts);
    return periodColors[todPeriodForPacific(parts.ymd, parts.hour)] || c.kwh;
  };
  const barData = useCategory
    ? flowVals.map((v, index) => {
        if (v == null || !Number.isFinite(Number(v))) return null;
        const n = Number(v);
        const exportBar = signedFlow && n < 0;
        const barColor = colorForHour(starts[index], n);
        return {
          value: n,
          itemStyle: {
            color: barColor,
            borderRadius: exportBar ? [0, 0, 5, 5] : [5, 5, 0, 0],
          },
          emphasis: barEmphasis(barColor),
        };
      })
    : flowVals.map(([t, v]) => {
        if (v == null || !Number.isFinite(Number(v))) return [t, null];
        const n = Number(v);
        const exportBar = signedFlow && n < 0;
        const ts = typeof t === "number" && t > 1e12 ? t / 1000 : t;
        const barColor = colorForHour(ts, n);
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
    ...(starts.length > 48
      ? {
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
        }
      : {}),
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
      ...(periodColors
        ? [
            { name: "Off-peak", type: "bar", data: [], itemStyle: { color: periodColors.off_peak } },
            { name: "Mid-peak", type: "bar", data: [], itemStyle: { color: periodColors.mid_peak } },
            { name: "On-peak", type: "bar", data: [], itemStyle: { color: periodColors.on_peak } },
          ]
        : []),
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
    const noun = data.length === 1 ? "day" : "days";
    return showChartEmpty(
      host,
      `Only ${data.length} ${noun} in the last 12 months have both usage and temperature.`,
    );
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

/** Vertical space for one year inside a single heatmap chart. */
const HEATMAP_YEAR_PITCH = 124;
/** Phone calendars stay horizontal and scroll at this width. */
const HEATMAP_CALENDAR_MIN_WIDTH = 720;

function heatmapYears(startYmd, endYmd) {
  const startYear = Number(startYmd.slice(0, 4));
  const endYear = Number(endYmd.slice(0, 4));
  const years = [];
  for (let year = startYear; year <= endYear; year += 1) years.push(String(year));
  return years;
}

/** Calendar heatmap for daily values (ECharts calendar + heatmap). */
export async function renderHeatmap(host, { xs, ys, diverging = false, title = "", onClick = null }) {
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
  const spanDays = (Date.parse(`${data[data.length - 1][0]}T00:00:00Z`) - Date.parse(`${data[0][0]}T00:00:00Z`)) / 86400000;
  const singleSpan = spanDays < 400;
  const years = singleSpan ? [data[0][0].slice(0, 4)] : heatmapYears(data[0][0], data[data.length - 1][0]);
  const yearText = years.length === 1 ? years[0] : `${years[0]}–${years[years.length - 1]}`;
  const heading = title ? `${title} · ${yearText}` : yearText;
  const values = data.map((d) => d[1]);
  const vmin = Math.min(...values);
  let vmax = Math.max(...values);
  // A few imported spikes would otherwise pin the ramp and hide ordinary days.
  let clipHigh = false;
  if (!diverging && values.length >= 20 && vmax > 0) {
    const sorted = [...values].sort((a, b) => a - b);
    const p95 = sorted[Math.round(0.95 * (sorted.length - 1))];
    if (p95 > 0 && vmax > p95 * 1.5) {
      vmax = p95;
      clipHigh = true;
    }
  }
  const titleSpace = 22;
  const cellStyle = {
    color: withAlpha(theme.muted, 0.06),
    borderWidth: 1,
    borderColor: withAlpha(theme.muted, 0.22),
  };
  const option = {
    ...chartMotion(),
    backgroundColor: theme.bg,
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
      show: true,
      text: [String(Math.round(vmax)), String(Math.round(vmin))],
      min: vmin,
      max: vmax === vmin ? vmin + 1 : vmax,
      orient: "horizontal",
      left: "center",
      bottom: 6,
      // Horizontal visualMap uses itemWidth as thickness and itemHeight as length.
      itemWidth: 10,
      itemHeight: 140,
      textStyle: { color: theme.muted },
      inRange: diverging
        ? { color: [colors.tempCold, withAlpha(theme.text, 0.4), colors.tempHot] }
        : { color: [withAlpha(colors.kwh, 0.18), withAlpha(colors.kwh, 0.55), colors.kwh] },
      outOfRange: {
        color: clipHigh ? colors.kwh : withAlpha(theme.muted, 0.12),
      },
    },
    graphic: years.map((year, index) => ({
      type: "text",
      left: 0,
      top: titleSpace + index * HEATMAP_YEAR_PITCH,
      style: {
        text: year,
        fill: theme.muted,
        fontSize: 11,
        fontWeight: 600,
      },
    })),
    calendar: years.map((year, index) => ({
      top: titleSpace + 16 + index * HEATMAP_YEAR_PITCH,
      left: 28,
      right: 8,
      range: singleSpan ? [data[0][0], data[data.length - 1][0]] : year,
      cellSize: ["auto", 11],
      itemStyle: cellStyle,
      splitLine: { show: false },
      dayLabel: {
        show: index === 0,
        color: theme.muted,
        nameMap: "en",
        firstDay: 0,
        fontSize: 9,
        margin: 4,
      },
      monthLabel: { color: theme.muted, fontSize: 10, margin: 4 },
      yearLabel: { show: false },
    })),
    series: years.map((_, index) => ({
      type: "heatmap",
      coordinateSystem: "calendar",
      calendarIndex: index,
      data,
      emphasis: heatmapCellEmphasis(theme),
    })),
  };
  const height = titleSpace + years.length * HEATMAP_YEAR_PITCH + 36;
  const parentWidth = host.parentElement?.clientWidth || host.clientWidth || 0;
  const phoneCalendar = parentWidth > 0 && parentWidth < 560;
  const wrapped = await mount(host, option, {
    height,
    scale: false,
    width: phoneCalendar ? HEATMAP_CALENDAR_MIN_WIDTH : parentWidth || null,
    onLayout: (_chart, layoutHost) => {
      const nextParent = layoutHost.parentElement?.clientWidth || layoutHost.clientWidth || 0;
      const scrollPhone = nextParent > 0 && nextParent < 560;
      const calendarWidth = scrollPhone ? HEATMAP_CALENDAR_MIN_WIDTH : nextParent || HEATMAP_CALENDAR_MIN_WIDTH;
      layoutHost.style.width = scrollPhone ? `${calendarWidth}px` : "100%";
      layoutHost.style.maxWidth = scrollPhone ? "none" : "100%";
      layoutHost.style.height = `${titleSpace + years.length * HEATMAP_YEAR_PITCH + 48}px`;
      layoutHost.style.minHeight = layoutHost.style.height;
    },
  });
  if (wrapped?.chart && typeof onClick === "function") {
    wrapped.chart.on("click", (params) => {
      const ymd = Array.isArray(params?.value) ? params.value[0] : null;
      if (typeof ymd === "string") onClick(ymd);
    });
  }
  return wrapped;
}

function countFinite(values) {
  let count = 0;
  for (const value of values || []) {
    if (value != null && Number.isFinite(Number(value))) count += 1;
  }
  return count;
}

function galleryBase(host) {
  const root = resolveRoot(host);
  return {
    root,
    theme: themeColors(root),
    tip: tooltipTheme(root),
    colors: seriesColors(root),
  };
}

/** 24-hour polar bar. `values` is mean kWh for hours 0 through 23. */
export async function createPolarBar(host, { values, color } = {}) {
  if (countFinite(values) < 2) return showChartEmpty(host, "Not enough hourly history.");
  const { theme, tip, colors } = galleryBase(host);
  const data = (values || []).map((value) => (value == null || !Number.isFinite(Number(value)) ? null : Number(value)));
  return mount(
    host,
    {
      ...chartMotion(),
      backgroundColor: theme.bg,
      tooltip: { ...tip, trigger: "item" },
      polar: { radius: ["12%", "72%"] },
      angleAxis: {
        type: "category",
        data: Array.from({ length: 24 }, (_, hour) => String(hour).padStart(2, "0")),
        startAngle: 90,
        axisLabel: { color: theme.muted },
      },
      radiusAxis: {
        axisLabel: { color: theme.muted },
        splitLine: { lineStyle: { color: theme.grid } },
      },
      series: [
        {
          type: "bar",
          coordinateSystem: "polar",
          data,
          itemStyle: { color: color || colors.kwh },
        },
      ],
    },
    { height: 280 },
  );
}

/** Polar scatter for the year spiral. Points are `{ angle, radius, value }`. */
export async function createPolarScatter(host, { points } = {}) {
  const data = (points || [])
    .filter((point) => Number.isFinite(point?.angle) && Number.isFinite(point?.radius) && Number.isFinite(Number(point?.value)))
    .map((point) => [point.angle, point.radius, Number(point.value)]);
  if (data.length < 2) return showChartEmpty(host, "Not enough hourly history.");
  const { theme, tip, colors } = galleryBase(host);
  const values = data.map((point) => point[2]);
  return mount(
    host,
    {
      animation: false,
      backgroundColor: theme.bg,
      tooltip: { ...tip, trigger: "item" },
      polar: {},
      angleAxis: { type: "value", min: 0, max: 23, axisLabel: { color: theme.muted } },
      radiusAxis: { axisLabel: { color: theme.muted }, splitLine: { lineStyle: { color: theme.grid } } },
      visualMap: {
        min: Math.min(...values),
        max: Math.max(...values),
        dimension: 2,
        calculable: false,
        right: 0,
        bottom: 0,
        textStyle: { color: theme.muted },
        inRange: { color: [colors.tempCold, colors.kwh, colors.tempHot] },
      },
      series: [
        {
          type: "scatter",
          coordinateSystem: "polar",
          large: true,
          symbolSize: 3,
          data,
        },
      ],
    },
    { height: 320 },
  );
}

/** One box per category. Each box is `[min, q1, median, q3, max]`. */
export async function createBoxPlot(host, { categories, boxes, colors: boxColors = [] } = {}) {
  const ready = (boxes || []).filter((box) => Array.isArray(box) && box.filter((value) => Number.isFinite(Number(value))).length >= 2);
  if (ready.length < 1 || countFinite(ready.flat()) < 2) return showChartEmpty(host, "Not enough hourly history.");
  const { theme, tip, colors } = galleryBase(host);
  return mount(
    host,
    {
      ...chartMotion(),
      backgroundColor: theme.bg,
      tooltip: { ...tip, trigger: "item" },
      xAxis: { type: "category", data: categories || [], axisLabel: { color: theme.muted } },
      yAxis: { type: "value", name: "kWh", axisLabel: { color: theme.muted }, splitLine: { lineStyle: { color: theme.grid } } },
      series: [
        {
          type: "boxplot",
          data: boxes.map((box, index) => ({
            value: box,
            itemStyle: {
              color: boxColors[index] || colors.kwh,
              borderColor: boxColors[index] || theme.text,
            },
          })),
        },
      ],
    },
    { height: 240 },
  );
}

export async function createSankey(host, { nodes, links } = {}) {
  const ready = (links || []).filter((link) => Number.isFinite(Number(link?.value)) && Number(link.value) > 0);
  if (ready.length < 1) return showChartEmpty(host, "Not enough priced hours.");
  const { theme, tip } = galleryBase(host);
  return mount(
    host,
    {
      ...chartMotion(),
      backgroundColor: theme.bg,
      tooltip: { ...tip, trigger: "item" },
      series: [
        {
          type: "sankey",
          data: nodes || [],
          links: ready,
          label: { color: theme.text },
          lineStyle: { color: "gradient", opacity: 0.4 },
        },
      ],
    },
    { height: 280 },
  );
}

export async function createTreemap(host, { data } = {}) {
  const rows = data || [];
  if (rows.some((row) => Number.isFinite(Number(row?.value)) && Number(row.value) < 0)) {
    return showChartEmpty(host, "A bill family is negative, so this chart is hidden.");
  }
  const ready = rows.filter((row) => Number.isFinite(Number(row?.value)) && Number(row.value) !== 0);
  if (ready.length < 2) return showChartEmpty(host, "Not enough bill detail.");
  const { theme, tip } = galleryBase(host);
  return mount(
    host,
    {
      ...chartMotion(),
      backgroundColor: theme.bg,
      tooltip: { ...tip, trigger: "item" },
      series: [
        {
          type: "treemap",
          data: ready,
          breadcrumb: { show: false },
          label: { color: theme.text },
          itemStyle: { borderColor: theme.bg },
        },
      ],
    },
    { height: 260 },
  );
}

export async function createParallel(host, { dimensions, rows } = {}) {
  const ready = (rows || []).filter((row) => countFinite(row) >= 2);
  if (ready.length < 2) return showChartEmpty(host, "Not enough closed days.");
  const { theme, tip, colors } = galleryBase(host);
  return mount(
    host,
    {
      ...chartMotion(),
      backgroundColor: theme.bg,
      tooltip: { ...tip, trigger: "item" },
      parallelAxis: (dimensions || []).map((name, dim) => ({
        dim,
        name: String(name).includes(" ") ? String(name).replace(/ (?=[^ ]+$)/, "\n") : name,
        nameTextStyle: { color: theme.muted },
        axisLabel: { color: theme.muted },
      })),
      parallel: { left: 48, right: 48, bottom: 24, top: 36 },
      series: [
        {
          type: "parallel",
          lineStyle: { width: 1, color: colors.kwh, opacity: 0.35 },
          data: ready,
        },
      ],
    },
    { height: 280 },
  );
}

/** One line per month, lifted by `ridgeGap` so the profiles do not sit on each other. */
export async function createRidgeline(host, { series, ridgeGap = 1 } = {}) {
  const ready = (series || []).filter((row) => countFinite(row?.values) >= 2);
  if (ready.length < 1) return showChartEmpty(host, "Not enough hourly history.");
  const { theme, tip, colors } = galleryBase(host);
  const hours = Array.from({ length: 24 }, (_, hour) => String(hour).padStart(2, "0"));
  return mount(
    host,
    {
      ...chartMotion(),
      backgroundColor: theme.bg,
      tooltip: {
        ...tip,
        trigger: "axis",
        formatter: (items) => {
          const rows = (Array.isArray(items) ? items : [items]).filter(Boolean);
          if (!rows.length) return "";
          const hour = rows[0].axisValueLabel ?? rows[0].axisValue ?? "";
          const lines = rows
            .map((item) => {
              const actual = item.data && typeof item.data === "object" ? item.data.actual : null;
              if (actual == null || !Number.isFinite(Number(actual))) return null;
              return `${item.marker || ""}${item.seriesName}: ${Number(actual).toFixed(2)} kWh`;
            })
            .filter(Boolean);
          return [`${hour}:00`, ...lines].join("<br/>");
        },
      },
      legend: { show: false },
      xAxis: { type: "category", data: hours, axisLabel: { color: theme.muted } },
      yAxis: { type: "value", axisLabel: { show: false }, splitLine: { show: false } },
      series: ready.map((row, monthIndex) => {
        const baseline = monthIndex * ridgeGap;
        return {
          type: "line",
          name: row.name,
          showSymbol: false,
          data: (row.values || []).map((value) => {
            if (value == null || !Number.isFinite(Number(value))) return null;
            const actual = Number(value);
            return { value: actual + baseline, actual };
          }),
          areaStyle: { origin: baseline, color: colors.kwh, opacity: 0.28 },
          lineStyle: { color: colors.kwh, width: 1.5 },
          endLabel: { show: true, formatter: () => row.name, color: theme.muted },
        };
      }),
    },
    { height: 320 },
  );
}

/**
 * Transparent helper stack plus a visible delta.
 * A step with `total: true` is an absolute end bar, not another delta.
 */
export async function createWaterfall(host, { steps, unit = "" } = {}) {
  const ready = (steps || []).filter((step) => Number.isFinite(Number(step?.value)));
  if (ready.length < 2) return showChartEmpty(host, "Not enough statement history.");
  const { theme, tip, colors } = galleryBase(host);
  let running = 0;
  const helpers = [];
  const deltas = [];
  const barLabel = (amount) => {
    const spec = waterfallBarLabel(amount, { unit, textColor: theme.text });
    return {
      show: true,
      position: spec.position,
      color: spec.color,
      distance: 6,
      formatter: () => spec.text,
    };
  };
  for (const step of ready) {
    const value = Number(step.value);
    if (step.total) {
      helpers.push(0);
      deltas.push({
        value,
        itemStyle: { color: colors.cost },
        label: barLabel(value),
      });
      running = value;
      continue;
    }
    if (value >= 0) {
      helpers.push(running);
      deltas.push({
        value,
        itemStyle: { color: colors.kwh },
        label: barLabel(value),
      });
      running += value;
    } else {
      running += value;
      helpers.push(running);
      deltas.push({
        value: -value,
        itemStyle: { color: colors.critical },
        label: barLabel(value),
      });
    }
  }
  const negativeLabelGap = waterfallNegativeLabelGap(ready);
  return mount(
    host,
    {
      ...chartMotion(),
      backgroundColor: theme.bg,
      tooltip: {
        ...tip,
        trigger: "axis",
        formatter: (items) => {
          const item = items?.[1] || items?.[0];
          const step = ready[item?.dataIndex];
          if (!step) return "";
          return `${step.label}: ${Number(step.value).toFixed(2)}${unit}`;
        },
      },
      grid: { top: 28, right: 16, bottom: 48, left: 8 },
      xAxis: {
        type: "category",
        data: ready.map((step) => step.label),
        axisLabel: {
          color: theme.muted,
          interval: 0,
          width: 72,
          overflow: "break",
          margin: 8 + negativeLabelGap,
        },
      },
      yAxis: {
        type: "value",
        axisLabel: {
          color: theme.muted,
          formatter: (value) => (unit === "$" ? `$${Math.round(Number(value))}` : String(value)),
        },
        splitLine: { lineStyle: { color: theme.grid } },
      },
      series: [
        { type: "bar", stack: "waterfall", data: helpers, itemStyle: { color: "transparent" }, emphasis: { disabled: true } },
        {
          type: "bar",
          stack: "waterfall",
          data: deltas,
          label: { show: true },
        },
      ],
    },
    { height: 240 },
  );
}

/** `data` rows are `[time, value, name]` for a themeRiver singleAxis. */
export async function createThemeRiver(host, { data } = {}) {
  const ready = (data || []).filter((row) => row && Number.isFinite(Number(row[1])));
  if (ready.length < 2) return showChartEmpty(host, "Not enough hourly history.");
  const { theme, tip, colors } = galleryBase(host);
  return mount(
    host,
    {
      animation: false,
      backgroundColor: theme.bg,
      tooltip: { ...tip, trigger: "axis" },
      singleAxis: { type: "time", top: 40, bottom: 24, axisLabel: { color: theme.muted } },
      series: [
        {
          type: "themeRiver",
          data: ready,
          label: { show: false },
          color: [colors.kwh, colors.cost, colors.export, colors.payment],
        },
      ],
    },
    { height: 240 },
  );
}

/** Weekday by hour. This is not the calendar heatmap. */
export async function createHourWeekdayHeatmap(host, { labels, values } = {}) {
  const cells = [];
  (values || []).forEach((row, weekday) => {
    (row || []).forEach((value, hour) => {
      if (value == null || !Number.isFinite(Number(value))) return;
      cells.push([hour, weekday, Number(value)]);
    });
  });
  if (cells.length < 2) return showChartEmpty(host, "Not enough hourly history.");
  const { theme, tip, colors } = galleryBase(host);
  const flat = cells.map((cell) => cell[2]);
  return mount(
    host,
    {
      ...chartMotion(),
      backgroundColor: theme.bg,
      tooltip: { ...tip, trigger: "item" },
      grid: { left: 48, right: 16, top: 16, bottom: 28 },
      xAxis: {
        type: "category",
        data: Array.from({ length: 24 }, (_, hour) => String(hour).padStart(2, "0")),
        axisLabel: { color: theme.muted },
      },
      yAxis: {
        type: "category",
        data: labels || ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
        axisLabel: { color: theme.muted },
      },
      visualMap: {
        min: Math.min(...flat),
        max: Math.max(...flat),
        show: false,
        inRange: { color: [withAlpha(colors.kwh, 0.08), colors.kwh] },
      },
      series: [{ type: "heatmap", data: cells, emphasis: heatmapCellEmphasis(theme) }],
    },
    { height: 220 },
  );
}

/**
 * Category or time chart for gallery hosts that are not a special ECharts type.
 * `series` entries: `{ name, values, color, type, area, stack }`.
 */
export async function createGalleryChart(host, {
  categories = [],
  series = [],
  yName = "",
  xName = "",
  horizontal = false,
  markLines = [],
  percent = false,
  panes = false,
} = {}) {
  const finite = series.reduce((count, row) => count + countFinite(row?.values), 0);
  if (finite < 2) return showChartEmpty(host, "Not enough history.");
  const { theme, tip, colors } = galleryBase(host);
  const palette = galleryPalette(host);
  const timeAxis = categories.length > 0 && typeof categories[0] === "number" && categories[0] > 1e9;
  const built = series.map((row, index) => {
    const color = row.color || palette[index % palette.length];
    const point = (value, i) => {
      if (value == null || !Number.isFinite(Number(value))) return null;
      const n = Number(value);
      const pointColor = row.colors?.[i];
      if (timeAxis) {
        const ts = categories[i];
        const t = typeof ts === "number" && ts < 1e12 ? ts * 1000 : ts;
        return pointColor ? { value: [t, n], itemStyle: { color: pointColor } } : [t, n];
      }
      return pointColor ? { value: n, itemStyle: { color: pointColor } } : n;
    };
    const data = (row.values || []).map((value, i) => point(value, i));
    return {
      name: row.name,
      type: row.type || "line",
      xAxisIndex: panes ? row.pane || 0 : 0,
      yAxisIndex: panes ? row.pane || 0 : 0,
      data,
      stack: row.stack,
      showSymbol: false,
      connectNulls: row.connectNulls === true,
      barMaxWidth: row.type === "bar" ? 28 : undefined,
      itemStyle:
        row.type === "bar" && !horizontal
          ? { color, borderRadius: [4, 4, 0, 0] }
          : { color },
      emphasis: series.length > 1 ? { focus: "series" } : undefined,
      label: row.labels
        ? { show: true, formatter: (params) => row.labels[params.dataIndex] || "" }
        : undefined,
      areaStyle: row.area
        ? {
            color: {
              type: "linear",
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: withAlpha(color, 0.28) },
                { offset: 1, color: withAlpha(color, 0) },
              ],
            },
          }
        : undefined,
      lineStyle: { color, type: row.dashed ? "dashed" : "solid" },
      markLine:
        index === 0 && markLines.length
          ? {
              symbol: "none",
              data: markLines.map((line) => ({ yAxis: line.y, name: line.name })),
              label: { color: theme.muted, formatter: "{b}", position: "insideEndTop" },
              lineStyle: { color: theme.muted, type: "dashed" },
            }
          : undefined,
    };
  });
  const categoryAxis = {
    type: "category",
    data: categories,
    name: horizontal ? yName : xName,
    inverse: horizontal,
    axisLabel: { color: theme.muted },
  };
  const valueAxis = {
    type: "value",
    name: horizontal ? xName : yName,
    nameTextStyle: { color: theme.muted },
    max: percent ? 100 : undefined,
    axisLabel: {
      color: theme.muted,
      formatter: percent ? "{value}%" : undefined,
    },
    axisLine: { show: false },
    splitLine: { lineStyle: { color: theme.grid, type: "dashed", opacity: 0.6 } },
  };
  const timeAxisOption = {
    type: "time",
    name: xName,
    axisLabel: { color: theme.muted },
  };
  return mount(
    host,
    {
      ...chartMotion(),
      backgroundColor: theme.bg,
      tooltip: {
        ...tip,
        trigger: "axis",
        formatter: (params) => {
          const rows = Array.isArray(params) ? params : [params];
          const lines = rows.map((row) => {
            const raw = Array.isArray(row.value) ? row.value[1] : row.value;
            const estimate = /estimate|cost|dollar/i.test(row.seriesName || "");
            const unit = estimate ? "$" : "kWh";
            return formatTooltipRow({ name: row.seriesName, value: raw, unit, estimate });
          });
          return lines.join("<br>");
        },
      },
      legend: series.length > 1 ? { type: "scroll", icon: "roundRect", textStyle: { color: theme.text } } : { show: false },
      axisPointer: panes ? { link: [{ xAxisIndex: "all" }] } : undefined,
      grid: panes
        ? [
            { left: 56, right: 16, top: 36, height: "52%" },
            { left: 56, right: 16, top: "68%", height: "22%" },
          ]
        : { left: horizontal ? 88 : 48, right: 16, top: series.length > 1 ? 36 : 16, bottom: 28 },
      xAxis: panes
        ? [
            { ...(timeAxis ? timeAxisOption : categoryAxis), gridIndex: 0 },
            { ...(timeAxis ? timeAxisOption : categoryAxis), gridIndex: 1, axisLabel: { show: false } },
          ]
        : horizontal
          ? valueAxis
          : timeAxis
            ? timeAxisOption
            : categoryAxis,
      yAxis: panes
        ? [
            { ...valueAxis, gridIndex: 0 },
            { ...valueAxis, gridIndex: 1, name: "Gap" },
          ]
        : horizontal
          ? categoryAxis
          : valueAxis,
      series: built,
    },
    { height: 240 },
  );
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
