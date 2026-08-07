"""Signed PGE usage → non-negative import/return/cost/compensation split."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .models import UsageInterval, UsageResolution

_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class DirectionalUsage:
    """Non-negative directional components for one energy interval."""

    consumption: Decimal
    return_kwh: Decimal
    cost: Decimal | None
    compensation: Decimal | None
    """Compensation is set only for hourly export credits; otherwise None."""


def split_signed_usage(
    kwh: Decimal,
    amount: Decimal | None,
    *,
    resolution: UsageResolution = UsageResolution.HOURLY,
) -> DirectionalUsage:
    """Split a signed PGE row into HA-compatible non-negative series values.

    HOURLY rows are signed net flow: positive ``kwh`` is grid import, negative
    ``kwh`` is grid export. Coarse DAILY/MONTHLY rows may carry a net total and
    must not fabricate gross return/compensation from that net.
    """
    if kwh > 0:
        consumption = kwh
        return_kwh = _ZERO
    elif kwh < 0:
        consumption = _ZERO
        return_kwh = -kwh if resolution == UsageResolution.HOURLY else _ZERO
    else:
        consumption = _ZERO
        return_kwh = _ZERO

    cost: Decimal | None
    compensation: Decimal | None = None
    if amount is None:
        cost = None
    else:
        cost = amount if amount > 0 else _ZERO
        if resolution == UsageResolution.HOURLY and kwh < 0 and amount < 0:
            compensation = -amount

    return DirectionalUsage(
        consumption=consumption,
        return_kwh=return_kwh,
        cost=cost,
        compensation=compensation,
    )


def energy_available(interval: UsageInterval) -> bool:
    """True when PGE published a kWh sample for this start."""
    return interval.kwh is not None


def importable_energy_intervals(intervals: list[UsageInterval]) -> list[UsageInterval]:
    """Intervals that may write energy/cost statistics (explicit null kWh omitted)."""
    return [iv for iv in intervals if iv.kwh is not None]


def explicit_gap_intervals(intervals: list[UsageInterval]) -> list[UsageInterval]:
    """Intervals PGE returned with an explicit null kWh (permanent gap markers)."""
    return [iv for iv in intervals if iv.kwh is None]
