"""Config flow for ATSmart — sign in once with the account, nothing else."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthError, BridgeError, fetch_credentials
from .const import (
    CONF_BRIDGE_URL,
    CONF_EMAIL,
    CONF_LOCAL,
    CONF_MQTT_HOST,
    CONF_MQTT_PASS,
    CONF_MQTT_PORT,
    CONF_MQTT_USER,
    CONF_PASSWORD,
    CONF_UID,
    DEFAULT_BRIDGE_URL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class ATSmartConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI setup: just email + password."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            try:
                creds = await fetch_credentials(
                    session,
                    user_input[CONF_EMAIL].strip(),
                    user_input[CONF_PASSWORD],
                    user_input.get(CONF_BRIDGE_URL, DEFAULT_BRIDGE_URL).strip(),
                )
            except AuthError:
                errors["base"] = "invalid_auth"
            except BridgeError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - surface anything else as unknown
                _LOGGER.exception("Unexpected error setting up ATSmart")
                errors["base"] = "unknown"
            else:
                # One account = one entry. The uid is stable and unique.
                await self.async_set_unique_id(creds["uid"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_EMAIL].strip(),
                    data={
                        CONF_EMAIL: user_input[CONF_EMAIL].strip(),
                        CONF_UID: creds["uid"],
                        CONF_MQTT_HOST: creds["mqtt_host"],
                        CONF_MQTT_PORT: creds["mqtt_port"],
                        CONF_MQTT_USER: creds["mqtt_user"],
                        CONF_MQTT_PASS: creds["mqtt_pass"],
                        CONF_LOCAL: user_input.get(CONF_LOCAL, True),
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_LOCAL, default=True): bool,
                vol.Optional(CONF_BRIDGE_URL, default=DEFAULT_BRIDGE_URL): str,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )
