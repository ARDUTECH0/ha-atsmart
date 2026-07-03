"""Cover platform for ATSmart (shutters / curtains / rollers)."""

from __future__ import annotations

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
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
            ATSmartCover(hub, entry, ep)
            for ep in endpoints
            if ep["kind"] == "cover" and ep["id"] not in known
        ]
        for ep in endpoints:
            if ep["kind"] == "cover":
                known.add(ep["id"])
        if new:
            async_add_entities(new)

    _add(list(hub.endpoints.values()))
    entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_NEW_ENDPOINTS.format(entry.entry_id), _add
        )
    )


class ATSmartCover(ATSmartEntity, CoverEntity):
    """A shutter/curtain exposed as an open / close / stop cover."""

    _attr_device_class = CoverDeviceClass.SHUTTER
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
    )

    # The board reports its last command (open / close / stop), not a live
    # position, so we map that to HA's open/closed state as best we can.
    @property
    def is_closed(self) -> bool | None:
        st = self._ep.get("state")
        if st == "close":
            return True
        if st == "open":
            return False
        return None  # stopped / unknown

    @property
    def is_opening(self) -> bool:
        return self._ep.get("state") == "open"

    @property
    def is_closing(self) -> bool:
        return self._ep.get("state") == "close"

    async def async_open_cover(self, **kwargs) -> None:
        idx = str(self._ep["chan_index"])
        self._hub.optimistic(self._id, state="open")
        await self._hub.async_send(self._serial, {"shutter": {idx: "open"}})

    async def async_close_cover(self, **kwargs) -> None:
        idx = str(self._ep["chan_index"])
        self._hub.optimistic(self._id, state="close")
        await self._hub.async_send(self._serial, {"shutter": {idx: "close"}})

    async def async_stop_cover(self, **kwargs) -> None:
        idx = str(self._ep["chan_index"])
        self._hub.optimistic(self._id, state="stop")
        await self._hub.async_send(self._serial, {"shutter": {idx: "stop"}})
