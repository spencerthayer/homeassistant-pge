from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.pge_energy import async_migrate_entry
from custom_components.pge_energy.auth import generate_legacy_account_key
from custom_components.pge_energy.const import (
    CONF_ACCOUNT_ID,
    CONF_ACCOUNT_KEY,
    CONF_BEARER_TOKEN,
    CONF_ENCRYPTED_PERSON_ID,
)


@pytest.mark.asyncio
async def test_migrate_preserves_legacy_account_key():
    hass = MagicMock()
    entry = MagicMock()
    entry.version = 1
    entry.data = {
        CONF_BEARER_TOKEN: "tok",
        CONF_ENCRYPTED_PERSON_ID: "enc_person",
        CONF_ACCOUNT_ID: "acct123",
    }
    expected = generate_legacy_account_key("manual", "acct123", "enc_person")

    ok = await async_migrate_entry(hass, entry)
    assert ok is True
    hass.config_entries.async_update_entry.assert_called_once()
    kwargs = hass.config_entries.async_update_entry.call_args.kwargs
    assert kwargs["version"] == 2
    assert kwargs["data"][CONF_ACCOUNT_KEY] == expected


@pytest.mark.asyncio
async def test_migrate_keeps_existing_account_key():
    hass = MagicMock()
    entry = MagicMock()
    entry.version = 1
    entry.data = {
        CONF_BEARER_TOKEN: "tok",
        CONF_ENCRYPTED_PERSON_ID: "enc_person",
        CONF_ACCOUNT_ID: "acct123",
        CONF_ACCOUNT_KEY: "fixedkeyfixedkey",
    }
    ok = await async_migrate_entry(hass, entry)
    assert ok is True
    kwargs = hass.config_entries.async_update_entry.call_args.kwargs
    assert kwargs["data"][CONF_ACCOUNT_KEY] == "fixedkeyfixedkey"
