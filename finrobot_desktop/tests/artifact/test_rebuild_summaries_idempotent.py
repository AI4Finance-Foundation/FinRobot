"""Regression for the rebuild_summaries IO leak.

`ArtifactStore.rebuild_summaries` used to unconditionally rewrite every
ticker's index.json on every startup. For users with 500 studied tickers
that's 500 disk writes per process boot (and every uvicorn --reload
cycle in dev). The skip-when-unchanged path keeps the migration
idempotent without the IO.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from finagent.artifact.store import ArtifactStore
from tests.artifact.conftest import _make_artifact


@pytest.mark.asyncio
async def test_rebuild_summaries_is_noop_when_indexes_current(tmp_path: Path) -> None:
    """save() writes the current-format index, so rebuild has nothing to do."""
    store = ArtifactStore(base_dir=tmp_path / "artifacts")
    await store.save(_make_artifact(id="art_AAPL_dcf1", ticker="AAPL"))
    await store.save(_make_artifact(id="art_MSFT_dcf1", ticker="MSFT"))

    # Indexes are already current-format → rebuild should be a 0 rewrite.
    rewritten = await store.rebuild_summaries()
    assert rewritten == 0

    # mtime stays put — proves _write_atomic was never called.
    idx_aapl = tmp_path / "artifacts" / "AAPL" / "index.json"
    idx_msft = tmp_path / "artifacts" / "MSFT" / "index.json"
    mtime_aapl_before = idx_aapl.stat().st_mtime_ns
    mtime_msft_before = idx_msft.stat().st_mtime_ns

    # Second call confirms idempotence.
    again = await store.rebuild_summaries()
    assert again == 0
    assert idx_aapl.stat().st_mtime_ns == mtime_aapl_before
    assert idx_msft.stat().st_mtime_ns == mtime_msft_before


@pytest.mark.asyncio
async def test_rebuild_summaries_rewrites_when_legacy_index_present(tmp_path: Path) -> None:
    """A legacy index missing the v5 fields should still trigger a rewrite."""
    store = ArtifactStore(base_dir=tmp_path / "artifacts")
    await store.save(_make_artifact(id="art_AAPL_dcf1", ticker="AAPL"))

    # Corrupt the index to look "legacy" — missing target_price, entry_price.
    idx_aapl = tmp_path / "artifacts" / "AAPL" / "index.json"
    idx_aapl.write_text(
        '[{"id":"art_AAPL_dcf1","ticker":"AAPL","cross_tickers":[],"type":"dcf",'
        '"created_at":"2026-05-13T10:00:00+00:00","headline":"old","source":"x",'
        '"archived":false}]',
        encoding="utf-8",
    )

    rewritten = await store.rebuild_summaries()
    assert rewritten == 1  # The legacy index doesn't match → must rewrite.

    # And a second call right after should be the no-op skip path.
    again = await store.rebuild_summaries()
    assert again == 0
