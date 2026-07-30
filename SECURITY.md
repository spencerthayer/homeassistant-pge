# PGE Energy Integration Security

## Supported authentication

- **Production:** PGE portal **email + password** plus **account number** per config entry (no MFA).
- **Unsupported:** MFA, CAPTCHA, device attestation challenges — fail closed.
- **Removed:** Manual bearer-token paste (alpha path). Legacy `auth_mode=manual_token` entries may still load until reauth upgrades them to credentials.

## Sensitive fields (never log / never commit)

- Bearer / access tokens
- Refresh / session secrets
- Encrypted person IDs
- Full account numbers
- Email addresses
- Passwords
- MFA codes (not supported; still never log if observed)

## Storage

| Data | Location | Notes |
|------|----------|--------|
| Email / password or refresh secret | HA config entry | HA’s storage trust boundary |
| Short-lived access token | Memory preferred | Persist only when renewal requires it |
| Immutable `account_key` | HA config entry | Not derived from renewable person IDs |
| Encrypted account / premise / SA ids | HA config entry | Opaque portal identifiers for billing/programs; redact in diagnostics/logs |
| Import/backfill state | HA `Store` | No secrets; includes billing ledger offset checkpoint |
| Statistics | HA recorder | Cumulative energy/cost + billing mean/sum series |

## Diagnostics redaction

`diagnostics.py` redacts tokens, person IDs, account IDs, email, password, refresh credentials, encrypted billing identifiers, and full `encrypted_bill_id` values via `async_redact_data`. Bill PDF diagnostics expose only counts, parse status codes, and truncated hashes — never raw extracted text.

## Bill PDF files (`www/` / `/local/`)

When **Download bill PDFs** is enabled, statement PDFs are written under `www/pge_energy/<account_key>/bills/`. Home Assistant serves these at `/local/pge_energy/...` **without authentication** if the instance is reachable. Users who expose HA to the internet should keep the toggle off or protect the instance (reverse proxy auth, VPN, etc.). Removing the integration does **not** auto-delete retained PDFs or normalized Store/recorder history. Normalized parse data in Store contains no customer name, service address, meter numbers, or raw PDF text.

## Custom panel static paths and websocket

- Static HTTP paths `/pge_energy_frontend/` and `/pge_energy_brand/` are unauthenticated (HA static-path default). They serve **only** the panel ES modules, vendored Apache ECharts, and bundled brand images — never Python sources, Store data, or credentials. Two prefixes are used so the integration package root is never exposed.
- Sidebar panel `/pge` and websocket commands `pge_energy/accounts` / `pge_energy/sync/subscribe` require an **admin** Home Assistant user.
- Websocket payloads are credential-free (account_key, entity/statistic ids, sync progress, options). No password, bearer token, refresh secret, or encrypted person/account/premise/SA ids.

## Credential revocation

1. Change the PGE portal password (and revoke sessions if the portal offers that).
2. Remove the integration from Home Assistant.

## Options / reauth

- **Sync settings** live in `entry.options` (polling, history, backfill flags, `include_billing` — no passwords).
- **Update credentials** writes email/password or refresh secret into `entry.data` only (plus best-effort encrypted billing ids); never changes account number, immutable `account_key`, or statistic IDs (account number shown read-only).
- Reauth uses email/password only (no token paste). Config-entry unique id is account-scoped so the same PGE account cannot be added twice.
- A failed renew/poll must not wipe already-downloaded usage or billing: sensors keep last-known values, recorder statistics stay, and credential reauth is requested without destroying history.
- Cognito InitiateAuth throttle / password-attempt lockout is treated as a rate limit (shared per-email cooldown): soft-fail without treating it as bad credentials or opening reauth. See [`AUTH_DISCOVERY.md`](AUTH_DISCOVERY.md).

## Local CLI vs PGE secrets

- Home Assistant owner login is **not** PGE portal credentials.
- Repo-root `.env` (when used for CLI) holds PGE test credentials: gitignored, mode **0600**, never committed; load only via explicit CLI `--env-file`.
- Do not confuse HA UI login with PGE Configure → Update credentials.
- Promote captured API shapes into `tests/fixtures/` only after sanitization and a clean `scripts/scan_secrets.py` pass. See `docs/LIVE_TESTING.md`.

## Unsupported API warning

This integration uses Portland General Electric’s customer portal API, which is not an official public API. PGE may change or restrict access at any time. Not endorsed by or affiliated with Portland General Electric.

## Reporting

Use GitHub private vulnerability reporting.
