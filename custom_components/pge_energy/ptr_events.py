"""Peak Time Rebate event coordinator — manual schedule + GraphQL detection.

PGE announces PTR events the day before via email/text; there is no public
upcoming-event API. This module gives HA a ``ptr_event_active`` binary sensor
that flips at user-entered Pacific start/end times (from the day-before
notice), plus a one-shot ``ptr_event_detected`` when GraphQL gains a new
historical ``eventDate``.

The coordinator mirrors :class:`TodPricingCoordinator`: ``update_interval=None``
with ``async_track_point_in_utc_time`` at the window's UTC instants so sensors
flip between 4-hour polls. Wall-clock delays are wrong across a Pacific
daylight-saving change.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .alerts import async_fire_pge_alert
from .const import (
    ALERT_PTR_EVENT_ACTIVE,
    ALERT_PTR_EVENT_DETECTED,
    ALERT_PTR_EVENT_ENDED,
    ALERT_PTR_EVENT_STARTING,
    DOMAIN,
    PTR_EVENT_MAX_DURATION_HOURS,
    PTR_EVENT_MAX_PAST_DAYS,
    PTR_EVENT_MIN_DURATION_HOURS,
    PTR_EVENT_STARTING_WARN_MINUTES,
)
from .time_util import PGE_TZ

if TYPE_CHECKING:
    from .coordinator import PGECoordinator

_LOGGER = logging.getLogger(__name__)


def _parse_iso(value: str) -> datetime | None:
    """Parse an ISO datetime string; return None on failure."""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=PGE_TZ)
        return dt.astimezone(PGE_TZ)
    except (ValueError, TypeError):
        return None


def validate_ptr_event_window(
    start_raw: str,
    end_raw: str,
    *,
    now: datetime | None = None,
) -> tuple[datetime, datetime] | tuple[None, None]:
    """Validate a PTR event window from ISO strings.

    Returns ``(start, end)`` on success, ``(None, None)`` on failure.
    Rules:
    - Both must parse as timezone-aware datetimes.
    - end > start.
    - Duration between 1 and 8 hours.
    - Start not more than 7 days in the past.
    """
    start = _parse_iso(start_raw)
    end = _parse_iso(end_raw)
    if start is None or end is None:
        return (None, None)
    if end <= start:
        return (None, None)
    duration = (end - start).total_seconds() / 3600.0
    if duration < PTR_EVENT_MIN_DURATION_HOURS or duration > PTR_EVENT_MAX_DURATION_HOURS:
        return (None, None)
    if now is None:
        now = datetime.now(PGE_TZ)
    if start < now - timedelta(days=PTR_EVENT_MAX_PAST_DAYS):
        return (None, None)
    return (start, end)


def ptr_wake_instants(
    now: datetime,
    start: datetime,
    end: datetime,
    *,
    warn_minutes: int,
) -> tuple[datetime | None, datetime | None, datetime | None]:
    """UTC instants for event start, the starting-soon warning, and event end.

    Each value is ``None`` when that instant is already in the past. The
    instants are absolute UTC so a daylight-saving fold does not shorten the
    delay by an hour.
    """
    now_utc = now.astimezone(UTC)
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    start_at = start_utc if now_utc < start_utc else None
    warn_at = start_utc - timedelta(minutes=warn_minutes)
    warn = warn_at if now_utc < warn_at else None
    end_at = end_utc if now_utc < end_utc else None
    return start_at, warn, end_at


def diff_new_ptr_event_dates(seen: list[str], events: list[dict]) -> list[str]:
    """Return event dates in ``events`` not present in ``seen``.

    ``events`` entries must already be normalized with ``event_date`` keys.
    """
    current = {e["event_date"] for e in events if isinstance(e, dict) and e.get("event_date")}
    return sorted(current - set(seen))


class PtrEventCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Manage a single manual PTR window + detection state.

    Sensors attach to the account :class:`PGECoordinator`; this coordinator
    pushes window-boundary wake-ups to it so ``ptr_event_active`` flips
    without waiting for the next usage poll. Soft-fail: any refresh error
    keeps last-known state.
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
            name=f"{DOMAIN} PTR events",
            update_interval=None,
        )
        self._entry = entry
        self._parent = parent
        self._start_timer: Callable[[], None] | None = None
        self._end_timer: Callable[[], None] | None = None
        self._starting_warn_timer: Callable[[], None] | None = None

    @property
    def scheduled_event(self) -> dict[str, Any] | None:
        return self._parent.import_store.ptr_scheduled_event

    @property
    def detected_event(self) -> dict[str, Any] | None:
        return self._parent.import_store.ptr_detected_event

    @property
    def event_active(self) -> bool:
        """True when now is inside the scheduled window."""
        event = self.scheduled_event
        if not event:
            return False
        now = datetime.now(PGE_TZ)
        start = _parse_iso(str(event.get("start", "")))
        end = _parse_iso(str(event.get("end", "")))
        if start is None or end is None:
            return False
        return start <= now < end

    @property
    def event_detected(self) -> bool:
        """True when a new event date has been detected but not acknowledged."""
        return self.detected_event is not None

    async def async_start(self) -> None:
        """Initial refresh; rehydrate timers on restart."""
        await self.async_refresh()

    async def async_stop(self) -> None:
        self._cancel_wake_timers()

    async def _async_update_data(self) -> dict[str, Any]:
        self._reschedule_timers()
        self._parent.async_update_listeners()
        return {
            "event_active": self.event_active,
            "event_detected": self.event_detected,
        }

    def _reschedule_timers(self) -> None:
        self._cancel_wake_timers()
        event = self.scheduled_event
        if not event:
            return
        now = datetime.now(PGE_TZ)
        start = _parse_iso(str(event.get("start", "")))
        end = _parse_iso(str(event.get("end", "")))
        if start is None or end is None:
            return
        start_at, warn_at, end_at = ptr_wake_instants(
            now,
            start,
            end,
            warn_minutes=PTR_EVENT_STARTING_WARN_MINUTES,
        )
        if start_at is not None:
            self._start_timer = async_track_point_in_utc_time(self.hass, self._on_start, start_at)
        if warn_at is not None:
            self._starting_warn_timer = async_track_point_in_utc_time(self.hass, self._on_starting_warn, warn_at)
        if end_at is not None:
            self._end_timer = async_track_point_in_utc_time(self.hass, self._on_end, end_at)

    def _cancel_wake_timers(self) -> None:
        for timer_attr in ("_start_timer", "_end_timer", "_starting_warn_timer"):
            timer = getattr(self, timer_attr)
            if timer is None:
                continue
            timer()
            setattr(self, timer_attr, None)

    def _on_start(self, _now: datetime) -> None:
        self._start_timer = None
        event = self.scheduled_event
        if event:
            async_fire_pge_alert(
                self.hass,
                ALERT_PTR_EVENT_ACTIVE,
                entry_id=self._entry.entry_id,
                account_key=self._parent.account_key,
                source="manual",
                label=event.get("label", ""),
                start=event.get("start", ""),
                end=event.get("end", ""),
            )
        self.hass.async_create_task(self.async_refresh())

    def _on_starting_warn(self, _now: datetime) -> None:
        self._starting_warn_timer = None
        event = self.scheduled_event
        if event:
            async_fire_pge_alert(
                self.hass,
                ALERT_PTR_EVENT_STARTING,
                entry_id=self._entry.entry_id,
                account_key=self._parent.account_key,
                source="manual",
                label=event.get("label", ""),
                start=event.get("start", ""),
                end=event.get("end", ""),
            )

    def _on_end(self, _now: datetime) -> None:
        self._end_timer = None
        event = self.scheduled_event
        if event:
            async_fire_pge_alert(
                self.hass,
                ALERT_PTR_EVENT_ENDED,
                entry_id=self._entry.entry_id,
                account_key=self._parent.account_key,
                source="manual",
                label=event.get("label", ""),
                start=event.get("start", ""),
                end=event.get("end", ""),
            )
        self.hass.async_create_task(self.async_refresh())

    # -- detection (called by billing_sync after programs persist) -----------

    async def async_check_detection(self, events: list[dict]) -> None:
        """Diff GraphQL events against seen dates; set detected state if new.

        The first call seeds ``ptr_seen_event_dates`` without an alert, including
        when that call's event list is empty. Later new dates alert once.
        Every newly observed date is marked seen when the newest is recorded,
        so unacknowledged syncs do not rediscover the same dates.
        """
        store = self._parent.import_store
        if not store.ptr_detection_initialized:
            store.ptr_seen_event_dates = sorted(
                e["event_date"] for e in events if isinstance(e, dict) and e.get("event_date")
            )
            store.ptr_detection_initialized = True
            await self._parent.async_persist_sensor_snapshots()
            return
        seen = list(store.ptr_seen_event_dates)
        new_dates = diff_new_ptr_event_dates(seen, events)
        if not new_dates:
            return
        newest = new_dates[-1]
        credit = None
        for e in events:
            if isinstance(e, dict) and e.get("event_date") == newest:
                credit = e.get("event_earned_credit")
                break
        store.ptr_seen_event_dates = sorted(set(seen).union(new_dates))
        store.ptr_detected_event = {
            "event_date": newest,
            "event_earned_credit": credit,
            "acked": False,
        }
        await self._parent.async_persist_sensor_snapshots()
        async_fire_pge_alert(
            self.hass,
            ALERT_PTR_EVENT_DETECTED,
            entry_id=self._entry.entry_id,
            account_key=self._parent.account_key,
            source="graphql",
            event_date=newest,
            event_earned_credit=credit,
        )
        await self.async_refresh()

    async def async_acknowledge_detection(self) -> None:
        """Copy the detected event date into seen dates and clear detection."""
        store = self._parent.import_store
        detected = store.ptr_detected_event
        if not detected:
            return
        event_date = str(detected.get("event_date", ""))
        if event_date and event_date not in store.ptr_seen_event_dates:
            store.ptr_seen_event_dates = sorted([*store.ptr_seen_event_dates, event_date])
        store.ptr_detected_event = None
        await self._parent.async_persist_sensor_snapshots()
        await self.async_refresh()
