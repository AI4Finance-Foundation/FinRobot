"""Capability-token auth on the local FastAPI surface.

The desktop sidecar binds loopback only, but loopback is shared by every
process on the box. These tests pin the contract that closes the residual
local-process vector (read /api/settings to steal keys, POST /api/runs to burn
quota) that TrustedHost + CORS do not cover:

  - env var unset            → no-op (dev `finrobot serve`, in-process tests)
  - env var set, no token    → 401 before the request reaches any route
  - env var set, good token  → passes the middleware (route handles it)
  - good token via ?token=   → passes (EventSource cannot set headers)
  - /health is always exempt → the Rust readiness poll has no token
"""

from __future__ import annotations

import logging

import pytest
from httpx import ASGITransport, AsyncClient

from finrobot.auth import CAPABILITY_TOKEN_ENV
from finrobot.obs.filters import RedactSecretsFilter
from finrobot.server import app

_TOKEN = "test-capability-token-abc123"


def _client() -> AsyncClient:
    # base_url host "test" is in TrustedHostMiddleware's allowlist.
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_no_env_var_is_noop(monkeypatch):
    monkeypatch.delenv(CAPABILITY_TOKEN_ENV, raising=False)
    async with _client() as c:
        # Nonexistent route 404s (not 401) → the middleware let it through.
        resp = await c.get("/api/__does_not_exist__")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_missing_token_is_rejected(monkeypatch):
    monkeypatch.setenv(CAPABILITY_TOKEN_ENV, _TOKEN)
    async with _client() as c:
        resp = await c.get("/api/__does_not_exist__")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_wrong_token_is_rejected(monkeypatch):
    monkeypatch.setenv(CAPABILITY_TOKEN_ENV, _TOKEN)
    async with _client() as c:
        resp = await c.get(
            "/api/__does_not_exist__",
            headers={"Authorization": "Bearer not-the-token"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_correct_bearer_token_passes(monkeypatch):
    monkeypatch.setenv(CAPABILITY_TOKEN_ENV, _TOKEN)
    async with _client() as c:
        resp = await c.get(
            "/api/__does_not_exist__",
            headers={"Authorization": f"Bearer {_TOKEN}"},
        )
    # Passed the middleware → route 404s. The point is it is NOT 401.
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_correct_query_token_passes(monkeypatch):
    """EventSource (SSE) cannot set headers, so the token rides ?token=."""
    monkeypatch.setenv(CAPABILITY_TOKEN_ENV, _TOKEN)
    async with _client() as c:
        resp = await c.get(f"/api/__does_not_exist__?token={_TOKEN}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_health_is_exempt(monkeypatch):
    """The Rust readiness poll hits /health with no token before the WebView."""
    monkeypatch.setenv(CAPABILITY_TOKEN_ENV, _TOKEN)
    async with _client() as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_health_echoes_token_when_configured(monkeypatch):
    """When a token is configured, /health echoes it so the readiness loop can
    prove the backend on :8321 is its own spawned child, not a port squatter.

    The probe stays exempt (no token required on the request) — this is an
    identity stamp, not an auth gate.
    """
    monkeypatch.setenv(CAPABILITY_TOKEN_ENV, _TOKEN)
    async with _client() as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    # engine_ready/agents_ready default True without a lifespan (cold-start split).
    assert resp.json() == {
        "status": "ready",
        "engine_ready": True,
        "agents_ready": True,
        "token": _TOKEN,
    }


@pytest.mark.asyncio
async def test_health_omits_token_when_unconfigured(monkeypatch):
    """Browser dev loop / live-backend / tests run without a token; /health must
    stay backward compatible and omit the field entirely."""
    monkeypatch.delenv(CAPABILITY_TOKEN_ENV, raising=False)
    async with _client() as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready", "engine_ready": True, "agents_ready": True}
    assert "token" not in resp.json()


def test_redact_secrets_filter_scrubs_token_and_apikey():
    f = RedactSecretsFilter()

    # uvicorn.access shape: message template + args tuple, full path in args.
    rec = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:5", "GET", "/api/runs/x/events?token=SECRET123", "1.1", 200),
        exc_info=None,
    )
    assert f.filter(rec) is True
    rendered = rec.getMessage()
    assert "SECRET123" not in rendered
    assert "token=REDACTED" in rendered

    # Pre-formatted message (no args) with an apikey-in-URL.
    rec2 = logging.LogRecord(
        name="x",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="fetch failed https://x/y?apikey=LIVEKEY&z=1",
        args=None,
        exc_info=None,
    )
    f.filter(rec2)
    assert "LIVEKEY" not in rec2.getMessage()
    assert "apikey=REDACTED" in rec2.getMessage()
