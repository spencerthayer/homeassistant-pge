/**
 * Local TOD vs billed vs rate-card Basic comparison (panel Time of Day hub).
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  computeTodPlanCompare,
  seriesCostCoverageComplete,
  todEnrollmentVerdict,
} from "../../custom_components/pge_energy/frontend/data.js";

const LIVE_WINDOW = {
  kwh: { off_peak: 297.22, mid_peak: 396.44, on_peak: 170.79 },
  cost: { off_peak: 54.7, mid_peak: 73.14, on_peak: 31.53 },
  rates: { off_peak: 0.0893, mid_peak: 0.167, on_peak: 0.4313 },
  basicRate: 0.1,
};

describe("seriesCostCoverageComplete", () => {
  it("requires a cost sample at every finite kWh timestamp", () => {
    const kwh = { xs: [1, 2, 3], values: [1, 1, 1] };
    assert.equal(
      seriesCostCoverageComplete(kwh, { xs: [1, 2, 3], values: [0.1, 0.1, 0.1] }),
      true,
    );
    assert.equal(
      seriesCostCoverageComplete(kwh, { xs: [1, 2], values: [0.1, 0.1] }),
      false,
    );
    assert.equal(seriesCostCoverageComplete(kwh, { xs: [], values: [] }), false);
    assert.equal(
      seriesCostCoverageComplete(kwh, { xs: [1, 2, 3], values: [0.1, null, 0.1] }),
      false,
    );
  });
});

describe("computeTodPlanCompare", () => {
  it("prices TOD from period rates and treats imported cost as billed when not enrolled", () => {
    const c = computeTodPlanCompare({ ...LIVE_WINDOW, enrolled: false });
    assert.equal(Number(c.totalKwh.toFixed(2)), 864.45);
    assert.equal(Number(c.billed.toFixed(2)), 159.37);
    assert.equal(Number(c.todPriced.toFixed(2)), 166.41);
    assert.equal(Number(c.rateCardBasic.toFixed(2)), 86.45);
    assert.equal(Number((c.effectiveUsdPerKwh * 100).toFixed(2)), 18.44);
    assert.equal(c.alternativePlan, "tod");
    assert.equal(Number(c.vsBilled.toFixed(2)), 7.04);
    assert.equal(Number(c.rateCardDelta.toFixed(2)), -79.96);
    assert.equal(Number(c.todPricedByPeriod.off_peak.toFixed(2)), 26.54);
  });

  it("uses rate-card Basic as the alternative when enrolled", () => {
    const c = computeTodPlanCompare({ ...LIVE_WINDOW, enrolled: true });
    assert.equal(c.alternativePlan, "basic");
    assert.equal(Number(c.billed.toFixed(2)), 159.37);
    assert.equal(Number(c.rateCardBasic.toFixed(2)), 86.45);
    assert.equal(Number(c.vsBilled.toFixed(2)), -72.92);
  });

  it("returns null when there is no energy to price", () => {
    assert.equal(
      computeTodPlanCompare({
        kwh: { off_peak: 0, mid_peak: 0, on_peak: 0 },
        cost: { off_peak: 0, mid_peak: 0, on_peak: 0 },
        rates: { off_peak: 0.1, mid_peak: 0.1, on_peak: 0.1 },
        basicRate: 0.1,
        enrolled: false,
      }),
      null,
    );
  });

  it("omits rate-card Basic and enrolled alternative when the Basic rate is missing", () => {
    const c = computeTodPlanCompare({
      ...LIVE_WINDOW,
      basicRate: null,
      enrolled: true,
    });
    assert.equal(c.rateCardBasic, null);
    assert.equal(c.rateCardDelta, null);
    assert.equal(c.vsBilled, null);
    assert.equal(Number(c.todPriced.toFixed(2)), 166.41);
  });
  it("returns null when cost samples were not observed", () => {
    assert.equal(
      computeTodPlanCompare({
        ...LIVE_WINDOW,
        cost: { off_peak: 0, mid_peak: 0, on_peak: 0 },
        enrolled: false,
        hasCost: false,
      }),
      null,
    );
  });

  it("returns null TOD pricing when a period rate is null", () => {
    const c = computeTodPlanCompare({
      ...LIVE_WINDOW,
      rates: { off_peak: 0.0893, mid_peak: null, on_peak: 0.4313 },
      enrolled: false,
    });
    assert.equal(c.todPriced, null);
    assert.equal(c.todPricedByPeriod, null);
    assert.equal(c.vsBilled, null);
  });

  it("preserves unknown enrollment without inventing a plan alternative", () => {
    const c = computeTodPlanCompare({ ...LIVE_WINDOW, enrolled: null });
    assert.equal(c.enrolled, null);
    assert.equal(c.alternativePlan, null);
    assert.equal(c.vsBilled, null);
    assert.equal(Number(c.todPriced.toFixed(2)), 166.41);
  });
});

describe("todEnrollmentVerdict", () => {
  it("says cost_more when not enrolled and TOD prices above billed", () => {
    const c = computeTodPlanCompare({ ...LIVE_WINDOW, enrolled: false });
    const v = todEnrollmentVerdict(c);
    assert.equal(v.kind, "cost_more");
    assert.equal(Number(v.amount.toFixed(2)), 7.04);
  });

  it("says save when not enrolled and TOD prices below billed", () => {
    const cheapTod = {
      ...LIVE_WINDOW,
      rates: { off_peak: 0.05, mid_peak: 0.05, on_peak: 0.05 },
      enrolled: false,
    };
    const v = todEnrollmentVerdict(computeTodPlanCompare(cheapTod));
    assert.equal(v.kind, "save");
    assert.ok(v.amount > 0);
  });

  it("says save when enrolled and billed TOD is below the Basic rate card", () => {
    const enrolledCheap = {
      ...LIVE_WINDOW,
      cost: { off_peak: 10, mid_peak: 10, on_peak: 10 },
      enrolled: true,
    };
    const v = todEnrollmentVerdict(computeTodPlanCompare(enrolledCheap));
    assert.equal(v.kind, "save");
  });

  it("says cost_more when enrolled and billed TOD is above the Basic rate card", () => {
    const v = todEnrollmentVerdict(
      computeTodPlanCompare({ ...LIVE_WINDOW, enrolled: true }),
    );
    assert.equal(v.kind, "cost_more");
    assert.equal(Number(v.amount.toFixed(2)), 72.92);
  });

  it("returns unknown when enrollment is unknown", () => {
    const c = computeTodPlanCompare({ ...LIVE_WINDOW, enrolled: null });
    assert.equal(todEnrollmentVerdict(c).kind, "unknown");
  });

  it("returns unknown when there is no comparison", () => {
    assert.equal(todEnrollmentVerdict(null).kind, "unknown");
  });
});
