/**
 * Load-shape aggregations. Timestamps are epoch seconds.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { pacificMidnightUtc } from "../../custom_components/pge_energy/frontend/data.js";
import {
  baseloadFloor,
  cycleCumulative,
  overnightFloorDays,
  dayFingerprints,
  hourWeekdayMatrix,
  loadDuration,
  monthRidges,
  monthlyByYear,
  publishedWeekDays,
  spreadBand,
  typicalDayProfiles,
} from "../../custom_components/pge_energy/frontend/chart-series.js";

function atHour(ymd, hour) {
  return Math.floor(pacificMidnightUtc(ymd).getTime() / 1000) + hour * 3600;
}

describe("load-shape series", () => {
  it("typicalDayProfiles splits Monday 18:00 from Saturday 18:00", () => {
    const profiles = typicalDayProfiles([
      { ts: atHour("2026-01-05", 18), kwh: 4 },
      { ts: atHour("2026-01-10", 18), kwh: 9 },
    ]);
    assert.equal(profiles.weekday[18], 4);
    assert.equal(profiles.weekend[18], 9);
    assert.equal(profiles.weekday[17], null);
    assert.equal(profiles.weekend[17], null);
  });

  it("loadDuration returns kWh descending", () => {
    assert.deepEqual(loadDuration([{ kwh: 1 }, { kwh: 5 }, { kwh: 3 }, { kwh: null }]), [5, 3, 1]);
  });

  it("hourWeekdayMatrix writes a Monday sample only into the Monday row", () => {
    const matrix = hourWeekdayMatrix([{ ts: atHour("2026-01-05", 18), kwh: 4 }]);
    assert.equal(matrix.labels[1], "Mon");
    assert.equal(matrix.values[1][18], 4);
    for (let row = 0; row < 7; row++) {
      for (let hour = 0; hour < 24; hour++) {
        if (row === 1 && hour === 18) continue;
        assert.equal(matrix.values[row][hour], null);
      }
    }
  });

  it("monthRidges keeps January and July hour profiles separate", () => {
    const ridges = monthRidges([
      { ts: atHour("2026-01-05", 18), kwh: 2 },
      { ts: atHour("2026-07-15", 18), kwh: 8 },
    ]);
    const jan = ridges.find((row) => row.key === "2026-01");
    const jul = ridges.find((row) => row.key === "2026-07");
    assert.equal(jan.hours[18], 2);
    assert.equal(jul.hours[18], 8);
    assert.equal(jan.hours[18] === jul.hours[18], false);
  });

  it("monthly totals require all dates and deduplicate daily input", () => {
    const january = Array.from({ length: 31 }, (_, day) => ({
      ts: atHour(`2026-01-${String(day + 1).padStart(2, "0")}`, 0),
      kwh: 1,
    }));
    const leap = Array.from({ length: 29 }, (_, day) => ({
      ts: atHour(`2024-02-${String(day + 1).padStart(2, "0")}`, 0),
      kwh: day === 0 ? 0 : 2,
    }));
    const out = monthlyByYear([
      ...january,
      january[0],
      { ts: atHour("2026-02-01", 0), kwh: 4 },
      { ts: atHour("2026-03-01", 0), kwh: null },
      ...leap,
    ]);
    assert.equal(out.series[out.years.indexOf("2026")][0], 31);
    assert.equal(out.series[out.years.indexOf("2026")][1], null);
    assert.equal(out.series[out.years.indexOf("2024")][1], 2 * 28);
  });

  it("cycleCumulative sums hourly kWh by day index from a statement start", () => {
    const start = atHour("2026-01-05", 0);
    const out = cycleCumulative(
      [
        { ts: start, kwh: 1 },
        { ts: start + 3600, kwh: 1 },
        { ts: atHour("2026-01-06", 0), kwh: 3 },
      ],
      start,
    );
    assert.deepEqual(out.dayIndex, [0, 1]);
    assert.deepEqual(out.cumulative, [2, 5]);
  });

  it("spreadBand on [2, 4] returns mean 3 and sample standard deviation sqrt(2)", () => {
    const band = spreadBand([2, 4]);
    assert.equal(band.mean, 3);
    assert.ok(Math.abs(band.sd - Math.sqrt(2)) < 1e-12);
  });

  it("publishedWeekDays returns seven day keys", () => {
    const keys = publishedWeekDays(new Date("2026-01-14T18:00:00.000Z"));
    assert.equal(keys.length, 7);
    assert.deepEqual(keys, [
      "2026-01-04",
      "2026-01-05",
      "2026-01-06",
      "2026-01-07",
      "2026-01-08",
      "2026-01-09",
      "2026-01-10",
    ]);
  });

  it("dayFingerprints skips a day that has kWh and no temperature", () => {
    const rows = dayFingerprints([
      { ts: atHour("2026-01-05", 18), kwh: 4, tempF: null, cost: 1 },
      { ts: atHour("2026-01-06", 18), kwh: 2, tempF: 40, cost: 0.5 },
    ]);
    assert.equal(rows.length, 1);
    assert.equal(rows[0].ymd, "2026-01-06");
    assert.equal(rows[0].tempF, 40);
  });

  it("baseloadFloor returns the minimum of hours 0 through 5", () => {
    assert.equal(baseloadFloor([3, 1.5, 2, 4, 0.4, 5, 9]), 0.4);
  });

  it("overnight floor requires all real DST slots and keeps large loads", () => {
    const slots = (iso, count) =>
      Array.from({ length: count }, (_, i) => ({
        ts: Date.parse(iso) / 1000 + i * 3600,
        kwh: i === 0 ? 12 : 13,
      }));
    assert.deepEqual(overnightFloorDays([{ ts: atHour("2019-11-01", 0), kwh: 1300 }]), []);
    assert.deepEqual(overnightFloorDays(slots("2026-03-08T08:00:00Z", 5)), [
      { ymd: "2026-03-08", kwh: 12 },
    ]);
    assert.deepEqual(overnightFloorDays(slots("2026-11-01T07:00:00Z", 7)), [
      { ymd: "2026-11-01", kwh: 12 },
    ]);
    assert.deepEqual(overnightFloorDays(slots("2026-11-01T07:00:00Z", 6)), []);
    const normal = slots("2026-06-15T07:00:00Z", 6);
    normal.push({ ts: normal[0].ts, kwh: 1 });
    assert.deepEqual(overnightFloorDays(normal), [{ ymd: "2026-06-15", kwh: 1 }]);
    assert.deepEqual(
      overnightFloorDays([{ ts: atHour("2026-06-15", 1), kwh: null }, ...slots("2026-06-15T07:00:00Z", 5)]),
      [],
    );
  });
});
