from __future__ import annotations

import asyncio
import logging
import re
import zoneinfo
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from typing import Any

import aiohttp

from .auth import PGEAuthManager
from .exceptions import (
    PGEAuthenticationError,
    PGEAuthorizationError,
    PGEConnectionError,
    PGEGraphQLError,
    PGERateLimitError,
    PGESchemaError,
)
from .models import (
    UsageInterval,
    UsageResolution,
    UsageResponse,
)

_LOGGER = logging.getLogger(__name__)

GRAPHQL_URL = "https://apix.portlandgeneral.com/pge-graphql"
OPERATION_NAME = "GetUsageCompare"
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)
MAX_RETRIES = 3

_LIST_FIELD_BY_MODE = {
    UsageResolution.HOURLY: "hourlyUsageList",
    UsageResolution.DAILY: "dailyUsageList",
    UsageResolution.MONTHLY: "monthlyUsageList",
}

_HOURLY_TS_RE = re.compile(r"(\d{2})-(\w{3})-(\d{4})\s+(\d{2}):(\d{2}):(\d{2})")
_MONTH_ABBREV = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}
_PGE_TZ = zoneinfo.ZoneInfo("America/Los_Angeles")


def _parse_hourly_timestamp(value: str) -> datetime:
    match = _HOURLY_TS_RE.match(value)
    if not match:
        raise PGESchemaError(f"Unrecognized hourly timestamp: {value}")
    day, mon, year, hour, minute, sec = match.groups()
    month = _MONTH_ABBREV.get(mon.upper())
    if month is None:
        raise PGESchemaError(f"Unknown month abbreviation: {mon}")
    local_dt = datetime(int(year), month, int(day), int(hour), int(minute), int(sec), tzinfo=_PGE_TZ)
    return local_dt.astimezone(UTC)


def _parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    return datetime.fromisoformat(value).astimezone(UTC)


def _safe_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _parse_retry_after(value: str | None, *, default: float = 60.0, cap: float = 300.0) -> float:
    """Parse Retry-After as seconds or HTTP-date; cap delay."""
    if not value:
        return default
    try:
        delay = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            delay = max(0.0, (when.astimezone(UTC) - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError, IndexError, OverflowError):
            return default
    return min(cap, max(0.0, delay))


def _sanitize_error_text(text: str, *, limit: int = 200) -> str:
    """Strip likely account/person identifiers before logging."""
    cleaned = re.sub(r"\b\d{8,12}\b", "[id]", text)
    cleaned = re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[jwt]", cleaned)
    return cleaned[:limit]


def _parse_interval(
    raw: dict[str, Any],
    resolution: UsageResolution,
    account_key: str,
) -> UsageInterval:
    kwh = _safe_decimal(raw.get("kwh"))
    if kwh is None:
        raise PGESchemaError("Interval missing kwh")

    if resolution == UsageResolution.HOURLY:
        interval_time = raw.get("intervalTime")
        if not interval_time:
            raise PGESchemaError("Hourly interval missing intervalTime")
        start = _parse_hourly_timestamp(interval_time)
        end = start + timedelta(hours=1)
    else:
        start = _parse_iso_timestamp(raw.get("startDate"))
        end = _parse_iso_timestamp(raw.get("endDate"))
        if start is None or end is None:
            raise PGESchemaError("Daily/monthly interval missing startDate/endDate")

    return UsageInterval(
        account_key=account_key,
        resolution=resolution,
        start=start,
        end=end,
        kwh=kwh,
        amount=_safe_decimal(raw.get("amount")),
        temperature=_safe_decimal(raw.get("temperature")),
        usage_status=raw.get("usageStatus"),
        interval_size=raw.get("intervalSize"),
        source_timestamp=None,
    )


def _classify_graphql_errors(errors: list[dict[str, Any]]) -> None:
    messages = " | ".join(str(e.get("message", e)) for e in errors)
    joined = messages.lower()
    if any(x in joined for x in ("unauthoriz", "unauthenticated", "token", "auth")):
        raise PGEAuthenticationError(f"GraphQL auth error: {messages}")
    if any(x in joined for x in ("forbidden", "not allowed", "access denied")):
        raise PGEAuthorizationError(f"GraphQL authorization error: {messages}")
    raise PGEGraphQLError(f"GraphQL errors: {messages}", errors)


def _parse_usage_response(
    data: dict[str, Any],
    resolution: UsageResolution,
    account_key: str,
) -> UsageResponse:
    if data.get("errors"):
        _classify_graphql_errors(list(data["errors"]))

    get_usage = (data.get("data") or {}).get("getUsageCompare")
    if get_usage is None:
        raise PGESchemaError("Response missing data.getUsageCompare")

    list_field = _LIST_FIELD_BY_MODE[resolution]
    raw_list = get_usage.get(list_field)
    if raw_list is None:
        raise PGESchemaError(f"Response missing {list_field}")

    intervals: list[UsageInterval] = []
    for raw in raw_list:
        intervals.append(_parse_interval(raw, resolution, account_key))

    return UsageResponse(
        resolution=resolution,
        intervals=intervals,
        total_kwh=_safe_decimal(get_usage.get("totalKwhUsage")),
        total_cost=_safe_decimal(get_usage.get("totalKwhCost")),
        is_tod=get_usage.get("isCustomerEnrolledInTOD"),
        acct_type=get_usage.get("acctType"),
    )


def _build_query(list_field: str) -> str:
    return (
        "query GetUsageCompare($params: GetUsageCompareParams!) {"
        "  getUsageCompare(params: $params) {"
        "    isCustomerEnrolledInTOD"
        "    acctType"
        "    totalKwhUsage"
        "    totalKwhCost"
        f"    {list_field} {{"
        "      efficientSimilarHomesKwh"
        "      intervalTime"
        "      kwh"
        "      intervalSize"
        "      usageStatus"
        "      rank"
        "      similarHomesKwh"
        "      amount"
        "      startDate"
        "      endDate"
        "      temperature"
        "    }"
        "  }"
        "}"
    )


class PGEApiClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: str | PGEAuthManager | None = None,
        encrypted_person_id: str | None = None,
        account_id: str | None = None,
        *,
        auth_manager: PGEAuthManager | None = None,
    ) -> None:
        self._session = session
        # Prefer explicit auth_manager; allow passing manager as second positional.
        if auth_manager is not None:
            self._auth_manager = auth_manager
            self._legacy_token = None
            self._legacy_person_id = None
            self._legacy_account_id = None
        elif isinstance(token, str) or token is None:
            self._auth_manager = None
            self._legacy_token = token
            self._legacy_person_id = encrypted_person_id
            self._legacy_account_id = account_id
        else:
            self._auth_manager = token
            self._legacy_token = None
            self._legacy_person_id = None
            self._legacy_account_id = None
        self._rate_limit_until: datetime | None = None

    def _credentials(self) -> tuple[str, str, str]:
        if self._auth_manager is not None:
            snap = self._auth_manager.snapshot()
            return snap.access_token, snap.encrypted_person_id, snap.account_id
        assert self._legacy_token and self._legacy_person_id and self._legacy_account_id
        return self._legacy_token, self._legacy_person_id, self._legacy_account_id

    @property
    def account_id(self) -> str:
        return self._credentials()[2]

    @property
    def encrypted_person_id(self) -> str:
        return self._credentials()[1]

    def update_credentials(
        self,
        token: str,
        encrypted_person_id: str | None = None,
        account_id: str | None = None,
    ) -> None:
        if self._auth_manager is not None:
            self._auth_manager.update_token(token)
            self._auth_manager.update_identity(
                encrypted_person_id=encrypted_person_id,
                account_id=account_id,
            )
            return
        self._legacy_token = token
        if encrypted_person_id is not None:
            self._legacy_person_id = encrypted_person_id
        if account_id is not None:
            self._legacy_account_id = account_id

    async def get_usage(
        self,
        resolution: UsageResolution,
        start: datetime,
        end: datetime,
        account_key: str,
    ) -> UsageResponse:
        if self._rate_limit_until and datetime.now(UTC) < self._rate_limit_until:
            raise PGERateLimitError(f"Rate limited until {self._rate_limit_until.isoformat()}")

        list_field = _LIST_FIELD_BY_MODE[resolution]
        query = _build_query(list_field)
        token, person_id, account_id = self._credentials()

        payload = {
            "query": query,
            "variables": {
                "params": {
                    "startDate": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "endDate": end.strftime("%Y-%m-%dT%H:%M:%S.999Z"),
                    "displayMode": resolution.value,
                    "accountId": account_id,
                    "encryptedPersonId": person_id,
                }
            },
            "operationName": OPERATION_NAME,
        }

        headers = {
            "accept": "*/*",
            "authorization": f"Bearer {token}",
            "aws_graphql_server": "graphql_server",
            "content-type": "application/json",
            "origin": "https://widget.portlandgeneral.com",
            "referer": "https://widget.portlandgeneral.com/",
        }

        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with self._session.post(
                    GRAPHQL_URL,
                    json=payload,
                    headers=headers,
                    timeout=DEFAULT_TIMEOUT,
                ) as resp:
                    if resp.status == 401:
                        raise PGEAuthenticationError("Token expired or invalid")
                    if resp.status == 403:
                        raise PGEAuthorizationError("Access forbidden")
                    if resp.status == 429:
                        delay = _parse_retry_after(resp.headers.get("Retry-After"))
                        self._rate_limit_until = datetime.now(UTC) + timedelta(seconds=delay)
                        raise PGERateLimitError(f"Rate limited, retry after {delay}s")
                    if resp.status in (502, 503, 504):
                        if attempt < MAX_RETRIES:
                            await asyncio.sleep(2**attempt)
                            continue
                        raise PGEConnectionError(f"HTTP {resp.status} after {MAX_RETRIES} attempts")
                    if resp.status != 200:
                        body = await resp.text()
                        raise PGEConnectionError(f"HTTP {resp.status}: {_sanitize_error_text(body)}")

                    data = await resp.json()

            except (TimeoutError, aiohttp.ClientError) as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(2**attempt)
                    continue
                raise PGEConnectionError(f"Connection failed: {exc}") from exc
            else:
                return _parse_usage_response(data, resolution, account_key)

        raise PGEConnectionError(f"Request failed after {MAX_RETRIES} attempts: {last_exc}")

    async def get_monthly_usage_paged(
        self,
        start: datetime,
        end: datetime,
        account_key: str,
        *,
        max_pages: int = 24,
    ) -> UsageResponse:
        """Fetch MONTHLY billing periods, paging backwards past the latest ~12.

        Live MONTHLY responses return only the newest ~12 billing cycles
        regardless of the requested range. Walk the window backwards from
        ``end`` until periods covering ``start`` are collected (or a page
        returns no new rows).
        """
        by_start: dict[datetime, UsageInterval] = {}
        page_end = end
        last_response: UsageResponse | None = None
        for _ in range(max_pages):
            page_start = page_end - timedelta(days=400)
            response = await self.get_usage(
                UsageResolution.MONTHLY,
                page_start,
                page_end,
                account_key,
            )
            last_response = response
            if not response.intervals:
                break
            new_count = 0
            for iv in response.intervals:
                if iv.start not in by_start:
                    by_start[iv.start] = iv
                    new_count += 1
            oldest = min(by_start)
            if oldest <= start or new_count == 0:
                break
            page_end = oldest - timedelta(milliseconds=1)

        intervals = sorted(by_start.values(), key=lambda iv: iv.start)
        in_range = [iv for iv in intervals if iv.end > start and iv.start < end]
        if last_response is None:
            return UsageResponse(
                resolution=UsageResolution.MONTHLY,
                intervals=[],
                total_kwh=None,
                total_cost=None,
                is_tod=None,
                acct_type=None,
            )
        return UsageResponse(
            resolution=UsageResolution.MONTHLY,
            intervals=in_range,
            total_kwh=None,  # MONTHLY response totals are unreliable / null
            total_cost=None,
            is_tod=last_response.is_tod,
            acct_type=last_response.acct_type,
        )
