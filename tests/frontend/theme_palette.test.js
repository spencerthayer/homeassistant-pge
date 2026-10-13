import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { BILL_FAMILY_KEYS, distinctPalette } from "../../custom_components/pge_energy/frontend/theme.js";

describe("palette", () => {
  it("distinctPalette keeps first occurrence order and drops repeats", () => {
    assert.deepEqual(distinctPalette(["#1baf7a", "#2a78d6", "#1BAF7A ", "#eb6834"]), [
      "#1baf7a",
      "#2a78d6",
      "#eb6834",
    ]);
  });

  it("distinctPalette normalizes short hex and whitespace", () => {
    assert.deepEqual(distinctPalette(["#abc", "#aabbcc", "rgb(1, 2, 3)", "rgb(1,2,3)"]), [
      "#aabbcc",
      "rgb(1,2,3)",
    ]);
  });

  it("bill family keys are fixed", () => {
    assert.deepEqual(BILL_FAMILY_KEYS, ["basic", "energyUse", "delivery", "taxes", "other"]);
  });
});
