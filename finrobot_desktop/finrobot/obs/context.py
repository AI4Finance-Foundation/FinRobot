"""Trace-id propagation via contextvars.

A single LogRecord can be enriched with the active request/session/run ids
without threading them through every function call — the ids ride contextvars,
which asyncio copies into child tasks automatically, so pipeline steps inherit
the binding for free.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_request_id: ContextVar[str] = ContextVar("finrobot_request_id", default="-")
_session_id: ContextVar[str] = ContextVar("finrobot_session_id", default="-")
_run_id: ContextVar[str] = ContextVar("finrobot_run_id", default="-")


def current_trace() -> dict[str, str]:
    """Snapshot the active trace ids (``-`` when unbound)."""
    return {
        "request_id": _request_id.get(),
        "session_id": _session_id.get(),
        "run_id": _run_id.get(),
    }


@contextmanager
def bind_request(request_id: str) -> Iterator[None]:
    """Bind a request id for the duration of the ``with`` block."""
    token = _request_id.set(request_id)
    try:
        yield
    finally:
        _request_id.reset(token)


@contextmanager
def bind_session(session_id: str) -> Iterator[None]:
    """Bind a session id for the duration of the ``with`` block."""
    token = _session_id.set(session_id)
    try:
        yield
    finally:
        _session_id.reset(token)


@contextmanager
def bind_run(run_id: str) -> Iterator[None]:
    """Bind a run id for the duration of the ``with`` block."""
    token = _run_id.set(run_id)
    try:
        yield
    finally:
        _run_id.reset(token)
