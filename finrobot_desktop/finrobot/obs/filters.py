"""Logging filters: trace-id stamping and secret-query redaction."""

from __future__ import annotations

import logging
import re
from typing import Any

from finrobot.obs.context import current_trace

# Secrets that ride in URL query strings: the per-launch capability token
# (``?token=`` on EventSource streams, which cannot set headers) and any
# legacy apikey-in-URL provider call. uvicorn's access logger prints the full
# request line, so without redaction these would land in ~/.finrobot/finrobot.log.
_SECRET_QS_RE = re.compile(r"((?:token|apikey|api_key)=)[^&\s\"']+", re.IGNORECASE)
_REDACT_REPL = r"\1REDACTED"


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


class RedactSecretsFilter(logging.Filter):
    """Scrub secret query params (token / apikey) from records before emit.

    Mutates both the pre-format message and the ``%``-args (uvicorn.access
    carries the full request line as an arg, not in ``msg``), so the secret is
    gone whether the record is rendered eagerly or lazily.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str) and ("=" in record.msg):
            record.msg = _SECRET_QS_RE.sub(_REDACT_REPL, record.msg)
        args = record.args
        if isinstance(args, tuple):
            record.args = tuple(_redact(a) for a in args)
        elif isinstance(args, dict):
            record.args = {k: _redact(v) for k, v in args.items()}
        return True


def _redact(value: Any) -> Any:
    if isinstance(value, str) and ("=" in value):
        return _SECRET_QS_RE.sub(_REDACT_REPL, value)
    return value
