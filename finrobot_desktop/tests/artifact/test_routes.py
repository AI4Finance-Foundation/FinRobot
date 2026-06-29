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

from finrobot.artifact.models import Artifact
from finrobot.artifact.store import ArtifactStore
from finrobot.routes.artifacts import router as artifacts_router
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

    def test_rejects_negative_limit(self, client: TestClient) -> None:
        resp = client.get("/api/artifacts?limit=-1")
        assert resp.status_code == 422


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

    def test_delete_drops_run_artifact_links(
        self, client: TestClient, store: ArtifactStore, sample_artifact: Artifact
    ) -> None:
        """Deleting the canonical artifact also removes the runs.db link rows —
        otherwise GET /api/runs/{id} keeps listing a ghost whose open-report
        path 404s forever."""
        from unittest.mock import AsyncMock

        _save_sync(store, sample_artifact)
        run_store = AsyncMock()
        client.app.state.run_store = run_store  # type: ignore[attr-defined]
        resp = client.delete(f"/api/artifacts/{sample_artifact.id}")
        assert resp.status_code == 200
        run_store.remove_artifact_links.assert_awaited_once_with(sample_artifact.id)


class TestDiff:
    def test_diff_identical_artifacts_flagged_identical(
        self, client: TestClient, store: ArtifactStore, sample_artifact: Artifact
    ) -> None:
        # Save the same artifact twice (different ids), same assumptions/outputs.
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
        delta = resp.json()
        assert delta["identical"] is True
        # No driver should report a direction other than flat.
        assert all(d["direction"] == "flat" for d in delta["drivers"])

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
        delta = resp.json()
        assert delta["identical"] is False

        drivers = {d["key"]: d for d in delta["drivers"]}
        wacc = drivers.get("wacc")
        assert wacc is not None
        assert wacc["old_value"] == pytest.approx(0.082)
        assert wacc["new_value"] == pytest.approx(0.095)
        assert wacc["direction"] == "up"
        # WACC is lower_better → a rise is a negative development.
        assert wacc["sentiment"] == "negative"
        # Backend gives the display string; "%" unit, not a guessed $.
        assert wacc["formatted_old"] == "8.2%"
        assert wacc["formatted_new"] == "9.5%"

        # Target price (DCF implied for a dcf artifact) fell 185 → 162.
        conclusion = {c["key"]: c for c in delta["conclusion"]}
        tp = conclusion.get("target_price")
        assert tp is not None
        assert tp["old_value"] == pytest.approx(185.0)
        assert tp["new_value"] == pytest.approx(162.0)
        assert tp["direction"] == "down"

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

    def test_timeline_rejects_negative_limit(self, client: TestClient) -> None:
        resp = client.get("/api/artifacts/by-ticker/TSLA/timeline?limit=-1")
        assert resp.status_code == 422


class TestTimelineIncludeSignals:
    """The signal lamp (hit/watching/failed) needs a LIVE quote per ticker, so
    attach_signals issues a synchronous fetch_canonical(PRICE) before the
    timeline returns — market-data latency on what is otherwise a local-DB read.
    Surfaces that don't render the lamp pass ?include_signals=false to skip it
    and paint the report history instantly. These tests pin the gating: the spy
    stands in for attach_signals so the contract holds regardless of whether any
    stored artifact would actually qualify for a quote fetch."""

    def _spy_attach(self, app: FastAPI, calls: list[int], monkeypatch: pytest.MonkeyPatch) -> None:
        from types import SimpleNamespace

        async def _spy(summaries: object, data_layer: object, **_: object) -> object:
            calls.append(1)
            return summaries

        # Non-None data_layer so the route reaches the attach_signals branch.
        app.state.deps = SimpleNamespace(data_layer=object())
        monkeypatch.setattr("finrobot.routes.artifacts.attach_signals", _spy)

    def test_signals_attached_by_default(
        self,
        app: FastAPI,
        client: TestClient,
        store: ArtifactStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _save_sync(store, _make_artifact(id="art_sig_default", ticker="TSLA"))
        calls: list[int] = []
        self._spy_attach(app, calls, monkeypatch)

        resp = client.get("/api/artifacts/by-ticker/TSLA/timeline")
        assert resp.status_code == 200
        assert calls == [1]  # live-quote signal compute ran

    def test_include_signals_false_skips_live_quote(
        self,
        app: FastAPI,
        client: TestClient,
        store: ArtifactStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _save_sync(store, _make_artifact(id="art_sig_off", ticker="TSLA"))
        calls: list[int] = []
        self._spy_attach(app, calls, monkeypatch)

        resp = client.get("/api/artifacts/by-ticker/TSLA/timeline?include_signals=false")
        assert resp.status_code == 200
        assert calls == []  # no fetch_canonical(PRICE) — instant local read
        # History still returned in full; only the lamp is deferred.
        assert {item["id"] for item in resp.json()} == {"art_sig_off"}


class TestSchemaDriftGhostRows:
    """P2 audit 2026-06-10: a row whose payload no longer deserialises used to
    be visible in every list (summary columns still render) yet 404 on detail —
    an unopenable ghost with no cleanup path. Contract now: first detection
    self-archives the row (drops out of default lists) and detail answers 410
    with an explanation; a never-stored id stays a plain 404."""

    def _corrupt(self, store: ArtifactStore, artifact_id: str) -> None:
        import sqlite3

        with sqlite3.connect(store._impl._db_path) as conn:
            conn.execute(
                'UPDATE artifacts SET payload = \'{"not": "an artifact"}\' WHERE id = ?',
                (artifact_id,),
            )
            conn.commit()

    def test_unreadable_detail_410_and_list_self_heals(
        self, client: TestClient, store: ArtifactStore
    ) -> None:
        _save_sync(store, _make_artifact(id="art_ghost", ticker="AAPL"))
        self._corrupt(store, "art_ghost")

        # Ghost is visible before anyone clicks (columns render fine).
        assert any(i["id"] == "art_ghost" for i in client.get("/api/artifacts").json())

        # The click that used to 404 now explains itself with 410...
        resp = client.get("/api/artifacts/art_ghost")
        assert resp.status_code == 410
        assert "旧版本" in resp.json()["detail"]

        # ...and the detection archived the row: default list stops showing it.
        assert not any(i["id"] == "art_ghost" for i in client.get("/api/artifacts").json())
        # Still recoverable/visible for an explicit archived view + deletable.
        archived = client.get("/api/artifacts", params={"archived": "true"}).json()
        assert any(i["id"] == "art_ghost" for i in archived)
        assert client.delete("/api/artifacts/art_ghost").status_code == 200

    def test_missing_id_still_plain_404(self, client: TestClient) -> None:
        assert client.get("/api/artifacts/art_never_existed").status_code == 404

    def test_view_on_ghost_410_and_does_not_resurrect(
        self, client: TestClient, store: ArtifactStore
    ) -> None:
        """POST /view un-archives — it must bail at 410 BEFORE that side effect,
        or every desktop open attempt would resurrect the ghost into lists."""
        _save_sync(store, _make_artifact(id="art_ghost2", ticker="AAPL"))
        self._corrupt(store, "art_ghost2")
        client.get("/api/artifacts/art_ghost2")  # trigger self-archive

        assert client.post("/api/artifacts/art_ghost2/view").status_code == 410
        assert not any(i["id"] == "art_ghost2" for i in client.get("/api/artifacts").json())

    def test_diff_with_ghost_410(self, client: TestClient, store: ArtifactStore) -> None:
        _save_sync(store, _make_artifact(id="art_ok", ticker="AAPL"))
        _save_sync(store, _make_artifact(id="art_ghost3", ticker="AAPL"))
        self._corrupt(store, "art_ghost3")

        assert client.get("/api/artifacts/art_ok/diff/art_ghost3").status_code == 410
        assert client.get("/api/artifacts/art_ok/diff/art_nope").status_code == 404
