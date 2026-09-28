"""File (JSON) and console (human) formatters sharing one LogRecord."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

_LEVEL_COLOR = {
    "DEBUG": "\x1b[36m",
    "INFO": "\x1b[32m",
    "WARNING": "\x1b[33m",
    "ERROR": "\x1b[31m",
    "CRITICAL": "\x1b[41m",
}
_RESET = "\x1b[0m"


def _iso(record: logging.LogRecord) -> str:
    return datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Machine-greppable trace fields."""

    def format(self, record: logging.LogRecord) -> str:
        try:
            msg = record.getMessage()
        except (TypeError, ValueError):
            msg = str(record.msg)
        payload: dict[str, object] = {
            "ts": _iso(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": msg,
            "request_id": getattr(record, "request_id", "-"),
            "session_id": getattr(record, "session_id", "-"),
            "run_id": getattr(record, "run_id", "-"),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class HumanFormatter(logging.Formatter):
    """Colorized single line for the terminal: HH:MM:SS LEVEL [run] logger msg."""

    def __init__(self, color: bool | None = None) -> None:
        super().__init__()
        # color is resolved by the caller (obs.setup passes
        # config.console_color_enabled, which honors NO_COLOR + isatty). When
        # None, fall back to a plain isatty check — the formatter never reads
        # environment variables itself (that lookup belongs in config.py).
        if color is None:
            self._color = bool(getattr(sys.stderr, "isatty", lambda: False)())
        else:
            self._color = color

    def format(self, record: logging.LogRecord) -> str:
        # tz asymmetry is intentional: console shows local time for readability,
        # the JSON file sink emits UTC for machine correlation across hosts.
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        run = getattr(record, "run_id", "-")
        try:
            msg = record.getMessage()
        except (TypeError, ValueError):
            msg = str(record.msg)
        level = record.levelname
        if self._color:
            tint = _LEVEL_COLOR.get(level, "")
            level = f"{tint}{level:<7}{_RESET}"
        else:
            level = f"{level:<7}"
        line = f"{ts} {level} [{run}] {record.name}  {msg}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line
