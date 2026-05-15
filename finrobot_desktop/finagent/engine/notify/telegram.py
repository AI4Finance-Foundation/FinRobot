"""Telegram bot notification channel."""
from __future__ import annotations

import logging

import httpx

from finagent.engine.notify.base import NotifyChannel, NotifyMessage

logger = logging.getLogger(__name__)


class TelegramChannel(NotifyChannel):
    name = "telegram"

    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
    ) -> None:
        self._token = bot_token
        self._chat_id = chat_id

    def is_configured(self) -> bool:
        return bool(self._token and self._chat_id)

    async def send(self, message: NotifyMessage) -> bool:
        if not self.is_configured():
            return False
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        text = f"**{message.title}**\n\n{message.body}"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                url,
                json={
                    "chat_id": self._chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                },
            )
            if resp.status_code != 200:
                logger.warning(
                    "Telegram API returned HTTP %d: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return False
            return True
