"""Discord webhook notification channel."""

from __future__ import annotations

import logging

import httpx

from finagent.engine.notify.base import NotifyChannel, NotifyMessage

logger = logging.getLogger(__name__)


class DiscordChannel(NotifyChannel):
    name = "discord"

    def __init__(self, webhook_url: str | None = None) -> None:
        self._url = webhook_url

    def is_configured(self) -> bool:
        return bool(self._url)

    async def send(self, message: NotifyMessage) -> bool:
        if not self._url:
            return False
        payload = {
            "embeds": [
                {
                    "title": message.title,
                    "description": message.body[:2048],
                    "color": 14793533,  # gold
                }
            ]
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(self._url, json=payload)
            if resp.status_code not in (200, 204):
                logger.warning(
                    "Discord webhook returned HTTP %d: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return False
            return True
