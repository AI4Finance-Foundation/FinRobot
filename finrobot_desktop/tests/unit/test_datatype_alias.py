"""DataType alias compatibility — sealed by spec v3 §4 门 2 test #2.

Why this exists:
  2026-05 EdgarTools migration introduced ``DataType.FILINGS_10K``,
  intended to replace the legacy ``DataType.FILINGS``. Two failure modes
  must be guarded against:

  1. **Cache slot collision**: legacy callers passing ``DataType.FILINGS``
     and new callers passing ``DataType.FILINGS_10K`` for the same ticker
     must hit the same cache row — otherwise the same 10-K gets fetched
     from SEC twice within the 7-day TTL window.
  2. **Old artifact deserialization**: artifacts written before the
     migration carry ``"data_type": "filings"``; re-validating those JSON
     blobs (e.g. the legacy-fs → SQLite migration) must not raise.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from finrobot.engine.data.cache import (
    _DATA_TYPE_ALIASES,
    _get_ttl_seconds,
    _normalize_data_type,
)
from finrobot.engine.data.types import DataType


class TestDataTypeAlias:
    def test_filings_alias_to_filings_10k(self) -> None:
        """``DataType.FILINGS`` is enum-distinct from ``DataType.FILINGS_10K`` but
        the cache layer normalises both to the same key."""
        assert DataType.FILINGS is not DataType.FILINGS_10K
        assert _normalize_data_type(DataType.FILINGS) == DataType.FILINGS_10K.value
        assert _normalize_data_type(DataType.FILINGS_10K) == DataType.FILINGS_10K.value
        # The raw string "filings" (old artifact JSON / SDK shim) also normalises.
        assert _normalize_data_type("filings") == DataType.FILINGS_10K.value

    def test_alias_table_only_contains_documented_mappings(self) -> None:
        """Guard against silent alias drift — every entry must be intentional."""
        assert _DATA_TYPE_ALIASES == {"filings": "filings_10k"}

    def test_ttl_consistent_across_alias(self) -> None:
        """Old + new key must return the SAME TTL number (no 60s vs 7d mismatch)."""
        ttl_old = _get_ttl_seconds(DataType.FILINGS)
        ttl_new = _get_ttl_seconds(DataType.FILINGS_10K)
        ttl_raw = _get_ttl_seconds("filings")
        assert ttl_old == ttl_new == ttl_raw == 604800

    def test_legacy_filings_enum_reverse_deserializes(self) -> None:
        """Pre-2026-05 artifacts/SDK requests carry ``"filings"`` strings.

        After enum value lookup, the result is the legacy-named member —
        adapter layer must accept this and dispatch to the 10-K handler.
        """
        legacy = DataType("filings")
        assert legacy is DataType.FILINGS
        # Adapter dispatch: this value must hash/compare equal to FILINGS_10K
        # via the normaliser so a downstream `if data_type in (FILINGS_10K, ...)`
        # branch still catches it (verified by the cache TTL test above; the
        # adapter does this branch explicitly — see edgar_provider._fetch_sync).


class TestDataTypeAliasCacheRoundTrip:
    """End-to-end: write under legacy key, read under new key, get same row."""

    @pytest.mark.asyncio
    async def test_set_legacy_get_new_collides(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        from finrobot.engine.data.cache import DataCache
        from finrobot.engine.data.interface import DataResult

        cache = DataCache(db_path=str(tmp_path / "cache.db"))
        envelope = DataResult(
            data={"marker": "from_legacy_FILINGS_key"},
            provider="test",
            ticker="AAPL",
            data_type=DataType.FILINGS,
            timestamp=datetime.now(tz=timezone.utc),
            warnings=[],
        )
        await cache.set(DataType.FILINGS, "AAPL", envelope)

        # New key reads the SAME slot
        got = await cache.get(DataType.FILINGS_10K, "AAPL")
        assert got is not None
        assert got.data.data == {"marker": "from_legacy_FILINGS_key"}, (
            "FILINGS write must be readable under FILINGS_10K — alias broken"
        )

        # And vice-versa
        envelope2 = DataResult(
            data={"marker": "from_new_FILINGS_10K_key"},
            provider="test",
            ticker="AAPL",
            data_type=DataType.FILINGS_10K,
            timestamp=datetime.now(tz=timezone.utc),
            warnings=[],
        )
        await cache.set(DataType.FILINGS_10K, "AAPL", envelope2)
        got2 = await cache.get(DataType.FILINGS, "AAPL")
        assert got2 is not None
        assert got2.data.data == {"marker": "from_new_FILINGS_10K_key"}
        await cache.close()
