"""Entities stay available when the coordinator has retained downloaded state."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.pge_energy.entity import PGEBaseEntity


def test_available_when_last_update_failed_but_retained():
    coordinator = MagicMock()
    coordinator.last_update_success = False
    coordinator.has_retained_state = True
    coordinator.account_key = "key"
    coordinator.account_id = "acct"

    entity = PGEBaseEntity(coordinator)
    assert entity.available is True


def test_unavailable_only_without_retained_state_after_failure():
    coordinator = MagicMock()
    coordinator.last_update_success = False
    coordinator.has_retained_state = False
    coordinator.account_key = "key"
    coordinator.account_id = "acct"

    entity = PGEBaseEntity(coordinator)
    assert entity.available is False


def test_available_when_last_update_succeeded():
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.has_retained_state = False
    coordinator.account_key = "key"
    coordinator.account_id = "acct"

    entity = PGEBaseEntity(coordinator)
    assert entity.available is True
