"""Light platform for ATSmart (dimmers, fans-as-light, and RGB)."""

from __future__ import annotations

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_NEW_ENDPOINTS
from .entity import ATSmartEntity
from .hub import ATSmartHub

LIGHT_KINDS = ("light", "color")


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: ATSmartHub = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def _add(endpoints: list[dict]) -> None:
        new = [
            ATSmartLight(hub, entry, ep)
            for ep in endpoints
            if ep["kind"] in LIGHT_KINDS and ep["id"] not in known
        ]
        for ep in endpoints:
            if ep["kind"] in LIGHT_KINDS:
                known.add(ep["id"])
        if new:
            async_add_entities(new)

    _add(list(hub.endpoints.values()))
    entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_NEW_ENDPOINTS.format(entry.entry_id), _add
        )
    )


class ATSmartLight(ATSmartEntity, LightEntity):
    def __init__(self, hub, entry, endpoint) -> None:
        super().__init__(hub, entry, endpoint)
        if endpoint["kind"] == "color":
            self._attr_color_mode = ColorMode.RGB
            self._attr_supported_color_modes = {ColorMode.RGB}
        else:
            self._attr_color_mode = ColorMode.BRIGHTNESS
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    @property
    def is_on(self) -> bool:
        return bool(self._ep.get("on"))

    @property
    def brightness(self) -> int | None:
        ep = self._ep
        if ep.get("kind") == "color":
            return None
        # Board reports 0..100; HA wants 0..255.
        return round((ep.get("brightness") or 0) * 2.55)

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        ep = self._ep
        if ep.get("kind") != "color":
            return None
        c = ep.get("rgb") or [0, 0, 0]
        return (int(c[0]), int(c[1]), int(c[2]))

    async def async_turn_on(self, **kwargs) -> None:
        ep = self._ep
        idx = str(ep["chan_index"])
        if ep.get("kind") == "color":
            rgb = kwargs.get(ATTR_RGB_COLOR)
            if rgb is None:
                rgb = self.rgb_color
                if not rgb or sum(rgb) == 0:
                    rgb = (255, 255, 255)
            await self._hub.async_send(self._serial, {"rgb": {idx: list(rgb)}})
            return
        # Dimmer/fan: convert HA 0..255 brightness to the board's 0..100.
        if ATTR_BRIGHTNESS in kwargs:
            level = max(1, round(kwargs[ATTR_BRIGHTNESS] / 2.55))
        else:
            level = ep.get("brightness") or 100
        key = "fan" if ep.get("fan") else "dim"
        await self._hub.async_send(self._serial, {key: {idx: level}})

    async def async_turn_off(self, **kwargs) -> None:
        ep = self._ep
        idx = str(ep["chan_index"])
        if ep.get("kind") == "color":
            await self._hub.async_send(self._serial, {"rgb": {idx: [0, 0, 0]}})
        else:
            key = "fan" if ep.get("fan") else "dim"
            await self._hub.async_send(self._serial, {key: {idx: 0}})
