import logging

from finrobot.obs.context import bind_run
from finrobot.obs.filters import TraceFilter


def _record() -> logging.LogRecord:
    return logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hi",
        args=(),
        exc_info=None,
    )


def test_filter_injects_defaults() -> None:
    rec = _record()
    assert TraceFilter().filter(rec) is True
    assert rec.run_id == "-"  # type: ignore[attr-defined]
    assert rec.session_id == "-"  # type: ignore[attr-defined]
    assert rec.request_id == "-"  # type: ignore[attr-defined]


def test_filter_injects_bound_run() -> None:
    rec = _record()
    with bind_run("r_99"):
        TraceFilter().filter(rec)
    assert rec.run_id == "r_99"  # type: ignore[attr-defined]
