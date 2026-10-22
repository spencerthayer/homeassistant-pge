"""Device registry lookups that work on old and new Home Assistant releases."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN


@callback
def async_device_for_entry(hass: HomeAssistant, entry_id: str, account_key: str) -> dr.DeviceEntry | None:
    """Return the PGE device owned by one config entry.

    Home Assistant 2026.8 made identifiers unique per config entry and deprecated
    ``async_get_device``. Older releases have no per-entry lookup, so keep the
    registry-wide call as a fallback until the test pin moves past 2026.7.
    """
    registry = dr.async_get(hass)
    get_by_identifier = getattr(registry, "async_get_device_by_identifier", None)
    if get_by_identifier is not None:
        return get_by_identifier((DOMAIN, account_key), entry_id)
    return registry.async_get_device(identifiers={(DOMAIN, account_key)})
