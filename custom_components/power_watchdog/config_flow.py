from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_TELEGRAM_TOKEN,
    CONF_TELEGRAM_CHAT_ID,
    CONF_ENTITY_ID,
    CONF_DEBOUNCE_SECONDS,
    DEFAULT_DEBOUNCE_SECONDS,
)

class PowerWatchdogConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            await self.async_set_unique_id(f"power_watchdog::{user_input[CONF_ENTITY_ID]}")
            self._abort_if_unique_id_configured()
            title = f"Power Watchdog: {user_input[CONF_ENTITY_ID]}"
            return self.async_create_entry(title=title, data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_TELEGRAM_TOKEN): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
                vol.Required(CONF_TELEGRAM_CHAT_ID): selector.TextSelector(),
                vol.Required(CONF_ENTITY_ID): selector.EntitySelector(selector.EntitySelectorConfig()),
                vol.Optional(CONF_DEBOUNCE_SECONDS, default=DEFAULT_DEBOUNCE_SECONDS): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=120, step=1, mode=selector.NumberSelectorMode.BOX)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)
