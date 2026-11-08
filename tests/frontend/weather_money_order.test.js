import assert from "node:assert/strict";
import { it } from "node:test";
import { renderWeatherMoney } from "../../custom_components/pge_energy/frontend/chart-gallery.js";

it("weather charts mount from daily statistics without billing-series reads", async () => {
  const makeHost = () => {
    const attrs = new Map();
    const classes = new Set();
    return {
      attrs,
      classes,
      isConnected: true,
      classList: {
        add: (name) => classes.add(name),
        remove: (name) => classes.delete(name),
      },
      setAttribute: (name, value) => attrs.set(name, value),
      removeAttribute: (name) => attrs.delete(name),
      closest: (selector) => selector === "figure" ? { removeAttribute() {}, setAttribute() {} } : null,
    };
  };
  const hosts = {
    "chart-degree-days": makeHost(),
    "chart-temp-bins": makeHost(),
    "chart-program-savings": makeHost(),
  };
  const periods = [];
  const statisticIds = [];
  const mounted = [];
  const panel = {
    _activeEntryId: "a",
    _galleryRenderGen: 1,
    _fetchCache: new Map(),
    _chartFactories: new Map(),
    _pendingMounts: new Map(),
    _charts: [],
    _lazyObserver: null,
    _mountDeferred: async (record) => mounted.push(record.id),
    _account: {
      statistic_ids: {
        consumption: "c", cost: "k", temperature: "t", bill_amount: "b",
        bill_kwh: "bk", ytd_program_savings: "s", account_balance: "ab", amount_due: "ad",
      },
    },
    _hass: {
      callWS: (msg) => {
        periods.push(msg.period);
        statisticIds.push(...msg.statistic_ids);
        return Promise.resolve({});
      },
    },
    shadowRoot: { getElementById: (id) => hosts[id] ?? null, querySelectorAll: () => [] },
  };
  const fns = { degreeDayPoint: () => null, tempBins: () => [] };
  await renderWeatherMoney(panel, fns);

  assert.ok(periods.length > 0);
  assert.ok(periods.every((period) => period === "day"));
  assert.deepEqual([...new Set(statisticIds)].sort(), ["c", "k", "s", "t"]);
  assert.deepEqual(mounted, ["chart-degree-days", "chart-temp-bins", "chart-program-savings"]);
  for (const host of Object.values(hosts)) {
    assert.ok(host.classes.has("chart-skeleton"));
    assert.equal(host.attrs.get("aria-busy"), "true");
  }
});
