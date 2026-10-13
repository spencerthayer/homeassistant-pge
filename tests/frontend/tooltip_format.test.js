import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { formatTooltipRow } from "../../custom_components/pge_energy/frontend/data.js";

describe("formatTooltipRow", () => {
  it("hedges a dollar estimate", () => {
    assert.equal(
      formatTooltipRow({ name: "Import cost", value: 1.3149, unit: "$", estimate: true }),
      "Import cost: about $1.31 (PGE estimate)",
    );
  });

  it("prints kWh to two decimals", () => {
    assert.equal(formatTooltipRow({ name: "kWh", value: 7.091, unit: "kWh" }), "kWh: 7.09 kWh");
  });

  it("says no data for a missing value", () => {
    assert.equal(formatTooltipRow({ name: "kWh", value: null, unit: "kWh" }), "kWh: no data");
  });
});
