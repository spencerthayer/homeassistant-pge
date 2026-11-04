import assert from "node:assert/strict";
import { it } from "node:test";
import { renderWeatherMoney } from "../../custom_components/pge_energy/frontend/chart-gallery.js";

it("degree days mount before the hourly statement history resolves", async () => {
  const host = () => ({ isConnected: true, classList: { add() {}, remove() {} }, closest: () => null });
  const hosts = { "chart-degree-days": host(), "chart-temp-bins": host() };
  const pending = [];
  const periods = [];
  const panel = {
    _activeEntryId: "a",
    _galleryRenderGen: 1,
    _lazyObserver: { observe() {} },
    _account: {
      statistic_ids: {
        consumption: "c", cost: "k", temperature: "t", bill_amount: "b",
        bill_kwh: "bk", ytd_program_savings: "s", account_balance: "ab", amount_due: "ad",
      },
    },
    _hass: {
      callWS: (msg) => {
        periods.push(msg.period);
        return msg.period === "day"
          ? Promise.resolve({})
          : new Promise((resolve) => pending.push(resolve));
      },
    },
    shadowRoot: { getElementById: (id) => hosts[id] ?? null, querySelectorAll: () => [] },
  };
  const fns = {
    degreeDayPoint: () => null, tempBins: () => [], statementWindows: () => [],
    statementGap: () => [], billVsImported: () => [],
  };
  const done = renderWeatherMoney(panel, fns);
  await new Promise((resolve) => setImmediate(resolve));
  assert.ok(panel._chartFactories?.has("chart-degree-days"));
  assert.ok(panel._chartFactories?.has("chart-temp-bins"));
  assert.ok(periods.includes("day"));
  assert.ok(periods.includes("hour"));
  assert.ok(periods.indexOf("hour") > periods.lastIndexOf("day"));
  for (const resolve of pending) resolve({});
  await done;
});
