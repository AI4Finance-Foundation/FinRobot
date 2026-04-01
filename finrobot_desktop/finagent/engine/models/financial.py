from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime


class FinancialData(BaseModel):
    """Structured financial data for a single company."""
    model_config = ConfigDict(frozen=False)

    ticker: str
    timestamp: datetime

    # Income statement
    revenue: float = Field(description="Annual revenue in USD")
    ebitda: float = Field(description="EBITDA in USD")
    net_income: float = Field(description="Net income in USD")

    # Balance sheet
    total_debt: float = Field(default=0, description="Total debt in USD")
    total_cash: float = Field(default=0, description="Total cash in USD")

    # Margins (as decimals)
    gross_margin: float = Field(ge=0, le=1, description="Gross margin as decimal")
    operating_margin: float = Field(ge=-5, le=1, description="Operating margin as decimal")

    # Valuation
    market_cap: float = Field(description="Market cap in USD")
    shares_outstanding: float = Field(gt=0)
    current_price: float = Field(gt=0)
    pe_ratio: float | None = Field(default=None)

    # Derived (computed by code, not LLM)
    enterprise_value: float | None = Field(default=None)
    ev_ebitda: float | None = Field(default=None)
    ev_revenue: float | None = Field(default=None)

    # Price history summary
    price_52w_high: float | None = None
    price_52w_low: float | None = None

    # Metadata
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
    rationale: str = Field(
        description="One sentence: why these peers were selected."
    )


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
    revenue_growth_rates: list[float] = Field(min_length=1, description="Projected annual growth rates as decimals")
    ebitda_margin: float = Field(ge=0, le=1, description="Projected EBITDA margin")
    capex_pct_revenue: float = Field(ge=0, le=1, description="Capex as % of revenue")
    nwc_pct_revenue: float = Field(ge=-0.2, le=0.5, description="Net working capital change as % of revenue")
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
    sensitivity_table: dict[str, list] | None = None

    # Inputs used (for reproducibility)
    inputs: DCFInputs


class ThesisResult(BaseModel):
    """Investment thesis. LLM provides judgment, code validates structure."""
    recommendation: str = Field(description="Buy/Hold/Sell")
    price_target: float = Field(gt=0)
    price_target_basis: str
    catalysts: list[str] = Field(min_length=1)
    risks: list[str] = Field(min_length=1)
    narrative: str


class StepOutput(BaseModel):
    """Wrapper for pipeline step output: text for report + optional structured data."""
    text: str
    structured: Any = None
