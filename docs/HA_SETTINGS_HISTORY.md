# Configure options: sync, history, and manual sync

Settings → Devices & Services → **Portland General Electric Energy Usage** → **Configure**.

## Sync settings

| Option | Default | Notes |
| ------ | ------- | ----- |
| Polling interval + unit | `4` + `hours` | Value plus `minutes` / `hours` / `days`. Minute intervals are a fixed cadence (minimum 15). Hour/day intervals align to the Pacific sync clock grid. |
| Sync clock (`sync_local_time`) | `00:00:00` Pacific | Anchors the hour/day polling grid (e.g. every 4 hours → 12am / 4am / 8am / noon / 4pm / 8pm). |
| Correction window | `7` days | How far back each scheduled/manual refresh re-fetches for late PGE corrections. |
| History mode | Full history | `full` from the integration floor (`2019-01-01`) or `from_date` with an explicit start. |
| History start date | — | Used when history mode is `from_date`. |
| Hourly history days | `365` | Newest N local days request HOURLY; older gaps use DAILY then MONTHLY. |
| Auto backfill | on | Continues tiered history after each successful poll until the window is complete. |
| Include cost | on | Import interval cost into statistics / sensors. |
| Include diagnostics | on | Expose diagnostic sensors (auth expiry, last API error, sync progress, etc.). |
| Enable diagnostic capture (`capture_graphql_diagnostics`) | off | Bounded PGE GraphQL contract capture for issue #5 / program probes. Logs sanitized interval rows plus allowlisted schema discovery. Usage values remain private; enable only while testing and disable afterward. Does not alter imports or statistics. |
| Import billing & programs (`include_billing`) | on | Soft-fail billing/programs sync after usage poll. |
| Download bill PDFs (`download_bill_pdfs`) | off | Opt-in portal PDF fetch to `www/pge_energy/…` (`/local/…`). Requires `include_billing`. Parsing and 18 `_bill_pdf_*` statistics import run automatically when enabled. |
| Bill PDF form (`bill_pdf_form`) | `detailed` | `detailed` or `simplified` (maps to portal REST flags). |
| Bill PDF retention (`bill_pdf_retention`) | `latest` | Binary file retention: `latest`, `all_imported`, or `rolling_n`. Normalized Store records and recorder history are kept independently. |
| Bill PDF rolling count (`bill_pdf_rolling_count`) | `12` | When retention is `rolling_n`, keep this many newest statement PDF files. |
| Backfill concurrency | `2` | Parallel day fetches during backfill. |
| TOD rate overrides (`tod_rate_off_peak` / `_mid_peak` / `_on_peak` / `_basic_service`) | blank | Optional USD/kWh overrides. Leave blank to use last portal rate, then built-in defaults. Empty boxes must validate (blank is allowed — do not require a float). |

PGE publishes usage **overnight**, not continuously. A daytime-stuck **Latest available interval** near ~01:00 Pacific often means the portal has not published later hours yet — confirm against portlandgeneral.com My Energy Use (hourly) before treating it as an integration stall. A tip frozen at an older hour **while history backfill is running** was an HA skip-poll bug (fixed in 0.9.13): correction-window polls keep fetching during backfill, hourly backfill walks newest days first, and a refresh runs when backfill exits.

## History tiering

1. **HOURLY** for the newest `hourly_backfill_days`.
2. **DAILY** for older incomplete days (request windows padded to ≥31 days — shorter DAILY windows can hard-error on the live API).
3. **MONTHLY** for the oldest gaps (paged backwards). Monthly totals are **not** imported onto `_consumption` / `_cost` for months that already have finer completed days (avoids double-counting).

Services for the same bounds: `pge_energy.backfill`, `pge_energy.retry_failed_ranges`, `pge_energy.reset_import_checkpoint` (does not delete recorder history).

## Manual sync

Configure → **Manual sync**:

| Action                       | Behavior                                                                       |
| ---------------------------- | ------------------------------------------------------------------------------ |
| **Refresh now**              | Re-fetches the correction window (same idea as `pge_energy.refresh`).          |
| **Backfill missing history** | Tiered hourly → daily → monthly over the current Sync settings history bounds. |

One job per entry. If a job is already running, the flow shows status and a link to the device page instead of starting a second job.

After start, a persistent notification links to the device (`PGE <accountnum>`). Live progress sensors:

| Sensor          | Role                                                                                                                                       |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Sync status     | `idle` / `refreshing` / `backfilling` / `complete` / `failed`                                                                              |
| Sync phase      | `idle` / `correction` / `hourly` / `daily` / `monthly` / billing phases / `downloading_pdfs` / `parsing_pdfs` / `importing_pdf_statistics` |
| Sync progress   | `0`–`100` %                                                                                                                                |
| Sync ETA        | Remaining seconds (unknown until enough samples)                                                                                           |
| Sync detail     | Short line (e.g. `Hourly 42/120`)                                                                                                          |
| Sync last error | Cleared on a new job start                                                                                                                 |

The sidebar panel at `/pge` also mirrors sync progress for admins.

ETA is a linear extrapolation from completed work units; tier transitions make early estimates optimistic — use **Sync detail** for the current phase.

## Update credentials

Email / password only. Account number is read-only after setup. Statistic IDs and immutable `account_key` do not change.

## Bill PDFs (v0.7.0)

Opt-in download + local parsing of portal statement PDFs. **Default off.**

| Surface                   | Notes                                                                                                                                                      |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Configure → Sync settings | Master toggle, form, retention, rolling count.                                                                                                             |
| Services                  | `pge_energy.download_bill_pdf` (by known `bill_date` from Store index); `pge_energy.reparse_bill_pdfs` (retained files only, no network).                  |
| Sensors                   | `bill_pdf_parse_status` (diagnostic); 14 disabled-by-default line-item sensors; current bill amount/kWh attributes include PDF link/status when available. |
| Statistics                | 18 external sum series `pge_energy:<account_key>_bill_pdf_*` (statement-dated). GraphQL `_bill_amount` / `_bill_kwh` remain canonical.                     |
| Panel `/pge`              | **View bill PDF** link, parse badge, **Statement details (PDF)** table when a safe normalized record exists.                                               |
| Security                  | PDFs under `www/pge_energy/` are served at `/local/…` without HA login if the instance is exposed. See `SECURITY.md`.                                      |

Sync phases when enabled: `downloading_pdfs` → `parsing_pdfs` → `importing_pdf_statistics` (after structured billing). Failures are soft: retained PDFs, last-known normalized data, and GraphQL billing sensors stay available.
