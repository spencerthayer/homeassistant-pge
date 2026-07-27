"""Register the PGE custom sidebar panel at ``/pge``."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components import frontend, panel_custom
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


async def async_setup_panel(hass: HomeAssistant) -> None:
    """Register static paths and the ``/pge`` custom panel (idempotent).

    Registers the panel only. Sidebar order and visibility are owned by Home
    Assistant's sidebar editor and/or Browser Mod — this integration never
    reads or writes frontend user-store ``sidebar`` data.
    """
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


@callback
def async_teardown_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar panel when the last config entry unloads."""
    if not hass.data.pop(PANEL_SETUP_KEY, None):
        return
    frontend.async_remove_panel(hass, PANEL_URL_PATH)
    _LOGGER.debug("Removed PGE panel /%s", PANEL_URL_PATH)
