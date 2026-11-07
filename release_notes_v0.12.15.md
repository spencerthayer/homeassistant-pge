# v0.12.15 — Center compact sync status icon

**Release type:** PATCH

The compact mobile sync button centers the information icon in a grid. In the warning state, the desktop warning dot is rendered by `.sync-pill.warn::before`. The mobile rule that hid `.sync-pill::before` was less specific, so the warning dot remained visible as a second grid row and shifted the information icon downward. This was why the icon appeared centered in some sync states but not others.

The compact warning style now explicitly hides the warning pseudo-element at matching specificity. The button keeps one centered grid item, the information icon, across good, warning, and critical states. The desktop warning dot remains unchanged. Integration and frontend cache versions move to `0.12.15` so Home Assistant loads the corrected style.
