"""Button platform for ATSmart.

Two different kinds of button live here:
  - ATSmartButton: one per learned IR/RF key (IR/RF hub boards, e.g.
    atgenx_halo). Pressing one replays that key exactly once.
  - ATSmartDashboardButton: one per account, always present. Pressing it
    (re)generates the KUSH SMART dashboard YAML — see dashboard.py for why
    that's a generated file rather than something created live.
"""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, SIGNAL_NEW_ENDPOINTS
from .entity import ATSmartEntity
from .hub import ATSmartHub

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: ATSmartHub = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([ATSmartDashboardButton(hub, entry)])

    known: set[str] = set()

    @callback
    def _add(endpoints: list[dict]) -> None:
        new = [
            ATSmartButton(hub, entry, ep)
            for ep in endpoints
            if ep["kind"] == "button" and ep["id"] not in known
        ]
        for ep in endpoints:
            if ep["kind"] == "button":
                known.add(ep["id"])
        if new:
            async_add_entities(new)

    _add(list(hub.endpoints.values()))
    entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_NEW_ENDPOINTS.format(entry.entry_id), _add
        )
    )


class ATSmartButton(ATSmartEntity, ButtonEntity):
    async def async_press(self) -> None:
        await self._hub.async_send(self._serial, {"send": self._ep["send_name"]})


class ATSmartDashboardButton(ButtonEntity):
    """Generate/refresh the KUSH SMART dashboard file, on demand."""

    _attr_has_entity_name = True
    _attr_name = "Create dashboard"
    _attr_icon = "mdi:view-dashboard-outline"
    _attr_should_poll = False

    def __init__(self, hub: ATSmartHub, entry: ConfigEntry) -> None:
        self._hub = hub
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_create_dashboard"

    @property
    def device_info(self) -> DeviceInfo:
        # Its own "service" device, not any one unit — this button covers the
        # whole account.
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="KUSH SMART",
            manufacturer=MANUFACTURER,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_press(self) -> None:
        from .dashboard import async_write_dashboard_file  # local: keeps yaml off the hot import path

        try:
            path = await async_write_dashboard_file(self.hass, self._hub)
        except OSError as err:
            _LOGGER.error("Could not write the KUSH SMART dashboard file: %s", err)
            await self.hass.services.async_call(
                "persistent_notification", "create",
                {
                    "title": "KUSH SMART Dashboard",
                    "notification_id": f"{DOMAIN}_dashboard_ready",
                    "message": f"Couldn't write the dashboard file: {err}",
                },
            )
            return

        await self.hass.services.async_call(
            "persistent_notification", "create",
            {
                "title": "KUSH SMART Dashboard",
                "notification_id": f"{DOMAIN}_dashboard_ready",
                "message": (
                    f"Dashboard file ready:\n\n`{path}`\n\n"
                    "One-time step to use it: **Settings -> Dashboards -> "
                    "Add Dashboard -> New dashboard from scratch**, give it a "
                    "name, then open its 3-dot menu -> **Edit Dashboard** -> "
                    "3-dot menu -> **Raw configuration editor**, and paste in "
                    "the contents of that file.\n\n"
                    "Press this button again any time you add a device, to "
                    "refresh the file with the new one."
                ),
            },
        )
