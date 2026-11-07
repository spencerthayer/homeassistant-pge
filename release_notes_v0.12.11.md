## v0.12.11 — Mobile tab navigation

**Release type:** PATCH

This release improves section switching in the PGE panel for mobile Home Assistant users, including the iOS app. Each tab button now owns its selection handler, so handling a button click does not depend on finding that button by walking the event target from the navigation container. Tab controls also use `touch-action: manipulation` for responsive native touch behavior.

The frontend module query versions also move from `0.12.10` to `0.12.11`. Home Assistant caches these ES modules; without the version change, an existing installation could keep serving the old navigation code after updating the integration. Restart Home Assistant after installing the HACS release so it registers the new panel module.

### Changes

- Bind tab selection to each tab button instead of delegating clicks through the navigation container.
- Keep the At a glance cards in four columns through a 1500px window; use seven columns only at 1680px and wider when the card itself is at least 1300px wide.
- Apply touch-optimized interaction to the tab controls while retaining the existing keyboard navigation.
- Bump the integration and all frontend module cache versions to `0.12.11`.
