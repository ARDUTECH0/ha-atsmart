# ATSmart for Home Assistant

Control your **ATSmart** smart-home devices from Home Assistant. Sign in once with
your ATSmart account — every switch, light, RGB and sensor is added
**automatically**, and any new device you add later shows up on its own. No MQTT
YAML, no manual entity setup, no blank/empty config.

- ✅ **Zero config** — just your account email + password.
- ✅ **Auto-discovery** — devices and channels appear by themselves and update live.
- ✅ **Local + cloud** — controls instantly over your LAN (`ws://device/ws`) when
  the unit is on the same network, and falls back to the cloud when you're away.
- ✅ **Account-scoped** — you only ever see *your* devices. Nothing from other
  accounts can appear or interfere.
- ✅ Switches (relays), dimmable lights, fans, RGB lights, temperature &
  humidity, analog and contact/door sensors.

## Installation

### HACS (recommended)

1. In Home Assistant: **HACS → ⋮ → Custom repositories**.
2. Add `https://github.com/ARDUTECH0/ha-atsmart` with category **Integration**.
3. Search for **ATSmart**, install it, then **restart Home Assistant**.
4. **Settings → Devices & Services → Add Integration → ATSmart**.
5. Enter your ATSmart account email and password. Done — your devices appear.

### Manual

Copy `custom_components/atsmart` into your Home Assistant `config/custom_components/`
folder and restart, then add the integration from the UI as above.

## How it works

On sign-in the integration exchanges your account for its **own MQTT credentials**
(the password is a stable token derived from your account id, so it's fetched once
and never expires). It then connects directly to the ATSmart broker, subscribes to
your account's topics only, and builds entities from each unit's live state. When a
unit reports a LAN IP, the integration also opens a local WebSocket to it and
prefers that path for instant control.

| Device                | Home Assistant entity            |
| --------------------- | -------------------------------- |
| Relay                 | `switch`                         |
| Dimmer / Fan          | `light` (brightness)             |
| RGB / WS2812          | `light` (RGB)                    |
| DHT sensor            | `sensor` temperature + humidity  |
| Analog sensor         | `sensor`                         |
| Digital / door sensor | `binary_sensor` (opening)        |

## Advanced

The **Bridge URL** field (default `https://smart.kushsmart.space`) only needs changing
if you self-host the KUSH SMART bridge. Local control can be turned off from the same
setup dialog if you prefer cloud-only.

## License

MIT — see [LICENSE](LICENSE).
