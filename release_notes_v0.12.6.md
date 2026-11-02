## v0.12.6 — Cognito retry logging fix

**Release type:** PATCH

**Fixes:**
- [#51](https://github.com/spencerthayer/homeassistant-pge/issues/51) — Cognito retry warnings drop the exception and fire on attempts that later succeed

**Changes:**
- **portal_auth.py**: Modified `_login_with_password` retry logic to log per-attempt connection errors at INFO level (with the underlying exception cause) instead of WARNING. Only the final failed attempt (after all 5 retries exhausted) logs at WARNING level.
- The exception message is now included in both INFO and WARNING logs for better diagnosability.
- The `host_detail()` function already sanitizes URLs (strips query strings, keeps only hostname), so no credentials, email, or query strings appear in logs.

**Before (problematic behavior):**
```
WARNING PGE Cognito connection error on attempt 1 of 5; retrying in 1s
WARNING PGE Cognito connection error on attempt 2 of 5; retrying in 2s
... (attempt 3 succeeds, but two permanent WARNING lines remain)
```

**After (fixed behavior):**
```
INFO  PGE Cognito connection error on attempt 1 of 5 (PGE auth connection error (ClientConnectorError) (host cognito-idp.us-west-2.amazonaws.com)); retrying in 1s
INFO  PGE Cognito connection error on attempt 2 of 5 (...); retrying in 2s
... (attempt 3 succeeds - only INFO logs, no WARNING noise)
```

If all retries exhausted:
```
INFO  PGE Cognito connection error on attempt 1 of 5 (...); retrying in 1s
INFO  PGE Cognito connection error on attempt 2 of 5 (...); retrying in 2s
INFO  PGE Cognito connection error on attempt 3 of 5 (...); retrying in 4s
INFO  PGE Cognito connection error on attempt 4 of 5 (...); retrying in 8s
WARNING PGE Cognito connection failed after 5 attempts: PGE auth connection error (ClientConnectorError) (host cognito-idp.us-west-2.amazonaws.com)
```

**Testing:**
- Added caplog assertions to existing tests:
  - `test_connection_error_retries_then_succeeds`: exactly 1 INFO, 0 WARNING
  - `test_connection_error_exhausts_retries`: exactly 4 INFO + 1 WARNING with underlying cause
  - Both tests verify no sensitive data (credentials, email, query strings) in log messages

**Files changed:**
- `custom_components/pge_energy/portal_auth.py`
- `tests/components/pge_energy/test_portal_auth.py`

**Version bump:**
- `VERSION` in `const.py`: 0.12.5 → 0.12.6
- `version` in `manifest.json`: 0.12.5 → 0.12.6
- Frontend cache-busting imports: `?v=0.12.5` → `?v=0.12.6`
- README version reference updated

**All CI checks pass:** test, prek, hacs, hassfest
