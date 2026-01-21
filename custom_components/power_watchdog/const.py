DOMAIN = "power_watchdog"

CONF_TELEGRAM_TOKEN = "telegram_token"
CONF_TELEGRAM_CHAT_ID = "telegram_chat_id"

CONF_ENTITY_ID = "entity_id"

CONF_VOLTAGE_ENTITY_ID = "voltage_entity_id"

CONF_DEBOUNCE_SECONDS = "debounce_seconds"
DEFAULT_DEBOUNCE_SECONDS = 10

OFFLINE_STATES = {"unavailable", "unknown", "offline"}

CONF_STALE_TIMEOUT_SECONDS = "stale_timeout_seconds"
DEFAULT_STALE_TIMEOUT_SECONDS = 300

CONF_NOTIFY_ON_START = "notify_on_start"
DEFAULT_NOTIFY_ON_START = True

CONF_REFRESH_SECONDS = "refresh_seconds"
DEFAULT_REFRESH_SECONDS = 30  # или 30