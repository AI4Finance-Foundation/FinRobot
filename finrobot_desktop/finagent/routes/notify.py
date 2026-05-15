"""Notification routes — test channels, list channel status."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.requests import Request

from finagent.engine.notify.base import ChannelStatus
from finagent.engine.notify.manager import NotifyManager

router = APIRouter(prefix="/api/notify", tags=["notify"])

logger = logging.getLogger(__name__)


class TestChannelResponse(BaseModel):
    channel: str
    success: bool


def _build_manager(request: Request) -> NotifyManager:
    """Build (or return cached) NotifyManager from current runtime settings.

    The manager is cached on ``app.state.notify_manager``.  It is rebuilt
    whenever the settings object reference changes (i.e. after a PUT /settings
    that calls _replace_runtime_settings).  This avoids rebuilding on every
    request while staying in sync with live config changes.
    """
    settings = request.app.state.deps.settings
    cached_manager: NotifyManager | None = getattr(request.app.state, "notify_manager", None)
    cached_settings = getattr(request.app.state, "_notify_manager_settings", None)

    if cached_manager is not None and cached_settings is settings:
        return cached_manager

    # Import channel implementations here to avoid circular-import risk
    # (engine/notify imports only stdlib + httpx, never routes).
    from finagent.engine.notify.discord import DiscordChannel
    from finagent.engine.notify.email_channel import EmailChannel
    from finagent.engine.notify.feishu import FeishuChannel
    from finagent.engine.notify.telegram import TelegramChannel
    from finagent.engine.notify.webhook import WebhookChannel

    manager = NotifyManager(
        channels=[
            FeishuChannel(webhook_url=settings.feishu_webhook_url or None),
            TelegramChannel(
                bot_token=settings.telegram_bot_token or None,
                chat_id=settings.telegram_chat_id or None,
            ),
            DiscordChannel(webhook_url=settings.discord_webhook_url or None),
            EmailChannel(
                smtp_host=settings.email_smtp_host or None,
                smtp_port=settings.email_smtp_port,
                smtp_user=settings.email_smtp_user or None,
                smtp_pass=settings.email_smtp_pass or None,
                to_addr=settings.email_to or None,
            ),
            WebhookChannel(url=settings.custom_webhook_url or None),
        ]
    )

    request.app.state.notify_manager = manager
    request.app.state._notify_manager_settings = settings
    return manager


@router.get("/channels", response_model=list[ChannelStatus])
async def list_channels(request: Request) -> list[ChannelStatus]:
    """List all notification channels and their configuration/error status."""
    manager = _build_manager(request)
    return manager.get_status()


@router.post("/test/{channel}", response_model=TestChannelResponse)
async def test_channel(channel: str, request: Request) -> TestChannelResponse:
    """Send a test notification to a specific channel.

    Returns 404 if the channel name is unknown or not configured.
    """
    _VALID_CHANNELS = {"feishu", "telegram", "discord", "email", "webhook"}
    if channel not in _VALID_CHANNELS:
        raise HTTPException(
            status_code=404,
            detail=(f"Unknown channel '{channel}'. Valid channels: {sorted(_VALID_CHANNELS)}"),
        )
    manager = _build_manager(request)
    success = await manager.test_channel(channel)
    return TestChannelResponse(channel=channel, success=success)
