# Billing schema mismatch and statistic collision

Live check on 2026-10-12 against `api.portlandgeneral.com`. Neither item belongs in the host-failover patch. Both need their own change once the missing facts below are in hand.

## Net metering and rate compare return HTTP 400

The calls are not an enrollment miss. The live schema rejects the selection set. Introspection is disabled (`introspection has been disabled`), so the field list cannot be read from the API.

`getNetMeteringDetails` (`NetMeteringDetailsParams`) rejects every selected field: `isEnrolled`, `cardType`, `currentBalance`, `lastStatementCredit`, `annualTrueUpDate`, `yearToDateGeneration`, `yearToDateExport`. The type `NetMeteringDetails` exists.

`getRateCompare` rejects `touTotal`, `basicTotal`, `savings`, and `comparisonPeriod` on type `RateCompareResponse`. The variable type in the document is `RateCompareParams!`. The server expects `GetRateCompareParams!`.

The extra message `Field "…" of type "Query" must have a selection of subfields` is returned alongside those unknown-field errors. A `__typename` selection was not enough to name the real fields.

Today the coordinator logs the 400 at debug and keeps the last-good snapshot. That hides a query that cannot succeed for any account.

### Resolve

1. From a logged-in portlandgeneral.com session, capture the portal's `getNetMeteringDetails` and `getRateCompare` documents (operation, variables type, selection set). Do not guess fields and do not publish ¢/kWh or kWh sensors from them.
2. Replace `GET_NET_METERING_DETAILS` and `GET_RATE_COMPARE` in `billing_api.py`, plus `docs/DATA_CONTRACT.md`.
3. A null or all-null payload still keeps the last-good snapshot. An HTTP 400 validation error must not be the steady state.
4. Re-run the live billing sync and confirm those two log lines are gone. If the account has no solar or rate-compare data, the response is a successful null, not a 400.

## Recorder unique constraint on startup

`compile_missing_statistics` inserts into `statistics` and hits `UNIQUE constraint failed: statistics.metadata_id, statistics.start_ts`. Home Assistant logs `Error executing query`, then `Blocked attempt to insert duplicated statistic rows`, then swallows the error (`filter_unique_constraint_integrity_error` in recorder `util.py`). The panel stayed populated. Later mirrors succeeded.

Cause: entity statistic rows were already imported for hours in the catch-up window. After the instance had been stopped, compile walks from the last statistics run and plain-INSERTs those hours. The 2-hour mirror cutoff does not cover that gap. Monetary mean series already avoid this by staying external-only. Usage, cost, and lifetime bill/payment mirrors still share the entity `statistic_id` with recorder compile because those sensors keep `state_class` for the Energy dashboard.

### Resolve

1. Keep external `pge_energy:<account_key>_*` series as the import source of truth.
2. Decide the Energy dashboard id. Either point Energy at the external statistic and stop mirroring onto the `state_class` entity id, or keep the entity id and accept that catch-up compile will log the swallowed unique error until Home Assistant upserts in `compile_missing_statistics`.
3. Do not delete existing statistics rows to silence the log.
4. After the choice, restart live HA from a stopped process and confirm the boot log has no `UNIQUE constraint failed: statistics.metadata_id, statistics.start_ts` from this integration's metadata ids, and `/energy` still shows consumption and cost.
