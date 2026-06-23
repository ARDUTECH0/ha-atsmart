"""ATSmart hub: one MQTT connection to the account broker plus best-effort local
WebSocket links to each unit on the LAN.

State and discovery flow over MQTT (the unit publishes <uid>/<serial>/state). When
a unit's LAN IP is known we also open ws://<ip>/ws and prefer it for commands, so
control is instant locally and still works over the cloud when away.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

import aiohttp
import paho.mqtt.client as mqtt

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_LOCAL,
    CONF_MQTT_HOST,
    CONF_MQTT_PORT,
    CONF_MQTT_USER,
    CONF_MQTT_PASS,
    CONF_UID,
    SIGNAL_NEW_ENDPOINTS,
    SIGNAL_UPDATE,
)

_LOGGER = logging.getLogger(__name__)


class ATSmartHub:
    """Owns the broker connection and the in-memory device model."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.uid: str = entry.data[CONF_UID]
        self._host: str = entry.data[CONF_MQTT_HOST]
        self._port: int = entry.data[CONF_MQTT_PORT]
        self._user: str = entry.data[CONF_MQTT_USER]
        self._pass: str = entry.data[CONF_MQTT_PASS]
        self._use_local: bool = entry.data.get(CONF_LOCAL, True)

        # id -> endpoint dict (metadata + latest state); serial -> unit metadata.
        self.endpoints: dict[str, dict] = {}
        self.units: dict[str, dict] = {}

        self._client: mqtt.Client | None = None
        self._local: dict[str, "LocalLink"] = {}
        self._session: aiohttp.ClientSession | None = None

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def async_start(self) -> None:
        self._session = async_get_clientsession(self.hass)
        cid = f"ha-atsmart-{self.uid[:8]}-{id(self) & 0xFFFF:x}"
        # paho-mqtt 2.x requires a CallbackAPIVersion; 1.x doesn't know it. Build
        # the client so the integration runs on either (HA ships 2.x now).
        try:
            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION1, client_id=cid, clean_session=True
            )
        except (AttributeError, TypeError):
            client = mqtt.Client(client_id=cid, clean_session=True)
        client.username_pw_set(self._user, self._pass)
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client = client
        # connect_async + loop_start never block and auto-reconnect for us.
        await self.hass.async_add_executor_job(
            client.connect_async, self._host, self._port, 30
        )
        client.loop_start()

    async def async_stop(self) -> None:
        for link in list(self._local.values()):
            await link.stop()
        self._local.clear()
        if self._client:
            self._client.loop_stop()
            await self.hass.async_add_executor_job(self._client.disconnect)
            self._client = None

    # ── MQTT callbacks (run on the paho thread) ──────────────────────────────
    def _on_connect(self, client, _userdata, _flags, rc, *_args) -> None:
        if rc != 0:
            _LOGGER.error("ATSmart MQTT connect failed rc=%s", rc)
            return
        _LOGGER.info("ATSmart connected to broker as %s", self._user)
        client.subscribe([(f"{self.uid}/+/state", 0), (f"{self.uid}/+/status", 0)])

    def _on_message(self, _client, _userdata, msg) -> None:
        try:
            parts = msg.topic.split("/")
            if len(parts) != 3:
                return
            _uid, serial, leaf = parts
            data = json.loads(msg.payload.decode(errors="ignore"))
        except (ValueError, UnicodeError):
            return
        # Hop onto the HA event loop before touching HA internals.
        self.hass.loop.call_soon_threadsafe(self._process, serial, leaf, data)

    # ── state ingestion (event loop) ─────────────────────────────────────────
    @callback
    def _process(self, serial: str, leaf: str, data: dict, *, local: bool = False) -> None:
        if leaf == "status":
            unit = self.units.setdefault(serial, {})
            unit["online"] = str(data.get("status", "")).lower() == "online"
            self._dispatch_update()
            return

        # leaf == "state"
        unit = self.units.setdefault(serial, {})
        unit["online"] = True
        unit["name"] = data.get("project") or unit.get("name") or serial
        unit["board"] = data.get("board", unit.get("board", ""))
        unit["fw"] = str(data.get("fw", unit.get("fw", "")))
        ip = data.get("ip")
        if ip:
            unit["ip"] = ip
            if self._use_local and not local:
                self._ensure_local(serial, ip)

        new = self._rebuild_endpoints(serial, data)
        if new:
            async_dispatcher_send(
                self.hass, SIGNAL_NEW_ENDPOINTS.format(self.entry.entry_id), new
            )
        self._dispatch_update()

    def _rebuild_endpoints(self, serial: str, s: dict) -> list[dict]:
        """Update self.endpoints from a state doc; return newly-seen endpoints."""
        names = s.get("names") if isinstance(s.get("names"), list) else []
        found: list[tuple[str, dict]] = []

        # Relays → switches (states[] indexed by relay ordinal).
        for i, on in enumerate(s.get("states", []) or []):
            found.append((f"{serial}:r{i}", {
                "kind": "switch", "relay_index": i,
                "name": names[i] if i < len(names) and names[i] else f"Switch {i + 1}",
                "on": on is True,
            }))

        # Dimmers/fans → dimmable lights.
        for d in s.get("dimmers", []) or []:
            idx = d.get("index")
            found.append((f"{serial}:dim{idx}", {
                "kind": "light", "chan_index": idx,
                "name": d.get("name") or f"Light {idx}",
                "on": (d.get("value") or 0) > 0, "brightness": d.get("value") or 0,
            }))
        for d in s.get("fans", []) or []:
            idx = d.get("index")
            found.append((f"{serial}:dim{idx}", {
                "kind": "light", "chan_index": idx, "fan": True,
                "name": d.get("name") or f"Fan {idx}",
                "on": (d.get("value") or 0) > 0, "brightness": d.get("value") or 0,
            }))

        # RGB → colour lights.
        for r in s.get("rgbs", []) or []:
            idx = r.get("index")
            color = r.get("color") if isinstance(r.get("color"), list) else [0, 0, 0]
            found.append((f"{serial}:rgb{idx}", {
                "kind": "color", "chan_index": idx,
                "name": r.get("name") or f"RGB {idx}",
                "on": sum(int(c) for c in color[:3]) > 0, "rgb": color,
            }))

        # Sensors → read-only entities.
        for se in s.get("sensors", []) or []:
            idx = se.get("index")
            stype = se.get("type")
            name = se.get("name") or "Sensor"
            if stype == "dht":
                if "temp" in se:
                    found.append((f"{serial}:temp{idx}", {
                        "kind": "temperature", "name": f"{name} Temperature",
                        "value": se.get("temp")}))
                if "hum" in se:
                    found.append((f"{serial}:hum{idx}", {
                        "kind": "humidity", "name": f"{name} Humidity",
                        "value": se.get("hum")}))
            elif stype == "analog":
                found.append((f"{serial}:an{idx}", {
                    "kind": "analog", "name": name, "value": se.get("value")}))
            elif stype == "digital":
                found.append((f"{serial}:dig{idx}", {
                    "kind": "contact", "name": name,
                    "detected": se.get("value") in (True, 1)}))

        new_eps: list[dict] = []
        for eid, ep in found:
            ep.update({"id": eid, "serial": serial})
            is_new = eid not in self.endpoints
            self.endpoints[eid] = ep
            if is_new:
                new_eps.append(ep)
        return new_eps

    @callback
    def _dispatch_update(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_UPDATE.format(self.entry.entry_id))

    # ── helpers used by entities ─────────────────────────────────────────────
    def is_online(self, serial: str) -> bool:
        return bool(self.units.get(serial, {}).get("online"))

    def unit_info(self, serial: str) -> dict:
        return self.units.get(serial, {})

    def control_path(self, serial: str) -> str:
        """Which channel a command to this unit will currently take."""
        link = self._local.get(serial)
        return "local" if (link and link.connected) else "cloud"

    @callback
    def optimistic(self, endpoint_id: str, **changes) -> None:
        """Apply an expected state immediately so the UI responds instantly; the
        unit's echo (local or cloud, usually within ~100 ms) then confirms it."""
        ep = self.endpoints.get(endpoint_id)
        if not ep:
            return
        ep.update(changes)
        self._dispatch_update()

    async def async_send(self, serial: str, payload: dict[str, Any]) -> None:
        """Send a command, preferring the local link, falling back to the cloud."""
        payload = {**payload, "owner": self.uid}
        link = self._local.get(serial)
        if link and link.connected:
            if await link.send(payload):
                return
        if self._client:
            self._client.publish(
                f"{self.uid}/{serial}/set", json.dumps(payload), qos=1
            )

    # ── local WebSocket links ────────────────────────────────────────────────
    def _ensure_local(self, serial: str, ip: str) -> None:
        link = self._local.get(serial)
        if link and link.ip == ip:
            return
        if link:
            self.hass.async_create_task(link.stop())
        link = LocalLink(self, serial, ip)
        self._local[serial] = link
        link.start()


class LocalLink:
    """A best-effort ws://<ip>/ws connection to one unit on the LAN."""

    def __init__(self, hub: ATSmartHub, serial: str, ip: str) -> None:
        self._hub = hub
        self.serial = serial
        self.ip = ip
        self.connected = False
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._task: asyncio.Task | None = None
        self._stop = False

    def start(self) -> None:
        self._task = self._hub.hass.async_create_task(self._run())

    async def stop(self) -> None:
        self._stop = True
        if self._ws:
            await self._ws.close()
        if self._task:
            self._task.cancel()

    async def send(self, payload: dict) -> bool:
        if not self._ws or self._ws.closed:
            return False
        try:
            await self._ws.send_str(json.dumps(payload))
            return True
        except (aiohttp.ClientError, ConnectionError):
            return False

    async def _run(self) -> None:
        session = self._hub._session
        delay = 2
        while not self._stop:
            try:
                async with session.ws_connect(
                    f"ws://{self.ip}/ws", heartbeat=20, timeout=10
                ) as ws:
                    self._ws = ws
                    self.connected = True
                    delay = 2
                    _LOGGER.debug("ATSmart local link up: %s (%s)", self.serial, self.ip)
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue
                        try:
                            data = json.loads(msg.data)
                        except ValueError:
                            continue
                        if isinstance(data, dict):
                            self._hub._process(self.serial, "state", data, local=True)
            except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError):
                pass
            finally:
                self.connected = False
                self._ws = None
            if self._stop:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)
