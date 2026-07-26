# Usage fixtures (sanitized live shapes)

Derived from `outputs/probe/` live extraction (2026-07-23). No tokens,
person IDs, or account numbers.

| File | Shape |
|------|--------|
| `hourly_day_with_boundary.json` | 25 rows: 24 local-day hours + +1 boundary at `day_end` |
| `daily_short_window_error.json` | DAILY &lt;~31d GraphQL hard-error message |
| `monthly_latest_12.json` | Latest ~12 billing periods (range-independent) |
