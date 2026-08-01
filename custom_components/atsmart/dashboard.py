"""Generate a professional Lovelace dashboard for KUSH SMART devices.

Home Assistant's dashboard storage isn't a stable API for a third-party
integration to write into directly (confirmed against HA core's own source:
the collection that backs it lives as a local variable inside the lovelace
component's own async_setup, not on hass.data — the same reason a
well-established integration like Keymaster only ever generates a YAML file
too). So this generates the file; the "Create dashboard" button in button.py
writes it and tells the user the one-time step to point a dashboard at it.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .hub import ATSmartHub

_LOGGER = logging.getLogger(__name__)

# Endpoint "kind" (hub.py's own model) -> the HA entity domain that kind's
# platform file (switch.py, light.py, ...) actually registers under.
_DOMAIN_FOR_KIND = {
    "switch": "switch",
    "light": "light",
    "color": "light",
    "cover": "cover",
    "temperature": "sensor",
    "humidity": "sensor",
    "analog": "sensor",
    "contact": "binary_sensor",
    "button": "button",
}


def _resolve_entity_id(hass: HomeAssistant, endpoint_id: str, kind: str) -> str | None:
    """Look up the real HA entity_id for one of our endpoints.

    Every ATSmartEntity sets unique_id = the endpoint id (see entity.py), so
    this is the same lookup the entity registry already does internally.
    """
    domain = _DOMAIN_FOR_KIND.get(kind)
    if not domain:
        return None
    registry = er.async_get(hass)
    return registry.async_get_entity_id(domain, DOMAIN, endpoint_id)


def generate_dashboard_config(hass: HomeAssistant, hub: ATSmartHub) -> dict[str, Any]:
    """Build a Sections-view dashboard: one section per unit, one tile per entity.

    Pure data generation, no HA storage/frontend calls here, so this is safe
    to call from a button press and easy to reason about independently of
    whatever Home Assistant version is running it.
    """
    sections: list[dict[str, Any]] = []
    for serial, unit in sorted(
        hub.units.items(), key=lambda kv: (kv[1].get("name") or kv[0]).lower()
    ):
        cards: list[dict[str, Any]] = [
            {"type": "heading", "heading": unit.get("name") or serial, "heading_style": "title"}
        ]
        for ep in hub.endpoints.values():
            if ep.get("serial") != serial:
                continue
            entity_id = _resolve_entity_id(hass, ep["id"], ep.get("kind", ""))
            if entity_id:
                cards.append({"type": "tile", "entity": entity_id})
        if len(cards) > 1:  # more than just the heading
            sections.append({"type": "grid", "cards": cards})

    if not sections:
        sections = [{
            "type": "grid",
            "cards": [{
                "type": "markdown",
                "content": (
                    "No KUSH SMART devices seen yet. Make sure at least one "
                    "unit is online, then press **Create dashboard** again."
                ),
            }],
        }]

    return {
        "title": "KUSH SMART",
        "views": [{
            "title": "KUSH SMART",
            "path": "kush-smart",
            "icon": "mdi:home-automation",
            "type": "sections",
            "sections": sections,
        }],
    }


def dashboard_file_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.path("custom_components", DOMAIN, "dashboards", "kush_smart.yaml"))


async def async_write_dashboard_file(hass: HomeAssistant, hub: ATSmartHub) -> Path:
    """Generate the dashboard YAML and write it to disk. Returns the file path."""
    config = generate_dashboard_config(hass, hub)
    path = dashboard_file_path(hass)

    def _write() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        _LOGGER.debug("Dashboard YAML written: %s", path)

    await hass.async_add_executor_job(_write)
    return path
