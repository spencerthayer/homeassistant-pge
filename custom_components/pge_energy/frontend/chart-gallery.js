/**
 * Mounts /pge gallery charts from recorder series the panel already fetches.
 * Windows end at publishedDataEnd and do not follow the Usage range chip.
 */

import {
  createBoxPlot,
  createGalleryChart,
  createHourWeekdayHeatmap,
  createParallel,
  createPolarBar,
  createRidgeline,
  createSankey,
  createThemeRiver,
  createTreemap,
  createWaterfall,
} from "./charts.js?v=0.12.1";
import {
  estimatePlanCostSeries,
  fetchStatisticSeries,
  pacificParts,
  pacificYmd,
  publishedDataEnd,
  TOD_PERIOD_LABELS,
  todPeriodForPacific,
  isTodOffPeakDay,
} from "./data.js?v=0.12.1";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const HOURS = Array.from({ length: 24 }, (_, hour) => String(hour).padStart(2, "0"));

async function fetchRole(panel, role, { start, end, period, field = "values" }) {
  const statisticId = panel._account?.statistic_ids?.[role];
  if (!statisticId || !panel._hass) return { xs: [], values: [] };
  const series = await fetchStatisticSeries(panel._hass, statisticId, {
    start,
    end,
    period,
    maxPoints: Infinity,
  });
  const values = field === "means" ? series.means : series.values;
  return { xs: series.xs || [], values: values || [] };
}

function joinSamples(parts) {
  const map = new Map();
  for (const part of parts) {
    for (let i = 0; i < part.xs.length; i++) {
      const ts = part.xs[i];
      let row = map.get(ts);
      if (!row) {
        row = { ts, kwh: null, returned: null, cost: null, compensation: null, tempF: null };
        map.set(ts, row);
      }
      const value = part.values[i];
      row[part.key] = value == null || !Number.isFinite(Number(value)) ? null : Number(value);
    }
  }
  return [...map.values()].sort((a, b) => a.ts - b.ts);
}

function hoursOfDay(samples, ymd) {
  const hours = Array(24).fill(null);
  for (const sample of samples) {
    if (pacificYmd(sample.ts) !== ymd || sample.kwh == null) continue;
    hours[pacificParts(sample.ts).hour] = sample.kwh;
  }
  return hours;
}

function galleryStamp(panel) {
  return {
    entryId: panel._activeEntryId ?? null,
    gen: panel._galleryRenderGen ?? 0,
  };
}

function galleryStale(panel, stamp) {
  if (!stamp) return false;
  return (panel._activeEntryId ?? null) !== stamp.entryId || (panel._galleryRenderGen ?? 0) !== stamp.gen;
}

async function mountHost(panel, id, factory, stamp) {
  if (galleryStale(panel, stamp)) return;
  const host = panel.shadowRoot?.getElementById(id);
  const figure = host?.closest("figure");
  if (!host) return;
  panel._disposeHostCharts(host);
  if (figure) figure.hidden = false;
  const chart = await factory(host);
  if (galleryStale(panel, stamp)) {
    try {
      chart?.destroy?.();
    } catch (_err) {
      /* account changed while this chart was initializing */
    }
    return;
  }
  if (!chart) {
    if (figure) figure.hidden = true;
    return;
  }
  panel._charts.push(chart);
}

/**
 * @param {object} panel
 * @param {object} fns load-shape functions from chart-series.js
 */
export async function renderLoadShape(panel, fns) {
  const stamp = galleryStamp(panel);
  const mount = (id, factory) => mountHost(panel, id, factory, stamp);
  if (!panel._account || !panel.shadowRoot?.getElementById("chart-typical-day")) return;
  const end = publishedDataEnd();
  const start28 = new Date(end.getTime() - 28 * 86400000);
  const start12 = new Date(end.getTime() - 370 * 86400000);
  const start5 = new Date(end.getTime() - 5 * 365 * 86400000);

  const [kwh28, cost28, temp28, kwh12, kwhDay, tempDay] = await Promise.all([
    fetchRole(panel, "consumption", { start: start28, end, period: "hour" }),
    fetchRole(panel, "cost", { start: start28, end, period: "hour" }),
    fetchRole(panel, "temperature", { start: start28, end, period: "hour", field: "means" }),
    fetchRole(panel, "consumption", { start: start12, end, period: "hour" }),
    fetchRole(panel, "consumption", { start: start5, end, period: "day" }),
    fetchRole(panel, "temperature", { start: start5, end, period: "day", field: "means" }),
  ]);
  if (galleryStale(panel, stamp)) return;
  const hourly = joinSamples([
    { key: "kwh", ...kwh28 },
    { key: "cost", ...cost28 },
    { key: "tempF", ...temp28 },
  ]);
  const hourlyYear = joinSamples([{ key: "kwh", ...kwh12 }]);
  const daily = joinSamples([
    { key: "kwh", ...kwhDay },
    { key: "tempF", ...tempDay },
  ]);

  const profiles = fns.typicalDayProfiles(hourly);
  await mount( "chart-typical-day", (host) =>
    createGalleryChart(host, {
      categories: HOURS,
      yName: "kWh",
      series: [
        { name: "Weekday", values: profiles.weekday },
        { name: "Weekend", values: profiles.weekend },
      ],
    }),
  );

  const matrix = fns.hourWeekdayMatrix(hourly);
  await mount( "chart-hour-weekday", (host) =>
    createHourWeekdayHeatmap(host, { labels: matrix.labels, values: matrix.values }),
  );

  const ridges = fns.monthRidges(hourlyYear).filter((row) => row.hours.some((value) => value != null));
  await mount( "chart-ridgelines", (host) =>
    createRidgeline(host, {
      ridgeGap: 1,
      series: ridges.map((row) => ({ name: row.key, values: row.hours })),
    }),
  );

  await mount( "chart-polar", (host) => createPolarBar(host, { values: profiles.weekday }));

  const dailyKwh = daily.map((row) => row.kwh).filter((value) => value != null);
  const histogram = fns.histogramBins(dailyKwh);
  await mount( "chart-histogram", (host) =>
    createGalleryChart(host, {
      categories: histogram.labels,
      yName: "Days",
      series: [{ name: "Days", values: histogram.counts, type: "bar" }],
    }),
  );

  const byYear = fns.monthlyByYear(daily);
  await mount( "chart-yoy", (host) =>
    createGalleryChart(host, {
      categories: MONTHS,
      yName: "kWh",
      series: byYear.years.map((year, index) => ({ name: year, values: byYear.series[index] })),
    }),
  );

  await mount( "chart-cycle-race", async (host) => {
    const bill = panel._billBounds?.();
    if (!bill) return null;
    const durationMs = bill.end.getTime() - bill.start.getTime();
    const prevStart = new Date(bill.start.getTime() - durationMs);
    const cycleKwh = await fetchRole(panel, "consumption", { start: prevStart, end, period: "hour" });
    const cycleSamples = joinSamples([{ key: "kwh", ...cycleKwh }]);
    const currentStart = Math.floor(bill.start.getTime() / 1000);
    const previousStart = Math.floor(prevStart.getTime() / 1000);
    const current = fns.cycleCumulative(
      cycleSamples.filter((row) => row.ts >= currentStart),
      currentStart,
    );
    const previous = fns.cycleCumulative(
      cycleSamples.filter((row) => row.ts >= previousStart && row.ts < currentStart),
      previousStart,
    );
    const length = Math.max(current.dayIndex.length, previous.dayIndex.length);
    const categories = Array.from({ length }, (_, index) => String(index + 1));
    const align = (race) => categories.map((_, index) => race.cumulative[race.dayIndex.indexOf(index)] ?? null);
    return createGalleryChart(host, {
      categories,
      yName: "kWh",
      series: [
        { name: "This cycle", values: align(current) },
        { name: "Previous cycle", values: align(previous) },
      ],
    });
  });

  const floor = fns.baseloadFloor(profiles.weekday);
  await mount( "chart-baseload", (host) =>
    createGalleryChart(host, {
      categories: HOURS,
      yName: "kWh",
      markLines: floor == null ? [] : [{ y: floor, name: "Hours 0-5 minimum" }],
      series: [{ name: "Weekday mean", values: profiles.weekday }],
    }),
  );

  const band = fns.spreadBand(dailyKwh);
  await mount( "chart-spread", (host) =>
    createGalleryChart(host, {
      categories: daily.map((row) => row.ts),
      yName: "kWh",
      markLines: band
        ? [
            { y: band.mean, name: "Mean" },
            { y: band.low, name: "Mean - 2 sd" },
            { y: band.high, name: "Mean + 2 sd" },
          ]
        : [],
      series: [{ name: "Daily kWh", values: daily.map((row) => row.kwh) }],
    }),
  );

  const weekKeys = fns.publishedWeekDays(new Date());
  await mount( "chart-published-week", (host) =>
    createGalleryChart(host, {
      categories: HOURS,
      yName: "kWh",
      series: weekKeys.map((ymd) => ({ name: ymd.slice(5), values: hoursOfDay(hourly, ymd) })),
    }),
  );

  const prints = fns.dayFingerprints(hourly);
  await mount( "chart-fingerprint", (host) =>
    createParallel(host, {
      dimensions: ["kWh", "Peak hour", "Mean °F", "On-peak share", "Portal ¢/kWh"],
      rows: prints.map((row) => [row.kwh, row.peakHour, row.tempF, row.onPeakShare, row.centsPerKwh]),
    }),
  );
}

function catalogBundle(panel) {
  const tod = panel._account?.tod || {};
  const catalogs = tod.catalogs || {};
  return {
    todCatalog: catalogs.tod || [],
    basicCatalog: catalogs.basic || [],
    overrideRates: tod.override_rates || null,
  };
}

export async function renderTodCharts(panel, fns) {
  const stamp = galleryStamp(panel);
  const mount = (id, factory) => mountHost(panel, id, factory, stamp);
  if (!panel.shadowRoot?.getElementById("chart-tod-stacked")) return;
  const end = publishedDataEnd();
  const start28 = new Date(end.getTime() - 28 * 86400000);
  const start12 = new Date(end.getTime() - 370 * 86400000);
  const [kwh28, kwh12] = await Promise.all([
    fetchRole(panel, "consumption", { start: start28, end, period: "hour" }),
    fetchRole(panel, "consumption", { start: start12, end, period: "hour" }),
  ]);
  if (galleryStale(panel, stamp)) return;
  const recent = joinSamples([{ key: "kwh", ...kwh28 }]);
  const year = joinSamples([{ key: "kwh", ...kwh12 }]);
  const { todCatalog, basicCatalog, overrideRates } = catalogBundle(panel);

  const stacked = { off_peak: [], mid_peak: [], on_peak: [], categories: [] };
  for (const sample of recent) {
    if (sample.kwh == null) continue;
    const { ymd, hour } = pacificParts(sample.ts);
    const period = todPeriodForPacific(ymd, hour);
    stacked.categories.push(sample.ts);
    for (const key of ["off_peak", "mid_peak", "on_peak"]) {
      stacked[key].push(period === key ? sample.kwh : 0);
    }
  }
  await mount( "chart-tod-stacked", (host) =>
    createGalleryChart(host, {
      categories: stacked.categories,
      yName: "kWh",
      series: ["off_peak", "mid_peak", "on_peak"].map((key) => ({
        name: TOD_PERIOD_LABELS[key],
        values: stacked[key],
        type: "line",
        area: true,
        stack: "tod",
      })),
    }),
  );

  const mix = fns.periodMixByMonth(year);
  await mount( "chart-period-mix", (host) =>
    createGalleryChart(host, {
      categories: mix.map((row) => row.month),
      yName: "Share",
      series: ["off_peak", "mid_peak", "on_peak"].map((key) => ({
        name: TOD_PERIOD_LABELS[key],
        values: mix.map((row) => row[key]),
        type: "bar",
        stack: "mix",
      })),
    }),
  );

  const boxRows = ["off_peak", "mid_peak", "on_peak"]
    .map((key) => {
      const values = [];
      for (const sample of recent) {
        if (sample.kwh == null) continue;
        const { ymd, hour } = pacificParts(sample.ts);
        if (todPeriodForPacific(ymd, hour) === key) values.push(sample.kwh);
      }
      const box = fns.periodBox(values);
      return box ? { label: TOD_PERIOD_LABELS[key], box: [box.min, box.q1, box.median, box.q3, box.max] } : null;
    })
    .filter(Boolean);
  await mount( "chart-period-box", (host) =>
    createBoxPlot(host, {
      categories: boxRows.map((row) => row.label),
      boxes: boxRows.map((row) => row.box),
    }),
  );

  const matrix = fns.hourWeekdayMatrix(recent);
  const ribbonStart = Math.floor(end.getTime() / 1000);
  const ribbon = fns.forwardRibbon({ startTs: ribbonStart, means: matrix.values });
  await mount( "chart-forward-ribbon", (host) =>
    createGalleryChart(host, {
      categories: ribbon.map((row) => row.label),
      yName: "kWh",
      series: [
        {
          name: "Historical mean",
          values: ribbon.map((row) => row.kwh),
          type: "bar",
        },
      ],
    }),
  );

  const estimate28 = estimatePlanCostSeries({
    hourlyKwh: kwh28,
    todCatalog,
    basicCatalog,
    overrideRates,
    start: start28,
    end,
  });
  const priced28 = estimate28?.coverage?.complete === true;
  if (!priced28) {
    const host = panel.shadowRoot.getElementById("chart-money-pareto");
    const figure = host?.closest("figure");
    if (figure) figure.hidden = true;
  } else {
    const paretoSamples = [];
    for (let i = 0; i < (estimate28.xs || []).length; i++) {
      const dollars = estimate28.todValues[i];
      if (dollars == null || !Number.isFinite(Number(dollars))) continue;
      paretoSamples.push({ ts: estimate28.xs[i], dollars: Number(dollars) });
    }
    const pareto = fns.moneyHourPareto(paretoSamples);
    await mount( "chart-money-pareto", (host) =>
      createGalleryChart(host, {
        categories: pareto.map((row) => String(row.hour).padStart(2, "0")),
        xName: "Dollars",
        horizontal: true,
        series: [{ name: "Local TOD imported-energy estimate", values: pareto.map((row) => row.dollars), type: "bar" }],
      }),
    );
  }

  if (galleryStale(panel, stamp)) return;
  const estimateYear = estimatePlanCostSeries({
    hourlyKwh: kwh12,
    todCatalog,
    basicCatalog,
    overrideRates,
    start: start12,
    end,
  });
  if (estimateYear?.coverage?.complete !== true) {
    for (const id of ["chart-tod-delta", "chart-sankey"]) {
      const host = panel.shadowRoot.getElementById(id);
      const figure = host?.closest("figure");
      if (figure) figure.hidden = true;
    }
    return;
  }
  const monthly = fns.todMinusBasicByMonth(
    (estimateYear.xs || []).map((ts, index) => ({
      ts,
      tod: estimateYear.todValues[index],
      basic: estimateYear.basicValues[index],
    })),
  );
  await mount( "chart-tod-delta", (host) =>
    createGalleryChart(host, {
      categories: monthly.map((row) => row.month),
      yName: "Dollars, positive means the local TOD estimate is lower",
      series: [{ name: "Local TOD minus local Basic", values: monthly.map((row) => row.delta), type: "bar" }],
    }),
  );
  const dollars = { off_peak: 0, mid_peak: 0, on_peak: 0 };
  const kwhByPeriod = { off_peak: 0, mid_peak: 0, on_peak: 0 };
  const kwhMap = new Map((kwh12.xs || []).map((ts, index) => [ts, kwh12.values[index]]));
  for (let i = 0; i < (estimateYear.xs || []).length; i++) {
    const { ymd, hour } = pacificParts(estimateYear.xs[i]);
    const period = todPeriodForPacific(ymd, hour);
    const kwh = kwhMap.get(estimateYear.xs[i]);
    if (Number.isFinite(Number(kwh))) kwhByPeriod[period] += Number(kwh);
    const dollarsValue = estimateYear.todValues[i];
    if (Number.isFinite(Number(dollarsValue))) dollars[period] += Number(dollarsValue);
  }
  const flows = fns.sankeyFlows(
    ["off_peak", "mid_peak", "on_peak"].map((period) => ({
      period,
      kwh: kwhByPeriod[period],
      dollars: dollars[period],
    })),
  );
  const target = "Local TOD imported-energy estimate";
  await mount( "chart-sankey", (host) =>
    createSankey(host, {
      nodes: [
        ...flows.map((row) => ({
          name: `${TOD_PERIOD_LABELS[row.period]} ${row.kwh.toFixed(0)} kWh`,
        })),
        { name: target },
      ],
      links: flows.map((row) => ({
        source: `${TOD_PERIOD_LABELS[row.period]} ${row.kwh.toFixed(0)} kWh`,
        target,
        value: row.dollars,
      })),
    }),
  );
}

function sparseChanges(series) {
  const rows = [];
  for (let i = 0; i < (series.xs || []).length; i++) {
    const value = series.values?.[i];
    if (value == null || !Number.isFinite(Number(value)) || Number(value) === 0) continue;
    rows.push({ ts: series.xs[i], value: Number(value) });
  }
  return rows;
}

function billBoundsSeconds(panel) {
  const bill = panel._billBounds?.();
  if (!bill) return null;
  return {
    start: Math.floor(bill.start.getTime() / 1000),
    end: Math.floor(bill.end.getTime() / 1000),
  };
}

export async function renderWeatherMoney(panel, fns) {
  const stamp = galleryStamp(panel);
  const mount = (id, factory) => mountHost(panel, id, factory, stamp);
  if (!panel._account) return;
  const end = publishedDataEnd();
  const start5 = new Date(end.getTime() - 5 * 365 * 86400000);
  const startBills = new Date("2019-01-01T00:00:00.000Z");
  const [kwhDay, costDay, tempDay, billAmount, billKwh, costHour, kwhHour, savings, balance, due] =
    await Promise.all([
      fetchRole(panel, "consumption", { start: start5, end, period: "day" }),
      fetchRole(panel, "cost", { start: start5, end, period: "day" }),
      fetchRole(panel, "temperature", { start: start5, end, period: "day", field: "means" }),
      fetchRole(panel, "bill_amount", { start: startBills, end, period: "hour" }),
      fetchRole(panel, "bill_kwh", { start: startBills, end, period: "hour" }),
      fetchRole(panel, "cost", { start: startBills, end, period: "hour" }),
      fetchRole(panel, "consumption", { start: startBills, end, period: "hour" }),
      fetchRole(panel, "ytd_program_savings", { start: start5, end, period: "hour", field: "means" }),
      fetchRole(panel, "account_balance", { start: start5, end, period: "hour", field: "means" }),
      fetchRole(panel, "amount_due", { start: start5, end, period: "hour", field: "means" }),
    ]);
  if (galleryStale(panel, stamp)) return;
  const days = joinSamples([
    { key: "kwh", ...kwhDay },
    { key: "cost", ...costDay },
    { key: "tempF", ...tempDay },
  ]);
  await mount( "chart-degree-days", (host) =>
    createGalleryChart(host, {
      categories: days.map((row) => row.ts),
      yName: "kWh or degree days",
      series: [
        { name: "kWh", values: days.map((row) => row.kwh) },
        {
          name: "Heating degree days",
          values: days.map((row) => fns.degreeDayPoint(row.tempF)?.heating ?? null),
        },
        {
          name: "Cooling degree days",
          values: days.map((row) => fns.degreeDayPoint(row.tempF)?.cooling ?? null),
        },
      ],
    }),
  );
  const bins = fns.tempBins(days);
  await mount( "chart-temp-bins", (host) =>
    createGalleryChart(host, {
      categories: bins.map((row) => row.label),
      yName: "Mean kWh",
      series: [{ name: "Mean kWh", values: bins.map((row) => row.meanKwh), type: "bar" }],
    }),
  );

  if (!panel.shadowRoot?.getElementById("chart-statement-portal")) return;
  const bounds = billBoundsSeconds(panel);
  const amountRows = sparseChanges(billAmount);
  const kwhRows = sparseChanges(billKwh);
  const windows = fns.statementWindows(amountRows, bounds);
  const costSamples = joinSamples([{ key: "cost", ...costHour }]);
  const kwhSamples = joinSamples([{ key: "kwh", ...kwhHour }]);
  const costGaps = fns.statementGap(windows, costSamples);
  const kwhGaps = fns.billVsImported(windows, kwhSamples);
  const labels = windows.map((window) => pacificYmd(new Date(window.end * 1000)));
  const amountByTs = new Map(amountRows.map((row) => [row.ts, row.value]));
  const kwhByTs = new Map(kwhRows.map((row) => [row.ts, row.value]));
  await mount( "chart-statement-portal", (host) =>
    createGalleryChart(host, {
      categories: labels,
      yName: "Dollars",
      series: [
        { name: "Billed amount", values: windows.map((window) => amountByTs.get(window.end) ?? null), type: "bar" },
        { name: "PGE usage estimate", values: costGaps.map((row) => row.total), type: "bar" },
      ],
    }),
  );
  await mount( "chart-bill-imported", (host) =>
    createGalleryChart(host, {
      categories: labels,
      yName: "kWh",
      series: [
        { name: "Billed kWh", values: windows.map((window) => kwhByTs.get(window.end) ?? null), type: "bar" },
        { name: "Imported kWh", values: kwhGaps.map((row) => row.total), type: "bar" },
      ],
    }),
  );
  await mount( "chart-program-savings", (host) =>
    createGalleryChart(host, {
      categories: savings.xs,
      yName: "Dollars",
      series: [{ name: "YTD program savings", values: savings.values }],
    }),
  );
  await mount( "chart-balance-due", (host) =>
    createGalleryChart(host, {
      categories: balance.xs.length ? balance.xs : due.xs,
      yName: "Dollars",
      series: [
        { name: "Account balance", values: balance.values },
        { name: "Amount due", values: due.values },
      ],
    }),
  );

  if (galleryStale(panel, stamp)) return;
  panel._galleryDays = days;
  panel._galleryBillAmount = billAmount;
}

function hideFigure(panel, id, hidden) {
  const host = panel.shadowRoot?.getElementById(id);
  const figure = host?.closest("figure");
  if (figure) figure.hidden = hidden;
}

export async function renderPdfSolar(panel, fns) {
  const stamp = galleryStamp(panel);
  const mount = (id, factory) => mountHost(panel, id, factory, stamp);
  if (!panel._account) return;
  const end = publishedDataEnd();
  const start28 = new Date(end.getTime() - 28 * 86400000);
  const start12 = new Date(end.getTime() - 370 * 86400000);
  const [kwh28, return28, kwh12, return12, cost12, comp12] = await Promise.all([
    fetchRole(panel, "consumption", { start: start28, end, period: "hour" }),
    fetchRole(panel, "return", { start: start28, end, period: "hour" }),
    fetchRole(panel, "consumption", { start: start12, end, period: "hour" }),
    fetchRole(panel, "return", { start: start12, end, period: "hour" }),
    fetchRole(panel, "cost", { start: start12, end, period: "hour" }),
    fetchRole(panel, "compensation", { start: start12, end, period: "hour" }),
  ]);
  if (galleryStale(panel, stamp)) return;
  const recent = joinSamples([
    { key: "kwh", ...kwh28 },
    { key: "returned", ...return28 },
  ]);
  const year = joinSamples([
    { key: "kwh", ...kwh12 },
    { key: "returned", ...return12 },
    { key: "cost", ...cost12 },
    { key: "compensation", ...comp12 },
  ]);
  const showDuck = fns.hasExport(recent) || fns.hasExport(year);
  hideFigure(panel, "chart-duck", !showDuck);
  hideFigure(panel, "chart-duck-months", !showDuck);
  if (showDuck) {
    const duck = fns.duckHourProfiles(recent);
    await mount( "chart-duck", (host) =>
      createGalleryChart(host, {
        categories: HOURS,
        yName: "kWh",
        series: [
          { name: "Import", values: duck.consumption },
          { name: "Export", values: duck.returned },
        ],
      }),
    );
    const months = fns.duckMonthBars(year);
    await mount( "chart-duck-months", (host) =>
      createGalleryChart(host, {
        categories: months.map((row) => row.month),
        yName: "kWh or dollars",
        series: [
          { name: "Import kWh", values: months.map((row) => row.kwh), type: "bar" },
          { name: "Export kWh", values: months.map((row) => row.returned), type: "bar" },
          { name: "PGE usage estimate", values: months.map((row) => row.cost) },
          { name: "Export compensation", values: months.map((row) => row.compensation) },
        ],
      }),
    );
  }

  const slot = panel.shadowRoot?.getElementById("chart-pdf-slot");
  if (!slot) return;
  const ids = panel._account.bill_pdf_statistic_ids || {};
  const fetched = await Promise.all(
    Object.entries(ids).map(async ([key, statisticId]) => {
      if (!statisticId) return [key, { xs: [], values: [] }];
      const series = await fetchStatisticSeries(panel._hass, statisticId, {
        start: new Date("2019-01-01T00:00:00.000Z"),
        end,
        period: "hour",
        maxPoints: Infinity,
      });
      return [key, { xs: series.xs || [], values: series.values || [] }];
    }),
  );
  if (galleryStale(panel, stamp)) return;
  const byTs = new Map();
  let any = false;
  for (const [key, series] of fetched) {
    for (const row of sparseChanges(series)) {
      any = true;
      const statement = byTs.get(row.ts) || { ts: row.ts };
      statement[key] = row.value;
      byTs.set(row.ts, statement);
    }
  }
  if (!any) {
    panel._disposeHostCharts(slot);
    slot.replaceChildren();
    return;
  }
  panel._disposeHostCharts(slot);
  slot.innerHTML = panel._pdfGalleryHtml();
  const statements = [...byTs.values()].sort((a, b) => a.ts - b.ts);
  const anatomy = fns.billAnatomyRows(statements);
  const labels = anatomy.map((row) => pacificYmd(new Date(row.ts * 1000)));
  const familyKeys = ["basic", "energyUse", "delivery", "taxes", "other"];
  const familyLabels = ["Basic", "Energy use", "Delivery", "Taxes", "Other"];
  await mount( "chart-bill-anatomy", (host) =>
    createGalleryChart(host, {
      categories: labels,
      yName: "Dollars",
      series: familyKeys.map((key, index) => ({
        name: familyLabels[index],
        values: anatomy.map((row) => row[key]),
        type: "bar",
        stack: "bill",
      })),
    }),
  );
  const slices = fns.treemapSlices(statements);
  await mount( "chart-treemap", (host) =>
    createTreemap(host, {
      data: slices.map((slice) => ({ name: slice.label, value: slice.value })),
    }),
  );
  const latest = statements[statements.length - 1];
  await mount( "chart-waterfall", (host) =>
    createWaterfall(host, {
      unit: "",
      steps: fns.waterfallSteps(latest).map((step, index, all) => ({
        label: step.label,
        value: step.value,
        total: index === all.length - 1,
      })),
    }),
  );
  await mount( "chart-fixed-variable", (host) =>
    createGalleryChart(host, {
      categories: labels,
      yName: "Dollars",
      series: familyKeys.map((key, index) => ({
        name: familyLabels[index],
        values: anatomy.map((row) => row[key]),
        type: "bar",
        stack: "fixed",
      })),
    }),
  );
  await mount( "chart-line-mix", (host) =>
    createGalleryChart(host, {
      categories: labels,
      yName: "Share",
      series: familyKeys.map((key, index) => ({
        name: familyLabels[index],
        values: statements.map((row) => fns.lineItemShares(row).find((share) => share.key === key)?.share ?? null),
        type: "bar",
        stack: "share",
      })),
    }),
  );
}

const SHIFT_PRESETS = {
  ev: { kw: 7.2, hours: 4, runs: 20 },
  dryer: { kw: 3, hours: 1, runs: 20 },
  dishwasher: { kw: 1.2, hours: 2, runs: 20 },
};

function catalogRateAt(rows, ymd, field) {
  const match = [...(rows || [])].reverse().find((row) => !row.effective_from || row.effective_from <= ymd);
  return finiteNumber(match?.[field]);
}

function finiteNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export async function renderInsights(panel, fns) {
  const stamp = galleryStamp(panel);
  const mount = (id, factory) => mountHost(panel, id, factory, stamp);
  if (!panel._account || !panel.shadowRoot) return;
  const end = publishedDataEnd();
  const start366 = new Date(end.getTime() - 366 * 86400000);
  let sourceDays = panel._galleryDays;
  const hourlyFetches = [
    fetchRole(panel, "consumption", { start: start366, end, period: "hour" }),
    fetchRole(panel, "consumption", { start: new Date("2019-01-01T00:00:00.000Z"), end, period: "hour" }),
  ];
  if (!sourceDays) {
    const start5 = new Date(end.getTime() - 5 * 365 * 86400000);
    hourlyFetches.unshift(
      fetchRole(panel, "consumption", { start: start5, end, period: "day" }),
      fetchRole(panel, "temperature", { start: start5, end, period: "day", field: "means" }),
      fetchRole(panel, "cost", { start: start5, end, period: "day" }),
    );
  }
  const fetched = await Promise.all(hourlyFetches);
  if (galleryStale(panel, stamp)) return;
  if (!sourceDays) {
    sourceDays = joinSamples([
      { key: "kwh", ...fetched[0] },
      { key: "tempF", ...fetched[1] },
      { key: "cost", ...fetched[2] },
    ]);
  }
  const hourSeries = sourceDays === panel._galleryDays ? fetched : fetched.slice(3);
  const days = sourceDays.map((day) => ({
    ...day,
    offPeakDay: isTodOffPeakDay(pacificYmd(day.ts)) ? 1 : 0,
  }));
  const usable = days.filter((day) => day.kwh != null && day.tempF != null);
  const trailing = usable.slice(-365);
  const model = fns.weatherModel(trailing);
  const [kwhHour, kwhAll] = hourSeries;
  const hourly = joinSamples([{ key: "kwh", ...kwhHour }]);
  const allHourly = joinSamples([{ key: "kwh", ...kwhAll }]);

  const modelHosts = [
    "chart-bill-explainer",
    "chart-weather-counterfactual",
    "chart-baseload-history",
    "chart-daypart-stream",
  ];
  let centsValue = null;
  if (!model) {
    for (const id of modelHosts) hideFigure(panel, id, true);
    const kpi = panel.shadowRoot.getElementById("kpi-degree-price");
    if (kpi) kpi.hidden = true;
  } else {
    const counter = fns.counterfactual(usable);
    hideFigure(panel, "chart-weather-counterfactual", !counter);
    if (counter) {
      await mount( "chart-weather-counterfactual", (host) =>
        createGalleryChart(host, {
          categories: counter.rows.map((row) => row.ts),
          yName: "kWh",
          series: [
            { name: "Actual", values: counter.rows.map((row) => row.actual) },
            { name: "Predicted", values: counter.rows.map((row) => row.predicted) },
            { name: "Cumulative gap", values: counter.rows.map((row) => row.gap) },
          ],
        }),
      );
      const figure = panel.shadowRoot.getElementById("chart-weather-counterfactual")?.closest("figure");
      const note = figure?.querySelector("p");
      if (note) note.textContent = `r2 ${counter.model.r2.toFixed(2)}. Fit on an earlier baseline, not the days drawn.`;
    }

    const cents = fns.centsPerKwh(trailing);
    centsValue = cents.length ? cents.reduce((sum, row) => sum + row.cents, 0) / cents.length : null;
    const price = centsValue == null ? null : fns.degreePrice(model, centsValue);
    const kpi = panel.shadowRoot.getElementById("kpi-degree-price");
    if (kpi) {
      kpi.hidden = !price;
      kpi.textContent = price
        ? `A 1 °F colder day: $${price.heating.toFixed(2)}. A 1 °F hotter day: $${price.cooling.toFixed(2)}. PGE usage estimate.`
        : "";
    }

    const billAmount = panel._galleryBillAmount || (await fetchRole(panel, "bill_amount", {
      start: new Date("2019-01-01T00:00:00.000Z"),
      end,
      period: "hour",
    }));
    const ordered = sparseChanges(billAmount).sort((a, b) => a.ts - b.ts);
    const windows = fns.statementWindows(ordered, billBoundsSeconds(panel));
    const stats = windows
      .map((window, index) => {
        const rows = usable.filter((day) => day.ts >= window.start && day.ts < window.end);
        if (!rows.length) return null;
        const amount = ordered[index + 1]?.value ?? null;
        if (amount == null) return null;
        return {
          window,
          days: rows.length,
          kwh: rows.reduce((sum, row) => sum + row.kwh, 0),
          pred: rows.reduce((sum, row) => sum + (model.predict(row) || 0), 0),
          amount,
        };
      })
      .filter(Boolean);
    hideFigure(panel, "chart-bill-explainer", stats.length < 2);
    if (stats.length >= 2) {
      const previous = stats[stats.length - 2];
      const current = stats[stats.length - 1];
      const bars = fns.billExplainer({
        amount0: previous.amount,
        amount1: current.amount,
        kwh0: previous.kwh,
        kwh1: current.kwh,
        days0: previous.days,
        days1: current.days,
        pred0: previous.pred,
        pred1: current.pred,
      });
      const delta = current.amount - previous.amount;
      await mount( "chart-bill-explainer", (host) =>
        createWaterfall(host, {
          steps: [
            { label: "Days", value: bars.days },
            { label: "Weather", value: bars.weather },
            { label: "Rate", value: bars.rate },
            { label: "Usage", value: bars.usage },
            { label: "Change in amount due", value: delta, total: true },
          ],
        }),
      );
    }

    const overnight = [];
    const byDay = new Map();
    for (const sample of allHourly) {
      if (sample.kwh == null) continue;
      const { ymd, hour } = pacificParts(sample.ts);
      if (hour > 5) continue;
      const prior = byDay.get(ymd);
      byDay.set(ymd, prior == null ? sample.kwh : Math.min(prior, sample.kwh));
    }
    for (const ymd of [...byDay.keys()].sort()) overnight.push({ ymd, kwh: byDay.get(ymd) });
    const steps = fns.baseloadSteps(overnight.map((row) => row.kwh));
    const dollarsPerKwh = centsValue == null ? null : centsValue / 100;
    await mount( "chart-baseload-history", (host) =>
      createGalleryChart(host, {
        categories: overnight.map((row) => row.ymd),
        yName: "kWh/h",
        series: [{ name: "Hours 0-5 minimum", values: overnight.map((row) => row.kwh) }],
      }),
    );
    const historyFigure = panel.shadowRoot.getElementById("chart-baseload-history")?.closest("figure");
    const historyNote = historyFigure?.querySelector("p");
    if (historyNote && steps.length) {
      const text = steps
        .map((step) => {
          const kwhSign = step.delta > 0 ? "+" : "";
          const yearlyDollars = dollarsPerKwh == null ? null : step.delta * 24 * 365 * dollarsPerKwh;
          const yearly =
            yearlyDollars == null
              ? ""
              : `, ${yearlyDollars > 0 ? "+" : yearlyDollars < 0 ? "-" : ""}$${Math.abs(yearlyDollars).toFixed(0)}/year`;
          return `${kwhSign}${step.delta.toFixed(2)} kWh/h since ${overnight[step.index]?.ymd || "that day"}${yearly}, PGE usage estimate`;
        })
        .join(". ");
      historyNote.textContent = text;
    }
    await mount( "chart-daypart-stream", (host) =>
      createThemeRiver(host, { data: fns.daypartDays(hourly) }),
    );
  }

  if (galleryStale(panel, stamp)) return;
  const ymd = pacificYmd(end);
  const { todCatalog, basicCatalog, overrideRates } = catalogBundle(panel);
  let rates = {
    off_peak: catalogRateAt(todCatalog, ymd, "off_peak"),
    mid_peak: catalogRateAt(todCatalog, ymd, "mid_peak"),
    on_peak: catalogRateAt(todCatalog, ymd, "on_peak"),
  };
  let basicRate = catalogRateAt(basicCatalog, ymd, "rate");
  if (
    finiteNumber(overrideRates?.off_peak) > 0 &&
    finiteNumber(overrideRates?.mid_peak) > 0 &&
    finiteNumber(overrideRates?.on_peak) > 0 &&
    finiteNumber(overrideRates?.basic_service) > 0
  ) {
    rates = {
      off_peak: overrideRates.off_peak,
      mid_peak: overrideRates.mid_peak,
      on_peak: overrideRates.on_peak,
    };
    basicRate = overrideRates.basic_service;
  }
  const shiftFigure = panel.shadowRoot.getElementById("chart-shift-sim")?.closest("figure");
  const covered = rates.off_peak != null && rates.mid_peak != null && rates.on_peak != null && basicRate != null;
  if (shiftFigure) shiftFigure.hidden = !covered;
  if (covered) {
    const drawShift = async () => {
      const kw = finiteNumber(panel.shadowRoot.getElementById("chart-shift-kw")?.value);
      const hours = finiteNumber(panel.shadowRoot.getElementById("chart-shift-hours")?.value);
      const runs = finiteNumber(panel.shadowRoot.getElementById("chart-shift-runs")?.value);
      if (kw == null || hours == null || runs == null) return;
      const rows = fns.shiftCostByStartHour({ kw, hours, runsPerMonth: runs, rates, basicRate });
      await mount( "chart-shift-sim", (host) =>
        createGalleryChart(host, {
          categories: rows.map((row) => String(row.startHour).padStart(2, "0")),
          yName: "Dollars per month",
          markLines: [{ y: rows[0]?.basic, name: "Local Basic estimate" }],
          series: [{ name: "Local TOD imported-energy estimate", values: rows.map((row) => row.tod), type: "bar" }],
        }),
      );
    };
    const preset = panel.shadowRoot.getElementById("chart-shift-preset");
    const applyPreset = () => {
      const chosen = SHIFT_PRESETS[preset?.value];
      if (!chosen) return;
      panel.shadowRoot.getElementById("chart-shift-kw").value = String(chosen.kw);
      panel.shadowRoot.getElementById("chart-shift-hours").value = String(chosen.hours);
      panel.shadowRoot.getElementById("chart-shift-runs").value = String(chosen.runs);
    };
    if (preset) {
      preset.onchange = () => {
        applyPreset();
        void drawShift();
      };
    }
    for (const id of ["chart-shift-kw", "chart-shift-hours", "chart-shift-runs"]) {
      const input = panel.shadowRoot.getElementById(id);
      if (input) {
        input.oninput = () => {
          if (preset) preset.value = "custom";
          void drawShift();
        };
      }
    }
    void drawShift();
  }
}
