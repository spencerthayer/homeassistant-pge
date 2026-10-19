import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { panelTabHash, RANGE_PRESET_LABELS, RANGE_PRESET_PRIMARY, RANGE_PRESET_TOD, minPointsForPreset, rangePresets, resolvePanelTab, syncPillState } from "../../custom_components/pge_energy/frontend/data.js";

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

  it("usage fast-select is 24h, 3 days, 7 days, month, then the cycles", () => {
    assert.deepEqual(RANGE_PRESET_PRIMARY, ["24h", "3d", "7d", "30d", "cycle", "last_cycle"]);
    assert.equal(RANGE_PRESET_LABELS["3d"], "3 days");
    assert.equal(RANGE_PRESET_LABELS["7d"], "7 days");
    assert.deepEqual(RANGE_PRESET_TOD, RANGE_PRESET_PRIMARY);
    const presets = rangePresets(new Date("2026-10-19T18:00:00Z"));
    assert.equal(presets["3d"].period, "hour");
    assert.equal(presets["3d"].end.getTime() - presets["3d"].start.getTime(), 3 * 24 * 60 * 60 * 1000);
    assert.equal(minPointsForPreset("3d"), 12);
    assert.equal(presets["24h"].period, "hour");
    assert.equal(presets["24h"].end.getTime() - presets["24h"].start.getTime(), 24 * 60 * 60 * 1000);
  });

  it("gallery figures use heading hint popups instead of fig-info details", () => {
    const src = readFileSync(new URL("../../custom_components/pge_energy/frontend/pge-panel.js", import.meta.url), "utf8");
    assert.equal(src.includes('details class="fig-info"'), false);
    assert.equal(src.includes("mdi:information-outline"), false);
    assert.match(src, /_hint\(about, \{ html: true, label: "About this chart" \}\)/);
  });

  it("heatmap day click rebuilds the Usage range bar before the hero", () => {
    const src = readFileSync(new URL("../../custom_components/pge_energy/frontend/pge-panel.js", import.meta.url), "utf8");
    const start = src.indexOf("_openUsageDay(");
    const body = src.slice(start, src.indexOf("_heatmapWindowKey()", start));
    assert.match(body, /this\._renderFilters\(\);/);
    assert.ok(body.indexOf("this._renderFilters();") < body.indexOf("this._renderRangeScope()"));
  });

  it("disconnect releases the hashchange listener and header ResizeObserver", () => {
    const src = readFileSync(new URL("../../custom_components/pge_energy/frontend/pge-panel.js", import.meta.url), "utf8");
    const start = src.indexOf("disconnectedCallback() {");
    const body = src.slice(start, src.indexOf("async _boot()", start));
    assert.match(body, /window\.removeEventListener\("hashchange", this\._onPanelHashChange\)/);
    assert.match(body, /this\._headerObserver\?\.disconnect\(\)/);
  });

  it("glance uses the overview hash", () => {
    assert.equal(panelTabHash("glance"), "#overview");
    assert.equal(panelTabHash("tod"), "#tod");
  });
});
