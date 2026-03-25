"""Middleware for the Orchestra server."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import MutableMapping
from typing import TYPE_CHECKING, Any

from starlette.types import ASGIApp, Receive, Scope, Send

if TYPE_CHECKING:
    from fastapi import FastAPI
    from starlette.requests import Request
    from starlette.responses import Response

    from orchestra.server.config import ServerConfig


def add_cors_middleware(app: FastAPI, config: ServerConfig) -> None:
    """Configure CORS middleware on the FastAPI app."""
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=config.cors_credentials,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )


def add_body_size_middleware(app: FastAPI, config: ServerConfig) -> None:
    """Reject requests whose body exceeds config.max_request_body_bytes (HTTP 413)."""
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=config.max_request_body_bytes)


def add_rate_limit_middleware(app: FastAPI, config: ServerConfig) -> None:
    """Apply per-credential token-bucket rate limiting (HTTP 429 on excess)."""
    app.add_middleware(
        RateLimitMiddleware,
        max_tokens=config.rate_limit_per_minute,
        window_seconds=60.0,
    )


def add_request_id_middleware(app: FastAPI) -> None:
    """Add middleware that generates a UUID request ID for each request.

    The ID is returned in the ``X-Request-ID`` response header.
    """
    from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

    class RequestIDMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
            request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex)
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response

    app.add_middleware(RequestIDMiddleware)


class _BodyTooLarge(Exception):
    """Sentinel raised inside limited_receive when the body size limit is exceeded."""


class BodySizeLimitMiddleware:
    """Pure ASGI middleware that rejects requests exceeding max_bytes (HTTP 413).

    Checks the Content-Length header first, then streams and counts bytes for
    chunked requests with no declared length.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int = 1 * 1024 * 1024) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from starlette.datastructures import Headers

        headers = Headers(scope=scope)
        content_length = headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    await self._reject(send)
                    return
            except ValueError:
                pass  # malformed Content-Length — let the app handle it

        received_bytes = 0
        response_started = False

        async def limited_receive() -> MutableMapping[str, Any]:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_bytes:
                    raise _BodyTooLarge()
            return message

        async def tracked_send(message: MutableMapping[str, Any]) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _BodyTooLarge:
            if not response_started:
                await self._reject(send)

    async def _reject(self, send: Send) -> None:
        body = json.dumps(
            {"detail": "Request body too large", "error_type": "payload_too_large"}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class RateLimitMiddleware:
    """Token-bucket rate limiting middleware keyed by API credential or IP.

    Exempts health probe paths. Returns HTTP 429 with Retry-After and
    X-RateLimit-* headers when the bucket is exhausted.
    """

    _EXEMPT_PATHS = frozenset({"/healthz", "/readyz"})

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_tokens: int = 60,
        window_seconds: float = 60.0,
    ) -> None:
        from orchestra.security.rate_limit import TokenBucket

        self.app = app
        self._bucket = TokenBucket(max_tokens=max_tokens, window_seconds=window_seconds)
        # Single lock — allow() is pure computation with no I/O, so
        # serialising through one lock adds negligible latency.
        self._lock = asyncio.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from starlette.datastructures import Headers

        path = scope.get("path", "")
        if path in self._EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        auth = headers.get("authorization", "")
        client = scope.get("client")
        ip = client[0] if client else "unknown"
        if auth:
            token_hash = hashlib.sha256(auth.encode()).hexdigest()[:16]
            identity = f"token:{token_hash}"
        else:
            identity = f"ip:{ip}"

        async with self._lock:
            allowed = self._bucket.allow(identity)
            remaining = self._bucket.remaining(identity)

        if not allowed:
            body = json.dumps(
                {"detail": "Rate limit exceeded", "error_type": "rate_limited"}
            ).encode()
            retry_after = str(int(self._bucket.window_seconds))
            limit = str(self._bucket.max_tokens)
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode()),
                        (b"retry-after", retry_after.encode()),
                        (b"x-ratelimit-limit", limit.encode()),
                        (b"x-ratelimit-remaining", b"0"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        # Inject rate-limit headers into the response via a send wrapper
        remaining_str = str(max(0, int(remaining))).encode()
        limit_bytes = str(self._bucket.max_tokens).encode()
        headers_injected = False

        async def send_with_headers(message: MutableMapping[str, Any]) -> None:
            nonlocal headers_injected
            if message["type"] == "http.response.start" and not headers_injected:
                headers_injected = True
                extra = [
                    (b"x-ratelimit-limit", limit_bytes),
                    (b"x-ratelimit-remaining", remaining_str),
                ]
                message = {**message, "headers": list(message.get("headers", [])) + extra}
            await send(message)

        await self.app(scope, receive, send_with_headers)
