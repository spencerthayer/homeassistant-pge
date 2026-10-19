import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { presetProbeEffect } from "../../custom_components/pge_energy/frontend/data.js";

describe("presetProbeEffect", () => {
  const base = {
    previousPresets: ["24h", "7d"],
    nextPresets: ["24h", "7d"],
    previousKey: "24h",
    nextKey: "24h",
    filterFocused: false,
  };

  it("skips a rebuild when availability and the selected key are unchanged", () => {
    assert.equal(presetProbeEffect(base), "skip");
    assert.equal(presetProbeEffect({ ...base, filterFocused: true }), "skip");
  });

  it("defers a real change while a filter control is focused", () => {
    assert.equal(
      presetProbeEffect({
        ...base,
        nextPresets: ["24h", "7d", "30d"],
        filterFocused: true,
      }),
      "defer",
    );
    assert.equal(
      presetProbeEffect({ ...base, nextKey: "7d", filterFocused: true }),
      "defer",
    );
  });

  it("rebuilds when the menu is closed and the choices changed", () => {
    assert.equal(
      presetProbeEffect({ ...base, nextPresets: ["24h", "7d", "cycle"] }),
      "rebuild",
    );
    assert.equal(presetProbeEffect({ ...base, previousKey: "24h", nextKey: "7d" }), "rebuild");
  });
});
