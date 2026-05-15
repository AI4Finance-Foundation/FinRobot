"""Route tests for /api/notify endpoints.

Coverage:
- GET /api/notify/channels — lists channel statuses
- POST /api/notify/test/{channel} — sends test notification
  - valid channel, configured → calls manager.test_channel()
  - valid channel, unconfigured → returns {success: false}
  - invalid channel name → 404

Mock discipline: NotifyManager is replaced with a stub to avoid
any real HTTP calls. These are unit-level route tests.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from finagent.engine.notify.base import ChannelStatus
from finagent.routes.notify import router as notify_router


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------

def _make_app(manager_mock: Any) -> FastAPI:
    test_app = FastAPI()

    # Stub settings with all notify fields empty
    class _FakeSettings:
        feishu_webhook_url = None
        telegram_bot_token = None
        telegram_chat_id = None
        discord_webhook_url = None
        email_smtp_host = None
        email_smtp_port = 587
        email_smtp_user = None
        email_smtp_pass = None
        email_to = None
        custom_webhook_url = None

    class _FakeDeps:
        settings = _FakeSettings()

    test_app.state.deps = _FakeDeps()
    test_app.state.notify_manager = manager_mock
    test_app.state._notify_manager_settings = _FakeDeps.settings

    test_app.include_router(notify_router)
    return test_app


@pytest.fixture()
def manager_mock() -> MagicMock:
    mock = MagicMock()
    mock.get_status.return_value = [
        ChannelStatus(name="feishu", enabled=False, configured=False),
        ChannelStatus(name="telegram", enabled=True, configured=True),
    ]
    mock.test_channel = AsyncMock(return_value=True)
    return mock


@pytest.fixture()
def client(manager_mock: MagicMock) -> Any:
    app = _make_app(manager_mock)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# GET /api/notify/channels
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_channels_returns_channel_list(
    client: Any, manager_mock: MagicMock
) -> None:
    """GET /api/notify/channels returns list of ChannelStatus objects."""
    with patch("finagent.routes.notify._build_manager", return_value=manager_mock):
        async with client as c:
            resp = await c.get("/api/notify/channels")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 2

    names = [ch["name"] for ch in data]
    assert "feishu" in names
    assert "telegram" in names


@pytest.mark.asyncio
async def test_list_channels_response_fields(
    client: Any, manager_mock: MagicMock
) -> None:
    """Each ChannelStatus has name, enabled, configured, last_error fields."""
    with patch("finagent.routes.notify._build_manager", return_value=manager_mock):
        async with client as c:
            resp = await c.get("/api/notify/channels")

    item = resp.json()[0]
    assert "name" in item
    assert "enabled" in item
    assert "configured" in item
    assert "last_error" in item


@pytest.mark.asyncio
async def test_list_channels_unconfigured_feishu(
    client: Any, manager_mock: MagicMock
) -> None:
    """Feishu shows configured=False when no webhook URL is set."""
    with patch("finagent.routes.notify._build_manager", return_value=manager_mock):
        async with client as c:
            resp = await c.get("/api/notify/channels")

    feishu = next(ch for ch in resp.json() if ch["name"] == "feishu")
    assert feishu["configured"] is False
    assert feishu["enabled"] is False


# ---------------------------------------------------------------------------
# POST /api/notify/test/{channel}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_test_channel_valid_configured_returns_success(
    client: Any, manager_mock: MagicMock
) -> None:
    """POST /api/notify/test/telegram returns {success: true} when channel sends ok."""
    manager_mock.test_channel = AsyncMock(return_value=True)

    with patch("finagent.routes.notify._build_manager", return_value=manager_mock):
        async with client as c:
            resp = await c.post("/api/notify/test/telegram")

    assert resp.status_code == 200
    assert resp.json() == {"channel": "telegram", "success": True}


@pytest.mark.asyncio
async def test_test_channel_send_failure_returns_success_false(
    client: Any, manager_mock: MagicMock
) -> None:
    """POST /api/notify/test/feishu returns {success: false} when channel returns False."""
    manager_mock.test_channel = AsyncMock(return_value=False)

    with patch("finagent.routes.notify._build_manager", return_value=manager_mock):
        async with client as c:
            resp = await c.post("/api/notify/test/feishu")

    assert resp.status_code == 200
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_test_channel_invalid_name_returns_404(
    client: Any, manager_mock: MagicMock
) -> None:
    """POST /api/notify/test/{unknown} returns 404."""
    with patch("finagent.routes.notify._build_manager", return_value=manager_mock):
        async with client as c:
            resp = await c.post("/api/notify/test/unknown_channel")

    assert resp.status_code == 404
    assert "unknown_channel" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_test_channel_valid_names_all_accepted(
    client: Any, manager_mock: MagicMock
) -> None:
    """All valid channel names (feishu, telegram, discord, email, webhook) are accepted."""
    manager_mock.test_channel = AsyncMock(return_value=False)
    valid_names = ["feishu", "telegram", "discord", "email", "webhook"]

    with patch("finagent.routes.notify._build_manager", return_value=manager_mock):
        async with client as c:
            for name in valid_names:
                resp = await c.post(f"/api/notify/test/{name}")
                assert resp.status_code == 200, f"Expected 200 for channel '{name}'"


@pytest.mark.asyncio
async def test_test_channel_response_schema(
    client: Any, manager_mock: MagicMock
) -> None:
    """Response has 'channel' and 'success' fields."""
    manager_mock.test_channel = AsyncMock(return_value=True)

    with patch("finagent.routes.notify._build_manager", return_value=manager_mock):
        async with client as c:
            resp = await c.post("/api/notify/test/discord")

    data = resp.json()
    assert "channel" in data
    assert "success" in data
    assert data["channel"] == "discord"
