import logging
from logging.handlers import TimedRotatingFileHandler

import pytest

import finrobot.obs.setup as setup_mod
from finrobot.config import FinRobotSettings
from finrobot.obs.setup import setup_logging


@pytest.fixture(autouse=True)
def _restore_root_logging() -> "pytest.Generator[None, None, None]":
    root = logging.getLogger()
    saved = root.handlers[:]
    saved_level = root.level
    saved_flag = setup_mod._CONFIGURED
    try:
        yield
    finally:
        root.handlers[:] = saved
        root.setLevel(saved_level)
        setup_mod._CONFIGURED = saved_flag


def test_setup_adds_file_and_console_handlers(tmp_path) -> None:
    s = FinRobotSettings(log_to_file=True, log_retention_days=5)
    setup_logging(s, logs_dir=tmp_path, force=True)
    root = logging.getLogger()
    file_handlers = [h for h in root.handlers if isinstance(h, TimedRotatingFileHandler)]
    assert len(file_handlers) == 1
    assert file_handlers[0].backupCount == 5
    assert file_handlers[0].baseFilename.endswith("finrobot.log")


def test_setup_is_idempotent(tmp_path) -> None:
    s = FinRobotSettings()
    setup_logging(s, logs_dir=tmp_path, force=True)
    n = len(logging.getLogger().handlers)
    setup_logging(s, logs_dir=tmp_path)  # no force → no-op
    assert len(logging.getLogger().handlers) == n


def test_setup_no_file_when_disabled(tmp_path) -> None:
    s = FinRobotSettings(log_to_file=False)
    setup_logging(s, logs_dir=tmp_path, force=True)
    root = logging.getLogger()
    assert not any(isinstance(h, TimedRotatingFileHandler) for h in root.handlers)


def test_setup_degrades_when_dir_unwritable(tmp_path) -> None:
    s = FinRobotSettings(log_to_file=True)
    bad = tmp_path / "nope"
    bad.write_text("not a dir")  # path exists as a FILE → mkdir under it fails
    # Should NOT raise — console-only fallback.
    setup_logging(s, logs_dir=bad / "logs", force=True)
    assert logging.getLogger().handlers  # at least the console handler present
