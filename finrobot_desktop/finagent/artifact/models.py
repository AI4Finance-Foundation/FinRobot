"""4-element computational artifact snapshot.

Stores everything needed to reproduce a financial analysis: input data
snapshot, assumption set, compute version, outputs, and meta. This is the
audit-trail layer Bloomberg/FactSet level tools have built in; for FinAgent
it's the core differentiation vs "ask ChatGPT to do DCF".
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ArtifactType = Literal[
    "dcf",
    "lbo",
    "comps",
    "ddm",
    "earnings",
    "ic_memo",
    "equity_research",
    "peer_research",
    "ad_hoc",
]


class ArtifactInputs(BaseModel):
    """Data snapshot at time of computation. Frozen so it can be replayed."""

    data_source: str = Field(description="yfinance|FMP|Finnhub|SEC|...")
    data_fetched_at: datetime
    raw_data: dict[str, Any] = Field(
        description=(
            "Provider's raw return values, captured verbatim. "
            "Enables byte-equal replay even if external API drifts."
        )
    )


class ArtifactAssumptions(BaseModel):
    """All parameters fed into the deterministic compute layer."""

    parameters: dict[str, Any] = Field(
        description="wacc / terminal_growth / tax_rate / revenue_growth_rates etc."
    )
    user_overrides: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Subset of parameters the user explicitly overrode (vs LLM-selected via param_agent)."
        ),
    )


class ArtifactComputeVersion(BaseModel):
    """Snapshot of the compute code that produced the result."""

    package: str = "finagent"
    version: str  # e.g. "0.5.2"
    git_commit: str | None = None  # short SHA if available
    formula_id: str  # e.g. "dcf_simplified_v1"
    formula_warnings: list[str] = Field(default_factory=list)


class ArtifactOutputs(BaseModel):
    """Computed results returned to the user."""

    structured: dict[str, Any] = Field(
        description="The model dump of e.g. DCFResult / LBOResult / PeerComps."
    )
    summary_text: str = ""
    warnings: list[str] = Field(default_factory=list)


class ArtifactMeta(BaseModel):
    """Provenance: when, by whom, via what flow."""

    created_at: datetime
    source: str = Field(
        description=(
            "'conversation:<session_id>' | 'stocks_page_button' | "
            "'workspace_batch:<batch_id>' | 'cli'"
        )
    )
    user_id: str = "local"  # multi-user later
    tags: list[str] = Field(default_factory=list)
    parent_artifact_id: str | None = Field(
        default=None,
        description="If this artifact is a re-run / iteration of an earlier one.",
    )
    last_viewed_at: datetime | None = Field(
        default=None,
        description="Updated by mark_viewed(). Used for auto-archive logic.",
    )
    archived: bool = Field(
        default=False,
        description="True when artifact has been unviewed for > archive_hours.",
    )


class Artifact(BaseModel):
    """A single financial analysis snapshot."""

    id: str  # e.g. "art_2026-05-13T14:32:18_AAPL_dcf"
    ticker: str | None  # None for cross-ticker analyses
    cross_tickers: list[str] = Field(
        default_factory=list,
        description="Populated when ticker is None (e.g. peer comparison).",
    )
    type: ArtifactType

    inputs: ArtifactInputs
    assumptions: ArtifactAssumptions
    compute_version: ArtifactComputeVersion
    outputs: ArtifactOutputs
    meta: ArtifactMeta


class ArtifactSummary(BaseModel):
    """Sidebar / Library view — strips heavy fields."""

    id: str
    ticker: str | None
    cross_tickers: list[str]
    type: ArtifactType
    created_at: datetime
    headline: str  # short text — e.g. "DCF implied $185 / WACC 8.2%"
    source: str  # from meta
    archived: bool = False  # 24h no view → archived
