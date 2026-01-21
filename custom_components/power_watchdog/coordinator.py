from __future__ import annotations

import time
import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DEBOUNCE_SECONDS,
    CONF_ENTITY_ID,                # fallback (старый ключ)
    CONF_VOLTAGE_ENTITY_ID,        # новый ключ
    CONF_TELEGRAM_CHAT_ID,
    CONF_TELEGRAM_TOKEN,
    DEFAULT_DEBOUNCE_SECONDS,
    OFFLINE_STATES,
    CONF_STALE_TIMEOUT_SECONDS,
    DEFAULT_STALE_TIMEOUT_SECONDS,
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


def _format_duration(seconds: float | None) -> str | None:
    """Human-friendly duration like '2ч 3м 10с'."""
    if seconds is None:
        return None
    if seconds < 0:
        seconds = 0

    total = int(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)

    parts = []
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    if minutes:
        parts.append(f"{minutes}м")
    parts.append(f"{secs}с")
    return " ".join(parts)


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
        self._unsub_timer = None
        self._pending_task: asyncio.Task | None = None

        self._stale_timeout = int(entry.data.get(CONF_STALE_TIMEOUT_SECONDS, DEFAULT_STALE_TIMEOUT_SECONDS))
        self._check_interval = 15

        # Контролируем voltage sensor.
        # Фолбэк на старый key, если entry создан раньше.
        self._voltage_entity_id = (
            entry.data.get(CONF_VOLTAGE_ENTITY_ID)
            or entry.data.get(CONF_ENTITY_ID)
        )

        self._token = entry.data[CONF_TELEGRAM_TOKEN]
        self._chat_id = entry.data[CONF_TELEGRAM_CHAT_ID]
        self._debounce = int(entry.data.get(CONF_DEBOUNCE_SECONDS, DEFAULT_DEBOUNCE_SECONDS))

        # Пробуем принудительно обновлять сущность, когда оффлайн
        self._probe_when_offline = True
        self._probe_every = 20
        self._last_probe_ts = 0.0

        # Таймеры длительности
        self._online_since = None  # datetime
        self._offline_since = None  # datetime

    def _get_report_time(self, st) -> object:
        """
        В новых версиях HA есть st.last_reported — он лучше для heartbeat.
        Если его нет, используем last_updated.
        """
        rep = getattr(st, "last_reported", None)
        return rep or st.last_updated

    def _compute_online(self) -> tuple[bool, str | None, float | None]:
        st = self.hass.states.get(self._voltage_entity_id)
        if st is None:
            return (False, None, None)

        # Базовая проверка unavailable/unknown/offline
        online = _is_online(st.state)

        # stale timeout: если давно не было обновлений — считаем оффлайн
        age = (dt_util.utcnow() - self._get_report_time(st)).total_seconds()
        if online and self._stale_timeout > 0 and age > self._stale_timeout:
            return (False, st.state, age)

        return (online, st.state, age)

    async def async_start(self) -> None:
        online, state, _age = self._compute_online()
        now = dt_util.utcnow()

        # Инициализируем таймеры
        if online:
            self._online_since = now
            self._offline_since = None
        else:
            self._offline_since = now
            self._online_since = None

        self.async_set_updated_data(
            WatchdogData(
                online=online,
                watched_entity_id=self._voltage_entity_id,
                state=state,
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
                    reason="state_change",
                    old_state=(old_state.state if old_state else None),
                    new_state=(new_state.state if new_state else None),
                )
            )

        # Слушаем изменения именно voltage sensor
        self._unsub = async_track_state_change_event(
            self.hass,
            [self._voltage_entity_id],
            _handle
        )

        # Периодическая проверка stale + probe
        self._unsub_timer = async_track_time_interval(
            self.hass,
            self._periodic_check,
            timedelta(seconds=self._check_interval)
        )

    async def _periodic_check(self, _now) -> None:
        # Если сейчас оффлайн — попробуем принудительно обновить voltage sensor
        if self.data and self._probe_when_offline and (not self.data.online):
            now_ts = time.time()
            if now_ts - self._last_probe_ts >= self._probe_every:
                self._last_probe_ts = now_ts
                try:
                    await self.hass.services.async_call(
                        "homeassistant",
                        "update_entity",
                        {"entity_id": self._voltage_entity_id},
                        blocking=True,
                    )
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("update_entity probe failed")

        # После возможного обновления пересчитываем online
        online, state, age = self._compute_online()
        current = self.data.online if self.data else None
        if current is None or online == current:
            return

        if self._pending_task and not self._pending_task.done():
            self._pending_task.cancel()

        reason = "probe_recovered" if online else (
            "stale_timeout" if (age is not None and self._stale_timeout > 0 and age > self._stale_timeout)
            else "periodic"
        )

        self._pending_task = self.hass.async_create_task(
            self._debounced_commit_and_notify(
                new_online=online,
                reason=reason,
                old_state=self.data.state,
                new_state=state,
            )
        )

    async def _debounced_commit_and_notify(
        self,
        new_online: bool,
        reason: str,
        old_state: str | None,
        new_state: str | None
    ) -> None:
        try:
            if self._debounce > 0:
                await asyncio.sleep(self._debounce)

            # перепроверяем текущий online
            current_online, current_state, age = self._compute_online()
            if current_online != new_online:
                return

            prev_online = self.data.online if self.data else None
            now = dt_util.utcnow()

            # Посчитать длительность и обновить "since"-таймеры
            duration_line = None

            if prev_online is not None and prev_online != new_online:
                if prev_online and (not new_online):
                    # online -> offline
                    online_for = (now - self._online_since).total_seconds() if self._online_since else None
                    duration_line = _format_duration(online_for)
                    self._offline_since = now
                    self._online_since = None
                elif (not prev_online) and new_online:
                    # offline -> online
                    offline_for = (now - self._offline_since).total_seconds() if self._offline_since else None
                    duration_line = _format_duration(offline_for)
                    self._online_since = now
                    self._offline_since = None
            else:
                # Если это первая инициализация/без перехода — просто синхронизируем таймеры
                if new_online and self._online_since is None:
                    self._online_since = now
                    self._offline_since = None
                if (not new_online) and self._offline_since is None:
                    self._offline_since = now
                    self._online_since = None

            # Обновляем данные для binary_sensor
            self.async_set_updated_data(
                WatchdogData(
                    online=new_online,
                    watched_entity_id=self._voltage_entity_id,
                    state=current_state
                )
            )

            title = "✅ Свет/связь ЕСТЬ (устройство онлайн)" if new_online else "❌ Свет/связи НЕТ (устройство оффлайн)"
            reason_line = f"Reason: {reason}"
            if reason == "stale_timeout" and age is not None:
                reason_line += f" (no updates for {int(age)}s)"

            # Длительности в сообщение
            extra = ""
            if prev_online is not None and prev_online != new_online and duration_line:
                if new_online:
                    extra = f"Света не было: {duration_line}\n"
                else:
                    extra = f"Свет был: {duration_line}\n"

            text = (
                f"{title}\n\n"
                f"{extra}"
                f"{reason_line}\n"
                f"Entity: {self._voltage_entity_id}\n"
                f"Old: {old_state}\n"
                f"New: {new_state}\n"
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

        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
