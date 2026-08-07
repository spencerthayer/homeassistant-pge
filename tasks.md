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

## Active agents

- None
