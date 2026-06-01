"""Everything under tests/integration/ is a live acceptance test (real
yfinance / SEC / LLM calls). Auto-mark every item *in this directory*
``integration`` so the default gate (``addopts = -m 'not integration'``) skips
the whole acceptance suite to completion — the per-test ``@pytest.mark.integration``
decorators here were applied unevenly, leaving unmarked tests that stalled
``pytest tests/`` on real network calls. Run it explicitly with ``pytest -m integration``.

NOTE: ``pytest_collection_modifyitems`` receives the *whole* session's item
list even from a subdirectory conftest, so we must filter to items that live
under this directory — otherwise every test in the repo gets marked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_INTEGRATION_DIR = Path(__file__).parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        item_path = Path(str(item.fspath))
        if _INTEGRATION_DIR == item_path.parent or _INTEGRATION_DIR in item_path.parents:
            item.add_marker(pytest.mark.integration)
