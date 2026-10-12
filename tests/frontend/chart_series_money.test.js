/**
 * Weather, statement, and open-cycle aggregations.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  billVsImported,
  centsPerKwh,
  degreeDayPoint,
  openCycleCone,
  statementGap,
  statementWindows,
  tempBins,
} from "../../custom_components/pge_energy/frontend/chart-series.js";

describe("weather and money series", () => {
  it("degreeDayPoint uses a 65 F base", () => {
    assert.deepEqual(degreeDayPoint(60), { heating: 5, cooling: 0 });
    assert.deepEqual(degreeDayPoint(70), { heating: 0, cooling: 5 });
  });

  it("tempBins puts 75 F into the 70-79 bin", () => {
    const bins = tempBins([{ tempF: 75, kwh: 4 }]);
    const bin = bins.find((row) => row.key === "70-79");
    assert.ok(bin);
    assert.equal(bin.meanKwh, 4);
    assert.equal(bins.find((row) => row.key === "60-69").count, 0);
  });

  it("centsPerKwh ignores a day with 0 kWh", () => {
    const points = centsPerKwh([
      { kwh: 0, cost: 5, tempF: 40 },
      { kwh: 2, cost: 1, tempF: 50 },
    ]);
    assert.equal(points.length, 1);
    assert.equal(points[0].cents, 50);
  });

  it("statementWindows builds consecutive spans and replaces the last with bill bounds", () => {
    const bills = [{ ts: 10 }, { ts: 20 }, { ts: 30 }];
    assert.deepEqual(statementWindows(bills), [
      { start: 10, end: 20 },
      { start: 20, end: 30 },
    ]);
    assert.deepEqual(statementWindows(bills, { start: 18, end: 40 }), [
      { start: 10, end: 20 },
      { start: 18, end: 40 },
    ]);
    assert.deepEqual(statementWindows([{ ts: 10 }]), []);
  });

  it("statementGap sums cost samples inside each window", () => {
    const windows = [
      { start: 10, end: 20 },
      { start: 20, end: 30 },
    ];
    const gaps = statementGap(windows, [
      { ts: 10, cost: 1 },
      { ts: 19, cost: 2 },
      { ts: 20, cost: 4 },
      { ts: 25, cost: 1 },
    ]);
    assert.deepEqual(
      gaps.map((row) => row.total),
      [3, 5],
    );
  });

  it("billVsImported sums kWh samples inside each window", () => {
    const gaps = billVsImported([{ start: 10, end: 20 }], [
      { ts: 12, kwh: 2 },
      { ts: 20, kwh: 9 },
    ]);
    assert.equal(gaps[0].total, 2);
  });

  it("openCycleCone keeps tracker guides and running cost samples unchanged", () => {
    const samples = [{ ts: 1, cost: 3 }, { ts: 2, cost: 4 }];
    const cone = openCycleCone({ min: 10, max: 20, samples });
    assert.equal(cone.min, 10);
    assert.equal(cone.max, 20);
    assert.equal(cone.samples, samples);
  });
});
