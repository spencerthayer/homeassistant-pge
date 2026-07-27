# Tasks

## Done

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

## Follow-ups

- [ ] Browser Mod UAT with `@gatlinnewhouse` on [#2](https://github.com/spencerthayer/homeassistant-pge/issues/2): after 0.5.46, Clear synced sidebar once if still overridden, reapply Browser Mod hides/order, restart HA, confirm hidden items stay hidden; close issue only after confirmation
- [ ] Browser UAT (operator): `./stop`/`./start` with this repo’s `pge_energy` linked; confirm `/pge` sync sensors leave `backfilling` on stall/complete, poll overlaps backfill without freeze, mid-backfill reload returns promptly, boot resume keeps targets after unload cancel
- [ ] Operator: after upgrading to 0.5.43, confirm recorder health (no `Cannot operate on a closed database` / `Unexpected exception when updating statistics`); if present, `recorder.purge` with `repack: true` before trusting mismatch-free polls
- [ ] Operator UAT 0.5.43: no `Recorder state mismatch …_cost`; `dirty_from` clears; four state-class repairs gone after cleanup and stay gone across a billing sync; `/pge` + Energy still show external billing means
- [ ] Optional: per-call timeout inside `async_import_with_baseline` / recorder executor jobs if stalls persist under Pi load
- [ ] Optional: auth-lock wall-clock timeout beyond existing aiohttp bounds (30s GraphQL, 45s portal login)

## Active agents

_(none)_
