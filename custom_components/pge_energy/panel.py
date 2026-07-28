"""Register the PGE custom panel at ``/pge`` from integration-wide settings."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback

from .const import (
    BRAND_URL_PATH,
    DOMAIN,
    FRONTEND_URL_PATH,
    PANEL_SETUP_KEY,
    PANEL_URL_PATH,
    PANEL_WEBCOMPONENT,
    VERSION,
)
from .panel_settings import PanelSettings, async_load_panel_settings, async_save_panel_settings

_LOGGER = logging.getLogger(__name__)

_INTEGRATION_DIR = Path(__file__).parent
_FRONTEND_DIR = _INTEGRATION_DIR / "frontend"
_BRAND_DIR = _INTEGRATION_DIR / "brand"

PANEL_STATIC_PATHS_KEY = f"{DOMAIN}_panel_static_paths"
PANEL_LOCK_KEY = f"{DOMAIN}_panel_lock"
PANEL_APPLIED_SETTINGS_KEY = f"{DOMAIN}_panel_applied_settings"


def _panel_lock(hass: HomeAssistant) -> asyncio.Lock:
    lock = hass.data.get(PANEL_LOCK_KEY)
    if lock is None:
        lock = asyncio.Lock()
        hass.data[PANEL_LOCK_KEY] = lock
    return lock


async def _async_register_static_paths(hass: HomeAssistant) -> None:
    if hass.data.get(PANEL_STATIC_PATHS_KEY):
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
    hass.data[PANEL_STATIC_PATHS_KEY] = True


async def _async_register_panel(hass: HomeAssistant, settings: PanelSettings) -> None:
    """Register ``/pge`` with the given presentation settings."""
    kwargs: dict = {
        "frontend_url_path": PANEL_URL_PATH,
        "webcomponent_name": PANEL_WEBCOMPONENT,
        "module_url": f"{FRONTEND_URL_PATH}/pge-panel.js?v={VERSION}",
        "embed_iframe": False,
        "require_admin": settings.require_admin,
        "config": {"default_section": settings.default_section},
    }
    if settings.show_sidebar:
        kwargs["sidebar_title"] = settings.sidebar_title
        kwargs["sidebar_icon"] = settings.sidebar_icon
    else:
        kwargs["sidebar_title"] = None
        kwargs["sidebar_icon"] = None

    await panel_custom.async_register_panel(hass, **kwargs)
    hass.data[PANEL_SETUP_KEY] = True
    hass.data[PANEL_APPLIED_SETTINGS_KEY] = settings
    _LOGGER.debug(
        "Registered PGE panel at /%s (sidebar=%s title=%s admin=%s section=%s)",
        PANEL_URL_PATH,
        settings.show_sidebar,
        settings.sidebar_title if settings.show_sidebar else None,
        settings.require_admin,
        settings.default_section,
    )


async def _async_remove_panel_if_registered(hass: HomeAssistant) -> None:
    if not hass.data.pop(PANEL_SETUP_KEY, None):
        return
    frontend.async_remove_panel(hass, PANEL_URL_PATH)
    _LOGGER.debug("Removed PGE panel /%s for re-apply", PANEL_URL_PATH)


async def async_setup_panel(hass: HomeAssistant) -> None:
    """Register static paths and the ``/pge`` custom panel (idempotent).

    Panel chrome (sidebar link, title, icon, admin gate, landing section) comes
    from the domain panel Store. Sidebar *order* remains owned by Home
    Assistant's sidebar editor and/or Browser Mod — this integration never
    reads or writes frontend user-store ``sidebar`` data.
    """
    async with _panel_lock(hass):
        await _async_register_static_paths(hass)
        if hass.data.get(PANEL_SETUP_KEY):
            return
        settings = await async_load_panel_settings(hass)
        await _async_register_panel(hass, settings)


async def async_apply_panel(
    hass: HomeAssistant,
    settings: PanelSettings | None = None,
) -> None:
    """Re-register ``/pge`` from the given or persisted settings.

    On failure, attempts to restore the previously applied settings (and Store)
    so a broken candidate is not left active.
    """
    async with _panel_lock(hass):
        await _async_register_static_paths(hass)
        previous = hass.data.get(PANEL_APPLIED_SETTINGS_KEY)
        if not isinstance(previous, PanelSettings):
            previous = await async_load_panel_settings(hass)

        candidate = settings if settings is not None else await async_load_panel_settings(hass)
        try:
            await _async_remove_panel_if_registered(hass)
            await _async_register_panel(hass, candidate)
        except Exception:
            _LOGGER.exception("Failed to apply PGE panel settings; attempting rollback")
            try:
                await _async_remove_panel_if_registered(hass)
                await _async_register_panel(hass, previous)
                await async_save_panel_settings(hass, previous)
            except Exception:
                _LOGGER.exception("Failed to restore previous PGE panel registration")
            raise


@callback
def async_teardown_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar panel when the last config entry unloads."""
    if not hass.data.pop(PANEL_SETUP_KEY, None):
        return
    frontend.async_remove_panel(hass, PANEL_URL_PATH)
    hass.data.pop(PANEL_APPLIED_SETTINGS_KEY, None)
    _LOGGER.debug("Removed PGE panel /%s", PANEL_URL_PATH)
