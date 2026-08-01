"""Button platform for ATSmart — learned IR/RF keys (IR/RF hub boards, e.g.
atgenx_halo). Pressing one replays that key exactly once."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
