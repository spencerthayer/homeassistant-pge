from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.pge_energy.panel_settings import (
    CONF_DEFAULT_SECTION,
    CONF_SIDEBAR_ICON,
    CONF_SIDEBAR_TITLE,
    PANEL_STORAGE_KEY,
    PANEL_STORE_DATA_KEY,
    PanelSettings,
    PanelSettingsValidationError,
    async_load_panel_settings,
    async_save_panel_settings,
    default_panel_settings,
    normalize_panel_settings,
)


def test_normalize_defaults_for_empty_payload():
    settings = normalize_panel_settings(None)
    assert settings == default_panel_settings()


def test_normalize_round_trip_values():
    settings = normalize_panel_settings(
        {
            "show_sidebar": False,
            "sidebar_title": " Energy ",
            "sidebar_icon": "mdi:flash",
            "require_admin": False,
            "default_section": "billing",
        },
        strict=True,
    )
    assert settings.show_sidebar is False
    assert settings.sidebar_title == "Energy"
    assert settings.sidebar_icon == "mdi:flash"
    assert settings.require_admin is False
    assert settings.default_section == "billing"
    assert settings.as_dict()["sidebar_title"] == "Energy"


def test_normalize_store_load_falls_back_per_field():
    settings = normalize_panel_settings(
        {
            "show_sidebar": True,
            "sidebar_title": "   ",
            "sidebar_icon": "flash",
            "require_admin": "yes",
            "default_section": "nope",
        },
        strict=False,
    )
    assert settings.sidebar_title == "PGE"
    assert settings.sidebar_icon == "mdi:transmission-tower"
    assert settings.require_admin is True
    assert settings.default_section == "glance"


def test_normalize_strict_rejects_invalid_fields():
    with pytest.raises(PanelSettingsValidationError) as err:
        normalize_panel_settings(
            {
                "show_sidebar": True,
                "sidebar_title": "",
                "sidebar_icon": "not-mdi",
                "require_admin": True,
                "default_section": "weather",
            },
            strict=True,
        )
    assert err.value.errors[CONF_SIDEBAR_TITLE] == "invalid_sidebar_title"
    assert err.value.errors[CONF_SIDEBAR_ICON] == "invalid_sidebar_icon"
    assert err.value.errors[CONF_DEFAULT_SECTION] == "invalid_default_section"


@pytest.mark.asyncio
async def test_async_load_missing_store_returns_defaults():
    hass = MagicMock()
    hass.data = {}
    store = MagicMock()
    store.async_load = AsyncMock(return_value=None)

    with patch("custom_components.pge_energy.panel_settings.Store", return_value=store):
        settings = await async_load_panel_settings(hass)

    assert settings == default_panel_settings()
    assert hass.data[PANEL_STORE_DATA_KEY] is store


@pytest.mark.asyncio
async def test_async_save_and_load_round_trip():
    hass = MagicMock()
    hass.data = {}
    payload: dict | None = None

    store = MagicMock()

    async def _load():
        return payload

    async def _save(data):
        nonlocal payload
        payload = dict(data)

    store.async_load = AsyncMock(side_effect=_load)
    store.async_save = AsyncMock(side_effect=_save)

    with patch("custom_components.pge_energy.panel_settings.Store", return_value=store) as store_cls:
        candidate = PanelSettings(
            show_sidebar=False,
            sidebar_title="Home",
            sidebar_icon="mdi:home",
            require_admin=False,
            default_section="usage",
        )
        await async_save_panel_settings(hass, candidate)
        loaded = await async_load_panel_settings(hass)

    assert loaded == candidate
    store_cls.assert_called_once()
    assert store_cls.call_args.args[2] == PANEL_STORAGE_KEY
    store.async_save.assert_awaited_once_with(candidate.as_dict())


@pytest.mark.asyncio
async def test_async_save_exception_propagates():
    hass = MagicMock()
    hass.data = {}
    store = MagicMock()
    store.async_save = AsyncMock(side_effect=OSError("disk full"))

    with patch("custom_components.pge_energy.panel_settings.Store", return_value=store):
        with pytest.raises(OSError, match="disk full"):
            await async_save_panel_settings(hass, default_panel_settings())
