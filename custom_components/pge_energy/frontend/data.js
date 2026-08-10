/**
 * Statistics fetch → normalize → LTTB downsample → in-memory cache.
 * Uses built-in recorder/statistics_during_period (no custom backend).
 */

const _cache = new Map();

function _cacheKey(statisticId, period, start, end) {
  return `${statisticId}|${period}|${start}|${end}`;
}

/** Largest-Triangle-Three-Buckets downsample for [x, y] pairs. */
export function lttb(xs, ys, threshold) {
  const n = xs.length;
  if (threshold >= n || threshold < 3) {
    return { xs: xs.slice(), ys: ys.slice() };
  }
  const sampledX = [];
  const sampledY = [];
  const every = (n - 2) / (threshold - 2);
  let a = 0;
  sampledX.push(xs[0]);
  sampledY.push(ys[0]);
  for (let i = 0; i < threshold - 2; i++) {
    const avgRangeStart = Math.floor((i + 1) * every) + 1;
    const avgRangeEnd = Math.min(Math.floor((i + 2) * every) + 1, n);
    let avgX = 0;
    let avgY = 0;
    const avgRangeLength = Math.max(1, avgRangeEnd - avgRangeStart);
    for (let j = avgRangeStart; j < avgRangeEnd; j++) {
      avgX += xs[j];
      avgY += ys[j] ?? 0;
    }
    avgX /= avgRangeLength;
    avgY /= avgRangeLength;

    const rangeOffs = Math.floor(i * every) + 1;
    const rangeTo = Math.min(Math.floor((i + 1) * every) + 1, n);
    const pointAX = xs[a];
    const pointAY = ys[a] ?? 0;
    let maxArea = -1;
    let nextA = rangeOffs;
    for (let j = rangeOffs; j < rangeTo; j++) {
      const area =
        Math.abs(
          (pointAX - avgX) * ((ys[j] ?? 0) - pointAY) -
            (pointAX - xs[j]) * (avgY - pointAY)
        ) * 0.5;
      if (area > maxArea) {
        maxArea = area;
        nextA = j;
      }
    }
    sampledX.push(xs[nextA]);
    sampledY.push(ys[nextA]);
    a = nextA;
  }
  sampledX.push(xs[n - 1]);
  sampledY.push(ys[n - 1]);
  return { xs: sampledX, ys: sampledY };
}

export function invalidateStatsCache() {
  _cache.clear();
}

/** Sum change/delta over a window — never downsamples (KPI-safe). */
export async function sumStatisticChange(hass, statisticId, { start, end, period = "hour" } = {}) {
  const startIso = start instanceof Date ? start.toISOString() : start;
  const endIso = end instanceof Date ? end.toISOString() : end;
  const raw = await hass.callWS({
    type: "recorder/statistics_during_period",
    start_time: startIso,
    end_time: endIso,
    statistic_ids: [statisticId],
    period,
    types: ["sum", "change"],
  });
  const rows = (raw && raw[statisticId]) || [];
  let total = 0;
  let count = 0;
  for (let i = 0; i < rows.length; i++) {
    let v = rows[i].change;
    if (v == null && rows[i].sum != null && i > 0 && rows[i - 1].sum != null) {
      v = rows[i].sum - rows[i - 1].sum;
    }
    if (v == null) continue;
    total += Number(v);
    count += 1;
  }
  return { total, count };
}

/**
 * @returns {Promise<{xs: number[], sums: (number|null)[], means: (number|null)[], states: (number|null)[]}>}
 */
export async function fetchStatisticSeries(hass, statisticId, { start, end, period = "hour", maxPoints = 1200 } = {}) {
  const startIso = start instanceof Date ? start.toISOString() : start;
  const endIso = end instanceof Date ? end.toISOString() : end;
  const key = _cacheKey(statisticId, period, startIso, endIso);
  if (_cache.has(key)) {
    return _cache.get(key);
  }

  const raw = await hass.callWS({
    type: "recorder/statistics_during_period",
    start_time: startIso,
    end_time: endIso,
    statistic_ids: [statisticId],
    period,
    types: ["sum", "state", "mean", "change"],
  });

  const rows = (raw && raw[statisticId]) || [];
  const xs = [];
  const sums = [];
  const means = [];
  const states = [];
  const changes = [];
  for (const row of rows) {
    const t = row.start;
    xs.push(typeof t === "number" ? Math.floor(t / 1000) : Math.floor(new Date(t).getTime() / 1000));
    sums.push(row.sum ?? null);
    means.push(row.mean ?? null);
    states.push(row.state ?? null);
    changes.push(row.change ?? null);
  }

  // Prefer change for cumulative series bars; fall back to delta of sum.
  let values = changes;
  if (!values.some((v) => v != null)) {
    values = [];
    for (let i = 0; i < sums.length; i++) {
      if (i === 0 || sums[i] == null || sums[i - 1] == null) {
        values.push(sums[i]);
      } else {
        values.push(sums[i] - sums[i - 1]);
      }
    }
  }

  let out = { xs, sums, means, states, changes: values, values };
  if (xs.length > maxPoints) {
    const dSum = lttb(xs, values, maxPoints);
    const dMean = lttb(xs, means, maxPoints);
    out = {
      xs: dSum.xs,
      values: dSum.ys,
      changes: dSum.ys,
      means: dMean.ys,
      sums: dSum.ys,
      states: dSum.ys,
    };
  }

  _cache.set(key, out);
  return out;
}

/** Coerce epoch-seconds / ms / ISO string / Date into a Date. */
function _asDate(t = new Date()) {
  if (t instanceof Date) return t;
  if (typeof t === "number" && t < 1e12) return new Date(t * 1000);
  return new Date(t);
}

/** Pacific calendar YYYY-MM-DD for an instant. */
export function pacificYmd(date = new Date()) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Los_Angeles",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(_asDate(date));
}

/** UTC instant of Pacific local midnight for YYYY-MM-DD. */
export function pacificMidnightUtc(ymd) {
  for (const offset of ["07:00:00.000Z", "08:00:00.000Z"]) {
    const candidate = new Date(`${ymd}T${offset}`);
    if (Number.isNaN(candidate.getTime())) continue;
    if (pacificYmd(candidate) !== ymd) continue;
    const hour = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      hour: "2-digit",
      hour12: false,
    }).format(candidate);
    // Midnight can format as "24" or "00" depending on engine.
    if (hour === "00" || hour === "24") return candidate;
  }
  return new Date(`${ymd}T07:00:00.000Z`);
}

/** Previous Pacific calendar YYYY-MM-DD (calendar arithmetic, DST-safe). */
export function priorPacificYmd(ymd) {
  const [y, m, d] = String(ymd).split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() - 1);
  const yy = dt.getUTCFullYear();
  const mm = String(dt.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(dt.getUTCDate()).padStart(2, "0");
  return `${yy}-${mm}-${dd}`;
}

/**
 * Exclusive end of published PGE usage: Pacific midnight of the current
 * Pacific calendar day. PGE never publishes a complete "today" — only
 * closed days through yesterday.
 */
export function publishedDataEnd(now = new Date()) {
  return pacificMidnightUtc(pacificYmd(now));
}

const HOUR_MS = 60 * 60 * 1000;

/** Near-zero threshold for suppressing nonsense $/kWh on net-zero buckets. */
export const RATE_EPSILON_KWH = 1e-6;

/**
 * Build a timestamp → finite number map from a `{xs, values}` series.
 * Non-finite values are omitted (missing ≠ zero).
 */
function _seriesMap(series) {
  const map = new Map();
  const xs = series?.xs || [];
  const ys = series?.values || series?.ys || [];
  for (let i = 0; i < xs.length; i++) {
    const t = xs[i];
    const v = ys[i];
    if (t == null || v == null) continue;
    const n = Number(v);
    if (!Number.isFinite(n)) continue;
    map.set(t, n);
  }
  return map;
}

function _sortedUnionKeys(...maps) {
  const keys = new Set();
  for (const m of maps) {
    for (const k of m.keys()) keys.add(k);
  }
  return [...keys].sort((a, b) => a - b);
}

/**
 * Project directional recorder series into a panel view model.
 *
 * Energy: grid flow = consumption − return (positive import, negative export).
 * Amount: net interval amount = cost − compensation only when the range
 * contains at least one positive compensation credit (> 0); otherwise import cost.
 * A zero-only compensation series does not enable net mode.
 *
 * Missing counterparts at a timestamp with a directional observation mean zero.
 * True gaps (neither direction observed) stay omitted.
 *
 * @param {{kwh?, returned?, cost?, compensation?}} series
 * @returns {{
 *   flow: {xs:number[], values:(number|null)[]},
 *   amount: {xs:number[], values:(number|null)[]},
 *   hasReturn: boolean,
 *   hasCompensation: boolean,
 *   flowMode: 'import'|'signed',
 *   amountMode: 'import'|'net',
 * }}
 */
export function projectDirectionalUsage({ kwh, returned, cost, compensation } = {}) {
  const consMap = _seriesMap(kwh);
  const retMap = _seriesMap(returned);
  const costMap = _seriesMap(cost);
  const compMap = _seriesMap(compensation);

  const hasReturn = [...retMap.values()].some((v) => v > 0);
  // Match hasReturn / KPI policy: only positive credits flip amount mode to net.
  const hasCompensation = [...compMap.values()].some((v) => v > 0);
  const flowMode = hasReturn ? "signed" : "import";
  const amountMode = hasCompensation ? "net" : "import";

  const energyKeys = _sortedUnionKeys(consMap, retMap);
  const flowXs = [];
  const flowYs = [];
  for (const t of energyKeys) {
    const hasCons = consMap.has(t);
    const hasRet = retMap.has(t);
    if (!hasCons && !hasRet) continue;
    const c = hasCons ? consMap.get(t) : 0;
    const r = hasRet ? retMap.get(t) : 0;
    flowXs.push(t);
    flowYs.push(c - r);
  }

  const amountKeys = amountMode === "net" ? _sortedUnionKeys(costMap, compMap) : [...costMap.keys()].sort((a, b) => a - b);
  const amountXs = [];
  const amountYs = [];
  for (const t of amountKeys) {
    const hasCost = costMap.has(t);
    const hasComp = compMap.has(t);
    if (amountMode === "net") {
      if (!hasCost && !hasComp) continue;
      const c = hasCost ? costMap.get(t) : 0;
      const p = hasComp ? compMap.get(t) : 0;
      amountXs.push(t);
      amountYs.push(c - p);
    } else if (hasCost) {
      amountXs.push(t);
      amountYs.push(costMap.get(t));
    }
  }

  return {
    flow: { xs: flowXs, values: flowYs },
    amount: { xs: amountXs, values: amountYs },
    hasReturn,
    hasCompensation,
    flowMode,
    amountMode,
  };
}

/**
 * Symmetric axis extent around zero for bipolar series: ``[-bound, +bound]``.
 * Returns null for empty/non-finite input.
 */
export function symmetricExtent(values, padRatio = 0.08) {
  const nums = (values || [])
    .filter((v) => v != null && Number.isFinite(Number(v)))
    .map(Number);
  if (!nums.length) return null;
  let maxAbs = 0;
  for (const n of nums) maxAbs = Math.max(maxAbs, Math.abs(n));
  if (maxAbs === 0) return [-1, 1];
  const bound = maxAbs * (1 + padRatio);
  return [-bound, bound];
}

/** Format USD for tooltips/KPIs; negative → ``−$0.08`` (not ``$-0.08``). */
export function formatSignedUsd(value, digits = 2) {
  if (value == null || value === "" || value === "-") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const abs = Math.abs(n).toFixed(digits);
  if (n < 0) return `−$${abs}`;
  return `$${abs}`;
}

/** Human kWh label; negative flow shown as positive export magnitude when signed. */
export function formatSignedKwh(value, { signed = false } = {}) {
  if (value == null || value === "" || value === "-") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  if (signed && n < 0) return `${Math.abs(n).toFixed(2)} kWh`;
  return `${Number(n.toFixed(2))} kWh`;
}
const DAY_MS = 24 * HOUR_MS;

/**
 * Pacific Sunday 00:00 of the calendar week that contains the latest
 * published day (yesterday). Pair with {@link publishedDataEnd} for
 * week-to-date sums (Sun → yesterday, exclusive end).
 */
export function pacificWeekStartUtc(now = new Date()) {
  const published = publishedDataEnd(now);
  let cursor = new Date(published.getTime() - 1);
  for (let i = 0; i < 7; i++) {
    const weekday = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/Los_Angeles",
      weekday: "short",
    }).format(cursor);
    if (weekday === "Sun") {
      return pacificMidnightUtc(pacificYmd(cursor));
    }
    cursor = new Date(cursor.getTime() - DAY_MS);
  }
  return pacificMidnightUtc(pacificYmd(new Date(published.getTime() - 1)));
}

/**
 * Pacific Jan 1 00:00 of the calendar year containing ``now``.
 * Pair with {@link publishedDataEnd} for year-to-date charts.
 */
export function pacificYearStartUtc(now = new Date()) {
  const ymd = pacificYmd(now);
  return pacificMidnightUtc(`${ymd.slice(0, 4)}-01-01`);
}

/**
 * Chart/history range presets ending at {@link publishedDataEnd}.
 *
 * Short windows (`6h` / `12h` / `24h`) are the **last N hours of published
 * data** (through Pacific midnight), never a wall-clock rolling window that
 * would include incomplete “today”. Bill-bound keys (`cycle` / `last_cycle`)
 * use fallback windows here; the panel overlays statement dates when known.
 */
export function rangePresets(now = new Date()) {
  const end = publishedDataEnd(now);
  const ytdStart = pacificYearStartUtc(now);
  return {
    "6h": { start: new Date(end.getTime() - 6 * HOUR_MS), end, period: "hour", label: "6h" },
    "12h": { start: new Date(end.getTime() - 12 * HOUR_MS), end, period: "hour", label: "12h" },
    "24h": { start: new Date(end.getTime() - DAY_MS), end, period: "hour", label: "24h" },
    // Legacy alias kept for older panel state.
    yesterday: { start: new Date(end.getTime() - DAY_MS), end, period: "hour", label: "24h" },
    "7d": { start: new Date(end.getTime() - 7 * DAY_MS), end, period: "hour", label: "7d" },
    "30d": { start: new Date(end.getTime() - 30 * DAY_MS), end, period: "day", label: "30d" },
    cycle: { start: new Date(end.getTime() - 30 * DAY_MS), end, period: "day", label: "cycle" },
    last_cycle: {
      start: new Date(end.getTime() - 60 * DAY_MS),
      end: new Date(end.getTime() - 30 * DAY_MS),
      period: "day",
      label: "last_cycle",
    },
    "3mo": { start: new Date(end.getTime() - 90 * DAY_MS), end, period: "day", label: "3mo" },
    "6mo": { start: new Date(end.getTime() - 180 * DAY_MS), end, period: "day", label: "6mo" },
    "12mo": { start: new Date(end.getTime() - 365 * DAY_MS), end, period: "day", label: "12mo" },
    ytd: {
      start: ytdStart.getTime() < end.getTime() ? ytdStart : new Date(end.getTime() - DAY_MS),
      end,
      period: "day",
      label: "ytd",
    },
  };
}

/** Primary fast-select buttons (always shown; disabled when no data). */
export const RANGE_PRESET_PRIMARY = ["24h", "cycle", "last_cycle", "7d", "30d"];

/** Additional presets offered in the More… dropdown. */
export const RANGE_PRESET_MORE = ["6h", "12h", "3mo", "6mo", "12mo", "ytd"];

/** All preset keys (primary first, then More…). */
export const RANGE_PRESET_ORDER = [...RANGE_PRESET_PRIMARY, ...RANGE_PRESET_MORE];

/** Display labels for Usage range controls. */
export const RANGE_PRESET_LABELS = {
  "6h": "6 hours",
  "12h": "12 hours",
  "24h": "24h",
  "7d": "7 days",
  "30d": "Month",
  cycle: "This cycle",
  last_cycle: "Last cycle",
  "3mo": "3 months",
  "6mo": "6 months",
  "12mo": "12 months",
  ytd: "Year to date",
};
/** Cap an end instant so it never includes the incomplete Pacific "today". */
export function clampToPublishedEnd(end, now = new Date()) {
  const published = publishedDataEnd(now);
  const e = end instanceof Date ? end : new Date(end);
  if (!Number.isFinite(e.getTime()) || e > published) return published;
  return e;
}

/** Count non-null numeric samples in a statistic series. */
export function countSeriesPoints(series, field = "values") {
  const arr = series?.[field] || series?.values || [];
  let n = 0;
  for (const v of arr) {
    if (v != null && Number.isFinite(Number(v))) n += 1;
  }
  return n;
}

/**
 * True when every finite primary (kWh) timestamp has a finite secondary (cost)
 * sample. Partial / mid-window cost must not baseline a full-window energy total.
 *
 * @param {{xs?: number[], values?: (number|null)[]}|null|undefined} primary
 * @param {{xs?: number[], values?: (number|null)[]}|null|undefined} secondary
 */
export function seriesCostCoverageComplete(primary, secondary) {
  const sec = new Set();
  for (let i = 0; i < (secondary?.xs || []).length; i++) {
    const rawV = secondary.values?.[i];
    // Number(null) === 0 — must not treat explicit null as observed $0 cost.
    if (rawV == null) continue;
    const x = Number(secondary.xs[i]);
    const v = Number(rawV);
    if (!Number.isFinite(x) || !Number.isFinite(v)) continue;
    sec.add(x);
  }
  let primaryCount = 0;
  for (let i = 0; i < (primary?.xs || []).length; i++) {
    const rawV = primary.values?.[i];
    if (rawV == null) continue;
    const x = Number(primary.xs[i]);
    const v = Number(rawV);
    if (!Number.isFinite(x) || !Number.isFinite(v)) continue;
    primaryCount += 1;
    if (!sec.has(x)) return false;
  }
  return primaryCount > 0;
}

function _finiteNums(arr) {
  const out = [];
  for (const v of arr || []) {
    if (v == null || Number.isNaN(Number(v))) continue;
    out.push(Number(v));
  }
  return out;
}

function _sum(nums) {
  let t = 0;
  for (const n of nums) t += n;
  return t;
}

function _mean(nums) {
  return nums.length ? _sum(nums) / nums.length : null;
}

function _median(nums) {
  if (!nums.length) return null;
  const s = [...nums].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

function _stdev(nums) {
  if (nums.length < 2) return null;
  const m = _mean(nums);
  let acc = 0;
  for (const n of nums) acc += (n - m) ** 2;
  return Math.sqrt(acc / (nums.length - 1));
}

function _extremum(nums, xs, preferMax) {
  if (!nums.length) return { value: null, at: null };
  let best = nums[0];
  let bestI = 0;
  for (let i = 1; i < nums.length; i++) {
    if (preferMax ? nums[i] > best : nums[i] < best) {
      best = nums[i];
      bestI = i;
    }
  }
  return { value: best, at: xs?.[bestI] ?? null };
}

function _seriesStats(values, xs) {
  const paired = [];
  for (let i = 0; i < (values || []).length; i++) {
    const v = values[i];
    if (v == null || Number.isNaN(Number(v))) continue;
    paired.push({ v: Number(v), t: xs?.[i] ?? null });
  }
  const nums = paired.map((p) => p.v);
  const peak = _extremum(nums, paired.map((p) => p.t), true);
  const low = _extremum(nums, paired.map((p) => p.t), false);
  return {
    count: nums.length,
    total: nums.length ? _sum(nums) : null,
    mean: _mean(nums),
    median: _median(nums),
    min: low.value,
    max: peak.value,
    stdev: _stdev(nums),
    peakAt: peak.at,
    lowAt: low.at,
  };
}

/**
 * Which statistic periods / rollup tables to load for a Usage range span.
 * Keeps hour detail for short windows; day/month/year for long history
 * (including multi-decade imports).
 */
export function accountingPlan(spanDays, chartPeriod = "hour") {
  const days = Number(spanDays) || 0;
  const period = chartPeriod || "hour";
  // Hour series: fine up to ~13 months (~9k points); decades use day/month.
  const needHour = period === "hour" ? days <= 400 : days <= 45;
  const needDay = days > 1.1 || period === "day";
  const needMonth = days > 45 || period === "month";
  const showHours = needHour && days <= 14;
  const showDays = needDay && days <= 400;
  const showMonths = needMonth || days > 45;
  // Year table once the window can span 2 calendar years or ~6+ months.
  const showYears = days > 180;
  let scale = "hours";
  if (days > 180) scale = "years";
  else if (days > 45) scale = "months";
  else if (days > 2) scale = "days";
  return {
    scale,
    needHour,
    needDay,
    needMonth,
    showHours,
    showDays,
    showMonths,
    showYears,
  };
}

function _tempField(temp) {
  return temp?.means?.some((v) => v != null) ? temp.means : temp?.values;
}

/**
 * Bucket $/kWh for signed-or-import accounting.
 *
 * Import-cost mode: only when net flow is a clear import (avoids negative
 * “Avg import $/kWh” on net-export buckets). Net-amount mode: allow signed
 * cost ÷ signed kWh (credit ÷ export can be a positive effective rate).
 *
 * When signed flow has a gross-import denominator (net flow + returned), the
 * import-cost rate uses gross import so export-heavy buckets do not overstate
 * “$/kWh” (mirrors `_avgImportRate` at range level).
 */
function _bucketRate(cost, kwh, amountMode = "import", grossImport = null) {
  if (cost == null || kwh == null) return null;
  const c = Number(cost);
  const k = Number(kwh);
  if (!Number.isFinite(c) || !Number.isFinite(k)) return null;
  if (amountMode === "net") {
    return Math.abs(k) > RATE_EPSILON_KWH ? c / k : null;
  }
  const g = Number(grossImport);
  if (Number.isFinite(g)) {
    return g > RATE_EPSILON_KWH ? c / g : null;
  }
  return k > RATE_EPSILON_KWH ? c / k : null;
}

/**
 * Range-level average rate. When flow is signed but amount is still import
 * cost (no compensation observed), prefer gross import (net + return).
 */
function _avgImportRate(totalCost, totalKwh, returnedValues, flowMode, amountMode) {
  if (!Number.isFinite(Number(totalCost))) return null;
  const cost = Number(totalCost);
  const kwh = Number(totalKwh) || 0;
  if (amountMode === "net") {
    return Math.abs(kwh) > RATE_EPSILON_KWH ? cost / kwh : null;
  }
  if (flowMode === "signed") {
    const retNums = _finiteNums(returnedValues);
    if (retNums.length) {
      const grossImport = kwh + _sum(retNums);
      return grossImport > RATE_EPSILON_KWH ? cost / grossImport : null;
    }
  }
  return kwh > RATE_EPSILON_KWH ? cost / kwh : null;
}

function _rollupRows(kwh, cost, temp, keyFn, amountMode = "import", returned = null) {
  const tempField = _tempField(temp);
  const costByT = new Map((cost?.xs || []).map((t, i) => [t, cost.values[i]]));
  const tempByT = new Map((temp?.xs || []).map((t, i) => [t, (tempField || [])[i]]));
  const retByT = returned?.xs?.length ? _seriesMap(returned) : null;
  const map = new Map();
  for (let i = 0; i < (kwh?.xs || []).length; i++) {
    const t = kwh.xs[i];
    const kv = kwh.values[i];
    if (t == null || kv == null || Number.isNaN(Number(kv))) continue;
    const key = keyFn(t);
    if (!key) continue;
    const row = map.get(key) || {
      key,
      kwh: 0,
      cost: 0,
      tempSum: 0,
      tempN: 0,
      samples: 0,
      firstT: t,
      peakKwh: null,
      peakT: null,
      grossImport: retByT ? 0 : null,
    };
    const n = Number(kv);
    row.kwh += n;
    row.samples += 1;
    if (row.peakKwh == null || n > row.peakKwh) {
      row.peakKwh = n;
      row.peakT = t;
    }
    if (retByT) {
      const rv = retByT.get(t);
      row.grossImport += Math.max(0, n + (Number.isFinite(rv) ? rv : 0));
    }
    const c = costByT.get(t);
    if (c != null && Number.isFinite(Number(c))) row.cost += Number(c);
    const tf = tempByT.get(t);
    if (tf != null && Number.isFinite(Number(tf))) {
      row.tempSum += Number(tf);
      row.tempN += 1;
    }
    map.set(key, row);
  }
  return [...map.keys()]
    .sort()
    .map((key) => {
      const r = map.get(key);
      return {
        key,
        kwh: r.kwh,
        cost: r.cost,
        avgTemp: r.tempN ? r.tempSum / r.tempN : null,
        samples: r.samples,
        rate: _bucketRate(r.cost, r.kwh, amountMode, r.grossImport),
        grossImport: retByT ? r.grossImport : null,
        peakKwh: r.peakKwh,
        peakAt: r.peakT,
      };
    });
}

function _pacificMonthKey(unixSec) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Los_Angeles",
    year: "numeric",
    month: "2-digit",
  }).format(new Date(unixSec * 1000)); // YYYY-MM
}

function _pacificYearKey(unixSec) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Los_Angeles",
    year: "numeric",
  }).format(new Date(unixSec * 1000));
}

function _bestWorst(rows, field = "kwh") {
  if (!rows?.length) return { best: null, worst: null };
  let best = rows[0];
  let worst = rows[0];
  for (const r of rows) {
    if (r[field] > best[field]) best = r;
    if (r[field] < worst[field]) worst = r;
  }
  return { best, worst };
}

/**
 * Project a raw fetch triple into chart-shaped series for accounting/charts.
 * Temp is passed through unchanged. Call once per grain (hour/day/month).
 *
 * @param {{kwh?, returned?, cost?, compensation?, temp?}} raw
 */
export function projectUsageSeries(raw = {}) {
  const projected = projectDirectionalUsage(raw);
  return {
    kwh: projected.flow,
    cost: projected.amount,
    temp: raw.temp || { xs: [], values: [], means: [] },
    returned: raw.returned || { xs: [], values: [] },
    compensation: raw.compensation || { xs: [], values: [] },
    hasReturn: projected.hasReturn,
    hasCompensation: projected.hasCompensation,
    flowMode: projected.flowMode,
    amountMode: projected.amountMode,
  };
}

/**
 * Multi-scale Usage accounting. Prefer the finest available series for rollups
 * (hour → day → month); chart-bucket stats always come from ``chart``.
 *
 * Callers should pass already-projected chart/hourly/daily/monthly series
 * (``projectUsageSeries`` at each grain) so signed flow and net interval
 * amounts stay aligned.
 *
 * @param {{kwh,cost,temp,flowMode?,amountMode?}} chart
 * @param {{start,end,period,hourly?,daily?,monthly?}} opts
 */
export function computeUsageAccounting(
  chart,
  { start, end, period, hourly = null, daily = null, monthly = null } = {}
) {
  const kwh = chart?.kwh;
  const cost = chart?.cost;
  const temp = chart?.temp;
  const flowMode = chart?.flowMode || "import";
  const amountMode = chart?.amountMode || "import";
  const startDate = start instanceof Date ? start : new Date(start);
  const endDate = end instanceof Date ? end : new Date(end);
  const spanMs = Math.max(0, endDate.getTime() - startDate.getTime());
  const spanHours = spanMs / HOUR_MS;
  const spanDays = spanHours / 24;
  const spanMonths = spanDays / 30.437;
  const spanYears = spanDays / 365.25;
  const plan = accountingPlan(spanDays, period);

  const kwhStats = _seriesStats(kwh?.values, kwh?.xs);
  const costStats = _seriesStats(cost?.values, cost?.xs);
  const tempStats = _seriesStats(_tempField(temp), temp?.xs);

  // Prefer coarser undownsampled series for lifetime totals when available.
  const totalSource = monthly?.kwh?.xs?.length
    ? monthly
    : daily?.kwh?.xs?.length
      ? daily
      : hourly?.kwh?.xs?.length
        ? hourly
        : chart;
  const coarseKwh = _finiteNums(totalSource.kwh?.values);
  const coarseCost = _finiteNums(totalSource.cost?.values);
  // Preserve legitimate 0 totals from undownsampled series; only fall back when
  // that source has no finite samples (|| would treat 0 as missing).
  const totalKwh = coarseKwh.length ? _sum(coarseKwh) : kwhStats.total || 0;
  const totalCost = coarseCost.length ? _sum(coarseCost) : costStats.total || 0;
  const avgRate = _avgImportRate(
    totalCost,
    totalKwh,
    totalSource.returned?.values,
    flowMode,
    amountMode
  );

  const hourSource = hourly || (period === "hour" ? chart : null);
  const daySource = daily || (period === "day" ? chart : null) || hourSource;
  const monthSource = monthly || (period === "month" ? chart : null) || daySource;

  const hours = hourSource
    ? _rollupRows(
        hourSource.kwh,
        hourSource.cost,
        hourSource.temp,
        (t) => {
          const d = new Date(t * 1000);
          return new Intl.DateTimeFormat("en-CA", {
            timeZone: "America/Los_Angeles",
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            hour12: false,
          })
            .format(d)
            .replace(", ", "T");
        },
        amountMode,
        hourSource.returned
      )
    : [];

  const days = daySource
    ? _rollupRows(
        daySource.kwh,
        daySource.cost,
        daySource.temp,
        (t) => pacificYmd(new Date(t * 1000)),
        amountMode,
        daySource.returned
      )
    : [];

  const months = monthSource
    ? _rollupRows(
        monthSource.kwh,
        monthSource.cost,
        monthSource.temp,
        (t) => _pacificMonthKey(t),
        amountMode,
        monthSource.returned
      )
    : [];

  const years = months.length
    ? (() => {
        const map = new Map();
        for (const m of months) {
          const y = m.key.slice(0, 4);
          const row = map.get(y) || {
            key: y,
            kwh: 0,
            cost: 0,
            tempSum: 0,
            tempN: 0,
            samples: 0,
            peakKwh: null,
            peakAt: null,
            grossImport: null,
          };
          row.kwh += m.kwh;
          row.cost += m.cost;
          row.samples += m.samples;
          if (m.grossImport != null) {
            row.grossImport = (row.grossImport || 0) + m.grossImport;
          }
          if (m.avgTemp != null) {
            row.tempSum += m.avgTemp;
            row.tempN += 1;
          }
          if (m.peakKwh != null && (row.peakKwh == null || m.peakKwh > row.peakKwh)) {
            row.peakKwh = m.peakKwh;
            row.peakAt = m.peakAt;
          }
          map.set(y, row);
        }
        return [...map.keys()]
          .sort()
          .map((key) => {
            const r = map.get(key);
            return {
              key,
              kwh: r.kwh,
              cost: r.cost,
              avgTemp: r.tempN ? r.tempSum / r.tempN : null,
              samples: r.samples,
              rate: _bucketRate(r.cost, r.kwh, amountMode, r.grossImport),
              grossImport: r.grossImport,
              peakKwh: r.peakKwh,
              peakAt: r.peakAt,
            };
          });
      })()
    : daySource
      ? _rollupRows(
          daySource.kwh,
          daySource.cost,
          daySource.temp,
          (t) => _pacificYearKey(t),
          amountMode,
          daySource.returned
        )
      : [];

  const dayBW = _bestWorst(days);
  const monthBW = _bestWorst(months);
  const yearBW = _bestWorst(years);
  const hourBW = _bestWorst(hours);

  // Hour-level stats from true hourly series when present.
  const hourStats = hourSource
    ? _seriesStats(hourSource.kwh?.values, hourSource.kwh?.xs)
    : null;
  const hourCostStats = hourSource
    ? _seriesStats(hourSource.cost?.values, hourSource.cost?.xs)
    : null;
  const hourTempStats = hourSource
    ? _seriesStats(_tempField(hourSource.temp), hourSource.temp?.xs)
    : null;

  return {
    period: period || "hour",
    plan,
    flowMode,
    amountMode,
    spanHours,
    spanDays,
    spanMonths,
    spanYears,
    daysCovered: days.length,
    monthsCovered: months.length,
    yearsCovered: years.length,
    totalKwh,
    totalCost,
    avgRate,
    avgKwhPerHour: spanHours > 0 ? totalKwh / spanHours : null,
    avgKwhPerDay: spanDays > 0 ? totalKwh / spanDays : null,
    avgKwhPerMonth: spanMonths > 0 ? totalKwh / spanMonths : null,
    avgKwhPerYear: spanYears > 0 ? totalKwh / spanYears : null,
    avgCostPerHour: spanHours > 0 ? totalCost / spanHours : null,
    avgCostPerDay: spanDays > 0 ? totalCost / spanDays : null,
    avgCostPerMonth: spanMonths > 0 ? totalCost / spanMonths : null,
    avgCostPerYear: spanYears > 0 ? totalCost / spanYears : null,
    kwh: kwhStats,
    cost: costStats,
    temp: tempStats,
    hour: hourStats,
    hourCost: hourCostStats,
    hourTemp: hourTempStats,
    hours,
    days,
    months,
    years,
    bestDay: dayBW.best,
    worstDay: dayBW.worst,
    bestMonth: monthBW.best,
    worstMonth: monthBW.worst,
    bestYear: yearBW.best,
    worstYear: yearBW.worst,
    bestHour: hourBW.best,
    worstHour: hourBW.worst,
  };
}

/**
 * Shift a resolved chart window by ``steps`` window-lengths (negative = older).
 * Clamps so ``end`` never passes {@link publishedDataEnd}.
 */
export function shiftChartRange(range, steps = 0, now = new Date()) {
  const start0 = range.start instanceof Date ? range.start : new Date(range.start);
  const end0 = range.end instanceof Date ? range.end : new Date(range.end);
  const duration = Math.max(HOUR_MS, end0.getTime() - start0.getTime());
  const published = publishedDataEnd(now);
  let end = new Date(end0.getTime() + Number(steps) * duration);
  let start = new Date(start0.getTime() + Number(steps) * duration);
  if (end.getTime() > published.getTime()) {
    end = published;
    start = new Date(end.getTime() - duration);
  }
  return { ...range, start, end };
}

/**
 * Minimum non-null consumption points required before a preset is offered.
 * Short windows require most of their hours so empty shells stay hidden.
 */
export function minPointsForPreset(key) {
  switch (key) {
    case "6h":
      return 4;
    case "12h":
      return 8;
    case "24h":
    case "yesterday":
      return 12;
    case "7d":
      return 12;
    case "30d":
      return 7;
    case "cycle":
    case "last_cycle":
      return 1;
    case "3mo":
      return 14;
    case "6mo":
      return 30;
    case "12mo":
    case "ytd":
      return 7;
    default:
      return 1;
  }
}

/** Format a Pacific-aware range label for the Usage toolbar. */
export function formatRangeLabel(start, end) {
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Los_Angeles",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
  const a = start instanceof Date ? start : new Date(start);
  const b = end instanceof Date ? end : new Date(end);
  if (!Number.isFinite(a.getTime()) || !Number.isFinite(b.getTime())) return "";
  // Exclusive end: show last included instant when sub-day.
  const shownEnd = new Date(Math.max(a.getTime(), b.getTime() - 1));
  return `${fmt.format(a)} → ${fmt.format(shownEnd)} PT`;
}

export function stateNumber(hass, entityId) {
  if (!entityId || !hass.states[entityId]) return null;
  const v = Number(hass.states[entityId].state);
  return Number.isFinite(v) ? v : null;
}

export function stateDisplay(hass, entityId, fallback = "—") {
  if (!entityId || !hass.states[entityId]) return fallback;
  const st = hass.states[entityId];
  if (st.state === "unknown" || st.state === "unavailable") return fallback;
  return st.state;
}

export function stateAttr(hass, entityId, attr) {
  if (!entityId || !hass.states[entityId]) return null;
  return hass.states[entityId].attributes?.[attr] ?? null;
}

// ---------------------------------------------------------------------------
// Time of Day (E-TOU) schedule — mirrors tod_schedule.py for panel rendering.
// Weekday windows (Pacific): off [21:00,07:00) / mid [07:00,17:00) / on
// [17:00,21:00). Weekends + observed holidays are off-peak all day.
// ---------------------------------------------------------------------------

export const TOD_PERIODS = ["off_peak", "mid_peak", "on_peak"];

export const TOD_PERIOD_LABELS = {
  off_peak: "Off-peak",
  mid_peak: "Mid-peak",
  on_peak: "On-peak",
};

/** 0-23 Pacific-local hour for an epoch-seconds / ms / ISO / Date instant. */
export function pacificHour(t) {
  const d = _asDate(t);
  const raw = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Los_Angeles",
    hour: "2-digit",
    hour12: false,
  }).format(d);
  // Midnight can format as "24" depending on the engine.
  const n = Number(raw);
  return n === 24 ? 0 : n;
}

/** Pacific YYYY-MM-DD + hour for an instant (single helper for TOD bucketing). */
export function pacificParts(t) {
  return { ymd: pacificYmd(t), hour: pacificHour(t) };
}

function _observedIso(date) {
  const ymd = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(
    date.getDate()
  ).padStart(2, "0")}`;
  return ymd;
}

/** First (nth>=1) or last (nth=-1) weekday of a month → Date. */
function _nthWeekday(year, month, nth, weekday) {
  const first = new Date(year, month, 1);
  const firstWday = first.getDay();
  const day = 1 + ((weekday - firstWday + 7) % 7);
  if (nth > 0) return new Date(year, month, day + (nth - 1) * 7);
  const last = new Date(year, month + 1, 0);
  const lastWday = last.getDay();
  return new Date(year, month, last.getDate() - ((lastWday - weekday + 7) % 7));
}

/** Shift a fixed holiday to its observed day: Sat→Fri, Sun→Mon. */
function _observed(date) {
  const wd = date.getDay();
  if (wd === 6) return new Date(date.getFullYear(), date.getMonth(), date.getDate() - 1);
  if (wd === 0) return new Date(date.getFullYear(), date.getMonth(), date.getDate() + 1);
  return date;
}

/**
 * Observed PGE holidays (YYYY-MM-DD) for a year — mirrors tod_schedule.py,
 * including the Dec 31 edge case when next Jan 1 is a Saturday.
 */
const _todHolidayCache = new Map();

export function todHolidays(year) {
  const cached = _todHolidayCache.get(year);
  if (cached) return cached;
  const observed = new Set();
  const fixed = [
    new Date(year, 0, 1),
    new Date(year, 6, 4),
    new Date(year, 11, 25),
  ];
  for (const d of fixed) {
    const obs = _observed(d);
    if (obs.getFullYear() === year) observed.add(_observedIso(obs));
  }
  observed.add(_observedIso(_nthWeekday(year, 4, -1, 1))); // Memorial: last Mon May
  observed.add(_observedIso(_nthWeekday(year, 8, 1, 1))); // Labor: first Mon Sep
  observed.add(_observedIso(_nthWeekday(year, 10, 4, 4))); // Thanksgiving: 4th Thu Nov
  const nextJan1 = new Date(year + 1, 0, 1);
  if (nextJan1.getDay() === 6) observed.add(`${year}-12-31`);
  _todHolidayCache.set(year, observed);
  return observed;
}

/** True for Saturday, Sunday, or a PGE holiday (all-day off-peak). */
export function isTodOffPeakDay(ymd) {
  const [y, m, d] = ymd.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  const wd = dt.getDay();
  if (wd === 0 || wd === 6) return true;
  return todHolidays(y).has(ymd);
}

/**
 * E-TOU period for a Pacific YYYY-MM-DD + local hour (0-23).
 * @returns {"off_peak"|"mid_peak"|"on_peak"}
 */
export function todPeriodForPacific(ymd, hour) {
  if (isTodOffPeakDay(ymd)) return "off_peak";
  if (hour < 7) return "off_peak";
  if (hour < 17) return "mid_peak";
  if (hour < 21) return "on_peak";
  return "off_peak";
}

/**
 * Bucket an hourly statistic series by E-TOU period (Pacific), summing values.
 * @param {{xs: number[], values: (number|null)[]}} series
 * @returns {{off_peak: number, mid_peak: number, on_peak: number}}
 */
export function bucketTodByPeriod(series) {
  const totals = { off_peak: 0, mid_peak: 0, on_peak: 0 };
  for (let i = 0; i < (series.xs || []).length; i++) {
    const v = Number(series.values?.[i]);
    if (!Number.isFinite(v)) continue;
    const { ymd, hour } = pacificParts(series.xs[i]);
    totals[todPeriodForPacific(ymd, hour)] += v;
  }
  return totals;
}

/**
 * Local TOD vs billed vs rate-card Basic comparison for the panel hub.
 *
 * When not enrolled, billed imported cost is treated as actual Basic energy
 * charges and TOD is period kWh × effective TOD rates. When enrolled, billed
 * cost is TOD and the alternative is kWh × the Basic rate card (not inferred
 * ¢/kWh — TOD-shaped bills are not a flat Basic rate).
 *
 * Requires observed cost samples with complete timestamp coverage of imported
 * kWh (`hasCost: true`). Empty or partial cost (Include cost off / mid-window
 * cost history) must not be treated as $0 billed energy.
 * Enrollment is tri-state: unknown withholds the enrollment-specific verdict.
 *
 * @param {{
 *   kwh: {off_peak?: number, mid_peak?: number, on_peak?: number},
 *   cost: {off_peak?: number, mid_peak?: number, on_peak?: number},
 *   rates: {off_peak?: number, mid_peak?: number, on_peak?: number},
 *   basicRate: number|null|undefined,
 *   enrolled: boolean|null|undefined,
 *   hasCost?: boolean,
 * }} input
 * @returns {null | {
 *   totalKwh: number,
 *   billed: number,
 *   effectiveUsdPerKwh: number|null,
 *   todPriced: number|null,
 *   todPricedByPeriod: {off_peak: number, mid_peak: number, on_peak: number}|null,
 *   rateCardBasic: number|null,
 *   rateCardDelta: number|null,
 *   vsBilled: number|null,
 *   enrolled: boolean|null,
 *   alternativePlan: "tod"|"basic"|null,
 * }}
 */
export function computeTodPlanCompare({
  kwh,
  cost,
  rates,
  basicRate,
  enrolled,
  hasCost = true,
}) {
  const totalKwh = TOD_PERIODS.reduce((sum, p) => sum + (Number(kwh?.[p]) || 0), 0);
  if (!(totalKwh > 0)) return null;
  // Missing cost must not become a $0 billed baseline (false savings verdict).
  if (hasCost !== true) return null;

  const billed = TOD_PERIODS.reduce((sum, p) => sum + (Number(cost?.[p]) || 0), 0);
  const todPricedByPeriod = { off_peak: 0, mid_peak: 0, on_peak: 0 };
  let todPriced = 0;
  let ratesOk = true;
  for (const p of TOD_PERIODS) {
    const rawRate = rates?.[p];
    // Number(null) === 0 — missing period rates must withhold the comparison.
    if (rawRate == null) {
      ratesOk = false;
      break;
    }
    const rate = Number(rawRate);
    if (!Number.isFinite(rate) || rate < 0) {
      ratesOk = false;
      break;
    }
    const priced = (Number(kwh?.[p]) || 0) * rate;
    todPricedByPeriod[p] = priced;
    todPriced += priced;
  }
  if (!ratesOk) {
    todPriced = null;
  }
  const basic = Number(basicRate);
  const rateCardBasic = Number.isFinite(basic) && basic > 0 ? totalKwh * basic : null;
  const effectiveUsdPerKwh = Number.isFinite(billed) ? billed / totalKwh : null;
  const enrollmentKnown = enrolled === true || enrolled === false;
  const isEnrolled = enrolled === true;
  const alternativePlan = !enrollmentKnown ? null : isEnrolled ? "basic" : "tod";
  const alternative = !enrollmentKnown ? null : isEnrolled ? rateCardBasic : todPriced;
  const vsBilled =
    alternative == null || !Number.isFinite(billed) ? null : alternative - billed;
  const rateCardDelta =
    rateCardBasic == null || todPriced == null ? null : rateCardBasic - todPriced;
  return {
    totalKwh,
    billed,
    effectiveUsdPerKwh,
    todPriced,
    todPricedByPeriod: ratesOk ? todPricedByPeriod : null,
    rateCardBasic,
    rateCardDelta,
    vsBilled,
    enrolled: enrollmentKnown ? isEnrolled : null,
    alternativePlan,
  };
}

/**
 * Plain-language cost outcome for the panel hero.
 *
 * Not enrolled: TOD-priced kWh vs billed energy (would cost more / would save).
 * Enrolled: billed TOD vs rate-card Basic (currently costing more / saving).
 * Unknown enrollment or missing vsBilled → unknown (no false verdict).
 *
 * @param {ReturnType<typeof computeTodPlanCompare>} compare
 * @returns {{kind: "cost_more"|"save"|"same"|"unknown", amount: number|null}}
 */
export function todEnrollmentVerdict(compare) {
  if (
    !compare ||
    compare.enrolled == null ||
    compare.vsBilled == null ||
    !Number.isFinite(compare.vsBilled)
  ) {
    return { kind: "unknown", amount: null };
  }
  const amount = Math.abs(compare.vsBilled);
  if (amount < 0.005) return { kind: "same", amount: 0 };
  if (!compare.enrolled) {
    return compare.vsBilled > 0
      ? { kind: "cost_more", amount }
      : { kind: "save", amount };
  }
  // vsBilled = Basic estimate − billed TOD; positive means TOD is cheaper.
  return compare.vsBilled > 0
    ? { kind: "save", amount }
    : { kind: "cost_more", amount };
}

/** Sun–Sat labels with the Pacific YYYY-MM-DD for the current week. */
export function todWeekDays(today = new Date()) {
  const nowLocal = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Los_Angeles",
  }).format(today);
  const [, mm, dd, yy] = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/.exec(nowLocal) || [];
  const start = new Date(Number(yy), Number(mm) - 1, Number(dd));
  const dow = start.getDay();
  const sunday = new Date(start.getFullYear(), start.getMonth(), start.getDate() - dow);
  const days = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(sunday.getFullYear(), sunday.getMonth(), sunday.getDate() + i);
    days.push({
      name: new Intl.DateTimeFormat("en-US", { weekday: "short" }).format(d),
      ymd: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
        d.getDate()
      ).padStart(2, "0")}`,
    });
  }
  return days;
}
