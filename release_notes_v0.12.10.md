## v0.12.10 — First paint and releases on merge

**Release type:** PATCH

This is the HACS release for everything after v0.12.6. v0.12.7, v0.12.8, and v0.12.9 were tagged earlier; this note repeats those changes so an upgrade to v0.12.10 shows the whole set. Restart Home Assistant after installing. The panel modules use a new `?v=0.12.10`.

### v0.12.7 — Panel load

- Preset probes run together instead of as twelve sequential recorder calls.
- Heatmaps default to the trailing 12 months. All years stays available.
- Only the open tab's main content loads at boot. Galleries load on first visit.
- A per-render cache drops duplicate statistic queries.
- Downsampling and the major render phases yield so the page can paint.

### v0.12.8 — Blank panel

- Removes the duplicate `const heatWindow` that stopped `pge-panel.js` from parsing and left `/pge` blank on iOS Safari.
- Bumps the module cache key so Home Assistant does not keep the broken 0.12.7 file.

### v0.12.9 — First chart

- The visible Usage or Overview chart renders before range probes, KPI rollups, and data-gap queries.
- The hidden Overview or Usage chart is not initialized until that tab opens.

### v0.12.10 — Selected tab and Analytics

- Entity-state At a glance tiles paint first. Six recorder-derived values stay pending until the primary content is ready.
- The selected tab's primary content renders before secondary recorder work. Time of Day, Billing, and Programs build their bodies on the first visit.
- Hass updates and the initial sync snapshot wait until that primary is ready. Leaving `/pge` drops deferred gallery work.
- Analytics degree-day and temperature-bin charts start with the scatter. Hourly history back to 2019 no longer blocks the first charts or a tab change.
- The ECharts download starts with the hero recorder reads.
- A merge to `main` publishes the HACS release after CI and Prek pass. A merge that is still on an already published version gets the next patch in that same job.
