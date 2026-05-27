"""Notification routes — send a test message to a configured channel.

Only the test endpoint is exposed: the Settings UI uses it to verify webhook
URLs, SMTP credentials, etc. before persisting them. Channel status is not
surfaced (UI tracks enabled-state locally from the settings payload).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.requests import Request

from finrobot.engine.notify.manager import NotifyManager

router = APIRouter(prefix="/api/notify", tags=["notify"])

logger = logging.getLogger(__name__)

_VALID_CHANNELS = frozenset({"feishu", "telegram", "discord", "email", "webhook"})


class TestChannelResponse(BaseModel):
    channel: str
    success: bool


def _build_manager(request: Request) -> NotifyManager:
    """Build (or return cached) NotifyManager from current runtime settings.

    Cached on ``app.state.notify_manager`` and invalidated when the settings
    object reference changes (after PUT /api/settings replaces deps.settings).
    """
    settings = request.app.state.deps.settings
    cached_manager: NotifyManager | None = getattr(request.app.state, "notify_manager", None)
    cached_settings = getattr(request.app.state, "_notify_manager_settings", None)

    if cached_manager is not None and cached_settings is settings:
        return cached_manager

    from finrobot.engine.notify.discord import DiscordChannel
    from finrobot.engine.notify.email_channel import EmailChannel
    from finrobot.engine.notify.feishu import FeishuChannel
    from finrobot.engine.notify.telegram import TelegramChannel
    from finrobot.engine.notify.webhook import WebhookChannel

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


@router.post("/test/{channel}", response_model=TestChannelResponse)
async def test_channel(channel: str, request: Request) -> TestChannelResponse:
    """Send a test notification to a specific channel.

    Returns 404 if the channel name is unknown. Returns ``{success: False}``
    when the channel is unconfigured or the underlying send fails.
    """
    if channel not in _VALID_CHANNELS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown channel '{channel}'. Valid channels: {sorted(_VALID_CHANNELS)}",
        )
    manager = _build_manager(request)
    success = await manager.test_channel(channel)
    return TestChannelResponse(channel=channel, success=success)
