/**
 * Bill PDF composition and solar profiles. No new fetch.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { pacificMidnightUtc } from "../../custom_components/pge_energy/frontend/data.js";
import {
  billAnatomyRows,
  duckHourProfiles,
  fixedVariableRows,
  hasExport,
  lineItemShares,
  treemapSlices,
  waterfallSteps,
} from "../../custom_components/pge_energy/frontend/chart-series.js";

function atHour(ymd, hour) {
  return Math.floor(pacificMidnightUtc(ymd).getTime() / 1000) + hour * 3600;
}

const FAMILIES = {
  basic_charge: 20,
  energy_use_charge: 20,
  transmission_charge: 10,
  distribution_charge: 10,
  taxes_and_investments: 15,
  local_tax: 5,
  energy_delivery_charges: 20,
  power_cost_adjustment: 4,
  amount_due: 100,
  balance_forward: 0,
  previous_amount_due: 80,
  payment_received: 80,
};

describe("pdf and solar series", () => {
  it("duckHourProfiles keeps return in its own array", () => {
    const profiles = duckHourProfiles([
      { ts: atHour("2026-01-05", 14), kwh: 2, returned: 1 },
    ]);
    assert.equal(profiles.consumption[14], 2);
    assert.equal(profiles.returned[14], 1);
    assert.notEqual(profiles.consumption, profiles.returned);
  });

  it("hasExport is false when every return value is 0 or null", () => {
    assert.equal(hasExport([{ returned: 0 }, { returned: null }]), false);
    assert.equal(hasExport([{ returned: 0.2 }]), true);
  });

  it("billAnatomyRows stacks five families and does not add the delivery subtotal", () => {
    const rows = billAnatomyRows([{ ts: 100, ...FAMILIES }]);
    assert.equal(rows[0].basic, 20);
    assert.equal(rows[0].energyUse, 20);
    assert.equal(rows[0].delivery, 20);
    assert.equal(rows[0].taxes, 20);
    assert.equal(rows[0].other, 20);
    const column = rows[0].basic + rows[0].energyUse + rows[0].delivery + rows[0].taxes + rows[0].other;
    assert.equal(column, 100);
  });

  it("treemapSlices uses the latest statement only", () => {
    const slices = treemapSlices([
      { ts: 10, ...FAMILIES, amount_due: 40, balance_forward: 0, basic_charge: 40, energy_use_charge: 0, transmission_charge: 0, distribution_charge: 0, taxes_and_investments: 0, local_tax: 0, power_cost_adjustment: 0 },
      { ts: 20, ...FAMILIES },
    ]);
    assert.equal(slices.reduce((sum, slice) => sum + slice.value, 0), 100);
  });

  it("waterfallSteps walks previous due, payment, new charges, and amount due", () => {
    const steps = waterfallSteps({
      previous_amount_due: 100,
      payment_received: 40,
      balance_forward: 60,
      amount_due: 90,
    });
    assert.deepEqual(
      steps.map((step) => step.value),
      [100, -40, 30, 90],
    );
    const fallback = waterfallSteps({
      previous_amount_due: 100,
      payment_received: 40,
      amount_due: 90,
    });
    assert.equal(fallback[2].value, 30);
    assert.equal(fallback[3].value, 90);
  });

  it("fixedVariableRows and lineItemShares use the same five families", () => {
    const statement = { ts: 100, ...FAMILIES };
    const fixed = fixedVariableRows([statement]);
    const shares = lineItemShares(statement);
    assert.deepEqual(
      fixed[0].families.map((row) => row.key),
      shares.map((row) => row.key),
    );
    assert.equal(
      shares.reduce((sum, row) => sum + row.share, 0),
      100,
    );
    assert.ok(shares.every((row) => row.share === 20));
  });
});
