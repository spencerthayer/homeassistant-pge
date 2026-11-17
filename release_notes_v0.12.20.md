# v0.12.20 — Auth failure reasons and CAPTCHA poll handling

**Release type:** PATCH

## Why this update

A failed poll logged only `Authentication failed`, so the password, token, or portal error that caused it was discarded. A CAPTCHA or device challenge is a subclass of that same authentication error, and the poll treated it as a bad password. Home Assistant then asked for credentials that cannot satisfy the challenge.

## Changes

- Both poll authentication paths now log a safe cause and the exception class, and store that same text on the last error and a tracked sync failure.
- Usage GraphQL authentication errors use a fixed category. Emails, account ids, tokens, and passwords from the server message are not copied into the exception or the poll log.
- A CAPTCHA during the initial login, a proactive token check, or a 401 renewal keeps downloaded usage and billing, does not open a password reauth flow, and does not immediately retry the login. With nothing downloaded yet, the poll raises `UpdateFailed` instead of `ConfigEntryAuthFailed`.
- Setup and the options flow still reject CAPTCHA and MFA. Ordinary wrong-password failures still request one reauth flow until a later token acquisition resets that debounce.

## Limitations

- This does not solve CAPTCHA, and it does not show that any earlier outage was a challenge.
- Billing GraphQL errors can still include server text. This release only changes the usage poll path that was hiding the cause.
- Local verification used Home Assistant 2026.7.3. The report that prompted the fix was from 2026.10.4.
