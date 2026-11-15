"""Security headers and a coarse per-IP request limit, as pure ASGI middleware (safe with streaming responses)."""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.rate_limit import RateLimiter

GLOBAL_LIMIT = 600  # requests
GLOBAL_WINDOW = 60  # seconds
_global = RateLimiter()


def _client_ip(scope: Scope) -> str:
    headers = dict(scope.get("headers") or [])
    forwarded = headers.get(b"x-forwarded-for", b"").decode("latin-1")
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else "unknown"


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, *, production: bool) -> None:
        self.app = app
        self.production = production

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if path.startswith("/api/") and scope["method"] != "OPTIONS":
            try:
                _global.check(f"ip:{_client_ip(scope)}", GLOBAL_LIMIT, GLOBAL_WINDOW)
            except Exception:  # noqa: BLE001 - HTTPException from the limiter
                body = json.dumps({"detail": "Too many requests. Please slow down."}).encode()
                await send({"type": "http.response.start", "status": 429, "headers": [(b"content-type", b"application/json"), (b"retry-after", b"30"), (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                names = {h[0].lower() for h in headers}
                extra = [(b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"), (b"referrer-policy", b"no-referrer")]
                if path.startswith("/api/"):
                    extra.append((b"cache-control", b"no-store"))
                if self.production:
                    extra.append((b"strict-transport-security", b"max-age=63072000; includeSubDomains"))
                headers += [h for h in extra if h[0] not in names]
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, with_headers)


def reset_global_limit() -> None:
    _global.reset()
