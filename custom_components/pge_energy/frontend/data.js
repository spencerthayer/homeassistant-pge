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

/**
 * Exclusive end of published PGE usage: Pacific midnight of the current
 * Pacific calendar day. PGE never publishes a complete "today" — only
 * closed days through yesterday.
 */
export function publishedDataEnd(now = new Date()) {
  return pacificMidnightUtc(pacificYmd(now));
}

const HOUR_MS = 60 * 60 * 1000;
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

function _rollupRows(kwh, cost, temp, keyFn) {
  const tempField = _tempField(temp);
  const costByT = new Map((cost?.xs || []).map((t, i) => [t, cost.values[i]]));
  const tempByT = new Map((temp?.xs || []).map((t, i) => [t, (tempField || [])[i]]));
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
    };
    const n = Number(kv);
    row.kwh += n;
    row.samples += 1;
    if (row.peakKwh == null || n > row.peakKwh) {
      row.peakKwh = n;
      row.peakT = t;
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
        rate: r.kwh > 0 ? r.cost / r.kwh : null,
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
 * Multi-scale Usage accounting. Prefer the finest available series for rollups
 * (hour → day → month); chart-bucket stats always come from ``chart``.
 *
 * @param {{kwh,cost,temp}} chart
 * @param {{start,end,period,hourly?,daily?,monthly?}} opts
 */
export function computeUsageAccounting(
  chart,
  { start, end, period, hourly = null, daily = null, monthly = null } = {}
) {
  const kwh = chart?.kwh;
  const cost = chart?.cost;
  const temp = chart?.temp;
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
  const totalKwh = _sum(_finiteNums(totalSource.kwh?.values)) || kwhStats.total || 0;
  const totalCost = _sum(_finiteNums(totalSource.cost?.values)) || costStats.total || 0;
  const avgRate = totalKwh > 0 ? totalCost / totalKwh : null;

  const hourSource = hourly || (period === "hour" ? chart : null);
  const daySource = daily || (period === "day" ? chart : null) || hourSource;
  const monthSource = monthly || (period === "month" ? chart : null) || daySource;

  const hours = hourSource
    ? _rollupRows(hourSource.kwh, hourSource.cost, hourSource.temp, (t) => {
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
      })
    : [];

  const days = daySource
    ? _rollupRows(daySource.kwh, daySource.cost, daySource.temp, (t) =>
        pacificYmd(new Date(t * 1000))
      )
    : [];

  const months = monthSource
    ? _rollupRows(monthSource.kwh, monthSource.cost, monthSource.temp, (t) =>
        _pacificMonthKey(t)
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
          };
          row.kwh += m.kwh;
          row.cost += m.cost;
          row.samples += m.samples;
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
              rate: r.kwh > 0 ? r.cost / r.kwh : null,
              peakKwh: r.peakKwh,
              peakAt: r.peakAt,
            };
          });
      })()
    : daySource
      ? _rollupRows(daySource.kwh, daySource.cost, daySource.temp, (t) =>
          _pacificYearKey(t)
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
