"""Tiered history backfill: hourly → daily → monthly."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import date, datetime, timedelta

from homeassistant.core import HomeAssistant

from .const import (
    BACKFILL_TIER_TIMEOUT,
    CONF_BACKFILL_CONCURRENCY,
    CONF_HOURLY_BACKFILL_DAYS,
    CONF_INCLUDE_COST,
    DEFAULT_BACKFILL_CONCURRENCY,
    DEFAULT_HISTORY_FLOOR,
    DEFAULT_HOURLY_BACKFILL_DAYS,
    DEFAULT_INCLUDE_COST,
    MAX_BACKFILL_CONCURRENCY,
    MIN_DAILY_REQUEST_DAYS,
    SYNC_PHASE_DAILY,
    SYNC_PHASE_HOURLY,
    SYNC_PHASE_MONTHLY,
    SYNC_STATUS_BACKFILLING,
)
from .coordinator import PGECoordinator
from .day_validation import clip_hourly_to_local_day, is_invalid_closed_day, validate_hourly_day
from .models import UsageInterval, UsageResolution
from .options import (
    compute_hourly_date_range,
    days_covered_by_interval,
    get_entry_option,
    iter_month_windows,
)
from .statistics import async_import_with_baseline
from .store import ImportStoreData, async_save_import_state
from .time_util import PGE_TZ, iter_local_days, local_day_bounds, today_local
from .usage_direction import explicit_gap_intervals, importable_energy_intervals

_LOGGER = logging.getLogger(__name__)

BACKFILL_DELAY_BETWEEN_CHUNKS = 0.5


def _include_cost(coordinator: PGECoordinator) -> bool:
    return bool(get_entry_option(coordinator.entry, CONF_INCLUDE_COST, DEFAULT_INCLUDE_COST))


def _concurrency(coordinator: PGECoordinator) -> int:
    return min(
        MAX_BACKFILL_CONCURRENCY,
        max(
            1,
            int(
                get_entry_option(
                    coordinator.entry,
                    CONF_BACKFILL_CONCURRENCY,
                    DEFAULT_BACKFILL_CONCURRENCY,
                )
            ),
        ),
    )


def _hourly_days(coordinator: PGECoordinator) -> int:
    return int(
        get_entry_option(
            coordinator.entry,
            CONF_HOURLY_BACKFILL_DAYS,
            DEFAULT_HOURLY_BACKFILL_DAYS,
        )
    )


def _iter_days(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def _normalize_daily_interval(iv: UsageInterval) -> UsageInterval:
    day = iv.start.astimezone(PGE_TZ).date()
    start, end = local_day_bounds(day)
    return replace(iv, start=start, end=end, resolution=UsageResolution.DAILY)


def _normalize_monthly_interval(iv: UsageInterval) -> UsageInterval:
    """Place a billing-period total on the period's local-month start for stats.

    PGE MONTHLY rows are billing cycles (e.g. 2021-07-08→2021-08-06), not
    calendar months. Completion coverage must use the raw ``iv.start``/``iv.end``
    via ``days_covered_by_interval``; this helper only chooses the statistic
    timestamp.
    """
    local = iv.start.astimezone(PGE_TZ)
    month_start = date(local.year, local.month, 1)
    next_month = date(local.year + 1, 1, 1) if local.month == 12 else date(local.year, local.month + 1, 1)
    start, _ = local_day_bounds(month_start)
    end, _ = local_day_bounds(next_month)
    return replace(iv, start=start, end=end, resolution=UsageResolution.MONTHLY)


def _merge_by_month_start(intervals: list[UsageInterval]) -> list[UsageInterval]:
    """Collapse month-start-normalized periods, summing collisions.

    Two billing cycles can start in the same calendar month (short cycle after a
    rate/meter change), so ``_normalize_monthly_interval`` can map both onto the
    same statistic timestamp. Sum them instead of dropping one — the days of both
    cycles get marked complete either way.
    """
    merged: dict[datetime, UsageInterval] = {}
    for iv in sorted(intervals, key=lambda i: i.start):
        prior = merged.get(iv.start)
        if prior is None:
            merged[iv.start] = iv
            continue
        amounts = [a for a in (prior.amount, iv.amount) if a is not None]
        kwh_parts = [k for k in (prior.kwh, iv.kwh) if k is not None]
        merged[iv.start] = replace(
            prior,
            kwh=sum(kwh_parts) if kwh_parts else None,
            amount=sum(amounts) if amounts else None,
        )
    return list(merged.values())


def _calendar_month_has_completed(store: ImportStoreData, month_start: date) -> bool:
    """True when any Pacific day in that calendar month is already completed.

    Monthly stats land on month-start. If finer hourly/daily data already owns
    any day in that month, importing the billing-period total would inflate the
    month-start day (e.g. 648 kWh lump + hourly ≈ 677 kWh on the scatter).
    """
    if month_start.month == 12:
        next_month = date(month_start.year + 1, 1, 1)
    else:
        next_month = date(month_start.year, month_start.month + 1, 1)
    completed = set(store.completed_local_dates)
    day = month_start
    while day < next_month:
        if day.isoformat() in completed:
            return True
        day += timedelta(days=1)
    return False


def _mark_completed(store: ImportStoreData, days: list[date] | list[str]) -> int:
    """Mark days complete; return how many were newly added."""
    newly = 0
    for day in days:
        iso = day if isinstance(day, str) else day.isoformat()
        if iso not in store.completed_local_dates:
            store.completed_local_dates.append(iso)
            newly += 1
        if iso in store.failed_local_dates:
            store.failed_local_dates.remove(iso)
    return newly


def _mark_failed(store: ImportStoreData, iso: str) -> None:
    if iso not in store.failed_local_dates:
        store.failed_local_dates.append(iso)


async def _async_note_completed(
    coordinator: PGECoordinator,
    store: ImportStoreData,
    days: list[date] | list[str],
    *,
    phase: str,
) -> None:
    newly = _mark_completed(store, days)
    if newly <= 0:
        return
    new_done = coordinator.sync_progress.done + newly
    total = coordinator.sync_progress.total
    coordinator.update_sync_progress(
        done=new_done,
        phase=phase,
        message=f"{phase.capitalize()} {new_done}/{total}",
    )
    await coordinator.async_persist_sync_progress()


async def _async_note_failed(coordinator: PGECoordinator, iso: str, error: str) -> None:
    _mark_failed(coordinator.import_store, iso)
    coordinator.update_sync_progress(error=error)
    await coordinator.async_persist_sync_progress()


async def _async_import_batch(
    hass: HomeAssistant,
    entry_id: str,
    coordinator: PGECoordinator,
    intervals: list[UsageInterval],
) -> bool:
    if not intervals:
        return True
    store = coordinator.import_store
    store.dirty_from = min(iv.start for iv in intervals).isoformat()
    await async_save_import_state(hass, entry_id, store, critical=True)
    try:
        async with coordinator.import_lock:
            import_result = await async_import_with_baseline(
                hass,
                coordinator.account_key,
                intervals,
                include_cost=_include_cost(coordinator),
                account_id=coordinator.account_id,
            )
        await coordinator.async_refresh_lifetime_totals()
    except Exception as exc:
        _LOGGER.warning("Backfill import failed: %s", exc)
        return False
    # Soft cost/temperature ack failures still clear dirty_from; mark days for retry.
    for iso in import_result.cost_failed_days:
        _mark_failed(store, iso)
        if iso in store.completed_local_dates:
            store.completed_local_dates.remove(iso)
    store.dirty_from = None
    store.last_imported_start = min(iv.start for iv in intervals).isoformat()
    store.last_imported_end = max(iv.end for iv in intervals).isoformat()
    await async_save_import_state(hass, entry_id, store, critical=True)
    return not import_result.cost_failed_days


async def async_fetch_hourly_day(
    coordinator: PGECoordinator,
    day: date,
) -> tuple[date, list[UsageInterval]]:
    """Fetch one local day at HOURLY resolution (empty list on transport failure)."""
    day_start, day_end = local_day_bounds(day)
    request_end = day_end - timedelta(milliseconds=1)
    try:
        response = await coordinator.async_get_usage_with_auth_retry(
            day_start,
            request_end,
            resolution=UsageResolution.HOURLY,
        )
    except Exception as exc:
        _LOGGER.warning("Hourly backfill fetch failed for %s: %s", day, exc)
        return day, []
    return day, list(response.intervals)


async def _async_backfill_hourly(
    hass: HomeAssistant,
    entry_id: str,
    coordinator: PGECoordinator,
    start: date,
    end: date,
) -> None:
    store = coordinator.import_store
    completed = set(store.completed_local_dates)
    pending = [d for d in _iter_days(start, end) if d.isoformat() not in completed]
    if not pending:
        return

    concurrency = _concurrency(coordinator)
    sem = asyncio.Semaphore(concurrency)

    async def _bounded(day: date) -> tuple[date, list[UsageInterval] | None]:
        async with sem:
            day_out, intervals = await async_fetch_hourly_day(coordinator, day)
            # Distinguish transport failure (empty + failed earlier) from empty API day.
            # async_fetch_hourly_day returns [] for both; treat empty as invalid closed day.
            return day_out, intervals

    coordinator.update_sync_progress(phase=SYNC_PHASE_HOURLY)
    for idx in range(0, len(pending), concurrency):
        batch = pending[idx : idx + concurrency]
        fetched = await asyncio.gather(*[_bounded(d) for d in batch])
        results = {day: intervals for day, intervals in fetched}

        batch_intervals: list[UsageInterval] = []
        days_to_complete: list[str] = []
        for day in sorted(batch):
            intervals = results.get(day)
            iso = day.isoformat()
            if intervals is None:
                await _async_note_failed(coordinator, iso, f"Hourly fetch failed for {iso}")
                continue

            clipped = clip_hourly_to_local_day(day, intervals)
            ok_complete, reason = validate_hourly_day(day, clipped, clip_boundary=False)
            if is_invalid_closed_day(ok_complete, reason):
                _LOGGER.warning(
                    "Hourly backfill day %s invalid (%s) — will try daily/monthly",
                    iso,
                    reason,
                )
                await _async_note_failed(coordinator, iso, f"{iso}:{reason}")
                continue

            gap_rows = explicit_gap_intervals(clipped)
            if gap_rows:
                _LOGGER.warning(
                    "Hourly backfill day %s %s — %s explicit null interval(s); "
                    "importing %s energy sample(s) and not retrying coarse tiers",
                    iso,
                    reason,
                    len(gap_rows),
                    len(importable_energy_intervals(clipped)),
                )
            # Keep unavailable rows so temperature overlay can still import °F;
            # statistics skips null-kWh for energy/cost series.
            if clipped:
                batch_intervals.extend(clipped)
            if ok_complete:
                days_to_complete.append(iso)

        if batch_intervals:
            ok = await _async_import_batch(hass, entry_id, coordinator, batch_intervals)
            if not ok:
                for day in sorted(batch):
                    await _async_note_failed(coordinator, day.isoformat(), "Hourly import failed")
                await async_save_import_state(hass, entry_id, store)
            else:
                await _async_note_completed(coordinator, store, days_to_complete, phase=SYNC_PHASE_HOURLY)
                await async_save_import_state(hass, entry_id, store)
        else:
            await async_save_import_state(hass, entry_id, store)

        await asyncio.sleep(BACKFILL_DELAY_BETWEEN_CHUNKS)


def _daily_request_window(
    need_start: date,
    need_end: date,
    *,
    floor: date = DEFAULT_HISTORY_FLOOR,
) -> tuple[datetime, datetime]:
    span = (need_end - need_start).days + 1
    req_start = need_start
    if span < MIN_DAILY_REQUEST_DAYS:
        padded = need_end - timedelta(days=MIN_DAILY_REQUEST_DAYS - 1)
        req_start = max(padded, floor)
    start_dt, _ = local_day_bounds(req_start)
    _, end_excl = local_day_bounds(need_end)
    return start_dt, end_excl - timedelta(milliseconds=1)


async def _async_backfill_daily(
    hass: HomeAssistant,
    entry_id: str,
    coordinator: PGECoordinator,
    start: date,
    end: date,
) -> None:
    store = coordinator.import_store
    coordinator.update_sync_progress(phase=SYNC_PHASE_DAILY)
    for month_start, month_end in iter_month_windows(start, end):
        completed = set(store.completed_local_dates)
        month_incomplete = [d for d in _iter_days(month_start, month_end) if d.isoformat() not in completed]
        if not month_incomplete:
            continue
        need_start, need_end = month_incomplete[0], month_incomplete[-1]
        req_start, req_end = _daily_request_window(need_start, need_end)
        try:
            response = await coordinator.async_get_usage_with_auth_retry(
                req_start,
                req_end,
                resolution=UsageResolution.DAILY,
            )
        except Exception as exc:
            _LOGGER.warning("Daily backfill fetch failed for %s..%s: %s", need_start, need_end, exc)
            for day in month_incomplete:
                await _async_note_failed(coordinator, day.isoformat(), f"Daily fetch failed: {exc}")
            await async_save_import_state(hass, entry_id, store)
            continue

        needed = {d.isoformat() for d in month_incomplete}
        normalized: list[UsageInterval] = []
        covered: list[str] = []
        for iv in response.intervals:
            daily = _normalize_daily_interval(iv)
            day_iso = daily.start.astimezone(PGE_TZ).date().isoformat()
            if day_iso not in needed:
                continue
            normalized.append(daily)
            covered.append(day_iso)

        if normalized:
            ok = await _async_import_batch(hass, entry_id, coordinator, normalized)
            if ok:
                await _async_note_completed(coordinator, store, covered, phase=SYNC_PHASE_DAILY)
            else:
                for day in month_incomplete:
                    await _async_note_failed(coordinator, day.isoformat(), "Daily import failed")
        else:
            for day in month_incomplete:
                await _async_note_failed(coordinator, day.isoformat(), "Daily response empty")
        await async_save_import_state(hass, entry_id, store)
        await asyncio.sleep(BACKFILL_DELAY_BETWEEN_CHUNKS)


async def _async_backfill_monthly(
    hass: HomeAssistant,
    entry_id: str,
    coordinator: PGECoordinator,
    start: date,
    end: date,
) -> None:
    """Fill remaining days from MONTHLY billing periods (paged from yesterday).

    Important: PGE returns ~12 periods relative to the requested *end*. Asking
    only through the last incomplete day drops the open billing cycle that still
    covers those days (live example: end=2021-07-31 omits the 2021-07-08 period).
    Always page from yesterday back to ``start`` so covering periods are present.

    Days before the oldest returned period have no PGE history — mark them
    complete as before-service rather than failing the job forever.
    """
    store = coordinator.import_store
    coordinator.update_sync_progress(phase=SYNC_PHASE_MONTHLY)
    completed = set(store.completed_local_dates)
    incomplete = [d for d in _iter_days(start, end) if d.isoformat() not in completed]
    if not incomplete:
        return

    # Page from yesterday (or the range end, whichever is later) so the billing
    # period that covers the newest incomplete day is included.
    yesterday = today_local() - timedelta(days=1)
    fetch_end_day = max(incomplete[-1], yesterday)
    req_start, _ = local_day_bounds(incomplete[0])
    _, end_excl = local_day_bounds(fetch_end_day)
    req_end = end_excl - timedelta(milliseconds=1)

    try:
        # Fresh login at tier start; 401 mid-page renews via auth-retry helper.
        await coordinator.auth_manager.ensure_valid_token(force=coordinator.auth_manager.auth_mode == "credential")
        coordinator.persist_auth_to_entry()
        response = await coordinator.async_get_monthly_usage_with_auth_retry(req_start, req_end)
    except Exception as exc:
        _LOGGER.warning("Monthly backfill fetch failed for %s..%s: %s", incomplete[0], fetch_end_day, exc)
        for day in incomplete:
            await _async_note_failed(coordinator, day.isoformat(), f"Monthly fetch failed: {exc}")
        await async_save_import_state(hass, entry_id, store)
        return

    if not response.intervals:
        for day in incomplete:
            await _async_note_failed(coordinator, day.isoformat(), "Monthly response empty")
        await async_save_import_state(hass, entry_id, store)
        return

    needed_days = set(incomplete)
    oldest_period_start = min(iv.start for iv in response.intervals).astimezone(PGE_TZ).date()

    # No PGE history exists before the oldest billing period — close those days.
    before_service = [d for d in incomplete if d < oldest_period_start]
    if before_service:
        _LOGGER.info(
            "Marking %s day(s) before oldest monthly period %s as complete (no PGE history)",
            len(before_service),
            oldest_period_start.isoformat(),
        )
        await _async_note_completed(coordinator, store, before_service, phase=SYNC_PHASE_MONTHLY)
        needed_days -= set(before_service)

    to_import: list[UsageInterval] = []
    covered_days: list[date] = []
    skipped_for_finer = 0
    for iv in response.intervals:
        # Coverage must use raw billing bounds, not calendar-month normalization.
        covered = [d for d in days_covered_by_interval(iv.start, iv.end) if d in needed_days]
        if not covered:
            continue
        covered_days.extend(covered)
        normalized = _normalize_monthly_interval(iv)
        month_start_day = normalized.start.astimezone(PGE_TZ).date()
        # Never park a full billing-period total on a month that already has
        # hourly/daily rows — correction windows re-fetch recent days and the
        # lump + finer hours double-count (Weather vs usage outlier).
        if _calendar_month_has_completed(store, month_start_day):
            skipped_for_finer += 1
            continue
        to_import.append(normalized)

    if skipped_for_finer:
        _LOGGER.info(
            "Skipping monthly statistics for %s period(s) whose calendar month "
            "already has finer completed days; still closing covered gap days",
            skipped_for_finer,
        )

    if to_import:
        merged = _merge_by_month_start(to_import)
        ok = await _async_import_batch(hass, entry_id, coordinator, merged)
        if not ok:
            # Finer hourly/daily rows often already occupy the month-start hour;
            # a recorder mismatch must not leave the history checkpoint stuck.
            # Escalated to error: this also swallows genuine import failures, and
            # the closed days are never retried by a later backfill pass.
            _LOGGER.error(
                "Monthly statistics import failed for %s period(s); closing %s covered day(s) "
                "without statistics to avoid a stuck checkpoint",
                len(merged),
                len(set(covered_days)),
            )
    if covered_days:
        await _async_note_completed(coordinator, store, covered_days, phase=SYNC_PHASE_MONTHLY)
    elif needed_days:
        # The response had periods, just none covering these days (mid-service gap).
        for day in sorted(needed_days):
            await _async_note_failed(coordinator, day.isoformat(), "No monthly period covers this day")
    await async_save_import_state(hass, entry_id, store)


async def async_backfill_range(
    hass: HomeAssistant,
    entry_id: str,
    coordinator: PGECoordinator,
    start: datetime,
    end: datetime,
) -> None:
    """Backfill [start, end] using hourly → daily → monthly tiers."""
    days = [d for d in iter_local_days(start, end) if d != today_local()]
    if not days:
        if coordinator.sync_progress.status == SYNC_STATUS_BACKFILLING:
            coordinator.complete_sync_job(message="Backfill done")
            await coordinator.async_persist_sync_progress()
        return

    store = coordinator.import_store
    incomplete = [d for d in days if d.isoformat() not in store.completed_local_dates]
    if coordinator.sync_progress.status != SYNC_STATUS_BACKFILLING:
        coordinator.begin_sync_job(
            status=SYNC_STATUS_BACKFILLING,
            phase=SYNC_PHASE_HOURLY,
            total=len(incomplete),
            message=f"Hourly 0/{len(incomplete)}",
        )
        await coordinator.async_persist_sync_progress()
    elif coordinator.sync_progress.total <= 0:
        coordinator.update_sync_progress(total=len(incomplete), done=0)

    # Short-lived bearer: login once at job start; per-request helpers renew on 401.
    try:
        await coordinator.auth_manager.ensure_valid_token(force=coordinator.auth_manager.auth_mode == "credential")
        coordinator.persist_auth_to_entry()
    except Exception as exc:
        _LOGGER.warning("Backfill auth failed before fetch: %s", exc)
        coordinator.fail_sync_job(f"Authentication failed: {exc}")
        await coordinator.async_persist_sync_progress()
        return

    if not incomplete:
        coordinator.complete_sync_job(message="Backfill done")
        await coordinator.async_persist_sync_progress()
        store.target_start = None
        store.target_end = None
        await async_save_import_state(hass, entry_id, store)
        return

    range_start, range_end = days[0], days[-1]
    hourly_days = _hourly_days(coordinator)
    hourly_range = compute_hourly_date_range(range_start, range_end, hourly_days)

    if hourly_range is not None:
        _LOGGER.info(
            "Backfill hourly tier %s..%s (max %s days)",
            hourly_range[0],
            hourly_range[1],
            hourly_days,
        )
        try:
            # Timeout only fires if the tier is at a cancellable await; hard release
            # covers non-cancellable hangs. A cancelled tier may leave dirty_from set
            # for async_repair_dirty_if_needed on the next boot.
            await asyncio.wait_for(
                _async_backfill_hourly(hass, entry_id, coordinator, hourly_range[0], hourly_range[1]),
                timeout=BACKFILL_TIER_TIMEOUT.total_seconds(),
            )
        except TimeoutError:
            _LOGGER.error("Hourly tier exceeded %s — continuing to daily", BACKFILL_TIER_TIMEOUT)

    remaining = [d for d in days if d.isoformat() not in store.completed_local_dates]
    if remaining:
        _LOGGER.info("Backfill daily tier for %s incomplete day(s)", len(remaining))
        try:
            await asyncio.wait_for(
                _async_backfill_daily(hass, entry_id, coordinator, remaining[0], remaining[-1]),
                timeout=BACKFILL_TIER_TIMEOUT.total_seconds(),
            )
        except TimeoutError:
            _LOGGER.error("Daily tier exceeded %s — continuing to monthly", BACKFILL_TIER_TIMEOUT)

    remaining = [d for d in days if d.isoformat() not in store.completed_local_dates]
    if remaining:
        _LOGGER.info("Backfill monthly tier for %s incomplete day(s)", len(remaining))
        try:
            await asyncio.wait_for(
                _async_backfill_monthly(hass, entry_id, coordinator, remaining[0], remaining[-1]),
                timeout=BACKFILL_TIER_TIMEOUT.total_seconds(),
            )
        except TimeoutError:
            _LOGGER.error("Monthly tier exceeded %s — leaving remaining days incomplete", BACKFILL_TIER_TIMEOUT)

    remaining = [d for d in days if d.isoformat() not in store.completed_local_dates]
    # Drop stale failures that were later completed. Days outside this job's range
    # keep their failure record — it drives the `retry_failed_ranges` service.
    in_job = {d.isoformat() for d in days}
    completed = set(store.completed_local_dates)
    store.failed_local_dates = [iso for iso in store.failed_local_dates if iso not in completed]
    await async_save_import_state(hass, entry_id, store)

    if not remaining:
        # Every in-job day is completed, so the filter above already cleared their failures.
        store.target_start = None
        store.target_end = None
        await async_save_import_state(hass, entry_id, store)
        coordinator.complete_sync_job(message="Backfill done")
        await coordinator.async_persist_sync_progress()
    else:
        failed_in_job = [iso for iso in store.failed_local_dates if iso in in_job]
        coordinator.fail_sync_job(f"Incomplete days={len(remaining)} failed={len(failed_in_job)}")
        await coordinator.async_persist_sync_progress()
