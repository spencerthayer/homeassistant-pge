"""Unit tests for billing sensors and binary sensors."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from custom_components.pge_energy.billing_models import (
    AccountSnapshot,
    BillDetails,
    EnergyTrackerEstimates,
    ProgramsSnapshot,
)
from custom_components.pge_energy.binary_sensor import (
    PGEAutopayBinarySensor,
    PGEGreenFutureBinarySensor,
    PGEPaperlessBinarySensor,
)
from custom_components.pge_energy.sensor import (
    PGEAccountBalanceSensor,
    PGEBillingCycleDaySensor,
    PGEBillingCycleTotalDaysSensor,
    PGECurrentBillAmountSensor,
    PGECurrentBillKwhSensor,
    PGEEstCurrentChargesSensor,
    PGEEstNextBillMaxSensor,
    PGEEstNextBillMinSensor,
    PGELifetimePaymentsSensor,
    PGEYtdProgramSavingsSensor,
)


def _coord() -> MagicMock:
    coord = MagicMock()
    coord.account_id = "0000000000"
    coord.account_snapshot = AccountSnapshot(
        account_number="0000000000",
        amount_due=300.13,
        autopay_enrolled=True,
        paperless_enrolled=True,
        bill=BillDetails(
            amount_due=300.13,
            kwh=1358.0,
            period_start=datetime(2026, 6, 4, 7, tzinfo=UTC),
            period_end=datetime(2026, 7, 6, 7, tzinfo=UTC),
        ),
    )
    coord.programs_snapshot = ProgramsSnapshot(
        green_future_enrolled=True,
        green_future_pct=73.0,
        ytd_flex_load_earnings=3.7,
        on_bill_flex_load_earnings=0.0,
    )
    coord.lifetime_payments_usd = 1200.0
    coord.tracker_estimates = EnergyTrackerEstimates(
        details_available=True,
        has_more_than_15_days=True,
        billing_cycle_day=17,
        billing_cycle_total_days=30,
        bill_to_date_amount=124.0,
        projected_min_amount=186.3,
        projected_max_amount=227.7,
    )
    return coord


class TestBillingSensors:
    def test_account_balance(self):
        sensor = PGEAccountBalanceSensor(_coord(), "key")
        assert sensor.native_value == 300.13
        attrs = sensor.extra_state_attributes
        assert attrs["external_statistic_id"].endswith("account_balance")
        assert "entity_statistic_id" in attrs

    def test_current_bill_fields(self):
        coord = _coord()
        assert PGECurrentBillAmountSensor(coord, "key").native_value == 300.13
        assert PGECurrentBillKwhSensor(coord, "key").native_value == 1358.0

    def test_lifetime_and_ytd(self):
        coord = _coord()
        assert PGELifetimePaymentsSensor(coord, "key").native_value == 1200.0
        assert PGEYtdProgramSavingsSensor(coord, "key").native_value == 3.7


class TestTrackerEstimateSensors:
    def test_estimate_values(self):
        coord = _coord()
        assert PGEEstCurrentChargesSensor(coord, "key").native_value == 124.0
        assert PGEEstNextBillMinSensor(coord, "key").native_value == 186.3
        assert PGEEstNextBillMaxSensor(coord, "key").native_value == 227.7
        assert PGEBillingCycleDaySensor(coord, "key").native_value == 17
        assert PGEBillingCycleTotalDaysSensor(coord, "key").native_value == 30

    def test_estimates_hidden_until_details_available(self):
        coord = _coord()
        coord.tracker_estimates = EnergyTrackerEstimates(
            details_available=False,
            billing_cycle_day=3,
            bill_to_date_amount=12.0,
        )
        assert PGEEstCurrentChargesSensor(coord, "key").native_value is None
        assert PGEBillingCycleDaySensor(coord, "key").native_value is None

    def test_attributes_flag_source(self):
        attrs = PGEEstCurrentChargesSensor(_coord(), "key").extra_state_attributes
        assert attrs["source"] == "getEnergyTrackerData"
        assert attrs["details_available"] is True


class TestBillingBinarySensors:
    def test_autopay_paperless(self):
        coord = _coord()
        assert PGEAutopayBinarySensor(coord, "key").is_on is True
        assert PGEPaperlessBinarySensor(coord, "key").is_on is True

    def test_green_future_attrs(self):
        sensor = PGEGreenFutureBinarySensor(_coord(), "key")
        assert sensor.is_on is True
        assert sensor.extra_state_attributes["green_future_pct"] == 73.0
