# PGE GraphQL API Data Contract

## Endpoint

```none
POST https://apix.portlandgeneral.com/pge-graphql
```

## Required Headers

| Header               | Value                                 |
| -------------------- | ------------------------------------- |
| `Authorization`      | `Bearer <token>`                      |
| `aws_graphql_server` | `graphql_server`                      |
| `Content-Type`       | `application/json`                    |
| `Origin`             | `https://widget.portlandgeneral.com`  |
| `Referer`            | `https://widget.portlandgeneral.com/` |

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

| `displayMode` | Field returned     |
| ------------- | ------------------ |
| `HOURLY`      | `hourlyUsageList`  |
| `DAILY`       | `dailyUsageList`   |
| `MONTHLY`     | `monthlyUsageList` |

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

| Field                     | Type           | Example     |
| ------------------------- | -------------- | ----------- |
| `isCustomerEnrolledInTOD` | boolean        | `true`      |
| `acctType`                | string         | `"RES"`     |
| `totalKwhUsage`           | string or null | `"1234.56"` |
| `totalKwhCost`            | string or null | `"234.56"`  |

### Usage list item fields (common)

| Field                      | Type             |
| -------------------------- | ---------------- |
| `intervalTime`             | string           |
| `kwh`                      | string (decimal) |
| `amount`                   | float or integer |
| `intervalSize`             | integer or null  |
| `usageStatus`              | string or null   |
| `temperature`              | string or null   |
| `startDate`                | string or null   |
| `endDate`                  | string or null   |
| `similarHomesKwh`          | string or null   |
| `efficientSimilarHomesKwh` | string or null   |
| `rank`                     | null             |

### Grid import / export (signed HOURLY usage, v0.8.0)

Generating-account capture ([#5](https://github.com/spencerthayer/homeassistant-pge/issues/5)) established that HOURLY `getUsageCompare` is a **signed net-flow** series:

- Positive `kwh` / `amount` → grid import / import cost
- Negative `kwh` / `amount` → grid export / export compensation
- `usageStatus` remains `"kWh-Delivered"` for both signs (not a direction discriminator)
- One row per interval start (`max_rows_per_start = 1`); no separate delivered/received rows
- Explicit `kwh: null` (with timestamp) is an unavailable sample — keep the start for day contiguity, skip energy/cost writes, preserve temperature when present, and mark the closed day `complete_with_gap` so backfill does not loop through failing DAILY/MONTHLY tiers
- DAILY/MONTHLY net totals must **not** fabricate gross `_return` / `_compensation` (offsetting import+export inside the period is lost). MONTHLY rows with `kwh=0` and positive `amount` are fixed/base charges into `_cost` only

Published statistics:

| Direction | External statistic | Notes |
| --- | --- | --- |
| Grid import | `pge_energy:<account_key>_consumption` | non-negative; HA Energy “imported from grid”; display name `PGE <account> consumption` |
| Grid export | `pge_energy:<account_key>_return` | non-negative; HOURLY signed rows only |
| Import cost | `pge_energy:<account_key>_cost` | `max(0, amount)` |
| Export compensation | `pge_energy:<account_key>_compensation` | only when hourly `kwh < 0` and `amount < 0` |

A one-time Store-gated migration (`signed_usage_split_migration_done`) rewrites proven fine-grained negative `_consumption` / `_cost` states into `_return` / `_compensation`. Coarse monthly lumps are left alone when source grain cannot be proven.

**Panel projection (v0.9.1):** `/pge` never mutates recorder series. `projectDirectionalUsage` builds a view model at each grain: grid flow = `consumption − return` (positive import / negative export); net interval amount = `cost − compensation` only when the selected range contains at least one **positive** compensation credit (`> 0`), otherwise import cost. A zero-only compensation series stays in import-cost mode. Missing compensation for a whole range is not treated as zero credit. This is an interval estimate — not PGE’s statement credit bank (`getNetMeteringDetails` monthly buckets are published separately as diagnostic fields).

`getNetMeteringDetails` statement/credit-bucket fields are fetched best-effort when solar return history or a net-metering program row is present; units/signs stay diagnostic until generating-account UAT confirms them. They must not rewrite `_cost` / `_compensation`.

The default-off `capture_graphql_diagnostics` switch remains available for follow-up captures; it does not change production import.

---

## Display Mode Details

### HOURLY

| Field                      | Value                                                                                                      |
| -------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `intervalTime`             | `"DD-MON-YYYY HH:MM:SS"` format — **local time** in `America/Los_Angeles` (e.g., `"01-JUL-2025 00:00:00"`) |
| `intervalSize`             | `900` (integer, minutes)                                                                                   |
| `kwh`                      | string (decimal, e.g., `"1.57"`)                                                                           |
| `amount`                   | float (e.g., `0.29`)                                                                                       |
| `usageStatus`              | `"kWh-Delivered"`                                                                                          |
| `temperature`              | string (integer, Fahrenheit) or `null`                                                                     |
| `startDate`                | `null`                                                                                                     |
| `endDate`                  | `null`                                                                                                     |
| `similarHomesKwh`          | `null`                                                                                                     |
| `efficientSimilarHomesKwh` | `null`                                                                                                     |
| `rank`                     | `null`                                                                                                     |

- **Rows returned:** ~25 per closed day — 24 local-day hours **plus** a +1 boundary hour whose start equals `day_end` exactly. Consumers must filter interval starts to `[day_start, day_end)` and dedupe the shared boundary hour across adjacent day fetches.
- **Retention:** ~1 year back from current date
- **DST fall-back (Nov 2):** expect 25 rows including the boundary hour (24 in-range after filter)
- **DST spring-forward (Mar 8):** expect 24 rows including the boundary hour (23 in-range after filter)
- **`totalKwhUsage` / `totalKwhCost`:** often `null` for HOURLY — do not rely on response totals; sum interval `kwh` / `amount` instead

### DAILY

| Field                      | Value                                                                                       |
| -------------------------- | ------------------------------------------------------------------------------------------- |
| `intervalTime`             | `"YYYY-MM-DD-00.00.00"` format (e.g., `"2026-06-07-00.00.00"`)                              |
| `startDate`                | ISO 8601 UTC (e.g., `"2026-06-07T07:00:00.000Z"`) — note: 7-hour offset from local midnight |
| `endDate`                  | ISO 8601 UTC (e.g., `"2026-06-08T07:00:00.000Z"`)                                           |
| `intervalSize`             | `null`                                                                                      |
| `kwh`                      | string (e.g., `"47.0"`)                                                                     |
| `amount`                   | integer (e.g., `10`)                                                                        |
| `usageStatus`              | `null`                                                                                      |
| `temperature`              | string (float, e.g., `"56.96"`) or `null`                                                   |
| `similarHomesKwh`          | string or `null`                                                                            |
| `efficientSimilarHomesKwh` | string or `null`                                                                            |
| `rank`                     | `null`                                                                                      |

- **Rows returned:** ~31 per successful chunk
- **Retention:** ~5 years back
- **Short windows:** DAILY ranges under ~31 days may hard-error with GraphQL `"Something unexpected happened"`. For live validation prefer HOURLY (yesterday) or a DAILY window ≥ ~31 days.
- **`totalKwhUsage` / `totalKwhCost`:** typically populated for DAILY (unlike HOURLY/MONTHLY)

### MONTHLY

| Field                      | Value                          |
| -------------------------- | ------------------------------ |
| `intervalTime`             | `"YYYY-MM-DD-00.00.00"` format |
| `startDate`                | ISO 8601 UTC                   |
| `endDate`                  | ISO 8601 UTC                   |
| `intervalSize`             | `null`                         |
| `kwh`                      | string                         |
| `amount`                   | integer (sometimes `0`)        |
| `usageStatus`              | `null`                         |
| `temperature`              | `null`                         |
| `similarHomesKwh`          | string or `null`               |
| `efficientSimilarHomesKwh` | string or `null`               |
| `rank`                     | `null`                         |

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

### Account discovery (credential setup / renew)

Credential login discovers which account numbers belong to the login **before** usage validation:

1. `getAccountInfo` — returns `accountMeta` plus each group's `defaultAccount.accountNumber` only (non-default accounts are not selected by the document).
2. `getAccountDetailList` with `groupId: "ALL_ACCTS"` and `accountStatus: "ACTIVE"` — portal account-switcher source; returns every ACTIVE `accounts[].accountNumber` (paging limit 50).
3. Merge: union of defaults + detail-list rows (exact-string dedupe, defaults first). Soft-fail detail-list errors and keep defaults so single-account flows never regress.
4. Config flow still requires the user-entered number to match a discovered id (exact or digits-only). Empty discovery still accepts the typed value for usage validation.

**Caveat:** discovery keeps `accountStatus: "ACTIVE"`. Inactive/closed accounts that remain browsable on the portal may still fail with `account_not_found` until a separate status strategy is justified.

### `getAccountDetailList` (`AccountDetailListParams!`)

- **Purpose:** account summary, latest bill details, Auto Pay / paperless flags, encrypted account / person / premise / SA ids; also used to **enumerate ACTIVE accounts** during credential discovery (`portal_auth`).
- **Typical variables:** `{ accountStatus: "ACTIVE", groupId: "ALL_ACCTS", paging, sort, filter }`.
- **Key fields:** `billInfo.{amountDue,dueDate,lastPaymentAmount,lastPaymentDate,billDetails…}`, `autoPay.isEnrolled`, `isPaperlessBillEnrolled.result`, `premiseInfo[].encryptedPremiseId`, `saDetails[].encryptedSAId`, `viewBillAverageTemperature.currentBillingPeriod.averageTemperature`.
- **Identity note:** AccountDetail `encryptedAccountNumber` can differ from `getAccountInfo` group defaults — prefer AccountDetail for programs/history.
- **Multi-account:** logins with multiple ACTIVE accounts return multiple `accounts[]` rows (issue #20).

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

### `getTimeOfDayPricingDetails` — REMOVED (v0.9.1)

This speculative GraphQL operation was never verified against a live portal and has been removed. The `get_tod_pricing` API method and its billing-sync caller `_async_fetch_tod_snapshot` no longer exist.

- **Resolution chain:** account overrides (`tod_rate_off_peak`/`_mid_peak`/`_on_peak`/`_basic_service`) → retained last-good portal `TodSnapshot` (when present; restored from the Store by `async_load_store`, no live op populates it in v0.9.1) → built-in defaults (`DEFAULT_TOD_RATES` / `DEFAULT_BASIC_RATE`). Period definitions, holiday rules, and the offline engine live in `tod_schedule.py`; resolution in `tod_pricing.resolve_tod_rates`.
- **Replacement ops:** `getTimeOfDayEnrollmentDetails` now carries `annualLookBackEarnedCredit`, `offPeakCharges`, `midPeakCharges`, `onPeakCharges`, `planSavings` as diagnostic attributes on the TOD binary sensor. `getRateCompare` (params: `{ accountNumber }`) returns `touTotal`, `basicTotal`, `savings`, `comparisonPeriod` — persisted as a diagnostic `RateCompareSnapshot` on the coordinator; its `savings` aggregate powers the `tod_vs_basic_savings` sensor fallback and the panel's official “PGE TOD vs Basic savings” block (see below). Neither op is used to derive per-period ¢/kWh rates.

### `getRateCompare` (`RateCompareParams!`) — v0.9.1+

- **Purpose:** aggregate TOD vs Basic cost comparison (diagnostic + portal savings surface).
- **Variables:** `{ params: { accountNumber } }` — plaintext account number (not encrypted).
- **Fields:** `touTotal`, `basicTotal`, `savings`, `comparisonPeriod`.
- **Consumers (v0.9.1):** `savings` feeds `sensor.pge_*_tod_vs_basic_savings` when the legacy pricing-plan `savings_total` snapshot is absent, the `tod.rate_compare` block of the `pge_energy/accounts` websocket payload, and the official “PGE TOD vs Basic savings” card on `/pge#tod`. Per-period rates are never derived from these aggregates.
- **Panel local estimate (v0.9.2+):** `/pge#tod` does **not** use `getRateCompare` totals for the local hero. `computeTodPlanCompare` prices the selected window’s imported hourly kWh at effective TOD rates and compares that to **billed imported cost** (not to `DEFAULT_BASIC_RATE` × kWh). Inferred ¢/kWh is billed ÷ kWh. `todEnrollmentVerdict` drives the hero (**Would cost about $X more** / **Would save about $X** when not enrolled; **Costing** / **Saving** versus Basic when enrolled). The estimate window is chosen in `#tod` (`_todRangeKey`, default `last_cycle`) and does not follow the Usage chart range. The collapsed “How this was calculated” table still shows the rate-card TOD vs Basic model as “$X more” / “$X cheaper” (never a signed savings figure). Energy charges only — fees/taxes/adjustments omitted. Official portal savings remain the separate green card.
- **Failure policy:** best-effort; soft-fails to last-good `RateCompareSnapshot`. A null/missing payload, or a payload whose fields are all null, parses as an empty/blank snapshot and **does not** overwrite a previously valid snapshot.

### `getSmartChargingEnrollmentDetails` (`SmartChargingEnrollmentDetailsParams!`) — v0.9.1+

- **Purpose:** EV Smart Charging program detail.
- **Variables:** `{ params: { encryptedAccountNumber } }`.
- **Fields:** `enrollmentStatus`, `cardType`, `lastSeasonEarnedCredit`, `activeSeason { name start end }`.
- **Failure policy:** best-effort program detail; soft-fails to `None`.

### `getSmartBatteryDetails` (`SmartBatteryDetailsParams!`) — v0.9.1+

- **Purpose:** Smart Battery Pilot program detail.
- **Variables:** `{ params: { encryptedServiceAgreementId } }`.
- **Fields:** `isEnrolled`, `cardType`, `currentBillCreditAmount`, `currentBillKwh`, `ytdCreditAmount`, `ytdKwh`, `peakTimeSeason { seasonCategory season startDate endDate }`.
- **Failure policy:** best-effort; no monetary/kWh sensors are derived — fields are diagnostic attributes only.

### `getNetMeteringDetails` (`NetMeteringDetailsParams!`) — v0.9.1+

- **Purpose:** net-metering account detail (diagnostic, gated on solar return history).
- **Variables:** `{ params: { encryptedAccountId, encryptedPremiseId } }`.
- **Fields:** `isEnrolled`, `cardType`, `currentBalance`, `lastStatementCredit`, `annualTrueUpDate`, `yearToDateGeneration`, `yearToDateExport`.
- **Failure policy:** best-effort; soft-fails to last-good. Only called when lifetime return > 0 or a net-metering program row exists. A null/missing payload, or a payload whose fields are all null, parses as an empty/blank snapshot and **does not** overwrite a previously valid snapshot. All fields are raw diagnostic attributes until UAT validates units.

### Programs

- **Status:** `getProgramsEnrollmentStatusDetails` with `{ encryptedAccountNumber, encryptedPremiseId, encryptedSaId }`.
- **Detail ops (best-effort):** Peak Time (`encryptedAccountNumber` + `ptrMockServerDate: ""`; extended v0.9.1 with `peakTimeEvents`, `seasonalDates`, `lastPTRSeason`, `nextPTRSeason`), Renewables (`encryptedServiceAgreementId`), TOD (`encryptedAccountNumber` + `encryptedServiceAgreementId`; extended v0.9.1 with `annualLookBackEarnedCredit`, `offPeakCharges`, `midPeakCharges`, `onPeakCharges`, `planSavings`), Smart Thermostat (`encryptedAccountNumber`), EV Smart Charging (`encryptedAccountNumber`, v0.9.1+), Smart Battery Pilot (`encryptedServiceAgreementId`, v0.9.1+).
- **Program matching:** status list keyword matching plus `_program_list_lookup` for Smart Charging (`EV_SMART_CHARGING` aliases) and Smart Battery (`SMART_BATTERY_PILOT` aliases). Every program row preserves `is_eligible` from the enrollment status list; per-program eligibility (`*_eligible`) is surfaced as an `is_eligible` attribute on each program binary sensor (PTR, Green Future, TOD, Smart Thermostat, Habitat Support, Smart Charging, Smart Battery) so the panel can distinguish "Eligible" from "Not enrolled".
- **HA import:** enrollment flags + YTD / on-bill flex earnings; dual-publish mean series for YTD savings. `next_ptr_event_date` sensor exposes the nearest future PTR event from sorted/deduped `peakTimeEvents`. Bill PDF download is opt-in (`download_bill_pdfs`, v0.7+).

### Bill PDF REST / normalized parsing (shipped v0.7.0)

- **Download:** `POST https://apix.portlandgeneral.com/pge-bill-api/pdf/bills` with the Apigee bearer, portal Origin/Referer, and `{ encryptedBillId, isSummary: false, isNonDetailed: false }` for the detailed form.
- **Live matrix (2026-07-28):** three recent bills in both `detailed` and `simplified` form (six PDFs total), including a move/multi-meter statement. All were valid, unencrypted, text-backed letter PDFs (2-4 pages / ~121-145 KB); OCR was not required. Layout extraction keeps rotated payment-stub text (`layout_mode_strip_rotated=False`); a plain variant is still merged for Form XObject coverage. Core fields reconcile across both variants; complementary metric keys merge without double-counting values across variants. Accounted-for pypdf rotation log lines are filtered in `bill_pdf_parser` (exact message match only).
- **Normalized contract:** statement/due/service dates, amount due, total kWh, multi-service provenance, and 16 USD metric families (balance/payment; energy/delivery totals and primary components; regulatory/pass-through/program/Green Future/tax totals). All six live PDFs reconciled their core amount/kWh/period identity against GraphQL. Missing/mismatched core fields block publication; incomplete known-line-item arithmetic and a GraphQL segment period contained by a multi-service PDF period are explicit non-blocking advisories.
- **Golden fixtures:** public-sample arithmetic plus digit-tokenized single-service and multi-service layouts cover rotated fallback text, glued labels/values, `for N days`, detailed/simplified variants, multiple meter totals, and complementary extraction modes.
- **Privacy:** raw PDF text contains account/address data. Runtime Store/WS/diagnostics never persist raw text or PII; committed golden fixtures are digit-tokenized. Files live under `www/pge_energy/…` (`/local/…`, unauthenticated if HA is exposed).

### Bill PDF statistic suffixes (external sum series, statement-dated)

When parsing reconciles: `_bill_pdf_amount_due`, `_bill_pdf_total_kwh`, plus 16 USD line-item `_bill_pdf_*` ids (see `bill_pdf_statistics.py`). Distinct from GraphQL `_bill_amount` / `_bill_kwh`.

### Billing statistics suffixes

External `pge_energy:<account_key>_*` series: `_account_balance`, `_amount_due`, `_last_payment_amount`, `_bill_avg_temperature`, `_ytd_program_savings` (mean); `_bill_amount`, `_bill_kwh`, `_payment_amount` (sum from ledger). Mean series are **external-only** — snapshot-stamped rows are never mirrored onto recorder entity statistics because HA Core's `compile_statistics` does a plain INSERT for the same hour and logs `UNIQUE constraint failed: statistics.metadata_id, statistics.start_ts` ("Blocked attempt to insert duplicated statistic rows") against a pre-seeded slot. The `_bill_amount` / `_payment_amount` sum series still mirror onto `sensor.pge_*_lifetime_billed` / `_lifetime_payments` entity stats. Every entity mirror (usage energy/cost/outdoor temperature + bill/payment sums) goes through `_async_mirror_entity_statistics`, which drops rows newer than `utcnow` floored − 2h so it can never race the recorder's compile INSERT; HA natively compiles those newest hours and the mirror re-curates them once they age past the cutoff.

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

- **Publication is overnight / daily, not real-time.** PGE does not continuously publish new hourly intervals through the day. During daytime polls the newest available tip often sits near the early-morning Pacific hour (commonly ~`01:00` local / `08:00Z` in PDT) until the next overnight drop. Treat “Latest available interval” as newest _published_, not wall-clock freshness. The integration defaults to polling **every 4 hours** on a Pacific clock grid (`sync_local_time` default **00:00**) so overnight publication is picked up without waiting a full day.
- **HTTP 502 transient errors** occur intermittently — retry with backoff.
- **MONTHLY** returns the latest ~12 billing periods regardless of range width.
- **DAILY** short windows (<~31d) may hard-error; use ≥31d or HOURLY for validation.
- **HOURLY** day requests return ~25 rows (+1 boundary hour at `day_end`); filter to `[day_start, day_end)`.
- **Response totals** (`totalKwhUsage` / `totalKwhCost`) are reliable mainly for DAILY; HOURLY/MONTHLY often leave them null.
- **Hidden CSV endpoint** exists at `/pge-bill-api/usageCompare/download` but returned HTTP 500 at time of analysis.
