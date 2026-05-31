"""Logging filter that stamps each record with the active trace ids."""

from __future__ import annotations

import logging

from finrobot.obs.context import current_trace


class TraceFilter(logging.Filter):
    """Inject request_id/session_id/run_id onto every record.

    Runs on the emit path (cheap dict reads from contextvars), so formatters
    can reference ``%(run_id)s`` etc. unconditionally.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        trace = current_trace()
        record.request_id = trace["request_id"]
        record.session_id = trace["session_id"]
        record.run_id = trace["run_id"]
        return True
