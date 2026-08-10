# Live / CLI testing

For maintainers validating the GraphQL contract without a full Home Assistant UI session. Never commit `.env` or live capture bodies.

## Credentials

```bash
# gitignored; chmod 600
# keys: email, password, account_number (optional username)
```

Load only via explicit `--env-file`. Tests and CI never auto-load `.env`.

## CLI (ships with the integration package)

From a venv with `requirements_test.txt` installed:

```bash
.venv/bin/python -m custom_components.pge_energy.cli --env-file .env login
.venv/bin/python -m custom_components.pge_energy.cli --env-file .env renew
.venv/bin/python -m custom_components.pge_energy.cli --env-file .env validate
.venv/bin/python -m custom_components.pge_energy.cli --env-file .env fetch \
  --resolution hourly --start-date 2025-07-01 --end-date 2025-07-03

.venv/bin/python -m custom_components.pge_energy.cli --env-file .env billing-snapshot --json
.venv/bin/python -m custom_components.pge_energy.cli --env-file .env billing-history --page 0 --json
.venv/bin/python -m custom_components.pge_energy.cli --env-file .env programs --json
```

Output redacts account/person IDs by default; pass `--show-ids` only for local debugging. Use `--ask` to prompt for missing secrets via getpass.

Setup validation in Home Assistant uses a **HOURLY yesterday** request (short DAILY windows hard-error on the live API).

## Grid import/export alpha capture (v0.7.3)

The issue #5 capture uses PGE GraphQL only and is disabled by default:

1. Upgrade to v0.7.3 and restart Home Assistant.
2. Open Configure → Sync settings and enable **Enable diagnostic capture**.
3. Let normal sync run for 1–2 days; optionally trigger one Manual sync → Refresh now.
4. Open Settings → System → Logs (`/config/logs`) and download the log.
5. Review the file before sharing it. The page's visible `filter=pge` filter may not limit the downloaded file; prefer sharing only lines containing `PGE_ALPHA_GRID_CAPTURE` if unrelated logs are sensitive.
6. Disable the alpha switch when capture is complete.

Capture logs allowlist interval timestamps, kWh, amount, usage status, interval size, and temperature. They exclude request headers, tokens, account/person IDs, config-entry data, and unknown response fields, but the allowed usage values remain privacy-sensitive. Introspection is a one-shot best-effort request to `apix.portlandgeneral.com/pge-graphql`; failure is non-fatal. Never commit a live capture body.

## Automated suite

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
bash scripts/run_tests.sh
```

`scripts/run_tests.sh` runs component tests, recorder tests, and `scripts/scan_secrets.py`. Prefer sanitized fixtures under `tests/fixtures/` — run `scripts/sanitize_fixture.py` before promoting any live capture.

## Home Assistant UI UAT

Install via HACS (or copy `custom_components/pge_energy`), restart Home Assistant, then:

1. Add the integration with email / password / account number.
2. Open `/pge` (admin) and confirm At a glance + Usage + Billing populate after the first poll/backfill.
3. Confirm Energy dashboard can select `pge_energy:…_consumption` (or the mirrored `sensor.pge_…_energy` statistic).

Private development harnesses (`./scripts/start.sh` / `./scripts/stop.sh`, in-process HA scripts) live under `scripts/` for maintainer UAT.
