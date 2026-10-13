"""Unit tests for PTR event coordinator, validation, and detection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.pge_energy.const import ALERT_PTR_EVENT_ACTIVE, ALERT_PTR_EVENT_DETECTED
from custom_components.pge_energy.ptr_events import (
    PtrEventCoordinator,
    diff_new_ptr_event_dates,
    ptr_wake_instants,
    validate_ptr_event_window,
)
from custom_components.pge_energy.time_util import PGE_TZ


def _make_coordinator() -> PtrEventCoordinator:
    hass = MagicMock()
    hass.loop = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_entry"
    parent = MagicMock()
    parent.account_key = "test_account"
    parent.import_store.ptr_scheduled_event = None
    parent.import_store.ptr_seen_event_dates = []
    parent.import_store.ptr_detected_event = None
    parent.import_store.ptr_detection_initialized = False
    parent.async_persist_sensor_snapshots = AsyncMock()
    parent.async_update_listeners = MagicMock()
    return PtrEventCoordinator(hass, entry, parent)


class TestValidatePtrEventWindow:
    def test_valid_window(self):
        now = datetime(2026, 8, 19, 12, 0, tzinfo=PGE_TZ)
        start = "2026-08-19T17:00:00-07:00"
        end = "2026-08-19T21:00:00-07:00"
        s, e = validate_ptr_event_window(start, end, now=now)
        assert s is not None
        assert e is not None
        assert e > s

    def test_fall_back_one_hour_window_is_accepted(self):
        now = datetime(2026, 11, 1, 0, 30, tzinfo=PGE_TZ)
        start, end = validate_ptr_event_window(
            "2026-11-01T01:30:00-07:00",
            "2026-11-01T01:30:00-08:00",
            now=now,
        )
        assert start is not None
        assert end is not None

    def test_fall_back_sub_hour_window_is_rejected(self):
        now = datetime(2026, 11, 1, 0, 30, tzinfo=PGE_TZ)
        start, end = validate_ptr_event_window(
            "2026-11-01T01:45:00-07:00",
            "2026-11-01T01:30:00-08:00",
            now=now,
        )
        assert start is None
        assert end is None

    def test_end_before_start(self):
        now = datetime(2026, 8, 19, 12, 0, tzinfo=PGE_TZ)
        start = "2026-08-19T21:00:00-07:00"
        end = "2026-08-19T17:00:00-07:00"
        s, e = validate_ptr_event_window(start, end, now=now)
        assert s is None
        assert e is None

    def test_too_short(self):
        now = datetime(2026, 8, 19, 12, 0, tzinfo=PGE_TZ)
        start = "2026-08-19T17:00:00-07:00"
        end = "2026-08-19T17:30:00-07:00"
        s, e = validate_ptr_event_window(start, end, now=now)
        assert s is None
        assert e is None

    def test_too_long(self):
        now = datetime(2026, 8, 19, 12, 0, tzinfo=PGE_TZ)
        start = "2026-08-19T17:00:00-07:00"
        end = "2026-08-20T02:00:00-07:00"
        s, e = validate_ptr_event_window(start, end, now=now)
        assert s is None
        assert e is None

    def test_too_far_in_past(self):
        now = datetime(2026, 8, 19, 12, 0, tzinfo=PGE_TZ)
        start = "2026-08-10T17:00:00-07:00"
        end = "2026-08-10T21:00:00-07:00"
        s, e = validate_ptr_event_window(start, end, now=now)
        assert s is None
        assert e is None

    def test_naive_datetime_assumes_pacific(self):
        now = datetime(2026, 8, 19, 12, 0, tzinfo=PGE_TZ)
        start = "2026-08-19T17:00:00"
        end = "2026-08-19T21:00:00"
        s, e = validate_ptr_event_window(start, end, now=now)
        assert s is not None
        assert e is not None


class TestDiffNewPtrEventDates:
    def test_new_date_detected(self):
        seen = ["2026-08-05"]
        events = [
            {"event_date": "2026-08-05", "event_earned_credit": 5.0},
            {"event_date": "2026-08-18", "event_earned_credit": 12.0},
        ]
        result = diff_new_ptr_event_dates(seen, events)
        assert result == ["2026-08-18"]

    def test_no_new_dates(self):
        seen = ["2026-08-05", "2026-08-18"]
        events = [
            {"event_date": "2026-08-05", "event_earned_credit": 5.0},
            {"event_date": "2026-08-18", "event_earned_credit": 12.0},
        ]
        result = diff_new_ptr_event_dates(seen, events)
        assert result == []

    def test_empty_seen_returns_all(self):
        seen = []
        events = [{"event_date": "2026-08-05", "event_earned_credit": 5.0}]
        result = diff_new_ptr_event_dates(seen, events)
        assert result == ["2026-08-05"]


class TestPtrEventCoordinator:
    @pytest.mark.asyncio
    async def test_event_active_inside_window(self):
        coord = _make_coordinator()
        now = datetime.now(PGE_TZ)
        coord._parent.import_store.ptr_scheduled_event = {
            "start": (now - timedelta(hours=1)).isoformat(),
            "end": (now + timedelta(hours=1)).isoformat(),
            "label": "Test",
        }
        assert coord.event_active is True

    @pytest.mark.asyncio
    async def test_event_active_outside_window(self):
        coord = _make_coordinator()
        now = datetime.now(PGE_TZ)
        coord._parent.import_store.ptr_scheduled_event = {
            "start": (now + timedelta(hours=2)).isoformat(),
            "end": (now + timedelta(hours=4)).isoformat(),
            "label": "Test",
        }
        assert coord.event_active is False

    @pytest.mark.asyncio
    async def test_event_active_no_window(self):
        coord = _make_coordinator()
        assert coord.event_active is False

    @pytest.mark.asyncio
    async def test_event_detected_true(self):
        coord = _make_coordinator()
        coord._parent.import_store.ptr_detected_event = {
            "event_date": "2026-08-18",
            "event_earned_credit": 12.0,
            "acked": False,
        }
        assert coord.event_detected is True

    @pytest.mark.asyncio
    async def test_event_detected_false(self):
        coord = _make_coordinator()
        assert coord.event_detected is False

    @pytest.mark.asyncio
    async def test_detection_seeds_on_first_boot(self):
        coord = _make_coordinator()
        events = [{"event_date": "2026-08-05", "event_earned_credit": 5.0}]
        await coord.async_check_detection(events)
        assert coord._parent.import_store.ptr_seen_event_dates == ["2026-08-05"]
        assert coord._parent.import_store.ptr_detected_event is None
        assert coord._parent.import_store.ptr_detection_initialized is True
        coord._parent.async_persist_sensor_snapshots.assert_called_once()

    @pytest.mark.asyncio
    async def test_detection_fires_on_new_date(self):
        coord = _make_coordinator()
        coord._parent.import_store.ptr_detection_initialized = True
        coord._parent.import_store.ptr_seen_event_dates = ["2026-08-05"]
        events = [
            {"event_date": "2026-08-05", "event_earned_credit": 5.0},
            {"event_date": "2026-08-18", "event_earned_credit": 12.0},
        ]
        with patch("custom_components.pge_energy.ptr_events.async_fire_pge_alert") as mock_alert:
            await coord.async_check_detection(events)
        assert coord._parent.import_store.ptr_detected_event is not None
        assert coord._parent.import_store.ptr_detected_event["event_date"] == "2026-08-18"
        assert coord._parent.import_store.ptr_seen_event_dates == ["2026-08-05", "2026-08-18"]
        mock_alert.assert_called_once()
        call_kwargs = mock_alert.call_args
        assert call_kwargs[0][1] == ALERT_PTR_EVENT_DETECTED

    @pytest.mark.asyncio
    async def test_detection_no_new_dates(self):
        coord = _make_coordinator()
        coord._parent.import_store.ptr_detection_initialized = True
        coord._parent.import_store.ptr_seen_event_dates = ["2026-08-05", "2026-08-18"]
        events = [
            {"event_date": "2026-08-05", "event_earned_credit": 5.0},
            {"event_date": "2026-08-18", "event_earned_credit": 12.0},
        ]
        with patch("custom_components.pge_energy.ptr_events.async_fire_pge_alert") as mock_alert:
            await coord.async_check_detection(events)
        assert coord._parent.import_store.ptr_detected_event is None
        mock_alert.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_baseline_does_not_mute_the_next_event(self):
        coord = _make_coordinator()
        with patch("custom_components.pge_energy.ptr_events.async_fire_pge_alert") as mock_alert:
            await coord.async_check_detection([])
            assert coord._parent.import_store.ptr_detection_initialized is True
            assert coord._parent.import_store.ptr_seen_event_dates == []
            mock_alert.assert_not_called()
            await coord.async_check_detection([{"event_date": "2026-08-18", "event_earned_credit": 12.0}])
        assert coord._parent.import_store.ptr_detected_event["event_date"] == "2026-08-18"
        mock_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_detection_marks_every_new_date_seen(self):
        coord = _make_coordinator()
        coord._parent.import_store.ptr_detection_initialized = True
        coord._parent.import_store.ptr_seen_event_dates = ["2026-08-05"]
        events = [
            {"event_date": "2026-08-05", "event_earned_credit": 5.0},
            {"event_date": "2026-08-12", "event_earned_credit": 8.0},
            {"event_date": "2026-08-18", "event_earned_credit": 12.0},
        ]
        with patch("custom_components.pge_energy.ptr_events.async_fire_pge_alert") as mock_alert:
            await coord.async_check_detection(events)
            await coord.async_check_detection(events)
        assert coord._parent.import_store.ptr_seen_event_dates == [
            "2026-08-05",
            "2026-08-12",
            "2026-08-18",
        ]
        assert coord._parent.import_store.ptr_detected_event["event_date"] == "2026-08-18"
        mock_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_acknowledge_detection(self):
        coord = _make_coordinator()
        coord._parent.import_store.ptr_seen_event_dates = ["2026-08-05"]
        coord._parent.import_store.ptr_detected_event = {
            "event_date": "2026-08-18",
            "event_earned_credit": 12.0,
            "acked": False,
        }
        await coord.async_acknowledge_detection()
        assert "2026-08-18" in coord._parent.import_store.ptr_seen_event_dates
        assert coord._parent.import_store.ptr_detected_event is None

    @pytest.mark.asyncio
    async def test_acknowledge_no_detection(self):
        coord = _make_coordinator()
        await coord.async_acknowledge_detection()
        assert coord._parent.import_store.ptr_detected_event is None

    def test_fall_back_timer_uses_the_later_utc_instant_and_cancels(self):
        coord = _make_coordinator()
        coord._parent.import_store.ptr_scheduled_event = {
            "start": "2026-11-01T01:30:00-08:00",
            "end": "2026-11-01T03:30:00-08:00",
            "label": "fold",
        }
        frozen = datetime(2026, 11, 1, 0, 30, tzinfo=PGE_TZ)
        captured: list[datetime] = []
        unsubs: list[MagicMock] = []

        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return frozen if tz is None else frozen.astimezone(tz)

        def track(_hass, _action, point):
            captured.append(point)
            unsub = MagicMock()
            unsubs.append(unsub)
            return unsub

        with (
            patch("custom_components.pge_energy.ptr_events.datetime", FrozenDateTime),
            patch(
                "custom_components.pge_energy.ptr_events.async_track_point_in_utc_time",
                side_effect=track,
            ),
        ):
            coord._reschedule_timers()
            assert captured[0] == datetime(2026, 11, 1, 9, 30, tzinfo=UTC)
            assert captured[0] != datetime(2026, 11, 1, 8, 30, tzinfo=UTC)
            coord._reschedule_timers()

        assert unsubs[0].call_count == 1
        assert unsubs[1].call_count == 1
        assert unsubs[2].call_count == 1

    def test_start_callback_fires_the_active_alert(self):
        coord = _make_coordinator()
        coord._parent.import_store.ptr_scheduled_event = {
            "start": "2026-11-01T01:30:00-08:00",
            "end": "2026-11-01T03:30:00-08:00",
            "label": "fold",
        }
        coord._start_timer = MagicMock()

        def _close(coro):
            coro.close()

        coord.hass.async_create_task.side_effect = _close
        with patch("custom_components.pge_energy.ptr_events.async_fire_pge_alert") as fire:
            coord._on_start(datetime(2026, 11, 1, 9, 30, tzinfo=UTC))
        fire.assert_called_once()
        assert fire.call_args.args[1] == ALERT_PTR_EVENT_ACTIVE
        coord.hass.async_create_task.assert_called_once()
        assert coord._start_timer is None


class TestPtrWakeInstants:
    def test_fall_back_keeps_the_pst_occurrence(self):
        now = datetime(2026, 11, 1, 0, 30, tzinfo=PGE_TZ)
        start = datetime.fromisoformat("2026-11-01T01:30:00-08:00")
        end = datetime.fromisoformat("2026-11-01T03:30:00-08:00")
        start_at, warn_at, end_at = ptr_wake_instants(now, start, end, warn_minutes=15)
        assert start_at == datetime(2026, 11, 1, 9, 30, tzinfo=UTC)
        assert warn_at == datetime(2026, 11, 1, 9, 15, tzinfo=UTC)
        assert end_at == datetime(2026, 11, 1, 11, 30, tzinfo=UTC)
