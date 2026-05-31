"""ASGI middleware that mints a request id and binds it for the request scope."""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from finrobot.obs.context import bind_request


class RequestTraceMiddleware(BaseHTTPMiddleware):
    """Generate a short request id, bind it to the contextvar for the duration
    of the request, and echo it back as ``X-Request-ID`` so the desktop UI /
    log readers can correlate a user action with its server-side log lines.

    An inbound ``X-Request-ID`` is honored (lets a client thread its own id
    through), otherwise a fresh 12-char hex id is minted.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        with bind_request(request_id):
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
