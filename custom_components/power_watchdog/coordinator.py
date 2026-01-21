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
    CONF_NOTIFY_ON_START,
    DEFAULT_NOTIFY_ON_START,
    CONF_REFRESH_SECONDS,
    DEFAULT_REFRESH_SECONDS,
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
        parts.append(f"{hours}г")
    if minutes:
        parts.append(f"{minutes}хв")
    parts.append(f"{secs}с")
    return " ".join(parts)


class PowerWatchdogCoordinator(DataUpdateCoordinator[WatchdogData]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name="power_watchdog",
            update_interval=None,
        )
        self.entry = entry
        self._unsub = None
        self._unsub_timer = None
        self._pending_task: asyncio.Task | None = None

        self._stale_timeout = int(entry.data.get(CONF_STALE_TIMEOUT_SECONDS, DEFAULT_STALE_TIMEOUT_SECONDS))
        self._check_interval = 15

        self._voltage_entity_id = (
            entry.data.get(CONF_VOLTAGE_ENTITY_ID)
            or entry.data.get(CONF_ENTITY_ID)
        )

        self._token = entry.data[CONF_TELEGRAM_TOKEN]
        self._chat_id = entry.data[CONF_TELEGRAM_CHAT_ID]
        self._debounce = int(entry.data.get(CONF_DEBOUNCE_SECONDS, DEFAULT_DEBOUNCE_SECONDS))
        self._notify_on_start = bool(entry.data.get(CONF_NOTIFY_ON_START, DEFAULT_NOTIFY_ON_START))

        # Пробуем принудительно обновлять сущность, когда оффлайн
        self._probe_when_offline = True
        self._probe_every = 20
        self._last_probe_ts = 0.0

        # Таймеры длительности
        self._online_since = None
        self._offline_since = None

        self._refresh_every = int(entry.data.get(CONF_REFRESH_SECONDS, DEFAULT_REFRESH_SECONDS))
        self._last_refresh_ts = 0.0

    def _get_report_time(self, st) -> object:
        rep = getattr(st, "last_reported", None)
        return rep or st.last_updated

    def _compute_online(self) -> tuple[bool, str | None, float | None]:
        st = self.hass.states.get(self._voltage_entity_id)
        if st is None:
            return (False, None, None)

        online = _is_online(st.state)

        age = (dt_util.utcnow() - self._get_report_time(st)).total_seconds()
        if online and self._stale_timeout > 0 and age > self._stale_timeout:
            return (False, st.state, age)

        return (online, st.state, age)

    def _sync_data_without_notify(self, online: bool, state: str | None) -> None:
        """Обновить coordinator.data без отправки сообщений (для дедупликации)."""
        self.async_set_updated_data(
            WatchdogData(
                online=online,
                watched_entity_id=self._voltage_entity_id,
                state=state,
            )
        )

    async def async_start(self) -> None:
        online, state, age = self._compute_online()
        now = dt_util.utcnow()

        if online:
            self._online_since = now
            self._offline_since = None
        else:
            self._offline_since = now
            self._online_since = None

        self._sync_data_without_notify(online, state)

        # Сообщение при запуске интеграции
        if self._notify_on_start:
            title = "🟦 Бот було перезапущено"
            status = "✅ Зараз: світло є" if online else "❌ Зараз: світла немає"
            extra = ""
            if age is not None:
                extra = f"Дані оновлювались: {int(age)}с тому\n"

            voltage_line = ""
            if state is not None and state not in OFFLINE_STATES:
                voltage_line = f"Напруга: {state} В\n"
            elif state in OFFLINE_STATES:
                voltage_line = f"Напруга: {state} В\n"

            if online:
                text = (
                    f"{title}\n\n"
                    f"{status}\n"
                    f"{extra}"
                    f"Пристрій: {self._voltage_entity_id}\n"
                    f"{voltage_line}"
                )
            else:
                text = (
                    f"{title}\n\n"
                    f"{status}\n"
                    f"Пристрій: {self._voltage_entity_id}\n"
                )
            self.hass.async_create_task(
                async_send_telegram(self.hass, self._token, self._chat_id, text)
            )

        @callback
        def _handle(event):
            old_state = event.data.get("old_state")
            new_state = event.data.get("new_state")

            new_state_str = new_state.state if new_state else None
            new_online = _is_online(new_state_str)

            # ✅ ДЕДУПЛИКАЦИЯ: если интеграция уже в этом состоянии — не шлём сообщение
            if self.data is not None and self.data.online == new_online:
                # но обновим state, чтобы в атрибутах было актуально (например 224.2 -> unavailable)
                self._sync_data_without_notify(new_online, new_state_str)
                return

            if self._pending_task and not self._pending_task.done():
                self._pending_task.cancel()

            self._pending_task = self.hass.async_create_task(
                self._debounced_commit_and_notify(
                    new_online=new_online,
                    reason="state_change",
                    old_state=(old_state.state if old_state else None),
                    new_state=new_state_str,
                )
            )

        self._unsub = async_track_state_change_event(
            self.hass,
            [self._voltage_entity_id],
            _handle
        )

        self._unsub_timer = async_track_time_interval(
            self.hass,
            self._periodic_check,
            timedelta(seconds=self._check_interval)
        )

    async def _periodic_check(self, _now) -> None:
        # Если сейчас оффлайн — пробуем обновить voltage sensor
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

        now_ts = time.time()

        if self._refresh_every > 0 and (now_ts - self._last_refresh_ts >= self._refresh_every):
            self._last_refresh_ts = now_ts
            try:
                await self.hass.services.async_call(
                    "homeassistant",
                    "update_entity",
                    {"entity_id": self._voltage_entity_id},
                    blocking=True,
                )
            except Exception:
                _LOGGER.exception("update_entity refresh failed")

        online, state, age = self._compute_online()
        current = self.data.online if self.data else None
        if current is None:
            return

        # Если состояние не изменилось — просто синхронизируем state и выходим
        if online == current:
            if self.data.state != state:
                self._sync_data_without_notify(online, state)
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

            current_online, current_state, age = self._compute_online()
            if current_online != new_online:
                return

            prev_online = self.data.online if self.data else None
            now = dt_util.utcnow()

            # Если по какой-то причине уже синхронизированы — не шлём повторно
            if prev_online is not None and prev_online == new_online:
                self._sync_data_without_notify(new_online, current_state)
                return

            duration_line = None
            extra = ""

            if prev_online is not None and prev_online != new_online:
                if prev_online and (not new_online):
                    # online -> offline
                    online_for = (now - self._online_since).total_seconds() if self._online_since else None
                    duration_line = _format_duration(online_for)
                    self._offline_since = now
                    self._online_since = None
                    if duration_line:
                        extra = f"Світло було: {duration_line}\n"
                elif (not prev_online) and new_online:
                    # offline -> online
                    offline_for = (now - self._offline_since).total_seconds() if self._offline_since else None
                    duration_line = _format_duration(offline_for)
                    self._online_since = now
                    self._offline_since = None
                    if duration_line:
                        extra = f"Світла не було: {duration_line}\n"
            else:
                # первая инициализация
                if new_online:
                    self._online_since = now
                    self._offline_since = None
                else:
                    self._offline_since = now
                    self._online_since = None

            # Обновляем данные
            self._sync_data_without_notify(new_online, current_state)

            # Текст сообщения (как у тебя на скринах)
            title = "✅ Світло є" if new_online else "❌ Світло зникло"

            reason_line = f"Reason: {reason}"
            if reason == "stale_timeout" and age is not None:
                reason_line += f" (no updates for {int(age)}s)"

            voltage_line = ""
            if current_state is not None:
                # Если число — добавляем "В", если unavailable/unknown — тоже покажем
                if current_state in OFFLINE_STATES:
                    voltage_line = f"Напруга: {current_state} В\n"
                else:
                    voltage_line = f"Напруга: {current_state} В\n"

            text = (
                f"{title}\n\n"
                f"{extra}"
                # f"{reason_line}\n"
                # f"Пристрій: {self._voltage_entity_id}\n"
                f"{voltage_line}"
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
