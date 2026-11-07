## v0.12.13 — Responsive mobile panel interactions

**Release type:** PATCH

This release addresses slow or missed tab taps in the iOS Home Assistant app. On touch-sized screens, the initial landing scroll could move the tab row while a finger was still down. The browser then delivered the synthesized click to the content beneath the row rather than to the tab, leaving the selected section unchanged. The panel now keeps its navigation in place on phones and touch devices.

Tab state, accessibility selection, and panel visibility still update immediately. First-visit chart galleries, recorder-backed work, and chart resizing now wait until after the selected panel has had a frame to paint. That keeps the tab response visible before chart work can occupy the main thread; work for a tab that is no longer active is skipped.

The sync-information glyph is centered inside its mobile status button. The button remains an icon-only, full-size touch target when its text label is hidden.

The integration version and every frontend module cache query move to `0.12.13` so Home Assistant fetches the updated modules. Restart Home Assistant after installing this HACS release.

### Changes

- Skip the initial `scrollIntoView` on coarse-pointer and phone-width layouts so startup cannot retarget a tap on the tab row.
- Defer first-visit gallery work and chart resizing until after the selected tab paints; cancel deferred work after a tab or account change.
- Center the mobile sync-information icon within the status button.
- Bump the integration and all frontend module cache versions to `0.12.13`.
