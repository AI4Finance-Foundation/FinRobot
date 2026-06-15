"""Per-launch capability-token auth for the local FastAPI surface.

The desktop sidecar binds loopback only, but loopback is shared by every
process on the machine: TrustedHost + CORS stop a *browser* / DNS-rebinding
attacker, not another local process POSTing to 127.0.0.1:8321 to read
``/api/settings`` (and steal the user's FMP / Anthropic keys) or hammer
``/api/runs`` (and burn LLM quota).

The Tauri shell mints a random token at launch, hands it to the sidecar via
``FINROBOT_CAPABILITY_TOKEN`` and to the WebView via a Tauri command; the
WebView attaches it to every request. A process that can reach loopback but
cannot read our environment or drive the WebView's in-process IPC cannot
obtain the token.

When the env var is unset the middleware is a no-op. That keeps the browser
dev loop (``finrobot serve`` + Vite, no token) and the in-process test harness
(httpx ASGITransport) working without threading a token through every call —
and the live-backend dev posture (``dev.sh --app``), where the shell skips the
bundled sidecar and never sets the env, behaves the same way.
"""

from __future__ import annotations

import hmac

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Env access lives in config.py (audit red-line: only config / secret_store may
# read the process environment). CAPABILITY_TOKEN_ENV re-exported for tests.
from finrobot.config import CAPABILITY_TOKEN_ENV, get_capability_token

__all__ = ["CAPABILITY_TOKEN_ENV", "CapabilityAuthMiddleware"]

# Unauthenticated paths. ``/health`` is polled by the Tauri shell's readiness
# loop (a bare ureq GET with no token) before the WebView — and hence the
# token — exists, so it must stay open even when auth is enforced.
_EXEMPT_PATHS = frozenset({"/health"})

_BEARER_PREFIX = "Bearer "


def _extract_token(request: Request) -> str | None:
    """Pull the presented token from the Authorization header or ?token=.

    EventSource (SSE) cannot set request headers, so the run event
    streams pass the token as a ``token`` query parameter instead.
    """
    header = request.headers.get("Authorization")
    if header and header.startswith(_BEARER_PREFIX):
        token = header[len(_BEARER_PREFIX) :].strip()
        if token:
            return token
    query_token = request.query_params.get("token")
    if query_token:
        return query_token
    return None


class CapabilityAuthMiddleware(BaseHTTPMiddleware):
    """Require a per-launch capability token when one is configured.

    The expected token is read from ``FINROBOT_CAPABILITY_TOKEN`` on every
    request (not captured at construction) so tests can toggle enforcement via
    ``monkeypatch.setenv``. ``OPTIONS`` (CORS preflight) and ``/health`` are
    always allowed; everything else 401s without a matching token.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        expected = get_capability_token()
        if not expected:
            return await call_next(request)  # auth disabled (dev / tests)

        if request.method == "OPTIONS" or request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        presented = _extract_token(request)
        if presented is None or not hmac.compare_digest(presented, expected):
            return JSONResponse(
                {"detail": "Missing or invalid capability token."},
                status_code=401,
            )
        return await call_next(request)
