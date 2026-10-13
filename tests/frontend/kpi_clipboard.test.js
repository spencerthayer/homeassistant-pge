/**
 * Dependency-free Node tests for At a glance KPI clipboard formatting.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { formatKpiClipboardText, pctDelta } from "../../custom_components/pge_energy/frontend/data.js";

describe("pctDelta", () => {
  it("returns the percent change and null for a missing or zero baseline", () => {
    assert.ok(Math.abs(pctDelta(68.64, 60) - 14.4) < 0.001);
    assert.equal(pctDelta(5, 0), null);
    assert.equal(pctDelta(null, 5), null);
  });
});

describe("formatKpiClipboardText", () => {
  it("joins label, value, and delta on separate lines", () => {
    assert.equal(
      formatKpiClipboardText({
        label: "Yesterday import",
        value: "12.34 kWh",
        delta: "2026-08-09 → 2026-08-14",
      }),
      "Yesterday import\n12.34 kWh\n2026-08-09 → 2026-08-14"
    );
  });

  it("omits empty delta and collapses whitespace", () => {
    assert.equal(
      formatKpiClipboardText({
        label: "  Yesterday export  ",
        value: "  1.5 kWh\n",
        delta: "   ",
      }),
      "Yesterday export\n1.5 kWh"
    );
  });

  it("returns empty string when nothing useful is present", () => {
    assert.equal(formatKpiClipboardText({}), "");
    assert.equal(formatKpiClipboardText({ label: null, value: "", delta: undefined }), "");
  });
});
