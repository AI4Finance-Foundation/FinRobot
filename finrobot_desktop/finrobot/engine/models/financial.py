from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field
from datetime import date, datetime


# ---------------------------------------------------------------------------
# FinancialData sub-models (S1 refactor)
# ---------------------------------------------------------------------------


class IncomeStatement(BaseModel):
    """Income statement metrics."""

    revenue: float = Field(description="Annual revenue in USD")
    # None ≠ 0: a missing figure stays None so downstream withholds the derived
    # metric (data unavailable) instead of treating a fabricated 0 as a real
    # value — 0 EBITDA / 0 margin is a going-concern signal, not "not reported".
    ebitda: float | None = Field(default=None, description="EBITDA in USD; None when unavailable")
    net_income: float | None = Field(
        default=None, description="Net income in USD; None when unavailable"
    )
    gross_margin: float | None = Field(
        default=None, ge=0, le=1, description="Gross margin as decimal; None when unavailable"
    )
    operating_margin: float | None = Field(
        default=None, ge=-5, le=1, description="Operating margin as decimal; None when unavailable"
    )
    depreciation_amortization: float | None = None
    rd_expense: float | None = None
    sga_expense: float | None = None
    interest_expense: float | None = None
    income_tax_expense: float | None = None
    """Income tax provision in USD. Carried from NormalizedFinancials so the DCF
    seed can derive a company-specific effective tax rate
    (tax / (net_income + tax)) instead of falling back to the Damodaran industry
    aggregate — which for distorted sectors (Software (Internet) = 40%, skewed by
    loss-makers) badly misstates a profitable mega-cap's real ~16-21% rate."""


class BalanceSheet(BaseModel):
    """Balance sheet metrics."""

    total_debt: float = Field(default=0, description="Total debt in USD")
    total_cash: float = Field(default=0, description="Total cash in USD")


class MarketData(BaseModel):
    """Market and price data."""

    market_cap: float = Field(description="Market cap in USD")
    shares_outstanding: float = Field(gt=0)
    current_price: float = Field(gt=0)
    pe_ratio: float | None = None
    price_52w_high: float | None = None
    price_52w_low: float | None = None
    # Industry / sector strings as reported by the data provider. Used by
    # dcf_seed to look up Damodaran industry medians when ticker-level data
    # is missing. None when provider didn't expose it.
    industry: str | None = None
    sector: str | None = None
    beta: float | None = Field(default=None, ge=0, le=5)


class ValuationMetrics(BaseModel):
    """Derived valuation multiples. Computed by code, not LLM."""

    model_config = ConfigDict(frozen=False)

    enterprise_value: float | None = None
    # EBITDA carried in two calibers (engine.compute.multiples):
    #   ebitda_operating = EBIT + D&A          → ev_ebitda          (PRIMARY)
    #   ebitda_reported  = NI+tax+interest+D&A → ev_ebitda_reported (street x-check)
    # ev_ebitda uses the operating caliber because EV already nets out cash;
    # the *_reported pair mirrors retail aggregators (which credit non-operating
    # income) so the UI can footnote the gap instead of looking "wrong".
    ebitda_operating: float | None = None
    ebitda_reported: float | None = None
    ev_ebitda: float | None = None
    ev_ebitda_reported: float | None = None
    ev_revenue: float | None = None


class DataProvenance(BaseModel):
    """Source + freshness + degradation flags for a snapshot's numbers.

    Surfaced to the UI (SourcedNumber popovers, degraded badges, "TTM 截至 X"
    label) so provenance is visible instead of hardcoded/assumed (ADR-0004).
    """

    model_config = ConfigDict(frozen=False)

    provider: str
    as_of: date | None = None  # financials period end — the data's semantic time
    period_basis: str = "ttm"
    pe_ttm_lag_quarters: int | None = None
    degraded: list[str] = Field(default_factory=list)  # close_only / ttm_lag / ccy_inferred


class FinancialData(BaseModel):
    """Structured financial data for a single company.

    Access fields via sub-models:
        fd.income.revenue, fd.balance.total_debt, fd.market.market_cap, etc.
    """

    model_config = ConfigDict(frozen=False)

    ticker: str
    company_name: str = ""
    timestamp: datetime  # when this data was fetched — not the fiscal period end

    # Fiscal period this snapshot represents. Set by extract_financial_data when
    # the provider supplies `fiscal_year` or `date` (historical fetches do, the
    # single-year TTM fetch doesn't). Downstream consumers (extract_historical_
    # metrics, chart year labels) prefer this over `timestamp.year` so a
    # five-year history doesn't collapse to today's year five times.
    fiscal_period_end: date | None = None

    income: IncomeStatement
    balance: BalanceSheet = Field(default_factory=BalanceSheet)
    market: MarketData
    valuation: ValuationMetrics = Field(default_factory=ValuationMetrics)

    # Currency tags carried from NormalizedFinancials (same meaning as on
    # CompanyFinancials): reporting_currency = IS/BS line items, quote_currency =
    # market_cap/price. They DISAGREE for foreign-listed ADRs (TSM: TWD / USD).
    # build_xbrl_aligned_company reads these to FX-normalize a foreign target to
    # canonical USD before comps multiples, symmetric with the peer path (BUG-018).
    reporting_currency: str = "USD"
    quote_currency: str = "USD"

    data_source: str = "yfinance"
    provenance: DataProvenance | None = None
    warnings: list[str] = Field(default_factory=list)


class AggregatedNewsItem(BaseModel):
    """Single news item from the multi-source aggregator.

    Lighter than compute.news.NewsItem (which requires LLM classification).
    This model holds raw aggregated data + keyword-based sentiment score.
    """

    title: str
    source: str
    url: str = ""
    published_at: str = ""
    sentiment_score: float | None = Field(
        default=None,
        ge=-1.0,
        le=1.0,
        description="Keyword or Alpha Vantage sentiment. -1 to +1. None if unavailable.",
    )
    category: str | None = None


class AggregatedNewsFeed(BaseModel):
    """Response model for /api/data/{ticker}/news endpoint."""

    ticker: str
    items: list[AggregatedNewsItem]
    sources_used: list[str]
    overall_sentiment: float = Field(
        ge=-1.0,
        le=1.0,
        description="Average sentiment across all items.",
    )
    fetched_at: datetime
    warnings: list[str] = Field(default_factory=list)


class PriceHistory(BaseModel):
    """Structured price history."""

    ticker: str
    period: str
    data_points: int
    current_price: float
    high_52w: float
    low_52w: float
    avg_price: float


class CompanyFinancials(BaseModel):
    """Financial data for one company in a peer set.

    Two currency tags because yfinance carries them separately and they
    DISAGREE for foreign-listed ADRs:

    - ``reporting_currency`` (ISO 4217): currency of the income-statement
      and balance-sheet line items — ``revenue, ebitda, net_income,
      total_debt, total_cash``.
    - ``quote_currency`` (ISO 4217): currency of the market quote —
      ``market_cap`` (and any price-derived field).

    For US issuers both are USD. For TSM ADR they are TWD and USD
    respectively — that mismatch collapses EV/EBITDA to 0.158x without
    normalization. See ``finrobot.engine.compute.fx_normalize`` for the
    canonical-USD pipeline applied before EV/EBITDA is computed.
    """

    model_config = ConfigDict(frozen=False)

    ticker: str
    name: str | None = None
    revenue: float
    # None ≠ 0: a provider that omits these must not be treated as zero EBITDA /
    # earnings / margin — that fabrication poisoned the peer median and the NOPAT
    # core P/E. Downstream multiples withhold the affected ratio when None.
    ebitda: float | None = None
    net_income: float | None = None
    market_cap: float
    # None ≠ 0: None means the provider did not report the figure, so EV (and
    # the EV-based multiples) MUST be withheld rather than computed against an
    # assumed-zero net-debt — that fabrication silently poisoned the peer median
    # (a cash-rich peer reported as debt=cash=0 → EV=market_cap). Mirrors the
    # target path in extract_financial_data, which already refuses EV when debt
    # or cash is missing.
    total_debt: float | None = None
    total_cash: float | None = None
    enterprise_value: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    pe_ratio: float | None = None
    ev_ebitda: float | None = None
    ev_revenue: float | None = None
    # Income tax provision in USD, carried from the provider so calculate_core_pe
    # can derive a company-specific effective rate (tax / (net_income + tax)) for
    # the NOPAT core-earnings caliber. None when the provider omits it.
    income_tax_expense: float | None = None
    # NOPAT-based core-earnings fields, filled by calculate_core_pe (a set-level
    # pass — the degenerate-tax fallback needs the whole peer set). They give P/E
    # comps a consistent earnings caliber: as-reported net income mixes in
    # non-operating items that differ across the set (NVDA's TTM investment gains,
    # AMD/AVGO near-zero effective tax), making raw P/E apples-to-oranges.
    effective_tax_rate: float | None = None
    core_net_income: float | None = None  # NOPAT = EBIT × (1 − effective_tax_rate)
    core_pe_ratio: float | None = None  # market_cap / NOPAT, gated by P/E sanity bounds
    reporting_currency: str = "USD"
    quote_currency: str = "USD"
    # [待核] note set when SEC XBRL TTM diverged materially from the FMP TTM base
    # and we kept FMP rather than overriding (ADR-0008). None when the two agree
    # or no XBRL was available. Rolled up into PeerComps.warnings for display.
    ttm_divergence_note: str | None = None


class PeerComps(BaseModel):
    """Comparable company analysis result."""

    model_config = ConfigDict(frozen=False)

    target: CompanyFinancials
    peers: list[CompanyFinancials] = Field(min_length=1)

    # Computed by code
    median_ev_ebitda: float | None = None
    median_pe: float | None = None
    median_ev_revenue: float | None = None
    mean_ev_ebitda: float | None = None
    mean_pe: float | None = None
    # Peer median of the NOPAT-based core P/E (calculate_core_pe). The comps_pe
    # valuation method pairs this with the target's core EPS so numerator and
    # denominator share one earnings caliber.
    median_core_pe: float | None = None

    # LLM-provided
    peer_justification: str = ""
    positioning_narrative: str = ""

    # Data-quality warnings produced by calculate_peer_statistics / validators
    warnings: list[str] = Field(default_factory=list)


class PeerSelection(BaseModel):
    """LLM structured output for peer selection step."""

    tickers: list[str] = Field(
        min_length=3,
        max_length=10,
        description="Peer ticker symbols. Exactly 3-10 publicly traded companies.",
    )
    rationale: str = Field(description="One sentence: why these peers were selected.")


class DCFInputs(BaseModel):
    """Inputs for DCF calculation. Built by ``seed_dcf_inputs`` from real
    filings (3y historical medians) + Damodaran industry fallback. The LLM
    never selects these numbers — it only interprets them in the output_gen
    narrative step.

    FCF formula (standard, always used):
        FCF = EBIT(1-tax) + D&A - CapEx - ΔNWC
            = (EBITDA - D&A)(1-tax) + D&A - revenue*capex_pct - revenue*nwc_pct

    ``da_pct_revenue`` carries the D&A tax shield and is always populated by
    seed_dcf_inputs.
    """

    revenue_base: float = Field(description="Base year revenue in USD")
    revenue_growth_rates: list[float] = Field(
        min_length=1, description="Projected annual growth rates as decimals"
    )
    ebitda_margin: float = Field(ge=0, le=1, description="Projected EBITDA margin")
    capex_pct_revenue: float = Field(ge=0, le=1, description="Capex as % of revenue")
    nwc_pct_revenue: float = Field(
        ge=-0.2, le=0.5, description="Net working capital change as % of revenue"
    )
    da_pct_revenue: float = Field(
        default=0.0,
        ge=0,
        le=0.5,
        description=(
            "D&A as % of revenue, carrying the tax shield in the FCF formula. "
            "Default 0.0 means no shield; seed_dcf_inputs always sets a non-zero "
            "value from 3y filings or Damodaran fallback. Direct callers may omit it."
        ),
    )
    tax_rate: float = Field(ge=0, le=1, default=0.21)

    # WACC inputs
    risk_free_rate: float = Field(ge=0, le=0.15)
    beta: float = Field(ge=0, le=5)
    equity_risk_premium: float = Field(ge=0, le=0.15)
    cost_of_debt: float = Field(ge=0, le=0.20)
    debt_ratio: float = Field(ge=0, le=1, description="Debt / (Debt + Equity)")

    # Terminal value
    terminal_growth_rate: float = Field(ge=0, le=0.05, description="Long-term growth rate")

    shares_outstanding: float = Field(gt=0)
    net_debt: float = Field(description="Total debt - cash. Negative if net cash.")

    assumption_provenance: dict[str, str] = Field(
        default_factory=dict,
        description="Maps assumption field names to their reasoning/source",
    )


class DCFResult(BaseModel):
    """DCF valuation output. All numbers computed by code, not LLM."""

    # WACC
    cost_of_equity: float | None  # None when wacc_override was used
    wacc: float

    # Projections
    projection_years: int
    projected_revenue: list[float]
    projected_ebitda: list[float]
    projected_fcf: list[float]

    # Terminal value
    terminal_value: float
    pv_terminal: float

    # Valuation
    pv_fcf_total: float
    enterprise_value: float
    equity_value: float
    implied_price: float

    # Sensitivity
    sensitivity_table: dict[str, Any] | None = None

    # Inputs used (for reproducibility)
    inputs: DCFInputs


class ThesisResult(BaseModel):
    """Investment thesis. LLM provides judgment, code validates structure.

    narrative fields are optional so old artifacts still
    validate after the schema bump; new pipeline runs populate them once
    the LLM cooperates. Together these 6 slots cover the standard 8
    8-agent surface (tagline / company_overview / investment_overview /
    valuation_overview / risks / competitor_analysis / major_takeaways /
    news_summary) — investment_overview maps to recommendation + narrative,
    major_takeaways maps to key_takeaways, risks maps to risks list.
    """

    recommendation: str = Field(description="Buy/Hold/Sell/REVIEW")
    price_target: float | None = Field(
        default=None,
        description=(
            "12-month price target. None when the valuation methods fail the "
            "data-health gate (recommendation='REVIEW') — the system refuses to "
            "publish a target it cannot defend rather than averaging "
            "non-corroborating methods into a phantom number."
        ),
    )
    price_target_basis: str
    catalysts: list[str] = Field(min_length=1)
    risks: list[str] = Field(min_length=1)
    narrative: str

    # ── narrative LLM narrative slots ───────────────────────────────
    tagline: str | None = Field(
        default=None,
        description=(
            "One-sentence shareable conclusion (≤ 60 中文字符). "
            "Example: 'NVDA · AI 算力超级周期受益者，估值仍有 30% 上行空间'."
        ),
    )
    key_takeaways: list[str] | None = Field(
        default=None,
        description=(
            "3-5 bullet points the analyst reader should walk away with. "
            "Distinct from `catalysts` (future events) and `risks` (downsides) "
            "— these are present-tense conclusions."
        ),
    )
    company_overview: str | None = Field(
        default=None,
        description=(
            "200-300 字 Company Overview (第 8 synthesis slot). "
            "Cover business model, reportable segments with revenue mix, "
            "geographic exposure, and the durable moat. Investment-bank "
            "tone — no retail simplification."
        ),
    )
    valuation_overview: str | None = Field(
        default=None,
        description=("150-200 字解读 DCF / Comps / DDM 之间为什么有差距、加权之后的目标价怎么来。"),
    )
    competitor_analysis: str | None = Field(
        default=None,
        description="vs 同业的竞争格局叙事（市占 / 增速 / 倍数对比的人话总结）。",
    )
    news_summary: str | None = Field(
        default=None,
        description="近 30 天关键新闻的 3-5 句话整体情绪叙事。",
    )


class StepOutput(BaseModel):
    """Wrapper for pipeline step output: text for report + optional structured data.

    The `structured` field accepts a BaseModel instance, a dict, or None.
    Uses ConfigDict(arbitrary_types_allowed=True) to prevent Pydantic validation
    that would try to instantiate BaseModel directly. The type annotation
    `object` is intentionally broad to prevent Pydantic coercion.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    text: str
    structured: object | None = Field(default=None)  # Accepts BaseModel, dict, or any object


class HistoricalMetrics(BaseModel):
    """Multi-year historical financial metrics extracted from provider data."""

    years: list[int]
    revenue: list[float]
    revenue_growth_yoy: list[float | None]
    cogs: list[float]
    gross_profit: list[float]
    # Margins are None for a year whose numerator the provider omitted — a
    # missing margin is "not reported", distinct from a real 0% (None ≠ 0). The
    # absolute line items keep the 0.0 fill (all-zero row = missing convention
    # used by dcf_seed._median_ratio).
    gross_margin: list[float | None]
    sga: list[float]
    sga_ratio: list[float | None]
    ebitda: list[float]
    ebitda_margin: list[float | None]
    operating_income: list[float]
    operating_margin: list[float | None]
    net_income: list[float]
    eps: list[float]
    pe_ratio: list[float | None]
    cagr_revenue: float | None
    ticker: str
    price_data_available: bool = False
    operating_cash_flow: list[float] = Field(default_factory=list)
    investing_cash_flow: list[float] = Field(default_factory=list)
    financing_cash_flow: list[float] = Field(default_factory=list)

    # P7 — line items needed for standard DCF FCF formula: EBIT(1-t) + D&A - CapEx - ΔNWC.
    # Parallel to revenue/ebitda — same year ordering. Empty when provider didn't expose
    # the row; downstream consumers (dcf_seed) must fall back to industry medians and mark
    # provenance accordingly.
    depreciation_amortization: list[float] = Field(default_factory=list)
    capital_expenditure: list[float] = Field(default_factory=list)
    change_in_working_capital: list[float] = Field(default_factory=list)


class MarginAssumptions(BaseModel):
    """User-provided or default margin targets for forecasting."""

    gross_margin_target: float | None = None
    ebitda_margin_target: float | None = None
    sga_ratio_target: float | None = None


class ForecastAssumptions(BaseModel):
    """Records exactly which assumptions were used in a forecast."""

    revenue_growth_rates: list[float]
    gross_margin: float
    ebitda_margin: float
    sga_ratio: float
    tax_rate: float = Field(
        default=0.21,
        ge=0,
        le=1.0,
        description="Corporate tax rate. Default 0.21 (US federal). Override for non-US companies.",
    )


class ForecastResult(BaseModel):
    """Deterministic 3-year financial forecast output."""

    years: list[int]
    revenue: list[float]
    ebitda: list[float]
    net_income: list[float]
    eps: list[float]
    assumptions: ForecastAssumptions
    warnings: list[str] = Field(default_factory=list)


class CatalystEvent(BaseModel):
    """Single catalyst event extracted by LLM from news."""

    category: Literal[
        "product_launch",
        "earnings",
        "regulatory",
        "acquisition",
        "management",
        "market",
    ]
    headline: str
    sentiment: Literal["positive", "negative", "neutral"]
    impact_score: int = Field(ge=1, le=5)
    probability: float = Field(ge=0, le=1)
    reasoning: str
    published: datetime | None = None
    url: str | None = None


class CatalystAnalysis(BaseModel):
    """LLM-structured catalyst analysis output."""

    events: list[CatalystEvent]
    overall_sentiment: Literal["bullish", "bearish", "neutral"]
    key_catalysts: list[str]
    # P6 additions
    net_sentiment: float = Field(default=0.0, description="Sum of expected impacts, -5 to +5 scale")
    category_breakdown: dict[str, int] = Field(default_factory=dict)
    top_positive: list[CatalystEvent] = Field(default_factory=list)
    top_negative: list[CatalystEvent] = Field(default_factory=list)


class ValuationMethod(BaseModel):
    """One valuation method's result range."""

    name: str
    low: float
    mid: float
    high: float
    confidence: float = Field(ge=0, le=1)
    source: str
    assumptions: str | None = Field(
        default=None,
        description=(
            "Short human-readable summary of the load-bearing assumptions behind "
            "`mid` — e.g. DCF's 'WACC 16.6% · 5年增长40%→2.5% · β2.24'. A mid like "
            "$73 is not a valuation, it's an answer conditional on these. Carried "
            "downstream into the IC debate so a price is never cited naked."
        ),
    )


class ValuationSynthesis(BaseModel):
    """Multi-method valuation synthesis. Football field data derives from methods."""

    methods: list[ValuationMethod]
    weighted_price: float | None
    """None when fewer than 2 methods are available — single-method "averages"
    are meaningless cross-checks and MUST NOT be presented as weighted targets."""
    current_price: float
    upside_downside: float | None
    """None when weighted_price is None (no valid cross-check available)."""
    outlier_methods: list[str] = Field(
        default_factory=list,
        description=(
            "Method names whose mid deviates > 30% from the cross-method median. "
            "Populated by synthesize_valuations; empty when fewer than 2 methods."
        ),
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Human-readable warnings produced during synthesis (e.g. spread alerts).",
    )
    reliable: bool = Field(
        default=True,
        description=(
            "False when at least one method deviates > 50% from the cross-method "
            "median — the weighted target is then the midpoint of estimates that "
            "don't corroborate and MUST NOT be published as a headline "
            "target/verdict. Drives the equity-research data-health gate."
        ),
    )


# ---------------------------------------------------------------------------
# LBO Models (P2d)
# ---------------------------------------------------------------------------


class LBOInputs(BaseModel):
    """Assumptions driving the LBO model. LLM selects these, code computes math."""

    ticker: str
    ltm_ebitda: float = Field(gt=0, description="LTM EBITDA at entry (USD)")
    entry_ev_ebitda: float = Field(gt=0, description="Entry EV/EBITDA multiple")
    exit_ev_ebitda: float = Field(gt=0, description="Exit EV/EBITDA multiple")
    holding_period_years: int = Field(default=5, ge=1, le=10)
    revenue_base: float = Field(gt=0, description="LTM revenue at entry (USD)")
    revenue_growth_rate: float = Field(
        ge=-0.5, le=1.0, description="Annual revenue growth (constant)"
    )
    ebitda_margin: float = Field(ge=0, le=1, description="EBITDA/revenue (constant)")
    da_pct_revenue: float = Field(default=0.04, ge=0, le=0.3)
    capex_pct_revenue: float = Field(default=0.04, ge=0, le=0.5)
    nwc_change_pct_revenue: float = Field(default=0.01, ge=-0.2, le=0.3)
    leverage_multiple: float = Field(
        default=5.0, ge=0, le=20, description="Total debt / EBITDA at entry"
    )
    interest_rate: float = Field(default=0.07, ge=0, le=0.5, description="Blended debt rate")
    mandatory_amort_pct: float = Field(
        default=0.01, ge=0, le=0.5, description="Mandatory amortization as % of entry debt per year"
    )
    cash_sweep: bool = Field(default=True, description="Sweep all excess FCF to debt")
    tax_rate: float = Field(default=0.25, ge=0, le=1)

    # Parallels DCFInputs.assumption_provenance — populated by seed_lbo_inputs.
    # Maps each LBO assumption field name to a Chinese-localised explanation of
    # where the number came from (3y historical median / industry median / PE
    # convention) so the UI can render a 散户-friendly provenance panel.
    # The DCFInputs equivalent is the canonical reference for the contract.
    assumption_provenance: dict[str, str] = Field(
        default_factory=dict,
        description="Maps assumption field names to their reasoning/source",
    )


class LBOYear(BaseModel):
    """One year of LBO operations. All numbers deterministically computed."""

    year: int
    revenue: float
    ebitda: float
    da: float
    ebit: float
    interest_expense: float
    ebt: float
    taxes: float
    net_income: float
    capex: float
    delta_nwc: float
    fcf: float  # Cash available for debt service
    mandatory_amort: float
    cash_sweep_amount: float
    total_debt_paydown: float
    revolver_draw: float = 0.0  # Revolver borrowing when FCF < mandatory amort (cash-burn year)
    ending_debt: float


class LBOResult(BaseModel):
    """Full LBO model output. All returns computed by code, not LLM."""

    entry_ev: float
    entry_debt: float
    entry_equity: float
    schedule: list[LBOYear] = Field(min_length=1)
    exit_ebitda: float
    exit_ev: float
    exit_equity: float
    moic: float
    irr: float = Field(description="Annualized IRR (decimal). -1.0 = total loss.")
    sensitivity: dict[str, Any] = Field(
        default_factory=dict,
        description="entry_multiples, exit_multiples, irr_grid, moic_grid",
    )
    irr_formula_warning: str | None = None
    capital_structure_warning: str | None = None


# ---------------------------------------------------------------------------
# Earnings Models (P2d)
# ---------------------------------------------------------------------------


class SurpriseDirection(str):
    """Beat/miss/inline classification. Not an Enum to avoid Pydantic v2 coercion issues."""

    BEAT = "beat"
    MISS = "miss"
    INLINE = "inline"


class EarningsSurprise(BaseModel):
    """Single quarter earnings surprise. All computed by code from raw provider data."""

    date: str
    eps_actual: float
    eps_estimated: float
    eps_surprise_pct: float | None  # (actual - est) / |est| × 100; None if est == 0
    eps_direction: str  # "beat" | "miss" | "inline" | "n/a" (n/a = undefined, est == 0)
    revenue_actual: float
    revenue_estimated: float
    revenue_surprise_pct: float | None  # None if estimate == 0 (undefined surprise)
    revenue_direction: str  # "beat" | "miss" | "inline" | "n/a"


class EarningsResult(BaseModel):
    """Aggregated earnings quality metrics. Computed from N quarters of data."""

    ticker: str
    surprises: list[EarningsSurprise]
    beat_rate: float = Field(ge=0, le=1, description="% of quarters with EPS beat")
    avg_eps_surprise_pct: float
    avg_revenue_surprise_pct: float
    consecutive_beats: int = Field(
        ge=0, description="Current consecutive beat streak (most recent first)"
    )


# ---------------------------------------------------------------------------
# IC Memo Models (P2d)
# ---------------------------------------------------------------------------


class ICFinancials(BaseModel):
    """Combined DCF + LBO results for IC Memo financial analysis step."""

    financial_data: "FinancialData"
    dcf_result: DCFResult
    lbo_result: LBOResult


# ---------------------------------------------------------------------------
# DDM Models (bank/dividend valuation)
# ---------------------------------------------------------------------------


class DDMInputs(BaseModel):
    """Inputs for Dividend Discount Model.

    DDM is the standard valuation method for banks, utilities, and
    dividend-paying stocks where traditional free cash flow is not meaningful.
    Banks earn via net interest income and return cash primarily through dividends.

    LLM selects these assumptions; code computes the valuation math.
    """

    dividend_per_share: float = Field(gt=0, description="Most recent annual DPS")
    dividend_growth_rates: list[float] = Field(
        min_length=1,
        max_length=10,
        description="Projected annual dividend growth rates as decimals",
    )
    payout_ratio: float = Field(ge=0, le=1, description="Dividend payout ratio")

    # Cost of equity inputs (CAPM)
    risk_free_rate: float = Field(ge=0, le=0.15)
    beta: float = Field(ge=0, le=3)
    equity_risk_premium: float = Field(ge=0, le=0.15)

    terminal_growth_rate: float = Field(ge=0, le=0.05)
    terminal_payout_ratio: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description=(
            "Payout ratio applied in the Gordon-perpetuity terminal phase. When "
            "set, the terminal dividend is normalized to the payout a mature firm "
            "can sustain at its ROE and terminal growth (≈ 1 − g/ROE), correcting "
            "the naive DDM error of holding a low trailing payout into perpetuity. "
            "seed_ddm_inputs derives this; when None calculate_ddm falls back to "
            "the constant-payout (naive Gordon) terminal."
        ),
    )
    shares_outstanding: float = Field(gt=0)
    current_price: float = Field(gt=0)

    # Bank-specific context (optional, for enriching narrative)
    book_value_per_share: float | None = None
    return_on_equity: float | None = None
    tier1_ratio: float | None = None
    net_interest_margin: float | None = None

    assumption_provenance: dict[str, str] = Field(
        default_factory=dict,
        description="Maps assumption field names to their reasoning/source",
    )


class DDMResult(BaseModel):
    """DDM valuation output. All numbers computed by code, not LLM.

    Uses cost of equity (not WACC) as discount rate because dividends
    are paid to equity holders only.
    """

    cost_of_equity: float
    projected_dividends: list[float]
    pv_dividends: list[float]
    pv_dividends_total: float
    terminal_dividend: float
    terminal_value: float
    pv_terminal: float
    equity_value_per_share: float
    inputs: DDMInputs

    @property
    def upside(self) -> float:
        """Upside/downside vs current price as a decimal."""
        return self.equity_value_per_share / self.inputs.current_price - 1


# ---------------------------------------------------------------------------
# Football Field aggregation (v5 §6.4)
# ---------------------------------------------------------------------------


ValuationMethodType = Literal["valuation", "multiple"]
"""Distinguishes independent valuation methods (DCF / Comps / DDM / LBO) from
multiple-based reverse-engineered ranges (EV/EBITDA, P/FCF) so the UI can render
them with different visual weight — solid bars vs dashed bars (spec §6.4)."""

ValuationMethodName = Literal[
    "dcf",
    "comps_pe",
    "lbo",
    "ddm",
    "ev_ebitda",
    "p_fcf",
]


class ValuationMethodRange(BaseModel):
    """One method's low / mid / high target-price band for the Football Field.

    A leaner cousin of ValuationMethod tagged with `method_type` so the front
    end can render valuation methods as solid bars and multiple-based reverse
    ranges as dashed bars (v5 §6.4).
    """

    method: ValuationMethodName
    method_type: ValuationMethodType
    low: float = Field(gt=0)
    mid: float = Field(gt=0)
    high: float = Field(gt=0)
    confidence: float = Field(ge=0, le=1)
    source: str = Field(description="Human-readable provenance, e.g. 'monte_carlo_p10_p90'")
    assumptions: str | None = Field(
        default=None,
        description=(
            "Short summary of the load-bearing assumptions behind `mid`, built at "
            "the source where the underlying result object is in scope. Propagated "
            "to ValuationMethod.assumptions and into the IC debate evidence."
        ),
    )
    warnings: list[str] = Field(default_factory=list)


class ValuationAggregate(BaseModel):
    """Response payload for ``GET /api/valuation/aggregate/{ticker}``.

    Contains every method we could compute for the ticker at request time.
    Missing methods are simply absent from `methods`; the UI shows what's
    available and explains the gaps via `warnings`.
    """

    ticker: str
    current_price: float | None
    as_of: datetime
    methods: list[ValuationMethodRange]
    warnings: list[str] = Field(default_factory=list)
