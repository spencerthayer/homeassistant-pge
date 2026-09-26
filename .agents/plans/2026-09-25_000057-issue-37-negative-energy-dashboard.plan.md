---
name: Fix issue 37 negative Energy consumption
overview: Harden the hourly publication frontier and coarse/fine statistics repair so synthetic recorder invariants prevent negative Energy deltas, without inventing export data or purging history.
todos:
  - id: task-1-branch-baseline
    content: Create the issue-37 branch and record a focused green baseline
    status: completed
    dependencies: []
  - id: task-2-recorder-red-test
    content: Add synthetic recorder contract tests for coarse and frontier sequences
    status: completed
    dependencies:
      - task-1-branch-baseline
  - id: task-3-collision-safe-merge
    content: Make cumulative overlay replacement collision-safe and monotonic
    status: completed
    dependencies:
      - task-2-recorder-red-test
  - id: task-4-startup-repair-red-test
    content: Add synthetic tests for existing sparse coarse/fine collision repair
    status: completed
    dependencies:
      - task-3-collision-safe-merge
  - id: task-5-coarse-fine-repair
    content: Extend startup repair to daily and monthly coarse collisions
    status: completed
    dependencies:
      - task-4-startup-repair-red-test
  - id: task-6-backfill-red-test
    content: Add a backfill regression for a gapped active hourly frontier
    status: completed
    dependencies:
      - task-3-collision-safe-merge
      - task-5-coarse-fine-repair
  - id: task-7-frontier-guard
    content: Prevent coarse tiers from completing the active hourly frontier
    status: completed
    dependencies:
      - task-6-backfill-red-test
  - id: task-8-document-contract
    content: Document the repaired import and repair contracts
    status: in_progress
    dependencies:
      - task-5-coarse-fine-repair
      - task-7-frontier-guard
  - id: task-9-bump-version
    content: Bump the PATCH version in every shipped location
    status: completed
    dependencies:
      - task-8-document-contract
  - id: task-10-verify-live
    content: Run focused, full-suite, and live Home Assistant verification
    status: completed
    dependencies:
      - task-9-bump-version
  - id: task-11-ship-gate
    content: Commit, push, pass CI, and stop at merge and release authorization gates
    status: completed
    dependencies:
      - task-10-verify-live
isProject: false
---

# Fix issue 37 negative Energy consumption Implementation Plan

**Goal:** Prevent the reported moving negative daily consumption value in Home Assistant Energy while preserving valid hourly import/export history, historical tiered backfill, and retained recorder data. The affected account and its recorder database are unavailable, so acceptance relies on synthetic recorder invariants and code-level risks rather than direct reproduction.

**Architecture:** Keep the existing recorder `state` + cumulative `sum` model. Prevent an incomplete day inside the configured hourly window from falling through to DAILY/MONTHLY completion, make same-timestamp coarse/fine replacement preserve cumulative monotonicity, and extend the existing startup collision repair to cover stale DAILY/MONTHLY rows. Do not convert coarse net negatives into fabricated return data and do not purge recorder history.

**Tech Stack:** Python 3.12+, Home Assistant custom integration and recorder statistics, pytest/pytest-homeassistant-custom-component, Ruff, GitHub Actions, HACS.

---

## Current context and observed facts

- Issue #37 reports one negative Energy-dashboard bar, always on the latest publication-frontier day, while Developer Tools shows no negative hourly `state` values.
- The reported magnitude is approximately 175 kWh. The exact affected recorder row is not present in the repository, so the magnitude is a hypothesis fixture value, not observed account data.
- `backfill.py::_async_backfill_hourly` validates a closed day, imports any clipped partial hours, and leaves invalid days incomplete.
- `backfill.py::async_backfill_range` then sends every remaining incomplete day to DAILY and then MONTHLY. The coarse tiers can import a row and mark the same gapped frontier day complete.
- `backfill.py::_normalize_daily_interval` places DAILY data at Pacific midnight. That timestamp can collide with the first HOURLY row.
- `statistics.py::_scrub_monthly_lumps_for_days` skips an existing lump whose timestamp is also in the finer overlay. A partial hourly import can therefore replace a daily-sized state at the same start without a monotonicity guard.
- `statistics.py::_async_upsert_cumulative_overlay` rebuilds cumulative rows from `_async_anchor_sum` plus non-negative states, but acknowledgement verifies exact `state` only. A row can be present with an undesirable cumulative transition.
- `statistics.py::async_repair_monthly_hourly_collisions` runs on startup through `coordinator.async_repair_monthly_collisions_if_needed`, but only recognizes monthly-sized collisions. A stale DAILY row can survive.
- `usage_direction.py::split_signed_usage` correctly maps HOURLY signed import/export and deliberately refuses to fabricate gross return/compensation from DAILY/MONTHLY net values. Preserve this contract.
- The signed-state migration in version 0.10.5 is not a repair for this issue: it targets negative fine-grained `state` rows, while the report says those states are already non-negative.
- We do not have access to the affected account, its Home Assistant instance, or its recorder database, and the reporter cannot provide that data. The exact affected row sequence is unavailable; do not request it or block implementation on it.

### Scope boundary

This plan covers only the negative Energy consumption/statistics path. The billing `Access forbidden` soft failure and deprecated device-registry lookup reported in the same notification are separate issues and must not be folded into this fix. Do not repeat or persist account identifiers in tests, logs, screenshots, commits, or the plan.

### Diagnosis status and operating assumption

Diagnosis is unconfirmed and cannot be completed from the affected installation. Code inspection identifies three independently actionable risks: the gapped hourly frontier can be completed by coarse tiers, a same-start DAILY/HOURLY collision has no explicit monotonicity contract, and startup repair does not recognize stale DAILY collisions.

Do not gate implementation on reproducing the reported historical magnitude. Build a synthetic recorder contract matrix that exercises every coarse/fine ordering we can generate and enforces nondecreasing Energy boundary deltas. Then remove each code-level risk conservatively. If a synthetic case passes before the fix, retain it as a contract test; it proves the invariant, not that the reporter's exact failure was reproduced. The release notes and issue comment must describe the change as a defensive fix pending reporter confirmation.

---

## Adaptive execution contract

Once implementation is authorized, repeat this loop until the objective is verified or no useful in-scope action remains:

1. **Read and reconcile.** Read this plan and compare its checkpoint with the actual branch, worktree, version, Store schema, tests, and live HA state. Preserve user changes. Mark one task `in_progress` only when all dependencies are `completed`.
2. **Check and record.** Before each dependent action, record timestamp, task/environment, expected result, observation, outcome (`pass`, `fail`, `inconclusive`, or `not applicable`), and a sanitized evidence reference in the Evidence and decisions log. An expected red test is a pass only when it fails for the intended behavior, not from setup/import failure.
3. **Correct the plan.** If evidence disproves a mechanism, preserve the failed evidence, revise the active instructions and affected dependencies, and identify which checks must be reopened. Do not force the original diagnosis.
4. **Act within scope.** Implement the smallest evidence-supported correction. Do not broaden into billing, device-registry deprecation, frontend rendering, account cleanup, or destructive recorder maintenance.
5. **Revalidate.** Rerun only checks invalidated by a correction. Keep exact-state acknowledgement, dirty-marker recovery, soft-fail behavior, hourly signed direction, and entity-statistic mirrors intact.
6. **Checkpoint and continue.** Update frontmatter statuses, body instructions, Mermaid marks/edges, checkpoint, and evidence together before yielding. Save an exact next action and blocker, if any.

If the same check fails again without new evidence, change the diagnostic method. Do not repeat an unchanged retry. If a plan-file update fails, restore the ability to record state before further mutations.

## Current execution checkpoint

| Field | Current state |
|---|---|
| Phase | Ship gate reached: committed, pushed, green CI, stopped for authorization |
| Active task | None |
| Last confirmed result | PR #38 head `d635281`: `CI` success (`test`, `hassfest`, `hacs` all `success`) and `Prek Checks` success on that exact SHA |
| Current approach | Stop. Every technical step in the plan is done |
| Blockers / open decisions | Merge and HACS `v0.10.6` release are unauthorized. Issue #37 stays open until the reporter retests |
| Next action | Ask the user to authorize the merge of PR #38, then the HACS release |

## Task dependency graph

```mermaid
flowchart TD
  subgraph discover [Discover]
    task_1_branch_baseline["☑ task-1-branch-baseline<br/>Create issue-37 branch and record baseline"]
    task_2_recorder_red_test(["☑ task-2-recorder-red-test<br/>Exercise coarse and frontier sequences in recorder"])
  end
  subgraph implement [Implement]
    task_3_collision_safe_merge{{"☑ task-3-collision-safe-merge<br/>Make cumulative replacement collision-safe"}}
    task_4_startup_repair_red_test(["☑ task-4-startup-repair-red-test<br/>Exercise existing collision repair synthetically"])
    task_5_coarse_fine_repair{{"☑ task-5-coarse-fine-repair<br/>Repair daily and monthly coarse collisions"}}
    task_6_backfill_red_test(["☑ task-6-backfill-red-test<br/>Reproduce frontier coarse fallback"])
    task_7_frontier_guard{{"☑ task-7-frontier-guard<br/>Keep active hourly frontier incomplete"}}
  end
  subgraph closeout [Closeout]
    task_8_document_contract("☑ task-8-document-contract<br/>Document import and repair contracts")
    task_9_bump_version{{"☑ task-9-bump-version<br/>Sync PATCH version locations"}}
    task_10_verify_live(["☑ task-10-verify-live<br/>Run local and live verification"])
    task_11_ship_gate{"☑ task-11-ship-gate<br/>Commit, push, CI, authorization gates"}
  end
  task_1_branch_baseline -->|clean named branch| task_2_recorder_red_test
  task_2_recorder_red_test -->|intended red behavior| task_3_collision_safe_merge
  task_3_collision_safe_merge -->|merge invariant fixed| task_4_startup_repair_red_test
  task_4_startup_repair_red_test -->|existing collision reproduced| task_5_coarse_fine_repair
  task_3_collision_safe_merge -->|statistics contract stable| task_6_backfill_red_test
  task_5_coarse_fine_repair -->|startup repair available| task_6_backfill_red_test
  task_6_backfill_red_test -->|frontier fallback reproduced| task_7_frontier_guard
  task_5_coarse_fine_repair -->|repair behavior verified| task_8_document_contract
  task_7_frontier_guard -->|tier behavior verified| task_8_document_contract
  task_8_document_contract -->|docs and task ledger current| task_9_bump_version
  task_9_bump_version -->|shipped files synchronized| task_10_verify_live
  task_10_verify_live -->|acceptance evidence recorded| task_11_ship_gate
  classDef evidence fill:#ede9fe,stroke:#7c3aed,color:#111827
  classDef data fill:#fee2e2,stroke:#dc2626,color:#111827
  classDef runtime fill:#ffedd5,stroke:#ea580c,color:#111827
  classDef gate fill:#111827,stroke:#f59e0b,color:#f8fafc
  class task_1_branch_baseline, task_8_document_contract evidence
  class task_2_recorder_red_test, task_4_startup_repair_red_test, task_6_backfill_red_test, task_10_verify_live runtime
  class task_3_collision_safe_merge, task_5_coarse_fine_repair, task_7_frontier_guard, task_9_bump_version data
  class task_11_ship_gate gate
  style discover fill:#f5f3ff,stroke:#7c3aed,color:#111827
  style implement fill:#fff7f7,stroke:#dc2626,color:#111827
  style closeout fill:#f8fafc,stroke:#111827,color:#111827
  style task_1_branch_baseline stroke-width:4px
  style task_2_recorder_red_test stroke-width:4px
  style task_3_collision_safe_merge stroke-width:4px
  style task_4_startup_repair_red_test stroke-width:4px
  style task_5_coarse_fine_repair stroke-width:4px
  style task_6_backfill_red_test stroke-width:4px
  style task_7_frontier_guard stroke-width:4px
  style task_8_document_contract stroke-width:4px
  style task_9_bump_version stroke-width:4px
  style task_10_verify_live stroke-width:4px
  style task_11_ship_gate stroke-width:4px
```

---

### Task 1: Create the issue branch and record the baseline

**Objective:** Establish a clean, named implementation branch and prove the existing focused tests are green before changing behavior.

**Files:**
- Modify: this plan only, for execution state/evidence
- No production files yet

**Step 1: Reconcile the branch**

- If local or remote `issue-37` exists, check it out and preserve its work.
- Otherwise create exactly `issue-37` from the current integration branch (`dev` at planning time), not from detached HEAD.
- Do not commit on `dev`, `main`, or a detached HEAD.

**Step 2: Record the baseline**

Run:

```bash
.venv/bin/python -m pytest \
  tests/components/pge_energy/test_day_validation.py \
  tests/components/pge_energy/test_usage_direction.py \
  tests/components/pge_energy/test_monthly_collision_scrub.py \
  tests/components/pge_energy/test_statistics_ack.py \
  tests/components/pge_energy/test_backfill_monthly.py \
  tests/components/pge_energy/test_coordinator.py -q
```

Expected: exit 0. If the focused baseline is red, record the exact existing failure and fix/rebase prerequisites before adding the regression.

**Step 3: Checkpoint**

Record branch, starting SHA, Python version, test exit/result, and any pre-existing worktree changes. Do not rerun user-reported failures without new evidence.

---

### Task 2: Exercise coarse and frontier sequences in the recorder

**Objective:** Build a deterministic contract matrix that proves import, merge, and repair keep Energy boundary deltas non-negative across every coarse/fine ordering we can generate, without relying on affected-account data.

**Files:**
- Modify: `tests/recorder/test_statistics_recorder.py`
- Modify: `tests/components/pge_energy/test_statistics_ack.py` only if a focused generated-row assertion belongs there

**Step 1: Extend the recorder fixture**

- Allow `_interval(...)` to create explicit `UsageResolution.HOURLY`, `DAILY`, and `MONTHLY` rows.
- Use synthetic values only: predecessor cumulative sum `S`, a representative 175 kWh DAILY row at Pacific midnight, and sparse/complete HOURLY frontiers. The 175 value is a scenario, not recovered account data.
- Capture the exact imported external rows and mirrored entity rows. Do not assert call counts, source text, or incidental defaults.

**Step 2: Add the contract matrix**

Read persisted rows back with Home Assistant's statistics query and calculate the Energy boundary delta as the last sum at period end minus the last sum before period start. Cover partial hourly → DAILY, DAILY → partial hourly, partial hourly → DAILY → partial hourly, partial hourly → DAILY → complete hourly, DAILY → complete hourly, and the 23/25-hour DST cases. Assert:

1. Every persisted `state` is non-negative.
2. The affected day's end sum is not lower than the predecessor boundary sum.
3. No same-start replacement introduces a negative Energy-period delta.
4. A complete local day can replace the DAILY row without retaining the coarse double count.
5. External and mirrored entity statistics carry the same accepted cumulative rows.

**Step 3: Run and interpret the matrix**

```bash
.venv/bin/python -m pytest tests/recorder/test_statistics_recorder.py -p homeassistant -o addopts= -q
```

Record the result for every sequence. A failure is the reproduction we can use. A pass is still a valid contract test and does not prove the reporter's exact instance. Continue with the independently proven code risks in Tasks 3–5; do not block on a synthetic red result and do not claim the reported issue was reproduced locally.

**Step 4: Keep the matrix account-independent**

The test must not require a real PGE login, `.env` values, an affected statistic key, or a live recorder database. Missing access to the reported instance is an accepted, permanent limitation of this fix.

---

### Task 3: Make cumulative replacement collision-safe

**Objective:** Ensure every accepted cumulative suffix is monotonic and semantically matches the replacement states without fabricating return or deleting history.

**Files:**
- Modify: `custom_components/pge_energy/statistics.py:507-527,658-777,905-968,1108-1199`
- Test: `tests/recorder/test_statistics_recorder.py`
- Test: `tests/components/pge_energy/test_statistics_ack.py`
- Test: `tests/components/pge_energy/test_monthly_collision_scrub.py`

**Step 1: Implement the collision policy established by the matrix**

- If an existing DAILY-sized row shares its timestamp with only a partial HOURLY overlay, do not replace that cumulative slot with the first hour. Defer the same-start replacement until the local day is complete.
- If a stale coarse row has a timestamp not present in the finer overlay and finer rows prove the collision, zero the coarse row and rebuild from the predecessor.
- Once a complete local day validates, allow HOURLY rows to replace the DAILY row atomically; the 23/25-hour DST cases must work.
- Preserve MONTHLY collision handling and deep-history behavior except for the startup repair extension in Task 5.
- Do not use `running = max(running, old_same_start_sum)` as a blanket fix; that can preserve a total inconsistent with the accepted state row.

**Step 2: Preserve direction semantics**

Keep `split_signed_usage` unchanged for HOURLY import/export. If the synthetic matrix shows that a negative DAILY/MONTHLY row overwrites a valid timestamp with a synthetic zero row, filter that coarse consumption overlay at `_directional_overlays` while preserving any independently valid portal cost. Do not invent `_return` or `_compensation` from coarse net data.

**Step 3: Strengthen verification only where needed**

If exact state acknowledgement can pass while the persisted cumulative row is stale, pass expected sums through the existing acknowledgement path and compare them after the recorder queue drains. Preserve bounded re-issue behavior and hard consumption versus soft cost/return/compensation handling.

**Step 4: Run focused checks**

```bash
.venv/bin/python -m pytest \
  tests/recorder/test_statistics_recorder.py \
  tests/components/pge_energy/test_statistics.py \
  tests/components/pge_energy/test_statistics_ack.py \
  tests/components/pge_energy/test_monthly_collision_scrub.py \
  -p homeassistant -o addopts= -q
```

Expected: all pass; sparse, same-start, and full-day collision cases remain distinct.

---

### Task 4: Exercise existing-history repair without account data

**Objective:** Prove that the current startup repair leaves a stale DAILY frontier lump beside sparse HOURLY rows, then cover the repair without an affected recorder database.

**Files:**
- Modify: `tests/recorder/test_statistics_recorder.py`
- Modify: `tests/components/pge_energy/test_monthly_collision_scrub.py`

**Step 1: Add the synthetic startup-repair test**

Pre-populate the test recorder with a synthetic prior day, a 175 kWh DAILY row at local midnight, and a few smaller HOURLY siblings. Run the existing startup repair function and assert:

- the coarse row is removed/zeroed only when finer evidence identifies the collision;
- cumulative sums are rebuilt from the predecessor;
- no period delta becomes negative;
- mirrored entity statistics receive the same repaired rows;
- a deep-history MONTHLY-only row with no finer sibling remains untouched.

**Step 2: Run the test**

```bash
.venv/bin/python -m pytest \
  tests/recorder/test_statistics_recorder.py \
  tests/components/pge_energy/test_monthly_collision_scrub.py \
  -p homeassistant -o addopts= -q
```

Expected: the daily-collision case fails because startup repair currently recognizes only the 200 kWh MONTHLY threshold. A pass would still leave the frontier behavior in Task 6 as the separately proven code defect.

---

### Task 5: Extend startup repair to coarse/fine collisions

**Objective:** Repair existing DAILY and MONTHLY collisions through the existing idempotent startup pass without a new Store schema or destructive purge.

**Files:**
- Modify: `custom_components/pge_energy/statistics.py:905-1099`
- Modify: `custom_components/pge_energy/coordinator.py:66-70,739-754`
- Modify: `custom_components/pge_energy/__init__.py:217-237`
- Test: `tests/components/pge_energy/test_monthly_collision_scrub.py`
- Test: `tests/recorder/test_statistics_recorder.py`

**Step 1: Rename the internal contract cleanly**

Because the responsibility expands beyond MONTHLY, rename the statistics function, coordinator wrapper, call site, and tests to `coarse/fine` terminology. Migrate every caller and remove the old name; do not add a compatibility alias.

**Step 2: Extend collision classification**

- Reuse `DAILY_LUMP_MIN_KWH`, `DAILY_LUMP_MIN_COST`, `MONTHLY_LUMP_MIN_KWH`, and `MONTHLY_LUMP_MIN_COST` rather than inventing another threshold.
- Treat a large local-midnight row with smaller same-day siblings as a DAILY collision candidate.
- Preserve the existing 200 kWh MONTHLY classification.
- Do not lower `MONTHLY_LUMP_MIN_KWH` merely because the issue estimate is 175 kWh; 175 may be DAILY, and changing the monthly heuristic without recorder evidence risks deleting valid deep-history data.
- Zero only proven collision rows, rebuild the affected suffix, acknowledge exact writes, mirror repaired rows, and return to a no-op on later startups.

**Step 3: Run repair tests**

```bash
.venv/bin/python -m pytest \
  tests/components/pge_energy/test_monthly_collision_scrub.py \
  tests/recorder/test_statistics_recorder.py \
  -p homeassistant -o addopts= -q
```

Expected: existing deep-history tests and new sparse-frontier repair tests pass.

---

### Task 6: Reproduce coarse fallback from a gapped hourly frontier

**Objective:** Prove that yesterday's invalid HOURLY response currently falls through to DAILY/MONTHLY and becomes complete.

**Files:**
- Create: `tests/components/pge_energy/test_backfill_frontier.py`

**Step 1: Add the orchestration regression**

Mock yesterday as the newest closed day with a contiguous-prefix HOURLY response that validates as `gap`. Return coarse DAILY and MONTHLY values. Run `async_backfill_range` and assert the intended contract:

- yesterday remains in `failed_local_dates`, not `completed_local_dates`;
- no DAILY or MONTHLY statistic is imported for yesterday;
- older days outside the configured hourly window can still use coarse fallback;
- when `hourly_backfill_days=0`, the user-disabled hourly tier does not block intentional coarse fallback.

**Step 2: Run the red test**

```bash
.venv/bin/python -m pytest tests/components/pge_energy/test_backfill_frontier.py -q
```

Expected: the first three assertions fail on current code because the coarse tiers see yesterday as merely incomplete.

---

### Task 7: Keep the active hourly frontier on the hourly tier

**Objective:** Defer coarse fallback only for the active publication frontier while preserving historical tiering.

**Files:**
- Modify: `custom_components/pge_energy/backfill.py:365-462,481-545,548-676,679-802`
- Test: `tests/components/pge_energy/test_backfill_frontier.py`
- Regression: `tests/components/pge_energy/test_backfill_monthly.py`
- Regression: `tests/components/pge_energy/test_backfill_hang.py`
- Regression: `tests/components/pge_energy/test_coordinator.py:618-714`

**Step 1: Add a focused frontier predicate**

Compute the blocked set from facts already available:

- `today_local() - 1 day` is inside the computed `hourly_range`;
- that date remains incomplete after `_async_backfill_hourly`;
- coarse fallback would otherwise import/complete it.

Do not infer frontier status from account size, a magic negative value, or a fixed 175 kWh threshold.

**Step 2: Filter coarse tiers by exact dates**

Pass a blocked-date set into DAILY and MONTHLY internal functions and remove those dates before import and before `_mark_completed`. Range-only filtering is insufficient because the frontier may be in the middle of a requested month window. If every requested day is blocked, skip that coarse request. Keep monthly fetch-end paging through yesterday so older billing-period coverage is unchanged.

**Step 3: Preserve correction behavior**

Keep the existing correction poll behavior: partial HOURLY rows are imported, the day is demoted from completed, and catch-up retries continue. The expected temporary state is incomplete/failed while PGE publishes yesterday, not coarse completion.

**Step 4: Run focused checks**

```bash
.venv/bin/python -m pytest \
  tests/components/pge_energy/test_backfill_frontier.py \
  tests/components/pge_energy/test_backfill_monthly.py \
  tests/components/pge_energy/test_backfill_hang.py \
  tests/components/pge_energy/test_coordinator.py -q
```

Expected: all pass; old historical monthly completion and newest-first hourly behavior remain intact.

---

### Task 8: Document the repaired contract

**Objective:** Keep architecture, data-contract, user recovery guidance, and the task ledger consistent with the code.

**Files:**
- Modify: `docs/ARCHITECTURE.md:67-98`
- Modify: `docs/DATA_CONTRACT.md:98-120,197-212`
- Modify: `README.md:304-318` only if user recovery/config guidance changes
- Modify: `tasks.md` with an Issue #37 section and updated `Active agents`

**Step 1: Document behavior**

State that:

- a gapped day inside the configured hourly window is not completed by DAILY/MONTHLY;
- DAILY/MONTHLY remain historical fallbacks outside that window or when hourly is disabled;
- cumulative consumption/cost sums are rebuilt monotonically across coarse/fine replacement;
- same-start partial replacement is deferred until the local day is complete;
- startup repair overwrites only proven coarse collisions and preserves unmatched deep-history rows;
- coarse net negatives still do not fabricate return/compensation;
- the fix is defensive because the affected instance and exact historical row sequence are unavailable; reporter confirmation is post-release, not a release gate.

**Step 2: Update the ledger**

Record completed implementation/tests, live-UAT state, CI state, and explicit remaining merge/release authorization. Do not paste issue screenshots, account numbers, statistic keys, credentials, or raw logs.

---

### Task 9: Bump the shipped PATCH version

**Objective:** Keep HACS, runtime, frontend cache busts, and README aligned for the bug fix.

**Files:**
- Modify: `custom_components/pge_energy/const.py` `VERSION`
- Modify: `custom_components/pge_energy/manifest.json` `version`
- Modify: `custom_components/pge_energy/frontend/charts.js` import `?v=`
- Modify: `custom_components/pge_energy/frontend/pge-panel.js` import `?v=`
- Modify: `README.md:19-21` concrete release example
- Modify: `tasks.md` version/release state

**Step 1: Choose SemVer**

Use PATCH `0.10.6` unless implementation introduces a new option, sensor, service, or backward-compatible capability. This is a bug fix with no intended API expansion.

**Step 2: Synchronize all locations**

Replace every shipped occurrence of `0.10.5` that denotes the current release. Do not change historical release notes or changelog history.

**Step 3: Verify synchronization**

```bash
.venv/bin/python -m json.tool custom_components/pge_energy/manifest.json >/dev/null
.venv/bin/python -m pytest tests/components/pge_energy/test_migrate.py -q
```

Expected: valid manifest and green version/migration checks.

---

### Task 10: Run focused, full-suite, and live verification

**Objective:** Prove the synthetic recorder invariants, full-suite health, and no regressions in our own live Home Assistant. The reported negative cannot be reproduced locally.

**Files:**
- No new files
- Update this plan and `tasks.md` with evidence

**Step 1: Run focused verification**

```bash
.venv/bin/python -m pytest \
  tests/components/pge_energy/test_backfill_frontier.py \
  tests/components/pge_energy/test_backfill_monthly.py \
  tests/components/pge_energy/test_backfill_hang.py \
  tests/components/pge_energy/test_coordinator.py \
  tests/components/pge_energy/test_monthly_collision_scrub.py \
  tests/components/pge_energy/test_statistics.py \
  tests/components/pge_energy/test_statistics_ack.py -q

.venv/bin/python -m pytest tests/recorder -p homeassistant -o addopts= -q
.venv/bin/python -m ruff check custom_components/pge_energy tests/components/pge_energy tests/recorder
```

Expected: all focused tests and Ruff pass.

**Step 2: Run the canonical full suite**

```bash
bash scripts/run_tests.sh
```

Expected: component tests, recorder tests, frontend Node tests, and secret scan all pass.

**Step 3: Restart live Home Assistant fully**

```bash
./scripts/stop.sh
./scripts/start.sh
```

Do not use config-entry reload for Python changes. Reuse the existing live HA lifecycle; do not start an ad-hoc second instance.

**Step 4: Verify available regression surfaces**

In a real browser against the maintainer's own live Home Assistant:

1. Hard-refresh `/pge` so `?v=0.10.6` modules load.
2. Confirm Usage, Range accounting, and sync status populate; no blank shell or unexpected `unavailable` sensors.
3. In Developer Tools → Statistics, inspect on-the-hour `state` and `sum` around the current frontier. Confirm no new negative boundary delta and no coarse/fine double count on the available account.
4. Open stock Home Assistant Energy and confirm the available account still has non-negative daily Grid consumption.
5. Trigger/observe manual sync until the latest closed day validates as complete hourly data. Sync status must be `complete` with no failed backfill days. If PGE is still publication-gapped, record this as inconclusive rather than a pass.
6. Confirm retained billing, programs, and panel data remain available; usage-statistics repair must not blank or purge them.

This instance is not the affected account. A clean Energy dashboard here is a no-regression check, not reproduction or resolution evidence. Record the issue reproduction status as unavailable by design.

**Step 5: Record acceptance evidence**

Record only sanitized dates/stat suffixes, commands, exit codes, visible no-regression observations, and the statement that affected-account confirmation is unavailable. No account identifiers or credentials.

---

### Task 11: Commit, push, pass CI, and stop at authorization gates

**Objective:** Deliver the HACS-compatible change without unauthorized merge or release side effects.

**Files:**
- Modify: this plan and `tasks.md` with final evidence/state

**Step 1: Commit on the named branch**

Before committing, confirm `git branch --show-current` is exactly `issue-37`. Commit the code, tests, docs, task ledger, and version changes together. Do not commit if HEAD is detached.

**Step 2: Push and open/update the PR**

Push `issue-37` to `origin`; opening/updating a PR is allowed. Do not merge.

**Step 3: Wait for green CI on the exact SHA**

Required jobs from `.github/workflows/ci.yml`:

- canonical full test suite;
- Home Assistant hassfest;
- HACS validation.

Use the SHA-specific Actions run and require conclusion `success` for every job. Fix and push again on failure; do not release from red or pending CI.

**Step 4: Stop for explicit HITL authorization**

- Never merge without explicit current-conversation authorization for this PR. Prefer a merge commit when authorized.
- Never run `gh release create` or otherwise publish HACS Latest without explicit current-conversation release authorization, even when CI is green.
- After an authorized merge, target the release at the merged green SHA. If an already-published version needs replacing, do not move/delete it without explicit authorization; advance PATCH instead.
- After release, leave the issue open or post a sanitized retest request as appropriate. Do not require reporter data before release and do not close the issue on our own non-reproducing instance.

---

## Acceptance criteria

1. **AC1 — Energy integrity (synthetic):** Every generated coarse/fine sequence in the recorder matrix produces a non-negative Energy boundary delta. Direct affected-account verification is explicitly unavailable and tracked as optional post-release confirmation.
2. **AC2 — State/sum integrity:** Recorder `state` remains non-negative where expected, persisted cumulative `sum` is monotonic, and external/entity mirror rows agree.
3. **AC3 — Frontier behavior:** A gapped newest closed day inside the configured hourly window stays incomplete and is not imported/completed by DAILY or MONTHLY.
4. **AC4 — Historical behavior:** Days outside the hourly window still use DAILY then MONTHLY fallback; disabling hourly backfill still permits intentional coarse import.
5. **AC5 — Existing-history recovery:** Proven stale coarse/fine collisions are repaired idempotently without deleting unmatched deep-history rows or fabricating export.
6. **AC6 — Operational safety:** Consumption write failures remain hard failures, other series remain soft failures, dirty-marker repair works, and no secrets/account identifiers enter the repository.
7. **AC7 — Verification:** Focused tests, recorder contract tests, full suite, and the maintainer's own live `/pge` plus Energy dashboard pass as no-regression checks; live UAT is documented as non-reproducing because the affected instance is unavailable.
8. **AC8 — Ship readiness:** Docs, `tasks.md`, version locations, named-branch commit, pushed SHA, green CI, PR, authorized merge, and authorized HACS release are recorded in order.

## Risks and open questions

- **No affected instance:** We cannot obtain the affected account, recorder rows, or Home Assistant configuration, so the exact root cause remains unconfirmed. Treat the change as defensive invariant hardening. Do not claim issue resolution from a non-reproducing local instance; reporter retest is post-release confirmation.
- **PGE publication lag:** Blocking coarse fallback can leave yesterday incomplete until hourly publication. This is intentional. The existing two-hour correction retry owns convergence; sync completion is a live acceptance requirement, not an assumption.
- **Already-lowered sums:** Without the affected recorder database we cannot determine whether an already-lowered sum still has collision evidence available for repair. Never add a destructive purge; report the limitation instead.
- **Heuristic false positives:** Daily/monthly size heuristics can misclassify an unusually large real hourly value. Restrict daily candidates to Pacific midnight with smaller same-day siblings and keep all existing thresholds unless the synthetic contract matrix demonstrates a change is necessary.
- **Same-timestamp representation:** A daily total and midnight hourly sample cannot occupy two state rows. The contract matrix must prove whether to defer, redistribute, or rebuild; never clamp the cumulative sum independently of its state.
- **Cost parity:** The consumption fix must not leave `_cost` with the same collision. Apply collision policy consistently to cumulative energy and cost overlays while preserving their different hard/soft failure behavior.
- **Release authority:** Green CI does not authorize merge or HACS publication.

## Evidence and decisions log

| When | Task / environment | Expected vs observed | Outcome / evidence | Correction or next action |
|---|---|---|---|---|
| 2026-09-25 | Planning / repository `dev` at `9be2ee0` | Named integration branch and current version are known | Observed `dev`, version `0.10.5` in `manifest.json` | Create/check out `issue-37` only when implementation starts |
| 2026-09-25 | Planning / issue #37 | Report distinguishes negative Energy delta from negative Developer Tools states | Observed issue narrative: one moving frontier-day bar; no negative states | Build recorder red test before production edits |
| 2026-09-25 | Planning / `backfill.py`, `day_validation.py` | Invalid hourly frontier should not become coarse-complete | Observed invalid hourly days remain incomplete, then all remaining days enter DAILY/MONTHLY | Add exact-date coarse block in Task 7 after red test |
| 2026-09-25 | Planning / `statistics.py` | Fine overlay collision should be monotonic | Observed same-start overlay replaces existing state; startup repair only recognizes monthly-sized collisions | Add recorder and startup-repair red tests; do not guess a clamp |
| 2026-09-25 | Planning / `usage_direction.py` | HOURLY direction and coarse net semantics remain correct | Observed explicit contract: coarse negatives do not fabricate return/compensation | Preserve unless a failing recorder test proves a separate overwrite defect |
| 2026-09-25 | Planning / access constraint | Original plan assumed affected `state`/`sum` evidence might be obtained for exact reproduction | Confirmed: no access to the affected account or Home Assistant recorder DB, and the reporter cannot supply it | `Affected-instance data unavailable -> synthetic recorder contract matrix plus conservative code-risk hardening; affected confirmation moved to optional post-release reporter follow-up; invalidated the exact-reproduction gate in Task 2 and live resolution claim in Task 10/AC1` |
| 2026-09-25 | Planning / tests | No baseline or runtime reproduction claimed | No tests, live HA actions, commits, pushes, or releases run during planning | Begin Task 1 only after implementation authorization |
| 2026-09-25 | Implementation start / repository | Begin only on a named ticket branch with a clean worktree | Observed `dev` at `608d4a8` with clean worktree; `issue-37` did not exist | Create `issue-37` from current `dev`; preserve the existing plan commit as the starting point |
| 2026-09-25 | Task 1 / `issue-37` branch | Named branch from current integration head; focused baseline green | Created `issue-37` from `608d4a8`; `61 passed, 6 warnings` exit 0 | Mark task 1 complete; start synthetic recorder contract matrix |
| 2026-09-25 | Task 2 / recorder matrix | Coarse/fine orderings expose a wrong Energy-period total | `3 failed, 4 passed`: `partial_then_daily` 177 vs 175, `daily_then_partial` 3 vs 175, `partial_daily_partial` 4 vs 175; 24/23/25-hour day cases all reproduce the same three; no `sum` decrease in any case | Direction correction: the reported negative is not reproducible synthetically; the proven defect is coarse/fine double count and total loss. Task 3 reconciles the collision instead of clamping `sum` |
| 2026-09-25 | Decision / Task 3 | Original plan assumed a synthetic negative `sum` transition would be reproducible | Matrix shows monotonic `sum` in every ordering; the wrong values are the day totals | `Negative-sum hypothesis -> coarse/fine reconciliation; no blanket sum clamp; no claim that the reporter's negative was reproduced` |
| 2026-09-25 | Task 3 / collision reconciliation | Coarse totals own incomplete finer days; complete finer days replace them | `_reconcile_coarse_fine_rows` handles both arrival orders; recorder matrix `7 passed`, collision + ack units `12 passed`, Ruff clean | Mark task 3 complete; cover the same rule in startup repair |
| 2026-09-25 | Decision / Task 3 | Plan proposed deferring only the same-start replacement | Matrix required the whole finer day to defer, and the coarse row to win when it arrives after fine rows | `Same-start-only defer -> whole-day reconciliation in both directions; monthly-sized lumps keep the existing retire-on-finer-row behavior` |
| 2026-09-25 | Task 4/5 / startup repair | Stored DAILY lump beside partial hours must resolve idempotently | Red first (`0 == 3`), then green: repaired to `[175, 0, 0, 0]`, second pass cleared `0`; recorder `8 passed`, repair + coordinator `39 passed`; renamed to `async_repair_coarse_fine_collisions` with no compatibility alias | Mark tasks 4 and 5 complete; move to the backfill frontier guard |
| 2026-09-25 | Decision / Task 5 | Plan proposed zeroing the DAILY lump during startup repair | Zeroing the lump drops the only complete total for the day (`175 -> 3`), so the finer rows defer instead | `Zero the daily lump -> zero the finer rows while the stored day is incomplete; a complete stored day retires the lump; monthly-sized lumps keep retiring immediately` |
| 2026-09-25 | Task 6/7 / frontier guard | A gapped day inside the hourly window must not be completed by DAILY/MONTHLY while older gaps still can | Red first (frontier completed and failure cleared), then green with `blocked_days` on both coarse tiers; backfill + coordinator `66 passed`, Ruff clean | Mark tasks 6 and 7 complete; document the contract |
| 2026-09-25 | Decision / Task 6 | Plan proposed a new `tests/components/pge_energy/test_backfill_frontier.py` | Reusing `_make_coordinator` from `test_backfill_hang.py` avoids duplicating the coordinator fixture | `New test file -> add test_gapped_hourly_frontier_skips_coarse_tiers to test_backfill_hang.py; no new fixture module` |
| 2026-09-25 | Task 8/9 / docs and version | Contract documented and PATCH version synchronized | `ARCHITECTURE.md` items 4-7, `DATA_CONTRACT.md` history section, `tasks.md` issue #37 section; `0.10.6` in const/manifest/frontend/README; `test_migrate.py` `2 passed` | Mark tasks 8 and 9 complete; run full verification |
| 2026-09-25 | Task 10 / local suite | Focused and canonical suites green | `bash scripts/run_tests.sh`: `533 passed`, recorder `8 passed`, node `41 pass`, secret scan passed | Mark task 10 local half complete |
| 2026-09-25 | Task 10 / live UAT | Own instance shows no regression after a full process restart | `/pge` loaded `?v=0.10.6`, KPIs populated, Sync status `complete` 100% with no failed days, latest interval Sep 25 01:00 PT; Energy dashboard Grid 350 Wh / Home 350 Wh with a positive bar; recorder DB over 2019-11 to 2026-09 shows zero negative Pacific day totals and zero negative states; 24 hourly rows on each recent day | No-regression evidence recorded; affected-account confirmation stays post-release |
| 2026-09-25 | Task 10 / startup repair live | One-time repair then stable no-op | First restart: `Cleared 6 coarse/fine collision row(s) ... rebuilt sums from 2025-08-01T07:00:00+00:00`; second restart: zero repair lines, zero recorder `UNIQUE constraint` errors, zero pge errors | The 4 unique-constraint errors were a one-time startup race with HA `compile_missing_statistics` on the first repair write; clean on the second run |
| 2026-09-25 | Task 11 / commit and push | Named branch, one commit, pushed, PR open | Committed `a140bc1` on `issue-37` (17 files), pushed `origin/issue-37`, opened PR #38 | No merge or release performed |
| 2026-09-25 | Decision / Task 11 | PR was opened against `dev` | `ci.yml` only triggers on `main`; prior feature PRs (#24, #25, #35) targeted `main` | `PR base dev -> main so the CI workflow runs; no code impact` |
| 2026-09-25 | Task 11 / CI | A run should start for `a140bc1` after the retarget | No run listed for `a140bc1` after repeated checks | Waiting on GitHub Actions; release stays blocked until a green run on this SHA |
| 2026-09-25 | Task 11 / CI final check | A run should exist for `a140bc1` after the retarget | `actions/runs?branch=issue-37` returned zero runs; PR #38 is open with `base=main` | `Task 11 stays in_progress: no green CI run on this SHA, and merge/release are unauthorized. Next action is the user's merge and release decision` |
| 2026-09-25 | Task 11 / CI trigger | The retarget alone should start a run | It did not; reopening PR #38 fired the `pull_request` event and CI started | `Retarget-only -> close/reopen the PR to emit pull_request; no code change needed` |
| 2026-09-25 | Task 11 / CI failures | CI green on the first push | Run `36212437190` Prek failed on `ruff-format` (`backfill.py`, `test_backfill_hang.py`), then `36212518440` CI `test` failed on `test_startup_repair_resolves_stale_daily_lump` (`assert 0 == 3`) | Fixed by `f0b9378` (ruff format) and `d635281` (drain the recorder queue with `async_wait_recorder_queue` before the repair reads rows); local full suite green after both |
| 2026-09-25 | Task 11 / CI green | All required jobs success on the PR head | `d635281`: `CI` `success` (`test`, `hassfest`, `hacs`) and `Prek Checks` `success` | Task 11 complete; merge and release still require explicit authorization |
