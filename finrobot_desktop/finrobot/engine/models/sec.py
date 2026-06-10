"""SEC EDGAR primary data layer — Pydantic types.

Source-of-truth schema for everything produced by
``finrobot.engine.data.providers.edgar_provider`` and consumed by:
  - pipeline steps (data_collection / catalyst_analysis / peer_analysis /
    ownership_governance_analysis)
  - artifact ``outputs.structured.sec_filings`` / ``ownership_governance`` /
    ``xbrl_facts_snapshot`` keys (see ``finrobot/artifact/builders.py``)
  - UI chapters 04 Financial / 06 News / 08 Catalysts / 10 Competitive /
    11 Data / 12 Ownership & Governance

Every SEC-sourced number lives in one of these models and **must** carry a
``FilingProvenance`` — that's the CLAUDE.md core contract ("LLM 永远不产出
无法追溯到函数调用的数字") applied to the SEC data plane.

The schema was sealed against EdgarTools 5.31.5 by ``scripts/probe_edgartools_api.py``
on 2026-05-27; see ``specs/research/edgartools_probe_findings_2026-05-27.md``
for field-by-field derivation.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Provenance — required on every SEC number written to an artifact
# ---------------------------------------------------------------------------


class FilingProvenance(BaseModel):
    """Where a SEC datum came from. Required on every SEC-sourced number.

    Renders into the UI's hover tooltip as
    ``"AAPL 2024 10-K · accession 0000320193-24-000123 · period 2024-09-28"``.
    """

    form: str  # "10-K" / "10-Q" / "8-K" / "4" / "13F-HR" / "DEF 14A"
    filing_date: date
    accession_no: str
    period_of_report: date | None = None
    source_url: str | None = None  # SEC EDGAR 直链


# ---------------------------------------------------------------------------
# XBRL — standardized financial facts (replaces yfinance/FMP for peer comps)
# ---------------------------------------------------------------------------


class XBRLFact(BaseModel):
    """Single XBRL standardized number tagged to a us-gaap concept.

    Probe 2026-05-27: AAPL/MSFT/GOOGL all report Revenue under the same
    concept ``us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax``
    (post-ASC-606 standard) — cross-company alignment works.
    """

    concept: str  # e.g. "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    value: float
    units: str = "USD"  # "USD" / "shares" / "USD/share"
    period_end: date
    period_start: date | None = None
    fiscal_year: int | None = None
    fiscal_period: str | None = None  # "FY" / "Q1" / "Q2" / "Q3"
    provenance: FilingProvenance


class XBRLTTMMetric(BaseModel):
    """Trailing-12-months metric — wraps edgartools ``TTMMetric``.

    ``component_provenance`` carries one FilingProvenance per constituent
    quarter so the UI can show "TTM = Q3 2025 + Q4 2025 + Q1 2026 + Q2 2026"
    with links to each underlying 10-Q/10-K.
    """

    concept: str
    value: float
    periods: list[str] = Field(
        default_factory=list
    )  # e.g. ["Q3 2025", "Q4 2025", "Q1 2026", "Q2 2026"]
    component_provenance: list[FilingProvenance] = Field(default_factory=list)


class SECCompanyFacts(BaseModel):
    """Snapshot of one company's typed XBRL metrics.

    Adapter pulls these via ``EntityFacts.get_revenue()`` etc. (typed getter)
    — NOT ``.to_pandas(tag)`` (which doesn't exist in 5.31, despite docs).
    """

    cik: str
    company_name: str | None = None
    ttm_revenue: XBRLTTMMetric | None = None
    ttm_net_income: XBRLTTMMetric | None = None
    latest_revenue: XBRLFact | None = None
    latest_net_income: XBRLFact | None = None
    latest_gross_profit: XBRLFact | None = None
    latest_operating_income: XBRLFact | None = None
    latest_total_assets: XBRLFact | None = None
    latest_total_liabilities: XBRLFact | None = None
    latest_shareholders_equity: XBRLFact | None = None
    # Fallback bag for arbitrary us-gaap concepts (used by xbrl_aligned_comps
    # when a non-core tag is needed for a peer table)
    facts_by_concept: dict[str, list[XBRLFact]] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 10-K / 10-Q — typed filings with section attribute access
# ---------------------------------------------------------------------------


class SECFilingSection(BaseModel):
    """One typed section of a 10-K / 10-Q.

    Probe 2026-05-27: edgartools 5.31 exposes typed attributes directly
    (``tenk.business``, ``tenk.risk_factors``, ``tenk.management_discussion``);
    we map each to a canonical_id so chapters can lookup by stable key.
    """

    title: str  # display: "Item 7 — Management's Discussion and Analysis"
    canonical_id: str  # edgar attribute name: "management_discussion"
    text: str
    char_count: int
    # Probe 2026-05-27: JPM's MD&A was only 396 chars (vs 100+ pages reality).
    # When the adapter triggers fallback we mark the source so downstream
    # consumers know the text is pulled from filing.text() not a typed attr.
    extracted_via: str = "edgartools_attribute"
    # ^ "edgartools_attribute" | "filing_text_fallback"


class SECFiling(BaseModel):
    """A single 10-K or 10-Q filing.

    ``sections_extraction_quality`` lets downstream UI / RAG decide whether
    to trust per-section accessors or treat the entire ``filing.text()`` as
    one blob to chunk via BM25.
    """

    form: str  # "10-K" / "10-Q" / "10-K/A"
    filing_date: date
    period_of_report: date | None = None
    accession_no: str
    source_url: str | None = None
    sections: list[SECFilingSection] = Field(default_factory=list)
    full_text_char_count: int = 0
    is_amended: bool = False
    sections_extraction_quality: str = "ok"
    # ^ "ok" | "fallback_to_full_text" | "amended_redirected"


# ---------------------------------------------------------------------------
# 8-K — current report on material events (CurrentReport in edgartools)
# ---------------------------------------------------------------------------


class SECEvent8K(BaseModel):
    """One 8-K filing. obj class is ``CurrentReport`` in edgartools 5.31."""

    filing_date: date
    period_of_report: date | None = None
    accession_no: str
    items: list[str] = Field(default_factory=list)
    # Probe 2026-05-27: ``items`` is bare codes like ['Item 2.02', 'Item 9.01'].
    # FinRobot attaches human-readable descriptions client-side via a
    # static lookup table (8-K Item 2.02 = "Results of Operations", etc.)
    # to avoid a per-filing LLM call.
    items_with_description: list[str] = Field(default_factory=list)
    text: str = ""
    source_url: str | None = None


# ---------------------------------------------------------------------------
# Form 4 — insider transactions
# ---------------------------------------------------------------------------


class InsiderTransaction(BaseModel):
    """One row inside one Form 4 filing.

    Fields mirror edgartools 5.31 ``TransactionActivity``. One Form 4 can
    contain multiple TransactionActivity rows (e.g. an option exercise + a
    same-day sale is two rows); we flatten to one InsiderTransaction per row
    so the UI table can render every leg of every disposition.

    Probe 2026-05-27 (TSLA Form 4 fixture): real data includes Elon Musk
    forfeit of 96,000,000 shares (transaction_type='other_disposition',
    code='D', value=0 — Tornetta Decision Event) — the schema has to handle
    value=0 / price=0 cases gracefully.
    """

    filing_date: date
    accession_no: str
    insider_name: str
    insider_position: str | None = None  # e.g. "Chief Financial Officer" / "CEO"
    transaction_type: (
        str  # "sale" / "purchase" / "exercise" / "other_disposition" / "grant" / "award"
    )
    code: (
        str  # SEC code: "S" sale / "P" purchase / "M" exercise / "D" other_disposition / "A" award
    )
    # None ≠ 0: shares/value are None when the provider omitted them (parse gap),
    # NOT a fabricated 0 — a 0-share/$0 row would read as a real (and for shares,
    # nonsensical) transaction. An *explicit* value=0 (forfeit/gift) stays 0.
    shares: float | None = None
    value: float | None = None  # USD value of this leg; explicit 0 = forfeit, None = missing
    price_per_share: float | None = None
    security_type: str = ""  # "non-derivative" / "derivative"
    security_title: str = ""  # "Common Stock" / "Non-Qualified Stock Option (right to buy)"
    underlying_security: str = ""  # only populated for derivatives
    exercise_date: date | None = None
    expiration_date: date | None = None
    footnote_ids: str = ""  # e.g. "F1" or "F1,F2"
    footnotes_text: str = ""  # full footnote prose (e.g. "10b5-1 plan adopted ...")
    provenance: FilingProvenance


# ---------------------------------------------------------------------------
# 13F — institutional holdings (reverse lookup via local cache)
# ---------------------------------------------------------------------------


class InstitutionalHolding(BaseModel):
    """One institution's position in a single ticker, at a single quarter end.

    Probe 2026-05-27: edgartools ``ThirteenF.holdings`` is a pandas DataFrame
    with ~386 rows per filing (filer CIK 1513703 sample). Reverse lookup
    ("who holds NVDA?") has no edgartools API, so FinRobot builds a local
    sqlite index keyed by (ticker, holder_cik, period_end) — see
    ``finrobot.engine.data.sec_holdings_cache``.

    Column names below assume the standard 13F-HR XML schema; the local-cache
    refresh job is responsible for normalising whatever edgartools surfaces
    into these names.
    """

    holder_name: str  # filer's company name
    holder_cik: str | None = None  # filer's SEC CIK
    cusip: str  # security identifier (used as the cross-filing join key)
    name_of_issuer: str  # e.g. "NVIDIA CORP"
    title_of_class: str = "COM"  # "COM" / "COM CL A" / "COM CL B" / ...
    shares: int
    value_usd: float  # 13F reports in thousands of USD; cache normalises to dollars
    period_end: date
    # Percentage units (4.2 means 4.2%, not 0.042), mirroring the convention
    # in finrobot/engine/compute/coordinators/market.py. UI calls formatPercent with
    # `alreadyPercent=true` so the visual layer never has to guess.
    shares_change_pct: float | None = None  # computed by FinRobot vs prior quarter
    provenance: FilingProvenance


# ---------------------------------------------------------------------------
# DEF 14A — proxy / executive compensation
# ---------------------------------------------------------------------------


class ProxyCompensation(BaseModel):
    """Executive compensation summary extracted from a DEF 14A proxy statement.

    The deep extraction (parsing the SCT table to dollars + computing
    pay-vs-performance) lives in ``finrobot/engine/compute/proxy.py``.
    """

    filing_date: date
    accession_no: str
    ceo_name: str | None = None
    ceo_total_compensation: float | None = None  # USD
    ceo_yoy_change_pct: float | None = None  # percentage units (e.g. 18.4 → 18.4%)
    ceo_pay_ratio: int | None = None  # CEO total / median employee total
    provenance: FilingProvenance


class ScheduleThirteenAlert(BaseModel):
    """5%+ shareholder activity (Schedule 13D = activist, 13G = passive)."""

    filer_name: str
    filer_cik: str | None = None
    filing_date: date
    accession_no: str
    schedule_type: str  # "13D" (activist) | "13G" (passive)
    shares: int
    pct_of_class: float | None = None  # 0..100
    transaction_summary: str = ""  # short prose pulled from the filing


# ---------------------------------------------------------------------------
# Top-level container for Chapter 12 "Ownership & Governance"
# ---------------------------------------------------------------------------


class OwnershipGovernanceAnalysis(BaseModel):
    """Persisted under ``artifact.outputs.structured.ownership_governance``."""

    insider_transactions: list[InsiderTransaction] = Field(default_factory=list)
    institutional_holdings: list[InstitutionalHolding] = Field(default_factory=list)
    proxy_compensation: ProxyCompensation | None = None
    schedule13_alerts: list[ScheduleThirteenAlert] = Field(default_factory=list)
    generated_at: datetime
    # Marks degraded sub-sections so the UI can render a "data unavailable"
    # placeholder instead of a misleading empty table.
    degraded_sections: list[str] = Field(default_factory=list)
    # ^ e.g. ["institutional_holdings"] when sec_holdings_cache is empty

    # Per-section reason codes for fine-grained UI messaging.
    # Keys match entries in degraded_sections; values map to i18n keys:
    #   identity_missing   → chapter.ownership.degraded.insiders.identity_missing
    #   no_recent_filings  → chapter.ownership.degraded.insiders.no_recent_filings
    #   fetch_error        → chapter.ownership.degraded.insiders.fetch_error
    #   parse_failed       → chapter.ownership.degraded.proxy.parse_failed
    degraded_reasons: dict[
        str,
        Literal["identity_missing", "no_recent_filings", "fetch_error", "parse_failed"],
    ] = Field(default_factory=dict)

    # Data-freshness / fetch warnings lifted from the SEC payloads (e.g. the
    # 13F cache serving a stale quarter). builders._collect_warnings hoists
    # any structured object's ``warnings`` into artifact.outputs.warnings —
    # same contract as FinancialData.warnings. Distinct from degraded_sections:
    # degraded = "section data unavailable, render placeholder"; a warning
    # annotates data that IS displayed.
    warnings: list[str] = Field(default_factory=list)
