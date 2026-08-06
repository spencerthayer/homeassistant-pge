# Auth discovery (PGE Cognito → Apigee)

Protocol notes for the unofficial Portland General Electric portal login chain used by `portal_auth.py`. Do not invent request fields beyond live capture / public portal assets.

## Happy path

1. Cognito `InitiateAuth` with `USER_PASSWORD_AUTH` (public client id from portal bundle).
2. Exchange Cognito `IdToken` at Apigee `pg-token-implicit-aws/token` → short-lived bearer + `expires_at`.
3. GraphQL `getAccountInfo` with the Apigee bearer → encrypted person id + account list.
4. Runtime renewal prefers password re-login when stored; falls back to `REFRESH_TOKEN_AUTH` only on recoverable credential auth errors (not throttle).

MFA / CAPTCHA challenges fail closed (`PGEMfaUnsupportedError` / `PGECaptchaUnsupportedError`).

## Cognito rate limits (live probe 2026-07-29)

Probe script: `scripts/probe_cognito_rate_limit.py` (opt-in `--env-file`, hard stop, ≤25 InitiateAuth calls). Stop live HA before probing.

### Observed

| Condition | Result |
| --- | --- |
| 25 sequential valid `USER_PASSWORD_AUTH` (~2.5 RPS) | No throttle |
| ~20-way parallel valid `USER_PASSWORD_AUTH` | `TooManyRequestsException` / `"Too many requests"` (HTTP 400); **no** `Retry-After` |
| Same parallel wave | Some requests still succeed while peers are throttled (shed, not hard account ban) |
| 5 wrong passwords | `NotAuthorizedException` / `"Incorrect username or password."` |
| 6th wrong password | `NotAuthorizedException` / `"Password attempts exceeded"` (temporary lockout; short initial recovery) |

AWS published baselines (pool/WAF may differ): ~10 InitiateAuth per user per second; failed-password exponential lockout after 5 fails (max ~15 minutes; 15 minutes quiet resets).

Fixtures:

- `tests/fixtures/auth/cognito_initiate_auth_too_many_requests.json`
- `tests/fixtures/auth/cognito_password_attempts_exceeded.json`

### Integration behavior

- Cognito throttle / password-attempt lockout → `PGERateLimitError` (not `PGEAuthenticationError`).
- No password→refresh InitiateAuth fallback on rate-limit (would amplify load).
- Shared per-email cooldown in `hass.data[DOMAIN]["cognito_rate_limit_until"]` (default **60s** for `TooManyRequests`, **900s** for password-attempt lockout; cap 900s).
- Coordinator soft-fails with retained sensors; **does not** open reauth UI for Cognito rate-limit.
- Poll `update_interval` stretches to remaining cooldown when longer than the normal/catch-up schedule.
- Concurrent `force_renew` waiters coalesce onto one Cognito login when a peer already replaced the token.

## Related docs

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — runtime auth / soft-fail flows
- [`../SECURITY.md`](../SECURITY.md) — credential storage
- [`../README.md`](../README.md) — user-facing auth diagram
- [`LIVE_TESTING.md`](LIVE_TESTING.md) — CLI / fixture sanitization
