/**
 * Pure aggregations for the /pge chart gallery.
 * Timestamps are epoch seconds, the unit fetchStatisticSeries returns in xs.
 * This module does not call hass.
 */

import {
  isTodOffPeakDay,
  pacificMidnightUtc,
  pacificParts,
  pacificYmd,
  publishedDataEnd,
  todPeriodForPacific,
} from "./data.js?v=0.12.4";

function finite(value) {
  if (value == null || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function mean(values) {
  if (!values.length) return null;
  let total = 0;
  for (const value of values) total += value;
  return total / values.length;
}

/** Weekday index for a Pacific YYYY-MM-DD. 0 is Sunday. */
function weekdayIndex(ymd) {
  const [year, month, day] = ymd.split("-").map(Number);
  return new Date(year, month - 1, day).getDay();
}

function addDays(ymd, days) {
  const [year, month, day] = ymd.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day + days));
  const yy = date.getUTCFullYear();
  const mm = String(date.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(date.getUTCDate()).padStart(2, "0");
  return `${yy}-${mm}-${dd}`;
}

function dayIndexBetween(startYmd, ymd) {
  const [ay, am, ad] = startYmd.split("-").map(Number);
  const [by, bm, bd] = ymd.split("-").map(Number);
  const delta = Date.UTC(by, bm - 1, bd) - Date.UTC(ay, am - 1, ad);
  return Math.round(delta / 86400000);
}

function emptyHours() {
  return Array.from({ length: 24 }, () => []);
}

/**
 * Weekday vs weekend mean kWh by Pacific hour.
 * @returns {{ weekday: (number|null)[], weekend: (number|null)[] }}
 */
export function typicalDayProfiles(samples) {
  const weekday = emptyHours();
  const weekend = emptyHours();
  for (const sample of samples || []) {
    const kwh = finite(sample.kwh);
    if (kwh == null || sample.ts == null) continue;
    const { ymd, hour } = pacificParts(sample.ts);
    const weekendDay = weekdayIndex(ymd) === 0 || weekdayIndex(ymd) === 6;
    (weekendDay ? weekend : weekday)[hour].push(kwh);
  }
  const average = (columns) => columns.map((values) => (values.length ? mean(values) : null));
  return { weekday: average(weekday), weekend: average(weekend) };
}

/** Finite kWh values, largest first. */
export function loadDuration(samples) {
  return (samples || [])
    .map((sample) => finite(sample.kwh))
    .filter((value) => value != null)
    .sort((a, b) => b - a);
}

/**
 * Mean kWh on a Sunday-first 7 by 24 grid.
 * @returns {{ labels: string[], values: (number|null)[][] }}
 */
export function hourWeekdayMatrix(samples) {
  const buckets = Array.from({ length: 7 }, () => emptyHours());
  for (const sample of samples || []) {
    const kwh = finite(sample.kwh);
    if (kwh == null || sample.ts == null) continue;
    const { ymd, hour } = pacificParts(sample.ts);
    buckets[weekdayIndex(ymd)][hour].push(kwh);
  }
  return {
    labels: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
    values: buckets.map((row) => row.map((values) => (values.length ? mean(values) : null))),
  };
}

/** One mean-kWh hour profile per Pacific month present in the samples. */
export function monthRidges(samples) {
  const byMonth = new Map();
  for (const sample of samples || []) {
    const kwh = finite(sample.kwh);
    if (kwh == null || sample.ts == null) continue;
    const { ymd, hour } = pacificParts(sample.ts);
    const key = ymd.slice(0, 7);
    if (!byMonth.has(key)) byMonth.set(key, emptyHours());
    byMonth.get(key)[hour].push(kwh);
  }
  return [...byMonth.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, hours]) => ({
      key,
      hours: hours.map((values) => (values.length ? mean(values) : null)),
    }));
}

/**
 * Minimum kWh on nights that have every real Pacific 00:00–06:00 hourly slot.
 * Spring-forward nights need 5 slots, ordinary nights 6, fall-back nights 7.
 * Sparse coarse rows and incomplete nights are left out. Large loads are kept.
 * @returns {{ ymd: string, kwh: number }[]}
 */
export function overnightFloorDays(samples) {
  const byDay = new Map();
  for (const sample of samples || []) {
    const kwh = finite(sample.kwh);
    if (!Number.isFinite(sample.ts) || kwh == null || kwh < 0) continue;
    const ymd = pacificYmd(sample.ts);
    const start = pacificMidnightUtc(ymd).getTime() / 1000;
    const probe = Date.parse(`${ymd}T12:00:00Z`) / 1000;
    const end = probe + (6 - pacificParts(probe).hour) * 3600;
    if (sample.ts < start || sample.ts >= end || (sample.ts - start) % 3600) continue;
    if (!byDay.has(ymd)) byDay.set(ymd, { start, end, slots: new Map() });
    byDay.get(ymd).slots.set(sample.ts, kwh);
  }
  return [...byDay.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .flatMap(([ymd, { start, end, slots }]) =>
      slots.size === (end - start) / 3600 ? [{ ymd, kwh: Math.min(...slots.values()) }] : [],
    );
}

/**
 * Daily kWh summed into calendar months, one series per year.
 * Unobserved months stay null so a future month is not drawn as zero.
 * @returns {{ years: string[], series: (number|null)[][] }}
 */
export function monthlyByYear(samples) {
  const days = new Map();
  for (const sample of samples || []) {
    const kwh = finite(sample.kwh);
    if (!Number.isFinite(sample.ts) || kwh == null) continue;
    days.set(pacificYmd(sample.ts), kwh);
  }
  const months = new Map();
  for (const [ymd, kwh] of days) {
    const key = ymd.slice(0, 7);
    const row = months.get(key) || { count: 0, total: 0 };
    row.count += 1;
    row.total += kwh;
    months.set(key, row);
  }
  const years = [...new Set([...months.keys()].map((key) => key.slice(0, 4)))].sort();
  return {
    years,
    series: years.map((year) =>
      Array.from({ length: 12 }, (_, month) => {
        const row = months.get(`${year}-${String(month + 1).padStart(2, "0")}`);
        const expected = new Date(Date.UTC(Number(year), month + 1, 0)).getUTCDate();
        return row?.count === expected ? row.total : null;
      }),
    ),
  };
}

/**
 * Cumulative kWh by Pacific day index from a statement start (epoch seconds).
 * @returns {{ dayIndex: number[], cumulative: number[] }}
 */
export function cycleCumulative(samples, startTs) {
  const startYmd = pacificYmd(startTs);
  const byDay = new Map();
  for (const sample of samples || []) {
    const kwh = finite(sample.kwh);
    if (!Number.isFinite(sample.ts) || sample.ts < startTs || kwh == null) continue;
    const index = dayIndexBetween(startYmd, pacificYmd(sample.ts));
    byDay.set(index, (byDay.get(index) || 0) + kwh);
  }
  const last = byDay.size ? Math.max(...byDay.keys()) : -1;
  const dayIndex = [];
  const cumulative = [];
  let total = 0;
  let complete = true;
  for (let day = 0; day <= last; day++) {
    dayIndex.push(day);
    if (!byDay.has(day)) complete = false;
    if (complete) total += byDay.get(day);
    cumulative.push(complete ? total : null);
  }
  return { dayIndex, cumulative };
}

/**
 * One row per Pacific day from startYmd inclusive to endYmdExclusive.
 * Absent days and dates in confirmedMissing stay null. A recorded zero stays zero.
 */
export function gapDailyRows(rows, startYmd, endYmdExclusive, confirmedMissing = new Set()) {
  const byDay = new Map(
    (rows || []).filter((row) => Number.isFinite(row.ts)).map((row) => [pacificYmd(row.ts), row]),
  );
  const out = [];
  for (let ymd = startYmd; ymd < endYmdExclusive; ymd = addDays(ymd, 1)) {
    const row = byDay.get(ymd);
    out.push({
      ...row,
      ts: pacificMidnightUtc(ymd).getTime() / 1000,
      kwh: confirmedMissing.has(ymd) ? null : finite(row?.kwh),
    });
  }
  return out;
}

/**
 * Mean and sample standard deviation. `low` / `high` are mean ± 2 sd.
 * @returns {{ mean: number, sd: number, low: number, high: number }|null}
 */
export function spreadBand(values) {
  const nums = (values || []).map(finite).filter((value) => value != null);
  if (nums.length < 2) return null;
  const center = mean(nums);
  const variance = nums.reduce((total, value) => total + (value - center) ** 2, 0) / (nums.length - 1);
  const sd = Math.sqrt(variance);
  return { mean: center, sd, low: center - 2 * sd, high: center + 2 * sd };
}

/**
 * Seven Pacific dates of the latest Sunday–Saturday week that has fully closed
 * before publishedDataEnd(now).
 */
export function publishedWeekDays(now = new Date()) {
  const end = publishedDataEnd(now);
  let cursor = new Date(end.getTime() - 1000);
  for (let i = 0; i < 8; i++) {
    const ymd = pacificYmd(cursor);
    if (weekdayIndex(ymd) === 6) {
      const start = addDays(ymd, -6);
      const keys = [];
      for (let day = 0; day < 7; day++) keys.push(addDays(start, day));
      return keys;
    }
    cursor = new Date(cursor.getTime() - 86400000);
  }
  return [];
}

/**
 * One row per closed day that has both kWh and a temperature sample.
 * @returns {{ ymd: string, kwh: number, peakHour: number, tempF: number, onPeakShare: number|null, centsPerKwh: number|null }[]}
 */
export function dayFingerprints(samples) {
  const days = new Map();
  for (const sample of samples || []) {
    if (sample.ts == null) continue;
    const ymd = pacificYmd(sample.ts);
    if (!days.has(ymd)) days.set(ymd, []);
    days.get(ymd).push(sample);
  }
  const rows = [];
  for (const [ymd, samplesForDay] of [...days.entries()].sort(([a], [b]) => a.localeCompare(b))) {
    const temps = samplesForDay.map((sample) => finite(sample.tempF)).filter((value) => value != null);
    const withKwh = samplesForDay.filter((sample) => finite(sample.kwh) != null);
    if (!withKwh.length || !temps.length) continue;
    let kwh = 0;
    let cost = 0;
    let onPeak = 0;
    let peakHour = 0;
    let peakKwh = -Infinity;
    for (const sample of withKwh) {
      const value = finite(sample.kwh);
      kwh += value;
      const hour = pacificParts(sample.ts).hour;
      if (value > peakKwh) {
        peakKwh = value;
        peakHour = hour;
      }
      if (todPeriodForPacific(ymd, hour) === "on_peak") onPeak += value;
      const sampleCost = finite(sample.cost);
      if (sampleCost != null) cost += sampleCost;
    }
    rows.push({
      ymd,
      kwh,
      peakHour,
      tempF: mean(temps),
      onPeakShare: kwh > 0 ? onPeak / kwh : null,
      centsPerKwh: kwh > 0 ? (cost / kwh) * 100 : null,
    });
  }
  return rows;
}

/** Minimum of the first six hourly means (Pacific hours 0 through 5). */
export function baseloadFloor(hourMeans) {
  const overnight = (hourMeans || []).slice(0, 6).map(finite).filter((value) => value != null);
  if (!overnight.length) return null;
  return Math.min(...overnight);
}

/**
 * Count daily kWh into fixed-width bins.
 * @returns {{ labels: string[], counts: number[] }}
 */
export function histogramBins(values, binCount = 12) {
  const nums = (values || []).map(finite).filter((value) => value != null);
  if (nums.length < 2) return { labels: [], counts: [] };
  const low = Math.min(...nums);
  const high = Math.max(...nums);
  const width = high === low ? 1 : (high - low) / binCount;
  const counts = Array(binCount).fill(0);
  for (const value of nums) {
    let index = Math.floor((value - low) / width);
    if (index >= binCount) index = binCount - 1;
    if (index < 0) index = 0;
    counts[index] += 1;
  }
  const labels = counts.map((_, index) => {
    const start = low + index * width;
    const end = start + width;
    return `${start.toFixed(1)} to ${end.toFixed(1)}`;
  });
  return { labels, counts };
}

/** Sum kWh into off_peak, mid_peak, and on_peak. */
export function periodKwh(samples) {
  const totals = { off_peak: 0, mid_peak: 0, on_peak: 0 };
  for (const sample of samples || []) {
    const kwh = finite(sample.kwh);
    if (kwh == null || sample.ts == null) continue;
    const { ymd, hour } = pacificParts(sample.ts);
    totals[todPeriodForPacific(ymd, hour)] += kwh;
  }
  return totals;
}

/** Percent of imported kWh in each period, by Pacific month. */
export function periodMixByMonth(samples) {
  const months = new Map();
  for (const sample of samples || []) {
    const kwh = finite(sample.kwh);
    if (kwh == null || sample.ts == null) continue;
    const { ymd, hour } = pacificParts(sample.ts);
    const month = ymd.slice(0, 7);
    if (!months.has(month)) months.set(month, { off_peak: 0, mid_peak: 0, on_peak: 0 });
    months.get(month)[todPeriodForPacific(ymd, hour)] += kwh;
  }
  return [...months.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([month, totals]) => {
      const sum = totals.off_peak + totals.mid_peak + totals.on_peak;
      const share = (value) => (sum > 0 ? (value / sum) * 100 : 0);
      return {
        month,
        off_peak: share(totals.off_peak),
        mid_peak: share(totals.mid_peak),
        on_peak: share(totals.on_peak),
      };
    });
}

/**
 * Clock hours ordered by kWh times the catalog rate for that hour's period.
 * At most eight rows.
 */
export function moneyHourPareto(samples, rates) {
  const byHour = new Map();
  for (const sample of samples || []) {
    if (sample.ts == null) continue;
    const explicit = finite(sample.dollars);
    const { ymd, hour } = pacificParts(sample.ts);
    let dollars = explicit;
    let kwh = finite(sample.kwh);
    if (dollars == null) {
      if (kwh == null) continue;
      const rate = finite(rates?.[todPeriodForPacific(ymd, hour)]);
      if (rate == null) continue;
      dollars = kwh * rate;
    }
    const row = byHour.get(hour) || { hour, dollars: 0, kwh: 0 };
    row.dollars += dollars;
    if (kwh != null) row.kwh += kwh;
    byHour.set(hour, row);
  }
  const ordered = [...byHour.values()]
    .sort((a, b) => b.dollars - a.dollars || b.hour - a.hour)
    .slice(0, 8);
  const total = ordered.reduce((sum, row) => sum + row.dollars, 0);
  let running = 0;
  return ordered.map((row) => {
    running += row.dollars;
    return { ...row, cumulativeShare: total ? (running / total) * 100 : 0 };
  });
}

/** Box stats for one period's hourly kWh values. */
export function periodBox(values) {
  const nums = (values || []).map(finite).filter((value) => value != null).sort((a, b) => a - b);
  if (!nums.length) return null;
  const middle = (list) => {
    const count = list.length;
    if (!count) return null;
    const index = Math.floor(count / 2);
    return count % 2 ? list[index] : (list[index - 1] + list[index]) / 2;
  };
  const median = middle(nums);
  const lower = middle(nums.slice(0, Math.floor(nums.length / 2)));
  const upper = middle(nums.slice(Math.ceil(nums.length / 2)));
  return {
    min: nums[0],
    q1: lower == null ? median : lower,
    median,
    q3: upper == null ? median : upper,
    max: nums[nums.length - 1],
  };
}

/** Monthly local Basic minus local TOD. Positive means TOD is lower. */
export function todMinusBasicByMonth(rows) {
  const months = new Map();
  for (const row of rows || []) {
    const tod = finite(row.tod);
    const basic = finite(row.basic);
    if (row.ts == null || tod == null || basic == null) continue;
    const month = pacificYmd(row.ts).slice(0, 7);
    const prev = months.get(month) || { month, tod: 0, basic: 0 };
    prev.tod += tod;
    prev.basic += basic;
    months.set(month, prev);
  }
  return [...months.values()]
    .sort((a, b) => a.month.localeCompare(b.month))
    .map((row) => ({ month: row.month, delta: row.basic - row.tod }));
}

/**
 * Next 48 Pacific hours of the offline schedule.
 * `means[weekday][hour]` is the historical mean kWh used as bar height.
 */
export function forwardRibbon({ startTs, means = null } = {}) {
  const rows = [];
  for (let step = 0; step < 48; step++) {
    const ts = startTs + step * 3600;
    const { ymd, hour } = pacificParts(ts);
    const weekday = weekdayIndex(ymd);
    const fromMeans = means?.[weekday]?.[hour];
    rows.push({
      ts,
      ymd,
      hour,
      period: todPeriodForPacific(ymd, hour),
      kwh: finite(fromMeans),
      label: `${ymd} ${String(hour).padStart(2, "0")}:00`,
    });
  }
  return rows;
}

/** Drop periods with no kWh so a Sankey node is not an empty stub. */
export function sankeyFlows(rows) {
  return (rows || []).filter((row) => {
    const kwh = finite(row.kwh);
    return kwh != null && kwh !== 0;
  });
}

const DEGREE_DAY_BASE_F = 65;

/** Heating and cooling degree days from a daily mean temperature. */
export function degreeDayPoint(tempF, base = DEGREE_DAY_BASE_F) {
  const temp = finite(tempF);
  if (temp == null) return null;
  return {
    heating: Math.max(0, base - temp),
    cooling: Math.max(0, temp - base),
  };
}

const TEMP_BINS = [
  { key: "under-40", label: "Under 40", match: (temp) => temp < 40 },
  { key: "40-49", label: "40 to 49", match: (temp) => temp >= 40 && temp < 50 },
  { key: "50-59", label: "50 to 59", match: (temp) => temp >= 50 && temp < 60 },
  { key: "60-69", label: "60 to 69", match: (temp) => temp >= 60 && temp < 70 },
  { key: "70-79", label: "70 to 79", match: (temp) => temp >= 70 && temp < 80 },
  { key: "80-up", label: "80 and above", match: (temp) => temp >= 80 },
];

/** Mean daily kWh in outdoor temperature bins. */
export function tempBins(days) {
  const groups = TEMP_BINS.map((bin) => ({ ...bin, values: [] }));
  for (const day of days || []) {
    const temp = finite(day.tempF);
    const kwh = finite(day.kwh);
    if (temp == null || kwh == null) continue;
    const bin = groups.find((row) => row.match(temp));
    if (bin) bin.values.push(kwh);
  }
  return groups.map((bin) => ({
    key: bin.key,
    label: bin.label,
    count: bin.values.length,
    meanKwh: bin.values.length ? mean(bin.values) : null,
  }));
}

/** Portal cents per kWh. Days with no imported kWh are omitted. */
export function centsPerKwh(days) {
  const points = [];
  for (const day of days || []) {
    const kwh = finite(day.kwh);
    const cost = finite(day.cost);
    if (kwh == null || kwh === 0 || cost == null) continue;
    points.push({ ...day, cents: (cost / kwh) * 100 });
  }
  return points;
}

/**
 * Approximate statement windows from consecutive bill timestamps.
 * When bounds are passed, they replace the last window. A single bill row
 * with no bounds yields no window. A single bill row with bounds is that window.
 */
export function statementWindows(bills, bounds = null) {
  const times = (bills || [])
    .map((bill) => bill.ts)
    .filter((ts) => ts != null)
    .sort((a, b) => a - b);
  const windows = [];
  for (let i = 1; i < times.length; i++) {
    windows.push({ start: times[i - 1], end: times[i], ledgerTs: times[i] });
  }
  if (bounds && bounds.start != null && bounds.end != null && bounds.end > bounds.start) {
    const ledgerTs = windows.length ? windows[windows.length - 1].ledgerTs : times.at(-1) ?? null;
    const current = { start: bounds.start, end: bounds.end, ledgerTs };
    if (windows.length) windows[windows.length - 1] = current;
    else windows.push(current);
  }
  return windows;
}

function sumInside(windows, samples, field) {
  return (windows || []).map((window) => {
    let total = 0;
    let seen = false;
    for (const sample of samples || []) {
      if (sample.ts == null || sample.ts < window.start || sample.ts >= window.end) continue;
      const value = finite(sample[field]);
      if (value == null) continue;
      seen = true;
      total += value;
    }
    return { start: window.start, end: window.end, total: seen ? total : null };
  });
}

/** Portal usage-estimate dollars inside each approximate statement window. */
export function statementGap(windows, samples) {
  return sumInside(windows, samples, "cost");
}

/** Imported kWh inside each approximate statement window. */
export function billVsImported(windows, samples) {
  return sumInside(windows, samples, "kwh");
}

/**
 * Tracker min/max stay flat guides. Running interval cost is not rescaled.
 */
export function openCycleCone({ min, max, samples } = {}) {
  return { min: finite(min), max: finite(max), samples: samples || [] };
}

function component(row, key) {
  return finite(row?.[key]) || 0;
}

/**
 * Signed payment credit.
 * Bill PDFs store a credit as a negative amount. A positive value is a magnitude.
 */
function paymentCredit(row) {
  const payment = finite(row?.payment_received);
  if (payment == null || payment === 0) return 0;
  return payment < 0 ? payment : -payment;
}

/** New charges from balance forward, or from previous due and payment. */
export function newCharges(row) {
  const due = finite(row?.amount_due);
  if (due == null) return null;
  const forward = finite(row?.balance_forward);
  if (forward != null) return due - forward;
  return due - component(row, "previous_amount_due") - paymentCredit(row);
}

/** Five bill families. Delivery and taxes are sums. Other is the residual. */
export function billFamilies(row) {
  const basic = component(row, "basic_charge");
  const energyUse = component(row, "energy_use_charge");
  const delivery = component(row, "transmission_charge") + component(row, "distribution_charge");
  const taxes = component(row, "taxes_and_investments") + component(row, "local_tax");
  const fresh = newCharges(row);
  const other = fresh == null ? 0 : fresh - (basic + energyUse + delivery + taxes);
  return [
    { key: "basic", label: "Basic", value: basic },
    { key: "energyUse", label: "Energy use", value: energyUse },
    { key: "delivery", label: "Delivery", value: delivery },
    { key: "taxes", label: "Taxes", value: taxes },
    { key: "other", label: "Other", value: other },
  ];
}

export function billAnatomyRows(statements) {
  return (statements || []).map((row) => {
    const families = billFamilies(row);
    const values = Object.fromEntries(families.map((family) => [family.key, family.value]));
    return { ts: row.ts, families, ...values };
  });
}

export function treemapSlices(statements) {
  const latest = [...(statements || [])].filter((row) => row?.ts != null).sort((a, b) => a.ts - b.ts).at(-1);
  if (!latest) return [];
  return billFamilies(latest);
}

export function waterfallSteps(statement) {
  const previous = component(statement, "previous_amount_due");
  const fresh = newCharges(statement) || 0;
  const due = component(statement, "amount_due");
  return [
    { key: "previous_amount_due", label: "Previous amount due", value: previous },
    { key: "payment_received", label: "Payment", value: paymentCredit(statement) },
    { key: "new_charges", label: "New charges", value: fresh },
    { key: "amount_due", label: "Amount due", value: due },
  ];
}

export function fixedVariableRows(statements) {
  return (statements || []).map((row) => ({ ts: row.ts, families: billFamilies(row) }));
}

export function lineItemShares(statement) {
  const families = billFamilies(statement);
  const total = families.reduce((sum, family) => sum + family.value, 0);
  return families.map((family) => ({
    ...family,
    share: total !== 0 ? (family.value / total) * 100 : 0,
  }));
}

/** Mean import and export kWh by Pacific hour. Return stays in its own array. */
export function duckHourProfiles(samples) {
  const consumption = emptyHours();
  const returned = emptyHours();
  for (const sample of samples || []) {
    if (sample.ts == null) continue;
    const hour = pacificParts(sample.ts).hour;
    const kwh = finite(sample.kwh);
    const back = finite(sample.returned);
    if (kwh != null) consumption[hour].push(kwh);
    if (back != null) returned[hour].push(back);
  }
  const average = (columns) => columns.map((values) => (values.length ? mean(values) : null));
  return { consumption: average(consumption), returned: average(returned) };
}

export function hasExport(samples) {
  return (samples || []).some((sample) => {
    const value = finite(sample.returned);
    return value != null && value > 0;
  });
}

/** Monthly import, export, usage estimate, and compensation for the duck months chart. */
export function duckMonthBars(samples) {
  const months = new Map();
  for (const sample of samples || []) {
    if (sample.ts == null) continue;
    const key = pacificYmd(sample.ts).slice(0, 7);
    const row = months.get(key) || { month: key, kwh: 0, returned: 0, cost: 0, compensation: 0 };
    const kwh = finite(sample.kwh);
    const back = finite(sample.returned);
    const cost = finite(sample.cost);
    const compensation = finite(sample.compensation);
    if (kwh != null) row.kwh += kwh;
    if (back != null) row.returned += back;
    if (cost != null) row.cost += cost;
    if (compensation != null) row.compensation += compensation;
    months.set(key, row);
  }
  return [...months.values()].sort((a, b) => a.month.localeCompare(b.month));
}

function median(values) {
  const nums = [...values].filter((value) => value != null).sort((a, b) => a - b);
  if (!nums.length) return null;
  const mid = Math.floor(nums.length / 2);
  return nums.length % 2 ? nums[mid] : (nums[mid - 1] + nums[mid]) / 2;
}

function mad(values) {
  const center = median(values);
  if (center == null) return 0;
  return median(values.map((value) => Math.abs(value - center))) || 0;
}

function dot(left, right) {
  let total = 0;
  for (let i = 0; i < left.length; i++) total += left[i] * right[i];
  return total;
}

function solveNormal(rows, targets) {
  const width = rows[0].length;
  const matrix = Array.from({ length: width }, () => Array(width + 1).fill(0));
  for (let i = 0; i < rows.length; i++) {
    for (let a = 0; a < width; a++) {
      matrix[a][width] += rows[i][a] * targets[i];
      for (let b = 0; b < width; b++) matrix[a][b] += rows[i][a] * rows[i][b];
    }
  }
  for (let col = 0; col < width; col++) {
    let pivot = col;
    for (let row = col + 1; row < width; row++) {
      if (Math.abs(matrix[row][col]) > Math.abs(matrix[pivot][col])) pivot = row;
    }
    const swap = matrix[col];
    matrix[col] = matrix[pivot];
    matrix[pivot] = swap;
    const divisor = matrix[col][col];
    if (Math.abs(divisor) < 1e-12) return null;
    for (let col2 = col; col2 <= width; col2++) matrix[col][col2] /= divisor;
    for (let row = 0; row < width; row++) {
      if (row === col) continue;
      const factor = matrix[row][col];
      for (let col2 = col; col2 <= width; col2++) matrix[row][col2] -= factor * matrix[col][col2];
    }
  }
  return matrix.map((row) => row[width]);
}

function offPeakFlag(day) {
  if (day.offPeakDay != null) return day.offPeakDay ? 1 : 0;
  if (day.ts == null) return 0;
  return isTodOffPeakDay(pacificYmd(day.ts)) ? 1 : 0;
}

/**
 * Daily OLS: kwh = b0 + bH * HDD + bC * CDD + bW * offPeakDay.
 * // adderall: fixed 65F balance point; upgrade path is a grid search over 55-70F by r2.
 */
export function weatherModel(days) {
  const usable = (days || []).filter((day) => finite(day.kwh) != null && finite(day.tempF) != null);
  if (usable.length < 60) return null;
  const includeHeating = usable.some((day) => day.tempF < 65);
  const includeCooling = usable.some((day) => day.tempF > 65);
  const rows = [];
  const targets = [];
  for (const day of usable) {
    const temp = finite(day.tempF);
    const cols = [1];
    if (includeHeating) cols.push(Math.max(0, 65 - temp));
    if (includeCooling) cols.push(Math.max(0, temp - 65));
    cols.push(offPeakFlag(day));
    rows.push(cols);
    targets.push(finite(day.kwh));
  }
  const solved = solveNormal(rows, targets);
  if (!solved) return null;
  let index = 1;
  const b0 = solved[0];
  const bH = includeHeating ? solved[index++] : 0;
  const bC = includeCooling ? solved[index++] : 0;
  const bW = solved[index];
  const coeffs = [b0];
  if (includeHeating) coeffs.push(bH);
  if (includeCooling) coeffs.push(bC);
  coeffs.push(bW);
  const predict = (day) => {
    const temp = finite(day.tempF);
    if (temp == null) return null;
    const cols = [1];
    if (includeHeating) cols.push(Math.max(0, 65 - temp));
    if (includeCooling) cols.push(Math.max(0, temp - 65));
    cols.push(offPeakFlag(day));
    return dot(coeffs, cols);
  };
  const center = mean(targets);
  let ssRes = 0;
  let ssTot = 0;
  for (let i = 0; i < targets.length; i++) {
    const predicted = dot(coeffs, rows[i]);
    ssRes += (targets[i] - predicted) ** 2;
    ssTot += (targets[i] - center) ** 2;
  }
  const r2 = ssTot === 0 ? 1 : 1 - ssRes / ssTot;
  const residualSd = Math.sqrt(ssRes / Math.max(1, targets.length - rows[0].length));
  return { b0, bH, bC, bW, r2, residualSd, n: targets.length, predict };
}

/** Days, weather, rate, and usage bars. They sum to amount1 - amount0. */
export function billExplainer({ amount0, amount1, kwh0, kwh1, days0, days1, pred0, pred1 }) {
  const r0 = kwh0 ? amount0 / kwh0 : 0;
  const r1 = kwh1 ? amount1 / kwh1 : 0;
  const days = days0 ? (days1 - days0) * (kwh0 / days0) * r0 : 0;
  const weather = days1 ? (pred1 / days1 - pred0 / days0) * days1 * r0 : 0;
  const rate = (r1 - r0) * kwh1;
  const usage = amount1 - amount0 - days - weather - rate;
  return { days, weather, rate, usage };
}

/** Fit the earliest baseline and score only the later days. */
export function counterfactual(days) {
  const usable = (days || []).filter((day) => finite(day.kwh) != null && finite(day.tempF) != null);
  const baselineCount = Math.min(365, usable.length - 30);
  if (baselineCount < 300) return null;
  const later = usable.slice(baselineCount);
  if (later.length < 30) return null;
  const model = weatherModel(usable.slice(0, baselineCount));
  if (!model) return null;
  let gap = 0;
  const rows = later.map((day) => {
    const predicted = model.predict(day);
    const actual = finite(day.kwh);
    gap += actual - predicted;
    return { ts: day.ts, actual, predicted, gap };
  });
  return { model, rows };
}

/**
 * // adderall: rolling-median step detector; upgrade path is binary segmentation.
 */
export function baseloadSteps(values) {
  const series = (values || []).map(finite);
  const flags = [];
  for (let index = 14; index + 14 <= series.length; index++) {
    const before = series.slice(index - 14, index);
    const after = series.slice(index, index + 14);
    if (before.some((value) => value == null) || after.some((value) => value == null)) continue;
    const delta = median(after) - median(before);
    const meanDelta = mean(after) - mean(before);
    const threshold = Math.max(0.05, 3 * mad(before));
    if (Math.abs(delta) > threshold) flags.push({ index, delta, meanDelta });
  }
  flags.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta) || Math.abs(b.meanDelta) - Math.abs(a.meanDelta));
  const kept = [];
  for (const flag of flags) {
    if (kept.some((row) => Math.abs(row.index - flag.index) < 30)) continue;
    kept.push(flag);
  }
  return kept.sort((a, b) => a.index - b.index);
}

/** Weekday local TOD cost by start hour. Hours past midnight use the next hour's period. */
export function shiftCostByStartHour({
  kw,
  hours,
  runsPerMonth,
  rates,
  basicRate,
  ymd = "2026-01-07",
} = {}) {
  const rows = [];
  for (let startHour = 0; startHour < 24; startHour++) {
    let energyCost = 0;
    let left = hours;
    let cursor = startHour;
    while (left > 1e-9) {
      const slice = Math.min(1, left);
      const day = addDays(ymd, Math.floor(cursor / 24));
      const period = todPeriodForPacific(day, cursor % 24);
      energyCost += kw * slice * (finite(rates?.[period]) || 0);
      left -= slice;
      cursor += 1;
    }
    rows.push({
      startHour,
      tod: energyCost * runsPerMonth,
      basic: kw * hours * (finite(basicRate) || 0) * runsPerMonth,
    });
  }
  return rows;
}

/** Angle is Pacific hour. Radius is the day index from the window start. */
export function spiralCells(samples, windowStartTs) {
  const startYmd = pacificYmd(windowStartTs);
  return (samples || []).map((sample) => {
    const { ymd, hour } = pacificParts(sample.ts);
    return {
      angle: hour,
      radius: dayIndexBetween(startYmd, ymd),
      kwh: finite(sample.kwh),
      ts: sample.ts,
    };
  });
}

function daypartName(hour) {
  if (hour <= 5) return "Overnight";
  if (hour <= 11) return "Morning";
  if (hour <= 16) return "Afternoon";
  return "Evening";
}

/** themeRiver rows `[ymd, kWh, name]`. */
export function daypartDays(samples) {
  const totals = new Map();
  for (const sample of samples || []) {
    const kwh = finite(sample.kwh);
    if (kwh == null || sample.ts == null) continue;
    const { ymd, hour } = pacificParts(sample.ts);
    const name = daypartName(hour);
    const key = `${ymd}|${name}`;
    totals.set(key, { ymd, name, kwh: (totals.get(key)?.kwh || 0) + kwh });
  }
  const order = ["Overnight", "Morning", "Afternoon", "Evening"];
  return [...totals.values()]
    .sort((a, b) => a.ymd.localeCompare(b.ymd) || order.indexOf(a.name) - order.indexOf(b.name))
    .map((row) => [row.ymd, row.kwh, row.name]);
}

export function anomalyDays(days, model) {
  const rows = [];
  for (const day of days || []) {
    if (finite(day.tempF) == null || finite(day.kwh) == null || !model?.predict) continue;
    const predicted = model.predict(day);
    if (predicted == null) continue;
    const residual = finite(day.kwh) - predicted;
    const scale = finite(model.residualSd);
    const z = scale ? residual / scale : 0;
    rows.push({ ...day, predicted, residual, z, absZ: Math.abs(z) });
  }
  return rows.sort((a, b) => b.absZ - a.absZ).slice(0, 10);
}

/** Dollars per degree-day from model slopes and trailing portal cents per kWh. */
export function degreePrice(model, centsPerKwhValue) {
  const dollars = (finite(centsPerKwhValue) || 0) / 100;
  return {
    heating: (finite(model?.bH) || 0) * dollars,
    cooling: (finite(model?.bC) || 0) * dollars,
  };
}

function weekOfYear(ymd) {
  const [year, month, day] = ymd.split("-").map(Number);
  const start = Date.UTC(year, 0, 1);
  const current = Date.UTC(year, month - 1, day);
  return Math.floor((current - start) / (7 * 86400000));
}

function forecastTemperature(ts, history) {
  const ymd = pacificYmd(ts);
  const year = Number(ymd.slice(0, 4));
  const week = weekOfYear(ymd);
  const prior = (history || []).filter((day) => {
    if (day.ts == null || finite(day.tempF) == null) return false;
    const dayYmd = pacificYmd(day.ts);
    return Number(dayYmd.slice(0, 4)) < year && weekOfYear(dayYmd) === week;
  });
  if (prior.length) return mean(prior.map((day) => finite(day.tempF)));
  const trailing = (history || []).filter((day) => finite(day.tempF) != null).slice(-14);
  return trailing.length ? mean(trailing.map((day) => finite(day.tempF))) : null;
}

/**
 * 80% fan after published data. Half-width is 1.2816 * residualSd * sqrt(lead days).
 * // adderall: climatology stand-in for a weather forecast; upgrade path is a forecast entity.
 */
export function forecastCone({ model, history, publishedEnd, cycleEnd } = {}) {
  if (!model || publishedEnd == null || cycleEnd == null || cycleEnd <= publishedEnd) return [];
  const points = [];
  for (let lead = 1; ; lead++) {
    const ts = publishedEnd + lead * 86400;
    if (ts > cycleEnd || ts <= publishedEnd) break;
    const tempF = forecastTemperature(ts, history);
    const ymd = pacificYmd(ts);
    const predicted = model.predict
      ? model.predict({ ts, tempF, offPeakDay: isTodOffPeakDay(ymd) ? 1 : 0 })
      : null;
    const half = 1.2816 * (finite(model.residualSd) || 0) * Math.sqrt(lead);
    const center = predicted == null ? 0 : predicted;
    points.push({ ts, tempF, predicted: center, low: center - half, high: center + half, lead });
  }
  return points;
}

function hourLabel(hour) {
  const h = ((hour % 24) + 24) % 24;
  const suffix = h >= 12 ? "PM" : "AM";
  const clock = h % 12 === 0 ? 12 : h % 12;
  return `${clock} ${suffix}`;
}

export function yesterdayHeadline({ kwh, avg7, complete = false } = {}) {
  const value = finite(kwh);
  const baseline = finite(avg7);
  if (!complete || value == null || baseline == null || baseline <= 0) return null;
  const delta = ((value - baseline) / baseline) * 100;
  const comparison =
    Math.abs(delta) <= 5
      ? "about the same as your usual day"
      : `${Math.round(Math.abs(delta))}% ${delta > 0 ? "more" : "less"} than your usual day`;
  return {
    text: `Yesterday you used ${value.toFixed(1)} kWh, ${comparison}.`,
    tone: Math.abs(delta) <= 5 ? "neutral" : delta > 0 ? "warn" : "good",
  };
}

export function peakHourHeadline(weekdayMeans) {
  const values = weekdayMeans || [];
  let peak = -1;
  let hour = -1;
  values.forEach((value, index) => {
    const n = finite(value);
    if (n != null && n > peak) {
      peak = n;
      hour = index;
    }
  });
  if (hour < 0) return null;
  return { text: `On weekdays your usage peaks around ${hourLabel(hour)}.`, tone: "neutral" };
}

export function cycleRaceHeadline({ openKwh, lastKwhSameDay, day } = {}) {
  const current = finite(openKwh);
  const previous = finite(lastKwhSameDay);
  if (current == null || previous == null || previous <= 0 || !Number.isInteger(day) || day < 1) return null;
  const delta = ((current - previous) / previous) * 100;
  if (Math.abs(delta) <= 5) {
    return { text: `Your energy use is about even with the last statement at day ${day}.`, tone: "neutral" };
  }
  return {
    text: `Your energy use is ${Math.round(Math.abs(delta))}% ${delta > 0 ? "ahead of" : "behind"} the last statement at day ${day}.`,
    tone: delta > 0 ? "warn" : "good",
  };
}

export function baseloadHeadline({ floorKwh, centsPerKwh } = {}) {
  const floor = finite(floorKwh);
  const cents = finite(centsPerKwh);
  if (floor == null || cents == null || floor < 0 || cents <= 0) return null;
  const monthly = Math.round(floor * 24 * 30 * (cents / 100));
  return {
    text: `About ${floor.toFixed(1)} kWh runs every hour, even overnight. That is roughly $${monthly} a month at PGE's estimated rate.`,
    tone: "neutral",
  };
}

export function weatherHeadline({ colderCents, hotterCents } = {}) {
  const cold = finite(colderCents);
  const hot = finite(hotterCents);
  if (cold == null || hot == null) return null;
  return {
    text: `Hot days cost you more than cold ones: about ${Math.round(hot)}¢ per extra degree versus ${Math.round(cold)}¢.`,
    tone: "neutral",
  };
}

export function paretoHeadline(rows) {
  const share = finite(rows?.share ?? rows);
  const count = Number(rows?.count ?? 5);
  if (share == null) return null;
  return {
    text: `Your ${count} most expensive hours make up ${Math.round(share)}% of the estimated cost.`,
    tone: "neutral",
  };
}

export function billChangeHeadline(bars) {
  const delta = finite(bars?.delta);
  if (delta == null || delta === 0) return null;
  const driver = bars?.driver || "usage";
  const phrase =
    driver === "days"
      ? "a longer bill period"
      : driver === "weather"
        ? "the weather"
        : driver === "rate"
          ? "rate changes"
          : delta < 0
            ? "using less energy"
            : "using more energy";
  const verb = delta > 0 ? "rose" : "fell";
  return {
    text: `This bill ${verb} $${Math.abs(Math.round(delta))}, mostly from ${phrase}.`,
    tone: delta > 0 ? "warn" : "good",
  };
}

export function periodHeadline({ onPeakShare } = {}) {
  const share = finite(onPeakShare);
  if (share == null) return null;
  return {
    text: `About ${Math.round(share)}% of your imported energy lands in on-peak hours.`,
    tone: "neutral",
  };
}

export function storySummary({ yesterday, cycle, estimate } = {}) {
  const rows = [yesterdayHeadline(yesterday), cycleRaceHeadline(cycle)].filter(Boolean);
  const low = finite(estimate?.low);
  const high = finite(estimate?.high);
  if (low != null && high != null && low >= 0 && high >= low) {
    rows.push({
      text: `PGE estimates your next bill between $${Math.round(low)} and $${Math.round(high)}.`,
      tone: "neutral",
    });
  }
  return rows;
}
