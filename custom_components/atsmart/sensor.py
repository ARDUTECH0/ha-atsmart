"""Sensor platform for ATSmart (temperature, humidity, analog)."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_NEW_ENDPOINTS
from .entity import ATSmartEntity
from .hub import ATSmartHub

SENSOR_KINDS = ("temperature", "humidity", "analog")


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    hub: ATSmartHub = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def _add(endpoints: list[dict]) -> None:
        new = [
            ATSmartSensor(hub, entry, ep)
            for ep in endpoints
            if ep["kind"] in SENSOR_KINDS and ep["id"] not in known
        ]
        for ep in endpoints:
            if ep["kind"] in SENSOR_KINDS:
                known.add(ep["id"])
        if new:
            async_add_entities(new)

    _add(list(hub.endpoints.values()))
    entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_NEW_ENDPOINTS.format(entry.entry_id), _add
        )
    )


class ATSmartSensor(ATSmartEntity, SensorEntity):
    def __init__(self, hub, entry, endpoint) -> None:
        super().__init__(hub, entry, endpoint)
        kind = endpoint["kind"]
        self._attr_state_class = SensorStateClass.MEASUREMENT
        if kind == "temperature":
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        elif kind == "humidity":
            self._attr_device_class = SensorDeviceClass.HUMIDITY
            self._attr_native_unit_of_measurement = PERCENTAGE

    @property
    def native_value(self):
        return self._ep.get("value")
