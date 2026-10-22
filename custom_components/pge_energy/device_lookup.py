"""Device registry lookups that work on old and new Home Assistant releases."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN


@callback
def async_device_for_entry(hass: HomeAssistant, entry_id: str, account_key: str) -> dr.DeviceEntry | None:
    """Return the PGE device owned by one config entry.

    Home Assistant 2026.8 added the per-entry lookup and made identifiers unique
    per config entry; 2026.9 deprecated ``async_get_device``. Keep the
    registry-wide call for the 2026.7 minimum in hacs.json until that minimum
    moves to 2026.8 or newer.
    """
    registry = dr.async_get(hass)
    get_by_identifier = getattr(registry, "async_get_device_by_identifier", None)
    if get_by_identifier is not None:
        return get_by_identifier((DOMAIN, account_key), entry_id)
    return registry.async_get_device(identifiers={(DOMAIN, account_key)})
