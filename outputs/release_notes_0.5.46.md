## Portland General Electric Energy Usage for Home Assistant

Custom integration for **Portland General Electric (PGE)** — **not** California Pacific Gas & Electric (PG&E) / Opower.

### What's new in 0.5.46
- Fix Browser Mod / sidebar ownership ([#2](https://github.com/spencerthayer/homeassistant-pge/issues/2)): stop reading or writing frontend user-store `sidebar` (`panelOrder` / `hiddenPanels`)
- Sidebar order and visibility remain under Home Assistant’s editor or Browser Mod; the integration only registers the `/pge` panel
- If 0.5.41–0.5.45 left synced HA sidebar settings that override Browser Mod, use Browser Mod’s **Clear** once, reapply preferences, then restart

### Capabilities
- Unattended email/password login (Cognito → Apigee) with automatic token renewal
- Hourly / daily / monthly usage import (kWh, cost, outdoor temperature) into HA Energy statistics
- Billing & programs sensors (structured fields; bill PDFs deferred)
- Sidebar panel at `/pge` for usage, billing, programs, and live sync progress

### Install (HACS custom repository)
1. HACS → Custom repositories → `https://github.com/spencerthayer/homeassistant-pge` → category **Integration**
2. Install **Portland General Electric Energy Usage** (this release: **0.5.46**)
3. Restart Home Assistant
4. Add the integration with PGE email, password, and account number

### Limits
- MFA / CAPTCHA accounts unsupported (fail closed)
- Unofficial portal API; may change without notice
- Requires Home Assistant **2026.7.0+**
- Not endorsed by or affiliated with Portland General Electric
