# v0.12.14 — Mobile sync drawer usability

**Release type:** PATCH

This update fixes the sync and diagnostics drawer on phones. The native dialog's default maximum width could leave the close control outside the visible viewport, while its top edge ignored the iOS safe-area inset. The result was a drawer whose close button could sit beneath the status/menu area and could be clipped horizontally.

The drawer now uses explicit viewport positioning, removes the browser's default dialog width cap, and adds the device safe-area insets to its padding and close-button position. Phone users can also swipe right on the drawer to dismiss it; vertical swipes continue scrolling diagnostics. The drawer shows a brief swipe hint, while its close button and Escape dismissal remain available.

### Changes

- Keep the drawer and close control inside the phone viewport, below iOS status-bar cutouts.
- Allow a rightward touch swipe to close the drawer without blocking vertical scrolling.
- Show the swipe gesture hint only on coarse-pointer phone layouts.
- Bump integration and frontend cache versions to `0.12.14` so Home Assistant loads the updated panel.
