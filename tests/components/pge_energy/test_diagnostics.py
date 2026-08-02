from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.pge_energy.const import (
    CONF_CAPTURE_GRAPHQL_DIAGNOSTICS,
    DOMAIN,
    VERSION,
)
from custom_components.pge_energy.diagnostics import async_get_config_entry_diagnostics


@pytest.mark.asyncio
async def test_diagnostics_reports_safe_capture_status_and_current_version():
    coordinator = SimpleNamespace(
        freshness=SimpleNamespace(
            last_successful_update=None,
            newest_interval=None,
            last_api_error=None,
            data_age_seconds=None,
        ),
        checkpoint=SimpleNamespace(last_imported_end=None),
        auth_manager=SimpleNamespace(token_expires_at=None),
        account_key="safe-account-key",
        update_interval=None,
        correction_window_days=7,
        recent_intervals=[],
        failed_ranges=[],
        lifetime_energy_kwh=12.3,
        lifetime_cost_usd=4.5,
        client=SimpleNamespace(introspection_attempted=True, captured_response_count=3),
        import_store=SimpleNamespace(
            bill_pdf_index={},
            bill_pdf_last_success=None,
            bill_pdf_last_error=None,
        ),
        bill_pdf_summary={},
    )
    entry = MagicMock()
    entry.entry_id = "entry-1"
    entry.data = {"email": "private@example.com", "bearer_token": "secret"}
    entry.options = {CONF_CAPTURE_GRAPHQL_DIAGNOSTICS: True}
    hass = MagicMock()
    hass.version = "2026.7.0"
    hass.data = {DOMAIN: {entry.entry_id: coordinator}}

    with patch(
        "custom_components.pge_energy.diagnostics.async_resolve_sensor_entity_id",
        return_value=None,
    ):
        result = await async_get_config_entry_diagnostics(hass, entry)

    diagnostics = result["diagnostics"]
    assert diagnostics["integration_version"] == VERSION
    assert diagnostics["graphql_diagnostic_capture"] == {
        "enabled": True,
        "introspection_attempted": True,
        "captured_responses": 3,
    }
    assert result["config_entry_data"]["email"] == "**REDACTED**"
    assert result["config_entry_data"]["bearer_token"] == "**REDACTED**"
