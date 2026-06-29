"""Constants for the ATSmart integration."""

DOMAIN = "atsmart"

# Default public bridge (fetches the per-account MQTT credentials) and the
# Firebase project the accounts live in. All overridable in the config flow's
# advanced options, but the defaults work out of the box.
DEFAULT_BRIDGE_URL = "https://smart.kushsmart.space"
FIREBASE_API_KEY = "AIzaSyDnaSP4wXQe1nL_9GVckvVw56Mzv1uVUBs"

# Config-entry data keys.
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_BRIDGE_URL = "bridge_url"
CONF_UID = "uid"
CONF_MQTT_HOST = "mqtt_host"
CONF_MQTT_PORT = "mqtt_port"
CONF_MQTT_USER = "mqtt_user"
CONF_MQTT_PASS = "mqtt_pass"
CONF_LOCAL = "local_control"

# Platforms this integration creates entities for.
PLATFORMS = ["switch", "light", "sensor", "binary_sensor"]

# Dispatcher signals (suffixed with the entry_id).
SIGNAL_NEW_ENDPOINTS = "atsmart_new_endpoints_{}"
SIGNAL_UPDATE = "atsmart_update_{}"

MANUFACTURER = "KUSH SMART"
