# Troubleshooting

## Quiet expected log warnings

`pypdf` may emit layout-extraction warnings from `pypdf._text_extraction._layout_mode._fixed_width_page` during bill-PDF parse. Since 0.8.2 the integration retains rotated stub text (`layout_mode_strip_rotated=False`) and installs a targeted `logging.Filter` for the two accounted-for `Rotated text discovered…` messages (exact strings only — other `pypdf` warnings still surface). `Limiting excessive whitespace…` can still appear and remains informational. The integration also logs some caught-and-retried soft-failures at warning level that resolve on the next poll.

To keep Settings → System → Logs focused on actionable entries, filter remaining noise with HA's native `logger` integration in `configuration.yaml` (config-only — survives HACS updates and is easily reversible):

```yaml
logger:
  filters:
    pypdf._text_extraction._layout_mode._fixed_width_page:
      - "Limiting excessive whitespace.*"
    custom_components.pge_energy.billing_sync:
      - "soft-failed.*"
    custom_components.pge_energy.bill_pdf_sync:
      - "soft-failed.*"
    custom_components.pge_energy.coordinator:
      - "finished outside the normal path.*"
    custom_components.pge_energy.__init__:
      - "already in progress"
```

Restart Home Assistant for the filters to apply. Auth failures, reauth prompts, backfill/statistics errors, and other actionable messages are intentionally **not** filtered. If a future `pypdf` version renames its logger so the filter stops matching, the blunt fallback is `logger: logs: pypdf: critical` (safe here — `pypdf` is only used by this integration).

## `sqlite3.IntegrityError: UNIQUE constraint failed: statistics.metadata_id, statistics.start_ts`

Pre-0.7.4 installs could log this ("Blocked attempt to insert duplicated statistic rows") after each billing sync: the bill-period average temperature statistic was mirrored onto its recorder-tracked entity, pre-seeding the current-hour slot that HA Core's `compile_statistics` then tries to plain-INSERT. Fixed in 0.7.4 by making that series external-only (HA compiles the sensor's own hourly rows natively; the `/pge` panel already reads the external `pge_energy:*` ids). Existing stale rows are cleared once automatically on the first setup after upgrade. Since 0.7.5 the remaining entity mirrors (usage energy/cost/outdoor temperature, lifetime billed/payments) also cap rows to hours HA has already compiled (`utcnow` floored − 2h), closing the same latent race. If the traceback still appears after 0.7.5, report it — it would mean an entity statistic is colliding outside the mirror path.
