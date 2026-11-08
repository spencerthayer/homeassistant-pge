# v0.12.19 — Mobile interaction and chart responsiveness

**Release type:** PATCH

## Why this update

On iPhone, tapping a panel tab could look like a dead button: the selected content and its charts did not appear until recorder queries and chart rendering completed. The delay was especially visible on Analytics, Billing, and Programs. This was a usability failure, not just a slow chart. A tab must acknowledge the tap immediately, even when its data is not ready.

Profiling the existing panel found that first-visit Analytics work included an all-history hourly usage query dating back to 2019, alongside billing-ledger requests and chart processing. These unrelated workloads ran on the same main thread as the interaction. A single statistics query could also be requested more than once while it was still in flight.
The remaining Time of Day pause came from constructing Pacific date/time formatters for every hourly sample: one live render blocked the main thread for 1,015 ms. Reusing formatter instances reduced the longest observed task to 84 ms.

Rapid heatmap-window changes also reproduced overlapping Analytics renders that detached the visible ECharts canvas. The latest render now cancels older data work and pending chart mounts before replacing those charts.

Mobile drawer testing also found the close control at the top edge when the embedded web view reported no safe-area inset. The diagnostics drawer now applies a phone-width fallback inset, keeps its close target inside the viewport and below the iOS status area, and retains right-swipe dismissal.

## Changes

- Selecting a tab now updates its selected/visible state synchronously. First-visit chart areas show an accessible animated loading skeleton before deferred chart work begins.
- Switching away cancels that tab's unfinished gallery render; stale work cannot block another tab or incorrectly mark an incomplete gallery as rendered.
- Analytics no longer loads statement-history charts or full-history hourly usage as part of its entry path. Its hourly analysis uses a bounded one-year window; full statement history is deferred to Billing, and the longest always-on load history is fetched only when explicitly opened.
- Identical in-flight recorder-statistics requests now share one promise. Cache invalidation is generation-guarded so an older response cannot repopulate cleared data.
- Added regression coverage for immediate tab state and skeletons, abandoned tab work, recorder-request deduplication, invalidation races, and the Analytics/Billing query boundary.
- The sync and diagnostics drawer uses a safe-area fallback on touch viewports through 870px, avoiding a close button hidden under the iOS status bar while preserving swipe-to-close.
- At a glance keeps two-column phone labels readable and lays group/metric labels inline in the four- and seven-column layouts.
- Compact chart headers now expose a 44px chart-expansion target on touch layouts instead of hiding the control behind a hover-only interaction.
- Expanded charts use an in-header 44px close target with a horizontal title row, so mobile users can dismiss the chart without a small or displaced control.
- Time of Day no longer builds its first-visit gallery twice; the primary section renders separately and the gallery runs once.
- Visible chart factories now start after their skeleton paints and yield between chart mounts, preventing a long gallery from blocking the next mobile tab or scroll input.
- Pacific date/hour formatters are reused across hourly samples. In the measured Time of Day render, the longest main-thread task fell from 1,015 ms to 84 ms.
- Rapid Analytics heatmap-window changes invalidate older Insights render generations and pending chart mounts, preventing stale work from detaching the current chart.

The aim is both real work reduction and immediate, visible feedback: the interface responds first, then fills in data. This release does not replace unavailable data with fabricated values or change billing calculations.
