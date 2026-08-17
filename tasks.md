# Tasks

## Issue #5 UAT follow-ups — TOD panel cost + program credit sensors (MINOR)

**Context:** Live HA fact-check on [#5 comment](https://github.com/spencerthayer/homeassistant-pge/issues/5#issuecomment-5305006740) confirmed:
- Signed import/export works.
- Portal TOD hourly `amount` is flat ~base rate × kWh (PGE data quality — ingest pass-through is correct; **charts that trust `_cost` still mislead**).
- Daily portal cost looks closer to the bill (possibly coarse/rounded).
- Outdoor °F is sparse PGE interval `temperature` (not a weather-feed bug).
- Programs shows enrollment only today (no PTR `$` yet) by design until this feature.
- **Portal confirmation (16 Aug 2026):** My Energy Use `getUsageCompare` HOURLY on a weekday (5 Aug) is ~18.45¢/kWh in off/mid/on (18.39 / 18.46 / 18.47). Control login is **not** TOD-enrolled (`isCustomerEnrolledInTOD=false`; Programs = PTR + Green Future only). Daily 5 Aug is integer `$10` vs hourly sum `$7.84`. Widget copy already says hourly/daily $ may not match the bill. `/pge#tod` last-cycle Cost column is 18.47¢ in every period. Schedule 7 TOD bundled ¢ is ~5.56 / 11.27 / 30.63 — FAQ defaults 8.93 / 16.7 / 43.13 are also stale vs that tariff.

**Two product tracks (one MINOR release):** (1) make `/pge` cost charts honest for TOD accounts without rewriting HA Energy statistics; (2) full program credit sensors + Programs UI + alerts.

**Out of scope:** Overwriting recorder `_cost` / Energy dashboard with rate-card estimates; Smart Charging pause-bucket entities (not in GraphQL); net-metering bank as Energy-canonical `$`/kWh; forging `$0` when detail soft-fails.

### Track A — TOD hourly cost on `/pge` (addresses the chart breakage)

**Approach (panel-first):** Keep importing portal `amount` into `pge_energy:…_cost` unchanged (Energy dashboard stays portal truth, however flat). When the account is TOD-enrolled, Usage + Analytics **display** cost from local TOD-priced imported kWh using the same rate card as `#tod` (`resolve_tod_rates` / WS `tod.rates`: override → portal cache → FAQ defaults). Label series and tooltips as **Local TOD estimate** vs optional secondary **PGE reported**. Reuse `bucketTodByPeriod` / period×rate math already in [`frontend/data.js`](custom_components/pge_energy/frontend/data.js); wire into Usage projection + Cost intelligence in [`charts.js`](custom_components/pge_energy/frontend/charts.js) / [`pge-panel.js`](custom_components/pge_energy/frontend/pge-panel.js).

- [x] Detect flat portal hourly effective rate across off/mid/on (enrolled only) → panel banner: PGE hourly cost is flat; charts use local TOD estimate
- [x] Usage multi-series + Range accounting cost columns: TOD-enrolled → local TOD-priced cost for hourly shape; show PGE reported in tooltip
- [x] Analytics Cost intelligence / ¢/kWh: same local estimate when enrolled (else portal `_cost`)
- [ ] Day-level KPIs (yesterday / since statement): prefer **portal daily cost** when a DAILY (or day-sum of portal) figure exists — reporter found daily closer to the bill; do not replace with sum of flat hourly portal amounts when daily is available
- [ ] `#tod` unchanged in role (already dual-tracks imported vs TOD-priced); ensure copy does not contradict Usage labeling
- [x] Docs: `DATA_CONTRACT.md` — portal HOURLY `amount` may ignore TOD periods; panel estimate contract; Energy `_cost` remains portal
- [ ] Issue #5 reply: acknowledge bad portal hourly `$`; this release fixes `/pge` readability via local estimate; Energy may still show flat portal cost until PGE fixes the API
- [ ] Node tests: flat-rate detector; enrolled Usage projection uses TOD rates; non-enrolled still uses portal `_cost`

### Track B — Program credit sensors + Programs UI + alerts

- [ ] `DATA_CONTRACT.md` / README: outdoor temp = portal interval field; Programs credits require enrollment + detail payload
- [ ] Close/replace open gate: “Gate Smart Battery financial/kWh sensors…” → ungate under enrolled-only + soft-fail + UAT

#### Sensors (enrolled-only native values; soft-fail → last-good; null ≠ 0)
- [ ] PTR: `ptr_total_earned_credit` ← `totalEarnedCredit`; `ptr_last_event_credit` ← newest `eventEarnedCredit`; keep `next_ptr_event_date`
- [ ] Smart Charging: `smart_charging_last_season_credit` ← `lastSeasonEarnedCredit`; flatten season/`enrollmentStatus`/`cardType` attrs
- [ ] Smart Battery: `smart_battery_current_bill_credit`, `smart_battery_ytd_credit`, `smart_battery_current_bill_kwh`, `smart_battery_ytd_kwh` + season attrs
- [ ] Flex rollup: add `on_bill_flex_load_earnings`; document `ytd_program_savings` as aggregate (do not sum with program tips without portal confirmation)
- [ ] Pattern: `MONETARY`+`USD` / energy kWh; `state_class=None` on mean credit tips; external-only mean stats
- [ ] Default entity enabled when enrolled (or detail present); disabled when not enrolled

#### Statistics / WS / panel
- [ ] External suffixes + import in `billing_statistics.py` (or `program_statistics.py`); PTR event credits by `eventDate` as external series
- [ ] `pge_energy/accounts` WS: typed credit fields for Programs UI
- [ ] `/pge` Programs: per-program credit KPIs + season window + PTR next/last event credit; `—` on soft-fail (never forged `$0`)

#### Alerts (introduce minimal `pge_energy_alert` surface if absent)
- [ ] Domain events: program enroll/unenroll (PTR/SC/Battery); credit increase/change tips
- [ ] Summary entities only as needed for automations; no built-in notify service

### Shared: tests / version / UAT / release
- [x] Unit + frontend tests for Track A and B (existing tests updated, 458 pass, ruff clean)
- [x] MINOR SemVer bump (`const` / `manifest` / frontend `?v=` / README) → `0.10.0`
- [ ] Contributor UAT: vvj0 — TOD charts readable + SC/PTR credits; Battery default-disabled until pilot if needed
- [ ] Green CI → HITL HACS Latest only with explicit approval

### v0.10.0 — On-device tariff catalogs + dual-source TOD/Basic

**Completed:**
- [x] `tod_tariff.py` — models, lookup, merge, validation, serialization
- [x] `tariff_sources.py` — PGE Gatsby page-data + PDF fetch/parse
- [x] `tariff_store.py` — domain-global Store v1 for tariff catalogs
- [x] `tariff_updater.py` — coordinator with conditional requests, retry backoff, effective-date wake
- [x] `tod_pricing.py` — `resolve_tod_rates_from_catalog`, `resolve_basic_from_catalog`, `RATE_SOURCE_CATALOG`
- [x] `__init__.py` — wire up domain-global tariff updater lifecycle
- [x] `websocket.py` — enriched `tod` payload (enrolled, catalogs, tariff_status, basic_comparison_*, override_*)
- [x] `data.js` — `estimatePlanCostSeries`, `aggregateEstimatedCostSeries`, `reconcilePlanComparison`, `detectFlatPortalRates`
- [x] `pge-panel.js` — `_todCompareHtmlDual`, `_tariffStatusHtml`, `_todCompareHtmlCoverage`; catalog-based dual-source presentation
- [x] Tests: updated `test_tod_pricing`, `test_panel`, `test_tod_data_js` for v0.10.0 behavior
- [x] Docs: `ARCHITECTURE.md`, `DATA_CONTRACT.md`, `README.md`

**Remaining:**
- [ ] Frontend tests for `data.js` new helpers (unit Node tests)
- [x] **BLOCKER (2026-08-17 live HA QA, PR #27):** `/pge` crashed because `_tod_payload` called `.get` on `ProgramsSnapshot`. Fixed to read `time_of_day_enrolled`. Live `/pge` and `/pge#tod` load after HA process restart; Sync settings TOD/Basic boxes omit `default=None` so empty overrides can render.
- [ ] Live HA UAT retry after the WS crash fix: `/pge#tod` dual-source presentation, tariff status block, flat-rate detection
- [ ] Issue #5 reply with release

## Stale tip during history backfill — 0.9.13

- [x] Root cause: scheduled poll skipped while `_backfill_in_progress`, hourly walked oldest-first (365d), next tip wait was the 4h Pacific grid — HA lagged live portal by a full published day
- [x] Correction-window polls fetch during backfill; `import_lock` serializes recorder writes (no `hass.async_block_till_done`)
- [x] Hourly backfill newest incomplete local day first
- [x] `async_request_refresh` when the backfill job exits
- [x] Tests: `test_poll_fetches_correction_window_while_backfill_in_progress`, newest-first hourly, post-backfill refresh
- [x] Docs: `ARCHITECTURE.md`, `DATA_CONTRACT.md`, `HA_SETTINGS_HISTORY.md`; VERSION `0.9.13`
- [x] Live HA `/pge`: `latest_available_interval` `2026-08-16T08:00:00Z` (Aug 16, 1:00 AM PT) matches portal/GraphQL tip; `last_successful_update` advanced on this boot; yesterday 17.03 kWh; sync complete; panel `?v=0.9.13`
- [x] HITL GitHub Release [`v0.9.13`](https://github.com/spencerthayer/homeassistant-pge/releases/tag/v0.9.13) Latest from `b700992` (CI `test`/`hassfest`/`hacs` green; leftover `9.9.10`/`0.9.12` branch tips merged keeping 0.9.13)

## Multi-account discovery — issue #20

- [x] Root cause: `getAccountInfo` only surfaces each group's `defaultAccount`; non-default accounts never enter config-flow matching (`account_not_found`)
- [x] Broaden discovery: merge `getAccountDetailList(ALL_ACCTS, ACTIVE)` account numbers with `getAccountInfo` defaults (soft-fail detail list)
- [x] Sanitized DEBUG discovery diagnostics (counts + last-4 only)
- [x] Fixtures/tests: two-accounts-one-default, detail-list soft-fail, multi-group, digits-only second account, unknown still rejected
- [x] Copilot review hardening (PR #25): gate detail-list on `accountMeta.totalAccounts`, fail-closed MFA/CAPTCHA on the detail-list call, minimal discovery GraphQL document (no billing overfetch)
- [x] Docs: `AUTH_DISCOVERY.md`, `DATA_CONTRACT.md`; VERSION `0.9.12`
- [ ] Green CI on PR; live HA single-account UAT; reporter multi-account UAT
- [ ] HITL squash/merge PR #25 → `Release` workflow publishes `v0.9.12` Latest when the tag is missing
- [ ] Comment on [#20](https://github.com/spencerthayer/homeassistant-pge/issues/20) after release

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
- [x] Fix Sync settings Submit `expected float` on blank TOD rate overrides (blocks diagnostic capture save); ship PATCH `v0.9.10`
- [x] At a glance KPI click-to-copy (label/value/delta); ship PATCH [`v0.9.11`](https://github.com/spencerthayer/homeassistant-pge/releases/tag/v0.9.11) (HITL squash-merge PR #24)

## Programs / net metering / TOD — v0.9.1

- [x] EV Smart Charging + Smart Battery Pilot enrollment binary sensors, eligibility attrs, Programs rows
- [x] PTR `peakTimeEvents` / seasonal dates attrs + `next_ptr_event_date` sensor + panel footnote
- [x] Net-metering best-effort fetch + Store retention + diagnostic sensor (units gated)
- [x] Remove dead `getTimeOfDayPricingDetails`; extend TOD enrollment attrs; `getRateCompare` diagnostic snapshot
- [ ] ~~Gate Smart Battery financial/kWh sensors until a pilot participant validates payload~~ → see **Track B** above (ungate with enrolled-only + UAT)
- [ ] Direct portal TOD period ¢/kWh remains unresolved (override → cache → FAQ defaults); **Track A** mitigates `/pge` charts via local TOD estimate without rewriting Energy `_cost`

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
