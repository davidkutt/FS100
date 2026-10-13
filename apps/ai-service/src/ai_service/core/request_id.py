"""x-request-id handling (plan.md D21): reuse or mint an id, echo it, log each request."""

import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ai_service.core.logging import request_id_var

REQUEST_ID_HEADER = "x-request-id"

# Accept ids from upstream callers only if they are short and log-safe; otherwise mint a new one.
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")

# Probes are not logged, to keep the logs readable.
_UNLOGGED_PATHS = frozenset({"/healthz", "/readyz"})

logger = logging.getLogger("ai_service.request")


def request_id_from(value: str | None) -> str:
    if value is not None and _SAFE_REQUEST_ID.fullmatch(value):
        return value
    return str(uuid.uuid4())


class RequestIdMiddleware:
    """Pure ASGI middleware, so streamed (SSE) responses pass through unbuffered."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = request_id_from(Headers(scope=scope).get(REQUEST_ID_HEADER))
        token = request_id_var.set(request_id)
        status = 500
        started = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            if scope["path"] not in _UNLOGGED_PATHS:
                logger.info(
                    "request completed",
                    extra={
                        "method": scope["method"],
                        "path": scope["path"],
                        "status": status,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    },
                )
            request_id_var.reset(token)
