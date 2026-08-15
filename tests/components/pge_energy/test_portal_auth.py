from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.pge_energy.exceptions import (
    PGEAuthenticationError,
    PGECaptchaUnsupportedError,
    PGEMfaUnsupportedError,
    PGERateLimitError,
)
from custom_components.pge_energy.portal_auth import (
    _classify_cognito_error,
    _extract_accounts,
    _extract_detail_list_accounts,
    _merge_account_ids,
    async_login_or_refresh,
    classify_challenge,
)


class TestClassifyCognitoError:
    def test_too_many_requests(self):
        with pytest.raises(PGERateLimitError) as excinfo:
            _classify_cognito_error({"__type": "TooManyRequestsException", "message": "Too many requests"})
        assert excinfo.value.retry_after == 60.0

    def test_password_attempts_exceeded_before_not_authorized(self):
        with pytest.raises(PGERateLimitError) as excinfo:
            _classify_cognito_error(
                {
                    "__type": "NotAuthorizedException",
                    "message": "Password attempts exceeded",
                }
            )
        assert excinfo.value.retry_after == 900.0

    def test_incorrect_password_still_auth_error(self):
        with pytest.raises(PGEAuthenticationError):
            _classify_cognito_error(
                {
                    "__type": "NotAuthorizedException",
                    "message": "Incorrect username or password.",
                }
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
    async def test_rate_limit_does_not_fall_back_to_refresh(self):
        session = _mock_session_post(
            [
                (
                    400,
                    {
                        "__type": "TooManyRequestsException",
                        "message": "Too many requests",
                    },
                )
            ]
        )
        with (
            patch(
                "custom_components.pge_energy.portal_auth.aiohttp.ClientSession",
                return_value=session,
            ),
            pytest.raises(PGERateLimitError),
        ):
            await async_login_or_refresh(
                email="user@example.com",
                password="secret",
                refresh_credential="must-not-be-used",
            )
        # Only the password InitiateAuth — no refresh InitiateAuth / Apigee / GraphQL.
        assert session.post.call_count == 1

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


class TestAccountDiscoveryMerge:
    def test_merge_preserves_order_and_dedupes(self):
        assert _merge_account_ids(["111"], ["111", "222"], ["333", "222"]) == ["111", "222", "333"]

    def test_extract_defaults_ignores_non_default_shape(self):
        person, ids = _extract_accounts(
            {
                "encryptedPersonId": "enc-person",
                "accountMeta": {"totalAccounts": 2, "hasInactiveAccounts": False},
                "groups": [
                    {
                        "numberOfAccounts": 2,
                        "defaultAccount": {"accountNumber": "1122334455"},
                    }
                ],
            }
        )
        assert person == "enc-person"
        assert ids == ["1122334455"]

    def test_extract_detail_list_collects_all_rows(self):
        person, ids = _extract_detail_list_accounts(
            {
                "totalCount": 2,
                "accounts": [
                    {"accountNumber": "1122334455", "encryptedPersonId": "enc-a"},
                    {"accountNumber": "9988776655", "encryptedPersonId": "enc-b"},
                ],
            }
        )
        assert person == "enc-a"
        assert ids == ["1122334455", "9988776655"]

    @pytest.mark.asyncio
    async def test_login_merges_non_default_detail_list_account(self):
        """Issue #20: second ACTIVE account is only on getAccountDetailList."""
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
                                "accountMeta": {"totalAccounts": 2, "hasInactiveAccounts": False},
                                "groups": [
                                    {
                                        "groupId": "g1",
                                        "numberOfAccounts": 2,
                                        "isDefault": True,
                                        "defaultAccount": {
                                            "accountNumber": "1122334455",
                                            "encryptedPersonId": "enc-person",
                                        },
                                    }
                                ],
                            }
                        }
                    },
                ),
                (
                    200,
                    {
                        "data": {
                            "getAccountDetailList": {
                                "totalCount": 2,
                                "accounts": [
                                    {"accountNumber": "1122334455", "encryptedPersonId": "enc-person"},
                                    {"accountNumber": "9988776655", "encryptedPersonId": "enc-person"},
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
        assert result.account_ids == ["1122334455", "9988776655"]
        assert session.post.call_count == 4

    @pytest.mark.asyncio
    async def test_login_soft_fails_detail_list_keeps_defaults(self):
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
                                            "accountNumber": "1122334455",
                                            "encryptedPersonId": "enc-person",
                                        }
                                    }
                                ],
                            }
                        }
                    },
                ),
                (500, {"errors": [{"message": "boom"}]}),
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
        assert result.account_ids == ["1122334455"]

    @pytest.mark.asyncio
    async def test_login_multi_group_defaults_plus_detail_list(self):
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
                                "accountMeta": {"totalAccounts": 3, "hasInactiveAccounts": False},
                                "groups": [
                                    {
                                        "numberOfAccounts": 1,
                                        "defaultAccount": {"accountNumber": "1111111111"},
                                    },
                                    {
                                        "numberOfAccounts": 2,
                                        "defaultAccount": {"accountNumber": "2222222222"},
                                    },
                                ],
                            }
                        }
                    },
                ),
                (
                    200,
                    {
                        "data": {
                            "getAccountDetailList": {
                                "totalCount": 3,
                                "accounts": [
                                    {"accountNumber": "1111111111"},
                                    {"accountNumber": "2222222222"},
                                    {"accountNumber": "3333333333"},
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
        assert result.account_ids == ["1111111111", "2222222222", "3333333333"]
