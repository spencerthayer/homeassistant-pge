from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.pge_energy.const import (
    AUTH_MODE_CREDENTIAL,
    CONF_ACCOUNT_ID,
    CONF_AUTH_MODE,
    CONF_BEARER_TOKEN,
    CONF_EMAIL,
    CONF_ENCRYPTED_PERSON_ID,
    CONF_PASSWORD,
    DOMAIN,
)
from tests.conftest import (
    TEST_ACCOUNT_ID,
    TEST_ENCRYPTED_PERSON_ID,
    TEST_TOKEN,
)


@pytest.fixture
def mock_config_entry():
    from homeassistant.config_entries import ConfigEntry

    return ConfigEntry(
        domain=DOMAIN,
        data={
            CONF_AUTH_MODE: AUTH_MODE_CREDENTIAL,
            CONF_BEARER_TOKEN: TEST_TOKEN,
            CONF_ENCRYPTED_PERSON_ID: TEST_ENCRYPTED_PERSON_ID,
            CONF_ACCOUNT_ID: TEST_ACCOUNT_ID,
            CONF_EMAIL: "user@example.com",
            CONF_PASSWORD: "secret",
        },
        entry_id="test_entry",
        unique_id=TEST_ACCOUNT_ID,
    )


@pytest.fixture
def hass():
    """Mock hass for fast unit tests (not the real HA fixture)."""
    mock_hass = MagicMock(spec=HomeAssistant)
    mock_hass.config_entries = MagicMock()
    mock_hass.config_entries.flow = MagicMock()
    mock_hass.data = {}
    mock_hass.helpers = MagicMock()
    mock_hass.helpers.aiohttp_client = MagicMock()
    mock_hass.helpers.aiohttp_client.async_get_clientsession = MagicMock(return_value=AsyncMock())
    return mock_hass
