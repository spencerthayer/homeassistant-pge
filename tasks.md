# Tasks

## Done

- [x] Recorder statistics collision (0.7.4): bill-period average temperature is now external-only — dropped its entity mirror (snapshot-stamped rows pre-seeded the current-hour slot and collided with HA Core `compile_statistics`' plain INSERT, logging `UNIQUE constraint failed: statistics.metadata_id, statistics.start_ts` / "Blocked attempt to insert duplicated statistic rows" every billing sync); added one-time `async_clear_statistics` cleanup (`bill_avg_temp_mirror_cleanup_done`) so stale rows can't re-block a purge/repack recompile; HA compiles the sensor's native hourly rows; panel unchanged (reads external `pge_energy:*` ids); docs updated (ARCHITECTURE/DATA_CONTRACT/README mean-series rule); HACS release `v0.7.4` (0.7.3 Latest was solar diagnostics only)
- [x] Backfill hang recovery: remove poll/`import_lock`/`hass.async_block_till_done` deadlock; background tasks for long-lived jobs; poll defers while backfill runs
- [x] Progress-stall watchdog + hard release + generation guard; CancelledError/`fail_sync_job`; selective `target_*` clear (stall/fail clear, unload cancel keeps resume)
- [x] Per-tier `asyncio.wait_for` (2h) and bounded `async_save_import_state` (30s, critical/non-critical)
- [x] Boot repair: restored `backfilling` → `failed` ("Interrupted by restart") when no live task
- [x] Unit tests in `tests/components/pge_energy/test_backfill_hang.py` (+ sync_progress / coordinator updates)
- [x] Code-review fixes on the hang-recovery commit: generation-scoped abort reason (`consume_backfill_abort(generation)`) and `owns_backfill_generation` guards so an orphaned job cannot clear its successor's `target_*` or flush the shared `import_store`; unload now cancels tracked orphans; stall heartbeat reset at task start; boot repair also clears restored `refreshing`; `_STORES` cache evicted on unload; ruff E402/F401/SIM102 from the original commit
- [x] Recorder ack rewrite (0.5.43): verify distinguishes row absent vs stale; ack re-issues write (bounded); cost/temperature ack non-fatal + clear `dirty_from`; mirror before cost/temp ack
- [x] Drop entity mirrors for four monetary mean sensors + one-time `async_clear_statistics` cleanup (`billing_mirror_cleanup_done`); downgrade "already in progress" service logs to warning
- [x] Remove stock HA energy-date-selection + statistics-graph fallback cards from `/pge` Usage section (0.5.44)
- [x] Weather vs usage scatter tooltip includes Pacific day date(s) (0.5.45)
- [x] Clarified `.cursor/rules/bump-version-on-code-changes.mdc`: HACS integration upgrade cycle (bump → commit → push → GitHub Release Latest) required for shipped versions
- [x] Stop mutating frontend user-store sidebar (`panelOrder` / `hiddenPanels`) so Browser Mod / HA own order and visibility ([issue #2](https://github.com/spencerthayer/homeassistant-pge/issues/2); 0.5.46); regression guards in `test_panel.py`
- [x] Published GitHub Release [v0.5.46](https://github.com/spencerthayer/homeassistant-pge/releases/tag/v0.5.46) and asked `@gatlinnewhouse` to retest on [#2](https://github.com/spencerthayer/homeassistant-pge/issues/2)
- [x] Panel: move Sync status under At a glance; combine with PGE publication gaps in one collapsible (default collapsed, `localStorage` persist key `sync_status`) — 0.5.47
- [x] Published GitHub Release [v0.5.47](https://github.com/spencerthayer/homeassistant-pge/releases/tag/v0.5.47)
- [x] Drop `device_class` on hourly tip sensors (`PGEHourlyEnergySensor` / `PGEHourlyCostSensor`) so `state_class=measurement` is HA-valid; units kept; lifetime sensors unchanged — 0.5.48
- [x] Panel: shrink dual-value PGE est. next bill KPI (`kpi-dual`) to `1.15rem` — 0.5.49
- [x] Configure → **Panel** (0.6.0): domain Store `pge_energy.panel` for show sidebar / title / icon / require_admin / default landing section; `/pge` stays registered when sidebar hidden; OptionsFlow aborts without touching entry options; never mutate HA/Browser Mod sidebar user-store
- [x] Bill PDF data feasibility spike: 25 focused tests + public/sanitized real-layout fixtures; six live PDFs (3 bills × detailed/simplified, including move/multi-meter) all reconcile core fields and expose 16 normalized metric families; raw PDFs deleted; no runtime/sync/Store changes

## Follow-ups

- [x] Cognito rate-limit exploration + respect (0.6.1): live probe fixtures; `PGERateLimitError` for TooManyRequests / Password attempts exceeded; shared email cooldown; no refresh amplify; coordinator soft-fail without reauth; force_renew coalesce; README mermaid + AUTH_DISCOVERY; GitHub Release [v0.6.1](https://github.com/spencerthayer/homeassistant-pge/releases/tag/v0.6.1)
- [x] Browser UAT 0.6.0: Configure → Panel menu; hide sidebar removes link; `/pge` still loads (billing landing + sync complete); Store persists; abort message shown
- [x] Commit / push / GitHub Release [v0.6.0](https://github.com/spencerthayer/homeassistant-pge/releases/tag/v0.6.0) (Panel Configure menu)
- [x] CI lint ([run 30330317615](https://github.com/spencerthayer/homeassistant-pge/actions/runs/30330317615)): ruff SIM108 ternaries in `panel_settings.py`, SIM117 combined `with` in panel tests, `ruff format` on `test_panel_landing_js.py`
- [x] Cursor rule: HACS release requires green CI (`.cursor/rules/hacs-release-requires-green-ci.mdc`); bump-version cycle + `AGENTS.md` cross-linked
- [ ] Browser Mod UAT with `@gatlinnewhouse` on [#2](https://github.com/spencerthayer/homeassistant-pge/issues/2): after 0.5.46, Clear synced sidebar once if still overridden, reapply Browser Mod hides/order, restart HA, confirm hidden items stay hidden; close issue only after confirmation
- [ ] Browser UAT (operator): `./stop`/`./start` with this repo’s `pge_energy` linked; confirm `/pge` sync sensors leave `backfilling` on stall/complete, poll overlaps backfill without freeze, mid-backfill reload returns promptly, boot resume keeps targets after unload cancel
- [ ] Operator: after upgrading to 0.5.43, confirm recorder health (no `Cannot operate on a closed database` / `Unexpected exception when updating statistics`); if present, `recorder.purge` with `repack: true` before trusting mismatch-free polls
- [ ] Operator UAT 0.5.43: no `Recorder state mismatch …_cost`; `dirty_from` clears; four state-class repairs gone after cleanup and stay gone across a billing sync; `/pge` + Energy still show external billing means
- [ ] Optional: per-call timeout inside `async_import_with_baseline` / recorder executor jobs if stalls persist under Pi load
- [ ] Optional: auth-lock wall-clock timeout beyond existing aiohttp bounds (30s GraphQL, 45s portal login)
- [x] Bill PDF download + normalized data (0.7.0): opt-in `download_bill_pdfs`; REST fetch; `www/pge_energy/…` retention; production parser (`pypdf`); Store v2 index; 18 `_bill_pdf_*` statistics; panel link + Statement details; services `download_bill_pdf` / `reparse_bill_pdfs`; GraphQL remains canonical — GitHub Release [v0.7.0](https://github.com/spencerthayer/homeassistant-pge/releases/tag/v0.7.0)
- [x] Bill PDF operator UAT (partial, live `./start`): enabled `download_bill_pdfs` + `latest`/`detailed`; `download_bill_pdf` + `reparse_bill_pdfs` for 2026-07-13; PDF at `/local/pge_energy/…/2026-07-13_detailed.pdf` (125 KB); panel **View bill PDF** + **Parsed** badge; Statement details reconcile ($300.13 / 1,358 kWh); statistics imported — **two live bugs found/fixed locally** (Store v1→v2 migration `NotImplementedError`; `bill_pdf_sync` loop variable shadowed `entry.entry_id`)
- [x] Bill PDF patch 0.7.1: Store v1→v2 migration + `bill_pdf_sync` entry shadowing fix — HACS release [v0.7.1](https://github.com/spencerthayer/homeassistant-pge/releases/tag/v0.7.1)
- [ ] Bill PDF UAT remainder: toggle-off (no PDF phases); simplified form switch; `rolling_n=2` GC; failure-harness path; enable one line-item sensor; diagnostics REST endpoint
- [ ] Bill PDF follow-ups: authenticated Media Source; cleanup `www/pge_energy/` on entry remove; OCR only if a real image-only bill appears
- [x] Log-noise reduction (0.7.2): quiet `pypdf` layout warnings (`Limiting excessive whitespace…`, `Rotated text discovered…`) plus caught-and-retried `pge_energy` soft-fails via HA `logger: filters:` in `configuration.yaml` — README Troubleshooting section + live dev config; filters require exact submodule logger names (HA logger filters do not cascade to child loggers); keep-list (auth/reauth, backfill errors, statistics errors, retry-day-invalid) untouched; verified live reparse emits no pypdf warnings; HACS release [v0.7.2](https://github.com/spencerthayer/homeassistant-pge/releases/tag/v0.7.2) (all 4 CI jobs green on the release SHA)
- [ ] Grid return PGE GraphQL discovery (0.7.3): default-off Configure → Sync settings alpha switch; bounded/redacted HOURLY/DAILY/MONTHLY capture; one-shot soft-fail introspection; live UAT confirmed `getNetMeteringDetails(encryptedAccountId, encryptedPremiseId)` → `monthlyBill.excessGeneration` exists but semantics remain unknown; NinjaNife 1–2 day handoff on [#5](https://github.com/spencerthayer/homeassistant-pge/issues/5); production `_return`/`_compensation` blocked on returned contract evidence

## Active agents

_(none)_
