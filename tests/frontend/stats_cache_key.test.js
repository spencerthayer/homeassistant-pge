/**
 * A full-resolution statistics read must not reuse a downsampled cache entry.
 */
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { fetchStatisticSeries, invalidateStatsCache } from "../../custom_components/pge_energy/frontend/data.js";

function hourlyRows(count) {
  const rows = [];
  for (let i = 0; i < count; i++) {
    rows.push({
      start: Date.parse("2024-06-01T00:00:00.000Z") + i * 3600_000,
      sum: i + 1,
      change: 1,
      mean: 60,
      state: i,
    });
  }
  return rows;
}

describe("fetchStatisticSeries cache key", () => {
  it("keeps a later full fetch at full length after a downsampled fetch", async () => {
    invalidateStatsCache();
    const hass = {
      async callWS() {
        return { "pge_energy:acct_consumption": hourlyRows(5) };
      },
    };
    const start = "2024-06-01T00:00:00.000Z";
    const end = "2024-06-02T00:00:00.000Z";
    const downsampled = await fetchStatisticSeries(hass, "pge_energy:acct_consumption", {
      start,
      end,
      period: "hour",
      maxPoints: 3,
    });
    const full = await fetchStatisticSeries(hass, "pge_energy:acct_consumption", {
      start,
      end,
      period: "hour",
      maxPoints: 100,
    });
    assert.equal(downsampled.xs.length, 3);
    assert.equal(full.xs.length, 5);
  });
});
