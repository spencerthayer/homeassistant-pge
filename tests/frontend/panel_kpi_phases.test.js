import assert from "node:assert/strict";
import { before, it } from "node:test";

let Panel;
before(async () => {
  globalThis.HTMLElement ??= class {};
  globalThis.customElements = {
    get: () => undefined,
    define: (_name, cls) => { Panel = cls; },
  };
  await import("../../custom_components/pge_energy/frontend/pge-panel.js");
});

function kpiPanel(callWS) {
  const el = {
    innerHTML: "", childElementCount: 0, attrs: new Map(),
    querySelectorAll: () => [],
    setAttribute(name, value) { this.attrs.set(name, value); },
    removeAttribute(name) { this.attrs.delete(name); },
  };
  const panel = Object.assign(Object.create(Panel.prototype), {
    _fetchCache: new Map(), _galleryRenderGen: 1, _activeEntryId: "a", _kpiSig: "",
    shadowRoot: { getElementById: (id) => id === "kpis" ? el : null },
    _accounts: [{
      entry_id: "a",
      entity_ids: { amount_due: "sensor.due", yesterday_energy: "sensor.yesterday" },
      statistic_ids: { consumption: "c", cost: "k", compensation: "comp" },
    }],
    _hass: {
      states: {
        "sensor.due": { state: "42.5" },
        "sensor.yesterday": { state: "18.25" },
      },
      callWS,
    },
  });
  return { panel, el };
}
function weekImport(html) {
  const match = html.match(/<span class="group">This week<\/span>Import<\/div><div class="value">([^<]*)<\/div>/);
  assert.ok(match, "completed week import tile exists");
  return match[1];
}

it("entity-only paint makes no recorder requests and announces busy correctly", async () => {
  let calls = 0;
  const { panel, el } = kpiPanel(async () => { calls += 1; return {}; });
  await panel._renderKpis({ recorder: false });
  assert.equal(calls, 0);
  assert.match(el.innerHTML, /42[.,]50/);
  assert.match(el.innerHTML, /18[.,]25 kWh/);
  assert.equal((el.innerHTML.match(/class="kpi-pending"/g) || []).length, 6);
  assert.equal(el.attrs.get("aria-busy"), "true");
});

it("recorder completion replaces pending with missing values, not zero", async () => {
  let calls = 0;
  const { panel, el } = kpiPanel(async () => { calls += 1; return {}; });
  await panel._renderKpis({ recorder: false });
  el.childElementCount = 1;
  await panel._renderKpis();
  assert.ok(calls > 0);
  assert.doesNotMatch(el.innerHTML, /kpi-pending/);
  assert.equal(el.attrs.has("aria-busy"), false);
  assert.equal(weekImport(el.innerHTML), "—");
});

it("a recorded zero stays zero", async () => {
  const { panel, el } = kpiPanel(async (msg) => ({
    [msg.statistic_ids[0]]: [{ start: Date.parse(msg.start_time), change: 0, sum: 0 }],
  }));
  await panel._renderKpis();
  assert.match(weekImport(el.innerHTML), /^0(?:[.,]0{1,2})? kWh$/);
});

it("phase 1 paints before a pending hero and phase 2 waits", async () => {
  let finish;
  const gate = new Promise((resolve) => { finish = resolve; });
  const calls = [];
  const panel = Object.assign(Object.create(Panel.prototype), {
    _fetchCache: new Map(), _galleryRenderGen: 1, _activeEntryId: "a",
    _activeTab: "glance", _renderedTabs: new Set(), _charts: [],
    _pendingMounts: new Map(), _chartFactories: new Map(),
    _rangeKey: "24h", _availablePresets: ["24h"],
    _renderSync() {}, _billBounds: () => null, _renderFilters() {},
    _renderDiagnostics() {}, _renderDataGaps: async () => {},
    _probeAvailablePresets: async () => false, _renderTabGalleries: async () => {},
    _renderKpis: async ({ recorder = true } = {}) => { calls.push(recorder ? "full" : "entity"); },
    _renderHero: () => { calls.push("hero"); return gate; },
  });
  globalThis.requestAnimationFrame = (callback) => { queueMicrotask(callback); return 0; };
  const done = panel._renderAll();
  try {
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(calls, ["entity", "hero"]);
  } finally {
    finish();
    await done;
  }
  assert.deepEqual(calls, ["entity", "hero", "full"]);
});
