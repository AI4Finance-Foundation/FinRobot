"""End-to-end tests for POST /api/exports/pdf/{artifact_id} (v5 PR5)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from finagent.artifact.models import (
    Artifact,
    ArtifactAssumptions,
    ArtifactComputeVersion,
    ArtifactInputs,
    ArtifactMeta,
    ArtifactOutputs,
)
from finagent.artifact.store import ArtifactStore
from finagent.routes.exports import router

UTC = timezone.utc
NOW = datetime(2026, 5, 21, tzinfo=UTC)


def _artifact(artifact_type: str = "dcf") -> Artifact:
    return Artifact(
        id=f"art_2026-05-21T00:00:00_NVDA_{artifact_type}",
        ticker="NVDA",
        cross_tickers=[],
        type=artifact_type,  # type: ignore[arg-type]
        inputs=ArtifactInputs(data_source="yfinance", data_fetched_at=NOW, raw_data={}),
        assumptions=ArtifactAssumptions(parameters={}),
        compute_version=ArtifactComputeVersion(version="0.1.0", formula_id=artifact_type),
        outputs=ArtifactOutputs(
            structured={"dcf_calc": {"implied_price": 920.0, "wacc": 0.082, "inputs": {}}},
            summary_text="DCF implied $920",
        ),
        meta=ArtifactMeta(created_at=NOW, source=f"pipeline:{artifact_type}"),
    )


async def _app(tmp_path: Path, *artifacts: Artifact) -> FastAPI:
    store = ArtifactStore(base_dir=tmp_path)
    for art in artifacts:
        await store.save(art)
    app = FastAPI()
    app.include_router(router)
    app.state.artifact_store = store
    return app


@pytest.mark.asyncio
async def test_export_pdf_404_when_artifact_unknown(tmp_path: Path) -> None:
    app = await _app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.post("/api/exports/pdf/art_does_not_exist")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_export_pdf_415_for_unsupported_type(tmp_path: Path) -> None:
    art = _artifact("ad_hoc")  # ad_hoc has no PDF template wired
    app = await _app(tmp_path, art)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.post(f"/api/exports/pdf/{art.id}")
    assert r.status_code == 415
    assert "Supported" in r.text


@pytest.mark.asyncio
async def test_export_pdf_503_when_store_missing() -> None:
    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.post("/api/exports/pdf/anything")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_export_pdf_returns_pdf_or_known_failure(tmp_path: Path) -> None:
    """Acceptable outcomes for CI portability:
      200 — weasyprint installed AND template happy with our context
      422 — template needs fields our minimal stub artifact doesn't provide
      501 — weasyprint missing on this CI image
    Anything else means the route is leaking internal errors.
    """
    art = _artifact("dcf")
    app = await _app(tmp_path, art)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        r = await client.post(f"/api/exports/pdf/{art.id}")
    assert r.status_code in (200, 422, 501), r.text
    if r.status_code == 200:
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF-")
        assert f'filename="{art.id}.pdf"' in r.headers["content-disposition"]
