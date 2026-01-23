from __future__ import annotations

import asyncio
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

SVITLOBOT_PING_URL = "https://api.svitlobot.in.ua/channelPing?channel_key={channel_key}"


async def async_channel_ping(hass: HomeAssistant, channel_key: str, timeout_s: int = 5) -> None:
    """Ping svitlobot channel. Safe: never raises outward."""
    if not channel_key:
        return

    url = SVITLOBOT_PING_URL.format(channel_key=channel_key)

    session = async_get_clientsession(hass)

    try:
        async with asyncio.timeout(timeout_s):
            async with session.get(url) as resp:
                # We don't care about body; just ensure request is done
                if resp.status >= 400:
                    _LOGGER.warning("SvitloBot channelPing failed: HTTP %s", resp.status)
    except Exception as e:  # noqa: BLE001
        _LOGGER.debug("SvitloBot channelPing exception: %s", e)
