from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

async def async_send_telegram(
    hass: HomeAssistant,
    token: str,
    chat_id: str,
    text: str,
) -> None:
    session = async_get_clientsession(hass)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }

    try:
        resp = await session.post(url, json=payload, timeout=15)
        if resp.status != 200:
            body = await resp.text()
            _LOGGER.error("Telegram send failed: %s %s", resp.status, body)
    except Exception:
        _LOGGER.exception("Telegram send exception")
