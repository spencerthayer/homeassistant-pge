import assert from "node:assert/strict";
import { before, it } from "node:test";

let Panel;
before(async () => {
  globalThis.HTMLElement ??= class {};
  globalThis.requestAnimationFrame = (callback) => {
    queueMicrotask(callback);
    return 0;
  };
  globalThis.customElements = {
    get: () => undefined,
    define: (_name, cls) => { Panel = cls; },
  };
  await import("../../custom_components/pge_energy/frontend/pge-panel.js");
});

function deferred() {
  let resolve;
  const promise = new Promise((finish) => { resolve = finish; });
  return { promise, resolve };
}
function panelWith(fields = {}) {
  return Object.assign(Object.create(Panel.prototype), {
    _fetchCache: new Map(), _galleryRenderGen: 1, _todRenderGen: 0,
    _rangeRenderGen: 0, _presetProbeGen: 0, _activeEntryId: "a", _activeTab: "analytics",
    _charts: [], _pendingMounts: new Map(), _chartFactories: new Map(),
    _renderedTabs: new Set(["usage"]), _primaryReady: true,
    _rangeKey: "24h", _availablePresets: ["24h"],
    _renderSync() {}, _billBounds: () => null, _renderFilters() {},
    _renderDiagnostics() {}, ...fields,
  });
}
function root(ids = {}) {
  return {
    getElementById: (id) => ids[id] ?? null,
    querySelector: () => null,
    querySelectorAll: () => [],
  };
}

it("starts the landing primary before any secondary recorder work", async () => {
  const gate = deferred();
  const calls = [];
  const panel = panelWith({
    _renderHero: async () => { calls.push("hero"); },
    _renderInsights: () => { calls.push("insights"); return gate.promise; },
    _renderKpis: async () => { calls.push("kpis"); },
    _renderDataGaps: async () => { calls.push("gaps"); },
    _probeAvailablePresets: async () => { calls.push("presets"); return false; },
    _renderTabGalleries: async (tab, options) => {
      calls.push("galleries");
      assert.equal(tab, "analytics");
      assert.equal(options.primaryRendered, true);
    },
  });
  const done = panel._renderAll();
  try {
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(calls, ["insights"]);
    assert.equal(panel._primaryReady, false);
  } finally {
    gate.resolve();
    await done;
  }
  assert.equal(panel._primaryReady, true);
  assert.equal(panel._renderedTabs.has("usage"), false);
  assert.equal(panel._renderedTabs.has("analytics"), true);
  assert.ok(calls.includes("galleries"));
  assert.ok(calls.indexOf("insights") < calls.indexOf("kpis"));
});

it("a deferred weather render does not block a switch off Analytics", async () => {
  const insights = deferred();
  const weather = deferred();
  const calls = [];
  const panel = panelWith({
    _activeTab: "analytics",
    _accounts: [{ entry_id: "a" }],
    _renderInsights: () => { calls.push("insights"); return insights.promise; },
    _renderWeatherMoney: () => { calls.push("weather"); return weather.promise; },
    _renderHero: async () => { calls.push("hero"); },
    _renderKpis: async () => {}, _renderDataGaps: async () => {},
    _probeAvailablePresets: async () => false, _renderTabGalleries: async () => {},
    _renderBillingPrograms() { calls.push("billing"); },
  });
  const done = panel._renderAll();
  try {
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(calls, ["weather", "insights"]);
    panel._activeTab = "billing";
    insights.resolve();
    await new Promise((resolve) => setImmediate(resolve));
    assert.ok(calls.includes("billing"));
    assert.equal(panel._primaryReady, true);
  } finally {
    weather.resolve();
    await done;
  }
  assert.equal(panel._primaryReady, true);
});

it("switching tabs during initial rendering renders the newly selected primary", async () => {
  const gate = deferred();
  const calls = [];
  const panel = panelWith({
    _activeTab: "glance",
    _renderHero: () => { calls.push("hero"); return gate.promise; },
    _renderInsights: async () => { calls.push("insights"); },
    _renderKpis: async () => {}, _renderDataGaps: async () => {},
    _probeAvailablePresets: async () => false, _renderTabGalleries: async () => {},
  });
  const done = panel._renderAll();
  panel._activeTab = "analytics";
  gate.resolve();
  await done;
  assert.deepEqual(calls, ["hero", "insights"]);
});

it("an invalidated render does not release secondary work", async () => {
  const gate = deferred();
  let secondary = 0;
  const panel = panelWith({
    _renderHero: () => gate.promise, _renderInsights: () => gate.promise,
    _renderKpis: async () => { secondary += 1; },
    _renderDataGaps: async () => { secondary += 1; },
    _probeAvailablePresets: async () => { secondary += 1; },
    _renderTabGalleries: async () => { secondary += 1; },
  });
  const done = panel._renderAll();
  panel._galleryRenderGen += 1;
  gate.resolve();
  await done;
  assert.equal(secondary, 0);
  assert.equal(panel._primaryReady, false);
});

it("hass pushes wait for primary readiness", () => {
  let secondary = 0;
  const panel = panelWith({
    _primaryReady: false, _loading: false, _hass: {}, _todBillReady: false,
    _accounts: [{ entry_id: "a" }], style: {},
    getAttribute: () => "|light", toggleAttribute() {}, setAttribute() {},
    _renderKpis: async () => { secondary += 1; },
    _renderBillingPrograms: () => { secondary += 1; return false; },
    _schedulePresetProbe: () => { secondary += 1; },
  });
  panel.hass = { themes: { darkMode: false } };
  assert.equal(secondary, 0);
});

it("a previously queued preset callback waits for primary readiness", async () => {
  let probes = 0;
  const panel = panelWith({
    _primaryReady: false, _filterControlFocused: () => false,
    _probeAvailablePresets: async () => { probes += 1; return false; },
  });
  await panel._refreshPresetFilters();
  assert.equal(probes, 0);
});

it("first visits build ToD, Billing, and Programs bodies", async () => {
  const calls = [];
  const panel = panelWith({
    shadowRoot: root(),
    _renderTod: async () => { calls.push("tod-body"); },
    _renderTodGallery: async () => { calls.push("tod-gallery"); },
    _renderBillingPrograms: () => { calls.push("account-body"); },
    _renderLedgerCharts: async () => { calls.push("ledger"); },
  });
  await panel._renderTabGalleries("tod");
  await panel._renderTabGalleries("billing");
  await panel._renderTabGalleries("programs");
  assert.deepEqual(calls, ["tod-body", "account-body", "ledger", "account-body"]);
  calls.length = 0;
  panel.shadowRoot = root({ "chart-tod-stacked": {} });
  await panel._renderTabGalleries("tod");
  assert.deepEqual(calls, ["tod-gallery"]);
});

it("a shell selection cannot start a primary or a gallery", () => {
  const calls = [];
  const panel = panelWith({
    shadowRoot: root(), _activeTab: "glance", _loading: false,
    _renderHero: async () => { calls.push("hero"); },
    _renderTabGalleries: async () => { calls.push("gallery"); },
  });
  panel._selectPanelTab("usage", { galleries: false });
  assert.deepEqual(calls, []);
  assert.equal(panel._renderedTabs.has("analytics"), false);
});


it("paints a selected tab before starting its first-visit gallery", () => {
  const frames = [];
  const oldRequestAnimationFrame = globalThis.requestAnimationFrame;
  globalThis.requestAnimationFrame = (callback) => {
    frames.push(callback);
    return frames.length;
  };
  const calls = [];
  const billingButton = {
    dataset: { tab: "billing" }, attributes: {},
    setAttribute(name, value) { this.attributes[name] = value; },
  };
  const glanceButton = {
    dataset: { tab: "glance" }, attributes: {},
    setAttribute(name, value) { this.attributes[name] = value; },
  };
  const billingPanel = { dataset: { tab: "billing" }, hidden: true };
  const glancePanel = { dataset: { tab: "glance" }, hidden: false };
  const panel = panelWith({
    _activeTab: "glance", _renderedTabs: new Set(), _loading: false,
    shadowRoot: {
      getElementById: (id) => id === "panel-billing" ? billingPanel : null,
      querySelector: () => null,
      querySelectorAll: (selector) =>
        selector === ".section-tabs [role=tab]"
          ? [glanceButton, billingButton]
          : selector === ".tab-panel" ? [glancePanel, billingPanel] : [],
    },
    _attachRangeBar() {},
    _resizeChartsUnder() { calls.push("resize"); },
    _renderTabGalleries(tab) { calls.push(`gallery:${tab}`); },
  });
  const runFrame = () => {
    for (const callback of frames.splice(0)) callback();
  };
  try {
    panel._selectPanelTab("billing");
    assert.equal(panel._activeTab, "billing");
    assert.equal(billingButton.attributes["aria-selected"], "true");
    assert.equal(billingPanel.hidden, false);
    assert.deepEqual(calls, []);
    runFrame();
    assert.deepEqual(calls, []);
    runFrame();
    assert.deepEqual(calls, ["resize", "gallery:billing"]);
    assert.equal(panel._renderedTabs.has("billing"), true);
  } finally {
    globalThis.requestAnimationFrame = oldRequestAnimationFrame;
  }
});

it("does not scroll the phone landing section over the tab controls", () => {
  const oldWindow = globalThis.window;
  let scrolls = 0;
  globalThis.window = { matchMedia: () => ({ matches: true }) };
  const panel = panelWith({
    _landingApplied: false, _accounts: [{}], _defaultSection: "glance",
    shadowRoot: { querySelector: () => ({ scrollIntoView: () => { scrolls += 1; } }) },
  });
  try {
    panel._scheduleDefaultLandingScroll();
    assert.equal(panel._landingApplied, true);
    assert.equal(scrolls, 0);
  } finally {
    if (oldWindow === undefined) delete globalThis.window;
    else globalThis.window = oldWindow;
  }
});

it("disconnect invalidates deferred work and releases lazy records", () => {
  let disconnected = 0;
  const panel = panelWith({
    _pendingMounts: new Map([["old", {}]]), _chartFactories: new Map([["old", {}]]),
    _lazyObserver: { disconnect() { disconnected += 1; } },
  });
  panel.disconnectedCallback();
  assert.equal(panel._galleryRenderGen, 2);
  assert.equal(panel._primaryReady, false);
  assert.equal(disconnected, 1);
  assert.equal(panel._pendingMounts.size, 0);
  assert.equal(panel._chartFactories.size, 0);
});
