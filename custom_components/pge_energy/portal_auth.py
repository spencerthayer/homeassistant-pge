"""PGE portal email/password authentication (Cognito + Apigee hybrid).

Protocol derived from public portal assets and capped live capture.
Do not invent request fields beyond that discovery.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import aiohttp

from .billing_api import GET_ACCOUNT_DETAIL_LIST, account_detail_list_params
from .const import (
    COGNITO_RATE_LIMIT_DEFAULT_SECONDS,
    COGNITO_RATE_LIMIT_LOCKOUT_SECONDS,
)
from .exceptions import (
    PGEAuthenticationError,
    PGECaptchaUnsupportedError,
    PGEConnectionError,
    PGEMfaUnsupportedError,
    PGERateLimitError,
)

_LOGGER = logging.getLogger(__name__)

# Observed production config from portlandgeneral.com app.js (2026-07-23).
COGNITO_REGION = "us-west-2"
COGNITO_CLIENT_ID = "4q9nbgmi0gcks5t7d6fkhubfnm"
COGNITO_USER_POOL_ID = "us-west-2_rnEzd20tN"
COGNITO_URL = f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/"
COGNITO_AUTH_FLOW = "USER_PASSWORD_AUTH"
COGNITO_REFRESH_FLOW = "REFRESH_TOKEN_AUTH"

APIGEE_AUTH_BASE = "https://apix.portlandgeneral.com"
APIGEE_CLIENT_ID = "rHuS10KrfsLwFAr2sZ7MHh7oHELGx6YK"
APIGEE_TOKEN_PATH = "/pg-token-implicit-aws/token"

GRAPHQL_URL = "https://apix.portlandgeneral.com/pge-graphql"

# Cap password InitiateAuth calls to avoid account lockout.
MAX_LOGIN_ATTEMPTS = 2

# Observed Cognito challenge names that mean MFA (fail closed).
_MFA_CHALLENGE_NAMES = frozenset(
    {
        "SMS_MFA",
        "SOFTWARE_TOKEN_MFA",
        "SELECT_MFA_TYPE",
        "MFA_SETUP",
    }
)

_GET_ACCOUNT_INFO = """
query getAccountInfo($params: GetAccountInfoParams) {
  getAccountInfo(params: $params) {
    encryptedPersonId
    accountMeta {
      totalAccounts
      hasInactiveAccounts
    }
    groups {
      groupId
      numberOfAccounts
      isDefault
      defaultAccount {
        accountNumber
        encryptedAccountNumber
        encryptedPersonId
      }
    }
  }
}
"""


@dataclass(frozen=True, slots=True)
class PortalAuthResult:
    access_token: str
    encrypted_person_id: str | None
    account_ids: list[str]
    expires_at: datetime | None
    refresh_credential: str | None


def classify_challenge(payload: dict[str, Any]) -> None:
    """Fail-closed challenge detection from observed + generic signals.

    Observed portal/Cognito signals:
    - ChallengeName in {SMS_MFA, SOFTWARE_TOKEN_MFA, SELECT_MFA_TYPE, MFA_SETUP}
    - status == MFA_REQUIRED (Amplify adapter return shape)

    Also keeps the generic key-name heuristic for boolean-ish flags.
    """
    challenge_name = payload.get("ChallengeName") or payload.get("challengeName")
    if isinstance(challenge_name, str) and challenge_name in _MFA_CHALLENGE_NAMES:
        raise PGEMfaUnsupportedError("PGE account requires MFA; this integration does not support MFA")

    status = payload.get("status")
    if status == "MFA_REQUIRED":
        raise PGEMfaUnsupportedError("PGE account requires MFA; this integration does not support MFA")

    for key, value in payload.items():
        key_l = str(key).lower()
        truthy = value in (True, "true", 1, "1", "yes")
        if not truthy:
            continue
        if any(token in key_l for token in ("mfa", "otp", "twofactor", "2fa")):
            raise PGEMfaUnsupportedError("PGE account requires MFA; this integration does not support MFA")
        if any(token in key_l for token in ("captcha", "recaptcha")):
            raise PGECaptchaUnsupportedError("PGE login requires CAPTCHA/device challenge; unsupported")


def _cognito_headers(target: str) -> dict[str, str]:
    return {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": target,
    }


def _apigee_token_url() -> str:
    qs = urlencode(
        {
            "client_id": APIGEE_CLIENT_ID,
            "response_type": "token",
            "redirect_uri": "",
        }
    )
    return f"{APIGEE_AUTH_BASE}{APIGEE_TOKEN_PATH}?{qs}"


def _parse_expires_at(raw: Any) -> datetime | None:
    if raw is None:
        return None
    try:
        # Observed Apigee field expires_at is unix seconds.
        return datetime.fromtimestamp(int(raw), tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _classify_cognito_error(payload: dict[str, Any]) -> None:
    """Map observed Cognito error/challenge payloads to typed exceptions."""
    classify_challenge(payload)

    err_type = str(payload.get("__type") or payload.get("code") or "")
    message = str(payload.get("message") or payload.get("Message") or "")
    combined = f"{err_type} {message}".lower()

    if "captcha" in combined or "recaptcha" in combined:
        raise PGECaptchaUnsupportedError("PGE login requires CAPTCHA/device challenge; unsupported")
    if "passwordresetrequired" in combined:
        raise PGEAuthenticationError("PGE password reset required")
    if "userlambda" in combined and "lock" in combined:
        raise PGEAuthenticationError("PGE account appears locked")
    # Must run before NotAuthorizedException — lockout uses that __type with this message.
    if "password attempts exceeded" in combined:
        raise PGERateLimitError(
            "PGE identity provider locked password attempts",
            retry_after=COGNITO_RATE_LIMIT_LOCKOUT_SECONDS,
        )
    if "toomanyrequests" in combined or "limitexceeded" in combined:
        raise PGERateLimitError(
            "PGE identity provider rate-limited the login",
            retry_after=COGNITO_RATE_LIMIT_DEFAULT_SECONDS,
        )
    if "notauthorized" in combined or "usernotfound" in combined:
        raise PGEAuthenticationError("PGE login rejected (incorrect username or password)")


async def _post_json(
    session: aiohttp.ClientSession,
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any] | None,
) -> tuple[int, dict[str, Any]]:
    try:
        request_kwargs: dict[str, Any] = {"headers": headers}
        if body is not None:
            request_kwargs["json"] = body
        async with session.post(url, **request_kwargs) as resp:
            try:
                payload = await resp.json(content_type=None)
            except Exception as exc:  # noqa: BLE001
                await resp.text()
                raise PGEConnectionError(f"Non-JSON auth response ({resp.status})") from exc
            if not isinstance(payload, dict):
                raise PGEConnectionError(f"Unexpected auth JSON type ({type(payload).__name__})")
            return resp.status, payload
    except TimeoutError as exc:
        raise PGEConnectionError("PGE auth request timed out") from exc
    except aiohttp.ClientError as exc:
        raise PGEConnectionError(f"PGE auth connection error: {exc}") from exc


async def _cognito_initiate_auth(
    session: aiohttp.ClientSession,
    *,
    auth_flow: str,
    auth_parameters: dict[str, str],
) -> dict[str, Any]:
    status, payload = await _post_json(
        session,
        COGNITO_URL,
        headers=_cognito_headers("AWSCognitoIdentityProviderService.InitiateAuth"),
        body={
            "AuthFlow": auth_flow,
            "ClientId": COGNITO_CLIENT_ID,
            "AuthParameters": auth_parameters,
        },
    )
    classify_challenge(payload)
    if "AuthenticationResult" in payload:
        return payload["AuthenticationResult"]
    if status >= 400 or "__type" in payload or "ChallengeName" in payload:
        _classify_cognito_error(payload)
        challenge = payload.get("ChallengeName")
        if challenge == "NEW_PASSWORD_REQUIRED":
            raise PGEAuthenticationError("PGE login requires a new password (unsupported)")
        raise PGEAuthenticationError(f"PGE Cognito login failed (HTTP {status})")
    raise PGEAuthenticationError("PGE Cognito login returned no AuthenticationResult")


async def _apigee_exchange_id_token(
    session: aiohttp.ClientSession,
    id_token: str,
) -> tuple[str, datetime | None]:
    status, payload = await _post_json(
        session,
        _apigee_token_url(),
        headers={"idp_access_token": id_token},
        body=None,
    )
    classify_challenge(payload)
    token = payload.get("access_token")
    if status >= 400 or not isinstance(token, str) or not token:
        raise PGEAuthenticationError(f"PGE Apigee token exchange failed (HTTP {status})")
    return token, _parse_expires_at(payload.get("expires_at"))


def _account_number_last4(value: str) -> str:
    """Sanitized account fingerprint for diagnostics (never log full numbers)."""
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if not digits:
        return "????"
    if len(digits) <= 4:
        return digits
    return digits[-4:]


def _merge_account_ids(*groups: list[str]) -> list[str]:
    """Union account numbers in encounter order (exact-string dedupe)."""
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for acct in group:
            if not isinstance(acct, str) or not acct or acct in seen:
                continue
            seen.add(acct)
            merged.append(acct)
    return merged


def _extract_accounts(account_info: dict[str, Any]) -> tuple[str | None, list[str]]:
    """Collect defaultAccount numbers from getAccountInfo groups.

    ``getAccountInfo`` only returns each group's defaultAccount — non-default
    accounts on the same login are invisible here (see getAccountDetailList).
    """
    person = account_info.get("encryptedPersonId")
    person_id = person if isinstance(person, str) and person else None
    account_ids: list[str] = []
    groups = account_info.get("groups") or []
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, dict):
                continue
            default = group.get("defaultAccount") or {}
            if not isinstance(default, dict):
                continue
            acct = default.get("accountNumber")
            if isinstance(acct, str) and acct and acct not in account_ids:
                account_ids.append(acct)
            enc_person = default.get("encryptedPersonId")
            if person_id is None and isinstance(enc_person, str) and enc_person:
                person_id = enc_person
    return person_id, account_ids


def _extract_detail_list_accounts(detail_list: dict[str, Any]) -> tuple[str | None, list[str]]:
    """Collect accountNumber values from getAccountDetailList.accounts[]."""
    person_id: str | None = None
    account_ids: list[str] = []
    accounts = detail_list.get("accounts") or []
    if not isinstance(accounts, list):
        return person_id, account_ids
    for row in accounts:
        if not isinstance(row, dict):
            continue
        acct = row.get("accountNumber")
        if isinstance(acct, str) and acct and acct not in account_ids:
            account_ids.append(acct)
        enc_person = row.get("encryptedPersonId")
        if person_id is None and isinstance(enc_person, str) and enc_person:
            person_id = enc_person
    return person_id, account_ids


def _log_discovery_summary(
    *,
    account_meta: dict[str, Any] | None,
    groups: list[Any] | None,
    default_ids: list[str],
    detail_ids: list[str] | None,
    merged_ids: list[str],
    detail_error: str | None,
) -> None:
    """Bounded sanitized discovery diagnostics (last-4 only; no ciphertexts)."""
    meta = account_meta if isinstance(account_meta, dict) else {}
    group_rows = groups if isinstance(groups, list) else []
    group_summaries: list[str] = []
    for group in group_rows:
        if not isinstance(group, dict):
            continue
        n_declared = group.get("numberOfAccounts")
        default = group.get("defaultAccount") if isinstance(group.get("defaultAccount"), dict) else {}
        default_acct = default.get("accountNumber") if isinstance(default, dict) else None
        last4 = _account_number_last4(default_acct) if isinstance(default_acct, str) else "none"
        group_summaries.append(f"declared={n_declared!r}/default_last4={last4}")
    if detail_ids is not None:
        detail_last4 = [_account_number_last4(a) for a in detail_ids]
        detail_part = f"detail_count={len(detail_ids)} last4={detail_last4}"
    else:
        detail_part = f"detail_soft_fail={detail_error or 'unknown'}"
    _LOGGER.debug(
        "PGE account discovery: totalAccounts=%r hasInactive=%r groups=%s defaults=%s %s merged=%s last4=%s",
        meta.get("totalAccounts"),
        meta.get("hasInactiveAccounts"),
        group_summaries or "[]",
        len(default_ids),
        detail_part,
        len(merged_ids),
        [_account_number_last4(a) for a in merged_ids],
    )


async def _enumerate_accounts_via_detail_list(
    session: aiohttp.ClientSession,
    access_token: str,
    *,
    headers: dict[str, str],
) -> tuple[str | None, list[str]]:
    """Enumerate ACTIVE accounts via the portal account-switcher op."""
    body = {
        "operationName": "getAccountDetailList",
        "query": GET_ACCOUNT_DETAIL_LIST,
        "variables": {"params": account_detail_list_params()},
    }
    status, payload = await _post_json(session, GRAPHQL_URL, headers=headers, body=body)
    classify_challenge(payload)
    if status >= 400:
        raise PGEAuthenticationError(f"PGE account detail list failed (HTTP {status})")
    if payload.get("errors"):
        raise PGEAuthenticationError("PGE account detail list GraphQL errors")
    detail = (payload.get("data") or {}).get("getAccountDetailList")
    if not isinstance(detail, dict):
        raise PGEAuthenticationError("PGE account detail list returned no getAccountDetailList")
    return _extract_detail_list_accounts(detail)


async def _discover_accounts(
    session: aiohttp.ClientSession,
    access_token: str,
) -> tuple[str | None, list[str]]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "aws_graphql_server": "graphql_server",
        "Content-Type": "application/json",
        "Origin": "https://portlandgeneral.com",
        "Referer": "https://portlandgeneral.com/",
    }
    # Observed operation accepts GetAccountInfoParams; null params used by portal variants.
    body = {
        "operationName": "getAccountInfo",
        "query": _GET_ACCOUNT_INFO,
        "variables": {"params": None},
    }
    status, payload = await _post_json(session, GRAPHQL_URL, headers=headers, body=body)
    classify_challenge(payload)
    if status >= 400:
        raise PGEAuthenticationError(f"PGE account discovery failed (HTTP {status})")
    if payload.get("errors"):
        raise PGEAuthenticationError("PGE account discovery GraphQL errors")
    info = (payload.get("data") or {}).get("getAccountInfo")
    if not isinstance(info, dict):
        raise PGEAuthenticationError("PGE account discovery returned no getAccountInfo")
    person_id, default_ids = _extract_accounts(info)

    detail_ids: list[str] | None = None
    detail_error: str | None = None
    try:
        detail_person, detail_ids = await _enumerate_accounts_via_detail_list(session, access_token, headers=headers)
        if person_id is None and detail_person:
            person_id = detail_person
    except Exception as exc:  # noqa: BLE001 - soft-fail; never regress single-account login
        detail_error = type(exc).__name__
        _LOGGER.debug(
            "PGE getAccountDetailList enumeration soft-failed; using getAccountInfo defaults only",
            exc_info=True,
        )

    merged = _merge_account_ids(default_ids, detail_ids or [])
    _log_discovery_summary(
        account_meta=info.get("accountMeta") if isinstance(info.get("accountMeta"), dict) else None,
        groups=info.get("groups") if isinstance(info.get("groups"), list) else None,
        default_ids=default_ids,
        detail_ids=detail_ids,
        merged_ids=merged,
        detail_error=detail_error,
    )
    return person_id, merged


async def _login_with_password(
    session: aiohttp.ClientSession,
    *,
    email: str,
    password: str,
) -> PortalAuthResult:
    auth_result: dict[str, Any] | None = None
    last_connection_error: Exception | None = None
    for attempt in range(1, MAX_LOGIN_ATTEMPTS + 1):
        try:
            auth_result = await _cognito_initiate_auth(
                session,
                auth_flow=COGNITO_AUTH_FLOW,
                auth_parameters={
                    "USERNAME": email,
                    "PASSWORD": password,
                },
            )
            break
        except (PGEMfaUnsupportedError, PGECaptchaUnsupportedError, PGERateLimitError):
            # Stop immediately — never retry challenges or Cognito throttle/lockout.
            raise
        except PGEAuthenticationError:
            # Credential reject / lock / reset: do not burn further attempts.
            _LOGGER.warning("PGE Cognito password login rejected on attempt %s", attempt)
            raise
        except PGEConnectionError as exc:
            last_connection_error = exc
            _LOGGER.warning("PGE Cognito connection error on attempt %s", attempt)
            if attempt >= MAX_LOGIN_ATTEMPTS:
                raise
            await asyncio.sleep(1)
    if auth_result is None:
        raise last_connection_error or PGEAuthenticationError("PGE login failed")

    id_token = auth_result.get("IdToken")
    refresh_token = auth_result.get("RefreshToken")
    if not isinstance(id_token, str) or not id_token:
        raise PGEAuthenticationError("PGE Cognito response missing IdToken")

    access_token, expires_at = await _apigee_exchange_id_token(session, id_token)
    person_id, account_ids = await _discover_accounts(session, access_token)
    return PortalAuthResult(
        access_token=access_token,
        encrypted_person_id=person_id,
        account_ids=account_ids,
        expires_at=expires_at,
        refresh_credential=refresh_token if isinstance(refresh_token, str) else None,
    )


async def _refresh_with_cognito_token(
    session: aiohttp.ClientSession,
    *,
    refresh_credential: str,
) -> PortalAuthResult:
    auth_result = await _cognito_initiate_auth(
        session,
        auth_flow=COGNITO_REFRESH_FLOW,
        auth_parameters={"REFRESH_TOKEN": refresh_credential},
    )
    id_token = auth_result.get("IdToken")
    if not isinstance(id_token, str) or not id_token:
        raise PGEAuthenticationError("PGE Cognito refresh missing IdToken")
    # RefreshToken is often omitted on REFRESH_TOKEN_AUTH; keep the prior credential.
    new_refresh = auth_result.get("RefreshToken")
    access_token, expires_at = await _apigee_exchange_id_token(session, id_token)
    person_id, account_ids = await _discover_accounts(session, access_token)
    return PortalAuthResult(
        access_token=access_token,
        encrypted_person_id=person_id,
        account_ids=account_ids,
        expires_at=expires_at,
        refresh_credential=new_refresh if isinstance(new_refresh, str) else refresh_credential,
    )


async def async_login_or_refresh(
    *,
    email: str,
    password: str | None,
    refresh_credential: str | None,
) -> PortalAuthResult:
    """Obtain a fresh Apigee bearer token.

    PGE bearer tokens are short-lived. Prefer email/password login whenever a
    password is available (typical path for each sync). Fall back to Cognito
    refresh only when password is missing or password login fails with a
    recoverable auth error. MFA/CAPTCHA fail closed.
    """
    if not email:
        raise PGEAuthenticationError("Email is required for PGE credential auth")

    timeout = aiohttp.ClientTimeout(total=45)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        if password:
            try:
                return await _login_with_password(session, email=email, password=password)
            except (PGEMfaUnsupportedError, PGECaptchaUnsupportedError, PGERateLimitError):
                # Never amplify Cognito throttle/lockout with a second InitiateAuth.
                raise
            except PGEAuthenticationError:
                if not refresh_credential:
                    raise
                _LOGGER.info("PGE password login failed; falling back to refresh credential")

        if refresh_credential:
            return await _refresh_with_cognito_token(session, refresh_credential=refresh_credential)

        raise PGEAuthenticationError("Password or refresh credential required for PGE login")
