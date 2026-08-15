"""Unit tests for billing sensors and binary sensors."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from custom_components.pge_energy.billing_models import (
    AccountSnapshot,
    BillDetails,
    EnergyTrackerEstimates,
    NetMeteringSnapshot,
    ProgramsSnapshot,
    RateCompareSnapshot,
    TodSnapshot,
)
from custom_components.pge_energy.binary_sensor import (
    PGEAutopayBinarySensor,
    PGEGreenFutureBinarySensor,
    PGEPaperlessBinarySensor,
    PGEPeakTimeRebatesBinarySensor,
    PGESmartBatteryBinarySensor,
    PGESmartChargingBinarySensor,
    PGETimeOfDayBinarySensor,
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
    PGENetMeteringSensor,
    PGENextPtrEventDateSensor,
    PGETodVsBasicSavingsSensor,
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

    def test_smart_charging_and_battery(self):
        coord = _coord()
        coord.programs_snapshot = ProgramsSnapshot(
            smart_charging_enrolled=True,
            smart_charging_eligible=True,
            smart_battery_enrolled=False,
            smart_battery_eligible=True,
            attributes={
                "smart_charging_detail": {"vehicles": 1},
                "smart_battery_detail": {"capacity_kwh": 13.5},
            },
        )
        charging = PGESmartChargingBinarySensor(coord, "key")
        assert charging.is_on is True
        assert charging.extra_state_attributes["is_eligible"] is True
        assert charging.extra_state_attributes["smart_charging_detail"] == {"vehicles": 1}
        battery = PGESmartBatteryBinarySensor(coord, "key")
        assert battery.is_on is False
        assert battery.extra_state_attributes["is_eligible"] is True
        assert battery.extra_state_attributes["smart_battery_detail"] == {"capacity_kwh": 13.5}

    def test_ptr_and_tod_detail_attrs(self):
        coord = _coord()
        coord.programs_snapshot = ProgramsSnapshot(
            peak_time_rebates_enrolled=True,
            time_of_day_enrolled=True,
            attributes={
                "peak_time_rebate": {
                    "peak_time_events": [{"event_date": "2099-01-15"}],
                    "activePTRSeason": "summer",
                },
                "tod_enrollment_detail": {
                    "planSavings": 42.5,
                    "onPeakCharges": 10.0,
                },
            },
        )
        ptr = PGEPeakTimeRebatesBinarySensor(coord, "key")
        assert ptr.is_on is True
        assert ptr.extra_state_attributes["peak_time_events"] == [{"event_date": "2099-01-15"}]
        assert ptr.extra_state_attributes["activePTRSeason"] == "summer"
        tod = PGETimeOfDayBinarySensor(coord, "key")
        assert tod.is_on is True
        assert tod.extra_state_attributes["planSavings"] == 42.5
        assert tod.extra_state_attributes["onPeakCharges"] == 10.0


def _freeze_pacific_now(monkeypatch, when: datetime) -> None:
    import custom_components.pge_energy.sensor as sensor_mod

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return when.replace(tzinfo=None)
            return when.astimezone(tz)

    monkeypatch.setattr(sensor_mod, "datetime", _FixedDateTime)


class TestPtrAndNetMeteringSensors:
    def test_next_ptr_event_date_skips_past(self, monkeypatch):
        _freeze_pacific_now(
            monkeypatch,
            datetime(2026, 8, 10, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
        )
        coord = _coord()
        coord.programs_snapshot = ProgramsSnapshot(
            attributes={
                "peak_time_rebate": {
                    "peak_time_events": [
                        {"event_date": "2026-08-01"},
                        {"event_date": "2026-08-15"},
                    ]
                }
            }
        )
        assert PGENextPtrEventDateSensor(coord, "key").native_value == date(2026, 8, 15)

    def test_next_ptr_event_date_none_when_all_past(self, monkeypatch):
        _freeze_pacific_now(
            monkeypatch,
            datetime(2026, 8, 10, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
        )
        coord = _coord()
        coord.programs_snapshot = ProgramsSnapshot(
            attributes={"peak_time_rebate": {"peak_time_events": [{"event_date": "2026-08-01"}]}}
        )
        assert PGENextPtrEventDateSensor(coord, "key").native_value is None

    def test_net_metering_enrolled_state_and_attrs(self):
        coord = _coord()
        coord.net_metering_snapshot = NetMeteringSnapshot(
            fetched_at=datetime(2026, 8, 10, 16, tzinfo=UTC),
            attributes={"isEnrolled": True, "creditBalance": "12.5"},
        )
        sensor = PGENetMeteringSensor(coord, "key")
        assert sensor.native_value == "enrolled"
        attrs = sensor.extra_state_attributes
        assert attrs["isEnrolled"] is True
        assert attrs["creditBalance"] == "12.5"
        assert attrs["fetched_at"].startswith("2026-08-10")


class TestTodVsBasicSavingsSensor:
    def test_prefers_legacy_snapshot_savings_total(self):
        coord = _coord()
        coord.tod.tod_snapshot = TodSnapshot(savings_total=12.5)
        coord.rate_compare_snapshot = RateCompareSnapshot(attributes={"savings": 25.0})
        assert PGETodVsBasicSavingsSensor(coord, "key").native_value == 12.5

    def test_falls_back_to_rate_compare_savings(self):
        coord = _coord()
        coord.tod.tod_snapshot = None
        coord.rate_compare_snapshot = RateCompareSnapshot(
            fetched_at=datetime(2026, 8, 10, 16, tzinfo=UTC),
            attributes={
                "savings": 25.0,
                "touTotal": 150.0,
                "basicTotal": 175.0,
                "comparisonPeriod": "2026-01 to 2026-07",
            },
        )
        sensor = PGETodVsBasicSavingsSensor(coord, "key")
        assert sensor.native_value == 25.0
        attrs = sensor.extra_state_attributes
        assert attrs["rate_compare_savings"] == 25.0
        assert attrs["rate_compare_tou_total"] == 150.0
        assert attrs["rate_compare_basic_total"] == 175.0
        assert attrs["rate_compare_period"] == "2026-01 to 2026-07"
        assert attrs["rate_compare_fetched_at"].startswith("2026-08-10")
        assert sensor.native_unit_of_measurement == "USD"
        assert sensor.state_class is None

    def test_no_portal_data_returns_none(self):
        coord = _coord()
        coord.tod.tod_snapshot = None
        coord.rate_compare_snapshot = None
        assert PGETodVsBasicSavingsSensor(coord, "key").native_value is None

    def test_empty_rate_compare_snapshot_returns_none(self):
        coord = _coord()
        coord.tod.tod_snapshot = None
        coord.rate_compare_snapshot = RateCompareSnapshot()
        assert PGETodVsBasicSavingsSensor(coord, "key").native_value is None

    def test_program_eligibility_attrs(self):
        coord = _coord()
        coord.programs_snapshot = ProgramsSnapshot(
            peak_time_rebates_enrolled=False,
            peak_time_rebates_eligible=True,
            green_future_enrolled=False,
            green_future_eligible=True,
            time_of_day_enrolled=False,
            time_of_day_eligible=True,
            smart_thermostat_enrolled=False,
            smart_thermostat_eligible=False,
            habitat_support_enrolled=False,
            habitat_support_eligible=None,
        )
        assert PGEPeakTimeRebatesBinarySensor(coord, "key").extra_state_attributes["is_eligible"] is True
        assert PGEGreenFutureBinarySensor(coord, "key").extra_state_attributes["is_eligible"] is True
        assert PGETimeOfDayBinarySensor(coord, "key").extra_state_attributes["is_eligible"] is True
        from custom_components.pge_energy.binary_sensor import (
            PGEHabitatSupportBinarySensor,
            PGESmartThermostatBinarySensor,
        )

        thermostat = PGESmartThermostatBinarySensor(coord, "key")
        assert thermostat.extra_state_attributes["is_eligible"] is False
        habitat = PGEHabitatSupportBinarySensor(coord, "key")
        assert "is_eligible" not in habitat.extra_state_attributes
