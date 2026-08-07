from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.pge_energy import async_remove_entry
from custom_components.pge_energy.const import DOMAIN, ENTRY_STATISTIC_SUFFIXES
from custom_components.pge_energy.statistics import entry_statistic_ids


def test_entry_statistic_ids_cover_usage_billing_and_pdf():
    ids = entry_statistic_ids("abcd1234efgh5678")
    assert len(ids) == len(ENTRY_STATISTIC_SUFFIXES)
    assert f"{DOMAIN}:abcd1234efgh5678_consumption" in ids
    assert f"{DOMAIN}:abcd1234efgh5678_return" in ids
    assert f"{DOMAIN}:abcd1234efgh5678_bill_pdf_amount_due" in ids


@pytest.mark.asyncio
async def test_async_remove_entry_clears_external_statistics():
    hass = MagicMock()
    entry = MagicMock()
    entry.data = {"account_key": "keykeykeykeykeyk", "account_id": "1234567890"}

    with patch(
        "custom_components.pge_energy.async_clear_entry_statistics",
        new_callable=AsyncMock,
        return_value=True,
    ) as clear:
        await async_remove_entry(hass, entry)

    clear.assert_awaited_once_with(hass, "keykeykeykeykeyk")


@pytest.mark.asyncio
async def test_async_remove_entry_skips_when_account_key_missing():
    hass = MagicMock()
    entry = MagicMock()
    entry.data = {"account_id": "1234567890"}

    with patch(
        "custom_components.pge_energy.async_clear_entry_statistics",
        new_callable=AsyncMock,
    ) as clear:
        await async_remove_entry(hass, entry)

    clear.assert_not_called()
