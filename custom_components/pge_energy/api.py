from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import zoneinfo
from collections import Counter
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
ALPHA_CAPTURE_PREFIX = "PGE_ALPHA_GRID_CAPTURE"
_CAPTURE_MAX_RESPONSES = 20
_CAPTURE_MAX_ROWS = 40
_CAPTURE_SCALAR_LIMIT = 120
_CAPTURE_MAX_INTROSPECTION_TYPES = 30
_CAPTURE_MAX_INTROSPECTION_FIELDS = 40
_CAPTURE_ROW_FIELDS = (
    "intervalTime",
    "startDate",
    "endDate",
    "kwh",
    "amount",
    "usageStatus",
    "intervalSize",
    "temperature",
)
_DIRECTION_FIELD_RE = re.compile(
    r"(?:receiv|return|export|generat|produc|deliver|import|solar|bidirect|netmeter|netenergy|netusage|netkwh|^net$)",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_LONG_ID_RE = re.compile(r"\b\d{8,12}\b")
_INTROSPECTION_TIMEOUT = aiohttp.ClientTimeout(total=10)
_INTROSPECTION_QUERY = """
query PGEAlphaGridIntrospection {
  __schema {
    queryType {
      fields {
        name
        args { name type { kind name ofType { kind name ofType { kind name ofType { kind name } } } } }
        type { kind name ofType { kind name ofType { kind name ofType { kind name } } } }
      }
    }
    types {
      kind
      name
      fields { name }
      inputFields { name }
    }
  }
}
"""

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
    cleaned = _LONG_ID_RE.sub("[id]", text)
    cleaned = _JWT_RE.sub("[jwt]", cleaned)
    cleaned = _EMAIL_RE.sub("[email]", cleaned)
    return cleaned[:limit]


def _sanitize_capture_scalar(value: Any) -> str | int | float | bool | None:
    """Return one bounded scalar suitable for the opt-in usage capture log."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        text = str(value)
        return value if len(text) <= _CAPTURE_SCALAR_LIMIT else text[:_CAPTURE_SCALAR_LIMIT]
    if not isinstance(value, str):
        return "[unsupported]"
    cleaned = _JWT_RE.sub("[jwt]", value)
    cleaned = _EMAIL_RE.sub("[email]", cleaned)
    cleaned = _LONG_ID_RE.sub("[id]", cleaned)
    return cleaned[:_CAPTURE_SCALAR_LIMIT]


def _capture_rows(data: dict[str, Any], list_field: str) -> list[dict[str, Any]]:
    """Project the response to the allowlisted usage fields only."""
    get_usage = (data.get("data") or {}).get("getUsageCompare") or {}
    raw_rows = get_usage.get(list_field) or []
    if not isinstance(raw_rows, list):
        return []
    rows: list[dict[str, Any]] = []
    for raw in raw_rows[:_CAPTURE_MAX_ROWS]:
        if not isinstance(raw, dict):
            continue
        rows.append({field: _sanitize_capture_scalar(raw.get(field)) for field in _CAPTURE_ROW_FIELDS})
    return rows


def _type_ref_name(type_ref: Any) -> str | None:
    """Return the innermost named GraphQL type from an introspection type ref."""
    current = type_ref
    while isinstance(current, dict):
        name = current.get("name")
        if isinstance(name, str) and name:
            return name
        current = current.get("ofType")
    return None


def _introspection_summary(data: dict[str, Any]) -> dict[str, Any]:
    """Reduce an introspection response to bounded field-name evidence."""
    schema = (data.get("data") or {}).get("__schema") or {}
    root_fields = ((schema.get("queryType") or {}).get("fields")) or []
    root_matches: list[dict[str, Any]] = []
    usage_contract_types: set[str] = set()
    for field in root_fields:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or "")
        if name == "getUsageCompare" or _DIRECTION_FIELD_RE.search(name):
            return_type = _type_ref_name(field.get("type"))
            if return_type:
                usage_contract_types.add(return_type)
            for arg in field.get("args") or []:
                if isinstance(arg, dict) and (arg_type := _type_ref_name(arg.get("type"))):
                    usage_contract_types.add(arg_type)
            root_matches.append(
                {
                    "name": name[:100],
                    "args": [
                        {
                            "name": str(arg.get("name") or "")[:100],
                            "type": _type_ref_name(arg.get("type")),
                        }
                        for arg in (field.get("args") or [])[:_CAPTURE_MAX_INTROSPECTION_FIELDS]
                        if isinstance(arg, dict)
                    ],
                    "return_type": return_type,
                }
            )

    type_matches: list[dict[str, Any]] = []
    for graph_type in schema.get("types") or []:
        if not isinstance(graph_type, dict):
            continue
        type_name = str(graph_type.get("name") or "")
        field_names = [
            str(field.get("name") or "")[:100] for field in (graph_type.get("fields") or []) if isinstance(field, dict)
        ]
        input_names = [
            str(field.get("name") or "")[:100]
            for field in (graph_type.get("inputFields") or [])
            if isinstance(field, dict)
        ]
        matching_fields = [name for name in field_names if _DIRECTION_FIELD_RE.search(name)]
        matching_inputs = [name for name in input_names if _DIRECTION_FIELD_RE.search(name)]
        include_all = (
            type_name == "GetUsageCompareParams" or type_name in usage_contract_types or "UsageCompare" in type_name
        )
        if include_all or matching_fields or matching_inputs:
            type_matches.append(
                {
                    "name": type_name[:100],
                    "kind": str(graph_type.get("kind") or "")[:30],
                    "fields": (field_names if include_all else matching_fields)[:_CAPTURE_MAX_INTROSPECTION_FIELDS],
                    "input_fields": (input_names if include_all else matching_inputs)[
                        :_CAPTURE_MAX_INTROSPECTION_FIELDS
                    ],
                }
            )
        if len(type_matches) >= _CAPTURE_MAX_INTROSPECTION_TYPES:
            break
    return {
        "query_fields": root_matches[:_CAPTURE_MAX_INTROSPECTION_FIELDS],
        "types": type_matches,
    }


def _parse_interval(
    raw: dict[str, Any],
    resolution: UsageResolution,
    account_key: str,
) -> UsageInterval:
    # Explicit null kWh is a valid unavailable sample (keep the timestamp).
    # Non-null unparsable values remain a schema error.
    raw_kwh = raw.get("kwh")
    if raw_kwh is None:
        kwh: Decimal | None = None
    else:
        kwh = _safe_decimal(raw_kwh)
        if kwh is None:
            raise PGESchemaError("Interval kwh must be numeric")

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
        capture_graphql_diagnostics: bool = False,
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
        self._capture_graphql_diagnostics = capture_graphql_diagnostics
        self._captured_requests: set[tuple[UsageResolution, str, str]] = set()
        self._captured_response_count = 0
        self._capture_limit_logged = False
        self._introspection_attempted = False
        self._capture_source = "unknown"

    @property
    def introspection_attempted(self) -> bool:
        """Whether this client attempted the opt-in schema discovery request."""
        return self._introspection_attempted

    @property
    def captured_response_count(self) -> int:
        """Number of bounded usage responses emitted to the opt-in log."""
        return self._captured_response_count

    def _log_usage_capture(
        self,
        data: dict[str, Any],
        resolution: UsageResolution,
        list_field: str,
        start: datetime,
        end: datetime,
        account_key: str,
    ) -> None:
        """Log bounded, allowlisted rows and direction clues for one unique request."""
        self._capture_source = hashlib.sha256(account_key.encode()).hexdigest()[:8]
        request_key = (resolution, start.isoformat(), end.isoformat())
        if request_key in self._captured_requests:
            return
        if self._captured_response_count >= _CAPTURE_MAX_RESPONSES:
            if not self._capture_limit_logged:
                _LOGGER.info(
                    "%s source=%s response_limit_reached limit=%s",
                    ALPHA_CAPTURE_PREFIX,
                    self._capture_source,
                    _CAPTURE_MAX_RESPONSES,
                )
                self._capture_limit_logged = True
            return
        self._captured_requests.add(request_key)
        self._captured_response_count += 1

        get_usage = (data.get("data") or {}).get("getUsageCompare") or {}
        raw_rows = get_usage.get(list_field) or []
        raw_row_count = len(raw_rows) if isinstance(raw_rows, list) else 0
        rows = _capture_rows(data, list_field)
        statuses = sorted({str(row["usageStatus"]) for row in rows if row.get("usageStatus") is not None})
        starts = [row.get("intervalTime") or row.get("startDate") for row in rows]
        start_counts = Counter(str(value) for value in starts if value)
        duplicate_starts = sorted(start for start, count in start_counts.items() if count > 1)[:20]
        negative_kwh = sum(1 for row in rows if (_safe_decimal(row.get("kwh")) or Decimal(0)) < 0)
        negative_amount = sum(1 for row in rows if (_safe_decimal(row.get("amount")) or Decimal(0)) < 0)
        summary = {
            "resolution": resolution.value,
            "start": start.astimezone(UTC).isoformat(),
            "end": end.astimezone(UTC).isoformat(),
            "row_count": raw_row_count,
            "logged_row_count": len(rows),
            "truncated": raw_row_count > len(rows),
            "usage_statuses": statuses[:30],
            "negative_kwh_count": negative_kwh,
            "negative_amount_count": negative_amount,
            "max_rows_per_start": max(start_counts.values(), default=0),
            "duplicate_starts": duplicate_starts,
        }
        _LOGGER.info(
            "%s source=%s capture=%s summary=%s",
            ALPHA_CAPTURE_PREFIX,
            self._capture_source,
            self._captured_response_count,
            json.dumps(summary, sort_keys=True, separators=(",", ":")),
        )
        for index, row in enumerate(rows):
            _LOGGER.info(
                "%s source=%s capture=%s row=%s data=%s",
                ALPHA_CAPTURE_PREFIX,
                self._capture_source,
                self._captured_response_count,
                index,
                json.dumps(row, sort_keys=True, separators=(",", ":")),
            )

    async def _async_capture_introspection(self, headers: dict[str, str]) -> None:
        """Attempt one PGE-only schema discovery request without affecting sync."""
        if self._introspection_attempted:
            return
        # Set before awaiting so concurrent backfill calls cannot duplicate the probe.
        self._introspection_attempted = True
        payload = {
            "query": _INTROSPECTION_QUERY,
            "operationName": "PGEAlphaGridIntrospection",
            "variables": {},
        }
        try:
            async with self._session.post(
                GRAPHQL_URL,
                json=payload,
                headers=headers,
                timeout=_INTROSPECTION_TIMEOUT,
                allow_redirects=False,
            ) as resp:
                if resp.status != 200:
                    _LOGGER.info(
                        "%s source=%s introspection=failed status=%s",
                        ALPHA_CAPTURE_PREFIX,
                        self._capture_source,
                        resp.status,
                    )
                    return
                data = await resp.json()
        except (TimeoutError, aiohttp.ClientError, ValueError) as exc:
            _LOGGER.info(
                "%s source=%s introspection=failed error_type=%s",
                ALPHA_CAPTURE_PREFIX,
                self._capture_source,
                type(exc).__name__,
            )
            return
        if not isinstance(data, dict):
            _LOGGER.info(
                "%s source=%s introspection=failed detail=non-object response",
                ALPHA_CAPTURE_PREFIX,
                self._capture_source,
            )
            return
        if data.get("errors"):
            errors = data["errors"]
            error_count = len(errors) if isinstance(errors, list) else 1
            _LOGGER.info(
                "%s source=%s introspection=failed graphql_error_count=%s",
                ALPHA_CAPTURE_PREFIX,
                self._capture_source,
                error_count,
            )
            return
        summary = _introspection_summary(data)
        _LOGGER.info(
            "%s source=%s introspection=success summary=%s",
            ALPHA_CAPTURE_PREFIX,
            self._capture_source,
            json.dumps(summary, sort_keys=True, separators=(",", ":")),
        )

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
                if self._capture_graphql_diagnostics and not data.get("errors"):
                    try:
                        self._log_usage_capture(data, resolution, list_field, start, end, account_key)
                    except Exception as exc:  # noqa: BLE001 - diagnostics must never fail usage sync
                        _LOGGER.info(
                            "%s source=%s processing=failed error_type=%s",
                            ALPHA_CAPTURE_PREFIX,
                            self._capture_source,
                            type(exc).__name__,
                        )
                    try:
                        await self._async_capture_introspection(headers)
                    except Exception as exc:  # noqa: BLE001 - diagnostics must never fail usage sync
                        _LOGGER.info(
                            "%s source=%s introspection=failed error_type=%s",
                            ALPHA_CAPTURE_PREFIX,
                            self._capture_source,
                            type(exc).__name__,
                        )
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
