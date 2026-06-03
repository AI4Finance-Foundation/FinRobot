"""BUG-070: the git_commit provenance stamp on every compute artifact must
degrade to None on hosts without git (pip-installed users / Docker slim / CI)
instead of crashing the final artifact-landing step.

`_get_git_commit()` shells out to `git rev-parse --short HEAD`. Its except tuple
must catch the exceptions subprocess actually raises:
  - git absent from PATH  -> FileNotFoundError (an OSError)
  - git wedged past timeout -> subprocess.TimeoutExpired (a SubprocessError)
The previous except (ImportError/AttributeError/TypeError/ValueError) caught
neither, so both punched through `_make_base_compute_version` and crashed the
build. These tests pin the degrade-to-None behaviour.
"""

from __future__ import annotations

import subprocess

import pytest

from finrobot.artifact import builders


def test_get_git_commit_returns_none_when_git_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """git not on PATH raises FileNotFoundError -> stamp degrades to None."""

    def _raise_missing(*_args: object, **_kwargs: object) -> object:
        raise FileNotFoundError("[Errno 2] No such file or directory: 'git'")

    monkeypatch.setattr(builders.subprocess, "run", _raise_missing)

    assert builders._get_git_commit() is None


def test_get_git_commit_returns_none_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """git wedged past the 2s timeout raises TimeoutExpired -> None."""

    def _raise_timeout(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd=["git"], timeout=2)

    monkeypatch.setattr(builders.subprocess, "run", _raise_timeout)

    assert builders._get_git_commit() is None


def test_make_base_compute_version_does_not_crash_without_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The compute-version stamp builds with git_commit=None, no exception."""

    def _raise_missing(*_args: object, **_kwargs: object) -> object:
        raise FileNotFoundError("[Errno 2] No such file or directory: 'git'")

    monkeypatch.setattr(builders.subprocess, "run", _raise_missing)

    version = builders._make_base_compute_version("dcf_v1")

    assert version.git_commit is None
    assert version.formula_id == "dcf_v1"
