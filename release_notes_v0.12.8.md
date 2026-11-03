## v0.12.8 — PGE panel startup fix

**Release type:** PATCH

**Fixes:**
- Removes a duplicate `const heatWindow` declaration that prevented `pge-panel.js` from parsing and left `/pge` blank on iOS Safari.
- Bumps the frontend cache-busting version so Home Assistant fetches the corrected module instead of a cached `0.12.7` copy.

**Verification:**
- Parse every served frontend ES module with Node.js.
- Run the frontend test suite and required CI checks before publishing.
