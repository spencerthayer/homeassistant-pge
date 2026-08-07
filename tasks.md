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
- [ ] Ship MINOR HACS release `v0.8.0` only after explicit approval (release+tag for v0.8.0 withdrawn; Latest remains v0.7.5)
- [x] Address Copilot suppressed feedback: return/compensation day sums report `0` (not unavailable) when published intervals have no export; fix `DirectionalUsage` field docstring

## Active agents

- None
