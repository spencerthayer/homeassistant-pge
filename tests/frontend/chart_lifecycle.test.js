import assert from "node:assert/strict";
import { it } from "node:test";
import { runGalleryFactory } from "../../custom_components/pge_energy/frontend/chart-gallery.js";

it("destroys a chart that finishes after an account switch", async () => {
  let finish;
  let destroyed = 0;
  const host = { isConnected: true };
  const panel = {
    _activeEntryId: "a",
    _galleryRenderGen: 1,
    _chartFactories: new Map(),
    shadowRoot: { getElementById: () => host },
  };
  const record = {
    id: "chart-test",
    sourceHost: host,
    stamp: { entryId: "a", gen: 1 },
    factory: () => new Promise((resolve) => { finish = resolve; }),
  };
  panel._chartFactories.set(record.id, record);
  const pending = runGalleryFactory(panel, record, host);
  panel._activeEntryId = "b";
  finish({ destroy() { destroyed += 1; } });
  assert.equal(await pending, null);
  assert.equal(destroyed, 1);
});
