from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import PowerWatchdogCoordinator

PLATFORMS = ["binary_sensor"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = PowerWatchdogCoordinator(hass, entry)
    await coordinator.async_start()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator: PowerWatchdogCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
    await coordinator.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
