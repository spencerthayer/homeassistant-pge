from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.pge_energy.auth import (
    PGEAuthManager,
    generate_account_key,
    generate_immutable_account_key,
)
from custom_components.pge_energy.exceptions import PGEAuthenticationError


class TestAccountKeyGeneration:
    def test_generate_account_key(self):
        key = generate_account_key("portal", "acct123", "enc456")
        assert len(key) == 16
        assert key == generate_account_key("portal", "acct123", "enc456")

    def test_different_inputs_different_keys(self):
        key1 = generate_account_key("portal", "acct1", "enc1")
        key2 = generate_account_key("portal", "acct2", "enc1")
        assert key1 != key2

    def test_immutable_key_is_stable_length(self):
        key = generate_immutable_account_key()
        assert len(key) == 16
        assert key != generate_immutable_account_key()

    def test_persisted_account_key_not_derived_from_person_id(self):
        mgr = PGEAuthManager(
            "token",
            "enc_person_A",
            "acct123",
            account_key="fixedkeyfixedkey",
        )
        mgr.update_identity(encrypted_person_id="enc_person_B")
        assert mgr.account_key == "fixedkeyfixedkey"


class TestAuthManager:
    def test_init(self):
        mgr = PGEAuthManager("token123", "enc_person", "acct123")
        assert mgr.access_token == "token123"
        assert mgr.encrypted_person_id == "enc_person"
        assert mgr.account_id == "acct123"

    def test_account_key(self):
        mgr = PGEAuthManager("token123", "enc_person", "acct123")
        key = mgr.account_key
        assert len(key) == 16
        assert key == generate_account_key("manual", "acct123", "enc_person")

    def test_identity(self):
        mgr = PGEAuthManager("token123", "enc_person", "acct123")
        identity = mgr.identity
        assert identity.portal_identity == "manual"
        assert identity.account_id == "acct123"

    def test_no_expiry_legacy_manual_not_expired(self):
        mgr = PGEAuthManager(
            "token123",
            "enc_person",
            "acct123",
            auth_mode="manual_token",
        )
        assert mgr.is_token_expired() is False

    def test_no_expiry_credential_treated_as_expired(self):
        mgr = PGEAuthManager(
            "token123",
            "enc_person",
            "acct123",
            auth_mode="credential",
            password="secret",
        )
        assert mgr.is_token_expired() is True

    def test_with_expiry_future(self):
        future = datetime.now(UTC) + timedelta(hours=1)
        mgr = PGEAuthManager("token123", "enc_person", "acct123", future)
        assert mgr.is_token_expired() is False

    def test_with_expiry_past(self):
        past = datetime.now(UTC) - timedelta(hours=1)
        mgr = PGEAuthManager("token123", "enc_person", "acct123", past)
        assert mgr.is_token_expired() is True

    @pytest.mark.asyncio
    async def test_ensure_valid_token_legacy_manual(self):
        mgr = PGEAuthManager(
            "token123",
            "enc_person",
            "acct123",
            auth_mode="manual_token",
        )
        token = await mgr.ensure_valid_token()
        assert token == "token123"

    @pytest.mark.asyncio
    async def test_ensure_valid_token_expired(self):
        past = datetime.now(UTC) - timedelta(hours=1)
        mgr = PGEAuthManager(
            "token123",
            "enc_person",
            "acct123",
            past,
            auth_mode="manual_token",
        )
        with pytest.raises(PGEAuthenticationError):
            await mgr.ensure_valid_token()

    @pytest.mark.asyncio
    async def test_ensure_valid_token_force_renews_credential(self):
        from unittest.mock import AsyncMock, patch

        from custom_components.pge_energy.portal_auth import PortalAuthResult

        future = datetime.now(UTC) + timedelta(hours=1)
        mgr = PGEAuthManager(
            "old",
            "enc",
            "acct",
            token_expires_at=future,
            email="user@example.com",
            password="secret",
            auth_mode="credential",
        )
        result = PortalAuthResult(
            access_token="new-token",
            encrypted_person_id="enc",
            account_ids=["acct"],
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            refresh_credential="refresh",
        )
        with patch(
            "custom_components.pge_energy.portal_auth.async_login_or_refresh",
            AsyncMock(return_value=result),
        ) as mock_login:
            token = await mgr.ensure_valid_token(force=True)
        assert token == "new-token"
        mock_login.assert_awaited_once()

    def test_update_token(self):
        mgr = PGEAuthManager("old_token", "enc_person", "acct123")
        mgr.update_token("new_token")
        assert mgr.access_token == "new_token"

    def test_account(self):
        mgr = PGEAuthManager("token", "enc", "acct")
        acct = mgr.account
        assert acct.account_id == "acct"
        assert acct.encrypted_person_id == "enc"

    def test_persistable_auth_data_includes_expiry_and_password(self):
        expires = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
        mgr = PGEAuthManager(
            "token123",
            "enc_person",
            "acct123",
            token_expires_at=expires,
            password="secret",
            refresh_credential="refresh-secret",
            auth_mode="credential",
        )
        data = mgr.persistable_auth_data()
        assert data["bearer_token"] == "token123"
        assert data["token_expires_at"] == expires.isoformat()
        assert data["refresh_credential"] == "refresh-secret"
        assert data["password"] == "secret"

    def test_skew_treats_near_expiry_as_expired(self):
        near = datetime.now(UTC) + timedelta(seconds=30)
        mgr = PGEAuthManager("token123", "enc_person", "acct123", near)
        assert mgr.is_token_expired(skew_seconds=120) is True

    @pytest.mark.asyncio
    async def test_force_renew_legacy_manual_mode_fails(self):
        # Legacy entries only — manual_token is no longer creatable.
        mgr = PGEAuthManager("token", "enc", "acct", auth_mode="manual_token")
        with pytest.raises(PGEAuthenticationError):
            await mgr.force_renew()

    @pytest.mark.asyncio
    async def test_force_renew_credential_calls_portal(self):
        from unittest.mock import AsyncMock, patch

        from custom_components.pge_energy.portal_auth import PortalAuthResult

        mgr = PGEAuthManager(
            "old",
            "enc",
            "acct",
            email="user@example.com",
            password="secret",
            auth_mode="credential",
        )
        result = PortalAuthResult(
            access_token="new-token",
            encrypted_person_id="enc2",
            account_ids=["acct"],
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            refresh_credential="refresh-2",
        )
        with patch(
            "custom_components.pge_energy.portal_auth.async_login_or_refresh",
            AsyncMock(return_value=result),
        ):
            token = await mgr.force_renew()
        assert token == "new-token"
        assert mgr.encrypted_person_id == "enc2"
        assert mgr.refresh_credential == "refresh-2"
