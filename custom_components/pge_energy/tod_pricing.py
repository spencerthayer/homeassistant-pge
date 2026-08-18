"""Transition coordinator + effective rate resolution for Time of Day pricing.

- :func:`resolve_tod_rates` implements the legacy rate priority:
  **manual override → last portal rates → bundled defaults** (never blank).
- :func:`resolve_tod_rates_from_catalog` uses effective-dated on-device catalogs
  for panel estimation: **manual override → effective-dated catalog → portal
  snapshot → bundled defaults**.
- :func:`resolve_basic_from_catalog` resolves the Basic comparison rate:
  **manual override → effective-dated catalog**.
- :class:`TodPricingCoordinator` recomputes the current period/rate at Pacific
  now and schedules a wake-up at the next E-TOU transition so sensors flip on
  time even between usage polls.

All rate values are USD/kWh. The portal snapshot
(:class:`~custom_components.pge_energy.billing_models.TodSnapshot`) is populated
soft-fail by ``billing_sync`` and cached on the coordinator/Store so a renew or
sync failure never blanks the sensors.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .billing_models import TodSnapshot
from .const import (
    CONF_TOD_RATE_BASIC_SERVICE,
    CONF_TOD_RATE_MID_PEAK,
    CONF_TOD_RATE_OFF_PEAK,
    CONF_TOD_RATE_ON_PEAK,
    DEFAULT_TOD_RATES,
    DOMAIN,
    E_TOU_PERIODS,
    RATE_SOURCE_DEFAULT,
    RATE_SOURCE_OVERRIDE,
    RATE_SOURCE_PORTAL,
    TodPeriod,
)
from .options import get_entry_option
from .time_util import PGE_TZ
from .tod_schedule import is_holiday, is_off_peak_day, next_transition, period_at
from .tod_tariff import (
    BasicComparisonRow,
    TodTariffRow,
    basic_comparison_rate_at,
    tod_rate_card_at,
)

if TYPE_CHECKING:
    from .coordinator import PGECoordinator

_LOGGER = logging.getLogger(__name__)

# Source label for on-device catalog rows.
RATE_SOURCE_CATALOG = "catalog"

# Period value → entry options CONF key for manual overrides.
_OVERRIDE_PERIOD_KEYS: dict[str, str] = {
    TodPeriod.OFF_PEAK.value: CONF_TOD_RATE_OFF_PEAK,
    TodPeriod.MID_PEAK.value: CONF_TOD_RATE_MID_PEAK,
    TodPeriod.ON_PEAK.value: CONF_TOD_RATE_ON_PEAK,
}


@dataclass(frozen=True, slots=True)
class TodRateCard:
    """Effective per-period rates plus the flat Basic counterfactual rate.

    ``sources`` mirrors ``rates`` per period so the panel can label each band
    (``override`` | ``catalog`` | ``portal`` | ``default``) rather than one
    global source.
    """

    rates: dict[str, float]
    sources: dict[str, str]
    basic_rate: float | None
    basic_source: str | None
    basic_effective_from: str | None = None
    basic_component_basis: str | None = None
    basic_exclusions: str | None = None
    tod_effective_from: str | None = None
    tod_component_basis: str | None = None
    tod_exclusions: str | None = None


def tod_overrides_from_entry(entry: ConfigEntry) -> dict[str, float | None]:
    """Read the four optional manual rate overrides from entry options/data.

    Returns a dict keyed by E-TOU period value plus the special key
    ``"basic_service"`` for the flat Basic override. Unset values are ``None``.
    """
    overrides: dict[str, float | None] = {}
    for period, conf_key in _OVERRIDE_PERIOD_KEYS.items():
        raw = get_entry_option(entry, conf_key, None)
        overrides[period] = float(raw) if isinstance(raw, (int, float)) and raw > 0 else None
    raw_basic = get_entry_option(entry, CONF_TOD_RATE_BASIC_SERVICE, None)
    overrides["basic_service"] = float(raw_basic) if isinstance(raw_basic, (int, float)) and raw_basic > 0 else None
    return overrides


def resolve_tod_rates(
    overrides: Mapping[str, float | None] | None,
    portal: TodSnapshot | None,
    *,
    defaults: Mapping[str, float] | None = None,
) -> TodRateCard:
    """Resolve effective rates: override beats portal beats bundled default.

    ``overrides`` is period-keyed (see :func:`tod_overrides_from_entry`);
    ``portal`` is the last-good portal snapshot (may be partial/None).
    ``basic_service`` returns None when neither override nor portal provides
    a Basic rate (the old DEFAULT_BASIC_RATE fallback is removed in v0.10.0).
    """
    overrides = overrides or {}
    base = dict(defaults or DEFAULT_TOD_RATES)
    portal_rates = portal.rates if portal is not None else {}

    rates: dict[str, float] = {}
    sources: dict[str, str] = {}
    for period in E_TOU_PERIODS:
        override = overrides.get(period)
        if isinstance(override, (int, float)) and override > 0:
            rates[period] = float(override)
            sources[period] = RATE_SOURCE_OVERRIDE
        elif period in portal_rates and isinstance(portal_rates[period], (int, float)) and portal_rates[period] > 0:
            rates[period] = float(portal_rates[period])
            sources[period] = RATE_SOURCE_PORTAL
        else:
            rates[period] = float(base.get(period, 0.0))
            sources[period] = RATE_SOURCE_DEFAULT

    basic_override = overrides.get("basic_service")
    if isinstance(basic_override, (int, float)) and basic_override > 0:
        basic_rate = float(basic_override)
        basic_source = RATE_SOURCE_OVERRIDE
    elif portal is not None and isinstance(portal.basic_rate, (int, float)) and portal.basic_rate > 0:
        basic_rate = float(portal.basic_rate)
        basic_source = RATE_SOURCE_PORTAL
    else:
        basic_rate = None
        basic_source = None

    return TodRateCard(
        rates=rates,
        sources=sources,
        basic_rate=basic_rate,
        basic_source=basic_source,
    )


def resolve_tod_rates_from_catalog(
    overrides: Mapping[str, float | None] | None,
    portal: TodSnapshot | None,
    tod_rows: list[TodTariffRow] | None,
    *,
    defaults: Mapping[str, float] | None = None,
) -> TodRateCard:
    """Resolve TOD rates using effective-dated catalogs.

    Priority: manual override → effective-dated catalog → portal snapshot
    → bundled defaults.
    """
    overrides = overrides or {}
    base = dict(defaults or DEFAULT_TOD_RATES)
    portal_rates = portal.rates if portal is not None else {}
    now = datetime.now(PGE_TZ)

    rates: dict[str, float] = {}
    sources: dict[str, str] = {}
    effective_from: str | None = None
    component_basis: str | None = None
    exclusions: str | None = None

    # Try effective-dated catalog first
    catalog_row = tod_rate_card_at(now, tod_rows) if tod_rows else None

    for period in E_TOU_PERIODS:
        override = overrides.get(period)
        if isinstance(override, (int, float)) and override > 0:
            rates[period] = float(override)
            sources[period] = RATE_SOURCE_OVERRIDE
        elif catalog_row is not None:
            catalog_rate = getattr(catalog_row, period, None)
            if catalog_rate is not None and isinstance(catalog_rate, (int, float)) and catalog_rate > 0:
                rates[period] = float(catalog_rate)
                sources[period] = RATE_SOURCE_CATALOG
                effective_from = catalog_row.effective_from
                component_basis = catalog_row.component_basis
                exclusions = catalog_row.exclusions
            elif period in portal_rates and isinstance(portal_rates[period], (int, float)) and portal_rates[period] > 0:
                rates[period] = float(portal_rates[period])
                sources[period] = RATE_SOURCE_PORTAL
            else:
                rates[period] = float(base.get(period, 0.0))
                sources[period] = RATE_SOURCE_DEFAULT
        elif period in portal_rates and isinstance(portal_rates[period], (int, float)) and portal_rates[period] > 0:
            rates[period] = float(portal_rates[period])
            sources[period] = RATE_SOURCE_PORTAL
        else:
            rates[period] = float(base.get(period, 0.0))
            sources[period] = RATE_SOURCE_DEFAULT

    return TodRateCard(
        rates=rates,
        sources=sources,
        basic_rate=None,  # resolved separately
        basic_source=None,
        tod_effective_from=effective_from,
        tod_component_basis=component_basis,
        tod_exclusions=exclusions,
    )


def resolve_basic_from_catalog(
    overrides: Mapping[str, float | None] | None,
    basic_rows: list[BasicComparisonRow] | None,
) -> tuple[float | None, str | None, str | None, str | None, str | None]:
    """Resolve the Basic comparison rate from catalog.

    Priority: manual override → effective-dated catalog.

    Returns (rate, source, effective_from, component_basis, exclusions).
    """
    overrides = overrides or {}
    basic_override = overrides.get("basic_service")
    if isinstance(basic_override, (int, float)) and basic_override > 0:
        return float(basic_override), RATE_SOURCE_OVERRIDE, None, None, None

    now = datetime.now(PGE_TZ)
    row = basic_comparison_rate_at(now, basic_rows) if basic_rows else None
    if row is not None:
        return (
            row.rate,
            RATE_SOURCE_CATALOG,
            row.effective_from,
            row.component_basis,
            row.exclusions,
        )

    return None, None, None, None, None


def tod_snapshot_to_dict(snapshot: TodSnapshot | None) -> dict[str, Any] | None:
    """Serialize a TodSnapshot for the import Store (JSON-safe)."""
    if snapshot is None:
        return None
    return {
        "rates": dict(snapshot.rates),
        "basic_rate": snapshot.basic_rate,
        "savings_total": snapshot.savings_total,
        "fetched_at": snapshot.fetched_at.isoformat() if snapshot.fetched_at else None,
        "attributes": dict(snapshot.attributes),
    }


def tod_snapshot_from_dict(data: dict[str, Any] | None) -> TodSnapshot | None:
    """Rebuild a TodSnapshot from Store dict; malformed data → None."""
    if not isinstance(data, dict):
        return None
    fetched_raw = data.get("fetched_at")
    fetched_at: datetime | None = None
    if isinstance(fetched_raw, str):
        try:
            fetched_at = datetime.fromisoformat(fetched_raw.replace("Z", "+00:00"))
        except ValueError:
            fetched_at = None
    rates = data.get("rates") or {}
    if not isinstance(rates, dict):
        rates = {}
    if not rates and data.get("basic_rate") is None and data.get("savings_total") is None:
        return None
    try:
        return TodSnapshot(
            rates={str(k): float(v) for k, v in rates.items() if isinstance(v, (int, float))},
            basic_rate=(float(data["basic_rate"]) if data.get("basic_rate") is not None else None),
            savings_total=(float(data["savings_total"]) if data.get("savings_total") is not None else None),
            fetched_at=fetched_at,
            attributes=dict(data.get("attributes") or {}),
        )
    except (TypeError, ValueError):
        return None


class TodPricingCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Recompute E-TOU period/rates at Pacific now and at each transition.

    Sensors attach to the account :class:`PGECoordinator`; this coordinator
    pushes a transition wake-up to it so period/price flip without waiting for
    the next usage poll. Soft-fail: any refresh error keeps last-known state.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        parent: PGECoordinator,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} TOD",
            update_interval=None,
        )
        self._entry = entry
        self._parent = parent
        self._transition_timer: asyncio.TimerHandle | None = None
        self._period: TodPeriod = TodPeriod.OFF_PEAK
        self._next_transition_at: datetime | None = None
        self._rate_card = resolve_tod_rates(None, None)
        self._is_holiday = False
        self._is_weekend = False

    # -- public state -----------------------------------------------------

    @property
    def period(self) -> TodPeriod:
        return self._period

    @property
    def is_holiday(self) -> bool:
        return self._is_holiday

    @property
    def is_weekend(self) -> bool:
        return self._is_weekend

    @property
    def next_transition_at(self) -> datetime | None:
        return self._next_transition_at

    @property
    def rate_card(self) -> TodRateCard:
        return self._rate_card

    @property
    def current_rate(self) -> float:
        return float(self._rate_card.rates.get(self._period.value, 0.0))

    @property
    def current_rate_source(self) -> str:
        return self._rate_card.sources.get(self._period.value, RATE_SOURCE_DEFAULT)

    @property
    def tod_snapshot(self) -> TodSnapshot | None:
        return self._parent.tod_snapshot

    # -- coordinator lifecycle --------------------------------------------

    async def async_start(self) -> None:
        """Initial refresh; also scheduled by the account coordinator."""
        await self.async_refresh()

    async def async_stop(self) -> None:
        if self._transition_timer is not None:
            self._transition_timer.cancel()
            self._transition_timer = None

    async def _async_update_data(self) -> dict[str, Any]:
        now = datetime.now(PGE_TZ)
        day = now.date()
        period = period_at(day, now.time())
        _next, transition_at = next_transition(now)
        self._period = period
        self._next_transition_at = transition_at
        self._is_holiday = is_holiday(day)
        self._is_weekend = is_off_peak_day(day) and day.weekday() >= 5
        self._rate_card = resolve_tod_rates(tod_overrides_from_entry(self._entry), self.tod_snapshot)
        self._schedule_transition()
        self._parent.async_update_listeners()
        return {
            "period": period.value,
            "next_transition_at": transition_at.isoformat() if transition_at else None,
            "rates": self._rate_card.rates,
            "sources": self._rate_card.sources,
            "rate_source": self.current_rate_source,
        }

    def _schedule_transition(self) -> None:
        if self._transition_timer is not None:
            self._transition_timer.cancel()
            self._transition_timer = None
        if self._next_transition_at is None:
            return
        delay = max(0.0, (self._next_transition_at - datetime.now(PGE_TZ)).total_seconds())
        if delay > 0:
            self._transition_timer = self.hass.loop.call_later(delay, self._on_transition)
            return
        # Missed-fire recovery: past due, refresh immediately.
        self.hass.async_create_task(self.async_refresh())

    def _on_transition(self) -> None:
        self._transition_timer = None
        self.hass.async_create_task(self.async_refresh())
