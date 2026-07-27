"""Pure helpers for manual-sync / backfill progress tracking."""

from __future__ import annotations

import math
from typing import Any

from .const import SYNC_PHASE_IDLE, SYNC_STATUS_IDLE
from .models import SyncProgressSnapshot


def compute_percent(done: int, total: int) -> int:
    """Return 0–100 progress percent (floor)."""
    if total <= 0:
        return 0
    if done <= 0:
        return 0
    if done >= total:
        return 100
    return min(100, math.floor(100 * done / total))


def compute_eta_seconds(elapsed: float, done: int, total: int) -> float | None:
    """Linear ETA from completed units; None until at least one unit finishes."""
    if done <= 0 or total <= 0 or elapsed < 0:
        return None
    remaining = total - done
    if remaining <= 0:
        return 0.0
    return (elapsed / done) * remaining


def idle_snapshot() -> SyncProgressSnapshot:
    return SyncProgressSnapshot(
        status=SYNC_STATUS_IDLE,
        phase=SYNC_PHASE_IDLE,
        done=0,
        total=0,
        percent=0,
        started_at=None,
        eta_seconds=None,
        message="",
        error=None,
    )


def snapshot_to_store_fields(snapshot: SyncProgressSnapshot) -> dict[str, Any]:
    """Flatten a snapshot into ImportStoreData field names.

    ``sync_started_at`` is omitted here — the coordinator writes a wall-clock ISO
    (monotonic ``started_at`` is process-local and must not be persisted).
    """
    return {
        "sync_status": snapshot.status,
        "sync_phase": snapshot.phase,
        "sync_done": int(snapshot.done),
        "sync_total": int(snapshot.total),
        "sync_percent": int(snapshot.percent),
        "sync_eta_seconds": snapshot.eta_seconds,
        "sync_message": snapshot.message,
        "sync_error": snapshot.error,
    }


def snapshot_from_store_fields(data: dict[str, Any] | Any) -> SyncProgressSnapshot:
    """Rebuild a snapshot from store-like attributes or a mapping."""

    def _get(key: str, default: Any = None) -> Any:
        if isinstance(data, dict):
            return data.get(key, default)
        return getattr(data, key, default)

    status = _get("sync_status") or SYNC_STATUS_IDLE
    phase = _get("sync_phase") or SYNC_PHASE_IDLE
    done = int(_get("sync_done") or 0)
    total = int(_get("sync_total") or 0)
    percent_raw = _get("sync_percent")
    percent = int(percent_raw) if percent_raw is not None else compute_percent(done, total)
    # Monotonic clocks and prior-process values are not usable after reload.
    # Keep ETA unset until the next live progress mutation.
    started_at = None
    eta_raw = _get("sync_eta_seconds")
    eta_seconds = float(eta_raw) if eta_raw is not None else None
    message = str(_get("sync_message") or "")
    error = _get("sync_error")
    return SyncProgressSnapshot(
        status=str(status),
        phase=str(phase),
        done=done,
        total=total,
        percent=percent,
        started_at=started_at,
        eta_seconds=eta_seconds,
        message=message,
        error=str(error) if error is not None else None,
    )


def apply_progress_math(snapshot: SyncProgressSnapshot, *, now_monotonic: float) -> None:
    """Recompute percent and ETA on an in-place snapshot."""
    snapshot.percent = compute_percent(snapshot.done, snapshot.total)
    if snapshot.started_at is None:
        snapshot.eta_seconds = None
        return
    elapsed = max(0.0, now_monotonic - snapshot.started_at)
    snapshot.eta_seconds = compute_eta_seconds(elapsed, snapshot.done, snapshot.total)
