from __future__ import annotations

from custom_components.pge_energy.models import SyncProgressSnapshot
from custom_components.pge_energy.store import ImportStoreData
from custom_components.pge_energy.sync_progress import (
    apply_progress_math,
    compute_eta_seconds,
    compute_percent,
    idle_snapshot,
    snapshot_from_store_fields,
    snapshot_to_store_fields,
)


def test_compute_percent_edges():
    assert compute_percent(0, 0) == 0
    assert compute_percent(0, 10) == 0
    assert compute_percent(3, 10) == 30
    assert compute_percent(10, 10) == 100
    assert compute_percent(11, 10) == 100
    assert compute_percent(1, 3) == 33  # floor


def test_compute_eta_seconds():
    assert compute_eta_seconds(10.0, 0, 10) is None
    assert compute_eta_seconds(10.0, 1, 0) is None
    assert compute_eta_seconds(10.0, 5, 5) == 0.0
    assert compute_eta_seconds(10.0, 2, 10) == 40.0  # (10/2)*8


def test_snapshot_store_round_trip():
    snap = SyncProgressSnapshot(
        status="backfilling",
        phase="hourly",
        done=4,
        total=20,
        percent=20,
        started_at=100.5,
        eta_seconds=40.0,
        message="Hourly 4/20",
        error=None,
    )
    fields = snapshot_to_store_fields(snap)
    store = ImportStoreData(account_key="abc", **fields)
    restored = snapshot_from_store_fields(store)
    assert restored.status == "backfilling"
    assert restored.phase == "hourly"
    assert restored.done == 4
    assert restored.total == 20
    assert restored.percent == 20
    assert restored.started_at == 100.5
    assert restored.eta_seconds == 40.0
    assert restored.message == "Hourly 4/20"
    assert restored.error is None

    via_dict = snapshot_from_store_fields(store.to_dict())
    assert via_dict.done == 4
    assert ImportStoreData.from_dict(store.to_dict()).sync_done == 4


def test_apply_progress_math():
    snap = idle_snapshot()
    snap.done = 2
    snap.total = 8
    snap.started_at = 100.0
    apply_progress_math(snap, now_monotonic=120.0)
    assert snap.percent == 25
    assert snap.eta_seconds == 60.0  # (20/2)*6
