from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .const import (
    AUTH_MODE_CREDENTIAL,
    COGNITO_RATE_LIMIT_DEFAULT_SECONDS,
    COGNITO_RATE_LIMIT_MAX_SECONDS,
    COGNITO_RATE_LIMIT_UNTIL_KEY,
    CONF_ACCOUNT_ID,
    CONF_BEARER_TOKEN,
    CONF_ENCRYPTED_ACCOUNT_NUMBER,
    CONF_ENCRYPTED_PERSON_ID,
    CONF_ENCRYPTED_PREMISE_ID,
    CONF_ENCRYPTED_SA_ID,
    CONF_PASSWORD,
    CONF_REFRESH_CREDENTIAL,
    CONF_TOKEN_EXPIRES_AT,
    DOMAIN,
    TOKEN_EXPIRY_SKEW_SECONDS,
)
from .exceptions import PGEAuthenticationError, PGERateLimitError
from .models import PGEAccount, PGEIdentity, PGEToken

_LOGGER = logging.getLogger(__name__)


def generate_legacy_account_key(portal_identity: str, account_id: str, encrypted_person_id: str) -> str:
    """Legacy derived key — preserved for existing entries that lack account_key."""
    raw = f"{portal_identity}:{account_id}:{encrypted_person_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# Backward-compatible alias used by older tests/callers.
generate_account_key = generate_legacy_account_key


def generate_stable_account_key(account_id: str) -> str:
    """Opaque key stable for the same PGE account number across delete/re-add.

    Statistic ids are ``pge_energy:<account_key>_*``. Deriving the key from the
    account number (not person id / tokens) keeps Energy dashboard sources and
    recorder history attached when an entry is removed and set up again.
    Credential renewal still leaves the persisted key untouched.
    """
    normalized = str(account_id or "").strip()
    if not normalized:
        raise ValueError("account_id is required for a stable account_key")
    return hashlib.sha256(f"{DOMAIN}:account:{normalized}".encode()).hexdigest()[:16]


def generate_immutable_account_key() -> str:
    """Random opaque key for ephemeral/CLI use (not used by config setup)."""
    return secrets.token_hex(8)


def normalize_auth_email(email: str | None) -> str | None:
    if not email or not str(email).strip():
        return None
    return str(email).strip().lower()


def _cap_retry_after(seconds: float | None) -> float:
    delay = COGNITO_RATE_LIMIT_DEFAULT_SECONDS if seconds is None else float(seconds)
    if delay < 1.0:
        delay = 1.0
    return min(delay, COGNITO_RATE_LIMIT_MAX_SECONDS)


def get_shared_cognito_rate_limit_until(hass: Any, email: str | None) -> datetime | None:
    """Return the domain-wide Cognito cooldown for a login email, if any."""
    key = normalize_auth_email(email)
    if hass is None or key is None:
        return None
    bucket = hass.data.get(DOMAIN, {}).get(COGNITO_RATE_LIMIT_UNTIL_KEY)
    if not isinstance(bucket, dict):
        return None
    until = bucket.get(key)
    return until if isinstance(until, datetime) else None


def set_shared_cognito_rate_limit_until(hass: Any, email: str | None, until: datetime) -> None:
    """Publish Cognito cooldown so every entry with the same email backs off."""
    key = normalize_auth_email(email)
    if hass is None or key is None:
        return
    domain_data = hass.data.setdefault(DOMAIN, {})
    bucket = domain_data.setdefault(COGNITO_RATE_LIMIT_UNTIL_KEY, {})
    if not isinstance(bucket, dict):
        bucket = {}
        domain_data[COGNITO_RATE_LIMIT_UNTIL_KEY] = bucket
    prev = bucket.get(key)
    if isinstance(prev, datetime) and prev > until:
        return
    bucket[key] = until


@dataclass(frozen=True, slots=True)
class AuthSnapshot:
    access_token: str
    encrypted_person_id: str
    account_id: str
    expires_at: datetime | None = None
    encrypted_account_number: str | None = None
    encrypted_premise_id: str | None = None
    encrypted_sa_id: str | None = None


class PGEAuthManager:
    """Manage short-lived PGE bearer tokens for credential-mode entries.

    Design assumption: Apigee bearer tokens expire frequently — often within a
    single sync/backfill job. Credential mode therefore:

    1. Prefers email/password login when a password is stored
    2. Proactively renews when expiry is unknown or near
    3. Supports forced renewal (401 mid-request) under a lock so concurrent
       day fetches share one login and continue the running sync
    4. Respects Cognito InitiateAuth throttle / password-attempt lockout with a
       shared per-email cooldown (no Cognito calls while cooling down)
    """

    def __init__(
        self,
        token: str,
        encrypted_person_id: str,
        account_id: str,
        token_expires_at: datetime | None = None,
        account_key: str | None = None,
        email: str | None = None,
        password: str | None = None,
        refresh_credential: str | None = None,
        auth_mode: str = AUTH_MODE_CREDENTIAL,
        encrypted_account_number: str | None = None,
        encrypted_premise_id: str | None = None,
        encrypted_sa_id: str | None = None,
        hass: Any | None = None,
    ) -> None:
        self._token = PGEToken(access_token=token, expires_at=token_expires_at)
        self._encrypted_person_id = encrypted_person_id
        self._account_id = account_id
        self._email = email
        self._password = password
        self._refresh_credential = refresh_credential
        self._auth_mode = auth_mode
        self._encrypted_account_number = encrypted_account_number
        self._encrypted_premise_id = encrypted_premise_id
        self._encrypted_sa_id = encrypted_sa_id
        self._hass = hass
        self._lock = asyncio.Lock()
        self._cognito_rate_limit_until: datetime | None = None
        # Preserve stored key when provided; otherwise fall back to the legacy
        # derivation used by older installs that never persisted account_key.
        self._account_key = account_key or generate_legacy_account_key(
            email or "manual",
            account_id,
            encrypted_person_id,
        )

    @property
    def access_token(self) -> str:
        return self._token.access_token

    @property
    def token_expires_at(self) -> datetime | None:
        return self._token.expires_at

    @property
    def encrypted_person_id(self) -> str:
        return self._encrypted_person_id

    @property
    def account_id(self) -> str:
        return self._account_id

    @property
    def account_key(self) -> str:
        return self._account_key

    @property
    def email(self) -> str | None:
        return self._email

    @property
    def password(self) -> str | None:
        return self._password

    @property
    def auth_mode(self) -> str:
        return self._auth_mode

    @property
    def encrypted_account_number(self) -> str | None:
        return self._encrypted_account_number

    @property
    def encrypted_premise_id(self) -> str | None:
        return self._encrypted_premise_id

    @property
    def encrypted_sa_id(self) -> str | None:
        return self._encrypted_sa_id

    @property
    def identity(self) -> PGEIdentity:
        return PGEIdentity(
            portal_identity=self._email or "manual",
            account_id=self._account_id,
            encrypted_person_id=self._encrypted_person_id,
        )

    @property
    def account(self) -> PGEAccount:
        return PGEAccount(
            account_id=self._account_id,
            encrypted_person_id=self._encrypted_person_id,
            account_type=None,
            is_tod=None,
        )

    def snapshot(self) -> AuthSnapshot:
        return AuthSnapshot(
            access_token=self._token.access_token,
            encrypted_person_id=self._encrypted_person_id,
            account_id=self._account_id,
            expires_at=self._token.expires_at,
            encrypted_account_number=self._encrypted_account_number,
            encrypted_premise_id=self._encrypted_premise_id,
            encrypted_sa_id=self._encrypted_sa_id,
        )

    def is_token_expired(self, *, skew_seconds: int | None = None) -> bool:
        """Return True when the bearer should be treated as unusable."""
        if skew_seconds is None:
            skew_seconds = TOKEN_EXPIRY_SKEW_SECONDS
        if self._token.expires_at is None:
            # Unknown expiry: credential mode must re-login. Legacy manual-token
            # entries (no longer creatable) treat the pasted bearer as sticky.
            return self._auth_mode == AUTH_MODE_CREDENTIAL
        return datetime.now(UTC) >= (self._token.expires_at - timedelta(seconds=skew_seconds))

    def update_token(self, token: str, expires_at: datetime | None = None) -> None:
        self._token = PGEToken(access_token=token, expires_at=expires_at)

    def update_identity(
        self,
        *,
        encrypted_person_id: str | None = None,
        account_id: str | None = None,
        encrypted_account_number: str | None = None,
        encrypted_premise_id: str | None = None,
        encrypted_sa_id: str | None = None,
    ) -> None:
        if encrypted_person_id is not None:
            self._encrypted_person_id = encrypted_person_id
        if account_id is not None:
            self._account_id = account_id
        if encrypted_account_number is not None:
            self._encrypted_account_number = encrypted_account_number
        if encrypted_premise_id is not None:
            self._encrypted_premise_id = encrypted_premise_id
        if encrypted_sa_id is not None:
            self._encrypted_sa_id = encrypted_sa_id

    @property
    def refresh_credential(self) -> str | None:
        return self._refresh_credential

    def persistable_auth_data(self) -> dict[str, str]:
        """Fields safe to merge into config entry data after renewal."""
        data: dict[str, str] = {
            CONF_BEARER_TOKEN: self._token.access_token,
            CONF_ENCRYPTED_PERSON_ID: self._encrypted_person_id,
            CONF_ACCOUNT_ID: self._account_id,
        }
        if self._token.expires_at is not None:
            data[CONF_TOKEN_EXPIRES_AT] = self._token.expires_at.isoformat()
        if self._refresh_credential:
            data[CONF_REFRESH_CREDENTIAL] = self._refresh_credential
        if self._password:
            data[CONF_PASSWORD] = self._password
        if self._encrypted_account_number:
            data[CONF_ENCRYPTED_ACCOUNT_NUMBER] = self._encrypted_account_number
        if self._encrypted_premise_id:
            data[CONF_ENCRYPTED_PREMISE_ID] = self._encrypted_premise_id
        if self._encrypted_sa_id:
            data[CONF_ENCRYPTED_SA_ID] = self._encrypted_sa_id
        return data

    def cognito_rate_limit_until(self) -> datetime | None:
        """Effective Cognito cooldown (local manager + shared email gate)."""
        local = self._cognito_rate_limit_until
        shared = get_shared_cognito_rate_limit_until(self._hass, self._email)
        if local is None:
            return shared
        if shared is None:
            return local
        return max(local, shared)

    def cognito_rate_limit_remaining_seconds(self) -> float:
        until = self.cognito_rate_limit_until()
        if until is None:
            return 0.0
        remaining = (until - datetime.now(UTC)).total_seconds()
        return max(0.0, remaining)

    def mark_cognito_rate_limited(self, retry_after: float | None = None) -> datetime:
        """Record a Cognito throttle/lockout cooldown (manager + shared email)."""
        delay = _cap_retry_after(retry_after)
        until = datetime.now(UTC) + timedelta(seconds=delay)
        current = self.cognito_rate_limit_until()
        if current is not None and current > until:
            until = current
        self._cognito_rate_limit_until = until
        set_shared_cognito_rate_limit_until(self._hass, self._email, until)
        _LOGGER.warning(
            "PGE Cognito rate-limit cooldown until %s (%.0fs) for %s",
            until.isoformat(),
            delay,
            normalize_auth_email(self._email) or "unknown",
        )
        return until

    def _raise_if_cognito_rate_limited(self) -> None:
        remaining = self.cognito_rate_limit_remaining_seconds()
        if remaining <= 0:
            return
        until = self.cognito_rate_limit_until()
        raise PGERateLimitError(
            f"PGE Cognito rate-limited until {until.isoformat() if until else 'unknown'}",
            retry_after=remaining,
        )

    async def ensure_valid_token(self, *, force: bool = False) -> str:
        """Return a usable access token, renewing when needed.

        ``force=True`` always re-authenticates (use at the start of a sync job).
        Otherwise renews when expired / near expiry / unknown expiry in
        credential mode. Concurrent callers share one renewal via the lock.
        """
        async with self._lock:
            self._raise_if_cognito_rate_limited()
            if not force and not self.is_token_expired():
                return self._token.access_token

            if self._auth_mode == AUTH_MODE_CREDENTIAL:
                await self._async_renew_credential()
                return self._token.access_token

            # Legacy AUTH_MODE_MANUAL_TOKEN entries cannot renew.
            if force or self.is_token_expired():
                raise PGEAuthenticationError("Token expired - reauthentication required")
            return self._token.access_token

    async def force_renew(self) -> str:
        """Force one renewal attempt (e.g. after GraphQL 401 mid-sync).

        Coalesces concurrent waiters: if another caller already replaced the
        token while this waiter held the lock queue, reuse that token.
        """
        prior = self._token.access_token
        async with self._lock:
            self._raise_if_cognito_rate_limited()
            if self._token.access_token != prior and not self.is_token_expired():
                return self._token.access_token
            if self._auth_mode == AUTH_MODE_CREDENTIAL:
                await self._async_renew_credential()
                return self._token.access_token
            raise PGEAuthenticationError("Token expired - reauthentication required")

    async def _async_renew_credential(self) -> None:
        """Renew access token using stored email/password (preferred) or refresh."""
        from . import portal_auth

        self._raise_if_cognito_rate_limited()

        if not self._password and not self._refresh_credential:
            raise PGEAuthenticationError("No stored password or refresh credential — update PGE credentials")

        _LOGGER.info(
            "Renewing PGE bearer token (password=%s refresh=%s)",
            bool(self._password),
            bool(self._refresh_credential),
        )
        try:
            result = await portal_auth.async_login_or_refresh(
                email=self._email or "",
                password=self._password,
                refresh_credential=self._refresh_credential,
            )
        except PGERateLimitError as exc:
            self.mark_cognito_rate_limited(exc.retry_after)
            raise

        self._token = PGEToken(
            access_token=result.access_token,
            expires_at=result.expires_at,
        )
        if result.encrypted_person_id:
            self._encrypted_person_id = result.encrypted_person_id
        if result.refresh_credential:
            self._refresh_credential = result.refresh_credential
