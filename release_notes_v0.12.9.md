## v0.12.9 — Prioritize the first chart

**Release type:** PATCH

- Render only the visible primary usage chart during panel startup; load the alternate Usage/Overview chart when its tab is selected.
- Complete the visible chart before historical range-availability probes, KPI rollups, and data-gap queries.
- Keep the existing range availability checks and KPI/data-gap behavior, but remove hidden chart initialization and duplicate recorder reads from the initial path.

Mobile UAT: local Home Assistant, Ego Browser at 375×812 CSS px / DPR 3 / coarse pointer. With HTTP cache disabled on a full panel load, the Overview chart canvas and populated series were ready at 292 ms. In-app `/home` → `/pge` navigation on the running HA shell reached a populated visible chart in 119 ms; selecting Usage populated its chart in 22 ms using retained series data. These localhost timings do not represent an actual iPhone, cold HA shell startup, or an end-user network.
