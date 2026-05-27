"""NotifyManager — orchestrates sending to all configured channels.

Design contract:
- One failing channel never affects others (isolated try/except per channel).
- Dedup window: identical title+body within 5 minutes is discarded once.
- All HTTP errors surfaced via logger.exception for full stack trace.
"""

from __future__ import annotations

import hashlib
import logging
import time

import httpx

from finrobot.engine.notify.base import ChannelStatus, NotifyChannel, NotifyMessage

logger = logging.getLogger(__name__)


class NotifyManager:
    def __init__(self, channels: list[NotifyChannel] | None = None) -> None:
        self._channels: list[NotifyChannel] = channels or []
        self._dedup: dict[str, float] = {}  # hash → timestamp
        self._dedup_ttl: float = 300.0  # 5 minutes
        self._errors: dict[str, str] = {}  # channel_name → last error

    def add_channel(self, channel: NotifyChannel) -> None:
        self._channels.append(channel)

    def get_status(self) -> list[ChannelStatus]:
        return [
            ChannelStatus(
                name=ch.name,
                enabled=ch.is_configured(),
                configured=ch.is_configured(),
                last_error=self._errors.get(ch.name),
            )
            for ch in self._channels
        ]

    async def send(self, message: NotifyMessage) -> dict[str, bool]:
        """Send to all configured channels. Returns {channel_name: success}.

        A channel that is not configured is skipped entirely (not included in
        the result dict).  A channel that raises an exception returns False and
        records the error — all remaining channels still execute.
        """
        # ── Dedup check ──────────────────────────────────────────────────────
        msg_hash = hashlib.md5(f"{message.title}{message.body}".encode()).hexdigest()
        now = time.time()
        if msg_hash in self._dedup and (now - self._dedup[msg_hash]) < self._dedup_ttl:
            logger.info("Notification deduped (same content within TTL window)")
            return {}
        self._dedup[msg_hash] = now

        # Evict expired dedup entries
        cutoff = now - self._dedup_ttl
        self._dedup = {k: v for k, v in self._dedup.items() if v > cutoff}

        # ── Send loop ────────────────────────────────────────────────────────
        results: dict[str, bool] = {}
        for channel in self._channels:
            if not channel.is_configured():
                continue
            try:
                success = await channel.send(message)
                results[channel.name] = success
                if success:
                    self._errors.pop(channel.name, None)
                else:
                    self._errors[channel.name] = "send() returned False"
                    logger.warning(
                        "Notification channel %s: send() returned False",
                        channel.name,
                    )
            except (httpx.HTTPError, OSError, TimeoutError) as exc:
                logger.exception(
                    "Notification channel %s failed with network/IO error", channel.name
                )
                results[channel.name] = False
                self._errors[channel.name] = str(exc)
            except (ValueError, RuntimeError) as exc:
                logger.exception(
                    "Notification channel %s failed with unexpected error", channel.name
                )
                results[channel.name] = False
                self._errors[channel.name] = str(exc)

        return results

    async def test_channel(self, channel_name: str) -> bool:
        """Send a test message to a specific channel by name.

        Returns False if the channel is unknown, not configured, or the send
        fails.  Errors are stored in self._errors for retrieval via get_status().
        """
        for ch in self._channels:
            if ch.name != channel_name:
                continue
            if not ch.is_configured():
                return False
            msg = NotifyMessage(
                title="FinRobot Test Notification",
                body="If you see this, the channel is configured correctly.",
                type="system",
            )
            try:
                return await ch.send(msg)
            except (httpx.HTTPError, OSError, TimeoutError, ValueError, RuntimeError):
                logger.exception("Test notification to channel %s failed", channel_name)
                self._errors[channel_name] = "test send failed"
                return False
        return False
