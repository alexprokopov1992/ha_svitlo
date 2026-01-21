DOMAIN = "power_watchdog"

CONF_TELEGRAM_TOKEN = "telegram_token"
CONF_TELEGRAM_CHAT_ID = "telegram_chat_id"

# Старый ключ (оставляем для обратной совместимости)
CONF_ENTITY_ID = "entity_id"

# Новый ключ: теперь контролируем именно датчик напряжения (sensor.*voltage)
CONF_VOLTAGE_ENTITY_ID = "voltage_entity_id"

CONF_DEBOUNCE_SECONDS = "debounce_seconds"
DEFAULT_DEBOUNCE_SECONDS = 10

OFFLINE_STATES = {"unavailable", "unknown", "offline"}

CONF_STALE_TIMEOUT_SECONDS = "stale_timeout_seconds"
DEFAULT_STALE_TIMEOUT_SECONDS = 120  # 2 минуты
