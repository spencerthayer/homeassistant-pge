# v0.12.20 — Stop the token-persistence reload loop

**Release type:** PATCH

## Why this update

Saving a renewed PGE bearer token was reloading the integration. Each reload logged in again, saved another token, and reloaded. Sync sensors flapped unavailable, and the repeated logins could lock the account. A stalled import-state write made that worse: every later save waited out a fresh 60-second window on the same parked write.

## Changes

- Token, title, and migration writes no longer reload the config entry. A settings change still reloads once. Reauth and Update credentials still reload once, and the listener does not add a second reload.
- Unload retires the coordinator before it awaits, and cancels post-setup work. A replaced coordinator cannot persist a token, write a checkpoint, or start backfill. If platform unload fails, that coordinator stays the live one.
- Each entry admits one network refresh per 60 seconds, including across reloads. Further attempts log `PGE reload loop detected`, keep the last sensor values, and run one deferred refresh when the window ends. A normal multi-hour schedule is not pulled forward. Cognito cooldown and a stalled import-state write wait until whichever deadline is later.
- A known-stalled import-state write fails later saves, loads, and clears immediately. One follower writes the newest critical snapshot after the parked write finishes. The on-disk order, content dedupe, and `last_commit` exclusion are unchanged.

This does not change usage, billing, or Time of Day calculations.
