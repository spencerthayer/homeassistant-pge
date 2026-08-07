from __future__ import annotations

from decimal import Decimal

from custom_components.pge_energy.models import UsageResolution
from custom_components.pge_energy.usage_direction import split_signed_usage


class TestSplitSignedUsage:
    def test_import_hour(self):
        split = split_signed_usage(Decimal("1.18"), Decimal("0.22"))
        assert split.consumption == Decimal("1.18")
        assert split.return_kwh == Decimal("0")
        assert split.cost == Decimal("0.22")
        assert split.compensation is None

    def test_export_hour(self):
        split = split_signed_usage(Decimal("-2.26"), Decimal("-0.42"))
        assert split.consumption == Decimal("0")
        assert split.return_kwh == Decimal("2.26")
        assert split.cost == Decimal("0")
        assert split.compensation == Decimal("0.42")

    def test_zero_kwh_fixed_charge(self):
        split = split_signed_usage(Decimal("0"), Decimal("16.60"), resolution=UsageResolution.MONTHLY)
        assert split.consumption == Decimal("0")
        assert split.return_kwh == Decimal("0")
        assert split.cost == Decimal("16.60")
        assert split.compensation is None

    def test_coarse_negative_does_not_fabricate_return(self):
        split = split_signed_usage(Decimal("-10"), Decimal("-2"), resolution=UsageResolution.DAILY)
        assert split.consumption == Decimal("0")
        assert split.return_kwh == Decimal("0")
        assert split.compensation is None

    def test_inconsistent_signs_are_not_compensation(self):
        split = split_signed_usage(Decimal("-1"), Decimal("0.20"))
        assert split.return_kwh == Decimal("1")
        assert split.cost == Decimal("0.20")
        assert split.compensation is None
