from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.pge_energy.exceptions import (
    PGEAuthenticationError,
    PGECaptchaUnsupportedError,
    PGEMfaUnsupportedError,
)
from custom_components.pge_energy.portal_auth import (
    async_login_or_refresh,
    classify_challenge,
)


class TestClassifyChallenge:
    def test_mfa_generic_key(self):
        with pytest.raises(PGEMfaUnsupportedError):
            classify_challenge({"mfaRequired": True})

    def test_mfa_challenge_name(self):
        with pytest.raises(PGEMfaUnsupportedError):
            classify_challenge({"ChallengeName": "SMS_MFA"})

    def test_mfa_status(self):
        with pytest.raises(PGEMfaUnsupportedError):
            classify_challenge({"status": "MFA_REQUIRED"})

    def test_captcha(self):
        with pytest.raises(PGECaptchaUnsupportedError):
            classify_challenge({"captchaRequired": True})

    def test_clean(self):
        classify_challenge({"ok": True})


def _mock_session_post(responses: list[tuple[int, dict]]):
    """Build an aiohttp ClientSession mock that returns queued JSON responses."""
    queue = list(responses)

    class _Resp:
        def __init__(self, status: int, payload: dict):
            self.status = status
            self._payload = payload

        async def json(self, content_type=None):  # noqa: ANN001
            return self._payload

        async def text(self) -> str:
            return ""

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):  # noqa: ANN002
            return False

    session = MagicMock()

    def _post(url, **kwargs):  # noqa: ANN003
        assert queue, f"unexpected request to {url}"
        status, payload = queue.pop(0)
        return _Resp(status, payload)

    session.post = MagicMock(side_effect=_post)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


class TestLoginOrRefresh:
    @pytest.mark.asyncio
    async def test_password_login_success(self):
        session = _mock_session_post(
            [
                (
                    200,
                    {
                        "AuthenticationResult": {
                            "IdToken": "id.jwt.token",
                            "AccessToken": "access.jwt.token",
                            "RefreshToken": "refresh-token-value",
                            "ExpiresIn": 3600,
                            "TokenType": "Bearer",
                        }
                    },
                ),
                (200, {"access_token": "apigee-bearer", "expires_at": 1893456000}),
                (
                    200,
                    {
                        "data": {
                            "getAccountInfo": {
                                "encryptedPersonId": "enc-person",
                                "groups": [
                                    {
                                        "defaultAccount": {
                                            "accountNumber": "0000000000",
                                            "encryptedPersonId": "enc-person",
                                        }
                                    }
                                ],
                            }
                        }
                    },
                ),
            ]
        )
        with patch(
            "custom_components.pge_energy.portal_auth.aiohttp.ClientSession",
            return_value=session,
        ):
            result = await async_login_or_refresh(
                email="user@example.com",
                password="secret",
                refresh_credential=None,
            )
        assert result.access_token == "apigee-bearer"
        assert result.encrypted_person_id == "enc-person"
        assert result.account_ids == ["0000000000"]
        assert result.refresh_credential == "refresh-token-value"
        assert result.expires_at == datetime.fromtimestamp(1893456000, tz=UTC)

    @pytest.mark.asyncio
    async def test_mfa_challenge_fails_closed(self):
        session = _mock_session_post([(200, {"ChallengeName": "SOFTWARE_TOKEN_MFA", "Session": "sess"})])
        with (
            patch(
                "custom_components.pge_energy.portal_auth.aiohttp.ClientSession",
                return_value=session,
            ),
            pytest.raises(PGEMfaUnsupportedError),
        ):
            await async_login_or_refresh(
                email="user@example.com",
                password="secret",
                refresh_credential=None,
            )

    @pytest.mark.asyncio
    async def test_not_authorized(self):
        session = _mock_session_post(
            [
                (
                    400,
                    {
                        "__type": "NotAuthorizedException",
                        "message": "Incorrect username or password.",
                    },
                )
            ]
        )
        with (
            patch(
                "custom_components.pge_energy.portal_auth.aiohttp.ClientSession",
                return_value=session,
            ),
            pytest.raises(PGEAuthenticationError),
        ):
            await async_login_or_refresh(
                email="user@example.com",
                password="secret",
                refresh_credential=None,
            )

    @pytest.mark.asyncio
    async def test_refresh_credential_path(self):
        session = _mock_session_post(
            [
                (
                    200,
                    {
                        "AuthenticationResult": {
                            "IdToken": "id.jwt.token",
                            "AccessToken": "access.jwt.token",
                            "ExpiresIn": 3600,
                            "TokenType": "Bearer",
                        }
                    },
                ),
                (200, {"access_token": "apigee-bearer-2", "expires_at": 1893456000}),
                (
                    200,
                    {
                        "data": {
                            "getAccountInfo": {
                                "encryptedPersonId": "enc-person",
                                "groups": [],
                            }
                        }
                    },
                ),
            ]
        )
        with patch(
            "custom_components.pge_energy.portal_auth.aiohttp.ClientSession",
            return_value=session,
        ):
            result = await async_login_or_refresh(
                email="user@example.com",
                password=None,
                refresh_credential="prior-refresh",
            )
        assert result.access_token == "apigee-bearer-2"
        assert result.refresh_credential == "prior-refresh"

    @pytest.mark.asyncio
    async def test_password_preferred_over_refresh(self):
        """When password is present, login with password (not Cognito refresh)."""
        session = _mock_session_post(
            [
                (
                    200,
                    {
                        "AuthenticationResult": {
                            "IdToken": "id.jwt.token",
                            "AccessToken": "access.jwt.token",
                            "RefreshToken": "refresh-from-password",
                            "ExpiresIn": 3600,
                            "TokenType": "Bearer",
                        }
                    },
                ),
                (200, {"access_token": "apigee-from-password", "expires_at": 1893456000}),
                (
                    200,
                    {
                        "data": {
                            "getAccountInfo": {
                                "encryptedPersonId": "enc-person",
                                "groups": [
                                    {
                                        "defaultAccount": {
                                            "accountNumber": "111",
                                            "encryptedPersonId": "enc-person",
                                        }
                                    }
                                ],
                            }
                        }
                    },
                ),
            ]
        )
        with patch(
            "custom_components.pge_energy.portal_auth.aiohttp.ClientSession",
            return_value=session,
        ):
            result = await async_login_or_refresh(
                email="user@example.com",
                password="secret",
                refresh_credential="stale-refresh-should-not-be-used",
            )
        assert result.access_token == "apigee-from-password"
        assert result.refresh_credential == "refresh-from-password"
