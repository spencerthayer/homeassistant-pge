/**
 * Dependency-free Node tests for directional usage projection helpers.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  RATE_EPSILON_KWH,
  computeUsageAccounting,
  formatSignedUsd,
  pacificMidnightUtc,
  priorPacificYmd,
  projectDirectionalUsage,
  projectUsageSeries,
  symmetricExtent,
} from "../../custom_components/pge_energy/frontend/data.js";

function series(pairs) {
  return {
    xs: pairs.map(([t]) => t),
    values: pairs.map(([, v]) => v),
  };
}

describe("projectDirectionalUsage", () => {
  it("import hour keeps positive flow and import amount", () => {
    const p = projectDirectionalUsage({
      kwh: series([[1, 1.2]]),
      cost: series([[1, 0.24]]),
    });
    assert.equal(p.flowMode, "import");
    assert.equal(p.amountMode, "import");
    assert.deepEqual(p.flow.values, [1.2]);
    assert.deepEqual(p.amount.values, [0.24]);
  });

  it("export with credit yields negative flow and net amount", () => {
    const p = projectDirectionalUsage({
      kwh: series([[1, 0]]),
      returned: series([[1, 0.75]]),
      cost: series([[1, 0]]),
      compensation: series([[1, 0.08]]),
    });
    assert.equal(p.flowMode, "signed");
    assert.equal(p.amountMode, "net");
    assert.deepEqual(p.flow.values, [-0.75]);
    assert.deepEqual(p.amount.values, [-0.08]);
  });

  it("export without compensation stays in import-cost amount mode", () => {
    const p = projectDirectionalUsage({
      returned: series([[1, 0.75]]),
      cost: series([[1, 0]]),
    });
    assert.equal(p.flowMode, "signed");
    assert.equal(p.amountMode, "import");
    assert.deepEqual(p.flow.values, [-0.75]);
    assert.deepEqual(p.amount.values, [0]);
  });

  it("zero-only compensation stays in import-cost amount mode", () => {
    const p = projectDirectionalUsage({
      returned: series([[1, 0.75]]),
      cost: series([[1, 0.1]]),
      compensation: series([[1, 0]]),
    });
    assert.equal(p.hasCompensation, false);
    assert.equal(p.amountMode, "import");
    assert.deepEqual(p.amount.values, [0.1]);
  });

  it("true gaps invent neither flow nor amount zeros", () => {
    const p = projectDirectionalUsage({
      kwh: series([[1, 1]]),
      cost: series([[1, 0.1]]),
    });
    assert.deepEqual(p.flow.xs, [1]);
    assert.ok(!p.flow.xs.includes(2));
    assert.ok(!p.amount.xs.includes(2));
  });

  it("defensive overlap subtracts algebraically", () => {
    const p = projectDirectionalUsage({
      kwh: series([[1, 1.0]]),
      returned: series([[1, 0.25]]),
      cost: series([[1, 0.2]]),
      compensation: series([[1, 0.03]]),
    });
    assert.deepEqual(p.flow.values, [0.75]);
    assert.deepEqual(p.amount.values, [0.17]);
  });

  it("aggregate buckets at the same grain", () => {
    const p = projectDirectionalUsage({
      kwh: series([[10, 5]]),
      returned: series([[10, 2]]),
      cost: series([[10, 1.1]]),
      compensation: series([[10, 0.2]]),
    });
    assert.deepEqual(p.flow.values, [3]);
    assert.equal(Number(p.amount.values[0].toFixed(2)), 0.9);
  });

  it("missing counterpart at an observed timestamp means zero", () => {
    const p = projectDirectionalUsage({
      returned: series([[5, 1.5]]),
      compensation: series([[5, 0.05]]),
    });
    assert.deepEqual(p.flow.values, [-1.5]);
    assert.deepEqual(p.amount.values, [-0.05]);
  });

  it("handles out-of-order timestamps", () => {
    const p = projectDirectionalUsage({
      kwh: series([
        [3, 1],
        [1, 2],
      ]),
      returned: series([[2, 0.5]]),
    });
    assert.deepEqual(p.flow.xs, [1, 2, 3]);
    assert.deepEqual(p.flow.values, [2, -0.5, 1]);
  });

  it("distinguishes missing from explicit zero", () => {
    const p = projectDirectionalUsage({
      kwh: series([[1, 0]]),
      returned: series([[1, 0]]),
      cost: series([[1, 0]]),
    });
    assert.equal(p.flowMode, "import");
    assert.deepEqual(p.flow.values, [0]);
    assert.equal(p.hasReturn, false);
  });

  it("omits non-finite series values including Infinity", () => {
    const p = projectDirectionalUsage({
      kwh: series([
        [1, 1.5],
        [2, Infinity],
        [3, -Infinity],
        [4, Number.NaN],
      ]),
      cost: series([
        [1, 0.3],
        [2, Infinity],
        [3, -Infinity],
        [4, Number.NaN],
      ]),
    });
    // Non-finite kWh/cost samples drop out of their maps; finite peers remain.
    assert.deepEqual(p.flow.xs, [1]);
    assert.deepEqual(p.flow.values, [1.5]);
    assert.deepEqual(p.amount.xs, [1]);
    assert.deepEqual(p.amount.values, [0.3]);
  });
});

describe("symmetricExtent", () => {
  it("returns symmetric padded bounds including zero", () => {
    const ext = symmetricExtent([-2, 1], 0.1);
    assert.ok(ext);
    assert.equal(ext[0], -ext[1]);
    assert.ok(ext[1] > 2);
  });

  it("handles all-zero with a unit range", () => {
    assert.deepEqual(symmetricExtent([0, 0]), [-1, 1]);
  });

  it("returns null for empty input", () => {
    assert.equal(symmetricExtent([]), null);
    assert.equal(symmetricExtent(null), null);
  });

  it("all-positive still centers on zero", () => {
    const ext = symmetricExtent([1, 3], 0);
    assert.deepEqual(ext, [-3, 3]);
  });
});

describe("formatSignedUsd", () => {
  it("formats negative currency with unicode minus", () => {
    assert.equal(formatSignedUsd(-0.08), "−$0.08");
  });

  it("formats positive currency", () => {
    assert.equal(formatSignedUsd(1.2), "$1.20");
  });

  it("handles nullish", () => {
    assert.equal(formatSignedUsd(null), "—");
  });
});

describe("projectUsageSeries + rate epsilon", () => {
  it("projects into chart-shaped series", () => {
    const view = projectUsageSeries({
      kwh: series([[1, 2]]),
      returned: series([[1, 0.5]]),
      cost: series([[1, 0.4]]),
      compensation: series([[1, 0.1]]),
      temp: { xs: [1], values: [70], means: [70] },
    });
    assert.equal(view.flowMode, "signed");
    assert.equal(view.amountMode, "net");
    assert.deepEqual(view.kwh.values, [1.5]);
    assert.equal(Number(view.cost.values[0].toFixed(2)), 0.3);
    assert.deepEqual(view.temp.means, [70]);
  });

  it("exposes a near-zero rate epsilon", () => {
    assert.ok(RATE_EPSILON_KWH > 0);
    assert.ok(RATE_EPSILON_KWH < 0.001);
  });
});

describe("computeUsageAccounting rates", () => {
  it("uses gross import for avgRate when signed flow keeps import-cost mode", () => {
    // Import 1 kWh @ $0.20 and export 2 kWh ⇒ net flow −1; gross import 1.
    const chart = projectUsageSeries({
      kwh: series([[1, 1]]),
      returned: series([[1, 2]]),
      cost: series([[1, 0.2]]),
    });
    assert.equal(chart.flowMode, "signed");
    assert.equal(chart.amountMode, "import");
    assert.deepEqual(chart.kwh.values, [-1]);
    const acct = computeUsageAccounting(chart, {
      start: new Date(0),
      end: new Date(3600_000),
      period: "hour",
    });
    assert.ok(acct.avgRate != null);
    assert.equal(Number(acct.avgRate.toFixed(2)), 0.2);
    // Bucket has 1 kWh gross import ⇒ divide by gross import, not the −1 net flow.
    assert.equal(Number(acct.hours[0].rate.toFixed(2)), 0.2);
    assert.equal(acct.hours[0].grossImport, 1);
  });

  it("divides by net flow + return so export-heavy buckets report gross-import rate", () => {
    // One hour: import 0, export 2 ⇒ gross import 0 ⇒ rate suppressed.
    const pureExport = projectUsageSeries({
      kwh: series([[1, 0]]),
      returned: series([[1, 2]]),
      cost: series([[1, 0]]),
    });
    const acctPure = computeUsageAccounting(pureExport, {
      start: new Date(0),
      end: new Date(3600_000),
      period: "hour",
    });
    assert.equal(acctPure.hours[0].grossImport, 0);
    assert.equal(acctPure.hours[0].rate, null);

    // Import 10 kWh @ $2 then export 5 kWh ⇒ net 5, gross import 10 ⇒ $0.20/kWh.
    const mixed = projectUsageSeries({
      kwh: series([[1, 10]]),
      returned: series([[1, 5]]),
      cost: series([[1, 2]]),
    });
    assert.equal(mixed.flowMode, "signed");
    assert.equal(mixed.amountMode, "import");
    const acctMixed = computeUsageAccounting(mixed, {
      start: new Date(0),
      end: new Date(3600_000),
      period: "hour",
    });
    assert.equal(acctMixed.hours[0].grossImport, 10);
    assert.equal(Number(acctMixed.hours[0].rate.toFixed(2)), 0.2);
  });

  it("keeps signed net rate when compensation is observed", () => {
    const chart = projectUsageSeries({
      kwh: series([[1, 0]]),
      returned: series([[1, 2]]),
      cost: series([[1, 0]]),
      compensation: series([[1, 0.1]]),
    });
    assert.equal(chart.amountMode, "net");
    const acct = computeUsageAccounting(chart, {
      start: new Date(0),
      end: new Date(3600_000),
      period: "hour",
    });
    assert.equal(Number(acct.avgRate.toFixed(2)), 0.05);
    assert.equal(Number(acct.hours[0].rate.toFixed(2)), 0.05);
  });
});

describe("priorPacificYmd", () => {
  it("subtracts one Pacific calendar day without 24h wall-clock math", () => {
    assert.equal(priorPacificYmd("2026-03-09"), "2026-03-08");
    assert.equal(priorPacificYmd("2026-11-02"), "2026-11-01");
    const start = pacificMidnightUtc(priorPacificYmd("2026-03-09"));
    const end = pacificMidnightUtc("2026-03-09");
    // Spring forward: Pacific 2026-03-08 is 23 hours long.
    assert.equal((end - start) / 3600_000, 23);
  });
});
