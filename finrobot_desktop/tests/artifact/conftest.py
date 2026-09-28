"""Shared fixtures for artifact tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from finrobot.artifact.models import (
    Artifact,
    ArtifactAssumptions,
    ArtifactComputeVersion,
    ArtifactInputs,
    ArtifactMeta,
    ArtifactOutputs,
)


UTC = timezone.utc
_TS = datetime(2026, 5, 13, 10, 0, 0, tzinfo=UTC)


def _make_artifact(
    id: str = "art_2026-05-13T10:00:00_AAPL_dcf",
    ticker: str | None = "AAPL",
    type: str = "dcf",
    wacc: float = 0.082,
    implied_price: float = 185.0,
    created_at: datetime | None = None,
) -> Artifact:
    return Artifact(
        id=id,
        ticker=ticker,
        type=type,
        inputs=ArtifactInputs(
            data_source="yfinance",
            data_fetched_at=_TS,
            raw_data={"revenue": 394_328_000_000, "ebitda": 130_541_000_000},
        ),
        assumptions=ArtifactAssumptions(
            parameters={
                "wacc": wacc,
                "terminal_growth_rate": 0.025,
                "revenue_growth_rates": [0.06, 0.05, 0.04, 0.03, 0.02],
                "ebitda_margin": 0.30,
                "tax_rate": 0.21,
            }
        ),
        compute_version=ArtifactComputeVersion(
            version="0.1.0",
            git_commit="abc1234",
            formula_id="dcf_simplified_v1",
        ),
        outputs=ArtifactOutputs(
            structured={
                "implied_price": implied_price,
                "wacc": wacc,
                "enterprise_value": 2_800_000_000_000,
            },
            summary_text=f"DCF implied ${implied_price:.2f} / WACC {wacc:.1%}",
            warnings=["Simplified FCF formula used"],
        ),
        meta=ArtifactMeta(
            created_at=created_at or _TS,
            source="pipeline:dcf",
            user_id="local",
        ),
    )


@pytest.fixture
def sample_artifact() -> Artifact:
    """A single DCF artifact for AAPL."""
    return _make_artifact()


@pytest.fixture
def sample_artifact_v2() -> Artifact:
    """A second DCF artifact with different assumptions (for diff tests)."""
    return _make_artifact(
        id="art_2026-05-13T11:00:00_AAPL_dcf",
        wacc=0.095,
        implied_price=162.0,
        created_at=datetime(2026, 5, 13, 11, 0, 0, tzinfo=UTC),
    )


@pytest.fixture
def tmp_store_dir(tmp_path: Path) -> Path:
    """Isolated temp directory for each test's artifact store."""
    return tmp_path / "artifacts"
