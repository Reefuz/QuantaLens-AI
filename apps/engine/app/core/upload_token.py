"""Short-lived, single-use tokens that let the browser upload a file straight to the engine.

Why: a platform in front of the engine may cap proxied request bodies. A token lets the browser send the file directly
without the session cookie (which does not travel cross-site). The token authorises exactly one thing, an upload for one
user, for five minutes. It cannot read data, change settings or be used on any other route.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
import uuid

from app.config import get_settings

TTL_SECONDS = 300
_used: dict[str, float] = {}
_lock = threading.Lock()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(body: str) -> str:
    key = get_settings().auth_secret.get_secret_value().encode()
    return _b64(hmac.new(key, b"upload-token:" + body.encode(), hashlib.sha256).digest())


def create_token(user_id: uuid.UUID, now: float | None = None) -> str:
    payload = {"u": str(user_id), "e": int((now if now is not None else time.time()) + TTL_SECONDS), "n": secrets.token_urlsafe(12), "p": "upload"}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_sign(body)}"


def verify_token(token: str, now: float | None = None, *, consume: bool = True) -> uuid.UUID | None:
    """Return the user id for a valid, unexpired, unused token, else None. Marks the token as used."""
    try:
        body, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, _sign(body)):
            return None
        payload = json.loads(_unb64(body))
        if payload.get("p") != "upload":
            return None
        current = now if now is not None else time.time()
        if payload["e"] < current:
            return None
        user_id = uuid.UUID(payload["u"])
        nonce = payload["n"]
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None
    with _lock:
        for k in [k for k, exp in _used.items() if exp < current]:
            _used.pop(k, None)
        if nonce in _used:
            return None
        if consume:
            _used[nonce] = payload["e"]
    return user_id


def reset() -> None:
    with _lock:
        _used.clear()
