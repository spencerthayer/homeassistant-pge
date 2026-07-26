# Configure options: sync, history, and manual sync

Settings → Devices & Services → **Portland General Electric Energy Usage** → **Configure**.

## Sync settings

| Option | Default | Notes |
|--------|---------|-------|
| Polling interval + unit | `4` + `hours` | Value plus `minutes` / `hours` / `days`. Minute intervals are a fixed cadence (minimum 15). Hour/day intervals align to the Pacific sync clock grid. |
| Sync clock (`sync_local_time`) | `00:00:00` Pacific | Anchors the hour/day polling grid (e.g. every 4 hours → 12am / 4am / 8am / noon / 4pm / 8pm). |
| Correction window | `7` days | How far back each scheduled/manual refresh re-fetches for late PGE corrections. |
| History mode | Full history | `full` from the integration floor (`2019-01-01`) or `from_date` with an explicit start. |
| History start date | — | Used when history mode is `from_date`. |
| Hourly history days | `365` | Newest N local days request HOURLY; older gaps use DAILY then MONTHLY. |
| Auto backfill | on | Continues tiered history after each successful poll until the window is complete. |
| Include cost | on | Import interval cost into statistics / sensors. |
| Include diagnostics | on | Expose diagnostic sensors (auth expiry, last API error, sync progress, etc.). |
| Import billing & programs (`include_billing`) | on | Soft-fail billing/programs sync after usage poll. |
| Backfill concurrency | `2` | Parallel day fetches during backfill. |

PGE publishes usage **overnight**, not continuously. A daytime-stuck **Latest available interval** near ~01:00 Pacific is expected.

## History tiering

1. **HOURLY** for the newest `hourly_backfill_days`.
2. **DAILY** for older incomplete days (request windows padded to ≥31 days — shorter DAILY windows can hard-error on the live API).
3. **MONTHLY** for the oldest gaps (paged backwards). Monthly totals are **not** imported onto `_consumption` / `_cost` for months that already have finer completed days (avoids double-counting).

Services for the same bounds: `pge_energy.backfill`, `pge_energy.retry_failed_ranges`, `pge_energy.reset_import_checkpoint` (does not delete recorder history).

## Manual sync

Configure → **Manual sync**:

| Action | Behavior |
|--------|----------|
| **Refresh now** | Re-fetches the correction window (same idea as `pge_energy.refresh`). |
| **Backfill missing history** | Tiered hourly → daily → monthly over the current Sync settings history bounds. |

One job per entry. If a job is already running, the flow shows status and a link to the device page instead of starting a second job.

After start, a persistent notification links to the device (`PGE <accountnum>`). Live progress sensors:

| Sensor | Role |
|--------|------|
| Sync status | `idle` / `refreshing` / `backfilling` / `complete` / `failed` |
| Sync phase | `idle` / `correction` / `hourly` / `daily` / `monthly` / billing phases |
| Sync progress | `0`–`100` % |
| Sync ETA | Remaining seconds (unknown until enough samples) |
| Sync detail | Short line (e.g. `Hourly 42/120`) |
| Sync last error | Cleared on a new job start |

The sidebar panel at `/pge` also mirrors sync progress for admins.

ETA is a linear extrapolation from completed work units; tier transitions make early estimates optimistic — use **Sync detail** for the current phase.

## Update credentials

Email / password only. Account number is read-only after setup. Statistic IDs and immutable `account_key` do not change.

## Bill PDFs (deferred)

v0.5 ships **structured** billing fields only (amounts, kWh, dates, enrollment). Portal bill PDF download via Apigee REST (`POST …/pge-bill-api/pdf/bills`) is a future option — not exposed in Configure today. When added, it will be an opt-in switch with retention controls so full-history PDF backfill does not spike disk use.
