# Tasks

## Grid import/export — issue #5

- [x] Ship default-off GraphQL diagnostic capture and collect NinjaNife's generating-account logs
- [x] Resolve the contract as signed HOURLY usage: positive import/cost, negative export/compensation
- [x] Preserve valid rows when PGE returns an explicit null interval and stop permanent-gap backfill loops
- [x] Split fine-grained usage into non-negative `_consumption`, `_return`, `_cost`, and `_compensation` statistics
- [x] Repair proven signed fine-grained recorder history without guessing at coarse monthly direction
- [x] Add return/compensation sensors, websocket IDs, `/pge` export charting, and HA Energy verification
- [x] Live HA UAT on `/pge`: sync complete, KPIs populated, frontend `?v=0.8.0`, export KPI hidden on non-generating account
- [x] Address [#10](https://github.com/spencerthayer/homeassistant-pge/issues/10): Energy dashboard docs, stable `account_key`, clear external stats on entry remove
- [x] Ship PATCH HACS release `v0.8.1` (includes signed import/export + Copilot follow-up; v0.8.0 tag was withdrawn)
- [x] Address Copilot suppressed feedback: return/compensation day sums report `0` (not unavailable) when published intervals have no export; fix `DirectionalUsage` field docstring

## Bill PDF rotated text — issue #16

- [x] Keep rotated payment-stub text in layout extraction (`layout_mode_strip_rotated=False`)
- [x] Replace dead `warnings.filterwarnings` with a targeted pypdf `logging.Filter`
- [x] Unit tests: layout retains rotated stubs; rotation warnings silenced; Form XObject via plain fallback
- [x] Live HA: force `download_bill_pdf` for 2026-08-05 → amount/kWh reconcile, confidence 1.0, no `Rotated text` log lines
- [x] Ship PATCH HACS release [`v0.8.2`](https://github.com/spencerthayer/homeassistant-pge/releases/tag/v0.8.2); closed [#16](https://github.com/spencerthayer/homeassistant-pge/issues/16)

## Agent / repo process

- [x] Add always-on Cursor rule: HITL required to merge any PR (no auto-merge without permission)

## TOD Pricing Hub — issue #11 (branch `issue-11` → PR)

- [x] `tod_schedule.py`: offline E-TOU engine — 3 periods, weekday Pacific windows (off 21-7, mid 7-17, on 17-21), observed/fixed holidays
- [x] `tod_pricing.py`: default rate card (MIT-attributed), override → portal snapshot → defaults resolution, transition coordinator
- [x] Coordinator TOD transition watchdog + additive `tod_snapshot` store persistence (no storage version bump)
- [x] `billing_sync` step 5 `_async_fetch_tod_snapshot`: speculative `getTimeOfDayPricingDetails`, soft-fail on any exception, re-persist last-good
- [x] Sensors `tod_period` / `tod_price` / `tod_vs_basic_savings` + WS `tod` payload roles; options override fields
- [x] Panel `#tod` section (schedule grid, per-period usage, local TOD vs Basic estimate + official savings) + `tod` landing section
- [x] Unit + source-assertion tests; full suite green; live HA UAT `/pge#tod` populated (offline defaults when portal TOD op soft-fails)
- [x] Panel harden: `TOD_PERIODS` import, ISO `next_transition_at` Date coerce, `_asDate` for pacific helpers, `_renderTod` error boundary, avg rate USD→¢
- [x] Docs/README (DATA_CONTRACT resolution chain, ARCHITECTURE modules, README panel/sensors/options); VERSION `0.9.0` + frontend `?v=0.9.0`
- [x] Open PR [#18](https://github.com/spencerthayer/homeassistant-pge/pull/18) from `issue-11`; CoPilot-PR-Loop clean review (iteration 9, review 4888386887)
- [ ] HITL merge PR #18; then HACS release `v0.9.0` after green CI on merge SHA

## Active agents

- None
