"""Request correlation and access logging."""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from shop.observability import correlation_id

HEADER = "x-request-id"
_ACCEPTED = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

access_logger = logging.getLogger("shop.access")


class CorrelationIdMiddleware:
    """Gives every request an id, returns it in ``X-Request-ID`` and logs one access line.

    A client-supplied id is reused so that a trace can span services, but only if it is short and
    made of harmless characters: anything else would let a caller forge log lines.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        supplied = dict(scope["headers"]).get(HEADER.encode(), b"").decode("latin-1")
        request_id = supplied if _ACCEPTED.match(supplied) else uuid.uuid4().hex
        token = correlation_id.set(request_id)
        started = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)[HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            # The query string is left out on purpose: it is where personal data tends to end up.
            access_logger.info(
                "%s %s -> %s",
                scope["method"],
                scope["path"],
                status,
                extra={"duration_ms": round((time.perf_counter() - started) * 1000, 1)},
            )
            correlation_id.reset(token)
