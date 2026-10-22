from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.pge_energy import device_lookup
from custom_components.pge_energy.device_lookup import async_device_for_entry

ACCOUNT_KEY = "abcdabcdabcdabcd"
ENTRY_ID = "entry1"
IDENTIFIER = (device_lookup.DOMAIN, ACCOUNT_KEY)


class _EntryAwareRegistry:
    def __init__(self, device):
        self.device = device
        self.calls: list[tuple[tuple[str, str], str]] = []

    def async_get_device_by_identifier(self, identifier, config_entry_id):
        self.calls.append((identifier, config_entry_id))
        return self.device


class _LegacyRegistry:
    def __init__(self, device):
        self.device = device
        self.calls: list[set[tuple[str, str]]] = []

    def async_get_device(self, identifiers=None, connections=None):
        self.calls.append(identifiers)
        return self.device


@pytest.fixture
def patch_registry(hass, monkeypatch):
    def _patch(registry):
        monkeypatch.setattr(device_lookup.dr, "async_get", lambda _hass: registry)
        return registry

    return _patch


def test_uses_per_entry_lookup_when_available(hass, patch_registry):
    device = SimpleNamespace(id="device-1")
    registry = patch_registry(_EntryAwareRegistry(device))

    assert async_device_for_entry(hass, ENTRY_ID, ACCOUNT_KEY) is device
    assert registry.calls == [(IDENTIFIER, ENTRY_ID)]


def test_falls_back_to_registry_wide_lookup(hass, patch_registry):
    device = SimpleNamespace(id="device-1")
    registry = patch_registry(_LegacyRegistry(device))

    assert async_device_for_entry(hass, ENTRY_ID, ACCOUNT_KEY) is device
    assert registry.calls == [{IDENTIFIER}]


def test_returns_none_when_device_is_missing(hass, patch_registry):
    patch_registry(_EntryAwareRegistry(None))

    assert async_device_for_entry(hass, ENTRY_ID, ACCOUNT_KEY) is None
