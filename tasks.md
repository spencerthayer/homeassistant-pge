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
- [x] v0.9.1: consumption display naming (`PGE <account> consumption` + sensor friendly name); preserve unique/statistic IDs + `_energy` object id
- [x] v0.9.1: pure `projectDirectionalUsage` + Node tests; signed Grid flow chart; net interval amount when compensation observed
- [x] v0.9.1: Range accounting / At a glance import vs net labels; statement-credit limitation copy
- [x] Contributor UAT (NinjaNife / vvj0): signed chart + net interval amount on generating accounts; net-metering units; enrolled Smart Charging / PTR / TOD aggregates
- [x] Open PR [#21](https://github.com/spencerthayer/homeassistant-pge/pull/21) from `issue-5`
- [x] Green CI on PR #21 (`test` / `hassfest` / `hacs` / `prek`)
- [x] Cold-boot soft-fail: persist/restore tip + account/programs/tracker snapshots so sensors stay warm after a failed first poll (not `unknown`)
- [x] Copilot PR loop iter 3: `RATE_EPSILON_KWH` in panel rollup; rename net-metering `encrypted_account_number`; PTR/net-metering + Smart Charging/Battery/PTR/TOD sensor tests
- [x] Copilot PR loop iter 4: Programs `stateDisplay(..., null)` for PTR footnote + enrollment Unknown; safe `interval_size` parse in `usage_interval_from_dict`
- [x] Copilot PR loop iter 3–4 verified stale after branch squash; iterations 6–9 re-triaged the reformulated findings
- [x] Copilot PR loop iter 6: preserve last-good rate-compare / net-metering snapshots on empty payloads; wire `getRateCompare.savings` into savings sensor + `_tod_payload` + panel; yesterday net label requires positive compensation
- [x] Copilot PR loop iter 7: gross-import denominators for rollup row + table footer rates; `savings_source` on `_tod_payload` + comparison-period footnote; UAT task reconciled
- [x] Copilot PR loop iter 8: yesterday compensation from `_compensation` statistic (entity disabled by default); TOD resolution-chain doc fix
- [x] Copilot PR loop iter 9: per-program `is_eligible` on all program binary sensors; savings card labeled from `savings_source`; money KPI sparkline pairs net value with net series
- [x] Code review + local UAT on PR #21: approve-with-nits; scrubbed real account# from cold-boot test (`aa87fcb`); `/pge` sync complete + KPIs/Programs/TOD populated
- [x] Review nits: persist tip before statistics-import soft-fail; `hasCompensation` requires `v > 0`
- [x] Copilot PR loop iter 12: program list eligibility/enrollment preserve null (tri-state) instead of coerced False
- [x] Copilot PR loop iter 13: enroll parse/Store null round-trip; peak-hour import guard; PTR DATE; DST yesterday; positive-credit docs
- [x] HITL merge PR #21 (`2dfb6a3`); HACS release [`v0.9.9`](https://github.com/spencerthayer/homeassistant-pge/releases/tag/v0.9.9); asked [@NinjaNife](https://github.com/NinjaNife) + [@spencerthayer](https://github.com/spencerthayer) to UAT on [#5](https://github.com/spencerthayer/homeassistant-pge/issues/5#issuecomment-5300448116)
- [ ] Fix Sync settings Submit `expected float` on blank TOD rate overrides (blocks diagnostic capture save); ship PATCH `v9.9.10`

## Programs / net metering / TOD — v0.9.1

- [x] EV Smart Charging + Smart Battery Pilot enrollment binary sensors, eligibility attrs, Programs rows
- [x] PTR `peakTimeEvents` / seasonal dates attrs + `next_ptr_event_date` sensor + panel footnote
- [x] Net-metering best-effort fetch + Store retention + diagnostic sensor (units gated)
- [x] Remove dead `getTimeOfDayPricingDetails`; extend TOD enrollment attrs; `getRateCompare` diagnostic snapshot
- [ ] Gate Smart Battery financial/kWh sensors until a pilot participant validates payload
- [ ] Direct portal TOD period ¢/kWh remains unresolved (override → cache → FAQ defaults)

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
- [x] v0.9.2: `#tod` hero is TOD-priced kWh vs billed imported energy (inferred ¢/kWh); rate-card TOD vs Basic stays in collapsed math; `computeTodPlanCompare` + Node tests
- [x] v0.9.3: `#tod` hero verdict is **Would cost more** / **Would save** (not a signed rate-card delta)
- [x] v0.9.4: `#tod` local estimate has its own range picker (default Last cycle), independent of Usage
- [x] v0.9.9: custom TOD clamp updates controls; tip merge
- [x] v0.9.8: merge tip intervals on partial correction; Programs landing + TOD exact windows
- [x] v0.9.7: TOD compare requires observed cost + tri-state enrollment; PR metadata aligned
- [x] v0.9.5: keep Last cycle as the estimate default when the first preset probe lacks statement dates; re-render `#tod` when bill bounds hydrate
- [x] Unit + source-assertion tests; full suite green; live HA UAT `/pge#tod` populated (offline defaults when portal TOD op soft-fails)
- [x] Panel harden: `TOD_PERIODS` import, ISO `next_transition_at` Date coerce, `_asDate` for pacific helpers, `_renderTod` error boundary, avg rate USD→¢
- [x] Docs/README (DATA_CONTRACT resolution chain, ARCHITECTURE modules, README panel/sensors/options); VERSION `0.9.0` + frontend `?v=0.9.0`
- [x] Open PR [#18](https://github.com/spencerthayer/homeassistant-pge/pull/18) from `issue-11`; CoPilot-PR-Loop clean review (iteration 9, review 4888386887)
- [x] HITL merge PR #18; HACS release `v0.9.0` published (`e2597ca`)
- [x] v0.9.1: remove nonexistent speculative TOD pricing op (see Programs / TOD section above)

## Active agents

- None
