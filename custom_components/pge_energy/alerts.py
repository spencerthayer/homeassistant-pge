"""Minimal pge_energy_alert domain event surface (PTR-only for now).

Fires typed alerts on the ``pge_energy_alert`` bus so HA automations can
react to Peak Time Rebate events without polling binary sensors.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

ALERT_DOMAIN_EVENT = f"{DOMAIN}_alert"


def async_fire_pge_alert(hass: HomeAssistant, alert_type: str, **payload: Any) -> None:
    """Fire a pge_energy_alert domain event.

    Deduplication is the caller's responsibility (use a dedupe key based on
    account_key + alert_type + event_date/window_id).
    """
    event_data = {
        "alert_type": alert_type,
        **payload,
    }
    hass.bus.async_fire(ALERT_DOMAIN_EVENT, event_data)
