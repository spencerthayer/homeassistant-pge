/**
 * Weather model and insight aggregations.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { pacificMidnightUtc } from "../../custom_components/pge_energy/frontend/data.js";
import {
  anomalyDays,
  baseloadSteps,
  billExplainer,
  counterfactual,
  daypartDays,
  degreePrice,
  forecastCone,
  shiftCostByStartHour,
  spiralCells,
  weatherModel,
} from "../../custom_components/pge_energy/frontend/chart-series.js";

function atHour(ymd, hour) {
  return Math.floor(pacificMidnightUtc(ymd).getTime() / 1000) + hour * 3600;
}

function syntheticDay(index, { tempF, offPeakDay = 0, extra = 0 }) {
  const hdd = Math.max(0, 65 - tempF);
  const cdd = Math.max(0, tempF - 65);
  return {
    ts: index * 86400,
    tempF,
    offPeakDay,
    kwh: 10 + 0.5 * hdd + 0.3 * cdd + 2 * offPeakDay + extra,
  };
}

describe("insight series", () => {
  it("weatherModel recovers a known linear day", () => {
    const days = [];
    for (let i = 0; i < 90; i++) {
      const tempF = 40 + (i % 50);
      days.push(syntheticDay(i, { tempF, offPeakDay: i % 7 === 0 ? 1 : 0 }));
    }
    const model = weatherModel(days);
    assert.ok(Math.abs(model.b0 - 10) < 1e-6);
    assert.ok(Math.abs(model.bH - 0.5) < 1e-6);
    assert.ok(Math.abs(model.bC - 0.3) < 1e-6);
    assert.ok(Math.abs(model.bW - 2) < 1e-6);
    assert.ok(Math.abs(model.r2 - 1) < 1e-9);
  });

  it("weatherModel returns null below 60 days and drops cooling when no day exceeds 65 F", () => {
    const cool = [];
    for (let i = 0; i < 59; i++) cool.push(syntheticDay(i, { tempF: 50, offPeakDay: i % 2 }));
    assert.equal(weatherModel(cool), null);
    const varied = [];
    for (let i = 0; i < 80; i++) {
      varied.push(syntheticDay(i, { tempF: 40 + (i % 20), offPeakDay: i % 3 === 0 ? 1 : 0 }));
    }
    const model = weatherModel(varied);
    assert.equal(model.bC, 0);
    assert.ok(Math.abs(model.bH - 0.5) < 1e-6);
  });

  it("billExplainer bars sum to the change in amount", () => {
    const bars = billExplainer({
      amount0: 100,
      amount1: 130,
      kwh0: 10,
      kwh1: 12,
      days0: 30,
      days1: 31,
      pred0: 10,
      pred1: 11,
    });
    const sum = bars.days + bars.weather + bars.rate + bars.usage;
    assert.ok(Math.abs(sum - (130 - 100)) < 1e-9);
  });

  it("counterfactual fits a baseline it does not plot", () => {
    const days = [];
    for (let i = 0; i < 395; i++) {
      const tempF = 40 + (i % 40);
      days.push(syntheticDay(i, { tempF, offPeakDay: i % 5 === 0 ? 1 : 0, extra: i >= 365 ? 4 : 0 }));
    }
    assert.equal(counterfactual(days.slice(0, 299)), null);
    assert.equal(counterfactual(days.slice(0, 329)), null);
    const out = counterfactual(days);
    assert.equal(out.rows.length, 30);
    assert.equal(out.rows[0].ts, 365 * 86400);
    assert.ok(out.rows[out.rows.length - 1].gap > 100);
  });

  it("baseloadSteps flags a sustained step and ignores a one-day spike", () => {
    const stepped = [...Array(60).fill(0.3), ...Array(60).fill(0.45)];
    const steps = baseloadSteps(stepped);
    assert.equal(steps.length, 1);
    assert.equal(steps[0].index, 60);
    assert.ok(Math.abs(steps[0].delta - 0.15) < 1e-9);
    const spiked = Array(40).fill(0.3);
    spiked[20] = 5;
    assert.equal(baseloadSteps(spiked).length, 0);
  });

  it("shiftCostByStartHour prices 24 weekday starts and wraps past midnight", () => {
    const rows = shiftCostByStartHour({
      kw: 7.2,
      hours: 4,
      runsPerMonth: 20,
      rates: { off_peak: 0.1, mid_peak: 0.2, on_peak: 0.4 },
      basicRate: 0.15,
    });
    assert.equal(rows.length, 24);
    assert.ok(rows[17].tod > rows[0].tod);
    const wrap = shiftCostByStartHour({
      kw: 1,
      hours: 2,
      runsPerMonth: 1,
      rates: { off_peak: 1, mid_peak: 2, on_peak: 10 },
      basicRate: 1,
    });
    assert.equal(wrap[20].tod, 11);
  });

  it("spiralCells maps the third day at 13:00 to angle 13 and radius 2", () => {
    const start = atHour("2026-01-05", 0);
    const [cell] = spiralCells([{ ts: atHour("2026-01-07", 13), kwh: 1.5 }], start);
    assert.equal(cell.angle, 13);
    assert.equal(cell.radius, 2);
  });

  it("daypartDays buckets hours into overnight, morning, afternoon, and evening", () => {
    const rows = daypartDays([
      { ts: atHour("2026-01-05", 5), kwh: 1 },
      { ts: atHour("2026-01-05", 6), kwh: 2 },
      { ts: atHour("2026-01-05", 12), kwh: 3 },
      { ts: atHour("2026-01-05", 17), kwh: 4 },
    ]);
    const byName = Object.fromEntries(rows.map((row) => [row[2], row[1]]));
    assert.equal(byName.Overnight, 1);
    assert.equal(byName.Morning, 2);
    assert.equal(byName.Afternoon, 3);
    assert.equal(byName.Evening, 4);
    assert.equal(rows[0][0], "2026-01-05");
  });

  it("anomalyDays returns at most 10 days and skips a day without temperature", () => {
    const model = {
      residualSd: 1,
      predict(day) {
        return 10;
      },
    };
    const days = [];
    for (let i = 0; i < 12; i++) days.push({ ts: i, kwh: 10 + i, tempF: 50 });
    days.push({ ts: 99, kwh: 50, tempF: null });
    const rows = anomalyDays(days, model);
    assert.equal(rows.length, 10);
    assert.ok(rows.every((row) => row.tempF != null));
    assert.ok(rows[0].absZ >= rows[1].absZ);
  });

  it("degreePrice converts slopes and cents per kWh into dollars per degree-day", () => {
    const price = degreePrice({ bH: 0.5, bC: 0.3 }, 10);
    assert.equal(price.heating, 0.05);
    assert.equal(price.cooling, 0.03);
  });

  it("forecastCone starts after published data and widens with the square root of lead days", () => {
    const publishedEnd = 2_000_000;
    const history = [];
    for (let i = 0; i < 14; i++) {
      history.push({ ts: publishedEnd - (14 - i) * 86400, tempF: 50, kwh: 10 });
    }
    const cone = forecastCone({
      model: { residualSd: 2, bH: 0.5, bC: 0, bW: 0, b0: 10, predict: () => 10 },
      history,
      publishedEnd,
      cycleEnd: publishedEnd + 4 * 86400,
    });
    assert.equal(cone.length, 4);
    assert.ok(cone.every((point) => point.ts > publishedEnd));
    assert.equal(cone[0].tempF, 50);
    const width = (point) => point.high - point.low;
    assert.ok(Math.abs(width(cone[3]) / width(cone[0]) - 2) < 1e-6);
    assert.ok(Math.abs(width(cone[0]) / 2 - 1.2816 * 2) < 1e-9);
  });
});
