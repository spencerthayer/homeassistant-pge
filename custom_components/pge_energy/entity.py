from __future__ import annotations

from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PGECoordinator
from .options import pge_display_name


class PGEBaseEntity(CoordinatorEntity[PGECoordinator], Entity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: PGECoordinator) -> None:
        super().__init__(coordinator)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.account_key)},
            "name": pge_display_name(coordinator.account_id),
            "manufacturer": "Portland General Electric",
            "model": coordinator.account_id,
        }

    @property
    def available(self) -> bool:
        """Stay available after auth/sync errors when last-known values remain.

        CoordinatorEntity defaults to ``last_update_success``, which flips sensors
        to ``unavailable`` on any failed poll — even though recorder history and
        in-memory billing/usage snapshots are still intact. Prefer retained state
        so the panel and Energy dashboard keep showing downloaded data.
        """
        if self.coordinator.last_update_success:
            return True
        return self.coordinator.has_retained_state
