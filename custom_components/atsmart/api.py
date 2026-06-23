"""Account → MQTT credential exchange for ATSmart.

The flow is intentionally one-shot: sign in to the ATSmart (Firebase) account,
hand the resulting ID token to the bridge, and get back the account's MQTT
credentials. The MQTT password is a stable HMAC of the account uid, so once
fetched it never expires — the integration connects straight to the broker
afterwards and never needs the password or a token refresh again.
"""

from __future__ import annotations

import logging

import aiohttp

from .const import FIREBASE_API_KEY

_LOGGER = logging.getLogger(__name__)

SIGNIN_URL = (
    "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
    "?key={key}"
)


class AuthError(Exception):
    """Raised when the email/password is wrong."""


class BridgeError(Exception):
    """Raised when the bridge can't issue MQTT credentials."""


async def fetch_credentials(
    session: aiohttp.ClientSession,
    email: str,
    password: str,
    bridge_url: str,
) -> dict:
    """Sign in and return the account's MQTT credentials.

    Returns a dict: {uid, mqtt_host, mqtt_port, mqtt_user, mqtt_pass}.
    """
    # 1. Sign in to the ATSmart account (Firebase email/password).
    try:
        async with session.post(
            SIGNIN_URL.format(key=FIREBASE_API_KEY),
            json={"email": email, "password": password, "returnSecureToken": True},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            body = await resp.json(content_type=None)
            if resp.status != 200:
                msg = (body or {}).get("error", {}).get("message", "UNKNOWN")
                _LOGGER.warning("ATSmart sign-in failed: %s", msg)
                raise AuthError(msg)
            id_token = body["idToken"]
            uid = body["localId"]
    except aiohttp.ClientError as err:
        raise BridgeError(f"sign-in network error: {err}") from err

    # 2. Exchange the ID token for the account's MQTT credentials at the bridge.
    url = bridge_url.rstrip("/") + "/mqtt/credentials"
    try:
        async with session.post(
            url,
            json={"idToken": id_token},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise BridgeError(f"bridge returned HTTP {resp.status}: {text[:120]}")
            creds = await resp.json(content_type=None)
    except aiohttp.ClientError as err:
        raise BridgeError(f"bridge network error: {err}") from err

    return {
        "uid": uid,
        "mqtt_host": creds["host"],
        "mqtt_port": int(creds["port"]),
        "mqtt_user": creds["username"],
        "mqtt_pass": creds["password"],
    }
