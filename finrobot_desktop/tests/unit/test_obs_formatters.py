import json
import logging

import pytest

from finrobot.config import console_color_enabled
from finrobot.obs.filters import TraceFilter
from finrobot.obs.formatters import HumanFormatter, JsonFormatter


def _record(msg: str = "hello", exc: bool = False) -> logging.LogRecord:
    exc_info = None
    if exc:
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            exc_info = sys.exc_info()
    rec = logging.LogRecord(
        name="finrobot.pipelines.dcf",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )
    TraceFilter().filter(rec)
    return rec


def test_json_formatter_emits_valid_line() -> None:
    out = JsonFormatter().format(_record())
    parsed = json.loads(out)
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "finrobot.pipelines.dcf"
    assert parsed["msg"] == "hello"
    assert parsed["run_id"] == "-"
    assert "ts" in parsed


def test_json_formatter_serializes_exc() -> None:
    parsed = json.loads(JsonFormatter().format(_record(exc=True)))
    assert "ValueError" in parsed["exc"]


def test_human_formatter_no_color_when_disabled() -> None:
    out = HumanFormatter(color=False).format(_record())
    assert "\x1b[" not in out
    assert "[-]" in out  # run_id placeholder
    assert "hello" in out


class _FakeStream:
    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_console_color_enabled_requires_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert console_color_enabled(_FakeStream(tty=True)) is True
    assert console_color_enabled(_FakeStream(tty=False)) is False


def test_console_color_enabled_honors_no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    # no-color.org: any non-empty NO_COLOR disables color even on a TTY.
    monkeypatch.setenv("NO_COLOR", "1")
    assert console_color_enabled(_FakeStream(tty=True)) is False
    monkeypatch.setenv("NO_COLOR", "")
    assert console_color_enabled(_FakeStream(tty=True)) is True


def test_formatters_survive_mismatched_args() -> None:
    rec = logging.LogRecord(
        name="finrobot.pipelines.dcf",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="val=%s %s",
        args=("a",),
        exc_info=None,
    )
    TraceFilter().filter(rec)

    json_out = JsonFormatter().format(rec)
    assert "val=%s" in json.loads(json_out)["msg"]

    human_out = HumanFormatter(color=False).format(rec)
    assert "val=%s" in human_out
