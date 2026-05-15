"""Tests for /api/artifacts FastAPI routes.

Coverage:
- GET  /api/artifacts        — list, filter, empty
- GET  /api/artifacts/{id}   — 200 with correct fields; 404 on missing
- DELETE /api/artifacts/{id} — 200 + 404
- GET  /api/artifacts/{a}/diff/{b} — correct FieldDiff output + 404
- POST /api/artifacts/{id}/view — 200; 404 on missing
- GET  /api/artifacts/by-ticker/{ticker}/timeline — correct ordering
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from finagent.artifact.models import Artifact
from finagent.artifact.store import ArtifactStore
from finagent.routes.artifacts import router as artifacts_router
from tests.artifact.conftest import _make_artifact


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    """Minimal FastAPI app with artifacts router and a temp ArtifactStore."""
    app = FastAPI()
    app.include_router(artifacts_router)

    store = ArtifactStore(base_dir=tmp_path / "artifacts")
    app.state.artifact_store = store
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def store(app: FastAPI) -> ArtifactStore:
    return app.state.artifact_store  # type: ignore[return-value]


def _save_sync(store: ArtifactStore, artifact: Artifact) -> None:
    import asyncio

    asyncio.get_event_loop().run_until_complete(store.save(artifact))


class TestListArtifacts:
    def test_empty_store_returns_empty_list(self, client: TestClient) -> None:
        resp = client.get("/api/artifacts")
        assert resp.status_code == 200
        data = resp.json()
        assert data == []

    def test_returns_summaries_not_full_artifacts(
        self, client: TestClient, store: ArtifactStore, sample_artifact: Artifact
    ) -> None:
        _save_sync(store, sample_artifact)
        resp = client.get("/api/artifacts")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        item = items[0]
        # ArtifactSummary fields (not full artifact)
        assert "id" in item
        assert "headline" in item
        assert "source" in item
        assert "type" in item
        # Full artifact fields must NOT be present at top level
        assert "inputs" not in item
        assert "assumptions" not in item

    def test_filter_by_ticker(self, client: TestClient, store: ArtifactStore) -> None:
        aapl = _make_artifact(id="art_AAPL_1", ticker="AAPL")
        msft = _make_artifact(id="art_MSFT_1", ticker="MSFT")
        _save_sync(store, aapl)
        _save_sync(store, msft)

        resp = client.get("/api/artifacts?ticker=AAPL")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["id"] == "art_AAPL_1"

    def test_filter_by_type(self, client: TestClient, store: ArtifactStore) -> None:
        dcf = _make_artifact(id="art_dcf", ticker="AAPL", type="dcf")
        lbo = _make_artifact(id="art_lbo", ticker="AAPL", type="lbo")
        _save_sync(store, dcf)
        _save_sync(store, lbo)

        resp = client.get("/api/artifacts?type=lbo")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["type"] == "lbo"

    def test_archived_excluded_by_default(self, client: TestClient, store: ArtifactStore) -> None:
        art = _make_artifact(id="art_archived")
        art.meta.archived = True
        _save_sync(store, art)

        resp = client.get("/api/artifacts")
        assert resp.json() == []

    def test_archived_included_with_flag(self, client: TestClient, store: ArtifactStore) -> None:
        art = _make_artifact(id="art_archived")
        art.meta.archived = True
        _save_sync(store, art)

        resp = client.get("/api/artifacts?archived=true")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestGetArtifact:
    def test_returns_full_artifact(
        self, client: TestClient, store: ArtifactStore, sample_artifact: Artifact
    ) -> None:
        _save_sync(store, sample_artifact)
        resp = client.get(f"/api/artifacts/{sample_artifact.id}")
        assert resp.status_code == 200
        data = resp.json()
        # Full artifact fields must be present
        assert data["id"] == sample_artifact.id
        assert data["ticker"] == "AAPL"
        assert data["type"] == "dcf"
        assert "inputs" in data
        assert "assumptions" in data
        assert "compute_version" in data
        assert "outputs" in data
        assert "meta" in data
        # Spot-check specific values
        assert data["assumptions"]["parameters"]["wacc"] == pytest.approx(0.082)
        assert data["outputs"]["structured"]["implied_price"] == pytest.approx(185.0)

    def test_404_for_missing_artifact(self, client: TestClient) -> None:
        resp = client.get("/api/artifacts/nonexistent_id")
        assert resp.status_code == 404
        assert "nonexistent_id" in resp.json()["detail"]


class TestDeleteArtifact:
    def test_delete_returns_200_with_status(
        self, client: TestClient, store: ArtifactStore, sample_artifact: Artifact
    ) -> None:
        _save_sync(store, sample_artifact)
        resp = client.delete(f"/api/artifacts/{sample_artifact.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "deleted"
        assert data["id"] == sample_artifact.id

    def test_delete_removes_from_list(
        self, client: TestClient, store: ArtifactStore, sample_artifact: Artifact
    ) -> None:
        _save_sync(store, sample_artifact)
        client.delete(f"/api/artifacts/{sample_artifact.id}")
        resp = client.get("/api/artifacts")
        assert resp.json() == []

    def test_delete_404_for_missing(self, client: TestClient) -> None:
        resp = client.delete("/api/artifacts/nonexistent_id")
        assert resp.status_code == 404


class TestDiff:
    def test_diff_identical_artifacts_returns_empty(
        self, client: TestClient, store: ArtifactStore, sample_artifact: Artifact
    ) -> None:
        # Save the same artifact twice (different ids)
        a = sample_artifact
        b = _make_artifact(
            id="art_2026-05-13T11:00:00_AAPL_dcf_b",
            wacc=0.082,
            implied_price=185.0,
        )
        _save_sync(store, a)
        _save_sync(store, b)

        resp = client.get(f"/api/artifacts/{a.id}/diff/{b.id}")
        assert resp.status_code == 200
        diffs = resp.json()
        # summary_text will differ (contains id), but numeric fields are same
        numeric_diffs = [
            d
            for d in diffs
            if d["path"]
            in (
                "assumptions.parameters.wacc",
                "outputs.structured.implied_price",
            )
        ]
        assert numeric_diffs == []

    def test_diff_changed_wacc(
        self,
        client: TestClient,
        store: ArtifactStore,
        sample_artifact: Artifact,
        sample_artifact_v2: Artifact,
    ) -> None:
        _save_sync(store, sample_artifact)
        _save_sync(store, sample_artifact_v2)

        resp = client.get(f"/api/artifacts/{sample_artifact.id}/diff/{sample_artifact_v2.id}")
        assert resp.status_code == 200
        diffs = resp.json()
        by_path = {d["path"]: d for d in diffs}

        wacc_diff = by_path.get("assumptions.parameters.wacc")
        assert wacc_diff is not None
        assert wacc_diff["kind"] == "changed"
        assert wacc_diff["old"] == pytest.approx(0.082)
        assert wacc_diff["new"] == pytest.approx(0.095)
        assert wacc_diff["abs_change"] is not None
        assert wacc_diff["pct_change"] is not None

    def test_diff_404_first_artifact_missing(
        self, client: TestClient, store: ArtifactStore, sample_artifact: Artifact
    ) -> None:
        _save_sync(store, sample_artifact)
        resp = client.get(f"/api/artifacts/nonexistent/diff/{sample_artifact.id}")
        assert resp.status_code == 404

    def test_diff_404_second_artifact_missing(
        self, client: TestClient, store: ArtifactStore, sample_artifact: Artifact
    ) -> None:
        _save_sync(store, sample_artifact)
        resp = client.get(f"/api/artifacts/{sample_artifact.id}/diff/nonexistent")
        assert resp.status_code == 404


class TestMarkViewed:
    def test_mark_viewed_returns_ok(
        self, client: TestClient, store: ArtifactStore, sample_artifact: Artifact
    ) -> None:
        _save_sync(store, sample_artifact)
        resp = client.post(f"/api/artifacts/{sample_artifact.id}/view")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["id"] == sample_artifact.id

    def test_mark_viewed_updates_last_viewed_at(
        self, client: TestClient, store: ArtifactStore, sample_artifact: Artifact
    ) -> None:
        _save_sync(store, sample_artifact)
        client.post(f"/api/artifacts/{sample_artifact.id}/view")

        # Fetch again and check last_viewed_at is set
        resp = client.get(f"/api/artifacts/{sample_artifact.id}")
        data = resp.json()
        assert data["meta"]["last_viewed_at"] is not None

    def test_mark_viewed_404_for_missing(self, client: TestClient) -> None:
        resp = client.post("/api/artifacts/nonexistent/view")
        assert resp.status_code == 404


class TestTimeline:
    def test_timeline_returns_all_types_for_ticker(
        self, client: TestClient, store: ArtifactStore
    ) -> None:
        dcf = _make_artifact(id="art_timeline_dcf", ticker="TSLA", type="dcf")
        lbo = _make_artifact(id="art_timeline_lbo", ticker="TSLA", type="lbo")
        _save_sync(store, dcf)
        _save_sync(store, lbo)

        resp = client.get("/api/artifacts/by-ticker/TSLA/timeline")
        assert resp.status_code == 200
        ids = {item["id"] for item in resp.json()}
        assert "art_timeline_dcf" in ids
        assert "art_timeline_lbo" in ids

    def test_timeline_includes_archived(self, client: TestClient, store: ArtifactStore) -> None:
        art = _make_artifact(id="art_timeline_archived", ticker="TSLA")
        art.meta.archived = True
        _save_sync(store, art)

        resp = client.get("/api/artifacts/by-ticker/TSLA/timeline")
        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()]
        assert "art_timeline_archived" in ids

    def test_timeline_sorted_newest_first(self, client: TestClient, store: ArtifactStore) -> None:
        from datetime import datetime, timezone

        early = _make_artifact(
            id="art_early_TSLA",
            ticker="TSLA",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        late = _make_artifact(
            id="art_late_TSLA",
            ticker="TSLA",
            created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        _save_sync(store, early)
        _save_sync(store, late)

        resp = client.get("/api/artifacts/by-ticker/TSLA/timeline")
        items = resp.json()
        assert items[0]["id"] == "art_late_TSLA"
        assert items[1]["id"] == "art_early_TSLA"
