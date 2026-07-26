from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.pge_energy.api import PGEApiClient
from custom_components.pge_energy.auth import PGEAuthManager


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
