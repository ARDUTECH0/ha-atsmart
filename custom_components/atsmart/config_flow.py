"""Config flow for ATSmart.

Two ways to link an account:
  • "Link with the app" (recommended): HA shows a short code, you type it into
    the already-signed-in KUSH SMART app — no password ever entered in HA.
  • "Email & password": sign in directly here.
"""

from __future__ import annotations

import asyncio
import base64
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


def _qr_data_uri(text: str) -> str:
    """Render `text` as a scannable QR, returned as an inline SVG data URI.

    Builds the SVG straight from qrcode's pure-Python module matrix — no Pillow
    and no lxml, so it works on any Home Assistant install.
    """
    try:
        import qrcode

        qr = qrcode.QRCode(border=2, box_size=1)
        qr.add_data(text)
        qr.make(fit=True)
        matrix = qr.get_matrix()
        n = len(matrix)
        scale = 10
        size = n * scale
        rects = []
        for y, row in enumerate(matrix):
            for x, cell in enumerate(row):
                if cell:
                    rects.append(
                        f'<rect x="{x * scale}" y="{y * scale}" '
                        f'width="{scale}" height="{scale}"/>'
                    )
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            f'viewBox="0 0 {size} {size}">'
            f'<rect width="{size}" height="{size}" fill="#ffffff"/>'
            f'<g fill="#000000">{"".join(rects)}</g></svg>'
        )
        b64 = base64.b64encode(svg.encode()).decode()
        return f"data:image/svg+xml;base64,{b64}"
    except Exception:  # noqa: BLE001 - QR is a convenience; never block linking
        _LOGGER.debug("QR generation failed", exc_info=True)
        return ""


class ATSmartConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI setup."""

    VERSION = 1

    def __init__(self) -> None:
        self._pair_id: str | None = None
        self._pair_code: str | None = None
        self._qr: str = ""
        self._poll_task: asyncio.Task | None = None
        self._creds: dict | None = None

    # ── entry point: pick a linking method ──────────────────────────────────
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="user",
            menu_options=["link_app", "link_email"],
        )

    # ── link with the app (scan the QR or type the code) ─────────────────────
    # HA shows a QR + code and then polls the bridge on its own until the app
    # claims it — no button to press. The moment it links, the flow finishes and
    # the account's devices are added automatically.
    async def async_step_link_app(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        session = async_get_clientsession(self.hass)

        # First entry: mint a code + QR and kick off the background poller.
        if self._poll_task is None:
            try:
                self._pair_code, self._pair_id = await pair_new(session, DEFAULT_BRIDGE_URL)
            except BridgeError:
                return self.async_abort(reason="cannot_connect")
            self._qr = _qr_data_uri(self._pair_code)
            self._poll_task = self.hass.async_create_task(
                self._wait_for_link(session, self._pair_id)
            )

        # Still waiting → show the QR/code with a spinner and let HA re-enter
        # this step when the task finishes.
        if not self._poll_task.done():
            return self.async_show_progress(
                step_id="link_app",
                progress_action="waiting",
                description_placeholders={"code": self._pair_code or "", "qr": self._qr},
                progress_task=self._poll_task,
            )

        # Task finished.
        creds = self._poll_task.result()
        self._poll_task = None
        if creds:
            self._creds = creds
            return self.async_show_progress_done(next_step_id="finish")
        # Expired / gave up → start over with a fresh code.
        self._pair_id = self._pair_code = None
        self._qr = ""
        return self.async_show_progress_done(next_step_id="link_app")

    async def _wait_for_link(self, session, pair_id: str) -> dict | None:
        """Poll the bridge until the app claims the code (or it expires)."""
        for _ in range(140):  # ~4.5 min, under the 5-min code TTL
            await asyncio.sleep(2)
            try:
                status, creds = await pair_poll(session, DEFAULT_BRIDGE_URL, pair_id)
            except BridgeError:
                continue
            if status == "linked" and creds:
                return creds
            if status == "expired":
                return None
        return None

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        creds = self._creds or {}
        await self.async_set_unique_id(creds["uid"])
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title="KUSH SMART",
            data={
                CONF_UID: creds["uid"],
                CONF_MQTT_HOST: creds["mqtt_host"],
                CONF_MQTT_PORT: creds["mqtt_port"],
                CONF_MQTT_USER: creds["mqtt_user"],
                CONF_MQTT_PASS: creds["mqtt_pass"],
                CONF_LOCAL: True,
            },
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
