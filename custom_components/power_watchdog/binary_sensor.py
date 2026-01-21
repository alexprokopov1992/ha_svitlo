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
        data: WatchdogData = self.coordinator.data
        return bool(data.online)

    @property
    def extra_state_attributes(self):
        data: WatchdogData = self.coordinator.data
        return {
            "watched_entity_id": data.watched_entity_id,
            "watched_state": data.state,
        }
