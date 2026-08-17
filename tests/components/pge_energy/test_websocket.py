from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from custom_components.pge_energy.billing_models import ProgramsSnapshot, RateCompareSnapshot, TodSnapshot
from custom_components.pge_energy.const import (
    CONF_ACCOUNT_ID,
    CONF_ACCOUNT_KEY,
    DOMAIN,
    STATISTIC_ID_SUFFIX_CONSUMPTION,
    WS_SETUP_KEY,
)
from custom_components.pge_energy.coordinator import PGECoordinator
from custom_components.pge_energy.models import SyncProgressSnapshot
from custom_components.pge_energy.websocket import (
    _tod_enrolled_from_programs,
    _tod_payload,
    async_setup_websocket,
    websocket_accounts,
    websocket_sync_subscribe,
)


def _make_coordinator(hass, entry_id: str = "entry1") -> PGECoordinator:
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.title = "PGE 123"
    entry.data = {
        CONF_ACCOUNT_ID: "1234567890",
        CONF_ACCOUNT_KEY: "abcdabcdabcdabcd",
    }
    entry.options = {}
    auth = MagicMock()
    auth.account_key = "abcdabcdabcdabcd"
    auth.token_expires_at = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
    auth.auth_mode = "credential"
    client = MagicMock()
    coord = PGECoordinator(hass, entry, auth, client)
    coord._sync_progress = SyncProgressSnapshot(
        status="refreshing",
        phase="hourly",
        done=1,
        total=4,
        percent=25,
        message="fetching",
        error=None,
        eta_seconds=120.0,
    )
    coord._newest_interval = datetime(2026, 7, 23, 1, 0, tzinfo=UTC)
    coord._last_successful_update = datetime(2026, 7, 24, 2, 0, tzinfo=UTC)
    coord._last_api_error = None
    return coord


def test_async_setup_websocket_idempotent():
    hass = MagicMock()
    hass.data = {}
    with patch("custom_components.pge_energy.websocket.websocket_api.async_register_command") as register:
        async_setup_websocket(hass)
        async_setup_websocket(hass)
    assert register.call_count == 2
    assert hass.data[WS_SETUP_KEY] is True


def test_websocket_accounts_payload_has_no_credentials():
    hass = MagicMock()
    coord = _make_coordinator(hass)
    hass.data = {DOMAIN: {"entry1": coord}}

    connection = MagicMock()
    device = MagicMock()
    device.id = "device-1"

    with (
        patch(
            "custom_components.pge_energy.websocket.dr.async_get",
            return_value=MagicMock(async_get_device=MagicMock(return_value=device)),
        ),
        patch(
            "custom_components.pge_energy.websocket.er.async_get",
            return_value=MagicMock(
                async_get_entity_id=MagicMock(side_effect=lambda platform, domain, uid: f"{platform}.{uid}")
            ),
        ),
    ):
        websocket_accounts(hass, connection, {"id": 7, "type": f"{DOMAIN}/accounts"})

    connection.send_result.assert_called_once()
    msg_id, payload = connection.send_result.call_args.args
    assert msg_id == 7
    assert "accounts" in payload
    account = payload["accounts"][0]
    assert account["entry_id"] == "entry1"
    assert account["account_id"] == "1234567890"
    assert account["account_key"] == "abcdabcdabcdabcd"
    assert account["device_id"] == "device-1"
    assert account["statistic_ids"]["consumption"] == (f"{DOMAIN}:abcdabcdabcdabcd{STATISTIC_ID_SUFFIX_CONSUMPTION}")
    assert account["entity_ids"]["energy"] == "sensor.abcdabcdabcdabcd_energy"
    assert account["entity_ids"]["autopay"] == "binary_sensor.abcdabcdabcdabcd_autopay"
    assert account["entity_ids"]["est_current_charges"] == ("sensor.abcdabcdabcdabcd_est_current_charges")
    assert account["entity_ids"]["billing_cycle_day"] == "sensor.abcdabcdabcdabcd_billing_cycle_day"
    blob = str(payload)
    for secret in ("password", "bearer_token", "encrypted_person_id", "refresh_credential"):
        assert secret not in blob


def test_websocket_sync_subscribe_pushes_and_tears_down():
    hass = MagicMock()
    coord = _make_coordinator(hass)
    listeners: list = []

    def add_listener(cb):
        listeners.append(cb)
        return MagicMock(name="unsub")

    coord.async_add_listener = add_listener  # type: ignore[method-assign]
    hass.data = {DOMAIN: {"entry1": coord}}

    connection = MagicMock()
    connection.subscriptions = {}

    websocket_sync_subscribe(hass, connection, {"id": 9, "type": f"{DOMAIN}/sync/subscribe"})

    connection.send_result.assert_called_once_with(9)
    connection.send_message.assert_called()
    event = connection.send_message.call_args.args[0]
    # event_message returns a dict-like structure from websocket_api
    assert event["id"] == 9
    assert event["type"] == "event"
    assert event["event"]["entries"][0]["entry_id"] == "entry1"
    assert event["event"]["entries"][0]["percent"] == 25
    assert event["event"]["entries"][0]["auth_expiration"].startswith("2026-07-24")

    assert 9 in connection.subscriptions
    assert len(listeners) == 1

    # Listener fire pushes again
    connection.send_message.reset_mock()
    listeners[0]()
    assert connection.send_message.call_count == 1

    # Teardown
    connection.subscriptions[9]()


def test_tod_payload_prefers_legacy_savings_total():
    hass = MagicMock()
    coord = _make_coordinator(hass)
    coord.tod_snapshot = TodSnapshot(savings_total=12.5)
    coord.rate_compare_snapshot = RateCompareSnapshot(attributes={"savings": 25.0})
    payload = _tod_payload(coord)
    assert payload["savings_total"] == 12.5
    assert payload["savings_source"] == "pricing_plan"
    assert payload["rate_compare"]["savings"] == 25.0


def test_tod_payload_falls_back_to_rate_compare_savings():
    hass = MagicMock()
    coord = _make_coordinator(hass)
    coord.tod_snapshot = None
    coord.rate_compare_snapshot = RateCompareSnapshot(
        fetched_at=datetime(2026, 8, 10, 16, tzinfo=UTC),
        attributes={
            "savings": 25.0,
            "touTotal": 150.0,
            "basicTotal": 175.0,
            "comparisonPeriod": "2026-01 to 2026-07",
        },
    )
    payload = _tod_payload(coord)
    assert payload["savings_total"] == 25.0
    assert payload["savings_source"] == "rate_compare"
    assert payload["rate_compare"] == {
        "savings": 25.0,
        "tou_total": 150.0,
        "basic_total": 175.0,
        "comparison_period": "2026-01 to 2026-07",
        "fetched_at": "2026-08-10T16:00:00+00:00",
    }


def test_tod_payload_empty_rate_compare_hidden():
    hass = MagicMock()
    coord = _make_coordinator(hass)
    coord.tod_snapshot = None
    coord.rate_compare_snapshot = RateCompareSnapshot()
    payload = _tod_payload(coord)
    assert payload["savings_total"] is None
    assert payload["savings_source"] is None
    assert payload["rate_compare"] is None


def test_tod_enrolled_from_programs_snapshot_dataclass():
    """Live coordinators store ProgramsSnapshot, not a program-id mapping."""
    assert _tod_enrolled_from_programs(None) is None
    assert _tod_enrolled_from_programs(ProgramsSnapshot(time_of_day_enrolled=False)) is False
    assert _tod_enrolled_from_programs(ProgramsSnapshot(time_of_day_enrolled=True)) is True
    assert _tod_enrolled_from_programs(ProgramsSnapshot()) is None


def test_tod_payload_survives_programs_snapshot_dataclass():
    """Regression: treating ProgramsSnapshot as a dict crashed /pge (Unknown error)."""
    hass = MagicMock()
    hass.data = {}
    coord = _make_coordinator(hass)
    coord.programs_snapshot = ProgramsSnapshot(time_of_day_enrolled=False)
    payload = _tod_payload(coord)
    assert payload["enrolled"] is False


def test_websocket_accounts_with_programs_snapshot():
    hass = MagicMock()
    coord = _make_coordinator(hass)
    coord.programs_snapshot = ProgramsSnapshot(time_of_day_enrolled=False)
    hass.data = {DOMAIN: {"entry1": coord}}

    connection = MagicMock()
    device = MagicMock()
    device.id = "device-1"

    with (
        patch(
            "custom_components.pge_energy.websocket.dr.async_get",
            return_value=MagicMock(async_get_device=MagicMock(return_value=device)),
        ),
        patch(
            "custom_components.pge_energy.websocket.er.async_get",
            return_value=MagicMock(
                async_get_entity_id=MagicMock(side_effect=lambda platform, domain, uid: f"{platform}.{uid}")
            ),
        ),
    ):
        websocket_accounts(hass, connection, {"id": 11, "type": f"{DOMAIN}/accounts"})

    connection.send_result.assert_called_once()
    _msg_id, payload = connection.send_result.call_args.args
    assert payload["accounts"][0]["tod"]["enrolled"] is False
