"""Notification channel abstract base."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class NotifyMessage(BaseModel):
    title: str
    body: str  # markdown formatted
    ticker: str | None = None
    type: str = "report"  # report | alert | system


class ChannelStatus(BaseModel):
    name: str
    enabled: bool
    configured: bool
    last_error: str | None = None


class NotifyChannel(ABC):
    name: str

    @abstractmethod
    async def send(self, message: NotifyMessage) -> bool:
        """Send notification. Returns True on success."""
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if channel has required config (webhook URL, token, etc.)."""
        ...
