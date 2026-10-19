import assert from "node:assert/strict";
import { it } from "node:test";
import {
  baseloadHeadline,
  billChangeHeadline,
  cycleRaceHeadline,
  paretoHeadline,
  peakHourHeadline,
  periodHeadline,
  storySummary,
  weatherHeadline,
  yesterdayHeadline,
} from "../../custom_components/pge_energy/frontend/chart-series.js";

it("headlines need coverage and keep zero distinct from missing", () => {
  assert.equal(yesterdayHeadline({ kwh: 68.64, avg7: 60.1 }), null);
  assert.equal(
    yesterdayHeadline({ kwh: 68.64, avg7: 60.1, complete: true }).text,
    "Yesterday you used 68.6 kWh, 14% more than your usual day.",
  );
  assert.equal(yesterdayHeadline({ kwh: 61, avg7: 60.1, complete: true }).text,
    "Yesterday you used 61.0 kWh, about the same as your usual day.");
  assert.equal(yesterdayHeadline({ kwh: 0, avg7: 10, complete: true }).tone, "good");
  assert.equal(peakHourHeadline([0, 0, 0, 0, 0, 0, 0, 0, 4]).text, "On weekdays your usage peaks around 8 AM.");
  assert.equal(
    cycleRaceHeadline({ openKwh: 410, lastKwhSameDay: 366, day: 8 }).text,
    "Your energy use is 12% ahead of the last statement at day 8.",
  );
  assert.equal(cycleRaceHeadline({ openKwh: null, lastKwhSameDay: 10, day: 2 }), null);
  assert.equal(
    baseloadHeadline({ floorKwh: 0.9, centsPerKwh: 18.4 }).text,
    "About 0.9 kWh runs every hour, even overnight. That is roughly $119 a month at PGE's estimated rate.",
  );
  assert.equal(
    weatherHeadline({ colderCents: 1, hotterCents: 7 }).text,
    "Hot days cost you more than cold ones: about 7¢ per extra degree versus 1¢.",
  );
  assert.equal(
    paretoHeadline({ count: 5, share: 34 }).text,
    "Your 5 most expensive hours make up 34% of the estimated cost.",
  );
  assert.equal(
    billChangeHeadline({ delta: 86, driver: "usage" }).text,
    "This bill rose $86, mostly from using more energy.",
  );
  assert.equal(
    periodHeadline({ onPeakShare: 20.16 }).text,
    "About 20% of your imported energy lands in on-peak hours.",
  );
  assert.deepEqual(storySummary(), []);
  assert.equal(
    storySummary({ estimate: { low: 212, high: 260 } })[0].text,
    "PGE estimates your next bill between $212 and $260.",
  );
});
