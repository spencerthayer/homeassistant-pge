import assert from "node:assert/strict";
import { it } from "node:test";
import { fetchStatisticSeries, invalidateStatsCache } from "../../custom_components/pge_energy/frontend/data.js";
import { renderBillingCharts, renderInsights, renderWeatherMoney } from "../../custom_components/pge_energy/frontend/chart-gallery.js";

function deferred() {
  let resolve;
  const promise = new Promise((finish) => { resolve = finish; });
  return { promise, resolve };
}

function seriesResponse(id, value) {
  return {
    [id]: [{ start: "2026-01-01T00:00:00Z", sum: value, change: value, mean: value, state: value }],
  };
}

it("shares an identical pending statistics request and caches its result", async () => {
  const response = deferred();
  let calls = 0;
  const hass = { callWS: () => { calls += 1; return response.promise; } };
  const options = {
    start: new Date("2026-01-01T00:00:00Z"),
    end: new Date("2026-01-02T00:00:00Z"),
    period: "day",
  };
  const first = fetchStatisticSeries(hass, "test.cache.concurrent", options);
  const second = fetchStatisticSeries(hass, "test.cache.concurrent", options);
  assert.equal(calls, 1);
  response.resolve(seriesResponse("test.cache.concurrent", 12));
  const [a, b] = await Promise.all([first, second]);
  assert.strictEqual(a, b);
  assert.equal((await fetchStatisticSeries(hass, "test.cache.concurrent", options)).values[0], 12);
  assert.equal(calls, 1);
});

it("does not repopulate a cleared cache from an older in-flight request", async () => {
  const responses = [deferred(), deferred()];
  let calls = 0;
  const hass = { callWS: () => responses[calls++].promise };
  const options = {
    start: new Date("2026-02-01T00:00:00Z"),
    end: new Date("2026-02-02T00:00:00Z"),
    period: "day",
  };
  const oldRequest = fetchStatisticSeries(hass, "test.cache.generation", options);
  invalidateStatsCache();
  responses[0].resolve(seriesResponse("test.cache.generation", 1));
  await oldRequest;
  const freshRequest = fetchStatisticSeries(hass, "test.cache.generation", options);
  assert.equal(calls, 2);
  responses[1].resolve(seriesResponse("test.cache.generation", 2));
  assert.equal((await freshRequest).values[0], 2);
  assert.equal((await fetchStatisticSeries(hass, "test.cache.generation", options)).values[0], 2);
  assert.equal(calls, 2);
});

it("keeps statement-history recorder requests out of the Analytics chart load", async () => {
  const calls = [];
  const roles = ["consumption", "cost", "temperature", "ytd_program_savings", "bill_amount", "bill_kwh", "account_balance", "amount_due"];
  const panel = {
    _activeEntryId: "entry",
    _galleryRenderGen: 1,
    _tabRenderContext: { tab: "analytics", token: 1, cancelled: false },
    _account: { statistic_ids: Object.fromEntries(roles.map((role) => [role, `pge:${role}`])) },
    _hass: {
      callWS: async (message) => {
        const id = message.statistic_ids[0];
        calls.push({ id, period: message.period, start: message.start_time });
        return { [id]: [] };
      },
    },
    _charts: [],
    shadowRoot: { getElementById: () => null },
  };
  await renderWeatherMoney(panel, { degreeDayPoint: () => null, tempBins: () => [] });
  assert.ok(calls.length > 0);
  assert.ok(calls.every((call) => call.period === "day"));
  assert.ok(calls.every((call) => call.id !== "pge:bill_amount" && call.id !== "pge:bill_kwh"));

  calls.length = 0;
  panel._galleryDays = [];
  await renderBillingCharts(panel, {
    billVsImported: () => [],
    statementGap: () => [],
    statementWindows: () => [],
  });
  assert.ok(calls.some((call) => call.id === "pge:bill_amount" && call.period === "hour"));
  assert.ok(calls.some((call) => call.id === "pge:bill_kwh" && call.period === "hour"));
});

it("limits Analytics hourly history to one year and leaves bill history lazy", async () => {
  const calls = [];
  const panel = {
    _activeEntryId: "entry",
    _galleryRenderGen: 1,
    _tabRenderContext: { tab: "analytics", token: 2, cancelled: false },
    _galleryDays: [],
    _account: { statistic_ids: { consumption: "pge:consumption" } },
    _hass: {
      callWS: async (message) => {
        calls.push({
          id: message.statistic_ids[0],
          period: message.period,
          start: Date.parse(message.start_time),
          end: Date.parse(message.end_time),
        });
        return { "pge:consumption": [] };
      },
    },
    shadowRoot: { getElementById: () => null },
  };
  await renderInsights(panel, {
    weatherModel: () => null,
    counterfactual: () => null,
    centsPerKwh: () => [],
    degreePrice: () => null,
    daypartDays: () => [],
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].id, "pge:consumption");
  assert.equal(calls[0].period, "hour");
  assert.ok(calls[0].end - calls[0].start <= 367 * 24 * 60 * 60 * 1000);
});
