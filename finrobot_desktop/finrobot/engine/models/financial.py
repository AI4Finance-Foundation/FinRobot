import math
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
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
    # Gross margin can be negative: a loss-maker selling below cost (RIVN-class EV
    # makers) reports gross_margin < 0. The old `ge=0` was an asymmetric guard —
    # its sibling operating_margin already allowed negatives (ge=-5) — and 500'd
    # /financials for Rivian. gross_margin ≥ operating_margin always (opex ≥ 0), so
    # the same -5 floor is provably crash-free while still catching a percentage/
    # decimal mixup (e.g. -50 meaning -50%).
    gross_margin: float | None = Field(
        default=None, ge=-5, le=1, description="Gross margin as decimal; None when unavailable"
    )
    operating_margin: float | None = Field(
        default=None, ge=-5, le=1, description="Operating margin as decimal; None when unavailable"
    )
    # Absolute operating income (EBIT) in USD. Carried alongside the margin so the
    # comps target can hand calculate_core_pe a period-consistent EBIT instead of
    # operating_margin × a possibly XBRL-overridden revenue (BUG-017).
    operating_income: float | None = None
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

    # None ≠ 0: a missing component is "not reported", not "the company has zero
    # debt/cash". Defaulting to 0 silently fabricated EV = market_cap + 0 − 0 =
    # market_cap, passing every downstream sanity gate while the net-debt bridge
    # was actually unknown. Consumers (dcf_seed/lbo_seed/fx_normalize) coerce to 0
    # only at the point of use and disclose it in provenance.
    total_debt: float | None = Field(
        default=None, description="Total debt in USD; None = not reported (≠ 0)"
    )
    total_cash: float | None = Field(
        default=None, description="Total cash in USD; None = not reported (≠ 0)"
    )
    # EV bridge completeness (numeric-audit family 3): preferred + minority interest
    # belong in EV; calculate_ev folds them in when reported. Carried here so the
    # extractor can pass them, and audit.ev_bridge can flag an UNREPORTED (None) one
    # whose assumed-0 would understate EV invisibly to the market_cap+debt−cash
    # identity (it still "balances"). None = not reported (≠ 0). Reporting-ccy (FX-scaled).
    preferred_stock: float | None = Field(
        default=None, description="Preferred equity in reporting ccy; None = not reported"
    )
    noncontrolling_interest: float | None = Field(
        default=None, description="Minority/NCI in reporting ccy; None = not reported"
    )


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
    # Issuer country as reported by the provider — FMP /profile gives ISO-2
    # ("US"/"TW"), yfinance .info gives full names ("United States"/"Taiwan").
    # Consumed by the family-1 foreign_issuer_usd_tags acceptor; None = unknown.
    country: str | None = None
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
    degraded: list[str] = Field(default_factory=list)  # close_only / ttm_lag / …


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

    # Quarter-end dates of the quarters summed into a TTM snapshot (FMP builds TTM
    # = Σ latest 4 quarters). Carried so the numeric-audit family-4 verifier can
    # assert the four quarters don't overlap/gap/duplicate — a silently wrong TTM
    # corrupts every ratio (P/E, EV/EBITDA, margins) and the DCF growth it feeds.
    # Empty on the yfinance / annual paths (no per-quarter rows) — the verifier
    # then has nothing to audit and abstains. Optional → read-compatible with
    # cached canonical payloads (BUG-038 precedent), so no schema-version bump.
    ttm_quarter_ends: list[date] = Field(default_factory=list)

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
    field_warnings: dict[str, list[str]] = Field(default_factory=dict)
    """Structured, per-field warning *codes* (not prose) — keyed by the field a
    caveat belongs to (``ev_ebitda`` / ``pe`` / …), each a stable code the UI
    maps to a localized caveat next to that specific number. The free-text
    :attr:`warnings` stays the row-level catch-all; this is what lets a caveat
    sit on the exact cell it concerns instead of a generic row marker."""

    @model_validator(mode="after")
    def _withhold_cross_currency_ratios(self) -> "FinancialData":
        """Structural invariant: a cross-currency EV/multiple cannot exist.

        When ``reporting_currency != quote_currency`` (a foreign ADR whose FX
        normalization was skipped or failed — see the DataLayer canonical FX
        gate) every EV-based ratio mixes a quote-currency ``market_cap`` with
        reporting-currency net debt, so it is meaningless (the -75B TSM EV, probe
        2026-06-09). Rather than trust each consumer to remember the currency
        check, withhold the affected fields HERE at construction: a mixed-currency
        ``enterprise_value`` / ``ev_ebitda`` / ``ev_revenue`` / ``pe_ratio`` can
        never reach the /financials route, Coverage table or AI orchestrator. The
        mismatch then reads honestly as "withheld" instead of a wrong/negative
        number. Single-currency snapshots (the common case once the canonical FX
        gate has run) hit the early return and are untouched.
        """
        if self.reporting_currency.upper() == self.quote_currency.upper():
            return self
        withheld = False
        for attr in ("enterprise_value", "ev_ebitda", "ev_ebitda_reported", "ev_revenue"):
            if getattr(self.valuation, attr) is not None:
                setattr(self.valuation, attr, None)
                withheld = True
        # pe = market_cap[quote ccy] / net_income[reporting ccy] is mixed too.
        if self.market.pe_ratio is not None:
            self.market.pe_ratio = None
            withheld = True
        if withheld:
            codes = self.field_warnings.setdefault("ev_ebitda", [])
            if FIELD_WARN_EV_CROSS_CURRENCY not in codes:
                codes.append(FIELD_WARN_EV_CROSS_CURRENCY)
            warning = (
                f"{self.ticker}: reporting currency {self.reporting_currency} ≠ quote "
                f"currency {self.quote_currency} and FX normalization was unavailable — "
                "EV, EV/EBITDA, EV/Revenue and P/E withheld (a cross-currency ratio is "
                "meaningless)."
            )
            if warning not in self.warnings:
                self.warnings.append(warning)
        return self


# ── Structured field-warning codes (attach at the generation site, where the
# affected field is known; consumers map code → localized caveat) ────────────
FIELD_WARN_EV_MISSING_NET_DEBT = "ev_missing_net_debt"
"""EV (hence EV/EBITDA, EV/Revenue) uncomputable — provider lacked debt/cash."""
FIELD_WARN_SHARES_DERIVED = "shares_derived"
"""shares_outstanding derived as market_cap/price — per-share (EPS, P/E) approximate."""
FIELD_WARN_EV_CROSS_CURRENCY = "ev_cross_currency"
"""EV / EV-multiples / P/E withheld — reporting≠quote currency and FX unavailable,
so a quote-ccy market_cap and reporting-ccy net debt can't form a valid ratio."""


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
    normalization. See ``finrobot.engine.compute.operators.fx_normalize`` for the
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
    # Forward consensus (FY1) — populated per-peer from DataType.FORWARD_ESTIMATES
    # via the red-line leaf compute.operators.forward_estimates.get_forward_financials,
    # which selects the nearest fiscal-year-end ≥ today (NOT rows[0]). forward_eps
    # is analyst-consensus EPS (already core/normalized — analysts strip one-offs),
    # so forward_pe = market_cap / (forward_eps × shares) feeds a forward_comps
    # method that is intentionally SEPARATE from the trailing NOPAT core_pe (one
    # forward caliber on both target and peers). None when no consensus is available
    # → that peer falls back to trailing for the comps median.
    forward_eps: float | None = None
    forward_pe: float | None = None
    market_cap: float
    # None ≠ 0: None means the provider did not report the figure, so EV (and
    # the EV-based multiples) MUST be withheld rather than computed against an
    # assumed-zero net-debt — that fabrication silently poisoned the peer median
    # (a cash-rich peer reported as debt=cash=0 → EV=market_cap). Mirrors the
    # target path in extract_financial_data, which already refuses EV when debt
    # or cash is missing.
    total_debt: float | None = None
    total_cash: float | None = None
    # EV-bridge completeness for peers (mirrors target FinancialData.balance):
    # calculate_ev folds preferred + NCI into a peer's EV when reported, so a peer
    # carrying them does not feed an understated EV/EBITDA into the comps median.
    # None ≠ 0 (not carried). Reporting-currency (FX-scaled with the other balance lines).
    preferred_stock: float | None = None
    noncontrolling_interest: float | None = None
    enterprise_value: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    # Absolute operating income (EBIT) in the reporting currency. calculate_core_pe
    # builds NOPAT from this directly instead of operating_margin × revenue, so a
    # revenue that was XBRL-TTM-reconciled (override_company_with_xbrl) can't drag
    # EBIT to a cross-period margin×revenue product (BUG-017). FX-normalized with
    # the other reporting-currency line items. None → fall back to margin×revenue.
    operating_income: float | None = None
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
    # Multiples that had computable inputs but fell outside the published sanity
    # bounds and were nulled by calculate_multiples (so excluded from medians).
    # Recorded so a thinned peer set is never silent — this is the *real* signal
    # that replaced the tautological range check in validate_peer_comps, which
    # could never fire because the floor had already nulled out-of-range values.
    sanity_drops: list[str] = Field(default_factory=list)


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
    # Peer median of forward P/E (market_cap / FY1 consensus net income, set per
    # peer in _fetch_one_peer). Sparser than trailing — only US issuers with
    # analyst consensus contribute. Feeds the forward_comps valuation method,
    # which pairs it with the target's forward EPS (one forward caliber both sides).
    median_forward_pe: float | None = None

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

    # Finiteness gate for the three fields without ge/le bounds (bounded
    # fields reject NaN for free — NaN fails every comparison). A NaN in
    # revenue_base / net_debt / any growth rate sails through calculate_dcf's
    # guards (NaN comparisons are all False) and ships implied_price=NaN into
    # the aggregation band; JSON bodies accept the NaN literal, so the
    # POST /monte-carlo direct-construction path is live, not theoretical.
    @field_validator("revenue_base", "net_debt")
    @classmethod
    def _reject_non_finite_scalar(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("must be finite — NaN/Inf is not a number, it's missing data")
        return v

    @field_validator("revenue_growth_rates")
    @classmethod
    def _reject_non_finite_growth(cls, v: list[float]) -> list[float]:
        for i, g in enumerate(v):
            if not math.isfinite(g):
                raise ValueError(
                    f"revenue_growth_rates[{i}] must be finite — "
                    "NaN/Inf is not a number, it's missing data"
                )
        return v

    currency: str = Field(
        default="USD",
        description=(
            "ISO 4217 quote currency of the per-share / equity outputs "
            "(``implied_price`` is ``equity_value / shares_outstanding``, a market "
            "quote, so it follows ``FinancialData.quote_currency`` — TWD for TSM, "
            "EUR for SAP). Threaded by ``seed_dcf_inputs`` from the financials "
            "snapshot; ``calculate_dcf`` passes it through to ``DCFResult`` so the "
            "artifact carries a real currency tag and the diff formatter never "
            "has to assume USD. Defaults to USD so direct callers and "
            "JSON-round-tripped legacy artifacts (no ``currency`` key) still "
            "validate — same read-compat precedent as ``ttm_quarter_ends``."
        ),
    )

    assumption_provenance: dict[str, str] = Field(
        default_factory=dict,
        description="Maps assumption field names to their reasoning/source",
    )

    inputs_fetched_at: datetime | None = Field(
        default=None,
        description=(
            "Wall-clock time the market/financial inputs behind this seed were "
            "fetched (= FinancialData.timestamp, the canonical fetch time). "
            "Stamped by seed_dcf_inputs so every surface that prints a DCF/WACC "
            "(REST /dcf-seed, what-if, chat Monte-Carlo, artifacts via "
            "DCFResult.inputs) can show 'inputs as of X' — 门四溯源半. None for "
            "direct construction (user-supplied REST bodies have no fetch time; "
            "never fabricate a now()) and for JSON-round-tripped legacy "
            "artifacts (read-compat, ttm_quarter_ends precedent)."
        ),
    )


class MarketImpliedCheck(BaseModel):
    """Reverse-DCF reality check: what the CURRENT market price implies.

    The forward DCF answers "given my assumptions, what is it worth?". This
    inverts it: "given the market's price, what constant growth (or discount
    rate) is the market implicitly pricing in?" — a Damodaran-style sanity
    check. It is the honest companion to a fair-value point: a DCF mid 60% below
    market is meaningless on its own, but "the market is pricing in 23%/yr
    growth — plausible?" is a checkable, user-understandable statement.

    All fields are COMPUTED (deterministic reverse-DCF), never LLM-narrated.
    Scalars only (no baked prose) so the bilingual UI renders the localized
    sentence and the thesis LLM cites the numbers in the report's language.
    """

    horizon_years: int
    """Explicit high-growth window the implied growth is solved over — matches
    the forward DCF's own projection_years so the two are directly comparable."""
    implied_growth: float | None = None
    """Constant annual revenue growth the market price implies over
    ``horizon_years``. None when the price is unreachable within the solver's
    growth bracket — see ``growth_unreachable``."""
    implied_wacc: float | None = None
    """Discount rate the market price implies under the seeded growth schedule.
    None when unreachable within the WACC bracket."""
    growth_unreachable: bool = False
    """True when NO growth in the solver bracket reaches the market price — the
    single most important signal that the price is NOT growth-explainable
    (option-value stock, e.g. TSLA: even 50% growth implies only ~$65 vs $418).
    When True the product must NOT present a fundamentals point target as the
    headline; the honest output is "priced on optionality the DCF cannot model"."""
    growth_ceiling: float | None = None
    """The solver's max growth tried (e.g. 0.50), for the unreachable narrative
    ("even {ceiling:.0%} growth only implies ${ceiling_price})."""
    ceiling_price: float | None = None
    """Implied price at ``growth_ceiling`` — the highest the DCF can reach. Lets
    the UI/narrative quantify how far the market sits beyond any plausible
    growth (TSLA: $65 ceiling vs $418 market)."""


class MarketImpliedNature(BaseModel):
    """Per-name valuation *nature*, re-solved against the LIVE price — the honest
    cross-name read for the Coverage desk.

    A cross-name *ranking* by implied-growth gap was deliberately rejected: the
    reverse solver fits a FLAT constant growth while the forward DCF projects a
    DECAYING schedule, so a single implied-growth scalar sits systematically
    below the decay-base anchor by an amount that scales with the name's growth
    tier — ranking by that gap ranks "whose growth curve is steepest", not
    "whose expectation is most stretched". What *does* survive that critique is a
    per-name **classification**, which is what this carries:

    * ``fundamental`` — the live price IS explainable by some growth in the
      solver bracket. ``implied_growth`` is the constant annual revenue growth
      the price implies, shown as per-name context (NOT a sortable cross-name
      number — see above).
    * ``option_value`` — no growth in the bracket reaches the price AND that
      verdict survives the most favourable plausible WACC (a band lower). The
      market is pricing optionality no cash-flow model can capture (TSLA-type).
      The robust, deterministic *exclusion* signal — and the moat: a generic LLM
      cannot reproduce it.
    * ``near_ceiling`` — unreachable at the name's own WACC, but a plausibly
      lower WACC rescues it into the solvable range. Flagged WACC-sensitive
      rather than asserting optionality, because the verdict would silently flip
      with the discount-rate assumption (and an unsourceable flip is exactly the
      kind of number this product refuses to ship).

    All fields are COMPUTED (deterministic reverse-DCF), never LLM-narrated.
    """

    kind: Literal["fundamental", "option_value", "near_ceiling"]
    implied_growth: float | None = None
    """Constant annual revenue growth the live price implies (``fundamental``
    only; None on the unreachable paths and when the price sits below even the
    bracket floor)."""
    implied_wacc: float | None = None
    """Discount rate the live price implies under the seeded growth schedule —
    surfaced so the growth read isn't mistaken for assumption-free (a high-beta
    name shows higher implied growth partly via its own higher WACC)."""
    horizon_years: int
    """Explicit window the implied growth is solved over (the source DCF's own
    ``projection_years``), so the number is anchored to a stated horizon."""
    growth_ceiling: float | None = None
    """The solver's max growth tried (``option_value``/``near_ceiling`` only) —
    for the narrative "even {ceiling:.0%} growth implies only ${ceiling_price}"."""
    ceiling_price: float | None = None
    """Implied price at ``growth_ceiling`` — how far the live price sits beyond
    any plausible growth. ``option_value``/``near_ceiling`` only."""


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

    # ISO 4217 quote currency of implied_price / equity_value, threaded from
    # DCFInputs.currency (← FinancialData.quote_currency). Lets the artifact
    # carry a real currency tag so the semantic-diff formatter stamps the right
    # symbol for non-USD issuers instead of assuming "$". Defaults to USD for
    # read-compat with legacy artifacts that predate the field.
    currency: str = "USD"

    # Sensitivity
    sensitivity_table: dict[str, Any] | None = None

    # Reverse-DCF reality check (what the market price implies). None when the
    # caller didn't run it (e.g. no current price available).
    market_implied: MarketImpliedCheck | None = None

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

    # Currency of every absolute monetary field (revenue/ebitda/eps/cash
    # flows…). The extractor normalizes native-reporting ADR history (TSM:
    # TWD) to the quote currency at today's spot before assembly; when FX is
    # unavailable the figures stay native and this tag says so — renderers and
    # LLM prompts must not assume USD. None = currency tags absent upstream
    # (test fakes / legacy rows). Ratios, margins and CAGR are
    # currency-invariant either way.
    currency: str | None = None

    years: list[int]
    revenue: list[float]
    revenue_growth_yoy: list[float | None]
    # cogs / gross_profit are None (not 0.0) for a year whose gross_profit the
    # provider omitted — chiefly no-COGS businesses (banks: fmp_provider sets
    # gross_profit=None). Fabricating cogs = revenue − 0 there would show a bank
    # "COGS = full revenue, gross profit = $0", which is misleading, not missing.
    cogs: list[float | None]
    gross_profit: list[float | None]
    # Margins are None for a year whose numerator the provider omitted — a
    # missing margin is "not reported", distinct from a real 0% (None ≠ 0). The
    # other absolute line items keep the 0.0 fill (all-zero row = missing
    # convention used by dcf_seed._median_ratio).
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
    net_sentiment: float = Field(
        default=0.0,
        description=(
            "Mean expected impact per event (impact × probability × sign), clamped "
            "to [-5, 5]. Mean, not sum — a 30-event news day must not saturate the "
            "scale (see summarize_catalyst_outlook)."
        ),
    )
    category_breakdown: dict[str, int] = Field(default_factory=dict)
    top_positive: list[CatalystEvent] = Field(default_factory=list)
    top_negative: list[CatalystEvent] = Field(default_factory=list)


class ValuationMethod(BaseModel):
    """One valuation method's result range."""

    name: str
    low: float
    mid: float
    high: float
    confidence: float = Field(
        ge=0,
        le=1,
        description=(
            "Method weight in the confidence-weighted price synthesis (NOT prediction accuracy). "
            "A higher value means this method is trusted more in the weighted average; "
            "it does NOT mean '85% chance the target is right'. Based on data quality / "
            "methodology robustness (DCF 0.85, forward comps 0.78 …), not back-tested accuracy."
        ),
    )
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
            "False when ANY of (a) the methods' mids span more than 2x (max/min, the "
            "pairwise-corroboration gate that catches a 2-method disagreement the "
            "median metric is blind to), (b) at least one method deviates > 50% from "
            "the cross-method median (a single outlier in a 3+ method set), OR (c) the "
            "confidence-weighted target / market price ratio falls outside [0.25x, 4x] "
            "(a model-vs-market divergence ORTHOGONAL to cross-method agreement — the "
            "Amazon-1999 / TSLA case where the methods may or may not corroborate yet all "
            "sit far from a market pricing option value the models can't capture; the "
            "warning text states the actual per-method spread. Symmetric in log-space, "
            "unlike an upside%%). "
            "In any case the weighted target MUST NOT be published as a headline "
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
    moic: float | None = Field(
        default=None,
        description="MOIC (×). 0 = total loss (equity wiped at exit). "
        "None = undefined (non-positive entry equity: debt ≥ entry EV — impossible structure).",
    )
    irr: float | None = Field(
        default=None,
        description="Annualized IRR (decimal). -1.0 = total loss (equity wiped at exit). "
        "None = undefined (non-positive entry equity — impossible LBO structure).",
    )
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
    eps_actual: float | None  # None when provider omits the value (None ≠ 0)
    eps_estimated: float | None
    eps_surprise_pct: float | None  # (actual-est)/|est|×100; None if est==0 or input missing
    eps_direction: str  # "beat" | "miss" | "inline" | "n/a" (n/a = undefined, est == 0)
    revenue_actual: float | None  # None ≠ 0: missing revenue stays None, never fabricated $0
    revenue_estimated: float | None
    revenue_surprise_pct: float | None  # None if est==0 or input missing (undefined surprise)
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

    # Same finiteness gate as DCFInputs.revenue_growth_rates (the unbounded-
    # list sibling): a NaN growth rate slips past calculate_ddm's < -1 guard
    # (NaN comparisons are False) and poisons the dividend projection.
    @field_validator("dividend_growth_rates")
    @classmethod
    def _reject_non_finite_growth(cls, v: list[float]) -> list[float]:
        for i, g in enumerate(v):
            if not math.isfinite(g):
                raise ValueError(
                    f"dividend_growth_rates[{i}] must be finite — "
                    "NaN/Inf is not a number, it's missing data"
                )
        return v

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
    confidence: float = Field(
        ge=0,
        le=1,
        description=(
            "Method weight in the confidence-weighted price synthesis (NOT prediction accuracy). "
            "Used internally as the weight in weighted_price = Σ(mid×wt)/Σ(wt). "
            "Does not represent a probability of the target being correct."
        ),
    )
    source: str = Field(description="Human-readable provenance, e.g. 'implied_price ± 20%'")
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
    # Forward-estimates provenance — tells the analyst WHICH forecast fiscal year
    # drives comps_pe / ev_ebitda / p_fcf rows (e.g. "2026-09-30"), where the
    # numbers came from, and how much to trust them. None when forward data was
    # unavailable (those rows are absent from `methods` anyway).
    forward_fiscal_period: str | None = None
    forward_confidence: str | None = None
    forward_source: str | None = None
