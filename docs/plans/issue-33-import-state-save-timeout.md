# Fix #33 — `PGE import state save timed out` on I/O-constrained hosts

Issue: https://github.com/spencerthayer/homeassistant-pge/issues/33
Branch: `issue/33` · PR base: `main` · Target release: **v0.10.4**
Release: **automatic upon PR merge** — `.github/workflows/release.yml` fires on push
to `main`, asserts `manifest.json` version == `const.py` VERSION, then runs
`gh release create vX.Y.Z --latest` from the merged SHA if the tag doesn't exist yet.
Merging the version-bump PR is therefore the publish action; the only HITL gate is merge itself.

## Problem

On slow/contended storage (e.g. Raspberry Pi SD cards), `async_save_import_state`
frequently exceeds its 30s wall-clock timeout. On `critical=True` calls the
`TimeoutError` propagates and aborts backfill / billing / poll jobs even though
in-memory state is valid — only the disk write was slow.

### Verified root causes

- `store.py:212` stamps `last_commit` on **every** save → no dedupe possible;
  every call = full `asdict()` + full disk rewrite.
- Backfill loop: `_async_import_batch` saves twice per batch (`backfill.py:206,228`),
  plus per-day progress persists (`async_persist_sync_progress`) and explicit
  post-batch saves (`backfill.py:323-328`) → 90–180 full rewrites per 365-day backfill.
- Payload grows monotonically (`completed_local_dates`, `bill_pdf_index`, `tip_intervals`).
- `critical=True` timeouts propagate: tier-level `except TimeoutError` in
  `async_backfill_range` accidentally swallows them (mislogged as "tier exceeded"),
  while job-boundary saves in `__init__.py` abort the whole job into generic failure.

## Decisions

| Decision | Choice |
| --- | --- |
| Checkpoint-timeout policy | **Deferred-batch gate** (revised in iterations 2, 11): the pre-import `dirty_from` marker must land durably — inline write with one retry — before ANY recorder mutation. On failure the whole batch defers (`BATCH_DEFERRED`): its days stay incomplete (not marked failed) for retry, nothing is imported, and the job continues with later batches. Post-import/progress/tier saves are debounced-resilient (safe to lose; next durable checkpoint absorbs them). Originally "log-and-continue importing"; revised after Copilot review showed importing without the marker silently drops boot repair for a crash mid-import. Iteration 11: marker set → durable save → recorder import → clear (+ clear-save) now run as one `import_lock` critical section in backfill batches, failed-range retries, and correction polling, so a concurrent importer cannot interleave markers and leave a crash without a valid repair boundary. Critical saves snapshot call-time state before any await (including the flush writer-wait). |
| Timed-out write ordering | **Shield + parked in-flight** (revised in iterations 6–7): `asyncio.wait_for` cannot cancel the executor-backed filesystem write once submitted, so each save task runs behind `asyncio.shield`, stays parked in `_SaveState.inflight` on timeout, and every later write — including the empty clear write and debounced retries — awaits it (bounded by the same 60s window) before writing newer payload; the dedupe hash is invalidated whenever a parked write is reconciled (running **or** already completed between saves), so a reverted payload forces a corrective rewrite instead of dedupe-skipping over newer on-disk content. Prevents an older write from finishing last and resurrecting stale checkpoint state or a       phantom recovery marker. Unload drops the Store immediately but keeps the per-entry coordination registered until the parked write drains, so a prompt config-entry reload orders new writes behind it instead of overlapping on a fresh Store instance (released only if unclaimed — `draining` marker). Reconcile and load await parked tasks unconditionally so a failed task's exception is always retrieved; when a reload's bounded wait times out it raises so `async_setup_entry` maps it to `ConfigEntryNotReady` and HA retries setup rather than hydrating stale checkpoint data. |
| Release version | **v0.10.4 exactly** (re-version if sibling fixes claim 0.10.2/0.10.3 first) |
| Timeout value | Single constant, 30 → 60s (not options-configurable) |
| Debounce window | 3.0 seconds |
| Approach | Coalescing writer + content-hash dedupe (1+2-lite) + timeout containment (5); skip full field-level dirty tracking |
| Release mechanics | Auto-publish on merge: `release.yml` creates `v0.10.4` tag + Latest from merged SHA; version must be final before merge |

## Steps

### Step 0 — Tracking plan *(this file)*
- [x] Save plan to `docs/plans/issue-33-import-state-save-timeout.md`; update checkboxes as work completes.

### Step 1 — `custom_components/pge_energy/const.py` ✅
- [x] `IMPORT_STATE_SAVE_TIMEOUT = 60.0` (was 30.0)
- [x] Add `IMPORT_STATE_SAVE_DEBOUNCE_SECONDS = 3.0`

### Step 2 — `custom_components/pge_energy/store.py` (core) ✅
- [x] Per-entry `_SaveState`: dirty flag, pending task ref (strong), last-written payload SHA-256
- [x] `critical=False` → mark dirty + schedule single debounced background write; return immediately.
      Bursts coalesce because callers share one mutable `ImportStoreData`; serialize at fire time.
- [x] `critical=True` → inline durable await unchanged (preserves `dirty_from` crash-safety checkpoint)
- [x] Content-hash dedupe (both paths): identical payload skips disk write AND the `last_commit` stamp
- [x] New `async_flush_import_state(hass, entry_id)`
- [x] Wire **discard-pending** into `async_clear_import_state` (`async_discard_pending_import_state`:
      cancel the debounced writer WITHOUT persisting its payload, then write empty state — revised
      in iteration 2 after Copilot flagged that flushing stale state first doubled I/O and could
      abort on slow-host timeout; iteration 3 routed the empty write through the bounded 60s path
      with digest recording)
- [x] Unload teardown: flush pending **before** `discard_store_cache` (`__init__.py`, `async_unload_entry`)
- [x] Keep constant read-at-call-time so `test_backfill_hang.py:418` monkeypatch keeps working

### Step 3 — Timeout containment ✅ (revised to gated durability in iterations 2–3)
- [x] Containment helpers implemented as **module-local wrappers** so existing test
      patch targets (`backfill.async_save_import_state` etc.) keep working:
      `backfill._async_save_checkpoint(durable=…)`, `coordinator._async_save_import_store_resilient`,
      `__init__._async_retry_checkpoint_save`. A shared `store.async_try_save_import_state`
      was tried first and removed because it bypassed per-module AsyncMock patches.
      Pre-import checkpoints are NOT suppress-and-continue: when they cannot land they gate
      recorder mutation. Retry policy differs by path (iteration 14 correction): backfill
      batches write inline with one retry (`_CHECKPOINT_SAVE_ATTEMPTS = 2`) and return
      `BATCH_DEFERRED` (hourly/daily/monthly leave covered days incomplete, not failed); the correction window
      soft-fails the cycle and retry-failed-ranges skips the day on a SINGLE timed-out
      attempt (no retry). Post-import clears are durable too, not debounced: correction
      saves synchronously with up to two attempts; only genuinely lossy saves (backfill
      post-import completion, tier progress) ride the debounced writer;
      terminal sync statuses persist fail-closed.
- [x] Apply in `_async_import_batch` (`backfill.py:206,228`)
- [x] Apply in tier loops (`backfill.py:323-328, 375, 399, 444, 450, 513`)
- [x] Soft-fail containment (iteration 7): `_async_soft_fail_poll` contains the terminal-write
      `TimeoutError` so slow storage cannot defeat the retained-data return; job-boundary and
      boot-repair terminal writes stay fail-closed. The parked in-flight save still lands the
      terminal status via the next durable checkpoint write.
- [x] Apply in retry-failed-ranges (`__init__.py:669,688`)
- [x] Apply in correction-window saves (`coordinator.py:1053,1095`)
- [x] Job-boundary saves and boot repair-completion (`coordinator.py:673`) keep fail-closed semantics

### Step 4 — Tests ✅
- [x] New `tests/components/pge_energy/test_store_save_coalescing.py`:
  - [x] burst of N non-critical saves → ≤2 disk writes, final payload wins
  - [x] critical flush completes before caller proceeds; call-order proves `dirty_from` durable before recorder import
  - [x] timeout matrix: non-critical swallows, critical raises, backfill continues past batch-save timeout
  - [x] dedupe skips redundant writes without bumping `last_commit`
  - [x] clear/unload resets pending debounce state
- [x] Audit save-count assertions in existing tests: full component suite (468) green unmodified
      once containment moved to module-local wrappers; terminal sync states persist via the
      durable path in `async_persist_sync_progress` instead of debounced.

### Step 5 — Docs + version ✅
- [x] `docs/ARCHITECTURE.md`: persistence section — debounce/dedupe semantics + containment trade-offs
- [x] VERSION → `0.10.4` in `const.py` + `manifest.json` (verified in sync); README example updated;
      panel ES-module cache suffixes bumped to `?v=0.10.4` on every relative import in
      `pge-panel.js` and `charts.js` per the documented VERSION invariant (iteration 7).
      Version is final pre-merge because merge = publish.

### Step 6 — Verification ✅ (re-run after iteration 34)
- [x] `ruff check` + `ruff format --check` clean; pytest components **531 passed**
      (base 468 + 63 added by this PR: 44 in `test_store_save_coalescing.py` covering
      coalescing/dedupe/timeout ordering, parked-save reconciliation/serialization,
      reload read ordering/binding, reset authority across iterations 6–34, stale
      discard/defer semantics, deferred-write dirty retry, bounded flush over a stuck
      mid-write writer, restore retry attached behind a drained parked write,
      timed-out clear re-raising bounded with a background restore, and result
      propagation; 9 coordinator tests for soft-fail timeout containment,
      import_lock-held checkpoint saves, backfill-reservation hold during reset,
      reset/import_lock ordering, correction failure marker retention with
      post-release repair, retained-marker skip gating, repair holding import_lock
      across clear+save, contained repair clear-save timeout with marker restore,
      and marker re-read under the lock; 10 backfill tests asserting the batch
      marker transaction holds `import_lock`, the retry rebinds after a reset swap,
      a stale-discarded checkpoint defers the batch, stale-generation orphans
      defer, fatal batches retain markers, fatal stops daily/monthly tiers, batch
      defers on a retained recovery marker, retry stops/skips while the marker is
      unrepaired, daily fatal gates monthly even after repair, and generation-stale
      deferral);
      recorder 4 passed; frontend node tests pass; secret scan passes.
      (mypy skipped: pinned HA 2026.7 needs py3.14 syntax, mypy config targets 3.12; CI runs no mypy job.)
- [x] Browser/API UAT against live HA (retained profile reused via symlink; this branch's code linked):
      boot clean; auth renewed; full poll + billing sync succeeded (`success: True`, 43.9s);
      `/pge` → 200, `pge-panel.js` → 200; 63 pge entities with 60 healthy (3 unknowns are the known
      portal HTTP-400 diagnostics: tod_vs_basic_savings / next_ptr_event_date / net_metering);
      **zero** `import state save timed out` lines; `.storage` import_state shows `sync_status=complete`,
      `dirty_from=null`, 2789 completed days, `last_commit` stamped seconds after poll end;
      `newest_interval=2026-08-21T08:00Z` (~1am Pacific tip = expected overnight publication lag).
      Live HA left running at http://127.0.0.1:8123 for HITL eyeball of `/pge`.

### Step 7 — Git workflow & PR ⛔ HITL gate = merge
- [x] Commits on `issue/33` (`325d3ad` plan, `47b0e6d` implementation, `76d2340` UAT results,
      plus `chore(lint)` fixing a pre-existing repo-wide ruff break in `scripts/probe_ptr_events.py`
      that prek exposed); pushed to origin
- [x] PR opened: https://github.com/spencerthayer/homeassistant-pge/pull/35 (base `main`, refs #33)
- [x] CI fully green on PR head SHA (test / hassfest / hacs / prek)
- [ ] Comment on issue #33 linking the PR
- [ ] ⛔ **DO NOT MERGE** — merge is the single HITL gate (HITL performs `gh pr merge --merge`)
- **Automatic upon merge (no manual release step):** push to `main` triggers
  `.github/workflows/release.yml` → version sanity check → `gh release create v0.10.4
  --target <merged-sha> --latest` (no-op if tag already exists) → HACS offers the upgrade.
  Never merge from a SHA with failing checks — the auto-release would be skipped or, worse,
  a later force-push could publish unverified code.
- [ ] Post-merge verification: Release workflow green on merged SHA; `v0.10.4` published as Latest
