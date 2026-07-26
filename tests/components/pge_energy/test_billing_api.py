"""Unit tests for billing GraphQL parsing (fixture-backed, no network)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.pge_energy.billing_api import (
    PGEBillingApiClient,
    _parse_date,
    _safe_bool,
    _safe_float,
    _select_account,
)
from custom_components.pge_energy.billing_models import LedgerEventType
from custom_components.pge_energy.exceptions import PGESchemaError

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "billing"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _client() -> PGEBillingApiClient:
    auth = MagicMock()
    auth.ensure_valid_token = AsyncMock(return_value="tok")
    auth.force_renew = AsyncMock(return_value="tok2")
    return PGEBillingApiClient(MagicMock(), auth)


class TestBillingHelpers:
    def test_safe_float_currency(self):
        assert _safe_float("$1,234.50") == 1234.5
        assert _safe_float("(12.00)") == -12.0
        assert _safe_float(None) is None
        assert _safe_float("n/a") is None

    def test_safe_bool(self):
        assert _safe_bool(True) is True
        assert _safe_bool("enrolled") is True
        assert _safe_bool("inactive") is False
        assert _safe_bool(None) is None

    def test_parse_date_iso_and_us(self):
        assert _parse_date("2026-07-13T07:00:00.000Z") == datetime(2026, 7, 13, 7, 0, tzinfo=UTC)
        assert _parse_date("07/30/2026") == datetime(2026, 7, 30, tzinfo=UTC)
        assert _parse_date("") is None


class TestAccountDetailParse:
    @pytest.mark.asyncio
    async def test_parse_account_detail_fixture(self):
        client = _client()
        client._post_graphql = AsyncMock(return_value=_load("get_account_detail_list.json"))
        snap = await client.get_account_detail("0000000000")
        assert snap.amount_due == 300.13
        assert snap.autopay_enrolled is True
        assert snap.paperless_enrolled is True
        assert snap.last_payment_amount == 293.01
        assert snap.encrypted_account_number == "<REDACTED>"
        assert snap.encrypted_premise_id == "<REDACTED>"
        assert snap.encrypted_sa_id == "<REDACTED>"
        assert snap.bill is not None
        assert snap.bill.kwh == 1358.0
        assert snap.bill.avg_temperature_f == 64.88
        assert snap.bill.period_start == datetime(2026, 6, 4, 7, 0, tzinfo=UTC)


class TestAccountSelection:
    def test_select_by_account_number_not_first(self):
        accounts = [
            {"accountNumber": "1111111111", "encryptedAccountNumber": "enc-other"},
            {"accountNumber": "0000000000", "encryptedAccountNumber": "enc-target"},
        ]
        matched = _select_account(accounts, account_number="0000000000")
        assert matched["encryptedAccountNumber"] == "enc-target"

    def test_select_by_encrypted_account_number(self):
        accounts = [
            {"accountNumber": "1111111111", "encryptedAccountNumber": "enc-a"},
            {"accountNumber": "2222222222", "encryptedAccountNumber": "enc-b"},
        ]
        matched = _select_account(accounts, encrypted_account_number="enc-b")
        assert matched["accountNumber"] == "2222222222"

    def test_select_raises_when_unmatched(self):
        with pytest.raises(PGESchemaError, match="Bound account not found"):
            _select_account(
                [{"accountNumber": "1111111111", "encryptedAccountNumber": "enc-a"}],
                account_number="9999999999",
            )


class TestPaymentHistoryParse:
    @pytest.mark.asyncio
    async def test_parse_payment_history_page(self):
        client = _client()
        client._post_graphql = AsyncMock(return_value=_load("payment_history_page.json"))
        events, total = await client.get_payment_history_page(
            "<REDACTED>",
            "enc-p",
            account_number="0000000000",
            limit=15,
            offset=0,
        )
        assert total == 72
        assert len(events) == 15
        assert events[0].event_type == LedgerEventType.BILL
        assert events[0].amount_due == 300.13
        assert events[0].kwh == 1358.0
        assert events[1].event_type == LedgerEventType.PAYMENT
        assert events[1].amount_paid == 293.01

    @pytest.mark.asyncio
    async def test_payment_history_matches_bound_account_not_first(self):
        client = _client()
        payload = {
            "getAccountDetailList": {
                "accounts": [
                    {
                        "accountNumber": "1111111111",
                        "encryptedAccountNumber": "enc-wrong",
                        "paymentHistory": {
                            "totalDetailsRecords": 1,
                            "paymentHistoryDetails": [
                                {
                                    "date": "2026-07-01T07:00:00.000Z",
                                    "type": "Bill",
                                    "amountDue": 1.0,
                                    "amountPaid": 0,
                                    "kwh": 1,
                                }
                            ],
                        },
                    },
                    {
                        "accountNumber": "0000000000",
                        "encryptedAccountNumber": "enc-right",
                        "paymentHistory": {
                            "totalDetailsRecords": 2,
                            "paymentHistoryDetails": [
                                {
                                    "date": "2026-07-13T07:00:00.000Z",
                                    "type": "Bill",
                                    "amountDue": 300.13,
                                    "amountPaid": 0,
                                    "kwh": 1358,
                                }
                            ],
                        },
                    },
                ]
            }
        }
        client._post_graphql = AsyncMock(return_value=payload)
        events, total = await client.get_payment_history_page(
            "enc-right",
            account_number="0000000000",
            limit=15,
            offset=0,
        )
        assert total == 2
        assert len(events) == 1
        assert events[0].amount_due == 300.13

    @pytest.mark.asyncio
    async def test_account_detail_raises_when_unmatched(self):
        client = _client()
        client._post_graphql = AsyncMock(return_value=_load("get_account_detail_list.json"))
        with pytest.raises(PGESchemaError, match="Bound account not found"):
            await client.get_account_detail("9999999999")


class TestEnergyTrackerParse:
    @pytest.mark.asyncio
    async def test_parse_tracker_estimates(self):
        client = _client()
        client._post_graphql = AsyncMock(
            return_value={
                "getEnergyTrackerData": {
                    "detailsAvailable": True,
                    "hasMoreThan15DaysOfData": True,
                    "details": {
                        "billingCycleDay": 17,
                        "numberOfBillingDays": 30,
                        "billToDateAmount": 124,
                        "minProjectedAmount": 186.3,
                        "maxProjectedAmount": 227.7,
                    },
                    "currentBillingPeriod": {"totalKwh": 358},
                    "previousBillingPeriod": {"totalKwh": 721},
                }
            }
        )
        estimates = await client.get_energy_tracker_estimates("enc-a", "enc-p")
        assert estimates.details_available is True
        assert estimates.billing_cycle_day == 17
        assert estimates.billing_cycle_total_days == 30
        assert estimates.bill_to_date_amount == 124.0
        assert estimates.projected_min_amount == 186.3
        assert estimates.projected_max_amount == 227.7
        assert estimates.current_period_kwh == 358.0
        assert estimates.previous_period_kwh == 721.0

    @pytest.mark.asyncio
    async def test_tracker_tolerates_missing_details(self):
        client = _client()
        client._post_graphql = AsyncMock(
            return_value={"getEnergyTrackerData": {"detailsAvailable": False, "details": None}}
        )
        estimates = await client.get_energy_tracker_estimates("enc-a", "enc-p")
        assert estimates.details_available is False
        assert estimates.billing_cycle_day is None
        assert estimates.bill_to_date_amount is None

    @pytest.mark.asyncio
    async def test_tracker_missing_root_raises(self):
        client = _client()
        client._post_graphql = AsyncMock(return_value={"getEnergyTrackerData": None})
        with pytest.raises(PGESchemaError):
            await client.get_energy_tracker_estimates("enc-a", "enc-p")


class TestProgramsParse:
    @pytest.mark.asyncio
    async def test_parse_programs_status_fixture(self):
        client = _client()
        status = _load("programs_enrollment.json")

        async def _post(query, variables, operation_name):
            if operation_name == "GetProgramsEnrollmentStatusDetails":
                return status
            raise AssertionError(f"unexpected op {operation_name}")

        client._post_graphql = AsyncMock(side_effect=_post)
        # Detail ops go through _best_effort_detail → _post_graphql; return None via error
        client._best_effort_detail = AsyncMock(return_value=None)
        programs = await client.get_programs("enc-a", "enc-p", "enc-sa")
        assert programs.ytd_flex_load_earnings == 3.7
        assert programs.peak_time_rebates_enrolled is True
        assert programs.green_future_enrolled is True
