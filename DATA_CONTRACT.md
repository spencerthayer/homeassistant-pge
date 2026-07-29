# PGE GraphQL API Data Contract

## Endpoint

```
POST https://apix.portlandgeneral.com/pge-graphql
```

## Required Headers

| Header                | Value                                        |
| --------------------- | -------------------------------------------- |
| `Authorization`       | `Bearer <token>`                             |
| `aws_graphql_server`  | `graphql_server`                             |
| `Content-Type`        | `application/json`                           |
| `Origin`              | `https://widget.portlandgeneral.com`         |
| `Referer`             | `https://widget.portlandgeneral.com/`        |

## Operation

**Name:** `GetUsageCompare`

## Query

```graphql
query GetUsageCompare($params: GetUsageCompareParams!) {
  getUsageCompare(params: $params) {
    isCustomerEnrolledInTOD
    acctType
    totalKwhUsage
    totalKwhCost
    hourlyUsageList | dailyUsageList | monthlyUsageList {
      efficientSimilarHomesKwh
      intervalTime
      kwh
      intervalSize
      usageStatus
      rank
      similarHomesKwh
      amount
      startDate
      endDate
      temperature
    }
  }
}
```

The returned usage list field depends on the `displayMode` parameter:

| `displayMode` | Field returned         |
| ------------- | ---------------------- |
| `HOURLY`      | `hourlyUsageList`      |
| `DAILY`       | `dailyUsageList`       |
| `MONTHLY`     | `monthlyUsageList`     |

## Variables

```json
{
  "params": {
    "startDate": "2026-06-07T00:00:00.000Z",
    "endDate": "2026-07-06T23:59:59.999Z",
    "displayMode": "HOURLY | DAILY | MONTHLY",
    "accountId": "<account_id>",
    "encryptedPersonId": "<encrypted_person_id>"
  }
}
```

## Response Structure

### Top-level fields

| Field                     | Type             | Example            |
| ------------------------- | ---------------- | ------------------ |
| `isCustomerEnrolledInTOD` | boolean          | `true`             |
| `acctType`                | string           | `"RES"`            |
| `totalKwhUsage`           | string or null   | `"1234.56"`        |
| `totalKwhCost`            | string or null   | `"234.56"`         |

### Usage list item fields (common)

| Field                      | Type                    |
| -------------------------- | ----------------------- |
| `intervalTime`             | string                  |
| `kwh`                      | string (decimal)        |
| `amount`                   | float or integer        |
| `intervalSize`             | integer or null         |
| `usageStatus`              | string or null          |
| `temperature`              | string or null          |
| `startDate`                | string or null          |
| `endDate`                  | string or null          |
| `similarHomesKwh`          | string or null          |
| `efficientSimilarHomesKwh` | string or null          |
| `rank`                     | null                    |

---

## Display Mode Details

### HOURLY

| Field                | Value                                                                            |
| -------------------- | -------------------------------------------------------------------------------- |
| `intervalTime`       | `"DD-MON-YYYY HH:MM:SS"` format — **local time** in `America/Los_Angeles` (e.g., `"01-JUL-2025 00:00:00"`) |
| `intervalSize`       | `900` (integer, minutes)                                                         |
| `kwh`                | string (decimal, e.g., `"1.57"`)                                                 |
| `amount`             | float (e.g., `0.29`)                                                             |
| `usageStatus`        | `"kWh-Delivered"`                                                                |
| `temperature`        | string (integer, Fahrenheit) or `null`                                           |
| `startDate`          | `null`                                                                           |
| `endDate`            | `null`                                                                           |
| `similarHomesKwh`    | `null`                                                                           |
| `efficientSimilarHomesKwh` | `null`                                                                       |
| `rank`               | `null`                                                                           |

- **Rows returned:** ~25 per closed day — 24 local-day hours **plus** a +1 boundary hour whose start equals `day_end` exactly. Consumers must filter interval starts to `[day_start, day_end)` and dedupe the shared boundary hour across adjacent day fetches.
- **Retention:** ~1 year back from current date
- **DST fall-back (Nov 2):** expect 25 rows including the boundary hour (24 in-range after filter)
- **DST spring-forward (Mar 8):** expect 24 rows including the boundary hour (23 in-range after filter)
- **`totalKwhUsage` / `totalKwhCost`:** often `null` for HOURLY — do not rely on response totals; sum interval `kwh` / `amount` instead

### DAILY

| Field                | Value                                                                            |
| -------------------- | -------------------------------------------------------------------------------- |
| `intervalTime`       | `"YYYY-MM-DD-00.00.00"` format (e.g., `"2026-06-07-00.00.00"`)                  |
| `startDate`          | ISO 8601 UTC (e.g., `"2026-06-07T07:00:00.000Z"`) — note: 7-hour offset from local midnight |
| `endDate`            | ISO 8601 UTC (e.g., `"2026-06-08T07:00:00.000Z"`)                               |
| `intervalSize`       | `null`                                                                           |
| `kwh`                | string (e.g., `"47.0"`)                                                          |
| `amount`             | integer (e.g., `10`)                                                             |
| `usageStatus`        | `null`                                                                           |
| `temperature`        | string (float, e.g., `"56.96"`) or `null`                                        |
| `similarHomesKwh`    | string or `null`                                                                 |
| `efficientSimilarHomesKwh` | string or `null`                                                             |
| `rank`               | `null`                                                                           |

- **Rows returned:** ~31 per successful chunk
- **Retention:** ~5 years back
- **Short windows:** DAILY ranges under ~31 days may hard-error with GraphQL `"Something unexpected happened"`. For live validation prefer HOURLY (yesterday) or a DAILY window ≥ ~31 days.
- **`totalKwhUsage` / `totalKwhCost`:** typically populated for DAILY (unlike HOURLY/MONTHLY)

### MONTHLY

| Field                | Value                                                                            |
| -------------------- | -------------------------------------------------------------------------------- |
| `intervalTime`       | `"YYYY-MM-DD-00.00.00"` format                                                   |
| `startDate`          | ISO 8601 UTC                                                                     |
| `endDate`            | ISO 8601 UTC                                                                     |
| `intervalSize`       | `null`                                                                           |
| `kwh`                | string                                                                           |
| `amount`             | integer (sometimes `0`)                                                          |
| `usageStatus`        | `null`                                                                           |
| `temperature`        | `null`                                                                           |
| `similarHomesKwh`    | string or `null`                                                                 |
| `efficientSimilarHomesKwh` | string or `null`                                                             |
| `rank`               | `null`                                                                           |

- **Rows returned:** latest ~12 **billing periods** relative to the requested **end** (not absolute “always newest”). Page the window backwards for older history via `get_monthly_usage_paged`.
- **Gotcha:** requesting `end = last incomplete day` can omit the open billing cycle that still covers that day (live: `end=2021-07-31` returned periods through `2021-06-08` only, dropping `2021-07-08→2021-08-06`). Backfill must page from **yesterday** back to the gap start.
- **Bounds:** periods are billing cycles, not calendar months — day coverage uses raw `startDate`/`endDate`; statistic placement uses calendar-month starts.
- **Retention:** oldest observed ~2019-11 for this account; days before the oldest period have no PGE history.
- **`totalKwhUsage` / `totalKwhCost`:** often `null` for MONTHLY — sum period rows instead

---

## Home Assistant consumption of this contract

- **Setup validation:** HOURLY yesterday (not short DAILY).
- **Poll / correction:** HOURLY one local day per request; clip starts to `[day_start, day_end)`.
  - Scheduled poll (default every **4 hours** from **00:00** America/Los_Angeles) always re-fetches the correction window.
  - If yesterday’s hourly is still gap/empty (PGE not finished publishing), **still import any hours returned**, demote the day from `completed_local_dates`, and **catch up every 2 hours** until yesterday validates complete — do not leave a stale daily midnight lump until the next grid slot.
- **History backfill (tiered):**
  1. HOURLY for newest `hourly_backfill_days`
  2. DAILY for older gaps (request windows padded to ≥31 days)
  3. MONTHLY via `get_monthly_usage_paged` from **yesterday** back through the gap; mark days before the oldest period complete (no PGE history); mark billing-period-covered days complete even if month-start statistic import conflicts with finer hourly rows
  - **Do not import MONTHLY into `_consumption`/`_cost` when that calendar month already has any completed finer day** — still close the gap days. Parking a full billing-period total on month-start atop hourly rows double-counts (live: 2025-09-01 showed 677 kWh = 648 monthly lump + ~29 hourly).
  - On finer import / startup repair: zero any `state ≥ 200 kWh` (or `≥ $50` cost) row that shares a Pacific day with smaller sibling rows, then rebuild cumulative sums.
- Daily import rows use local-midnight starts; monthly use calendar month starts for external sum statistics **only when the month has no finer history**.
- Interval `temperature` (when present) is imported as external statistic `pge_energy:<account_key>_temperature` (mean °F, no cumulative sum) alongside `_consumption` / `_cost`.
- The same hourly rows are mirrored onto recorder entity statistics for `sensor.pge_*_energy`, `sensor.pge_*_cost`, and `sensor.pge_*_outdoor_temperature` so entity pickers and Statistics graphs can use them.
- User controls: Configure → Sync settings (`docs/HA_SETTINGS_HISTORY.md`).

## Account / billing / programs (structured)

Same Apigee endpoint (`https://apix.portlandgeneral.com/pge-graphql`) and bearer as usage. Prefer portal Origin/Referer (`https://portlandgeneral.com`). Implemented in `billing_api.py`.

### `getAccountDetailList` (`AccountDetailListParams!`)

- **Purpose:** account summary, latest bill details, Auto Pay / paperless flags, encrypted account / person / premise / SA ids.
- **Typical variables:** `{ accountStatus: "ACTIVE", groupId: "ALL_ACCTS", paging, sort, filter }`.
- **Key fields:** `billInfo.{amountDue,dueDate,lastPaymentAmount,lastPaymentDate,billDetails…}`, `autoPay.isEnrolled`, `isPaperlessBillEnrolled.result`, `premiseInfo[].encryptedPremiseId`, `saDetails[].encryptedSAId`, `viewBillAverageTemperature.currentBillingPeriod.averageTemperature`.
- **Identity note:** AccountDetail `encryptedAccountNumber` can differ from `getAccountInfo` group defaults — prefer AccountDetail for programs/history.

### Nested `AccountDetail.paymentHistory` (`PaymentHistoryParams`)

- **Purpose:** BILL + PAYMENT ledger (amount due / paid, kWh, period bounds, encrypted bill id).
- **Paging:** `php.pagingParams.{limit,offset}` + `sortDirection: "DESC"`; `totalDetailsRecords` is the full count (~tens of rows for typical residential).
- **Account match:** multi-account logins return multiple `accounts[]` rows — select by plaintext `accountNumber` and/or `encryptedAccountNumber` for the bound entry; never assume `accounts[0]`. Unmatched targets raise (no silent first-account fallback). List paging limit is 50.
- **Do not use** `getViewPaymentHistoryChargeSummary` — live portal returns opaque GraphQL errors; nested history is the working path.
- **WAF note:** keep the paymentHistory field selection compact (one-line selection); some multiline documents have returned HTTP 403 from Apigee.
- **Refresh after complete:** once the ledger checkpoint is complete, only the newest page is re-read; older bill/payment corrections are not re-fetched (reset the import Store to re-page).

### `getEnergyTrackerData` (`EnergyTrackerDataParams`) — open-cycle estimates

Backs the portal “Current Use” card (est. current charges, billing-cycle day, est. next bill range). Verified live 2026-07-24 against the card values.

- **Variables:** `{ params: { encryptedAccountNumber, encryptedPersonId } }` — both `String`, both from `getAccountDetailList.accounts[]` for the bound account.
- **Fields:** `detailsAvailable`, `hasMoreThan15DaysOfData`, `details.{billingCycleDay, numberOfBillingDays, billToDateAmount, minProjectedAmount, maxProjectedAmount}`, `currentBillingPeriod.totalKwh`, `previousBillingPeriod.totalKwh`.
- **Portal rendering:** amounts are floored to whole dollars in the UI (`$186.3` → `$186`); the API returns cents.
- **Companion op:** `getEnergyTrackerUserInfo(encryptedAccountNumber: String)` → `{ mainAccountPersonId, premiseIds }` returned `null` for a residential account and is not required.
- **Gate:** `getAccountDetails.pgeEnergyTracker.energyTrackerInfo.showEnergyTracker` plus `detailsAvailable` control whether the portal shows the card.
- **Discrepancy note:** `currentBillingPeriod.totalKwh` does not match a raw sum of imported hourly intervals over the same open period (live sample: 358 vs ~554 kWh) — treat these estimates as a separate PGE-provided series, not a cross-check of interval imports.
- **Probe:** packaged CLI `billing-snapshot` / live portal Current Use card (maintainer notes in `docs/LIVE_TESTING.md`).
- **HA import:** fetched in `billing_sync` after the ledger, soft-failing to the previous value; surfaced as sensors (`est_current_charges`, `est_next_bill_min`/`_max`, `billing_cycle_day`, `billing_cycle_total_days`) and panel “PGE est.” cards. No statistics are published — these are estimates that get revised daily.

### Programs

- **Status:** `getProgramsEnrollmentStatusDetails` with `{ encryptedAccountNumber, encryptedPremiseId, encryptedSaId }`.
- **Detail ops (best-effort):** Peak Time (`encryptedAccountNumber` + `ptrMockServerDate: ""`), Renewables (`encryptedServiceAgreementId`), TOD (`encryptedAccountNumber` + `encryptedServiceAgreementId`), Smart Thermostat (`encryptedAccountNumber`).
- **HA import:** enrollment flags + YTD / on-bill flex earnings; dual-publish mean series for YTD savings. PDF bill download is deferred (see `docs/HA_SETTINGS_HISTORY.md`).

### Bill PDF REST / parsing feasibility (probed, not shipped)

- **Download:** `POST https://apix.portlandgeneral.com/pge-bill-api/pdf/bills` with the Apigee bearer, portal Origin/Referer, and `{ encryptedBillId, isSummary: false, isNonDetailed: false }` for the detailed form.
- **Live probe (2026-07-28):** HTTP 200 `application/pdf`, valid `%PDF` bytes, 3 pages / ~126 KB. `pypdf` extracted ~13,300 characters in memory, so the sampled detailed bill is text-backed and does not require OCR. Layout extraction warned about rotated text.
- **Normalization spike:** the public sample-bill vocabulary supports typed USD/kWh fields and statement-dated history samples, but the first strict parser recovered only part of the live layout and failed GraphQL reconciliation (missing due date/kWh and mismatched amount due). This is a useful fail-closed result: never publish PDF-derived statistics unless required fields and GraphQL identity values reconcile.
- **Privacy:** raw PDF text contains account/address data. Tests use synthetic/public-sample text, serialization omits raw text and personal identifiers, and the live probe did not save the PDF or extracted plaintext.

### Billing statistics suffixes

External `pge_energy:<account_key>_*` (+ mirrored entity stats): `_account_balance`, `_amount_due`, `_last_payment_amount`, `_bill_avg_temperature`, `_ytd_program_savings` (mean); `_bill_amount`, `_bill_kwh`, `_payment_amount` (sum from ledger).

## Panel websocket API (`/pge`)

Admin-only commands used by `frontend/pge-panel.js`. Payloads never include passwords, tokens, or encrypted identity fields.

### `pge_energy/accounts`

- **Request:** `{ "type": "pge_energy/accounts" }`
- **Result:** `{ "accounts": [ … ] }` — one object per loaded config entry:
  - `entry_id`, `title`, `account_id`, `account_key`, `device_id`
  - `options` — `include_billing`, `include_cost`, `include_diagnostics`, polling/history settings
  - `statistic_ids` — map of role → `pge_energy:<account_key>_<suffix>` for all 11 external series
  - `entity_ids` — map of role → resolved `sensor.*` / `binary_sensor.*` (or `null`)

### `pge_energy/sync/subscribe`

- **Request:** `{ "type": "pge_energy/sync/subscribe" }`
- **Result:** empty ack, then **events** `{ "entries": [ … ] }` on subscribe and whenever any coordinator listener fires.
- Each entry: `status`, `phase`, `done`, `total`, `percent`, `eta_seconds`, `message`, `error`, freshness timestamps, `auth_expiration`, `last_api_error`.
- Unsubscribe tears down coordinator listeners on connection close.

Chart series are **not** served by a custom command — the panel calls Home Assistant’s built-in `recorder/statistics_during_period` with the statistic ids from `accounts`.

## Known API Behaviors

- **Publication is overnight / daily, not real-time.** PGE does not continuously publish new hourly intervals through the day. During daytime polls the newest available tip often sits near the early-morning Pacific hour (commonly ~`01:00` local / `08:00Z` in PDT) until the next overnight drop. Treat “Latest available interval” as newest *published*, not wall-clock freshness. The integration defaults to polling **every 4 hours** on a Pacific clock grid (`sync_local_time` default **00:00**) so overnight publication is picked up without waiting a full day.
- **HTTP 502 transient errors** occur intermittently — retry with backoff.
- **MONTHLY** returns the latest ~12 billing periods regardless of range width.
- **DAILY** short windows (<~31d) may hard-error; use ≥31d or HOURLY for validation.
- **HOURLY** day requests return ~25 rows (+1 boundary hour at `day_end`); filter to `[day_start, day_end)`.
- **Response totals** (`totalKwhUsage` / `totalKwhCost`) are reliable mainly for DAILY; HOURLY/MONTHLY often leave them null.
- **Hidden CSV endpoint** exists at `/pge-bill-api/usageCompare/download` but returned HTTP 500 at time of analysis.
