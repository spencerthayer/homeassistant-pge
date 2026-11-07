## v0.12.12 — Mobile sync information

**Release type:** PATCH

This release fixes the green Sync status button on mobile. Tapping the button did set its expanded state and render the last-sync popover, but the `.section-tabs` container clipped the popover below the header, making the button appear unresponsive. The tab scroller retains its own horizontal overflow; the row now allows the sync popover to extend below it.

The button also gains an information icon so its purpose is visible when the mobile layout hides the “Sync status” text. The icon does not intercept taps and uses the theme text color against the status fill. On touch devices, tapping the button opens the existing last-sync summary; desktop behavior remains unchanged.

The integration and frontend module versions move to `0.12.12` so Home Assistant loads the corrected cached panel modules. Restart Home Assistant after installing the HACS release.

### Changes

- Stop clipping the mobile sync status popover at the tab-row boundary.
- Add a non-interactive information icon to the sync button, including its icon-only mobile layout.
- Bump the integration and all frontend module cache versions to `0.12.12`.
