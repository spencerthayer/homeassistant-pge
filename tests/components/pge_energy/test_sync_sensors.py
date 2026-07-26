from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.pge_energy.models import SyncProgressSnapshot
from custom_components.pge_energy.sensor import (
    PGESyncDetailSensor,
    PGESyncEtaSensor,
    PGESyncProgressSensor,
    PGESyncStatusSensor,
)


def test_sync_sensors_read_snapshot():
    coordinator = MagicMock()
    coordinator.sync_progress = SyncProgressSnapshot(
        status="backfilling",
        phase="hourly",
        done=4,
        total=20,
        percent=20,
        started_at=1.0,
        eta_seconds=40.0,
        message="Hourly 4/20",
        error=None,
    )
    assert PGESyncStatusSensor(coordinator, "ak").native_value == "backfilling"
    assert PGESyncProgressSensor(coordinator, "ak").native_value == 20
    assert PGESyncEtaSensor(coordinator, "ak").native_value == 40.0
    assert PGESyncDetailSensor(coordinator, "ak").native_value == "Hourly 4/20"
