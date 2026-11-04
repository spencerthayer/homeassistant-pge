import assert from "node:assert/strict";
import { it } from "node:test";

it("ECharts starts while hero recorder reads are pending", async () => {
  globalThis.HTMLElement ??= class {};
  let Panel;
  globalThis.customElements = {
    get: () => undefined,
    define: (_name, cls) => { Panel = cls; },
  };
  await import("../../custom_components/pge_energy/frontend/pge-panel.js");
  const calls = [];
  globalThis.window = {};
  globalThis.document = {
    createElement: () => ({}),
    head: {
      appendChild(script) {
        assert.equal(script.src, "/pge_energy_frontend/vendor/echarts.min.js");
        calls.push("echarts");
        window.echarts = {};
        script.onload();
      },
    },
  };
  let finish;
  const gate = new Promise((resolve) => { finish = resolve; });
  const panel = Object.assign(Object.create(Panel.prototype), {
    _accounts: [{ entry_id: "a", statistic_ids: {} }], _activeEntryId: "a",
    _activeTab: "glance", _galleryRenderGen: 1,
    _basePresetRange: () => ({
      start: new Date("2026-11-01T07:00:00Z"),
      end: new Date("2026-11-02T08:00:00Z"),
    }),
    _fetchUsageSeries: () => { calls.push("recorder"); return gate; },
    _paintUsageCombo: async () => true, _setOverviewUsageTitle() {},
  });
  const done = panel._renderHero();
  try {
    assert.deepEqual(calls, ["echarts", "recorder"]);
  } finally {
    finish({});
    await done;
  }
});
