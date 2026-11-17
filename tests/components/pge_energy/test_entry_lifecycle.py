"""Reload admission, options-only reload, and stalled-write poll deferral.

These tests drive the real config-entry update dispatcher. Network login is
stubbed. They do not talk to PGE.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_test_home_assistant,
)

from custom_components.pge_energy import (
    _async_post_setup_body,
    async_migrate_entry,
)
from custom_components.pge_energy.config_flow import PGEConfigFlow, PGEOptionsFlow
from custom_components.pge_energy.const import (
    AUTH_MODE_CREDENTIAL,
    CONF_ACCOUNT_ID,
    CONF_ACCOUNT_KEY,
    CONF_AUTH_MODE,
    CONF_BEARER_TOKEN,
    CONF_EMAIL,
    CONF_ENCRYPTED_PERSON_ID,
    CONF_PASSWORD,
    CONF_POLLING_INTERVAL,
    DOMAIN,
)
from custom_components.pge_energy.coordinator import (
    PGECoordinator,
    claim_refresh_admission,
    clear_refresh_admission,
)
from custom_components.pge_energy.exceptions import PGEConnectionError
from custom_components.pge_energy.portal_auth import PortalAuthResult
from custom_components.pge_energy.store import ImportStoreData

_ENTRY_DATA = {
    CONF_AUTH_MODE: AUTH_MODE_CREDENTIAL,
    CONF_BEARER_TOKEN: "old-token",
    CONF_ENCRYPTED_PERSON_ID: "enc-person",
    CONF_ACCOUNT_ID: "1071234567",
    CONF_ACCOUNT_KEY: "abcd1234abcd1234",
    CONF_EMAIL: "user@example.com",
}


def _add_entry(hass, *, entry_id: str = "entry1", options: dict | None = None, version: int = 2):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=dict(_ENTRY_DATA),
        options=options or {CONF_POLLING_INTERVAL: 4},
        title="PGE 1071234567",
        unique_id="1071234567",
        entry_id=entry_id,
        version=version,
    )
    entry.add_to_hass(hass)
    return entry


async def _stop_hass(hass) -> None:
    """Stop the test instance before pytest closes the loop."""
    await hass.async_stop(force=True)
    await hass.async_block_till_done()
    await asyncio.get_running_loop().shutdown_default_executor()


def _arm(hass, *entries) -> list[str]:
    """Attach listeners without HA's debounced entry-store write.

    That delayed write crashes CPython 3.14 during interpreter shutdown in
    this test process. The update listeners still run inside
    ``async_update_entry``.
    """
    from custom_components.pge_energy import _attach_update_listener

    hass.config_entries._async_schedule_save = lambda: None
    for entry in entries:
        _attach_update_listener(entry)
    return _count_reloads(hass)


def _count_reloads(hass) -> list[str]:
    reloads: list[str] = []

    async def _reload(entry_id: str) -> bool:
        reloads.append(entry_id)
        return True

    hass.config_entries.async_reload = _reload
    return reloads


async def test_token_updates_do_not_reload():
    """Data-only writes, including ones from a replaced coordinator, do not reload."""
    async with async_test_home_assistant(load_registries=False) as hass:
        entry = _add_entry(hass)
        reloads = _arm(hass, entry)
        hass.data[DOMAIN] = {"entry1": object()}

        for token in ("t1", "t2"):
            hass.config_entries.async_update_entry(
                entry,
                data={**entry.data, CONF_BEARER_TOKEN: token},
            )
        assert reloads == []

        # The listener no longer consults whichever coordinator is registered.
        hass.data[DOMAIN]["entry1"] = object()
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_BEARER_TOKEN: "from-replacement"},
        )
        hass.data[DOMAIN].pop("entry1")
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_BEARER_TOKEN: "from-nobody"},
        )
        hass.config_entries.async_update_entry(entry, title="Renamed")
        hass.config_entries.async_update_entry(entry, options=dict(entry.options))
        assert reloads == []

        stale = MockConfigEntry(
            domain=DOMAIN,
            data={CONF_ACCOUNT_ID: "1071234567", CONF_ENCRYPTED_PERSON_ID: "enc-person"},
            title="old",
            entry_id="migrate-entry",
            version=1,
        )
        stale.add_to_hass(hass)
        from custom_components.pge_energy import _attach_update_listener

        _attach_update_listener(stale)
        assert await async_migrate_entry(hass, stale) is True
        assert reloads == []
        await _stop_hass(hass)


async def test_token_updates_queued_listener_does_not_reload():
    """A listener queued behind a newer setup cannot reload after its generation retires."""
    from custom_components.pge_energy import _attach_update_listener

    async with async_test_home_assistant(load_registries=False) as hass:
        entry = _add_entry(hass)
        reloads = _arm(hass, entry)
        held: list = []
        original = hass.async_create_task_internal

        def _defer_listeners(target, name=None, eager_start=True):
            if isinstance(name, str) and "config entry update listener" in name:
                held.append(target)
                future = hass.loop.create_future()
                future.set_result(None)
                return future
            return original(target, name, eager_start)

        hass.async_create_task_internal = _defer_listeners
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_BEARER_TOKEN: "queued-1"},
        )
        hass.config_entries.async_update_entry(
            entry,
            options={**entry.options, CONF_POLLING_INTERVAL: 2},
        )
        assert held
        assert reloads == []

        # A new setup retires the queued generation before those callbacks run.
        _attach_update_listener(entry)
        for pending in held:
            await pending
        assert reloads == []
        await _stop_hass(hass)


async def test_options_change_reloads_once():
    async with async_test_home_assistant(load_registries=False) as hass:
        entry = _add_entry(hass)
        other = _add_entry(hass, entry_id="entry2")
        reloads = _arm(hass, entry, other)

        hass.config_entries.async_update_entry(
            entry,
            options={**entry.options, CONF_POLLING_INTERVAL: 2},
        )
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_BEARER_TOKEN: "after-options"},
        )
        hass.config_entries.async_update_entry(
            other,
            data={**other.data, CONF_BEARER_TOKEN: "sibling"},
        )
        assert reloads == ["entry1"]
        await _stop_hass(hass)


async def test_credentials_reload_once():
    """Both explicit credential flows reload once. The listener must not add another."""
    login = PortalAuthResult(
        access_token="new-token",
        encrypted_person_id="enc-person",
        account_ids=["1071234567"],
        expires_at=None,
        refresh_credential="durable-refresh",
    )
    async with async_test_home_assistant(load_registries=False) as hass:
        entry = _add_entry(hass)
        reloads = _arm(hass, entry)
        with (
            patch(
                "custom_components.pge_energy.config_flow.portal_auth.async_login_or_refresh",
                AsyncMock(return_value=login),
            ),
            patch(
                "custom_components.pge_energy.config_flow._async_discover_billing_ids",
                AsyncMock(return_value={}),
            ),
        ):
            options = PGEOptionsFlow()
            options.hass = hass
            options.handler = entry.entry_id
            options.flow_id = "options-flow"
            result = await options.async_step_credentials(
                {
                    CONF_ACCOUNT_ID: "1071234567",
                    CONF_EMAIL: "user@example.com",
                    CONF_PASSWORD: "secret",
                }
            )
            assert result["reason"] == "credentials_updated"
            assert reloads == ["entry1"]

            reauth = PGEConfigFlow()
            reauth.hass = hass
            reauth.flow_id = "reauth-flow"
            reauth.context = {"source": "reauth", "entry_id": entry.entry_id}
            result = await reauth.async_step_reauth_credential(
                {CONF_EMAIL: "user@example.com", CONF_PASSWORD: "secret"}
            )
            assert result["reason"] == "reauth_successful"
            assert reloads == ["entry1", "entry1"]
            assert entry.data[CONF_BEARER_TOKEN] == "new-token"
        await _stop_hass(hass)


def _make_coordinator(entry_id: str = "entry1") -> PGECoordinator:
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.config_entries.async_update_entry = MagicMock()
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {
        CONF_ACCOUNT_ID: "acct",
        CONF_ACCOUNT_KEY: "keykeykeykeykeyk",
        "correction_window": 1,
    }
    auth = MagicMock()
    auth.account_key = "keykeykeykeykeyk"
    auth.auth_mode = AUTH_MODE_CREDENTIAL
    auth.ensure_valid_token = AsyncMock(return_value="tok")
    auth.persistable_auth_data = MagicMock(return_value={CONF_BEARER_TOKEN: "tok"})
    auth.cognito_rate_limit_remaining_seconds = MagicMock(return_value=0.0)
    coord = PGECoordinator(hass, entry, auth, MagicMock())
    coord._import_store = ImportStoreData(account_key="keykeykeykeykeyk")
    return coord


def _arm_retained(coord: PGECoordinator) -> None:
    """Give the poll something to keep so a forced-login failure stays soft."""
    coord.data = {"intervals": ["kept"], "failed_days": []}
    coord._recent_intervals = ["kept"]
    coord.auth_manager.ensure_valid_token = AsyncMock(side_effect=PGEConnectionError("down"))


@pytest.mark.asyncio
async def test_reload_refresh_circuit_breaker(monkeypatch, caplog):
    clock = {"now": 10_000.0}
    monkeypatch.setattr(
        "custom_components.pge_energy.coordinator._monotonic",
        lambda: clock["now"],
    )
    monkeypatch.setattr(
        "custom_components.pge_energy.coordinator.resolve_polling_timedelta",
        lambda _entry: timedelta(hours=4),
    )
    caplog.set_level(logging.ERROR, logger="custom_components.pge_energy.coordinator")
    coord = _make_coordinator("entry-loop")
    _arm_retained(coord)
    await coord._async_update_data()
    assert coord.auth_manager.ensure_valid_token.await_count == 1
    assert coord.update_interval >= timedelta(hours=4)

    for _ in range(9):
        payload = await coord._async_update_data()
        assert payload["intervals"] == ["kept"]
        assert payload["stale"] is True
    assert coord.auth_manager.ensure_valid_token.await_count == 1
    assert "PGE reload loop detected" in caplog.text

    clock["now"] += 60
    await coord._async_update_data()
    assert coord.auth_manager.ensure_valid_token.await_count == 2
    assert coord.update_interval >= timedelta(hours=4)
    await coord._async_update_data()
    assert coord.auth_manager.ensure_valid_token.await_count == 2


@pytest.mark.asyncio
async def test_reload_refresh_respects_later_deadline(monkeypatch):
    clock = {"now": 20_000.0}
    monkeypatch.setattr(
        "custom_components.pge_energy.coordinator._monotonic",
        lambda: clock["now"],
    )
    schedule = {"interval": timedelta(seconds=30)}
    monkeypatch.setattr(
        "custom_components.pge_energy.coordinator.resolve_polling_timedelta",
        lambda _entry: schedule["interval"],
    )
    coord = _make_coordinator("entry-deadline")
    _arm_retained(coord)
    coord.auth_manager.cognito_rate_limit_remaining_seconds.return_value = 900.0
    await coord._async_update_data()
    assert coord.update_interval >= timedelta(seconds=900)

    clear_refresh_admission("entry-deadline")
    schedule["interval"] = timedelta(hours=4)
    coord.auth_manager.cognito_rate_limit_remaining_seconds.return_value = 120.0
    await coord._async_update_data()
    assert coord.update_interval >= timedelta(hours=4)


@pytest.mark.asyncio
async def test_reload_refresh_entries_are_independent(monkeypatch):
    clock = {"now": 30_000.0}
    monkeypatch.setattr(
        "custom_components.pge_energy.coordinator._monotonic",
        lambda: clock["now"],
    )
    monkeypatch.setattr(
        "custom_components.pge_energy.coordinator.resolve_polling_timedelta",
        lambda _entry: timedelta(hours=4),
    )
    first = _make_coordinator("entry-a")
    second = _make_coordinator("entry-b")
    _arm_retained(first)
    _arm_retained(second)
    await first._async_update_data()
    await second._async_update_data()
    assert first.auth_manager.ensure_valid_token.await_count == 1
    assert second.auth_manager.ensure_valid_token.await_count == 1
    await first._async_update_data()
    await second._async_update_data()
    assert first.auth_manager.ensure_valid_token.await_count == 1
    assert second.auth_manager.ensure_valid_token.await_count == 1


@pytest.mark.asyncio
async def test_reload_refresh_post_setup_admits_once(monkeypatch, caplog):
    clock = {"now": 40_000.0}
    monkeypatch.setattr(
        "custom_components.pge_energy.coordinator._monotonic",
        lambda: clock["now"],
    )
    caplog.set_level(logging.ERROR, logger="custom_components.pge_energy.coordinator")
    scheduled: list[float] = []
    cancelled = {"n": 0}

    def _later(_hass, delay, _action):
        scheduled.append(delay)

        def _cancel() -> None:
            cancelled["n"] += 1

        return _cancel

    monkeypatch.setattr("custom_components.pge_energy.async_call_later", _later)
    refreshes: list[str] = []
    hass = MagicMock()
    hass.data = {DOMAIN: {}}

    def _install(entry_id: str) -> PGECoordinator:
        coord = _make_coordinator(entry_id)
        coord.hass = hass

        async def _refresh() -> None:
            refreshes.append(entry_id)

        coord.async_config_entry_first_refresh = _refresh
        coord.async_start_tod = AsyncMock()
        coord.async_start_ptr = AsyncMock()
        coord.async_repair_dirty_if_needed = AsyncMock()
        coord.async_repair_coarse_fine_if_needed = AsyncMock()
        coord.async_refresh_lifetime_totals = AsyncMock()
        hass.data[DOMAIN][entry_id] = coord
        return coord

    entry = MagicMock()
    entry.entry_id = "entry-setup"
    with (
        patch("custom_components.pge_energy.async_cleanup_orphaned_billing_entity_mirrors", AsyncMock()),
        patch("custom_components.pge_energy.async_clear_bill_avg_temp_entity_statistics", AsyncMock()),
        patch("custom_components.pge_energy.async_migrate_signed_usage_split", AsyncMock()),
        patch("custom_components.pge_energy._async_maybe_start_auto_backfill", AsyncMock()),
    ):
        for _ in range(10):
            coord = _install("entry-setup")
            await _async_post_setup_body(hass, entry, coord)
        other = _install("entry-other")
        other_entry = MagicMock()
        other_entry.entry_id = "entry-other"
        await _async_post_setup_body(hass, other_entry, other)

    assert refreshes == ["entry-setup", "entry-other"]
    assert "PGE reload loop detected" in caplog.text
    # Nine suppressed reloads of the first entry replace one timer; the other
    # entry was admitted and did not schedule one.
    assert len(scheduled) == 9
    assert cancelled["n"] == 8
    assert scheduled[-1] > 0


@pytest.mark.asyncio
async def test_storage_cooldown_suppresses_poll(monkeypatch, caplog):
    monkeypatch.setattr(
        "custom_components.pge_energy.coordinator.import_state_backoff_remaining",
        lambda _entry_id: 45.0,
    )
    monkeypatch.setattr(
        "custom_components.pge_energy.coordinator.resolve_polling_timedelta",
        lambda _entry: timedelta(hours=4),
    )
    caplog.set_level(logging.WARNING, logger="custom_components.pge_energy.coordinator")
    coord = _make_coordinator("entry-stall")
    coord.data = {"intervals": ["kept"], "failed_days": []}
    coord._recent_intervals = ["kept"]
    payload = await coord._async_update_data()
    assert payload["intervals"] == ["kept"]
    coord.auth_manager.ensure_valid_token.assert_not_awaited()
    assert "PGE import state save still stalled" in caplog.text
    assert "PGE reload loop detected" not in caplog.text
    assert timedelta(seconds=40) <= coord.update_interval <= timedelta(seconds=45)
    assert claim_refresh_admission("entry-stall") is True
