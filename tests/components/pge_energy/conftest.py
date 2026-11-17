from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.pge_energy import coordinator as coordinator_mod
from custom_components.pge_energy.api import PGEApiClient
from custom_components.pge_energy.auth import PGEAuthManager
from custom_components.pge_energy.coordinator import clear_refresh_admission


@pytest.fixture(autouse=True)
def _reset_reload_admission():
    """Reload admission is process-global so one poll cannot suppress the next test."""
    clear_refresh_admission()
    coordinator_mod._REFRESH_NEXT_MONOTONIC.clear()
    yield
    clear_refresh_admission()


@pytest.fixture
def mock_auth_manager() -> PGEAuthManager:
    return PGEAuthManager(
        token="SYNTHETIC_TOKEN",
        encrypted_person_id="SYNTHETIC_PERSON_ID",
        account_id="0000000000",
    )


@pytest.fixture
def mock_api_client() -> MagicMock:
    client = MagicMock(spec=PGEApiClient)
    client.get_usage = AsyncMock()
    return client
