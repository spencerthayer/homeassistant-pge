"""Register the PGE custom sidebar panel at ``/pge`` (under Energy)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components import frontend, panel_custom
from homeassistant.components.frontend.storage import async_user_store
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback

from .const import (
    BRAND_URL_PATH,
    FRONTEND_URL_PATH,
    PANEL_SETUP_KEY,
    PANEL_SIDEBAR_ICON,
    PANEL_SIDEBAR_TITLE,
    PANEL_URL_PATH,
    PANEL_WEBCOMPONENT,
    VERSION,
)

_LOGGER = logging.getLogger(__name__)

_INTEGRATION_DIR = Path(__file__).parent
_FRONTEND_DIR = _INTEGRATION_DIR / "frontend"
_BRAND_DIR = _INTEGRATION_DIR / "brand"

# Built-in Energy panel url_path — PGE is pinned immediately after it.
_ENERGY_PANEL_PATH = "energy"
_DEFAULT_PANEL_PATH = "lovelace"


def ensure_pge_after_energy(panel_order: list[str] | None) -> list[str]:
    """Return a sidebar ``panelOrder`` with ``pge`` immediately after ``energy``.

    When the user has no custom order yet, seed a short prefix so Overview →
    Energy → PGE lead, and leave every other panel to HA's default sort.
    """
    order = list(panel_order or [])
    if PANEL_URL_PATH in order:
        order.remove(PANEL_URL_PATH)

    if not order:
        order = [_DEFAULT_PANEL_PATH, _ENERGY_PANEL_PATH]

    if _ENERGY_PANEL_PATH in order:
        insert_at = order.index(_ENERGY_PANEL_PATH) + 1
    elif _DEFAULT_PANEL_PATH in order:
        insert_at = order.index(_DEFAULT_PANEL_PATH) + 1
    else:
        insert_at = 0
    order.insert(insert_at, PANEL_URL_PATH)
    return order


async def async_ensure_sidebar_order(hass: HomeAssistant) -> None:
    """Pin the PGE sidebar item under Energy for every non-system user.

    HA has no register-time "after panel X" API — order lives in each user's
    frontend ``sidebar.panelOrder``. Re-asserting on setup keeps PGE under
    Energy across restarts even if it was dragged elsewhere.

    Soft-fails: a storage/auth hiccup must never abort config-entry setup.
    """
    try:
        users = await hass.auth.async_get_users()
    except Exception:  # pragma: no cover - auth API is best-effort here
        _LOGGER.debug("Could not list users for sidebar order", exc_info=True)
        return

    for user in users:
        if user.system_generated:
            continue
        try:
            store = await async_user_store(hass, user.id)
            sidebar: dict[str, Any] = dict(store.data.get("sidebar") or {})
            current = sidebar.get("panelOrder")
            if not isinstance(current, list):
                current = None
            desired = ensure_pge_after_energy(current)
            if current == desired:
                continue
            sidebar["panelOrder"] = desired
            if "hiddenPanels" not in sidebar:
                sidebar["hiddenPanels"] = list(sidebar.get("hiddenPanels") or [])
            await store.async_set_item("sidebar", sidebar)
            _LOGGER.debug("Pinned PGE sidebar panel under Energy for user %s", user.id)
        except Exception:  # pragma: no cover - per-user storage is best-effort
            _LOGGER.debug("Skipping sidebar order for user %s", user.id, exc_info=True)


async def async_setup_panel(hass: HomeAssistant) -> None:
    """Register static paths and the ``/pge`` custom panel (idempotent)."""
    if hass.data.get(PANEL_SETUP_KEY):
        return

    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                FRONTEND_URL_PATH,
                str(_FRONTEND_DIR),
                cache_headers=False,
            ),
            StaticPathConfig(
                BRAND_URL_PATH,
                str(_BRAND_DIR),
                cache_headers=True,
            ),
        ]
    )

    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_WEBCOMPONENT,
        sidebar_title=PANEL_SIDEBAR_TITLE,
        sidebar_icon=PANEL_SIDEBAR_ICON,
        module_url=f"{FRONTEND_URL_PATH}/pge-panel.js?v={VERSION}",
        embed_iframe=False,
        require_admin=True,
    )
    hass.data[PANEL_SETUP_KEY] = True
    _LOGGER.debug("Registered PGE panel at /%s (sidebar title %s)", PANEL_URL_PATH, PANEL_SIDEBAR_TITLE)
    # After the setup marker so a pin failure cannot leave a half-registered panel.
    await async_ensure_sidebar_order(hass)


@callback
def async_teardown_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar panel when the last config entry unloads."""
    if not hass.data.pop(PANEL_SETUP_KEY, None):
        return
    frontend.async_remove_panel(hass, PANEL_URL_PATH)
    _LOGGER.debug("Removed PGE panel /%s", PANEL_URL_PATH)
