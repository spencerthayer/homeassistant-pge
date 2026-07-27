# Tasks

## Done

- [x] Backfill hang recovery: remove poll/`import_lock`/`hass.async_block_till_done` deadlock; background tasks for long-lived jobs; poll defers while backfill runs
- [x] Progress-stall watchdog + hard release + generation guard; CancelledError/`fail_sync_job`; selective `target_*` clear (stall/fail clear, unload cancel keeps resume)
- [x] Per-tier `asyncio.wait_for` (2h) and bounded `async_save_import_state` (30s, critical/non-critical)
- [x] Boot repair: restored `backfilling` → `failed` ("Interrupted by restart") when no live task
- [x] Unit tests in `tests/components/pge_energy/test_backfill_hang.py` (+ sync_progress / coordinator updates)

## Follow-ups

- [ ] Browser UAT (operator): `./stop`/`./start` with this repo’s `pge_energy` linked; confirm `/pge` sync sensors leave `backfilling` on stall/complete, poll overlaps backfill without freeze, mid-backfill reload returns promptly, boot resume keeps targets after unload cancel
- [ ] Optional: per-call timeout inside `async_import_with_baseline` / recorder executor jobs if stalls persist under Pi load
- [ ] Optional: reduce 8× `async_ack_external_statistics` retry loop during multi-hundred-batch backfill (largest remaining latency win)
- [ ] Optional: auth-lock wall-clock timeout beyond existing aiohttp bounds (30s GraphQL, 45s portal login)

## Active agents

_(none)_
