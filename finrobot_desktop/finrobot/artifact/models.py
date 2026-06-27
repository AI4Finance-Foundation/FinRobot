"""4-element computational artifact snapshot.

Stores everything needed to reproduce a financial analysis: input data
snapshot, assumption set, compute version, outputs, and meta. This is the
audit-trail layer Bloomberg/FactSet level tools have built in; for FinRobot
it's the core differentiation vs "ask ChatGPT to do DCF".
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from finrobot.engine.compute.operators.signal import Signal

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

    package: str = "finrobot"
    version: str  # e.g. "0.5.2"
    git_commit: str | None = None  # short SHA if available
    formula_id: str  # e.g. "dcf_simplified_v1"
    formula_warnings: list[str] = Field(default_factory=list)


class ArtifactOutputs(BaseModel):
    """Computed results returned to the user."""

    structured: dict[str, Any] = Field(
        description="The model dump of e.g. DCFResult / LBOResult / PeerComps."
    )
    llm_narrative: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "LLM-authored narrative fields extracted from the thesis for direct consumption. "
            "Keys: tagline / key_takeaways / company_overview / valuation_overview / "
            "news_summary / competitor_analysis / recommendation / catalysts / risks. "
            "This is a mirror of structured.thesis.* fields for semantic clarity; "
            "structured.thesis remains the source of truth for the compute audit trail."
        ),
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
    language: Literal["en", "zh"] = Field(
        default="zh",
        description=(
            "Language the LLM wrote this artifact's prose in (thesis / "
            "key_takeaways / price_target_basis / financial commentary / news "
            "summary). Set at generation time = UI locale when the run was "
            "triggered. The frontend renders the body in THIS language regardless "
            "of the viewer's current UI locale; only chrome labels follow the live "
            "locale. Default is 'zh' — every artifact written before this field "
            "existed was generated in Chinese, so legacy artifacts deserialize "
            "correctly. (NB: differs from settings.language default 'en', which "
            "governs NEW generation when unspecified — a separate concern.)"
        ),
    )
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
    """Sidebar / Library view — strips heavy fields.

    v5 (ADR-0001) adds four optional fields powering the "我的研究" section's
    signal lamp + hit-rate banner. All default to None so legacy JSON
    artifacts (written before v5) deserialize cleanly; the UI must treat None
    as "no signal" and skip from hit-rate stats.
    """

    id: str
    ticker: str | None
    cross_tickers: list[str]
    type: ArtifactType
    created_at: datetime
    headline: str  # short text — e.g. "DCF implied $185 / WACC 8.2%"
    source: str  # from meta
    archived: bool = False  # 24h no view → archived

    entry_price: float | None = Field(
        default=None,
        description=(
            "Quote snapshot taken when the pipeline was triggered (USD/share). "
            "None for legacy artifacts or cross-ticker analyses without a "
            "single entry price."
        ),
    )
    target_price: float | None = Field(
        default=None,
        description=(
            "AI-given target price from the thesis step (USD/share). "
            "None when the artifact type has no thesis (peer_research / "
            "ad_hoc) or for legacy data."
        ),
    )
    target_date: datetime | None = Field(
        default=None,
        description=(
            "Deadline for the thesis (defaults to created_at + 365 days, set "
            "in the thesis step). None when target_price itself is None."
        ),
    )
    signal: Signal | None = Field(
        default=None,
        description=(
            "Lazy-computed realised-vs-target signal (hit / watching / failed) — "
            "never persisted. Route handlers call finrobot.engine.compute.operators.signal."
            "compute_signal at list time using a fresh quote. None when any of "
            "entry_price / target_price / current_price are unavailable. "
            "DO NOT confuse with `verdict` — signal is the post-trade outcome, "
            "verdict is the LLM's pre-trade BUY/HOLD/SELL call."
        ),
    )
    verdict: str | None = Field(
        default=None,
        description=(
            "LLM-emitted BUY / HOLD / SELL recommendation from the thesis step. "
            "Populated by summary_extractor.extract_verdict at summary build "
            "time. None when the artifact has no thesis (peer_research / ad_hoc) "
            "or when the recommendation field is missing / malformed."
        ),
    )
    tagline: str | None = Field(
        default=None,
        description=(
            "≤ 60 char shareable conclusion written by the synthesis_agent "
            "(narrative slot). Populated by summary_extractor."
            "extract_tagline; lets the workspace AI zone hot-state card show "
            "the real LLM call instead of the truncated pipeline.format_summary "
            "preview that gets stored in `headline`. None for legacy artifacts "
            "produced before the narrative bump."
        ),
    )
    primary_provider: str | None = Field(
        default=None,
        description=(
            "Data provider that fed this artifact (inputs.data_source), mirrored "
            "into a summary column at save time (门四溯源半) so the Library list "
            "shows the source without payload reads. None for the builders' "
            "'unknown' placeholder and for rows written before the column "
            "existed (backfilled by the projection rebuild)."
        ),
    )
    fairly_valued: bool = Field(
        default=False,
        description=(
            "True when the point target was withheld BECAUSE the live price sits "
            "inside the cross-method fair-value band (a confident HOLD = 'fairly "
            "valued'), as opposed to a genuine withhold (M&A / single divergent "
            "method). Populated by summary_extractor.extract_fairly_valued at "
            "save time so the version-timeline row can render 'Fairly Valued' "
            "instead of a generic 'WITHHELD'. Defaults to False so legacy / "
            "un-backfilled rows (NULL column) deserialise cleanly as 'not fairly "
            "valued' — backfilled from the payload by the projection rebuild."
        ),
    )
