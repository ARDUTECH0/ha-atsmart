"""Shared base entity for ATSmart."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN, MANUFACTURER, SIGNAL_UPDATE
from .hub import ATSmartHub


class ATSmartEntity(Entity):
    """Base for every ATSmart entity, keyed by its endpoint id."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, hub: ATSmartHub, entry: ConfigEntry, endpoint: dict) -> None:
        self._hub = hub
        self._entry = entry
        self._id = endpoint["id"]
        self._serial = endpoint["serial"]
        self._attr_unique_id = self._id
        self._attr_name = endpoint["name"]

    @property
    def _ep(self) -> dict:
        """The latest endpoint state from the hub (single source of truth)."""
        return self._hub.endpoints.get(self._id, {})

    @property
    def available(self) -> bool:
        return self._hub.is_online(self._serial)

    @property
    def device_info(self) -> DeviceInfo:
        unit = self._hub.unit_info(self._serial)
        return DeviceInfo(
            identifiers={(DOMAIN, self._serial)},
            name=unit.get("name", self._serial),
            manufacturer=MANUFACTURER,
            model=unit.get("board") or "Unit",
            sw_version=unit.get("fw") or None,
            serial_number=self._serial,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_UPDATE.format(self._entry.entry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        # Pick up a name the user later set on the board, then refresh state.
        if (name := self._ep.get("name")) and name != self._attr_name:
            self._attr_name = name
        self.async_write_ha_state()
