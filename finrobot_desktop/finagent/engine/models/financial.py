from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime


# ---------------------------------------------------------------------------
# FinancialData sub-models (S1 refactor)
# ---------------------------------------------------------------------------


class IncomeStatement(BaseModel):
    """Income statement metrics."""

    revenue: float = Field(description="Annual revenue in USD")
    ebitda: float = Field(description="EBITDA in USD")
    net_income: float = Field(description="Net income in USD")
    gross_margin: float = Field(ge=0, le=1, description="Gross margin as decimal")
    operating_margin: float = Field(ge=-5, le=1, description="Operating margin as decimal")
    depreciation_amortization: float | None = None
    rd_expense: float | None = None
    sga_expense: float | None = None
    interest_expense: float | None = None


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


class ValuationMetrics(BaseModel):
    """Derived valuation multiples. Computed by code, not LLM."""

    model_config = ConfigDict(frozen=False)

    enterprise_value: float | None = None
    ev_ebitda: float | None = None
    ev_revenue: float | None = None


class FinancialData(BaseModel):
    """Structured financial data for a single company.

    Access fields via sub-models:
        fd.income.revenue, fd.balance.total_debt, fd.market.market_cap, etc.
    """

    model_config = ConfigDict(frozen=False)

    ticker: str
    company_name: str = ""
    timestamp: datetime

    income: IncomeStatement
    balance: BalanceSheet = Field(default_factory=BalanceSheet)
    market: MarketData
    valuation: ValuationMetrics = Field(default_factory=ValuationMetrics)

    data_source: str = "yfinance"
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
    """Financial data for one company in a peer set."""

    model_config = ConfigDict(frozen=False)

    ticker: str
    name: str | None = None
    revenue: float
    ebitda: float
    net_income: float
    market_cap: float
    total_debt: float = 0
    total_cash: float = 0
    enterprise_value: float | None = None
    gross_margin: float
    operating_margin: float
    pe_ratio: float | None = None
    ev_ebitda: float | None = None
    ev_revenue: float | None = None


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

    # LLM-provided
    peer_justification: str = ""
    positioning_narrative: str = ""


class PeerSelection(BaseModel):
    """LLM structured output for peer selection step."""

    tickers: list[str] = Field(
        min_length=3,
        max_length=10,
        description="Peer ticker symbols. Exactly 3-10 publicly traded companies.",
    )
    rationale: str = Field(description="One sentence: why these peers were selected.")


class DCFInputs(BaseModel):
    """Inputs for DCF calculation. LLM selects these, code computes the math.

    Note on FCF formula (P1.5 simplification):
    FCF = EBITDA × (1 - tax) - revenue × capex_pct - revenue × nwc_pct

    The explicit expansion:
    - projected_ebitda = projected_revenue × ebitda_margin
    - after_tax_ebitda = projected_ebitda × (1 - tax_rate)
    - capex = projected_revenue × capex_pct_revenue
    - nwc_change = projected_revenue × nwc_pct_revenue
    - fcf = after_tax_ebitda - capex - nwc_change

    This over-taxes by not deducting D&A before tax. Acceptable because yfinance
    doesn't provide D&A separately.
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
    da_pct_revenue: float | None = Field(
        default=None,
        ge=0,
        le=0.5,
        description="D&A as % of revenue. None = use simplified FCF formula (P1.5).",
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

    fcf_formula: str = "simplified"  # "simplified" | "standard_with_da"
    fcf_formula_warning: str | None = None  # Non-None when simplified formula was used


class ThesisResult(BaseModel):
    """Investment thesis. LLM provides judgment, code validates structure."""

    recommendation: str = Field(description="Buy/Hold/Sell")
    price_target: float = Field(gt=0)
    price_target_basis: str
    catalysts: list[str] = Field(min_length=1)
    risks: list[str] = Field(min_length=1)
    narrative: str


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
    gross_margin: list[float]
    sga: list[float]
    sga_ratio: list[float]
    ebitda: list[float]
    ebitda_margin: list[float]
    operating_income: list[float]
    operating_margin: list[float]
    net_income: list[float]
    eps: list[float]
    pe_ratio: list[float | None]
    cagr_revenue: float | None
    ticker: str
    price_data_available: bool = False
    operating_cash_flow: list[float] = Field(default_factory=list)
    investing_cash_flow: list[float] = Field(default_factory=list)
    financing_cash_flow: list[float] = Field(default_factory=list)


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


class ValuationSynthesis(BaseModel):
    """Multi-method valuation synthesis. Football field data derives from methods."""

    methods: list[ValuationMethod]
    weighted_price: float
    current_price: float
    upside_downside: float


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
    revenue_growth_rate: float = Field(ge=-0.5, le=1.0, description="Annual revenue growth (constant)")
    ebitda_margin: float = Field(ge=0, le=1, description="EBITDA/revenue (constant)")
    da_pct_revenue: float = Field(default=0.04, ge=0, le=0.3)
    capex_pct_revenue: float = Field(default=0.04, ge=0, le=0.5)
    nwc_change_pct_revenue: float = Field(default=0.01, ge=-0.2, le=0.3)
    leverage_multiple: float = Field(default=5.0, ge=0, le=20, description="Total debt / EBITDA at entry")
    interest_rate: float = Field(default=0.07, ge=0, le=0.5, description="Blended debt rate")
    mandatory_amort_pct: float = Field(default=0.01, ge=0, le=0.5, description="Mandatory amortization as % of entry debt per year")
    cash_sweep: bool = Field(default=True, description="Sweep all excess FCF to debt")
    tax_rate: float = Field(default=0.25, ge=0, le=1)


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
    fcf: float                      # Cash available for debt service
    mandatory_amort: float
    cash_sweep_amount: float
    total_debt_paydown: float
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
    eps_surprise_pct: float         # (actual - est) / |est| × 100
    eps_direction: str              # "beat" | "miss" | "inline"
    revenue_actual: float
    revenue_estimated: float
    revenue_surprise_pct: float
    revenue_direction: str          # "beat" | "miss" | "inline"


class EarningsResult(BaseModel):
    """Aggregated earnings quality metrics. Computed from N quarters of data."""

    ticker: str
    surprises: list[EarningsSurprise]
    beat_rate: float = Field(ge=0, le=1, description="% of quarters with EPS beat")
    avg_eps_surprise_pct: float
    avg_revenue_surprise_pct: float
    consecutive_beats: int = Field(ge=0, description="Current consecutive beat streak (most recent first)")


# ---------------------------------------------------------------------------
# IC Memo Models (P2d)
# ---------------------------------------------------------------------------


class ICFinancials(BaseModel):
    """Combined DCF + LBO results for IC Memo financial analysis step."""

    financial_data: "FinancialData"
    dcf_result: DCFResult
    lbo_result: LBOResult
