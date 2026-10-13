/**
 * Time of Day aggregations. Period keys match todPeriodForPacific.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { pacificMidnightUtc } from "../../custom_components/pge_energy/frontend/data.js";
import {
  forwardRibbon,
  moneyHourPareto,
  periodBox,
  periodKwh,
  periodMixByMonth,
  sankeyFlows,
  todMinusBasicByMonth,
} from "../../custom_components/pge_energy/frontend/chart-series.js";

function atHour(ymd, hour) {
  return Math.floor(pacificMidnightUtc(ymd).getTime() / 1000) + hour * 3600;
}

const RATES = { off_peak: 0.1, mid_peak: 0.2, on_peak: 0.4 };

describe("time of day series", () => {
  it("puts a Saturday noon sample entirely in off_peak", () => {
    const totals = periodKwh([{ ts: atHour("2026-01-10", 12), kwh: 5 }]);
    assert.equal(totals.off_peak, 5);
    assert.equal(totals.mid_peak, 0);
    assert.equal(totals.on_peak, 0);
  });

  it("puts Wednesday 18:00 in on_peak and an observed July 4 Wednesday in off_peak", () => {
    const weekday = periodKwh([{ ts: atHour("2026-01-07", 18), kwh: 3 }]);
    assert.equal(weekday.on_peak, 3);
    const holiday = periodKwh([{ ts: atHour("2018-07-04", 18), kwh: 3 }]);
    assert.equal(holiday.off_peak, 3);
    assert.equal(holiday.on_peak, 0);
  });

  it("periodMixByMonth shares for a single on-peak hour are 100 on that period", () => {
    const mix = periodMixByMonth([{ ts: atHour("2026-01-07", 18), kwh: 4 }]);
    assert.equal(mix.length, 1);
    assert.equal(mix[0].month, "2026-01");
    assert.equal(mix[0].on_peak, 100);
    assert.equal(mix[0].off_peak, 0);
    assert.equal(mix[0].mid_peak, 0);
  });

  it("moneyHourPareto cumulative share is largest first", () => {
    const rows = moneyHourPareto(
      [
        { ts: atHour("2026-01-07", 1), dollars: 10 },
        { ts: atHour("2026-01-07", 2), dollars: 30 },
        { ts: atHour("2026-01-07", 3), dollars: 60 },
      ],
      { off_peak: 1, mid_peak: 1, on_peak: 1 },
    );
    assert.deepEqual(rows.map((row) => row.dollars), [60, 30, 10]);
    assert.deepEqual(
      rows.map((row) => row.cumulativeShare),
      [60, 90, 100],
    );
  });

  it("moneyHourPareto orders hours by kwh * rate descending and keeps at most 8", () => {
    const samples = [];
    for (let hour = 0; hour < 10; hour++) {
      samples.push({ ts: atHour("2026-01-10", hour), kwh: hour + 1 });
    }
    const rows = moneyHourPareto(samples, RATES);
    assert.equal(rows.length, 8);
    assert.ok(rows[0].dollars >= rows[1].dollars);
    assert.equal(rows[0].hour, 9);
  });

  it("moneyHourPareto sums explicit dollars and ignores the flat rate table", () => {
    const rows = moneyHourPareto(
      [
        { ts: atHour("2026-01-07", 18), dollars: 1.5 },
        { ts: atHour("2026-01-08", 18), dollars: 2.5 },
        { ts: atHour("2026-01-07", 1), dollars: 0.25 },
      ],
      { off_peak: 9, mid_peak: 9, on_peak: 9 },
    );
    const hour18 = rows.find((row) => row.hour === 18);
    assert.equal(hour18.dollars, 4);
  });

  it("periodBox on [1, 2, 3, 4] returns min 1, max 4, and a median inside the middle half", () => {
    const box = periodBox([1, 2, 3, 4]);
    assert.equal(box.min, 1);
    assert.equal(box.max, 4);
    assert.ok(box.median >= box.q1 && box.median <= box.q3);
  });

  it("periodBox on a single value uses that value for both quartiles", () => {
    const box = periodBox([5]);
    assert.deepEqual(box, { min: 5, q1: 5, median: 5, q3: 5, max: 5 });
  });

  it("todMinusBasicByMonth returns basicSum - todSum", () => {
    const rows = todMinusBasicByMonth([
      { ts: atHour("2026-01-05", 12), tod: 4, basic: 10 },
    ]);
    assert.equal(rows[0].month, "2026-01");
    assert.equal(rows[0].delta, 6);
  });

  it("forwardRibbon labels 48 hours and marks Saturday as off_peak for every hour", () => {
    const ribbon = forwardRibbon({ startTs: atHour("2026-01-10", 0) });
    assert.equal(ribbon.length, 48);
    const saturday = ribbon.filter((row) => row.ymd === "2026-01-10");
    assert.equal(saturday.length, 24);
    assert.ok(saturday.every((row) => row.period === "off_peak"));
    assert.ok(ribbon.every((row) => typeof row.label === "string" && row.label.length > 0));
  });

  it("sankeyFlows drops a period whose kWh is 0", () => {
    const flows = sankeyFlows([
      { period: "off_peak", kwh: 0, dollars: 0 },
      { period: "on_peak", kwh: 2, dollars: 0.8 },
    ]);
    assert.deepEqual(
      flows.map((row) => row.period),
      ["on_peak"],
    );
  });
});
