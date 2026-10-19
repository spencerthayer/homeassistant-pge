# `/pge` panel design review (2026-10-18)

Build under test: `0.13.3` frontend (`?v=0.13.3`), plus the uncommitted `custom_components/pge_energy/frontend/pge-panel.js` change on `dev`.
Browser: Ego Lite, live HA at `http://127.0.0.1:8123`, light theme, logged in as the local dev owner.
Method: each tab was opened at each window width from `.agents/rules/responsive-viewports.mdc`. The page was scrolled to the bottom to trigger lazy charts, then captured as a full-page screenshot. DOM measurements came from the panel shadow root and are used only to name selectors and sizes. Every finding below was first seen in a screenshot.

Screenshots: `qa-screenshots/design-review-2026-10-18/` (gitignored). File names follow `<tab>-<window>.png`. Close-up crops are named `issue-*.png`.

## Verdict: FAIL

| | Count |
| --- | --- |
| Major (content cut off, unreadable, or blocked) | 19 |
| Minor (spacing, clutter, consistency) | 39 |

The user-reported symptoms come from a small number of shared causes:

1. **Charts shrink when they get narrower.** `responsiveChartHeight()` in `charts.js` makes every chart shorter on phones (G1). Narrow charts lose both width and height.
2. **Chapters and gallery sections have no CSS.** `section.chapter`, `.chapter-head`, and `.explore-more` have no rules at all (measured margin 0, padding 0). Sections collide with the content above them (G8).
3. **Everything sits in one card per tab.** `#hero`, `#billing`, and `#tod` are each one `.card` 2,400 to 3,700 px tall, so a tab has no visual breaks (G10).
4. **Chart chrome repeats itself.** Each figure has an eyebrow, a title, a `?` hint, a ▶ ⓘ disclosure, and ⤢. Some chapters repeat the figure title (G7, G9).
5. **Phone header is too tall.** The sticky header covers 34% of a phone screen (G4).

## Measured layout

| Window | `.content` width | `#kpis` columns | Sticky `.pge-header` height | Usage combo chart |
| --- | --- | --- | --- | --- |
| 390 | 390 | 2 | 234 px (+56 px `.toolbar`) | 344 × 274 |
| 780 | 780 | 2 | 150 px | 724 × ~300 |
| 960 | 704 (sidebar open) | 2 | 150 px | not measured |
| 1100 | 844 | 2 | 150 px | not measured |
| 1280 | 1024 | 4 | 150 px | 958 × 380 |
| 1500 | 1244 | 4 | 150 px | not measured |
| 1680 | 1424 | 4 | 150 px | not measured |

Gallery chart hosts measured **344 × 200** at 390 and **958 × 240** at 1280. Phones get the shortest charts.

---

## G. Global issues (fix once, every tab improves)

### G1. Charts get shorter as they get narrower. **Major**

- **Where:** `charts.js` `responsiveChartHeight()` (lines 246 to 251). In `pge-panel.js`, `.chart-host.usage-combo` and `.chart-host.scatter-wide` min-heights step down in `@container pge (max-width: 1100px)`, `(max-width: 820px)`, `@media (max-width: 900px)`, and `@media (max-width: 640px)`.
- **What:** At ≤ 420 px the height is `base × 0.72` (floor 200). At ≤ 720 px it is `base × 0.82`. Every gallery chart is 200 px tall at 390. `#chart-overview-usage` and `#chart-usage` drop from 380 to 274. Plots with three y-axes get about 190 × 160 px of plotting area.
- **Fix:** Invert the scale. Narrow charts need *more* height, because the x-axis is compressed.

```js
/** Narrow cards get taller charts so the plot keeps a usable aspect ratio. */
function responsiveChartHeight(base, hostWidth) {
  // Keep the window fallback: the host is often 0 px wide on first paint.
  const w = hostWidth || window.innerWidth || base;
  if (w <= 420) return Math.min(Math.round(base * 1.3), 440);
  if (w <= 720) return Math.min(Math.round(base * 1.15), 440);
  return base;
}
```

  Then delete the step-down min-heights in `pge-panel.js` (the `.chart-host.usage-combo` and `.chart-host.scatter-wide` lines in the 1100, 820, 900, and 640 blocks). The inline height from `mount()` takes over.

### G2. Combo chart has three y-axes in a phone-width card. **Major**

- **Where:** `createUsageComboChart` (`charts.js`) via `chartLayoutPatch()`. Applies to `#chart-overview-usage` and `#chart-usage`.
- **What:** At 390 the kWh, $, and °F axes leave the plot about 55% of the card width. The legend shows six items, paged `1/2`. The blue "kWh" legend swatch matches no visible mark, because the bars use Time of Day colors.
- **Fix:** In `chartLayoutPatch()` when `narrow`, set `axisLabel.show: false` and `axisLine.show: false` on every y-axis after index 0. The tooltip already shows $ and °F. Drop the "kWh" legend entry when the bars use Time of Day colors. Remove `type: "scroll"` for ≤ 4 items.

### G3. Legend sits on top of the y-axis name. Minor (many charts)

- **Where:** `chartLayoutPatch()` sets `grid.top` to 36 when a legend exists. ECharts draws `yAxis.name` above the grid, on the legend row.
- **Seen in:** `#chart-overview-usage` and `#chart-usage` ("kWh" over "Import cost"), `#chart-typical-day` ("Weekday" over "kWh"), `#chart-degree-days` ("kWh or degree days"), `#chart-period-mix` ("Off-peak" over "Share"), `#chart-statement-portal`, `#chart-balance-due`, `#chart-bill-anatomy` (legend over "Dollars"), and `#ledger-kwh` ("Bill kWh" twice).
- **Fix:** Rotate y-axis names into the left gutter:

```js
// in chartLayoutPatch(), nextAxes map
nameLocation: "middle",
nameRotate: 90,
nameGap: narrow ? 30 : 40,
```

### G4. Sticky header covers a third of a phone screen. **Major**

- **Where:** `.pge-header` (sticky, `top: 0`) holds `.section-tabs` and `.hdr-range.filters`.
- **What:** At 390, `.hdr-range` is 164 px tall. It stacks four rows: presets `.seg`, `.stepper`, Hour/Day/Month `.seg`, and a lone `Custom` `.ghost`. With the tabs, the header is 234 px. Add the 56 px `.toolbar` and 290 of 844 px are chrome before any content. On load, `_scheduleDefaultLandingScroll()` scrolls `#kpis` to the top, so `#story` sits hidden under the header (`issue-header-390.png`).
- **Fix:**
  1. Keep only the tab row sticky below 640 px. `.hdr-range` is already static; its sticky parent pins it, so `position: static` on it does nothing. Dissolve the parent instead, which needs no DOM move:
     ```css
     @container pge (max-width: 640px) {
       .pge-header { display: contents; }
       .section-tabs {
         position: sticky; top: 0; z-index: 3;
         background: color-mix(in srgb, var(--primary-background-color) 88%, transparent);
         backdrop-filter: saturate(1.4) blur(8px);
       }
     }
     ```
  2. Put `.stepper` (flex: 1), the Hour/Day/Month `.seg`, and `Custom` on one row. Turn `Custom` into a 34 px icon button (`mdi:calendar-range`) with an `aria-label`.
  3. Change `.hdr-range.filters { margin: 20px 0px; }` to `margin: 8px 0 12px;`. The 20 px top and bottom margin is a large part of the gap above `#story`.
  4. Add `scroll-margin-top: calc(var(--pge-header-h, 150px) + 8px)` to the landing anchors (`#kpis`, `#hero`, `#insights-weather`, `#tod`, `#billing`).

### G5. Programs tab is cut off on phones. **Major**

- **Where:** `.section-tab-scroll` and `.sync-pill-wrap` in `.hdr-row`.
- **What:** At 390, `.section-tab-scroll` is 260 px wide. Six 48 px icon tabs need 288 px, so the Programs icon is half hidden under the `Synced` pill (tab right edge 310 px, scroller right edge 286 px). The hidden scrollbar gives no hint to swipe. Labels also stay hidden up to 820 px card width. At 780 there is 646 px of free tab width, enough for all six labels.
- **Fix:**
  1. Keep `.sync-pill-wrap` at the right of the tabs (AGENTS.md). Below 560 px card width, shrink it to a 28 px status dot with the status text kept for screen readers. Six tabs plus the dot fit in the 338 px row. (`.toolbar` is not sticky, so moving the pill there would hide sync state while scrolling.)
  2. Change the icon-only breakpoint from `@container pge (max-width: 820px)` to `max-width: 560px`.

### G6. "More…" range menu is off-screen on phones. **Major**

- **Where:** `.hdr-range .seg select.range-more` (x = 360 to 451 inside a 338 px `.seg`) and `#tod-range-more` (right edge 448 px).
- **What:** `.seg` uses `overflow-x: auto; scrollbar-width: none`, so the 6h/12h/3mo/6mo/12mo/YTD presets are unreachable without guessing that the pill scrolls.
- **Fix:** Below 640 px, take `select.range-more` out of `.seg` and render it as a `.ghost` control in the stepper row. Another option is `.seg { flex-wrap: wrap; border-radius: 16px; }` at that width.

### G7. Each chart header has five controls. Minor, but the main source of clutter

- **Where:** `figure.chart-card > .fig-head`: `.eyebrow`, `.fig-title`, `.hint` (`?`), `details.fig-info` (▶ ⓘ), and `button.fig-expand` (⤢). The markup is built at `pge-panel.js:3153`.
- **What:**
  - The ▶ is the native `<details>` marker on `details.fig-info > summary`. No rule hides it, unlike the other disclosures (`pge-panel.js:916-927`).
  - The `?` hint and ⓘ both open an explanation.
  - At 780 and 1280 the `?` wraps under ⓘ on its own line (see `analytics-780.png`, `billing-1280.png`).
  - The eyebrow repeats the title ("TEMPERATURE BINS" / "How temperature changes your daily use").
- **Fix:**
  ```css
  details.fig-info > summary { list-style: none; }
  details.fig-info > summary::-webkit-details-marker { display: none; }
  .fig-head .eyebrow { display: none; }   /* or delete it from the template */
  @container pge (max-width: 640px) { .fig-expand { min-width: 44px; min-height: 44px; } }
  ```
  Keep `.fig-expand` on phones: the expand dialog is the remedy for a small chart.
  Fold the `termHint` text into the `fig-info` body and stop rendering `this._hint(termHint)` inside `.fig-title`.

### G8. Chapters and "Explore more" have no styles. **Major** (spacing)

- **Where:** `section.chapter` (`pge-panel.js:3185`, `3242`, `3319`, `3388`), `header.chapter-head`, `h2.chapter-headline`, and `section.chapter.explore-more` (`pge-panel.js:1677`). None of these have rules. Measured `margin-top: 0px` and `padding: 0px`.
- **What:**
  - "When you use energy" starts directly under the `Total` row of `.usage-day-table` (`usage-1280.png`).
  - "Your Time of Day" starts directly under the Catalog table.
  - "Why this bill changed" starts directly under `#ledger-kwh`.
  - On Analytics, `section.chapter.explore-more` sits outside any `.card`. It is 370 px wide where cards are 344 px inside, so its charts run edge to edge with no surface. It looks unfinished at every width.
  - Figures inside a chapter have no vertical gap between them.
- **Fix:**
  ```css
  .chapter {
    margin-top: var(--pge-space-8);
    padding-top: var(--pge-space-6);
    border-top: 1px solid var(--pge-border);
  }
  .chapter-head { margin-bottom: var(--pge-space-4); }
  .chapter-head .eyebrow { display: inline-flex; align-items: center; gap: 6px; }
  .chapter-headline { font: var(--pge-text-headline); margin: 4px 0 0; }
  .chapter .chart-card + .chart-card,
  .chapter-views > * + * { margin-top: var(--pge-space-6); }
  section.chapter.explore-more { /* make it a real surface */ }
  ```
  For `explore-more`, add the `card` class in the template at `pge-panel.js:1677` (`class="card chapter explore-more"`) and drop the border-top for that case.

### G9. Duplicate and mismatched headings. Minor

- **Where:** `.chapter:has([data-chapter-headline]) .fig-title { display: none; }` (`pge-panel.js:1230`) hides a repeated figure title only when the chapter headline has `data-chapter-headline`. The billing chapters at `pge-panel.js:3321` and `3390` lack that attribute.
- **What:**
  - Billing shows "WHY THIS BILL CHANGED / Why this bill changed" twice in a row, and "What's in each bill" twice (`issue-billing-duplicate-heads-390.png`).
  - The Time of Day chapter is titled "Your most expensive hours" (`pge-panel.js:3244`), but its first block is the Load-shift simulator. The Pareto chart further down has the same title.
- **Fix:**
  - Add `data-chapter-headline` to both billing chapter `h2`s.
  - Rename the Time of Day chapter headline to match its content, for example "Shift your usage".

### G10. One card per tab, 2,400 to 3,700 px tall. Minor (main source of the "cluttered" look)

- **Where:** `#hero.card` (2,423 px at 390), `#billing.card` (3,544 px), and `#tod.card` (3,741 px).
- **What:** Summary tables, charts, disclosures, and chapters all share one white surface, so a tab has no rhythm.
- **Fix:** Close the parent `.card` before each `section.chapter` and give every chapter its own `.card`. For Billing, use three cards: "Balance & statement" (`.usage-summary-wrap`), "Statement details (PDF)", and "History" (ledger charts plus chapters). Use a `--pge-space-6` gap between cards (currently `margin-bottom: var(--pge-space-4)`).

### G11. Disclosure chevron reads as a stray bullet. Minor

- **Where:** `details.usage-accounting > summary::before` and its siblings (`pge-panel.js:928-941`). This covers "Range accounting", "Hourly breakdown", "Statement details (PDF)", "Catalog", and the Diagnostics summaries. `details.tod-holidays` and `details.tod-compare-math` use a different native ▾.
- **What:** A 0.85em `▸`/`▾` is absolutely positioned at `left: 4px; top: .55em`. It sits apart from the title and does not line up with the caption.
- **Fix:**
  ```css
  details.usage-accounting > summary, /* …same selector list… */ {
    display: grid; grid-template-columns: 20px 1fr; column-gap: 6px; padding: 10px 12px;
  }
  details.usage-accounting > summary::before /* … */ {
    position: static; content: "›"; font-size: 1.2rem; transition: transform var(--pge-dur-fast);
  }
  details.usage-accounting[open] > summary::before /* … */ { content: "›"; transform: rotate(90deg); }
  summary .rollup-caption { grid-column: 2; }
  ```
  Apply the same selector list to `details.tod-holidays` and `details.tod-compare-math` so every disclosure looks the same.

### G12. Raw ISO dates on category axes. Minor

- **Where:** `#chart-statement-portal`, `#chart-bill-imported`, and `#chart-bill-anatomy` show "2023-09-06". `#chart-forward-ribbon` shows "2026-10-18 21:00".
- **Fix:** Add an `axisLabel.formatter` that renders `Sep '23`. For the ribbon, render `Sat 9 PM`.

### G13. Spacing scale is tight overall. Minor

- **Where:** `.card { padding: var(--pge-space-4); margin-bottom: var(--pge-space-4); }`, `.kpi-grid { gap: 8px }`, `@media (max-width: 640px) .content { padding: 10px }`, and `.card { padding: 12px }`.
- **Fix:** Change the base card to `padding: var(--pge-space-6)` and `margin-bottom: var(--pge-space-6)`. Change `.kpi-grid` to `gap: var(--pge-space-3)`. On phones, keep `.content` at 12 px but give `.card` 16 px padding (the current 12 px with 10 px gutters is what makes phones feel cramped).

---

## O. Overview (`#panel-glance`)

| # | Selector | Width | Severity | Problem | Fix |
| --- | --- | --- | --- | --- | --- |
| O1 | `#chart-overview-usage.chart-host.usage-combo` | all | Minor | The chart is a direct child of `#panel-glance` with no `.card`, title, or surface. Its legend floats on the page background under a carded KPI block. | Wrap it in `<section class="card" id="overview-usage-card">` with the heading “Usage” plus the current range label. The header range drives this chart, so a fixed “Yesterday by hour” would be wrong. |
| O2 | `#kpis .kpi-grid` | 960, 1100 | **Major (rule)** | 2 columns. The viewport rule requires 4 at 960 and 1100. With the HA sidebar open, `#kpis` is 672 px and 812 px, below the 820 px container threshold. See R1. | Resolve R1 first. |
| O3 | `#kpis .kpi-grid` | 1680 | **Major (rule)** | 4 columns, not the 7 the rule requires. `#kpis` is about 1,390 px wide, under the 1,520 px threshold. | See R1. |
| O4 | `#kpis .kpi-grid` | 1280, 1500, 1680 | Minor | 14 tiles in 4 columns leave a last row of 2 tiles and 2 empty cells (`issue-kpi-orphans-1680.png`). The rule requires complete rows. | In the 4-column band from R1, `.kpi-grid > .kpi:nth-child(13), .kpi-grid > .kpi:nth-child(14) { grid-column: span 2; }`, reset to `auto` in the 7-column band. |
| O5 | `#kpis .kpi` | all | Minor | Rows have uneven heights. Tiles with sparklines (`Yesterday`, `Week`) are about 104 px and the rest about 68 px, so rows 1 and 2 are taller than rows 3 to 7. | `.kpi { display: grid; grid-template-rows: auto auto auto 1fr; min-height: 96px; }`. Pin the sparkline to the bottom (`align-self: end`). |
| O6 | `.kpi.kpi-usage`, `.kpi.kpi-statement`, `.kpi.kpi-estimate`, Last payment tile | all | Minor | Accent colors do not follow a rule. Blue marks kWh *and* "Usage cycle import cost" and "Since statement import cost". Orange marks "Statement cycle kWh". "Last payment" has no accent (`border-left-color: transparent`), so it looks misaligned. | Pick one key. Either color by unit (kWh = `--pge-series-kwh`, $ = `--pge-series-cost`) or by group. Give Last payment the same class as Amount due. |
| O7 | `#kpis .kpi .label` | 390, 780 | Minor | Uppercase 0.72rem labels wrap to two lines ("USAGE CYCLE IMPORT COST", "SINCE STATEMENT IMPORT KWH"). With a date line under each value, the grid reads as a wall of small caps. | Render the five groups (Yesterday, This week, Statement, Since statement, Account) as small group headings over each pair, and shorten tile labels to "Import" and "Cost". Use sentence case for `.kpi .label` (drop `text-transform: uppercase`). |
| O8 | `#story.card.story-band` | all | Minor | A whole card for one sentence. It repeats the "PGE est. next bill" tile. At 390 it is hidden under the sticky header on load (G4). | Remove the card chrome (`.story-band { background: none; border: 0; box-shadow: none; padding: 0 0 8px; }`) or move the sentence under the "At a glance" heading as a subtitle. |
| O9 | `#chart-overview-usage` dataZoom slider | all | Minor | A 24-bar day does not need zoom. At 390 the slider floats about 60 px below the axis, leaving a dead band. | Skip `dataZoom` when the series has 48 points or fewer. |

## U. Usage (`#panel-usage`, `#hero.card`)

| # | Selector | Width | Severity | Problem | Fix |
| --- | --- | --- | --- | --- | --- |
| U1 | `.usage-table-wrap .usage-day-table` | 390 | **Major** | The `@media (max-width: 640px)` rule sets `min-width: 520px` inside a 344 px wrapper. The Import cost column is clipped mid-value ("$0.0"), and $/kWh and Avg °F are off-screen with no scroll cue (`issue-usage-table-clipped-390.png`). | Below 640, remove `min-width: 520px`, keep `table-layout: fixed`, and hide `th:nth-child(4), td:nth-child(4), th:nth-child(5), td:nth-child(5)` ($/kWh and Avg °F are in Range accounting). |
| U2 | `#chart-usage` | 390 | **Major** | See G1 and G2. The plot is 274 px tall with three axes and a paged legend. | G1 and G2. |
| U3 | `#usage-stats .usage-summary-wrap` | 1100+ | Minor | Two columns of label/value pairs. Each value sits about 350 px right of its label at 1280. Odd-count sections leave an empty half-cell ("Avg import cost / hour", "Temp stdev", "Median hour flow"). There are about 30 rows. | `.usage-summary-items { grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); }` and `.usage-summary-wrap { max-width: 1100px; }`. Show "Totals & averages" open and put "Distribution" and "Extremes" behind their own disclosure. |
| U4 | `#hero .metric-toggle` | all | Minor | The kWh/Dollars toggle sits on its own row between the `h2` and the chart legend, adding a 30 px band. | Put it on the right side of the `Usage` heading row (`display: flex; justify-content: space-between`). |
| U5 | `section.chapter[data-chapter="when-you-use"] .chapter-views` chips | 390, 1280 | Minor | Eight view chips wrap to four rows at 390 and leave "Always-on power" alone at 1280. | Below 640, `.view-chips { flex-wrap: nowrap; overflow-x: auto; }` with a right-edge fade mask, or a `<select>`. |
| U6 | `section.chapter[data-chapter="when-you-use"]` | all | Minor | It starts under the table with no gap (G8). The eyebrow, headline "A typical weekday vs weekend", and figure eyebrow "TYPICAL DAY" are three heading layers for one chart. | G8 and G7. |
| U7 | `#chart-hour-weekday` | 390 | Minor | Pale blue sequential ramp with low contrast between adjacent cells. Cells are about 11 px. | Use a ramp with a darker end stop. Raise the height (G1). |

## A. Analytics (`#panel-analytics`)

| # | Selector | Width | Severity | Problem | Fix |
| --- | --- | --- | --- | --- | --- |
| A1 | `#insights-weather` message and `#scatter.chart-host.scatter-wide` | all | **Major** | It reads "Only 2 days in this range… Pick 7 days or longer". `_selectPanelTab()` hides `.hdr-range` on Analytics, so the user cannot act on it here. `#scatter` renders as a 14 to 28 px empty strip. The three charts below plot four years of history, which contradicts the message. | Decided 2026-10-18: fetch the scatter's `kwhDay` and `tempDay` with the 12mo window Cost intelligence already uses (`rangePresets()["12mo"]`), not `_resolveChartRange()`. Hide `#scatter` when empty instead of leaving the strip. |
| A2 | `#insights-heat.card.grid-2` | 1500, 1680 | **Major** | `.grid-2` turns the card into a 2-column grid once `.content` is over 1,100 px. The five children (`#heatmap-chips`, `h4`, `#heatmap-kwh`, `h4`, `#heatmap-temp`) flow into alternate columns. "kWh calendar" and "Temperature calendar" land in the right column, both heatmaps are in the left half, and the right half is empty. | Remove `grid-2` from `#insights-heat`. To get two side-by-side calendars, wrap each `h4` and heatmap pair in its own `<div>`. |
| A3 | `#heatmap-kwh`, `#heatmap-temp` | 390 | **Major** | Narrow patch sets `cellSize: ["auto", 8]` and 8 px day labels. The "S M T W T F S" labels collapse into an unreadable stack, and cells are about 6 × 8 px (`issue-heatmap-390.png`). | When the card is narrower than 720 px, mount the heatmap at a fixed 720 px width (`mount(..., { width: 720 })`) inside an `overflow-x: auto` wrapper scrolled to the newest days. A vertical calendar would make each phone chart about 2,000 px tall. |
| A4 | `#heatmap-kwh`, `#heatmap-temp` with the "12 months" chip | all | Minor | One calendar row per calendar year, so a trailing 12 months draws two years that are each about half empty. 2025 has Jan to Oct blank and 2026 has Nov and Dec blank. | For "12 months", use one calendar with `range: [startISO, endISO]`. Keep per-year rows for a single year and All years. |
| A5 | `#heatmap-chips` | 390 | Minor | 10 year chips wrap to two rows. | Use "12 months", the last 2 years, and "More years…" (`<select>`), or one scrolling row. |
| A6 | `section.chapter.explore-more` | all | **Major** (visual) | Not inside a card (G8). Charts run to the page edge, and at 1280+ every chart is full width, stacked eight deep (2,491 px). | G8, plus `section.chapter.explore-more { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 520px), 1fr)); gap: var(--pge-space-6); }` with `header.chapter-head` and `.fig-wide` at `grid-column: 1 / -1`. |
| A7 | `#chart-fingerprint` | 390 | Minor | Parallel-axis names are truncated ("On-peak s…", "Portal ¢…"). | Use two-line names (`"On-peak\nshare"`) or hide the chart on phones. |
| A8 | `#chart-ridgelines` | 390, 1280 | Minor | 13-month legend paged `1/4` at 390 and `1/2` at 1280. At phone height the ridges are hard to tell apart. | Drop the legend and label each ridge on the y-axis with the month. Ridgelines read by row, not by color. |
| A9 | `#chart-published-week`, `#chart-daypart-stream`, `#chart-weather-counterfactual` | 390 | Minor | Seven overlapping lines, a dense stream, and two stacked grids in 200 px. None are readable. | G1 heights. For published-week, highlight yesterday and grey the other six days. |
| A10 | `#chart-polar` | 1280+ | Minor | The 24-hour clock is drawn about 180 px across inside a 992 × 280 host, mostly whitespace. | Give it a half-width cell in the A6 grid. |
| A11 | `#insights-cost .insights-cost-grid` | 1500, 1680 | Minor | Two-column grid with one visible chart (`#cost-per-kwh`). The right half of the card is empty. The billed vs payments chart is not shown here. | Confirm whether the second chart moved to Billing (`#ledger-bill`). If it did, drop the grid. |
| A12 | `.fig-head .hint` | 780, 1280 | Minor | The `?` renders on a second line under ⓘ, next to nothing (`analytics-780.png`). | G7. |

## B. Billing (`#panel-billing`, `#billing.card`)

| # | Selector | Width | Severity | Problem | Fix |
| --- | --- | --- | --- | --- | --- |
| B1 | `section.chapter[data-chapter="billing-charts"]`, `section.chapter[data-chapter="bill-pdf"]` | all | Minor | Headings repeat (G9). | Add `data-chapter-headline`. |
| B2 | `#chart-bill-explainer` | all | **Major** | About 80 to 100 px of empty space between the title and the plot. Bar labels sit inside same-hue bars: "-$9.97" in red on a red bar and "-$7.91" are unreadable. Positive values carry a "+" prefix that reads as noise. | Set `label.position` to `"top"` for positives and `"bottom"` for negatives, with color `theme.text`. Reduce `grid.top` to the legend height. Format with `formatSignedUsd` only on negatives. |
| B3 | `#chart-waterfall` | 390 | **Major** | "+$212.28" is wider than its bar. The x labels "Previous amount due" and "Payment" run together. The same empty band sits above the plot. | `axisLabel: { interval: 0, width: 72, overflow: "break" }`, labels above the bars, and a smaller `grid.top`. |
| B4 | `#ledger-bill`, `#ledger-kwh` | all | Minor | No figure title or wrapper. `#ledger-kwh` is 160 px tall where its siblings are 240, and its legend overlaps its axis name ("Bill kWh" twice). | Render them through the same `figure()` helper ("Billed vs paid", "Billed kWh") with height 240. |
| B5 | `#chart-statement-portal`, `#chart-bill-imported`, `#chart-bill-anatomy` | all | Minor | Raw ISO dates on the x-axis (G12). | G12. |
| B6 | `#billing .usage-summary-wrap` | 1100+ | Minor | Same two-column label/value spread as U3. "Amount due" appears in Balance & due, in Statement details, and on the Overview tile. | U3 fix. Collapse "Statement details (PDF)" by default. |
| B7 | `#billing.card` | all | Minor | One 3,544 px card (G10). | G10. |

## T. Time of Day (`#panel-tod`, `#tod.card`)

| # | Selector | Width | Severity | Problem | Fix |
| --- | --- | --- | --- | --- | --- |
| T1 | `.tod-schedule .tod-grid` | 390 | **Major** | `grid-template-columns: 52px repeat(24, 1fr)` with `.tod-cell { min-width: 12px }` and 2 px gaps needs 390 px in a 344 px card. Hours 20 to 23 are clipped (`.tod-grid-head.tod-hour` right edge 397 and 411), and the highlighted current hour can be off-screen (`issue-tod-grid-overflow-390.png`). | Below 640: `.tod-grid { grid-template-columns: 22px repeat(24, minmax(0, 1fr)); gap: 1px; }`, `.tod-cell { min-width: 0; }`, single-letter day labels, and hour labels every 3 hours (`.tod-hour:not(:nth-child(3n+2)) { visibility: hidden; }`). |
| T2 | `details.tod-compare-math .tod-table` | 390 | **Major** | `@container pge (max-width: 640px) .tod-table th, .tod-table td { overflow-wrap: anywhere; }` breaks every cell character by character: "A m ou nt", "$1 95 .8 3", "TOD (offli ne defa ults)" (`issue-tod-math-table-390.png`). | Delete that rule. Add `.tod-table .num { white-space: nowrap; }`. Below 640, render each line as a stacked block (Line, then Amount · Rate, then the "What this is" paragraph) instead of a 4-column table. |
| T3 | `.tod-usage .tod-table` (Usage by period) | 390 | **Major** | Same rule: "1,023.45 kWh", "$188.9 1", and "37.24 %" wrap mid-number. | T2 fix. Hide the "Avg portal ¢/kWh" column below 640, since it is 18.46 in every row. |
| T4 | `#tod-range-more` and the TOD `.range-custom` form | 390, 1280 | **Major** at 390, Minor at 1280 | The More… select is off-screen (right edge 448). The two `datetime-local` inputs and `Apply` show even with the `Last cycle` preset selected, adding 120 px of form at 390. | G6. Render `.range-custom` only when Custom is active, as the header range bar does. |
| T5 | `.shift-form` | 780+ | Minor (CSS order bug) | `@container pge (min-width: 720px) { .shift-form { grid-template-columns: 1.4fr repeat(3, …) } }` at line 1069 comes *before* the base `.shift-form { grid-template-columns: 1fr; }` at line 1231. With equal specificity the later rule wins, so the 4-up layout never applies. At 1280 the "7.2" kW input is 938 px wide. | Move the `@container pge (min-width: 720px)` block after line 1244. |
| T6 | `#chart-shift-sim` | all | Minor | The markLine label "Schedule 7 base + Schedule 125" is drawn across the bars. The host is 264 px at 390 and 878 px at 1280, indented from the other charts. | `markLine.label: { position: "insideEndTop" }` with the short text "Basic rate". Remove the extra horizontal padding on the simulator wrapper. |
| T7 | `.kpi-row` (Period now, Current rate, Next transition) | 390 | Minor | Three full-width tiles take 243 px. They are cards nested in `#tod.card`, and only the first has an accent border. | Below 640, `.kpi-row { grid-template-columns: 1fr 1fr; }` with Period now spanning 2. |
| T8 | `#chart-tod-stacked` | 390 | Minor | 30 days of hourly stacked area show as spikes at 344 px. | When narrow, aggregate to daily stacked bars. |
| T9 | `#chart-period-box` | 390 | Minor | Large empty band above a 60 px tall plot. | Smaller `grid.top`, and G1. |
| T10 | `section.chapter[data-chapter="tod-charts"]` | all | Minor | The headline does not match its content (G9) and the chapter starts flush under the Catalog table (G8). | G8 and G9. |
| T11 | `details.tod-holidays`, `details.tod-compare-math` | all | Minor | Use the native ▾ marker. Every other disclosure uses the custom chevron. | Include them in the G11 selector list. |

## R. Rule conflict

**R1. The viewport table in `.agents/rules/responsive-viewports.mdc` cannot pass while the container thresholds stay at 820 and 1,520 px.** The table sets column counts by *window* width (960 → 4, 1100 → 4, 1680 → 7). The CSS correctly measures `#kpis`, and the HA sidebar (256 px) plus padding takes about 290 px. Measured `#kpis` widths are 672 px at 960, 812 px at 1100, and about 1,390 px at 1680. All three fall into the lower bucket.

A card-width threshold alone cannot fix this. At window 780 the HA sidebar is hidden, so `#kpis` is 726 px, and it must show 2 columns. At 960 the sidebar is open, `#kpis` is 638 px, and it must show 4. The fix combines the window and the card:

```css
@media (min-width: 871px) {            /* HA sidebar breakpoint */
  @container (min-width: 600px) { .kpi-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
  @container (min-width: 1300px) { /* 7 columns, 2 rows, column flow */ }
}
```

Re-measure after any card padding change and keep 600 and 1300 below the measured widths at 960 and 1680 and above 1500's (about 1,178 px).

---

## Fix order

**Now (Major issues, about 3 to 4 hours):**

1. G1 chart heights and G2 combo axes in `charts.js` (30 minutes). This fixes the "charts too condensed on mobile" complaint on every tab.
2. T1, T2, T3, U1: table and grid overflow at 390 (45 minutes, CSS only).
3. G4, G5, G6: phone header, tabs, and More… menu (60 to 90 minutes, `_renderShell()` markup plus CSS).
4. A1, A2, A3: Analytics weather message, `.grid-2` misuse, and phone calendar (60 minutes).
5. B2, B3: bill explainer and waterfall labels (20 minutes).

**Later (Minor issues, clutter and spacing, about 3 to 4 hours):**

1. G8 chapter styles, plus explore-more as a card and grid (30 minutes).
2. G7 and G9 chart header cleanup, plus duplicate headings (30 minutes).
3. G10 split the per-tab mega-cards (60 to 90 minutes).
4. G11, G12, G13 disclosures, date formats, and spacing scale (45 minutes).
5. Every O, U, A, B, and T row marked Minor (60 minutes), then R1.

After each step, re-run the seven widths. Capture steps: set device metrics, open `#tab`, scroll to the bottom to trigger lazy charts, measure `scrollHeight`, resize to full height, then screenshot.

## Not covered

- Dark theme and custom themes were not captured.
- `#programs` was not in scope.
- Hover and tooltip states, the chart expand dialog, and the sync drawer were not opened.
- Disclosure states (Range accounting, Hourly breakdown, and others) were captured as persisted in this browser profile: open.
