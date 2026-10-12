import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { chartLayoutPatch, containAxisLabels, formatCategoryAxis, responsiveChartHeight, waterfallBarLabel, waterfallNegativeLabelGap } from "../../custom_components/pge_energy/frontend/charts.js";

describe("responsiveChartHeight", () => {
  it("grows a narrow chart and leaves a wide chart at its base", () => {
    assert.equal(responsiveChartHeight(300, 390), Math.min(Math.round(300 * 1.3), 420));
    assert.ok(responsiveChartHeight(300, 390) > 300);
    assert.equal(responsiveChartHeight(300, 600), Math.min(Math.round(300 * 1.15), 440));
    assert.equal(responsiveChartHeight(380, 1000), 380);
    assert.equal(responsiveChartHeight(400, 390), 420);
  });
});

describe("waterfallBarLabel", () => {
  it("puts positives above the bar and signed currency only on negatives", () => {
    const up = waterfallBarLabel(212.28, { unit: "$", textColor: "#111" });
    assert.equal(up.position, "top");
    assert.equal(up.color, "#111");
    assert.equal(up.text, "$212.28");
    assert.equal(up.text.includes("+"), false);
    const down = waterfallBarLabel(-9.97, { unit: "$", textColor: "#111" });
    assert.equal(down.position, "bottom");
    assert.equal(down.text, "−$9.97");
  });

  it("adds axis-label margin room only when a step is negative", () => {
    assert.equal(waterfallNegativeLabelGap([{ value: 10 }, { value: 5 }]), 0);
    assert.equal(waterfallNegativeLabelGap([{ value: 298.14 }, { value: -212.28 }]), 16);
  });
});

describe("formatCategoryAxis", () => {
  it("renders statement dates as month and year and ribbon hours as weekday and hour", () => {
    assert.equal(formatCategoryAxis("2023-09-06"), "Sep '23");
    assert.equal(formatCategoryAxis("2026-10-18 21:00"), "Sun 9 PM");
    assert.equal(formatCategoryAxis("kWh"), "kWh");
  });
});

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

describe("chartLayoutPatch", () => {
  const option = {
    legend: { show: true, data: ["kWh", "On-peak"], textStyle: { color: "#111" } },
    grid: { left: 56, right: 88, top: 40, bottom: 56 },
    yAxis: [
      { type: "value", name: "kWh" },
      { type: "value", name: "°F", offset: 52 },
    ],
    xAxis: { type: "category", axisLabel: { rotate: 35 } },
  };

  it("keeps a short narrow legend plain and hides extra y-axes", () => {
    const patch = chartLayoutPatch(option, 390);
    assert.equal(patch.legend.type, "plain");
    assert.equal(patch.legend.formatter("On-peak"), "On\u2011peak");
    assert.equal(patch.yAxis[0].name, "kWh");
    assert.equal(patch.yAxis[0].nameRotate, 90);
    assert.equal(patch.yAxis[0].nameGap, 52);
    assert.equal(patch.yAxis[1].name, "");
    assert.equal(patch.yAxis[1].axisLabel.show, false);
    assert.equal(patch.yAxis[1].axisLine.show, false);
    assert.ok(patch.yAxis[1].offset < 52);
    assert.ok(patch.grid.right < 88);
    assert.equal(patch.grid.containLabel, true);
    assert.equal(option.yAxis[0].name, "kWh");
  });

  it("scrolls a compact legend only when it has more than four items", () => {
    const many = {
      ...option,
      legend: { ...option.legend, data: ["a", "b", "c", "d", "e", "f"] },
    };
    assert.equal(chartLayoutPatch(many, 700).legend.type, "scroll");
    assert.equal(chartLayoutPatch(option, 700).legend.type, "plain");
  });

  it("leaves a wide chart legend unscrolling and keeps axis names", () => {
    const patch = chartLayoutPatch(option, 1400);
    assert.equal(patch.legend.type, "plain");
    assert.equal(patch.yAxis[0].name, "kWh");
    assert.equal(patch.yAxis[0].nameRotate, 90);
    assert.equal(patch.yAxis[0].nameGap, 40);
    assert.equal(typeof patch.xAxis.axisLabel.formatter, "function");
    assert.equal(patch.xAxis.axisLabel.formatter("2023-09-06"), "Sep '23");
    assert.equal(patch.grid.right, 88);
  });

  it("keeps a phone calendar horizontal and shrinks the zoom slider", () => {
    const patch = chartLayoutPatch(
      {
        visualMap: { itemWidth: 10, itemHeight: 140, textStyle: {} },
        calendar: { left: 28, cellSize: ["auto", 11], dayLabel: { fontSize: 9 }, monthLabel: { fontSize: 10 } },
        dataZoom: [{ type: "slider", height: 18, bottom: 8 }],
      },
      320,
    );
    assert.ok(patch.visualMap.itemHeight < 140);
    assert.notEqual(patch.calendar.orient, "vertical");
    assert.deepEqual(patch.calendar.cellSize, ["auto", 11]);
    assert.equal(patch.calendar.monthLabel.show, true);
    assert.equal(patch.dataZoom[0].height, 12);
  });

  it("formats category dates and leaves time-axis formatters alone", () => {
    const time = chartLayoutPatch(
      { xAxis: { type: "time", axisLabel: { formatter: "{MMM}" } } },
      390,
    );
    assert.equal(time.xAxis.axisLabel.formatter, "{MMM}");
    const bare = chartLayoutPatch({ xAxis: { type: "time" } }, 390);
    assert.equal(bare.xAxis.axisLabel.formatter, undefined);
    const millis = chartLayoutPatch({ xAxis: { type: "time" } }, 1200);
    assert.notEqual(millis.xAxis.axisLabel.formatter, formatCategoryAxis);
  });
});
