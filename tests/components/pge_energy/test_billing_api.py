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
    _program_list_eligible,
    _program_list_enrolled,
    _safe_bool,
    _safe_float,
    _select_account,
    normalize_ptr_events,
)
from custom_components.pge_energy.billing_models import LedgerEventType, ProgramEnrollment, RateCompareSnapshot
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
        client._best_effort_detail = AsyncMock(return_value=None)
        programs = await client.get_programs("enc-a", "enc-p", "enc-sa")
        assert programs.ytd_flex_load_earnings == 3.7
        assert programs.peak_time_rebates_enrolled is True
        assert programs.green_future_enrolled is True
        assert programs.peak_time_rebates_eligible is True
        assert programs.green_future_eligible is True
        assert programs.time_of_day_enrolled is False
        assert programs.time_of_day_eligible is True
        assert programs.smart_thermostat_enrolled is False
        assert programs.smart_thermostat_eligible is False
        assert programs.habitat_support_enrolled is None
        assert programs.habitat_support_eligible is None

    @pytest.mark.asyncio
    async def test_smart_charging_and_battery_from_status_list(self):
        client = _client()
        status = _load("programs_enrollment.json")

        async def _post(query, variables, operation_name):
            if operation_name == "GetProgramsEnrollmentStatusDetails":
                return status
            raise AssertionError(f"unexpected op {operation_name}")

        client._post_graphql = AsyncMock(side_effect=_post)
        client._best_effort_detail = AsyncMock(return_value=None)
        programs = await client.get_programs("enc-a", "enc-p", "enc-sa")
        assert programs.smart_charging_enrolled is False
        assert programs.smart_charging_eligible is True
        assert programs.smart_battery_enrolled is False
        assert programs.smart_battery_eligible is True

    @pytest.mark.asyncio
    async def test_smart_charging_detail_enrichment(self):
        client = _client()
        status = _load("programs_enrollment.json")
        sc_detail = {
            "enrollmentStatus": "ENROLLED",
            "cardType": "smart_charging",
            "lastSeasonEarnedCredit": 12.5,
            "activeSeason": {"name": "Summer 2026", "start": "2026-06-01", "end": "2026-09-30"},
        }

        async def _post(query, variables, operation_name):
            if operation_name == "GetProgramsEnrollmentStatusDetails":
                return status
            raise AssertionError(f"unexpected op {operation_name}")

        client._post_graphql = AsyncMock(side_effect=_post)

        async def _detail(query, op_name, params):
            if op_name == "getSmartChargingEnrollmentDetails":
                return sc_detail
            return None

        client._best_effort_detail = AsyncMock(side_effect=_detail)
        programs = await client.get_programs("enc-a", "enc-p", "enc-sa")
        assert programs.smart_charging_enrolled is True
        assert programs.attributes.get("smart_charging_detail") == sc_detail

    @pytest.mark.asyncio
    async def test_smart_battery_detail_enrichment(self):
        client = _client()
        status = _load("programs_enrollment.json")
        sb_detail = {
            "isEnrolled": True,
            "cardType": "smart_battery",
            "currentBillCreditAmount": 5.0,
            "currentBillKwh": 20.0,
            "ytdCreditAmount": 25.0,
            "ytdKwh": 100.0,
        }

        async def _post(query, variables, operation_name):
            if operation_name == "GetProgramsEnrollmentStatusDetails":
                return status
            raise AssertionError(f"unexpected op {operation_name}")

        client._post_graphql = AsyncMock(side_effect=_post)

        async def _detail(query, op_name, params):
            if op_name == "getSmartBatteryDetails":
                return sb_detail
            return None

        client._best_effort_detail = AsyncMock(side_effect=_detail)
        programs = await client.get_programs("enc-a", "enc-p", "enc-sa")
        assert programs.smart_battery_enrolled is True
        assert programs.attributes.get("smart_battery_detail") == sb_detail


class TestPTREvents:
    def test_normalize_sorts_and_dedupes(self):
        raw = [
            {"eventDate": "2026-08-15", "eventEarnedCredit": 2.5},
            {"eventDate": "2026-08-10", "eventEarnedCredit": 1.0},
            {"eventDate": "2026-08-15", "eventEarnedCredit": 3.0},
        ]
        result = normalize_ptr_events(raw)
        assert len(result) == 2
        assert result[0]["event_date"] == "2026-08-10"
        assert result[1]["event_date"] == "2026-08-15"
        assert result[1]["event_earned_credit"] == 2.5

    def test_normalize_filters_malformed(self):
        raw = [
            {"eventDate": "not-a-date", "eventEarnedCredit": 1.0},
            {"eventDate": "2026-08-20", "eventEarnedCredit": None},
            {"eventDate": "", "eventEarnedCredit": 2.0},
            {},
            None,
        ]
        result = normalize_ptr_events(raw)
        assert len(result) == 1
        assert result[0]["event_date"] == "2026-08-20"
        assert result[0]["event_earned_credit"] is None

    def test_normalize_empty_and_none(self):
        assert normalize_ptr_events(None) == []
        assert normalize_ptr_events([]) == []

    def test_normalize_us_date_format(self):
        raw = [{"eventDate": "08/25/2026", "eventEarnedCredit": 3.0}]
        result = normalize_ptr_events(raw)
        assert len(result) == 1
        assert result[0]["event_date"] == "2026-08-25"

    @pytest.mark.asyncio
    async def test_ptr_detail_enriches_events(self):
        client = _client()
        status = _load("programs_enrollment.json")
        ptr_detail = {
            "enrollmentStatus": "ENROLLED",
            "cardType": "peak_time",
            "totalEarnedCredit": 10.0,
            "activePTRSeason": "Summer 2026",
            "peakTimeEvents": [
                {"eventDate": "2026-08-15", "eventEarnedCredit": 2.5},
                {"eventDate": "2026-08-10", "eventEarnedCredit": 1.0},
            ],
            "seasonalDates": {
                "summer": {"start": "2026-06-01", "end": "2026-09-30"},
                "winter": {"start": "2026-10-01", "end": "2027-05-31"},
            },
            "lastPTRSeason": "Winter 2025",
            "nextPTRSeason": "Winter 2026",
        }

        async def _post(query, variables, operation_name):
            if operation_name == "GetProgramsEnrollmentStatusDetails":
                return status
            raise AssertionError(f"unexpected op {operation_name}")

        client._post_graphql = AsyncMock(side_effect=_post)

        async def _detail(query, op_name, params):
            if op_name == "getPeakTimeRebateEnrollmentDetails":
                return ptr_detail
            return None

        client._best_effort_detail = AsyncMock(side_effect=_detail)
        programs = await client.get_programs("enc-a", "enc-p", "enc-sa")
        peak = programs.attributes.get("peak_time_rebate")
        assert peak is not None
        events = peak["peak_time_events"]
        assert len(events) == 2
        assert events[0]["event_date"] == "2026-08-10"
        assert events[1]["event_date"] == "2026-08-15"
        assert peak["seasonal_dates"]["summer"]["start"] == "2026-06-01"
        assert peak["lastPTRSeason"] == "Winter 2025"
        assert peak["nextPTRSeason"] == "Winter 2026"


class TestNetMeteringParse:
    @pytest.mark.asyncio
    async def test_parse_net_metering_details(self):
        client = _client()
        client._post_graphql = AsyncMock(
            return_value={
                "getNetMeteringDetails": {
                    "isEnrolled": True,
                    "cardType": "net_metering",
                    "currentBalance": "$45.00",
                    "annualTrueUpDate": "2027-04-15",
                }
            }
        )
        snapshot = await client.get_net_metering_details("enc-a", "enc-p")
        assert snapshot.fetched_at is not None
        assert snapshot.attributes["isEnrolled"] is True
        assert snapshot.attributes["currentBalance"] == "$45.00"

    @pytest.mark.asyncio
    async def test_net_metering_tolerates_missing(self):
        client = _client()
        client._post_graphql = AsyncMock(return_value={"getNetMeteringDetails": None})
        snapshot = await client.get_net_metering_details("enc-a", "enc-p")
        assert snapshot.attributes == {}


class TestRateCompareParse:
    @pytest.mark.asyncio
    async def test_parse_rate_compare(self):
        client = _client()
        client._post_graphql = AsyncMock(
            return_value={
                "getRateCompare": {
                    "touTotal": 150.0,
                    "basicTotal": 175.0,
                    "savings": 25.0,
                    "comparisonPeriod": "2026-01 to 2026-07",
                }
            }
        )
        snapshot = await client.get_rate_compare("0000000000")
        assert snapshot.fetched_at is not None
        assert snapshot.attributes["touTotal"] == 150.0
        assert snapshot.attributes["savings"] == 25.0

    def test_rate_compare_accessors(self):
        snapshot = RateCompareSnapshot(
            fetched_at=datetime(2026, 8, 10, tzinfo=UTC),
            attributes={
                "touTotal": 150.0,
                "basicTotal": 175.0,
                "savings": 25.0,
                "comparisonPeriod": "2026-01 to 2026-07",
            },
        )
        assert snapshot.savings == 25.0
        assert snapshot.tou_total == 150.0
        assert snapshot.basic_total == 175.0
        assert snapshot.comparison_period == "2026-01 to 2026-07"
        assert snapshot.has_data is True

    def test_rate_compare_accessors_empty_or_non_numeric(self):
        snapshot = RateCompareSnapshot()
        assert snapshot.savings is None
        assert snapshot.tou_total is None
        assert snapshot.basic_total is None
        assert snapshot.comparison_period is None
        assert snapshot.has_data is False

        weird = RateCompareSnapshot(attributes={"savings": "n/a", "touTotal": float("inf")})
        assert weird.savings is None
        assert weird.tou_total is None


class TestTodEnrollmentDetail:
    @pytest.mark.asyncio
    async def test_tod_detail_attributes_enriched(self):
        client = _client()
        status = _load("programs_enrollment.json")
        tod_detail = {
            "isEnrolled": False,
            "cardType": "time_of_day",
            "annualLookBackEarnedCredit": 42.0,
            "offPeakCharges": 100.0,
            "midPeakCharges": 50.0,
            "onPeakCharges": 75.0,
            "planSavings": 25.0,
        }

        async def _post(query, variables, operation_name):
            if operation_name == "GetProgramsEnrollmentStatusDetails":
                return status
            raise AssertionError(f"unexpected op {operation_name}")

        client._post_graphql = AsyncMock(side_effect=_post)

        async def _detail(query, op_name, params):
            if op_name == "getTimeOfDayEnrollmentDetails":
                return tod_detail
            return None

        client._best_effort_detail = AsyncMock(side_effect=_detail)
        programs = await client.get_programs("enc-a", "enc-p", "enc-sa")
        detail = programs.attributes.get("tod_enrollment_detail")
        assert detail is not None
        assert detail["annualLookBackEarnedCredit"] == 42.0
        assert detail["planSavings"] == 25.0


class TestProgramListTriState:
    def test_eligible_null_on_matched_row_stays_unknown(self):
        programs = [ProgramEnrollment(program_name="Time of Day", is_enrolled=True, is_eligible=None)]
        assert _program_list_eligible(programs, ("time of day", "tod")) is None

    def test_eligible_explicit_false(self):
        programs = [ProgramEnrollment(program_name="Time of Day", is_enrolled=False, is_eligible=False)]
        assert _program_list_eligible(programs, ("time of day",)) is False

    def test_eligible_true_wins_over_null_sibling(self):
        programs = [
            ProgramEnrollment(program_name="Time of Day A", is_enrolled=False, is_eligible=None),
            ProgramEnrollment(program_name="Time of Day B", is_enrolled=True, is_eligible=True),
        ]
        assert _program_list_eligible(programs, ("time of day",)) is True

    def test_enrolled_null_on_matched_row_stays_unknown(self):
        programs = [ProgramEnrollment(program_name="Peak Time Rebates", is_enrolled=None)]
        assert _program_list_enrolled(programs, ("peak time", "ptr")) is None

    def test_unmatched_stays_none(self):
        programs = [ProgramEnrollment(program_name="Other", is_eligible=True, is_enrolled=True)]
        assert _program_list_eligible(programs, ("time of day",)) is None
        assert _program_list_enrolled(programs, ("time of day",)) is None


def test_program_enrollment_store_round_trip_allows_null_enrolled():
    row = ProgramEnrollment(program_name="Time of Day", is_enrolled=None, is_eligible=True)
    restored = ProgramEnrollment.from_dict(row.to_dict())
    assert restored is not None
    assert restored.is_enrolled is None
    assert restored.is_eligible is True
