from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PowerWatchdogCoordinator, WatchdogData

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    coordinator: PowerWatchdogCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PowerWatchdogOnlineSensor(coordinator, entry)])

class PowerWatchdogOnlineSensor(CoordinatorEntity[PowerWatchdogCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Online"
    _attr_icon = "mdi:flash"

    def __init__(self, coordinator: PowerWatchdogCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_online"

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data
        return bool(data.online) if data else False

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data
        return {
            "watched_entity_id": data.watched_entity_id if data else None,
            "watched_state": data.state if data else None,
            "last_online_at": self.coordinator._last_online_at.isoformat() if self.coordinator._last_online_at else None,
            "last_offline_at": self.coordinator._last_offline_at.isoformat() if self.coordinator._last_offline_at else None,
        }
