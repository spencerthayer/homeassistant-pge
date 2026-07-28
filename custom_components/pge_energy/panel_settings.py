"""Integration-wide PGE panel presentation settings (domain Store)."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, PANEL_SIDEBAR_ICON, PANEL_SIDEBAR_TITLE

_LOGGER = logging.getLogger(__name__)

PANEL_STORAGE_VERSION = 1
PANEL_STORAGE_KEY = f"{DOMAIN}.panel"
PANEL_STORE_DATA_KEY = f"{DOMAIN}_panel_store"

CONF_SHOW_SIDEBAR = "show_sidebar"
CONF_SIDEBAR_TITLE = "sidebar_title"
CONF_SIDEBAR_ICON = "sidebar_icon"
CONF_REQUIRE_ADMIN = "require_admin"
CONF_DEFAULT_SECTION = "default_section"

DEFAULT_SHOW_SIDEBAR = True
DEFAULT_REQUIRE_ADMIN = True
DEFAULT_SECTION_GLANCE = "glance"
DEFAULT_SECTION_USAGE = "usage"
DEFAULT_SECTION_ANALYTICS = "analytics"
DEFAULT_SECTION_BILLING = "billing"

PANEL_DEFAULT_SECTIONS: tuple[str, ...] = (
    DEFAULT_SECTION_GLANCE,
    DEFAULT_SECTION_USAGE,
    DEFAULT_SECTION_ANALYTICS,
    DEFAULT_SECTION_BILLING,
)

PANEL_SECTION_LABELS: dict[str, str] = {
    DEFAULT_SECTION_GLANCE: "At a glance",
    DEFAULT_SECTION_USAGE: "Usage",
    DEFAULT_SECTION_ANALYTICS: "Analytics",
    DEFAULT_SECTION_BILLING: "Billing",
}


class PanelSettingsValidationError(Exception):
    """Invalid panel settings submitted by the user."""

    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("Invalid panel settings")
        self.errors = errors


@dataclass(frozen=True, slots=True)
class PanelSettings:
    """Normalized panel chrome settings for the whole integration."""

    show_sidebar: bool = DEFAULT_SHOW_SIDEBAR
    sidebar_title: str = PANEL_SIDEBAR_TITLE
    sidebar_icon: str = PANEL_SIDEBAR_ICON
    require_admin: bool = DEFAULT_REQUIRE_ADMIN
    default_section: str = DEFAULT_SECTION_GLANCE

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_panel_settings() -> PanelSettings:
    """Return factory defaults."""
    return PanelSettings()


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    return default


def normalize_panel_settings(
    raw: dict[str, Any] | None,
    *,
    strict: bool = False,
) -> PanelSettings:
    """Normalize stored or submitted panel settings.

    When ``strict`` is True, invalid user input raises
    :class:`PanelSettingsValidationError` with field errors. When False
    (Store load), each bad field falls back to its default with a warning.
    """
    data = dict(raw or {})
    errors: dict[str, str] = {}

    show_sidebar = _coerce_bool(data.get(CONF_SHOW_SIDEBAR), DEFAULT_SHOW_SIDEBAR)
    require_admin = _coerce_bool(data.get(CONF_REQUIRE_ADMIN), DEFAULT_REQUIRE_ADMIN)

    title_raw = data.get(CONF_SIDEBAR_TITLE, PANEL_SIDEBAR_TITLE)
    if title_raw is None:
        title = ""
    else:
        title = str(title_raw).strip()
    if not title:
        if strict:
            errors[CONF_SIDEBAR_TITLE] = "invalid_sidebar_title"
        else:
            _LOGGER.warning("Invalid panel sidebar_title %r; using default", title_raw)
            title = PANEL_SIDEBAR_TITLE

    icon_raw = data.get(CONF_SIDEBAR_ICON, PANEL_SIDEBAR_ICON)
    if icon_raw is None:
        icon = ""
    else:
        icon = str(icon_raw).strip()
    if not icon.startswith("mdi:") or len(icon) <= 4:
        if strict:
            errors[CONF_SIDEBAR_ICON] = "invalid_sidebar_icon"
        else:
            _LOGGER.warning("Invalid panel sidebar_icon %r; using default", icon_raw)
            icon = PANEL_SIDEBAR_ICON

    section_raw = data.get(CONF_DEFAULT_SECTION, DEFAULT_SECTION_GLANCE)
    section = str(section_raw).strip() if section_raw is not None else ""
    if section not in PANEL_DEFAULT_SECTIONS:
        if strict:
            errors[CONF_DEFAULT_SECTION] = "invalid_default_section"
        else:
            _LOGGER.warning("Invalid panel default_section %r; using default", section_raw)
            section = DEFAULT_SECTION_GLANCE

    if errors:
        raise PanelSettingsValidationError(errors)

    return PanelSettings(
        show_sidebar=show_sidebar,
        sidebar_title=title,
        sidebar_icon=icon,
        require_admin=require_admin,
        default_section=section,
    )


def _get_store(hass: HomeAssistant) -> Store:
    store = hass.data.get(PANEL_STORE_DATA_KEY)
    if store is None:
        store = Store(hass, PANEL_STORAGE_VERSION, PANEL_STORAGE_KEY)
        hass.data[PANEL_STORE_DATA_KEY] = store
    return store


async def async_load_panel_settings(hass: HomeAssistant) -> PanelSettings:
    """Load panel settings from the domain Store (defaults when missing)."""
    store = _get_store(hass)
    raw = await store.async_load()
    if not isinstance(raw, dict):
        return default_panel_settings()
    return normalize_panel_settings(raw, strict=False)


async def async_save_panel_settings(hass: HomeAssistant, settings: PanelSettings) -> None:
    """Persist normalized panel settings to the domain Store."""
    store = _get_store(hass)
    await store.async_save(settings.as_dict())
