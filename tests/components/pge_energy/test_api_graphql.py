from __future__ import annotations

import pytest

from custom_components.pge_energy.api import _parse_usage_response
from custom_components.pge_energy.exceptions import (
    PGEAuthenticationError,
    PGEAuthorizationError,
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

    def test_graphql_auth_error_does_not_expose_server_secrets(self):
        email = "user@example.com"
        account = "123456789"
        person = "987654321"
        jwt = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            + "dozjgNryP4J3jVmNHl0w5N_Z99UmkT1A1kK2kK2k"
        )
        password = "pw-SENTINEL-hunter2"
        opaque = "opaque-SENTINEL-token"
        message = (
            f"Unauthorized token for {email} account {account} person {person} "
            f"jwt {jwt} password={password} bearer {opaque}"
        )
        with pytest.raises(PGEAuthenticationError) as caught:
            _parse_usage_response(
                {"errors": [{"message": message}]},
                UsageResolution.HOURLY,
                "key",
            )
        text = str(caught.value)
        assert text == "GraphQL rejected the session as unauthenticated"
        for sentinel in (email, account, person, jwt, password, opaque):
            assert sentinel not in text

        with pytest.raises(PGEAuthenticationError) as token_caught:
            _parse_usage_response(
                {"errors": [{"message": "access token expired"}]},
                UsageResolution.HOURLY,
                "key",
            )
        assert str(token_caught.value) == "GraphQL rejected the access token"

        with pytest.raises(PGEAuthenticationError) as generic_caught:
            _parse_usage_response(
                {"errors": [{"message": "auth check failed"}]},
                UsageResolution.HOURLY,
                "key",
            )
        assert str(generic_caught.value) == "GraphQL authentication failed"

    def test_graphql_non_auth_error_does_not_expose_server_secrets(self):
        email = "user@example.com"
        jwt = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            + "dozjgNryP4J3jVmNHl0w5N_Z99UmkT1A1kK2kK2k"
        )
        password = "pw-SENTINEL-hunter2"
        bearer = "opaque-SENTINEL-secret"
        forbidden = f"Forbidden for {email}; session {jwt} invalid password={password} bearer {bearer}"
        with pytest.raises(PGEAuthorizationError) as caught:
            _parse_usage_response(
                {"errors": [{"message": forbidden}]},
                UsageResolution.HOURLY,
                "key",
            )
        text = str(caught.value)
        assert text == "GraphQL rejected the request as forbidden"
        for sentinel in (email, jwt, password, bearer):
            assert sentinel not in text

        with pytest.raises(PGEAuthorizationError) as denied:
            _parse_usage_response(
                {"errors": [{"message": "Access denied"}]},
                UsageResolution.HOURLY,
                "key",
            )
        assert str(denied.value) == "GraphQL rejected the request as access denied"

        with pytest.raises(PGEAuthorizationError) as blocked:
            _parse_usage_response(
                {"errors": [{"message": "Not allowed"}]},
                UsageResolution.HOURLY,
                "key",
            )
        assert str(blocked.value) == "GraphQL rejected the request as not allowed"

        generic = f"upstream failed for {email} password={password} bearer {bearer} {jwt}"
        with pytest.raises(PGEGraphQLError) as generic_caught:
            _parse_usage_response(
                {"errors": [{"message": generic}]},
                UsageResolution.HOURLY,
                "key",
            )
        generic_text = str(generic_caught.value)
        assert generic_text == "GraphQL request failed"
        for sentinel in (email, jwt, password, bearer):
            assert sentinel not in generic_text
