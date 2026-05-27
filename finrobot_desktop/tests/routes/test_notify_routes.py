"""Route tests for /api/notify/test/{channel}.

Only the test endpoint is exposed; /channels was retired (Settings UI tracks
channel state locally from the settings payload). Mock NotifyManager so no
real HTTP calls fire.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from finrobot.routes.notify import router as notify_router


def _make_app(manager_mock: Any) -> FastAPI:
    test_app = FastAPI()

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
    mock.test_channel = AsyncMock(return_value=True)
    return mock


@pytest.mark.asyncio
async def test_test_channel_valid_configured_returns_success(
    manager_mock: MagicMock,
) -> None:
    app = _make_app(manager_mock)
    with patch("finrobot.routes.notify._build_manager", return_value=manager_mock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post("/api/notify/test/feishu")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"channel": "feishu", "success": True}
    manager_mock.test_channel.assert_awaited_once_with("feishu")


@pytest.mark.asyncio
async def test_test_channel_send_failure_returns_success_false(
    manager_mock: MagicMock,
) -> None:
    manager_mock.test_channel = AsyncMock(return_value=False)
    app = _make_app(manager_mock)
    with patch("finrobot.routes.notify._build_manager", return_value=manager_mock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post("/api/notify/test/discord")

    assert resp.status_code == 200
    assert resp.json() == {"channel": "discord", "success": False}


@pytest.mark.asyncio
async def test_test_channel_unknown_name_returns_404(
    manager_mock: MagicMock,
) -> None:
    app = _make_app(manager_mock)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        resp = await c.post("/api/notify/test/slack")

    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert "Unknown channel" in detail
    assert "slack" in detail
    manager_mock.test_channel.assert_not_awaited()


@pytest.mark.parametrize("channel", ["feishu", "telegram", "discord", "email", "webhook"])
@pytest.mark.asyncio
async def test_all_valid_channels_accepted(channel: str, manager_mock: MagicMock) -> None:
    app = _make_app(manager_mock)
    with patch("finrobot.routes.notify._build_manager", return_value=manager_mock):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            resp = await c.post(f"/api/notify/test/{channel}")
    assert resp.status_code == 200
    assert resp.json()["channel"] == channel
