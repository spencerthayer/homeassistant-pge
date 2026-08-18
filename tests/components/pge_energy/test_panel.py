from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.pge_energy import panel as panel_module
from custom_components.pge_energy.const import (
    BRAND_URL_PATH,
    DOMAIN,
    FRONTEND_URL_PATH,
    PANEL_SETUP_KEY,
    PANEL_SIDEBAR_ICON,
    PANEL_SIDEBAR_TITLE,
    PANEL_URL_PATH,
    PANEL_WEBCOMPONENT,
    VERSION,
)
from custom_components.pge_energy.coordinator import PGECoordinator
from custom_components.pge_energy.panel import (
    PANEL_APPLIED_SETTINGS_KEY,
    PANEL_STATIC_PATHS_KEY,
    async_apply_panel,
    async_setup_panel,
    async_teardown_panel,
)
from custom_components.pge_energy.panel_settings import PanelSettings, default_panel_settings


def test_panel_module_does_not_touch_frontend_user_sidebar_store():
    source = Path(panel_module.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "async_user_store",
        "panelOrder",
        "hiddenPanels",
        "async_get_users",
    ):
        assert forbidden not in source, f"panel.py must not reference {forbidden}"


def _hass_mock() -> MagicMock:
    hass = MagicMock()
    hass.data = {}
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    return hass


@pytest.mark.asyncio
async def test_async_setup_panel_registers_paths_and_panel():
    hass = _hass_mock()

    with (
        patch(
            "custom_components.pge_energy.panel.async_load_panel_settings",
            new_callable=AsyncMock,
            return_value=default_panel_settings(),
        ),
        patch(
            "custom_components.pge_energy.panel.panel_custom.async_register_panel",
            new_callable=AsyncMock,
        ) as register_panel,
    ):
        await async_setup_panel(hass)
        await async_setup_panel(hass)  # idempotent

    assert hass.data[PANEL_SETUP_KEY] is True
    assert hass.data[PANEL_STATIC_PATHS_KEY] is True
    assert hass.http.async_register_static_paths.await_count == 1
    configs = hass.http.async_register_static_paths.await_args.args[0]
    assert len(configs) == 2
    assert configs[0].url_path == FRONTEND_URL_PATH
    assert configs[0].cache_headers is False
    assert configs[1].url_path == BRAND_URL_PATH
    assert Path(configs[0].path).name == "frontend"
    assert Path(configs[1].path).name == "brand"

    register_panel.assert_awaited_once()
    kwargs = register_panel.await_args.kwargs
    assert kwargs["frontend_url_path"] == PANEL_URL_PATH
    assert kwargs["webcomponent_name"] == PANEL_WEBCOMPONENT
    assert kwargs["sidebar_title"] == PANEL_SIDEBAR_TITLE == "PGE"
    assert kwargs["sidebar_icon"] == PANEL_SIDEBAR_ICON
    assert kwargs["require_admin"] is True
    assert kwargs["config"] == {"default_section": "glance"}
    assert kwargs["module_url"] == f"{FRONTEND_URL_PATH}/pge-panel.js?v={VERSION}"
    assert hass.data[PANEL_APPLIED_SETTINGS_KEY] == default_panel_settings()


@pytest.mark.asyncio
async def test_async_apply_panel_hides_sidebar_chrome():
    hass = _hass_mock()
    hass.data[PANEL_SETUP_KEY] = True
    hass.data[PANEL_STATIC_PATHS_KEY] = True
    hass.data[PANEL_APPLIED_SETTINGS_KEY] = default_panel_settings()
    hidden = PanelSettings(
        show_sidebar=False,
        sidebar_title="KeepMe",
        sidebar_icon="mdi:flash",
        require_admin=False,
        default_section="analytics",
    )

    with (
        patch("custom_components.pge_energy.panel.frontend.async_remove_panel") as remove,
        patch(
            "custom_components.pge_energy.panel.panel_custom.async_register_panel",
            new_callable=AsyncMock,
        ) as register_panel,
    ):
        await async_apply_panel(hass, hidden)

    remove.assert_called_once_with(hass, PANEL_URL_PATH)
    kwargs = register_panel.await_args.kwargs
    assert kwargs["sidebar_title"] is None
    assert kwargs["sidebar_icon"] is None
    assert kwargs["require_admin"] is False
    assert kwargs["config"] == {"default_section": "analytics"}
    assert hass.data[PANEL_SETUP_KEY] is True
    assert hass.data[PANEL_APPLIED_SETTINGS_KEY] == hidden


@pytest.mark.asyncio
async def test_async_apply_panel_visible_passes_chrome():
    hass = _hass_mock()
    hass.data[PANEL_STATIC_PATHS_KEY] = True
    hass.data[PANEL_APPLIED_SETTINGS_KEY] = default_panel_settings()
    custom = PanelSettings(
        show_sidebar=True,
        sidebar_title="Power",
        sidebar_icon="mdi:lightning-bolt",
        require_admin=True,
        default_section="usage",
    )

    with patch(
        "custom_components.pge_energy.panel.panel_custom.async_register_panel",
        new_callable=AsyncMock,
    ) as register_panel:
        await async_apply_panel(hass, custom)

    kwargs = register_panel.await_args.kwargs
    assert kwargs["sidebar_title"] == "Power"
    assert kwargs["sidebar_icon"] == "mdi:lightning-bolt"
    assert kwargs["config"] == {"default_section": "usage"}


@pytest.mark.asyncio
async def test_async_apply_panel_rolls_back_on_register_failure():
    hass = _hass_mock()
    hass.data[PANEL_STATIC_PATHS_KEY] = True
    previous = default_panel_settings()
    hass.data[PANEL_SETUP_KEY] = True
    hass.data[PANEL_APPLIED_SETTINGS_KEY] = previous
    bad = PanelSettings(
        show_sidebar=True,
        sidebar_title="Broken",
        sidebar_icon="mdi:alert",
        require_admin=True,
        default_section="billing",
    )

    register = AsyncMock(side_effect=[RuntimeError("boom"), None])

    with (
        patch("custom_components.pge_energy.panel.frontend.async_remove_panel"),
        patch(
            "custom_components.pge_energy.panel.panel_custom.async_register_panel",
            new=register,
        ),
        patch(
            "custom_components.pge_energy.panel.async_save_panel_settings",
            new_callable=AsyncMock,
        ) as save,
        pytest.raises(RuntimeError, match="boom"),
    ):
        await async_apply_panel(hass, bad)

    assert register.await_count == 2
    assert register.await_args_list[1].kwargs["sidebar_title"] == previous.sidebar_title
    save.assert_awaited_once_with(hass, previous)
    assert hass.data[PANEL_APPLIED_SETTINGS_KEY] == previous


@pytest.mark.asyncio
async def test_async_teardown_panel_removes_once():
    hass = MagicMock()
    hass.data = {PANEL_SETUP_KEY: True, PANEL_APPLIED_SETTINGS_KEY: default_panel_settings()}

    with patch("custom_components.pge_energy.panel.frontend.async_remove_panel") as remove:
        async_teardown_panel(hass)
        async_teardown_panel(hass)

    remove.assert_called_once_with(hass, PANEL_URL_PATH)
    assert PANEL_SETUP_KEY not in hass.data
    assert PANEL_APPLIED_SETTINGS_KEY not in hass.data


@pytest.mark.asyncio
async def test_unload_tears_down_panel_when_last_entry():
    from custom_components.pge_energy import async_unload_entry

    hass = MagicMock()
    hass.data = {DOMAIN: {}, PANEL_SETUP_KEY: True}
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.services.async_remove = MagicMock()
    hass.services.has_service = MagicMock(return_value=True)

    entry = MagicMock()
    entry.entry_id = "entry1"
    entry.data = {"account_id": "acct", "account_key": "keykeykeykeykeyk"}

    auth = MagicMock()
    auth.account_key = "keykeykeykeykeyk"
    auth.auth_mode = "credential"
    client = MagicMock()
    coord = PGECoordinator(hass, entry, auth, client)
    hass.data[DOMAIN][entry.entry_id] = coord

    with patch("custom_components.pge_energy.panel.frontend.async_remove_panel") as remove:
        ok = await async_unload_entry(hass, entry)

    assert ok is True
    assert DOMAIN not in hass.data
    remove.assert_called_once_with(hass, PANEL_URL_PATH)
    assert hass.services.async_remove.call_count == 5
