import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { panelTabHash, resolvePanelTab } from "../../custom_components/pge_energy/frontend/data.js";

describe("panel tabs", () => {
  it("hash wins over the default section", () => {
    assert.equal(resolvePanelTab("#tod", "glance"), "tod");
    assert.equal(resolvePanelTab("#overview", "billing"), "glance");
  });

  it("falls back to the configured default, then glance", () => {
    assert.equal(resolvePanelTab("", "billing"), "billing");
    assert.equal(resolvePanelTab("#nope", "bogus"), "glance");
  });

  it("glance uses the overview hash", () => {
    assert.equal(panelTabHash("glance"), "#overview");
    assert.equal(panelTabHash("tod"), "#tod");
  });
});
