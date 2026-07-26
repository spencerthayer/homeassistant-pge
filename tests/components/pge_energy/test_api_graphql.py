from __future__ import annotations

import pytest

from custom_components.pge_energy.api import _parse_usage_response
from custom_components.pge_energy.exceptions import (
    PGEAuthenticationError,
    PGEGraphQLError,
)
from custom_components.pge_energy.models import UsageResolution


class TestGraphQLErrors:
    def test_auth_graphql_error(self):
        with pytest.raises(PGEAuthenticationError):
            _parse_usage_response(
                {"errors": [{"message": "Unauthorized token"}]},
                UsageResolution.HOURLY,
                "key",
            )

    def test_generic_graphql_error(self):
        with pytest.raises(PGEGraphQLError):
            _parse_usage_response(
                {"errors": [{"message": "Something else"}]},
                UsageResolution.HOURLY,
                "key",
            )
