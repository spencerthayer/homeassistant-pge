import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { containAxisLabels } from "../../custom_components/pge_energy/frontend/charts.js";

describe("containAxisLabels", () => {
  it("sets containLabel on one grid and on every grid", () => {
    const single = containAxisLabels({ grid: { left: 8 } });
    assert.equal(single.grid.containLabel, true);
    assert.equal(single.grid.left, 8);
    const grids = [{ left: 1 }, { left: 2, containLabel: false }];
    const dual = containAxisLabels({ grid: grids });
    assert.deepEqual(
      dual.grid.map((grid) => grid.containLabel),
      [true, true],
    );
  });

  it("leaves an option without a grid unchanged and does not mutate the input", () => {
    const bare = { series: [] };
    assert.equal(containAxisLabels(bare), bare);
    const grid = { left: 4, containLabel: false };
    const input = { grid };
    const out = containAxisLabels(input);
    assert.equal(out.grid.containLabel, true);
    assert.equal(grid.containLabel, false);
    assert.notEqual(out, input);
    assert.notEqual(out.grid, grid);
  });
});
