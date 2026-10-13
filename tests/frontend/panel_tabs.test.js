import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { panelTabHash, resolvePanelTab, syncPillState } from "../../custom_components/pge_energy/frontend/data.js";

describe("panel tabs", () => {
  it("hash wins over the default section", () => {
    assert.equal(resolvePanelTab("#tod", "glance"), "tod");
    assert.equal(resolvePanelTab("#overview", "billing"), "glance");
  });

  it("falls back to the configured default, then glance", () => {
    assert.equal(resolvePanelTab("", "billing"), "billing");
    assert.equal(resolvePanelTab("#nope", "bogus"), "glance");
  });

  it("maps sync status onto the header pill", () => {
    assert.equal(syncPillState({ status: "complete" }).tone, "good");
    assert.match(syncPillState({ status: "complete" }).text, /^Synced/);
    assert.equal(syncPillState({ status: "backfilling", percent: 42 }).tone, "warn");
    assert.equal(syncPillState({ status: "backfilling", percent: 42 }).text, "Backfilling 42%");
    assert.equal(syncPillState({ status: "complete", failed_days: 2 }).tone, "critical");
    assert.equal(syncPillState({ status: "error" }).text, "Sync issue");
  });

  it("glance uses the overview hash", () => {
    assert.equal(panelTabHash("glance"), "#overview");
    assert.equal(panelTabHash("tod"), "#tod");
  });
});
