"""Switch platform for ATSmart (relays)."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_NEW_ENDPOINTS
from .entity import ATSmartEntity
from .hub import ATSmartHub


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: ATSmartHub = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def _add(endpoints: list[dict]) -> None:
        new = [
            ATSmartSwitch(hub, entry, ep)
            for ep in endpoints
            if ep["kind"] == "switch" and ep["id"] not in known
        ]
        for ep in endpoints:
            if ep["kind"] == "switch":
                known.add(ep["id"])
        if new:
            async_add_entities(new)

    _add(list(hub.endpoints.values()))
    entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_NEW_ENDPOINTS.format(entry.entry_id), _add
        )
    )


class ATSmartSwitch(ATSmartEntity, SwitchEntity):
    @property
    def is_on(self) -> bool:
        return bool(self._ep.get("on"))

    async def async_turn_on(self, **kwargs) -> None:
        await self._hub.async_send(
            self._serial, {"relays": {str(self._ep["relay_index"]): True}}
        )

    async def async_turn_off(self, **kwargs) -> None:
        await self._hub.async_send(
            self._serial, {"relays": {str(self._ep["relay_index"]): False}}
        )
