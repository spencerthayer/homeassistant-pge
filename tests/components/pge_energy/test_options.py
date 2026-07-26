from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import MagicMock

from custom_components.pge_energy.const import (
    CONF_HISTORY_MODE,
    CONF_HISTORY_START_DATE,
    CONF_POLLING_INTERVAL,
    CONF_POLLING_INTERVAL_UNIT,
    CONF_SYNC_LOCAL_TIME,
    DEFAULT_HISTORY_FLOOR,
    DEFAULT_POLLING_INTERVAL,
    DEFAULT_POLLING_INTERVAL_UNIT,
    DEFAULT_SYNC_LOCAL_TIME,
    HistoryMode,
    PollingIntervalUnit,
)
from custom_components.pge_energy.options import (
    compute_hourly_date_range,
    compute_pre_hourly_date_range,
    days_covered_by_interval,
    get_entry_option,
    history_incomplete,
    history_window_datetimes,
    iter_month_windows,
    minutes_to_polling_display,
    next_day_aligned_sync,
    next_hour_aligned_sync,
    parse_sync_local_time,
    pge_display_name,
    polling_interval_to_minutes,
    resolve_history_bounds,
    resolve_history_end,
    resolve_history_start,
    resolve_polling_interval_form_defaults,
    resolve_polling_interval_minutes,
    resolve_polling_timedelta,
    resolve_sync_local_time,
)
from custom_components.pge_energy.time_util import local_day_bounds


class TestResolveHistoryStart:
    def test_full_uses_floor(self):
        assert resolve_history_start(HistoryMode.FULL, None) == DEFAULT_HISTORY_FLOOR
        assert resolve_history_start("full", "2020-06-01") == DEFAULT_HISTORY_FLOOR

    def test_start_date_parsed(self):
        assert resolve_history_start(HistoryMode.START_DATE, "2021-03-15") == date(2021, 3, 15)

    def test_start_date_clamped_to_floor(self):
        assert resolve_history_start(HistoryMode.START_DATE, "2010-01-01") == DEFAULT_HISTORY_FLOOR

    def test_start_date_missing_falls_back_to_floor(self):
        assert resolve_history_start(HistoryMode.START_DATE, None) == DEFAULT_HISTORY_FLOOR


class TestHistoryEndAndBounds:
    def test_resolve_history_end_yesterday(self):
        assert resolve_history_end(today=date(2026, 7, 24)) == date(2026, 7, 23)

    def test_resolve_history_bounds_full(self):
        entry = MagicMock()
        entry.options = {CONF_HISTORY_MODE: HistoryMode.FULL.value}
        entry.data = {}
        start, end = resolve_history_bounds(entry, today=date(2026, 7, 24))
        assert start == DEFAULT_HISTORY_FLOOR
        assert end == date(2026, 7, 23)

    def test_resolve_history_bounds_start_date(self):
        entry = MagicMock()
        entry.options = {
            CONF_HISTORY_MODE: HistoryMode.START_DATE.value,
            CONF_HISTORY_START_DATE: "2024-01-01",
        }
        entry.data = {}
        start, end = resolve_history_bounds(entry, today=date(2026, 7, 24))
        assert start == date(2024, 1, 1)
        assert end == date(2026, 7, 23)

    def test_history_window_datetimes(self):
        start_dt, end_dt = history_window_datetimes(date(2024, 1, 1), date(2024, 1, 2))
        day1_start, _ = local_day_bounds(date(2024, 1, 1))
        _, day2_end = local_day_bounds(date(2024, 1, 2))
        assert start_dt == day1_start
        assert end_dt == day2_end - timedelta(milliseconds=1)


class TestTierBoundaries:
    def test_hourly_range_newest_n_days(self):
        assert compute_hourly_date_range(date(2024, 1, 1), date(2024, 1, 31), 7) == (
            date(2024, 1, 25),
            date(2024, 1, 31),
        )

    def test_hourly_range_clamped_to_span(self):
        assert compute_hourly_date_range(date(2024, 1, 1), date(2024, 1, 3), 30) == (
            date(2024, 1, 1),
            date(2024, 1, 3),
        )

    def test_hourly_range_empty_when_zero(self):
        assert compute_hourly_date_range(date(2024, 1, 1), date(2024, 1, 3), 0) is None

    def test_pre_hourly_range(self):
        hourly = (date(2024, 1, 25), date(2024, 1, 31))
        assert compute_pre_hourly_date_range(date(2024, 1, 1), date(2024, 1, 31), hourly) == (
            date(2024, 1, 1),
            date(2024, 1, 24),
        )

    def test_pre_hourly_none_when_hourly_covers_all(self):
        hourly = (date(2024, 1, 1), date(2024, 1, 3))
        assert compute_pre_hourly_date_range(date(2024, 1, 1), date(2024, 1, 3), hourly) is None

    def test_iter_month_windows(self):
        windows = iter_month_windows(date(2024, 1, 15), date(2024, 3, 10))
        assert windows == [
            (date(2024, 1, 15), date(2024, 1, 31)),
            (date(2024, 2, 1), date(2024, 2, 29)),
            (date(2024, 3, 1), date(2024, 3, 10)),
        ]

    def test_days_covered_by_interval_exclusive_midnight_end(self):
        start, _ = local_day_bounds(date(2024, 2, 1))
        end, _ = local_day_bounds(date(2024, 3, 1))
        days = days_covered_by_interval(start, end)
        assert days[0] == date(2024, 2, 1)
        assert days[-1] == date(2024, 2, 29)
        assert len(days) == 29

    def test_history_incomplete(self):
        assert history_incomplete(date(2024, 1, 1), date(2024, 1, 3), ["2024-01-01", "2024-01-02"]) is True
        assert (
            history_incomplete(
                date(2024, 1, 1),
                date(2024, 1, 2),
                ["2024-01-01", "2024-01-02"],
            )
            is False
        )


class TestGetEntryOption:
    def test_prefers_options_over_data(self):
        entry = MagicMock()
        entry.options = {CONF_POLLING_INTERVAL: 30}
        entry.data = {CONF_POLLING_INTERVAL: 60}
        assert get_entry_option(entry, CONF_POLLING_INTERVAL, 90) == 30

    def test_falls_back_to_data_then_default(self):
        entry = MagicMock()
        entry.options = {}
        entry.data = {CONF_POLLING_INTERVAL: 45}
        assert get_entry_option(entry, CONF_POLLING_INTERVAL, 90) == 45
        entry.data = {}
        assert get_entry_option(entry, CONF_POLLING_INTERVAL, 90) == 90


def test_history_mode_enum_values():
    assert HistoryMode.FULL.value == "full"
    assert HistoryMode.START_DATE.value == "start_date"


class TestPollingIntervalUnit:
    def test_to_minutes_hours_and_days(self):
        assert polling_interval_to_minutes(6, PollingIntervalUnit.HOURS) == 360
        assert polling_interval_to_minutes(1, PollingIntervalUnit.DAYS) == 1440
        assert polling_interval_to_minutes(30, PollingIntervalUnit.MINUTES) == 30

    def test_to_minutes_clamps_minimum(self):
        assert polling_interval_to_minutes(1, PollingIntervalUnit.MINUTES) == 15

    def test_minutes_to_display(self):
        assert minutes_to_polling_display(360) == (6, PollingIntervalUnit.HOURS)
        assert minutes_to_polling_display(1440) == (1, PollingIntervalUnit.DAYS)
        assert minutes_to_polling_display(45) == (45, PollingIntervalUnit.MINUTES)

    def test_resolve_minutes_default_four_hours(self):
        entry = MagicMock()
        entry.options = {}
        entry.data = {}
        assert resolve_polling_interval_minutes(entry) == 240

    def test_resolve_minutes_legacy_without_unit(self):
        entry = MagicMock()
        entry.options = {CONF_POLLING_INTERVAL: 60}
        entry.data = {}
        assert resolve_polling_interval_minutes(entry) == 60

    def test_resolve_minutes_with_unit(self):
        entry = MagicMock()
        entry.options = {
            CONF_POLLING_INTERVAL: 6,
            CONF_POLLING_INTERVAL_UNIT: PollingIntervalUnit.HOURS.value,
        }
        entry.data = {}
        assert resolve_polling_interval_minutes(entry) == 360

    def test_form_defaults_fresh_entry(self):
        entry = MagicMock()
        entry.options = {}
        entry.data = {}
        assert resolve_polling_interval_form_defaults(entry) == (
            DEFAULT_POLLING_INTERVAL,
            DEFAULT_POLLING_INTERVAL_UNIT.value,
        )
        assert DEFAULT_POLLING_INTERVAL == 4
        assert DEFAULT_POLLING_INTERVAL_UNIT is PollingIntervalUnit.HOURS

    def test_form_defaults_legacy_minutes(self):
        entry = MagicMock()
        entry.options = {CONF_POLLING_INTERVAL: 60}
        entry.data = {}
        assert resolve_polling_interval_form_defaults(entry) == (1, PollingIntervalUnit.HOURS.value)

    def test_next_day_aligned_sync_afternoon_to_next_2am(self):
        # 2026-07-24 12:19 PDT = 19:19 UTC
        now = datetime(2026, 7, 24, 19, 19, tzinfo=UTC)
        nxt = next_day_aligned_sync(now, every_days=1, hour=2)
        assert nxt == datetime(2026, 7, 25, 9, 0, tzinfo=UTC)  # 02:00 PDT

    def test_next_day_aligned_sync_just_after_2am(self):
        # 2026-07-24 02:00:30 PDT
        now = datetime(2026, 7, 24, 9, 0, 30, tzinfo=UTC)
        nxt = next_day_aligned_sync(now, every_days=1, hour=2)
        assert nxt == datetime(2026, 7, 25, 9, 0, tzinfo=UTC)

    def test_next_day_aligned_sync_every_two_days(self):
        now = datetime(2026, 7, 24, 19, 19, tzinfo=UTC)  # after today's 2am
        nxt = next_day_aligned_sync(now, every_days=2, hour=2)
        assert nxt == datetime(2026, 7, 26, 9, 0, tzinfo=UTC)

    def test_next_hour_aligned_sync_from_midnight_grid(self):
        # 2026-07-24 09:19 PDT = 16:19 UTC → next slot 12:00 PDT = 19:00 UTC
        now = datetime(2026, 7, 24, 16, 19, tzinfo=UTC)
        nxt = next_hour_aligned_sync(now, every_hours=4, hour=0)
        assert nxt == datetime(2026, 7, 24, 19, 0, tzinfo=UTC)

    def test_next_hour_aligned_sync_after_last_slot_rolls_to_midnight(self):
        # 2026-07-24 21:00 PDT = 04:00 UTC next calendar day → next is 00:00 PDT
        now = datetime(2026, 7, 25, 4, 0, tzinfo=UTC)
        nxt = next_hour_aligned_sync(now, every_hours=4, hour=0)
        assert nxt == datetime(2026, 7, 25, 7, 0, tzinfo=UTC)  # 00:00 PDT Jul 25

    def test_resolve_polling_timedelta_hours_aligns_to_sync_clock(self):
        entry = MagicMock()
        entry.options = {
            CONF_POLLING_INTERVAL: 6,
            CONF_POLLING_INTERVAL_UNIT: PollingIntervalUnit.HOURS.value,
            CONF_SYNC_LOCAL_TIME: "00:00:00",
        }
        entry.data = {}
        now = datetime(2026, 7, 24, 16, 19, tzinfo=UTC)  # 09:19 PDT
        delay = resolve_polling_timedelta(entry, now=now)
        # Next 6h slot from midnight: 12:00 PDT = 19:00 UTC
        assert delay == datetime(2026, 7, 24, 19, 0, tzinfo=UTC) - now

    def test_resolve_polling_timedelta_default_aligns_4h_from_midnight(self):
        entry = MagicMock()
        entry.options = {}
        entry.data = {}
        now = datetime(2026, 7, 24, 16, 19, tzinfo=UTC)  # 09:19 PDT
        delay = resolve_polling_timedelta(entry, now=now)
        # Default 4h from 00:00 → next is 12:00 PDT = 19:00 UTC
        assert delay == datetime(2026, 7, 24, 19, 0, tzinfo=UTC) - now

    def test_resolve_polling_timedelta_respects_configured_sync_time(self):
        entry = MagicMock()
        entry.options = {
            CONF_POLLING_INTERVAL: 1,
            CONF_POLLING_INTERVAL_UNIT: PollingIntervalUnit.DAYS.value,
            CONF_SYNC_LOCAL_TIME: "03:30:00",
        }
        entry.data = {}
        now = datetime(2026, 7, 24, 19, 19, tzinfo=UTC)  # 12:19 PDT
        delay = resolve_polling_timedelta(entry, now=now)
        # 03:30 PDT next day = 10:30 UTC
        assert delay == datetime(2026, 7, 25, 10, 30, tzinfo=UTC) - now

    def test_parse_and_resolve_sync_local_time(self):
        assert parse_sync_local_time("3:30") == (3, 30)
        assert parse_sync_local_time("bad") == (0, 0)
        entry = MagicMock()
        entry.options = {}
        entry.data = {}
        assert resolve_sync_local_time(entry) == DEFAULT_SYNC_LOCAL_TIME


def test_pge_display_name():
    assert pge_display_name("1071234567") == "PGE 1071234567"
