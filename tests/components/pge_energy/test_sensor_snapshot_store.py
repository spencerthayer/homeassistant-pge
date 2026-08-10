"""Round-trip Store serialization for cold-boot sensor soft-fail snapshots."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from custom_components.pge_energy.billing_models import (
    AccountSnapshot,
    BillDetails,
    EnergyTrackerEstimates,
    ProgramEnrollment,
    ProgramsSnapshot,
)
from custom_components.pge_energy.models import (
    UsageInterval,
    UsageResolution,
    tip_intervals_from_store,
    tip_intervals_to_store,
    usage_interval_from_dict,
)
from custom_components.pge_energy.store import ImportStoreData


def test_account_snapshot_store_omits_encrypted_ids():
    snap = AccountSnapshot(
        account_number="123",
        amount_due=10.0,
        encrypted_account_number="enc-a",
        encrypted_person_id="enc-p",
        bill=BillDetails(amount_due=10.0, encrypted_bill_id="enc-b"),
    )
    raw = snap.to_dict()
    assert "encrypted_account_number" not in raw
    assert raw["bill"]["encrypted_bill_id"] is None
    restored = AccountSnapshot.from_dict(raw)
    assert restored is not None
    assert restored.amount_due == 10.0
    assert restored.encrypted_account_number is None
    assert restored.bill is not None
    assert restored.bill.encrypted_bill_id is None


def test_programs_and_tracker_round_trip():
    programs = ProgramsSnapshot(
        peak_time_rebates_enrolled=True,
        smart_charging_enrolled=False,
        energy_shifting=[ProgramEnrollment(program_name="Time of Day", is_enrolled=True, is_eligible=True)],
    )
    tracker = EnergyTrackerEstimates(
        details_available=True,
        billing_cycle_day=4,
        billing_cycle_total_days=29,
        bill_to_date_amount=41.0,
    )
    store = ImportStoreData(
        account_key="k",
        programs_snapshot=programs.to_dict(),
        tracker_estimates=tracker.to_dict(),
    )
    loaded = ImportStoreData.from_dict(store.to_dict())
    assert ProgramsSnapshot.from_dict(loaded.programs_snapshot).peak_time_rebates_enrolled is True
    assert EnergyTrackerEstimates.from_dict(loaded.tracker_estimates).bill_to_date_amount == 41.0


def test_tip_intervals_round_trip_and_cap():
    start = datetime(2026, 8, 9, 7, 0, tzinfo=UTC)
    intervals = [
        UsageInterval(
            account_key="k",
            resolution=UsageResolution.HOURLY,
            start=start + timedelta(hours=i),
            end=start + timedelta(hours=i + 1),
            kwh=Decimal("1.25") if i % 2 == 0 else None,
            amount=Decimal("0.2"),
            temperature=Decimal("70"),
            usage_status="kWh-Delivered",
            interval_size=60,
            source_timestamp=None,
        )
        for i in range(10)
    ]
    raw = tip_intervals_to_store(intervals)
    restored = tip_intervals_from_store(raw)
    assert len(restored) == 10
    assert restored[0].kwh == Decimal("1.25")
    assert restored[1].kwh is None

    huge = intervals * 30
    capped = tip_intervals_to_store(huge)
    assert len(capped) == 240


def test_usage_interval_from_dict_rejects_bad_interval_size():
    start = datetime(2026, 8, 9, 7, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)
    good = {
        "account_key": "k",
        "resolution": "HOURLY",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "kwh": "1.0",
        "interval_size": 60,
    }
    assert usage_interval_from_dict(good) is not None
    assert usage_interval_from_dict({**good, "interval_size": "not-an-int"}) is None
    assert usage_interval_from_dict({**good, "interval_size": {"bad": True}}) is None
