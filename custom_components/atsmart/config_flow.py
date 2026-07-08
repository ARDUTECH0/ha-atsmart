"""Config flow for ATSmart.

Two ways to link an account:
  • "Link with the app" (recommended): HA shows a short code, you type it into
    the already-signed-in KUSH SMART app — no password ever entered in HA.
  • "Email & password": sign in directly here.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthError, BridgeError, fetch_credentials, pair_new, pair_poll
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
    """Handle the UI setup."""

    VERSION = 1

    def __init__(self) -> None:
        self._pair_id: str | None = None
        self._pair_code: str | None = None

    # ── entry point: pick a linking method ──────────────────────────────────
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="user",
            menu_options=["link_app", "link_email"],
        )

    # ── link with the app (code) ────────────────────────────────────────────
    async def async_step_link_app(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        session = async_get_clientsession(self.hass)
        errors: dict[str, str] = {}

        # First time in: mint a pairing code to display.
        if self._pair_id is None:
            try:
                self._pair_code, self._pair_id = await pair_new(session, DEFAULT_BRIDGE_URL)
            except BridgeError:
                return self.async_abort(reason="cannot_connect")

        # Submit = "I've entered the code in the app" → poll once.
        if user_input is not None:
            try:
                status, creds = await pair_poll(session, DEFAULT_BRIDGE_URL, self._pair_id)
            except BridgeError:
                errors["base"] = "cannot_connect"
            else:
                if status == "linked" and creds:
                    await self.async_set_unique_id(creds["uid"])
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title="ATSmart",
                        data={
                            CONF_UID: creds["uid"],
                            CONF_MQTT_HOST: creds["mqtt_host"],
                            CONF_MQTT_PORT: creds["mqtt_port"],
                            CONF_MQTT_USER: creds["mqtt_user"],
                            CONF_MQTT_PASS: creds["mqtt_pass"],
                            CONF_LOCAL: True,
                        },
                    )
                if status == "expired":
                    # Code timed out — mint a new one and show it.
                    try:
                        self._pair_code, self._pair_id = await pair_new(
                            session, DEFAULT_BRIDGE_URL
                        )
                    except BridgeError:
                        return self.async_abort(reason="cannot_connect")
                    errors["base"] = "code_expired"
                else:
                    errors["base"] = "not_linked_yet"

        return self.async_show_form(
            step_id="link_app",
            data_schema=vol.Schema({}),
            description_placeholders={"code": self._pair_code or ""},
            errors=errors,
        )

    # ── link with email + password ──────────────────────────────────────────
    async def async_step_link_email(
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
            }
        )
        return self.async_show_form(
            step_id="link_email", data_schema=schema, errors=errors
        )
