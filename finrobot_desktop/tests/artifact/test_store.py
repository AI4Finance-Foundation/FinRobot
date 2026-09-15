"""Tests for finrobot.artifact.store.ArtifactStore.

Coverage:
- save → get round-trip: full Artifact survives serialisation + deserialisation
- list_by_ticker: ticker filter, type filter, archived filter
- list_versions: same ticker+type sorted newest-first
- archive_stale: correctly marks old un-viewed artifacts
- concurrent save: parallel saves don't corrupt index.json
- delete: removes file and updates index
- mark_viewed: updates last_viewed_at and un-archives
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from finrobot.artifact.models import Artifact
from finrobot.artifact.store import ArtifactStore
from tests.artifact.conftest import _make_artifact

UTC = timezone.utc


@pytest.fixture
def store(tmp_store_dir: Path) -> ArtifactStore:
    return ArtifactStore(base_dir=tmp_store_dir)


class TestSaveGet:
    @pytest.mark.asyncio
    async def test_round_trip(self, store: ArtifactStore, sample_artifact: Artifact) -> None:
        """save() then get() returns an identical artifact."""
        await store.save(sample_artifact)
        loaded = await store.get(sample_artifact.id)

        assert loaded is not None
        assert loaded.id == sample_artifact.id
        assert loaded.ticker == "AAPL"
        assert loaded.type == "dcf"
        # Spot-check specific fields to ensure nothing is silently dropped
        assert loaded.assumptions.parameters["wacc"] == pytest.approx(0.082)
        assert loaded.outputs.structured["implied_price"] == pytest.approx(185.0)
        assert loaded.outputs.warnings == ["Simplified FCF formula used"]
        assert loaded.compute_version.formula_id == "dcf_simplified_v1"
        assert loaded.compute_version.git_commit == "abc1234"

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, store: ArtifactStore) -> None:
        result = await store.get("nonexistent_id_xyz")
        assert result is None

    @pytest.mark.asyncio
    async def test_cross_ticker_artifact_round_trip(self, store: ArtifactStore) -> None:
        """Cross-ticker artifacts (ticker=None) save + load like any other.

        Legacy implementation kept them in a separate ``_cross/`` directory;
        the SQLite implementation identifies them by ``ticker IS NULL``.
        Either way, the user-visible contract is the same: save then get.
        """
        art = _make_artifact(id="art_2026-05-13T10:00:00__cross_comps", ticker=None, type="comps")
        art.cross_tickers = ["AAPL", "MSFT"]
        await store.save(art)
        loaded = await store.get(art.id)
        assert loaded is not None
        assert loaded.ticker is None
        assert loaded.cross_tickers == ["AAPL", "MSFT"]


class TestListByTicker:
    @pytest.mark.asyncio
    async def test_filter_by_ticker(self, store: ArtifactStore, sample_artifact: Artifact) -> None:
        msft_art = _make_artifact(id="art_MSFT_dcf", ticker="MSFT")
        await store.save(sample_artifact)
        await store.save(msft_art)

        aapl_results = await store.list_by_ticker(ticker="AAPL")
        assert len(aapl_results) == 1
        assert aapl_results[0].id == sample_artifact.id
        assert aapl_results[0].ticker == "AAPL"

    @pytest.mark.asyncio
    async def test_filter_by_type(self, store: ArtifactStore) -> None:
        dcf_art = _make_artifact(id="art_AAPL_dcf", ticker="AAPL", type="dcf")
        lbo_art = _make_artifact(id="art_AAPL_lbo", ticker="AAPL", type="lbo")
        await store.save(dcf_art)
        await store.save(lbo_art)

        dcf_results = await store.list_by_ticker(ticker="AAPL", type="dcf")
        assert len(dcf_results) == 1
        assert dcf_results[0].type == "dcf"

    @pytest.mark.asyncio
    async def test_all_tickers_when_no_filter(self, store: ArtifactStore) -> None:
        aapl = _make_artifact(id="art_AAPL_dcf", ticker="AAPL")
        msft = _make_artifact(id="art_MSFT_dcf", ticker="MSFT")
        await store.save(aapl)
        await store.save(msft)

        results = await store.list_by_ticker()
        ids = {r.id for r in results}
        assert "art_AAPL_dcf" in ids
        assert "art_MSFT_dcf" in ids

    @pytest.mark.asyncio
    async def test_archived_excluded_by_default(self, store: ArtifactStore) -> None:
        art = _make_artifact(id="art_AAPL_archived")
        art.meta.archived = True
        await store.save(art)

        results = await store.list_by_ticker(ticker="AAPL")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_archived_included_when_requested(self, store: ArtifactStore) -> None:
        art = _make_artifact(id="art_AAPL_archived")
        art.meta.archived = True
        await store.save(art)

        results = await store.list_by_ticker(ticker="AAPL", include_archived=True)
        assert len(results) == 1
        assert results[0].archived is True

    @pytest.mark.asyncio
    async def test_limit_respected(self, store: ArtifactStore) -> None:
        for i in range(5):
            art = _make_artifact(id=f"art_AAPL_{i}")
            await store.save(art)

        results = await store.list_by_ticker(ticker="AAPL", limit=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_sorted_newest_first(self, store: ArtifactStore) -> None:
        early = _make_artifact(
            id="art_early",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        late = _make_artifact(
            id="art_late",
            created_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
        await store.save(early)
        await store.save(late)

        results = await store.list_by_ticker(ticker="AAPL")
        assert results[0].id == "art_late"
        assert results[1].id == "art_early"

    @pytest.mark.asyncio
    async def test_empty_store_returns_empty_list(self, store: ArtifactStore) -> None:
        results = await store.list_by_ticker()
        assert results == []


class TestListVersions:
    @pytest.mark.asyncio
    async def test_versions_sorted_newest_first(
        self, store: ArtifactStore, sample_artifact: Artifact, sample_artifact_v2: Artifact
    ) -> None:
        await store.save(sample_artifact)
        await store.save(sample_artifact_v2)

        versions = await store.list_versions("AAPL", "dcf")
        assert len(versions) == 2
        # sample_artifact_v2 has created_at 11:00, sample_artifact has 10:00
        assert versions[0].id == sample_artifact_v2.id
        assert versions[1].id == sample_artifact.id

    @pytest.mark.asyncio
    async def test_versions_include_archived(self, store: ArtifactStore) -> None:
        art = _make_artifact(id="art_archived_version")
        art.meta.archived = True
        await store.save(art)

        versions = await store.list_versions("AAPL", "dcf")
        assert any(v.id == "art_archived_version" for v in versions)


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_returns_true_on_success(
        self, store: ArtifactStore, sample_artifact: Artifact, tmp_store_dir: Path
    ) -> None:
        await store.save(sample_artifact)
        deleted = await store.delete(sample_artifact.id)
        assert deleted is True

    @pytest.mark.asyncio
    async def test_delete_removes_file(
        self, store: ArtifactStore, sample_artifact: Artifact, tmp_store_dir: Path
    ) -> None:
        await store.save(sample_artifact)
        await store.delete(sample_artifact.id)
        file_path = tmp_store_dir / "AAPL" / f"{sample_artifact.id}.json"
        assert not file_path.exists()

    @pytest.mark.asyncio
    async def test_delete_updates_index(
        self, store: ArtifactStore, sample_artifact: Artifact
    ) -> None:
        await store.save(sample_artifact)
        await store.delete(sample_artifact.id)

        results = await store.list_by_ticker(ticker="AAPL")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, store: ArtifactStore) -> None:
        deleted = await store.delete("nonexistent_id_xyz")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_get_after_delete_returns_none(
        self, store: ArtifactStore, sample_artifact: Artifact
    ) -> None:
        await store.save(sample_artifact)
        await store.delete(sample_artifact.id)
        result = await store.get(sample_artifact.id)
        assert result is None


class TestMarkViewed:
    @pytest.mark.asyncio
    async def test_mark_viewed_updates_last_viewed_at(
        self, store: ArtifactStore, sample_artifact: Artifact
    ) -> None:
        await store.save(sample_artifact)
        assert sample_artifact.meta.last_viewed_at is None

        await store.mark_viewed(sample_artifact.id)
        loaded = await store.get(sample_artifact.id)
        assert loaded is not None
        assert loaded.meta.last_viewed_at is not None

    @pytest.mark.asyncio
    async def test_mark_viewed_unarchives(self, store: ArtifactStore) -> None:
        art = _make_artifact(id="art_was_archived")
        art.meta.archived = True
        await store.save(art)

        await store.mark_viewed(art.id)
        loaded = await store.get(art.id)
        assert loaded is not None
        assert loaded.meta.archived is False

    @pytest.mark.asyncio
    async def test_mark_viewed_nonexistent_does_not_raise(self, store: ArtifactStore) -> None:
        # Should silently do nothing, not raise
        await store.mark_viewed("nonexistent_id")


class TestArchiveStale:
    @pytest.mark.asyncio
    async def test_stale_artifact_is_archived(self, store: ArtifactStore) -> None:
        """An artifact created >24h ago and never viewed gets archived."""
        from datetime import timedelta

        long_ago = datetime.now(UTC) - timedelta(hours=48)
        art = _make_artifact(id="art_old", created_at=long_ago)
        await store.save(art)

        count = await store.archive_stale(hours=24)
        assert count == 1

        loaded = await store.get(art.id)
        assert loaded is not None
        assert loaded.meta.archived is True

    @pytest.mark.asyncio
    async def test_fresh_artifact_not_archived(self, store: ArtifactStore) -> None:
        """An artifact created 1h ago should NOT be archived with hours=24."""
        from datetime import timedelta

        one_hour_ago = datetime.now(UTC) - timedelta(hours=1)
        art = _make_artifact(id="art_fresh", created_at=one_hour_ago)
        await store.save(art)

        count = await store.archive_stale(hours=24)
        assert count == 0

    @pytest.mark.asyncio
    async def test_already_archived_not_double_counted(self, store: ArtifactStore) -> None:
        art = _make_artifact(
            id="art_already_archived",
            created_at=datetime(2026, 5, 12, 9, 0, 0, tzinfo=UTC),
        )
        art.meta.archived = True
        await store.save(art)

        count = await store.archive_stale(hours=24)
        assert count == 0

    @pytest.mark.asyncio
    async def test_viewed_artifact_not_archived(self, store: ArtifactStore) -> None:
        """An artifact created 25h ago but viewed recently should NOT be archived."""
        from datetime import timedelta

        now = datetime.now(UTC)
        art = _make_artifact(
            id="art_recently_viewed",
            created_at=now - timedelta(hours=25),
        )
        # Set last_viewed_at to just now (within 1h)
        art.meta.last_viewed_at = now - timedelta(minutes=5)
        await store.save(art)

        count = await store.archive_stale(hours=24)
        assert count == 0


class TestConcurrentSave:
    @pytest.mark.asyncio
    async def test_concurrent_saves_do_not_corrupt_index(self, store: ArtifactStore) -> None:
        """10 concurrent saves to the same ticker should all appear in the index."""
        artifacts = [_make_artifact(id=f"art_concurrent_{i}", ticker="AAPL") for i in range(10)]

        await asyncio.gather(*[store.save(a) for a in artifacts])

        results = await store.list_by_ticker(ticker="AAPL")
        assert len(results) == 10
        saved_ids = {r.id for r in results}
        expected_ids = {a.id for a in artifacts}
        assert saved_ids == expected_ids
