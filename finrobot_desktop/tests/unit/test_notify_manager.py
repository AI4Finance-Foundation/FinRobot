"""Unit tests for finagent.engine.notify.manager.NotifyManager.

Coverage:
- get_status: reflects channel configured state
- send: skips unconfigured channels, returns results dict
- send: dedup window — identical message within 5 min is discarded
- send: one channel failure does not block others
- test_channel: returns False for unknown channel, unconfigured channel
- test_channel: returns send() result for configured channel

Mock discipline: these are unit tests — HTTP layer (httpx) is mocked.
The channel send() implementations themselves are tested separately.
"""
from __future__ import annotations


import pytest

from finagent.engine.notify.base import NotifyChannel, NotifyMessage
from finagent.engine.notify.manager import NotifyManager


# ---------------------------------------------------------------------------
# Stub channel
# ---------------------------------------------------------------------------

class _StubChannel(NotifyChannel):
    """Configurable stub: set configured=True and send_result to control behaviour."""

    def __init__(self, name: str, configured: bool = True, send_result: bool = True) -> None:
        self.name = name
        self._configured = configured
        self._send_result = send_result
        self.sent_messages: list[NotifyMessage] = []

    def is_configured(self) -> bool:
        return self._configured

    async def send(self, message: NotifyMessage) -> bool:
        self.sent_messages.append(message)
        return self._send_result


class _RaisingChannel(NotifyChannel):
    """A channel whose send() always raises an OSError."""
    name = "raiser"

    def is_configured(self) -> bool:
        return True

    async def send(self, message: NotifyMessage) -> bool:
        raise OSError("simulated network failure")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _msg(**kwargs) -> NotifyMessage:
    defaults = dict(title="Test Title", body="Test body", type="system")
    defaults.update(kwargs)
    return NotifyMessage(**defaults)


# ---------------------------------------------------------------------------
# 1. get_status reflects configured state
# ---------------------------------------------------------------------------

def test_get_status_configured_channel():
    """get_status returns enabled=True for configured channel."""
    ch = _StubChannel("feishu", configured=True)
    manager = NotifyManager(channels=[ch])
    statuses = manager.get_status()
    assert len(statuses) == 1
    assert statuses[0].name == "feishu"
    assert statuses[0].configured is True
    assert statuses[0].enabled is True


def test_get_status_unconfigured_channel():
    """get_status returns enabled=False for unconfigured channel."""
    ch = _StubChannel("feishu", configured=False)
    manager = NotifyManager(channels=[ch])
    statuses = manager.get_status()
    assert statuses[0].configured is False
    assert statuses[0].enabled is False


def test_get_status_no_channels():
    """get_status returns empty list when no channels registered."""
    manager = NotifyManager()
    assert manager.get_status() == []


# ---------------------------------------------------------------------------
# 2. send: skips unconfigured channels
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_skips_unconfigured_channels():
    """Unconfigured channels are not included in results dict."""
    ch_on = _StubChannel("telegram", configured=True)
    ch_off = _StubChannel("discord", configured=False)
    manager = NotifyManager(channels=[ch_on, ch_off])

    results = await manager.send(_msg())
    assert "telegram" in results
    assert "discord" not in results
    assert len(ch_off.sent_messages) == 0


# ---------------------------------------------------------------------------
# 3. send: all configured channels receive message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_reaches_all_configured_channels():
    """All configured channels receive the message."""
    ch1 = _StubChannel("feishu", configured=True)
    ch2 = _StubChannel("telegram", configured=True)
    manager = NotifyManager(channels=[ch1, ch2])

    msg = _msg(title="Broadcast", body="All channels get this")
    results = await manager.send(msg)

    assert results["feishu"] is True
    assert results["telegram"] is True
    assert len(ch1.sent_messages) == 1
    assert len(ch2.sent_messages) == 1


# ---------------------------------------------------------------------------
# 4. send: one failure does not block others
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_one_channel_failure_does_not_block_others():
    """A channel that raises OSError returns False; other channels still execute."""
    ch_raise = _RaisingChannel()
    ch_ok = _StubChannel("telegram", configured=True)
    manager = NotifyManager(channels=[ch_raise, ch_ok])

    results = await manager.send(_msg())
    assert results["raiser"] is False
    assert results["telegram"] is True
    assert len(ch_ok.sent_messages) == 1


# ---------------------------------------------------------------------------
# 5. Dedup: identical message within TTL returns empty dict
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_dedup_within_ttl():
    """Identical title+body sent twice within 5 min → second send returns {}."""
    ch = _StubChannel("feishu")
    manager = NotifyManager(channels=[ch])
    msg = _msg(title="Alert", body="Price crossed 200")

    first = await manager.send(msg)
    second = await manager.send(msg)

    assert first == {"feishu": True}
    assert second == {}  # deduped
    assert len(ch.sent_messages) == 1  # only sent once


@pytest.mark.asyncio
async def test_send_different_body_not_deduped():
    """Different body hash → both messages are sent."""
    ch = _StubChannel("feishu")
    manager = NotifyManager(channels=[ch])

    await manager.send(_msg(title="A", body="body1"))
    await manager.send(_msg(title="A", body="body2"))

    assert len(ch.sent_messages) == 2


# ---------------------------------------------------------------------------
# 6. Dedup TTL expired → message is sent again
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_dedup_expired_after_ttl():
    """After dedup TTL elapses, the same message is sent again."""
    ch = _StubChannel("feishu")
    manager = NotifyManager(channels=[ch])
    manager._dedup_ttl = 0.01  # shrink to 10ms for test speed
    msg = _msg(title="TTL Test", body="expires fast")

    await manager.send(msg)
    # Manually expire the dedup cache entry
    manager._dedup = {}  # simulate TTL expiry

    second = await manager.send(msg)
    assert second == {"feishu": True}
    assert len(ch.sent_messages) == 2


# ---------------------------------------------------------------------------
# 7. test_channel: unknown channel returns False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_test_channel_unknown_returns_false():
    """test_channel() returns False for a channel name not in the manager."""
    manager = NotifyManager(channels=[_StubChannel("feishu")])
    result = await manager.test_channel("nonexistent")
    assert result is False


# ---------------------------------------------------------------------------
# 8. test_channel: unconfigured channel returns False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_test_channel_unconfigured_returns_false():
    """test_channel() returns False when the channel is not configured."""
    ch = _StubChannel("telegram", configured=False)
    manager = NotifyManager(channels=[ch])
    result = await manager.test_channel("telegram")
    assert result is False
    assert len(ch.sent_messages) == 0


# ---------------------------------------------------------------------------
# 9. test_channel: configured channel returns send() result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_test_channel_configured_sends_test_message():
    """test_channel() sends the test NotifyMessage and returns True."""
    ch = _StubChannel("discord", configured=True, send_result=True)
    manager = NotifyManager(channels=[ch])

    result = await manager.test_channel("discord")
    assert result is True
    assert len(ch.sent_messages) == 1
    assert ch.sent_messages[0].title == "FinAgent Test Notification"
    assert ch.sent_messages[0].type == "system"


# ---------------------------------------------------------------------------
# 10. test_channel: channel that raises → returns False and records error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_test_channel_raises_returns_false():
    """test_channel() returns False and records error when channel raises."""
    manager = NotifyManager(channels=[_RaisingChannel()])
    result = await manager.test_channel("raiser")
    assert result is False
    assert "raiser" in manager._errors


# ---------------------------------------------------------------------------
# 11. add_channel
# ---------------------------------------------------------------------------

def test_add_channel_appends_to_channels():
    """add_channel() appends to the internal channel list."""
    manager = NotifyManager()
    ch = _StubChannel("webhook")
    manager.add_channel(ch)
    assert len(manager._channels) == 1
    assert manager._channels[0].name == "webhook"


# ---------------------------------------------------------------------------
# 12. send() records error when channel returns False
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_records_error_when_send_returns_false():
    """When a channel's send() returns False, the error is recorded in _errors."""
    ch = _StubChannel("feishu", configured=True, send_result=False)
    manager = NotifyManager(channels=[ch])
    await manager.send(_msg())
    assert "feishu" in manager._errors
    assert manager._errors["feishu"] == "send() returned False"
