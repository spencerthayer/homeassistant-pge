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
    PANEL_SIDEBAR_TITLE,
    PANEL_URL_PATH,
    PANEL_WEBCOMPONENT,
    VERSION,
)
from custom_components.pge_energy.coordinator import PGECoordinator
from custom_components.pge_energy.panel import (
    async_setup_panel,
    async_teardown_panel,
)


def test_panel_module_does_not_touch_frontend_user_sidebar_store():
    source = Path(panel_module.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "async_user_store",
        "panelOrder",
        "hiddenPanels",
        "async_get_users",
    ):
        assert forbidden not in source, f"panel.py must not reference {forbidden}"


@pytest.mark.asyncio
async def test_async_setup_panel_registers_paths_and_panel():
    hass = MagicMock()
    hass.data = {}
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    hass.auth.async_get_users = AsyncMock(return_value=[])

    with patch(
        "custom_components.pge_energy.panel.panel_custom.async_register_panel",
        new_callable=AsyncMock,
    ) as register_panel:
        await async_setup_panel(hass)
        await async_setup_panel(hass)  # idempotent

    assert hass.data[PANEL_SETUP_KEY] is True
    assert hass.http.async_register_static_paths.await_count == 1
    configs = hass.http.async_register_static_paths.await_args.args[0]
    assert len(configs) == 2
    assert configs[0].url_path == FRONTEND_URL_PATH
    assert configs[0].cache_headers is False
    assert configs[1].url_path == BRAND_URL_PATH
    assert Path(configs[0].path).name == "frontend"
    assert Path(configs[1].path).name == "brand"

    register_panel.assert_awaited_once()
    assert hass.auth.async_get_users.await_count == 0
    kwargs = register_panel.await_args.kwargs
    assert kwargs["frontend_url_path"] == PANEL_URL_PATH
    assert kwargs["webcomponent_name"] == PANEL_WEBCOMPONENT
    assert kwargs["sidebar_title"] == PANEL_SIDEBAR_TITLE == "PGE"
    assert kwargs["require_admin"] is True
    assert kwargs["module_url"] == f"{FRONTEND_URL_PATH}/pge-panel.js?v={VERSION}"


@pytest.mark.asyncio
async def test_async_teardown_panel_removes_once():
    hass = MagicMock()
    hass.data = {PANEL_SETUP_KEY: True}

    with patch("custom_components.pge_energy.panel.frontend.async_remove_panel") as remove:
        async_teardown_panel(hass)
        async_teardown_panel(hass)

    remove.assert_called_once_with(hass, PANEL_URL_PATH)
    assert PANEL_SETUP_KEY not in hass.data


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
    assert hass.services.async_remove.call_count == 4
