from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_DEBOUNCE_SECONDS,
    CONF_ENTITY_ID,
    CONF_TELEGRAM_CHAT_ID,
    CONF_TELEGRAM_TOKEN,
    DEFAULT_DEBOUNCE_SECONDS,
    OFFLINE_STATES,
)
from .telegram import async_send_telegram

_LOGGER = logging.getLogger(__name__)

@dataclass(frozen=True)
class WatchdogData:
    online: bool
    watched_entity_id: str
    state: str | None

def _is_online(state_str: str | None) -> bool:
    if state_str is None:
        return False
    return state_str not in OFFLINE_STATES

class PowerWatchdogCoordinator(DataUpdateCoordinator[WatchdogData]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name="power_watchdog",
            update_interval=None,  # push-only
        )
        self.entry = entry
        self._unsub = None
        self._pending_task: asyncio.Task | None = None

        self._entity_id = entry.data[CONF_ENTITY_ID]
        self._token = entry.data[CONF_TELEGRAM_TOKEN]
        self._chat_id = entry.data[CONF_TELEGRAM_CHAT_ID]
        self._debounce = int(entry.data.get(CONF_DEBOUNCE_SECONDS, DEFAULT_DEBOUNCE_SECONDS))

    async def async_start(self) -> None:
        st = self.hass.states.get(self._entity_id)
        online = _is_online(st.state if st else None)
        self.async_set_updated_data(
            WatchdogData(
                online=online,
                watched_entity_id=self._entity_id,
                state=st.state if st else None,
            )
        )

        @callback
        def _handle(event):
            old_state = event.data.get("old_state")
            new_state = event.data.get("new_state")
            old_online = _is_online(old_state.state if old_state else None)
            new_online = _is_online(new_state.state if new_state else None)

            if old_online == new_online:
                return

            if self._pending_task and not self._pending_task.done():
                self._pending_task.cancel()

            self._pending_task = self.hass.async_create_task(
                self._debounced_commit_and_notify(
                    new_online=new_online,
                    old_state=(old_state.state if old_state else None),
                    new_state=(new_state.state if new_state else None),
                )
            )

        self._unsub = async_track_state_change_event(self.hass, [self._entity_id], _handle)

    async def _debounced_commit_and_notify(self, new_online: bool, old_state: str | None, new_state: str | None) -> None:
        try:
            if self._debounce > 0:
                await asyncio.sleep(self._debounce)

            st = self.hass.states.get(self._entity_id)
            current_online = _is_online(st.state if st else None)
            if current_online != new_online:
                return

            self.async_set_updated_data(
                WatchdogData(
                    online=new_online,
                    watched_entity_id=self._entity_id,
                    state=st.state if st else None,
                )
            )

            title = "✅ Світло є" if new_online else "❌ Світло зникло"
            text = (
                f"{title}\n\n"
                # f"Пристрій: {self._entity_id}\n"
            )
            await async_send_telegram(self.hass, self._token, self._chat_id, text)
        except asyncio.CancelledError:
            return

    async def async_stop(self) -> None:
        if self._pending_task and not self._pending_task.done():
            self._pending_task.cancel()

        if self._unsub:
            self._unsub()
            self._unsub = None
