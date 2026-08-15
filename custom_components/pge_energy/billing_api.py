from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import aiohttp

from .auth import PGEAuthManager
from .billing_models import (
    AccountSnapshot,
    BillDetails,
    EnergyTrackerEstimates,
    LedgerEvent,
    LedgerEventType,
    NetMeteringSnapshot,
    ProgramEnrollment,
    ProgramsSnapshot,
    RateCompareSnapshot,
    sanitize_rate_compare_attrs,
)
from .exceptions import (
    PGEAuthenticationError,
    PGEAuthorizationError,
    PGEConnectionError,
    PGEGraphQLError,
    PGERateLimitError,
    PGESchemaError,
)

_LOGGER = logging.getLogger(__name__)

GRAPHQL_URL = "https://apix.portlandgeneral.com/pge-graphql"
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=30)
MAX_RETRIES = 3

# Portal-style origin (account/bill/programs calls originate from the main
# portal SPA, not the usage widget).
_ORIGIN = "https://portlandgeneral.com"
_REFERER = "https://portlandgeneral.com/"

# ---------------------------------------------------------------------------
# GraphQL documents (captured from portal JS discovery). Field/param names for
# the detail-list and per-program detail ops are best-effort and flagged in the
# module docstring / task summary; parsers below tolerate missing fields.
# ---------------------------------------------------------------------------

GET_ACCOUNT_DETAIL_LIST = """
query getAccountDetailList($params: AccountDetailListParams!) {
  getAccountDetailList(params: $params) {
    totalCount
    accounts {
      accountNumber
      encryptedAccountNumber
      encryptedPersonId
      billInfo {
        amountDue
        dueDate
        lastPaymentAmount
        lastPaymentDate
        billDetails {
          amountDue
          kwh
          billDate
          dueDate
          previousBalance
          totalAdjustments
          totalCurrentCharges
          totalBalanceAfterBill
          billingPeriodStartDate
          billingPeriodEndDate
          encryptedBillId
        }
      }
      autoPay {
        isEnrolled
      }
      isPaperlessBillEnrolled {
        result
      }
      premiseInfo {
        encryptedPremiseId
        saDetails {
          encryptedSAId
        }
      }
      viewBillAverageTemperature {
        temperatureSource
        currentBillingPeriod {
          averageTemperature
          date
          totalCost
          totalKwh
        }
      }
    }
  }
}
"""

# Charge-summary returns opaque portal errors; use nested AccountDetail.paymentHistory.
# Keep this document compact — a multiline field selection has been observed to
# trip Apigee/WAF 403s even when the same fields succeed in one-line form.
GET_ACCOUNT_DETAIL_PAYMENT_HISTORY = """
query getAccountDetailList($params: AccountDetailListParams!, $php: PaymentHistoryParams) {
  getAccountDetailList(params: $params) {
    accounts {
      accountNumber
      encryptedAccountNumber
      paymentHistory(paymentHistoryParams: $php) {
        totalDetailsRecords
        paymentHistoryDetails {
          date amountPaid type amountDue kwh billingPeriodStartDate billingPeriodEndDate encryptedBillId
        }
      }
    }
  }
}
"""

# Kept as a name alias for older capture scripts / callers.
GET_VIEW_PAYMENT_HISTORY_CHARGE_SUMMARY = GET_ACCOUNT_DETAIL_PAYMENT_HISTORY

GET_ENERGY_TRACKER_DATA = """
query getEnergyTrackerData($params: EnergyTrackerDataParams) {
  getEnergyTrackerData(params: $params) {
    detailsAvailable
    hasMoreThan15DaysOfData
    details {
      billingCycleDay
      numberOfBillingDays
      billToDateAmount
      minProjectedAmount
      maxProjectedAmount
    }
    currentBillingPeriod {
      totalKwh
    }
    previousBillingPeriod {
      totalKwh
    }
  }
}
"""

GET_PROGRAMS_ENROLLMENT_STATUS_DETAILS = """
query GetProgramsEnrollmentStatusDetails($params: ProgramsEnrollmentStatusDetailsParams!) {
  getProgramsEnrollmentStatusDetails(params: $params) {
    energyShifting {
      isEligible
      isEnrolled
      programName
    }
    renewables {
      isEligible
      isEnrolled
      programName
    }
    onBillFlexLoadEarnings
    ytdFlexLoadEarnings
  }
}
"""

GET_RENEWABLES_ENROLLMENT_DETAILS = """
query getRenewablesEnrollmentDetails($params: RenewablesEnrollmentDetailsParams!) {
  getRenewablesEnrollmentDetails(params: $params) {
    greenFutureProgramDetails {
      cardType
      consumptionPercentage
      isEnrolled
      totalConsumption
    }
    habitatSupport {
      isEnrolled
    }
  }
}
"""

GET_PEAK_TIME_REBATE_ENROLLMENT_DETAILS = """
query getPeakTimeRebateEnrollmentDetails($params: PeakTimeRebateEnrollmentDetailsParams!) {
  getPeakTimeRebateEnrollmentDetails(params: $params) {
    enrollmentStatus
    cardType
    totalEarnedCredit
    activePTRSeason
    peakTimeEvents { eventDate eventEarnedCredit }
    seasonalDates { summer { start end } winter { start end } }
    lastPTRSeason
    nextPTRSeason
  }
}
"""

GET_TIME_OF_DAY_ENROLLMENT_DETAILS = """
query getTimeOfDayEnrollmentDetails($params: TimeOfDayEnrollmentDetailsParams!) {
  getTimeOfDayEnrollmentDetails(params: $params) {
    isEnrolled
    cardType
    annualLookBackEarnedCredit
    offPeakCharges
    midPeakCharges
    onPeakCharges
    planSavings
  }
}
"""

GET_SMART_THERMOSTAT_ENROLLMENT_DETAILS = """
query getSmartThermostatEnrollmentDetails($params: SmartThermostatEnrollmentDetailsParams!) {
  getSmartThermostatEnrollmentDetails(params: $params) {
    isEnrolled
    cardType
  }
}
"""

GET_SMART_CHARGING_ENROLLMENT_DETAILS = """
query getSmartChargingEnrollmentDetails($params: SmartChargingEnrollmentDetailsParams!) {
  getSmartChargingEnrollmentDetails(params: $params) {
    enrollmentStatus
    cardType
    lastSeasonEarnedCredit
    activeSeason { name start end }
  }
}
"""

GET_SMART_BATTERY_DETAILS = """
query getSmartBatteryDetails($params: SmartBatteryDetailsParams!) {
  getSmartBatteryDetails(params: $params) {
    isEnrolled
    cardType
    currentBillCreditAmount
    currentBillKwh
    ytdCreditAmount
    ytdKwh
    peakTimeSeason { seasonCategory season startDate endDate }
  }
}
"""

GET_NET_METERING_DETAILS = """
query getNetMeteringDetails($params: NetMeteringDetailsParams!) {
  getNetMeteringDetails(params: $params) {
    isEnrolled
    cardType
    currentBalance
    lastStatementCredit
    annualTrueUpDate
    yearToDateGeneration
    yearToDateExport
  }
}
"""

GET_RATE_COMPARE = """
query getRateCompare($params: RateCompareParams!) {
  getRateCompare(params: $params) {
    touTotal
    basicTotal
    savings
    comparisonPeriod
  }
}
"""

_ISO_DATE_FORMATS = (
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%d-%b-%Y",
    "%b %d, %Y",
)


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


def _safe_float(value: Any) -> float | None:
    """Coerce a GraphQL scalar (number or currency-ish string) to float."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("$", "").replace(",", "")
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    try:
        result = float(text)
    except ValueError:
        return None
    return -result if negative else result


def _safe_int(value: Any) -> int | None:
    """Coerce a GraphQL scalar to a whole count (cycle day / day totals)."""
    number = _safe_float(value)
    if number is None:
        return None
    return int(number)


def _safe_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("true", "yes", "y", "1", "enrolled", "active"):
        return True
    if text in ("false", "no", "n", "0", "notenrolled", "not_enrolled", "inactive"):
        return False
    return None


def _parse_date(value: Any) -> datetime | None:
    """Parse an ISO timestamp or a common portal date string to UTC-aware."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    iso = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        parsed = None
    if parsed is None:
        for fmt in _ISO_DATE_FORMATS:
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _normalize_account_digits(value: str) -> str:
    """Digits-only compare key (strip leading zeros; keep a lone zero)."""
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits.lstrip("0") or ("0" if digits else "")


def account_detail_list_params(*, limit: int = 50) -> dict[str, Any]:
    """Shared AccountDetailList params; high limit covers multi-account logins.

    Used by billing sync and by credential account discovery (portal_auth).
    ``accountStatus: ACTIVE`` matches the portal account switcher for billable
    accounts; inactive/closed numbers are intentionally omitted.
    """
    return {
        "accountStatus": "ACTIVE",
        "groupId": "ALL_ACCTS",
        "paging": {"limit": limit, "offset": 0},
        "sort": {"direction": "ASC", "sort": "DEFAULT"},
        "filter": {"filterBy": "", "operator": "STARTSWITH"},
    }


# Compat alias for existing callers.
_account_detail_list_params = account_detail_list_params


def _select_account(
    accounts: list[Any],
    *,
    account_number: str | None = None,
    encrypted_account_number: str | None = None,
) -> dict[str, Any]:
    """Return the AccountDetail row for this entry; never silently pick accounts[0]."""
    rows = [a for a in accounts if isinstance(a, dict)]
    if not rows:
        raise PGESchemaError("Account detail list is empty")

    if encrypted_account_number:
        for account in rows:
            if account.get("encryptedAccountNumber") == encrypted_account_number:
                return account

    if account_number:
        target = _normalize_account_digits(account_number)
        for account in rows:
            if _normalize_account_digits(str(account.get("accountNumber", ""))) == target:
                return account

    raise PGESchemaError(
        "Bound account not found in getAccountDetailList "
        f"(account_number={'set' if account_number else 'missing'}, "
        f"encrypted={'set' if encrypted_account_number else 'missing'}, "
        f"returned={len(rows)})"
    )


def _classify_graphql_errors(errors: list[dict[str, Any]]) -> None:
    messages = " | ".join(str(e.get("message", e)) for e in errors)
    joined = messages.lower()
    if any(x in joined for x in ("unauthoriz", "unauthenticated", "token", "auth")):
        raise PGEAuthenticationError(f"GraphQL auth error: {messages}")
    if any(x in joined for x in ("forbidden", "not allowed", "access denied")):
        raise PGEAuthorizationError(f"GraphQL authorization error: {messages}")
    raise PGEGraphQLError(f"GraphQL errors: {messages}", errors)


class PGEBillingApiClient:
    """GraphQL client for PGE account/billing/programs data.

    Shares the usage endpoint and auth model (``PGEAuthManager``) with
    :class:`~custom_components.pge_energy.api.PGEApiClient` but uses the portal
    origin/referer and adds a single automatic token-renewal retry on HTTP 401.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        auth_manager: PGEAuthManager,
    ) -> None:
        self._session = session
        self._auth_manager = auth_manager
        self._rate_limit_until: datetime | None = None

    async def _post_graphql(
        self,
        query: str,
        variables: dict[str, Any],
        operation_name: str,
    ) -> dict[str, Any]:
        """POST a GraphQL document and return the parsed ``data`` object.

        Retries transient 5xx/network failures with backoff, renews the bearer
        token once on a 401, and classifies GraphQL/HTTP errors like ``api.py``.
        """
        if self._rate_limit_until and datetime.now(UTC) < self._rate_limit_until:
            raise PGERateLimitError(f"Rate limited until {self._rate_limit_until.isoformat()}")

        payload = {
            "query": query,
            "variables": variables,
            "operationName": operation_name,
        }

        renewed = False
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            token = await self._auth_manager.ensure_valid_token()
            headers = {
                "accept": "*/*",
                "authorization": f"Bearer {token}",
                "aws_graphql_server": "graphql_server",
                "content-type": "application/json",
                "origin": _ORIGIN,
                "referer": _REFERER,
            }
            try:
                async with self._session.post(
                    GRAPHQL_URL,
                    json=payload,
                    headers=headers,
                    timeout=DEFAULT_TIMEOUT,
                ) as resp:
                    if resp.status == 401:
                        if not renewed:
                            renewed = True
                            await self._auth_manager.force_renew()
                            continue
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
                if data.get("errors"):
                    _classify_graphql_errors(list(data["errors"]))
                result = data.get("data")
                if result is None:
                    raise PGESchemaError("GraphQL response missing data")
                return result

        raise PGEConnectionError(f"Request failed after {MAX_RETRIES} attempts: {last_exc}")

    # -- Account detail -----------------------------------------------------

    async def get_account_detail(self, account_number: str) -> AccountSnapshot:
        """Fetch account summary + latest bill for ``account_number``."""
        data = await self._post_graphql(
            GET_ACCOUNT_DETAIL_LIST,
            {"params": _account_detail_list_params()},
            "getAccountDetailList",
        )
        detail_list = data.get("getAccountDetailList")
        if detail_list is None:
            raise PGESchemaError("Response missing data.getAccountDetailList")
        accounts = detail_list.get("accounts") if isinstance(detail_list, dict) else detail_list
        if accounts is None:
            raise PGESchemaError("Response missing getAccountDetailList.accounts")
        if isinstance(accounts, dict):
            accounts = [accounts]
        if not isinstance(accounts, list):
            raise PGESchemaError("getAccountDetailList.accounts is not a list")

        matched = _select_account(accounts, account_number=account_number)
        return self._parse_account_snapshot(matched, account_number)

    def _parse_account_snapshot(
        self,
        account: dict[str, Any],
        account_number: str,
    ) -> AccountSnapshot:
        bill_info = account.get("billInfo") or {}
        bill_details_raw = bill_info.get("billDetails") or {}
        premise_list = account.get("premiseInfo") or []
        if isinstance(premise_list, dict):
            premise_list = [premise_list]
        encrypted_premise_id: str | None = None
        encrypted_sa_id: str | None = None
        if premise_list:
            premise = premise_list[0] or {}
            encrypted_premise_id = premise.get("encryptedPremiseId")
            sa_details = premise.get("saDetails") or []
            if isinstance(sa_details, dict):
                sa_details = [sa_details]
            if sa_details:
                encrypted_sa_id = (sa_details[0] or {}).get("encryptedSAId")

        autopay = account.get("autoPay") or {}
        paperless = account.get("isPaperlessBillEnrolled") or {}
        # Paperless may be a boolean or a { result: bool } object.
        paperless_enrolled = (
            _safe_bool(paperless) if not isinstance(paperless, dict) else _safe_bool(paperless.get("result"))
        )

        avg_temp_f: float | None = None
        avg_temp = account.get("viewBillAverageTemperature") or {}
        current_period = avg_temp.get("currentBillingPeriod") or {}
        avg_temp_f = _safe_float(current_period.get("averageTemperature"))

        bill = self._parse_bill_details(bill_details_raw, avg_temperature_f=avg_temp_f) if bill_details_raw else None

        return AccountSnapshot(
            account_number=str(account.get("accountNumber") or account_number),
            amount_due=_safe_float(bill_info.get("amountDue")),
            due_date=_parse_date(bill_info.get("dueDate")),
            last_payment_amount=_safe_float(bill_info.get("lastPaymentAmount")),
            last_payment_date=_parse_date(bill_info.get("lastPaymentDate")),
            autopay_enrolled=_safe_bool(autopay.get("isEnrolled")),
            paperless_enrolled=paperless_enrolled,
            bill=bill,
            encrypted_account_number=account.get("encryptedAccountNumber"),
            encrypted_person_id=account.get("encryptedPersonId"),
            encrypted_premise_id=encrypted_premise_id,
            encrypted_sa_id=encrypted_sa_id,
        )

    def _parse_bill_details(
        self,
        raw: dict[str, Any],
        *,
        avg_temperature_f: float | None = None,
    ) -> BillDetails:
        return BillDetails(
            amount_due=_safe_float(raw.get("amountDue")),
            kwh=_safe_float(raw.get("kwh")),
            bill_date=_parse_date(raw.get("billDate")),
            due_date=_parse_date(raw.get("dueDate")),
            previous_balance=_safe_float(raw.get("previousBalance")),
            total_adjustments=_safe_float(raw.get("totalAdjustments")),
            total_current_charges=_safe_float(raw.get("totalCurrentCharges")),
            total_balance_after_bill=_safe_float(raw.get("totalBalanceAfterBill")),
            period_start=_parse_date(raw.get("billingPeriodStartDate")),
            period_end=_parse_date(raw.get("billingPeriodEndDate")),
            encrypted_bill_id=raw.get("encryptedBillId"),
            avg_temperature_f=avg_temperature_f,
        )

    # -- Payment / bill history --------------------------------------------

    async def get_payment_history_page(
        self,
        encrypted_account_number: str,
        encrypted_person_id: str = "",
        *,
        account_number: str | None = None,
        limit: int = 15,
        offset: int = 0,
    ) -> tuple[list[LedgerEvent], int]:
        """Return a server-paged ledger page plus totalDetailsRecords.

        Uses nested ``AccountDetail.paymentHistory`` (portal charge-summary
        op fails with opaque errors). Matches the bound account by encrypted
        account number and/or plaintext ``account_number`` — never ``accounts[0]``.
        ``encrypted_person_id`` is retained for call-site compatibility only.
        """
        del encrypted_person_id
        variables = {
            "params": _account_detail_list_params(),
            "php": {
                "pagingParams": {"limit": limit, "offset": offset},
                "sortDirection": "DESC",
            },
        }
        data = await self._post_graphql(
            GET_ACCOUNT_DETAIL_PAYMENT_HISTORY,
            variables,
            "getAccountDetailList",
        )
        accounts = (data.get("getAccountDetailList") or {}).get("accounts") or []
        if isinstance(accounts, dict):
            accounts = [accounts]
        if not accounts:
            return [], 0
        matched = _select_account(
            accounts,
            account_number=account_number,
            encrypted_account_number=encrypted_account_number or None,
        )
        history = matched.get("paymentHistory") or {}
        rows = history.get("paymentHistoryDetails") or []
        total = int(history.get("totalDetailsRecords") or len(rows))

        events: list[LedgerEvent] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            event = self._parse_ledger_event(row)
            if event is not None:
                events.append(event)
        return events, total

    def _parse_ledger_event(self, row: dict[str, Any]) -> LedgerEvent | None:
        event_date = _parse_date(row.get("date"))
        if event_date is None:
            return None
        raw_type = str(row.get("type") or "").strip().lower()
        event_type = LedgerEventType.PAYMENT if raw_type.startswith("pay") else LedgerEventType.BILL
        return LedgerEvent(
            event_type=event_type,
            date=event_date,
            amount_due=_safe_float(row.get("amountDue")),
            amount_paid=_safe_float(row.get("amountPaid")),
            kwh=_safe_float(row.get("kwh")),
            period_start=_parse_date(row.get("billingPeriodStartDate")),
            period_end=_parse_date(row.get("billingPeriodEndDate")),
            encrypted_bill_id=row.get("encryptedBillId"),
        )

    # -- Open-cycle estimates ----------------------------------------------

    async def get_energy_tracker_estimates(
        self,
        encrypted_account_number: str,
        encrypted_person_id: str,
    ) -> EnergyTrackerEstimates:
        """Fetch the portal Current Use estimates for the open billing cycle."""
        data = await self._post_graphql(
            GET_ENERGY_TRACKER_DATA,
            {
                "params": {
                    "encryptedAccountNumber": encrypted_account_number,
                    "encryptedPersonId": encrypted_person_id,
                }
            },
            "getEnergyTrackerData",
        )
        tracker = data.get("getEnergyTrackerData")
        if not isinstance(tracker, dict):
            raise PGESchemaError("Response missing data.getEnergyTrackerData")
        details = tracker.get("details") or {}
        current = tracker.get("currentBillingPeriod") or {}
        previous = tracker.get("previousBillingPeriod") or {}
        return EnergyTrackerEstimates(
            details_available=bool(_safe_bool(tracker.get("detailsAvailable"))),
            has_more_than_15_days=_safe_bool(tracker.get("hasMoreThan15DaysOfData")),
            billing_cycle_day=_safe_int(details.get("billingCycleDay")),
            billing_cycle_total_days=_safe_int(details.get("numberOfBillingDays")),
            bill_to_date_amount=_safe_float(details.get("billToDateAmount")),
            projected_min_amount=_safe_float(details.get("minProjectedAmount")),
            projected_max_amount=_safe_float(details.get("maxProjectedAmount")),
            current_period_kwh=_safe_float(current.get("totalKwh")),
            previous_period_kwh=_safe_float(previous.get("totalKwh")),
        )

    # -- Net metering (gated, diagnostic) ------------------------------------

    async def get_net_metering_details(
        self,
        encrypted_account_id: str,
        encrypted_premise_id: str,
    ) -> NetMeteringSnapshot:
        """Best-effort net-metering detail; all fields kept as diagnostic strings."""
        data = await self._post_graphql(
            GET_NET_METERING_DETAILS,
            {
                "params": {
                    "encryptedAccountId": encrypted_account_id,
                    "encryptedPremiseId": encrypted_premise_id,
                }
            },
            "getNetMeteringDetails",
        )
        raw = data.get("getNetMeteringDetails")
        attrs = dict(raw) if isinstance(raw, dict) else {}
        return NetMeteringSnapshot(fetched_at=datetime.now(UTC), attributes=attrs)

    # -- Rate compare (TOD vs Basic aggregates) -----------------------------

    async def get_rate_compare(
        self,
        account_number: str,
    ) -> RateCompareSnapshot:
        """Best-effort rate comparison; diagnostic only — never derive period rates."""
        data = await self._post_graphql(
            GET_RATE_COMPARE,
            {"params": {"accountNumber": account_number}},
            "getRateCompare",
        )
        raw = data.get("getRateCompare")
        attrs = sanitize_rate_compare_attrs(dict(raw)) if isinstance(raw, dict) else {}
        return RateCompareSnapshot(fetched_at=datetime.now(UTC), attributes=attrs)

    # -- Programs -----------------------------------------------------------

    async def get_programs(
        self,
        encrypted_account_number: str,
        encrypted_premise_id: str,
        encrypted_sa_id: str,
    ) -> ProgramsSnapshot:
        """Fetch program enrollment; individual detail ops are best-effort."""
        params = {
            "encryptedAccountNumber": encrypted_account_number,
            "encryptedPremiseId": encrypted_premise_id,
            "encryptedSaId": encrypted_sa_id,
        }
        data = await self._post_graphql(
            GET_PROGRAMS_ENROLLMENT_STATUS_DETAILS,
            {"params": params},
            "GetProgramsEnrollmentStatusDetails",
        )
        status = data.get("getProgramsEnrollmentStatusDetails") or {}

        energy_shifting = [self._parse_program_enrollment(item) for item in (status.get("energyShifting") or [])]
        renewables = [self._parse_program_enrollment(item) for item in (status.get("renewables") or [])]

        snapshot_attrs: dict[str, object] = {}
        ptr_keywords = ("peak time", "peak_time", "peak-time", "peaktime", "rebate")
        green_future_keywords = ("green future", "green_future", "green source", "renewable")
        tod_keywords = ("time of day", "time_of_day", "time-of-day", "tod")
        smart_thermostat_keywords = ("smart thermostat", "smart_thermostat", "thermostat")
        peak_time_rebates_enrolled = _program_list_enrolled(energy_shifting, ptr_keywords)
        peak_time_rebates_eligible = _program_list_eligible(energy_shifting, ptr_keywords)
        green_future_enrolled = _program_list_enrolled(renewables, green_future_keywords)
        green_future_eligible = _program_list_eligible(renewables, green_future_keywords)
        time_of_day_enrolled = _program_list_enrolled(energy_shifting, tod_keywords)
        time_of_day_eligible = _program_list_eligible(energy_shifting, tod_keywords)
        smart_thermostat_enrolled = _program_list_enrolled(energy_shifting, smart_thermostat_keywords)
        smart_thermostat_eligible = _program_list_eligible(energy_shifting, smart_thermostat_keywords)
        habitat_support_enrolled = _program_list_enrolled(renewables + energy_shifting, ("habitat",))
        habitat_support_eligible = _program_list_eligible(renewables + energy_shifting, ("habitat",))
        smart_charging_match = _program_list_lookup(
            energy_shifting,
            ("ev_smart_charging", "ev smart charging", "smart charging", "ev charging"),
        )
        smart_charging_enrolled = smart_charging_match.is_enrolled if smart_charging_match else None
        smart_charging_eligible = smart_charging_match.is_eligible if smart_charging_match else None
        smart_battery_match = _program_list_lookup(
            energy_shifting,
            ("smart_battery_pilot", "smart battery pilot", "smart battery", "battery pilot"),
        )
        smart_battery_enrolled = smart_battery_match.is_enrolled if smart_battery_match else None
        smart_battery_eligible = smart_battery_match.is_eligible if smart_battery_match else None
        green_future_pct: float | None = None

        # Best-effort detail ops: swallow individual failures into a partial
        # snapshot so one unavailable program never breaks billing sync.
        # Param shapes differ per op (portal Apollo cache).
        peak = await self._best_effort_detail(
            GET_PEAK_TIME_REBATE_ENROLLMENT_DETAILS,
            "getPeakTimeRebateEnrollmentDetails",
            {
                "encryptedAccountNumber": encrypted_account_number,
                "ptrMockServerDate": "",
            },
        )
        if peak is not None:
            status_parsed = _safe_bool(peak.get("enrollmentStatus"))
            if status_parsed is not None:
                peak_time_rebates_enrolled = status_parsed
            else:
                enrolled = _safe_bool(peak.get("isEnrolled"))
                if enrolled is not None:
                    peak_time_rebates_enrolled = enrolled
            peak_enriched = dict(peak)
            peak_enriched["peak_time_events"] = normalize_ptr_events(peak.get("peakTimeEvents"))
            seasonal = peak.get("seasonalDates")
            if isinstance(seasonal, dict):
                peak_enriched["seasonal_dates"] = seasonal
            for season_key in ("lastPTRSeason", "nextPTRSeason", "activePTRSeason"):
                if peak.get(season_key) is not None:
                    peak_enriched[season_key] = peak[season_key]
            snapshot_attrs["peak_time_rebate"] = peak_enriched

        renew_detail = await self._best_effort_detail(
            GET_RENEWABLES_ENROLLMENT_DETAILS,
            "getRenewablesEnrollmentDetails",
            {"encryptedServiceAgreementId": encrypted_sa_id},
        )
        if renew_detail is not None:
            gfc = renew_detail.get("greenFutureProgramDetails") or {}
            enrolled = _safe_bool(gfc.get("isEnrolled"))
            if enrolled is not None:
                green_future_enrolled = enrolled
            green_future_pct = _safe_float(gfc.get("consumptionPercentage"))
            habitat = renew_detail.get("habitatSupport") or {}
            habitat_enrolled = _safe_bool(habitat.get("isEnrolled"))
            if habitat_enrolled is not None:
                habitat_support_enrolled = habitat_enrolled
            snapshot_attrs["renewables_detail"] = renew_detail

        tod_detail = await self._best_effort_detail(
            GET_TIME_OF_DAY_ENROLLMENT_DETAILS,
            "getTimeOfDayEnrollmentDetails",
            {
                "encryptedAccountNumber": encrypted_account_number,
                "encryptedServiceAgreementId": encrypted_sa_id,
            },
        )
        if tod_detail is not None:
            enrolled = _safe_bool(tod_detail.get("isEnrolled"))
            if enrolled is not None:
                time_of_day_enrolled = enrolled
            snapshot_attrs["tod_enrollment_detail"] = tod_detail

        thermostat_detail = await self._best_effort_detail(
            GET_SMART_THERMOSTAT_ENROLLMENT_DETAILS,
            "getSmartThermostatEnrollmentDetails",
            {"encryptedAccountNumber": encrypted_account_number},
        )
        if thermostat_detail is not None:
            enrolled = _safe_bool(thermostat_detail.get("isEnrolled"))
            if enrolled is not None:
                smart_thermostat_enrolled = enrolled

        smart_charging_detail = await self._best_effort_detail(
            GET_SMART_CHARGING_ENROLLMENT_DETAILS,
            "getSmartChargingEnrollmentDetails",
            {"encryptedAccountNumber": encrypted_account_number},
        )
        if smart_charging_detail is not None:
            sc_status = _safe_bool(smart_charging_detail.get("enrollmentStatus"))
            if sc_status is not None:
                smart_charging_enrolled = sc_status
            else:
                sc_enrolled = _safe_bool(smart_charging_detail.get("isEnrolled"))
                if sc_enrolled is not None:
                    smart_charging_enrolled = sc_enrolled
            snapshot_attrs["smart_charging_detail"] = smart_charging_detail

        smart_battery_detail = await self._best_effort_detail(
            GET_SMART_BATTERY_DETAILS,
            "getSmartBatteryDetails",
            {"encryptedServiceAgreementId": encrypted_sa_id},
        )
        if smart_battery_detail is not None:
            sb_enrolled = _safe_bool(smart_battery_detail.get("isEnrolled"))
            if sb_enrolled is not None:
                smart_battery_enrolled = sb_enrolled
            snapshot_attrs["smart_battery_detail"] = smart_battery_detail

        return ProgramsSnapshot(
            energy_shifting=energy_shifting,
            renewables=renewables,
            ytd_flex_load_earnings=_safe_float(status.get("ytdFlexLoadEarnings")),
            on_bill_flex_load_earnings=_safe_float(status.get("onBillFlexLoadEarnings")),
            peak_time_rebates_enrolled=peak_time_rebates_enrolled,
            peak_time_rebates_eligible=peak_time_rebates_eligible,
            green_future_enrolled=green_future_enrolled,
            green_future_eligible=green_future_eligible,
            time_of_day_enrolled=time_of_day_enrolled,
            time_of_day_eligible=time_of_day_eligible,
            smart_thermostat_enrolled=smart_thermostat_enrolled,
            smart_thermostat_eligible=smart_thermostat_eligible,
            habitat_support_enrolled=habitat_support_enrolled,
            habitat_support_eligible=habitat_support_eligible,
            smart_charging_enrolled=smart_charging_enrolled,
            smart_charging_eligible=smart_charging_eligible,
            smart_battery_enrolled=smart_battery_enrolled,
            smart_battery_eligible=smart_battery_eligible,
            green_future_pct=green_future_pct,
            attributes=snapshot_attrs,
        )

    def _parse_program_enrollment(self, item: dict[str, Any]) -> ProgramEnrollment:
        known = {"isEnrolled", "isEligible", "programName"}
        attributes = {k: v for k, v in item.items() if k not in known}
        return ProgramEnrollment(
            program_name=str(item.get("programName") or ""),
            is_enrolled=_safe_bool(item.get("isEnrolled")),
            is_eligible=_safe_bool(item.get("isEligible")),
            attributes=attributes,
        )

    async def _best_effort_detail(
        self,
        query: str,
        operation_name: str,
        params: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Run a per-program detail op, swallowing failures into ``None``."""
        try:
            data = await self._post_graphql(query, {"params": params}, operation_name)
        except (
            PGEGraphQLError,
            PGESchemaError,
            PGEConnectionError,
            PGERateLimitError,
            PGEAuthorizationError,
        ) as exc:
            _LOGGER.debug("Program detail op %s unavailable: %s", operation_name, exc)
            return None
        result = data.get(operation_name)
        if isinstance(result, dict):
            return result
        return None


def _program_list_enrolled(
    programs: list[ProgramEnrollment],
    keywords: tuple[str, ...],
) -> bool | None:
    """Return enrollment for matched programs (tri-state).

    ``True`` if any match is explicitly enrolled, ``False`` if any match is
    explicitly not enrolled (and none enrolled), else ``None`` when unmatched
    or all matched rows leave enrollment null.
    """
    saw_false = False
    matched = False
    for program in programs:
        name = program.program_name.lower()
        if any(keyword in name for keyword in keywords):
            matched = True
            if program.is_enrolled is True:
                return True
            if program.is_enrolled is False:
                saw_false = True
    if not matched:
        return None
    return False if saw_false else None


def _program_list_eligible(
    programs: list[ProgramEnrollment],
    keywords: tuple[str, ...],
) -> bool | None:
    """Return eligibility for matched programs (tri-state).

    ``True`` if any match is explicitly eligible, ``False`` if any match is
    explicitly ineligible (and none eligible), else ``None`` when unmatched
    or all matched rows leave eligibility null.
    """
    saw_false = False
    matched = False
    for program in programs:
        name = program.program_name.lower()
        if any(keyword in name for keyword in keywords):
            matched = True
            if program.is_eligible is True:
                return True
            if program.is_eligible is False:
                saw_false = True
    if not matched:
        return None
    return False if saw_false else None


def _program_list_lookup(
    programs: list[ProgramEnrollment],
    keywords: tuple[str, ...],
) -> ProgramEnrollment | None:
    """Return the first matching ProgramEnrollment (preserves is_eligible)."""
    for program in programs:
        name = program.program_name.lower()
        if any(keyword in name for keyword in keywords):
            return program
    return None


def normalize_ptr_events(raw_events: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Sort, dedupe, and filter malformed PTR event entries.

    Returns a list of ``{"event_date": "YYYY-MM-DD", "event_earned_credit": float|None}``
    sorted ascending by date, with duplicate dates removed (first occurrence wins).
    """
    if not raw_events:
        return []
    seen: set[str] = set()
    clean: list[dict[str, Any]] = []
    for entry in raw_events:
        if not isinstance(entry, dict):
            continue
        raw_date = entry.get("eventDate")
        if not raw_date:
            continue
        text = str(raw_date).strip()
        parsed = _parse_date(text)
        if parsed is None:
            continue
        iso = parsed.strftime("%Y-%m-%d")
        if iso in seen:
            continue
        seen.add(iso)
        clean.append(
            {
                "event_date": iso,
                "event_earned_credit": _safe_float(entry.get("eventEarnedCredit")),
            }
        )
    clean.sort(key=lambda e: e["event_date"])
    return clean
