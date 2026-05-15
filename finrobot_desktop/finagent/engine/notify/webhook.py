"""Generic webhook notification channel."""
from __future__ import annotations

import logging

import httpx

from finagent.engine.notify.base import NotifyChannel, NotifyMessage

logger = logging.getLogger(__name__)


class WebhookChannel(NotifyChannel):
    name = "webhook"

    def __init__(self, url: str | None = None) -> None:
        self._url = url

    def is_configured(self) -> bool:
        return bool(self._url)

    async def send(self, message: NotifyMessage) -> bool:
        if not self._url:
            return False
        payload = {
            "title": message.title,
            "body": message.body,
            "ticker": message.ticker,
            "type": message.type,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(self._url, json=payload)
            if not (200 <= resp.status_code < 300):
                logger.warning(
                    "Generic webhook returned HTTP %d: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return False
            return True
